"""Applicant side: self-declared ESCO skill profile.

Design rule (EU AI Act, Annex III 4(a)): our AI never evaluates the applicant.
  - AI only SUGGESTS skills from the applicant's own text; the applicant confirms every one.
  - The applicant chooses their skills and allocates points themselves (self-declaration).
  - Validation questions are generated from the ESCO skill alone (label + description),
    never from applicant data, and cached so every applicant gets the same question per skill.
  - Validation ANSWERS are stored verbatim and shown to recruiters only.
    They are NEVER sent to an LLM. Nothing in this module passes them to one.

Flow (PLAN.md, applicant steps 1-4):
  1. suggest_skills(text)        AI suggestions from CV / LinkedIn / free text (map_skills.py)
  2. search_skills(query)        applicant adds skills the AI missed (embedding search)
  3. allocation {uri: points}    applicant spends POINT_BUDGET points on <= MAX_SKILLS skills (points.py)
  4. validation_questions(...)   one question per chosen skill; the applicant answers in their own words
  5. make_applicant_profile()    confirmed skills + allocation + questions + answers -> ApplicantProfile

Usage:
    .venv/bin/python applicant.py --file cv.txt --out profile.json
    .venv/bin/python applicant.py "I kept the books for my family's shop..."
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from map_skills import SkillMapper
from points import POINT_BUDGET, allocate_in_terminal, check_allocation, points_bar

ROOT = Path(__file__).resolve().parent
QUESTION_CACHE = ROOT / "data" / "validation_questions.json"

MAX_SKILLS = 5


# ---------- Profile (what gets stored and shown to recruiters) ----------

class SkillClaim(BaseModel):
    uri: str
    label: str
    skillType: str
    origin: Literal["suggested", "added"] = Field(description="AI suggestion confirmed by the applicant, or added by them.")
    points: int = Field(ge=1, description="Self-assessed expertise, from the applicant's point budget.")
    validation_question: str = ""
    # The applicant's own words. Shown verbatim to recruiters. NEVER sent to an LLM.
    validation_answer: str = ""


class ApplicantProfile(BaseModel):
    # Deliberately no name, photo, age or nationality: recruiters see skills first (blind first contact).
    skills: list[SkillClaim]

    @model_validator(mode="after")
    def check_budget(self):
        check_allocation([s.points for s in self.skills], POINT_BUDGET, MAX_SKILLS)
        if len({s.uri for s in self.skills}) != len(self.skills):
            raise ValueError("each skill can be chosen only once")
        return self


def make_applicant_profile(skills, allocation, questions, answers=None):
    """Build the profile from what the applicant decided. Mirror of employer.make_job_profile.

    skills:     the confirmed skills, each a dict with uri, label, skillType and
                origin ("suggested" or "added")
    allocation: {uri: points}. Skills with 0 points are dropped.
    questions:  {uri: validation question}, from ApplicantFlow.questions_for()
    answers:    {uri: the applicant's own words}. Stored verbatim. NEVER sent to an LLM.

    Raises ValueError if the allocation breaks the rules (budget, max skills, unknown skill)."""
    answers = answers or {}
    by_uri = {s["uri"]: s for s in skills}
    unknown = set(allocation) - set(by_uri)
    if unknown:
        raise ValueError(f"points given to skills that were not confirmed: {sorted(unknown)}")
    claims = [
        SkillClaim(
            uri=uri,
            label=by_uri[uri]["label"],
            skillType=by_uri[uri]["skillType"],
            origin=by_uri[uri].get("origin", "suggested"),
            points=p,
            validation_question=questions.get(uri, ""),
            validation_answer=answers.get(uri, ""),
        )
        for uri, p in allocation.items() if p > 0
    ]
    return ApplicantProfile(skills=claims)


# ---------- Validation questions (generated from the skill only) ----------

class _Question(BaseModel):
    index: int
    question: str


class _Questions(BaseModel):
    questions: list[_Question]


QUESTION_PROMPT = """You write one validation question per ESCO skill for a job matching event.
Job seekers answer the question in their own words, and a human recruiter reads the answer.

Each question must:
- ask for ONE concrete example of using the skill: what the situation was, what they did, what came of it
- be answerable in 2-4 sentences by someone who has the skill at any level, including from informal,
  unpaid or volunteer work (do not assume a job title, employer or formal education)
- be plain and neutral, with no jargon beyond the skill's own name, max ~25 words
- not ask about age, nationality, family, health or other personal characteristics

Write the questions in {language}."""


def _load_cache():
    try:
        return json.loads(QUESTION_CACHE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def validation_questions(skills, mapper, language="English"):
    """One question per skill, keyed by URI. Input is ESCO skill data ONLY, so no applicant data
    reaches the LLM. Cached in data/validation_questions.json: same skill -> same question."""
    cache = _load_cache()
    key = lambda s: f"{language}|{s['uri']}"
    missing = [s for s in skills if key(s) not in cache]

    if missing:
        lines = [f"{i}. {s['label']} ({s['skillType']}): {s.get('description', '')[:300]}"
                 for i, s in enumerate(missing)]
        result = mapper.generate(QUESTION_PROMPT.format(language=language), "\n".join(lines), _Questions)
        for q in result.questions:
            if 0 <= q.index < len(missing):
                cache[key(missing[q.index])] = q.question
        QUESTION_CACHE.parent.mkdir(exist_ok=True)
        QUESTION_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    fallback = "Describe one situation where you used this skill: what you did and what came of it."
    return {s["uri"]: cache.get(key(s), fallback) for s in skills}


# ---------- AI suggestions and manual search ----------

class ApplicantFlow:
    def __init__(self, mapper=None):
        self.mapper = mapper or SkillMapper()

    def suggest_skills(self, text):
        """Step 1: suggestions only. The applicant must confirm each one."""
        return self.mapper.map_text(text, role="applicant")

    def search_skills(self, query, k=5):
        """Step 2: let the applicant find and add skills the AI missed."""
        return self.mapper.index.search(query, k=k)

    def questions_for(self, skills, language="English"):
        """Step 4: questions from skill data only (see validation_questions)."""
        meta = {s["uri"]: s for s in self.mapper.index.skills}
        return validation_questions([meta[s["uri"]] for s in skills], self.mapper, language)


# ---------- CLI ----------

def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def parse_numbers(answer, n):
    if answer.lower() == "all":
        return list(range(n))
    picked = []
    for part in answer.replace(",", " ").split():
        if part.isdigit() and 1 <= int(part) <= n and int(part) - 1 not in picked:
            picked.append(int(part) - 1)
    return picked


def run_cli(flow, text, language):
    # 1. Suggestions, confirmed by the applicant
    suggestions = flow.suggest_skills(text) if text.strip() else []
    confirmed = []
    if suggestions:
        print("\nSkills we found in your text. These are only suggestions: keep the ones that are true.\n")
        for i, s in enumerate(suggestions, 1):
            print(f"  {i:>2}. {s['label']}")
            print(f"      from: \"{s['evidence'][0]}\"")
        keep = parse_numbers(ask("\nWhich do you keep? (e.g. 1 3 4, 'all', or Enter for none) > "), len(suggestions))
        confirmed = [{**suggestions[i], "origin": "suggested"} for i in keep]

    # 2. Add missing skills via search
    while True:
        query = ask("\nSearch for a skill to add (Enter to continue) > ")
        if not query:
            break
        results = flow.search_skills(query)
        for i, r in enumerate(results, 1):
            print(f"  {i}. {r['label']}  - {r['description'][:90]}")
        for i in parse_numbers(ask("Add which? > "), len(results)):
            if results[i]["uri"] not in {c["uri"] for c in confirmed}:
                confirmed.append({**results[i], "origin": "added"})

    if not confirmed:
        sys.exit("No skills chosen.")

    # 3. Choose skills by spending points on them
    allocation = allocate_in_terminal(
        [c["label"] for c in confirmed], POINT_BUDGET, MAX_SKILLS,
        intro="Where are you strongest? Put more points on the skills you are best at.",
    )
    chosen = [confirmed[i] for i in allocation]
    points_by_uri = {confirmed[i]["uri"]: p for i, p in allocation.items()}

    # 4. Validation questions (skill data only) and the applicant's answers (never sent to an LLM)
    questions = flow.questions_for(chosen, language)
    print("\nOne question per skill. Recruiters read your answers as you write them; no AI evaluates them.\n")
    answers = {}
    for c in chosen:
        print(f"{c['label']}: {questions[c['uri']]}")
        answers[c["uri"]] = ask("  > ")
    return make_applicant_profile(confirmed, points_by_uri, questions, answers)


def print_recruiter_card(profile):
    print("\n=== Skill card (as recruiters see it) ===")
    for s in sorted(profile.skills, key=lambda s: -s.points):
        print(f"\n{points_bar(s.points)}  {s.points:>2}  {s.label}")
        print(f"  Q: {s.validation_question}")
        print(f"  A: {s.validation_answer or '(not answered)'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", help="CV / LinkedIn / free text (or use --file / stdin)")
    parser.add_argument("--file", help="read the text from a file")
    parser.add_argument("--language", default="English", help="language of the validation questions")
    parser.add_argument("--out", help="save the profile as JSON")
    args = parser.parse_args()

    if args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()
        sys.stdin = open("/dev/tty")  # text came from a pipe; read choices from the keyboard

    profile = run_cli(ApplicantFlow(), text, args.language)
    print_recruiter_card(profile)
    if args.out:
        Path(args.out).write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
