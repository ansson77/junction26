"""Free text (CV, job ad, task list) -> ESCO skills, with evidence.

Pipeline:
  1. extract  (Gemini)    text -> short ESCO-style English statements + the quote they came from
  2. retrieve (embedding) each statement -> top-k candidate skills from search.py
  3. select   (Gemini Decisions API) yes/no probability for every (statement, candidate) pair;
                          keep those >= 0.5 (or --selector llm for a single generateContent call)

Usage:
    .venv/bin/python map_skills.py "I kept the books for my family's shop for 6 years"
    .venv/bin/python map_skills.py --file cv.txt --role applicant
    .venv/bin/python map_skills.py --file job_ad.txt --role employer --json

From code:
    from map_skills import SkillMapper
    SkillMapper().map_text(text, role="applicant")

Needs GEMINI_API_KEY in the environment. GEMINI_MODEL overrides the model.
"""

import argparse
import json
import os
import sys
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from search import SkillIndex

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
CANDIDATES_PER_STATEMENT = 15

# Selection via the Decisions API (calibrated yes/no probabilities).
# Needs google-genai >= 3.2 and the v1beta API version.
DECISIONS_MODEL = "gemini-decision-1"
HIGH_THRESHOLD = 0.8     # probability >= this -> "high"
MEDIUM_THRESHOLD = 0.5   # probability >= this -> "medium", below -> dropped
MAX_PICKS_PER_STATEMENT = 3


# ---------- Structured output schemas ----------

class Statement(BaseModel):
    esco_phrase: str = Field(description="Short skill phrase in formal English, ESCO style: verb + object, e.g. 'perform bookkeeping', 'design ETL data pipelines'. Max ~8 words.")
    evidence: str = Field(description="Exact quote from the input text that supports this skill, copied verbatim in the original language.")


class Extraction(BaseModel):
    statements: list[Statement]


class Pick(BaseModel):
    statement_id: int
    candidate_id: str
    confidence: Literal["high", "medium"]


class Selection(BaseModel):
    picks: list[Pick]


# ---------- Prompts ----------

EXTRACT_PROMPT = {
    "applicant": """You extract skills from a job seeker's text (CV, LinkedIn profile, or free description).
The text may be in any language and may describe paid, unpaid, informal or volunteer work.

For every distinct skill or area of knowledge the person demonstrates, output:
- esco_phrase: a short skill phrase in formal English, in the style of the ESCO skills taxonomy
  (verb + object, e.g. "perform bookkeeping", "handle customer complaints", "use Python").
  Translate if needed. One skill per statement - split compound sentences.
- evidence: the exact quote from the text that shows it, verbatim, in the original language.

Rules:
- Only skills supported by the text. Do not infer skills that are not evidenced.
- Do not skip modestly described skills ("helped with", "sometimes did") - include them.
- Include soft/transversal skills when there is concrete evidence (e.g. "trained 3 new hires").
- Ignore personal details (name, age, nationality, photo, contact info).""",

    "employer": """You extract required skills from an employer's text (job ad, or a free list of tasks
the new hire will do). The text may be in any language.

For every distinct skill or area of knowledge the work requires, output:
- esco_phrase: a short skill phrase in formal English, in the style of the ESCO skills taxonomy
  (verb + object, e.g. "develop web applications", "manage project budgets", "use Python").
  Translate if needed. One skill per statement - split compound requirements.
- evidence: the exact quote from the text that the requirement comes from, verbatim, in the original language.

Rules:
- Prefer skills implied by concrete tasks over generic buzzwords ("rockstar", "team player")
  unless the text gives concrete evidence for them.
- Ignore requirements about personal characteristics (age, nationality, gender, appearance).""",
}

SELECT_PROMPT = """You map skill statements to the ESCO skills taxonomy.

For each statement you get a list of candidate ESCO skills (found by similarity search, so many are
wrong: they may share words but mean something else). Pick the candidates that genuinely describe
the same skill as the statement, given its evidence.

Rules:
- Pick 0-3 candidates per statement. Picking none is correct when nothing fits.
- confidence "high": the candidate clearly is this skill. "medium": closely related / broader skill that still applies.
- Do not pick candidates that only share words (e.g. oil "pipelines" for data pipelines).
- Only use candidate_id values that appear under that statement."""


# ---------- Pipeline ----------

class SkillMapper:
    def __init__(self, model=DEFAULT_MODEL, index=None, selector="decisions"):
        if not os.environ.get("GEMINI_API_KEY"):
            raise SystemExit("GEMINI_API_KEY is not set.")
        # v1beta: required for the Decisions API (generateContent works there too).
        self.client = genai.Client(http_options={"api_version": "v1beta"})
        self.model = model
        self.selector = selector  # "decisions" or "llm"
        self.index = index or SkillIndex()

    def generate(self, system, user, schema):
        response = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0,
            ),
        )
        return schema.model_validate_json(response.text)

    def extract_statements(self, text, role="applicant"):
        """Step 1: text -> [Statement]."""
        result = self.generate(EXTRACT_PROMPT[role], text, Extraction)
        return result.statements

    def retrieve(self, statements, k=CANDIDATES_PER_STATEMENT):
        """Step 2: [Statement] -> one candidate list per statement."""
        return self.index.search_many([s.esco_phrase for s in statements], k=k)

    def select_skills(self, statements, candidates, mode="evidence"):
        """Step 3. Returns [(statement_idx, skill, confidence)].

        mode="evidence":    the evidence quote must show the skill (applicant claims, raw job ads).
        mode="requirement": the statement phrase is an already-clarified requirement and is
                            authoritative; the evidence (task) is only context (employer.py)."""
        if self.selector == "decisions":
            return self.select_skills_decisions(statements, candidates, mode)
        return self.select_skills_llm(statements, candidates)

    def select_skills_decisions(self, statements, candidates, mode="evidence"):
        """Step 3 via the Gemini Decisions API: one independent yes/no question per
        (statement, candidate) pair, answered with a calibrated probability.
        A statement can match several skills or none."""
        if mode == "requirement":
            header = "Required skills for a job, each with the task it is needed for:"
            ask = ("Is this ESCO skill or knowledge the same as the required skill (or the core knowledge it is built on), "
                   "in the context of the task?")
            criteria = {
                "true_description": "Yes: it names the same skill, technology or knowledge as the requirement, or the core knowledge it is built on.",
                "false_description": "No: it is a different skill, technology or field (even if it shares words), or a specialisation for a different context than the task.",
            }
            context = "task"
        else:
            header = "Skill statements extracted from a text:"
            ask = ("Based on the statement and its evidence, does the person have (or does the job require) "
                   "this ESCO skill or knowledge?")
            criteria = {
                "true_description": "Yes: the evidence directly shows this exact skill, or the core knowledge it is built on. A recruiter reading the evidence would agree without guessing.",
                "false_description": "No: it is a different skill or field (even if it shares words, e.g. oil pipelines vs data pipelines), a narrower specialisation for a different context (e.g. 'train crew members' for training office staff), or merely plausible rather than shown.",
            }
            context = "evidence"

        shared_input = header + "\n" + "\n".join(
            f'{i}. "{s.esco_phrase}" ({context}: "{s.evidence}")' for i, s in enumerate(statements)
        )
        questions, keys = {}, {}
        for i, (stmt, cands) in enumerate(zip(statements, candidates)):
            for j, c in enumerate(cands):
                key = f"s{i}_c{j}"
                keys[key] = (i, j)
                questions[key] = {
                    "type": "noul",
                    "instructions": (
                        f'Statement {i}: "{stmt.esco_phrase}" ({context}: "{stmt.evidence}").\n'
                        f'ESCO {"knowledge item" if c["skillType"] == "knowledge" else "skill"}: '
                        f'"{c["label"]}": {c["description"][:300]}\n'
                        + ask
                    ),
                    "criteria": criteria,
                }

        # Max 1,000 questions per request.
        probs = {}
        items = list(questions.items())
        for start in range(0, len(items), 1000):
            response = self.client.decisions.create(
                model=DECISIONS_MODEL,
                input=shared_input,
                questions=dict(items[start:start + 1000]),
            )
            for key, answer in response.answers.items():
                probs[key] = answer.noul

        picks = []
        for i in range(len(statements)):
            scored = sorted(
                ((probs[k], j) for k, (si, j) in keys.items() if si == i and k in probs),
                reverse=True,
            )
            for p, j in scored[:MAX_PICKS_PER_STATEMENT]:
                if p >= MEDIUM_THRESHOLD:
                    skill = {**candidates[i][j], "probability": round(p, 3)}
                    picks.append((i, skill, "high" if p >= HIGH_THRESHOLD else "medium"))
        return picks

    def select_skills_llm(self, statements, candidates):
        """Step 3 via generateContent: one Gemini call that picks candidates for all statements."""
        blocks = []
        for i, (stmt, cands) in enumerate(zip(statements, candidates)):
            lines = [f'Statement {i}: "{stmt.esco_phrase}"', f'  Evidence: "{stmt.evidence}"', "  Candidates:"]
            for j, c in enumerate(cands):
                desc = c["description"][:200]
                lines.append(f"    {i}.{j}: {c['label']} [{c['skillType']}] - {desc}")
            blocks.append("\n".join(lines))

        result = self.generate(SELECT_PROMPT, "\n\n".join(blocks), Selection)

        picks = []
        for p in result.picks:
            # Validate: the id must exist under that statement, so the model cannot invent skills.
            try:
                s_idx, c_idx = (int(x) for x in p.candidate_id.split("."))
            except ValueError:
                continue
            if s_idx != p.statement_id or not (0 <= s_idx < len(candidates)) or not (0 <= c_idx < len(candidates[s_idx])):
                continue
            picks.append((s_idx, candidates[s_idx][c_idx], p.confidence))
        return picks

    def map_text(self, text, role="applicant"):
        """Full pipeline. Returns one entry per ESCO skill, with all evidence that supports it."""
        return self.run(text, role)[2]

    def run(self, text, role="applicant"):
        """Full pipeline, also returning intermediate steps: (statements, candidates, results)."""
        statements = self.extract_statements(text, role)
        if not statements:
            return [], [], []
        candidates = self.retrieve(statements)
        picks = self.select_skills(statements, candidates)

        by_uri = {}
        for s_idx, skill, confidence in picks:
            entry = by_uri.setdefault(skill["uri"], {
                "uri": skill["uri"],
                "label": skill["label"],
                "skillType": skill["skillType"],
                "reuseLevel": skill["reuseLevel"],
                "confidence": confidence,
                "probability": skill.get("probability"),  # only with the decisions selector
                "statements": [],
                "evidence": [],
            })
            if confidence == "high":
                entry["confidence"] = "high"
            if skill.get("probability") is not None:
                entry["probability"] = max(entry["probability"] or 0, skill["probability"])
            st = statements[s_idx]
            if st.esco_phrase not in entry["statements"]:
                entry["statements"].append(st.esco_phrase)
            if st.evidence not in entry["evidence"]:
                entry["evidence"].append(st.evidence)

        order = {"high": 0, "medium": 1}
        results = sorted(by_uri.values(), key=lambda e: (order[e["confidence"]], -(e["probability"] or 0)))
        return statements, candidates, results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", help="text to map (or use --file / stdin)")
    parser.add_argument("--file", help="read text from a file")
    parser.add_argument("--role", choices=["applicant", "employer"], default="applicant")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--selector", choices=["decisions", "llm"], default="decisions",
                        help="step 3: Decisions API probabilities (default) or a generateContent call")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    parser.add_argument("--debug", action="store_true", help="also print statements and candidates")
    args = parser.parse_args()

    if args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    mapper = SkillMapper(model=args.model, selector=args.selector)

    statements, candidates, results = mapper.run(text, args.role)

    if args.debug:
        for i, (s, cands) in enumerate(zip(statements, candidates)):
            print(f"[{i}] {s.esco_phrase}  <-  \"{s.evidence}\"")
            for c in cands[:5]:
                print(f"      {c['score']:.3f} {c['label']}")
        print()

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for r in results:
        prob = f" p={r['probability']:.2f}" if r.get("probability") is not None else ""
        print(f"[{r['confidence']:<6}{prob}] {r['label']}  ({r['skillType']}, {r['reuseLevel']})")
        for e in r["evidence"]:
            print(f"           \"{e}\"")


if __name__ == "__main__":
    main()
