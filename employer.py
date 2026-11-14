"""Employer side: vague job description / task list -> clarifying questions ->
concrete prioritised tasks -> ESCO skills ready for the recruiter to rank.

Flow (PLAN.md, employer steps 1-3):
  1. clarify()     Gemini looks for what is vague and asks up to 4 questions per round
                   (in the employer's language). Stops when tasks are concrete enough.
  2. build_spec()  Gemini turns text + answers into concrete tasks, each with a priority
                   (must_have / learnable / nice_to_have), its source, and ESCO-style
                   skill phrases. Flags requirements that may exclude people unnecessarily.
  3. map_spec()    Each skill phrase goes through the same retrieve + Decisions selection
                   as map_skills.py. Every ESCO skill keeps the tasks and priority behind it.

Each step is stateless, so a web backend can call them one request at a time.

Usage:
    .venv/bin/python employer.py "We need someone for our web stuff and some customer things"
    .venv/bin/python employer.py --file job_ad.txt
    .venv/bin/python employer.py --file job_ad.txt --no-questions --json

From code:
    emp = EmployerFlow()
    c = emp.clarify(text)                                  # -> questions (or is_clear_enough)
    qa = [QA(question=q.question, answer="...") for q in c.questions]
    spec = emp.build_spec(text, qa)                        # -> JobSpec (tasks, flags)
    skills = emp.map_spec(spec)                            # -> ESCO skills with priority + tasks
"""

import argparse
import json
import sys
from typing import Literal

from pydantic import BaseModel, Field

from map_skills import SkillMapper, Statement

MAX_QUESTIONS_PER_ROUND = 4
MAX_ROUNDS = 2
PRIORITY_ORDER = {"must_have": 0, "learnable": 1, "nice_to_have": 2}


# ---------- Schemas ----------

class ClarifyingQuestion(BaseModel):
    question: str = Field(description="One short, concrete question, in the same language as the employer's text.")
    why: str = Field(description="One short sentence on what is unclear, in the same language as the employer's text.")
    example_answers: list[str] = Field(description="2-3 short example answers that show the level of detail wanted.")


class Clarification(BaseModel):
    understood_so_far: str = Field(description="2-3 sentence summary of the role as understood so far, in the employer's language.")
    is_clear_enough: bool = Field(description="True if the concrete tasks are clear enough to identify the needed skills.")
    questions: list[ClarifyingQuestion] = Field(description="0-4 questions. Empty if is_clear_enough.")


class QA(BaseModel):
    question: str
    answer: str


class Task(BaseModel):
    task: str = Field(description="Concrete task in English: what the person will actually do, e.g. 'Fix bugs reported by customers in the React web shop'.")
    priority: Literal["must_have", "learnable", "nice_to_have"] = Field(
        description="must_have: needed from day one. learnable: can be learned within ~3 months on the job. nice_to_have: a bonus.")
    source: str = Field(description="The exact quote from the job text or the employer's answer that this task comes from, verbatim, in the original language.")
    skills: list[str] = Field(description="1-4 short ESCO-style skill phrases in English needed for this task (verb + object, e.g. 'debug software', 'use JavaScript', 'gather user requirements'). Name specific tools/languages as separate phrases.")


class Flag(BaseModel):
    requirement: str = Field(description="The requirement as written.")
    concern: str = Field(description="Why it may exclude suitable candidates unnecessarily, and what to ask or change. In English.")


class JobSpec(BaseModel):
    title: str = Field(description="A plain job title in English.")
    summary: str = Field(description="2-3 sentence summary of the role in English, focused on what the person will do.")
    tasks: list[Task]
    flags: list[Flag] = Field(description="Requirements worth challenging. Empty if none.")


# ---------- Prompts ----------

CLARIFY_PROMPT = f"""You help an employer describe a job clearly before a recruitment event.
Employers often write vague or buzzword-heavy descriptions ("rockstar developer", "help with marketing stuff").
Your goal: understand the concrete TASKS the new hire will do, so their skills can be identified.

Read the employer's text (and any earlier questions and answers). Decide whether the concrete tasks are clear.
If not, ask up to {MAX_QUESTIONS_PER_ROUND} questions that would clarify the most important gaps. Good questions ask about:
- what the person must have delivered or achieved after 3 / 6 / 12 months
- the concrete tasks of a normal week, and who they work with (customers, team, other departments)
- tools, technologies or methods actually used
- which requirements are truly needed from day one vs. learnable on the job in ~3 months
- whether a stated language requirement (e.g. Finnish) is needed for the actual work, or only nice to have

Rules:
- Never ask about something already answered in the text or earlier answers.
- Each question must be answerable in 1-2 sentences by a busy hiring manager. No compound questions.
- Never ask about age, gender, nationality, family, health or appearance.
- Write the questions in the same language as the employer's text.
- Set is_clear_enough=true (and return no questions) when you could list the concrete tasks and the skills they need."""

SPEC_PROMPT = """You turn an employer's job description (plus their answers to clarifying questions) into a concrete job spec.

tasks:
- List the concrete tasks the person will do. Each task: one sentence, specific, in English.
- Derive tasks from what the employer actually said. Do not invent duties a typical job of this kind might have.
- priority: "must_have" only if the text or answers say or clearly imply it is needed from day one.
  Use "learnable" if the employer said it can be learned, or it is a tool/method a competent person picks up in ~3 months.
  Use "nice_to_have" for bonuses ("is a plus", "ideally").
- skills: 1-4 short ESCO-style English phrases per task. Separate specific technologies/languages
  into their own phrases, as they are separate ESCO entries. ESCO rarely lists specific products or
  frameworks, so for each one also name the generic technology or category it belongs to
  (e.g. React -> "use JavaScript framework", "use JavaScript"; Shopify -> "use e-commerce systems";
  Jira -> "use project management software").
- Include language skills (e.g. "Finnish") as their own task only if the language is genuinely used in the work.
- source: verbatim quote (original language) from the text or from an answer.

flags: requirements that may exclude suitable candidates without being needed for the tasks, e.g.
- native or fluent Finnish when the tasks and answers suggest English is enough
- degree requirements unrelated to the tasks
- years-of-experience thresholds that could be replaced by a demonstrated skill
- anything about age, gender, nationality, family, health or appearance (always flag; never turn into a task)"""


# ---------- Flow ----------

def format_input(text, qa):
    parts = [f"Employer's text:\n{text}"]
    if qa:
        parts.append("Clarifying questions and the employer's answers:")
        for item in qa:
            parts.append(f"Q: {item.question}\nA: {item.answer or '(no answer)'}")
    return "\n\n".join(parts)


class EmployerFlow:
    def __init__(self, mapper=None):
        self.mapper = mapper or SkillMapper()

    def clarify(self, text, qa=()):
        """Step 1: what is still unclear? Returns a Clarification."""
        result = self.mapper.generate(CLARIFY_PROMPT, format_input(text, qa), Clarification)
        result.questions = result.questions[:MAX_QUESTIONS_PER_ROUND]
        if result.is_clear_enough:
            result.questions = []
        return result

    def build_spec(self, text, qa=()):
        """Step 2: text + answers -> JobSpec with concrete, prioritised tasks."""
        return self.mapper.generate(SPEC_PROMPT, format_input(text, qa), JobSpec)

    def map_spec(self, spec):
        """Step 3: JobSpec -> ESCO skills, each with its priority and the tasks behind it.

        Sorted for the recruiter's ranking view: must_have first, then by probability."""
        statements, task_of = [], []
        for t_idx, task in enumerate(spec.tasks):
            for phrase in task.skills:
                statements.append(Statement(esco_phrase=phrase, evidence=task.task))
                task_of.append(t_idx)
        if not statements:
            return []

        candidates = self.mapper.retrieve(statements)
        # The skill phrases were already clarified with the employer, so they are authoritative.
        picks = self.mapper.select_skills(statements, candidates, mode="requirement")

        by_uri = {}
        for s_idx, skill, confidence in picks:
            task = spec.tasks[task_of[s_idx]]
            entry = by_uri.setdefault(skill["uri"], {
                "uri": skill["uri"],
                "label": skill["label"],
                "skillType": skill["skillType"],
                "reuseLevel": skill["reuseLevel"],
                "priority": task.priority,
                "confidence": confidence,
                "probability": skill.get("probability"),
                "tasks": [],
                "sources": [],
            })
            # A skill needed by several tasks takes the strongest priority among them.
            if PRIORITY_ORDER[task.priority] < PRIORITY_ORDER[entry["priority"]]:
                entry["priority"] = task.priority
            if confidence == "high":
                entry["confidence"] = "high"
            if skill.get("probability") is not None:
                entry["probability"] = max(entry["probability"] or 0, skill["probability"])
            if task.task not in entry["tasks"]:
                entry["tasks"].append(task.task)
            if task.source not in entry["sources"]:
                entry["sources"].append(task.source)

        return sorted(
            by_uri.values(),
            key=lambda e: (PRIORITY_ORDER[e["priority"]], e["confidence"] != "high", -(e["probability"] or 0)),
        )

    def run(self, text, ask=None, max_rounds=MAX_ROUNDS):
        """Whole flow. `ask(clarification) -> list[QA]` collects answers (None = skip questions).
        Returns (qa, spec, skills)."""
        qa = []
        if ask:
            for _ in range(max_rounds):
                clarification = self.clarify(text, qa)
                if clarification.is_clear_enough or not clarification.questions:
                    break
                answers = ask(clarification)
                if not any(a.answer for a in answers):
                    break  # employer skipped everything
                qa.extend(answers)
        spec = self.build_spec(text, qa)
        return qa, spec, self.map_spec(spec)


# ---------- CLI ----------

def ask_in_terminal(clarification):
    print(f"\nUnderstood so far: {clarification.understood_so_far}\n")
    answers = []
    for i, q in enumerate(clarification.questions, 1):
        print(f"Q{i}: {q.question}")
        print(f"     ({q.why} e.g. {' / '.join(q.example_answers)})")
        try:
            answer = input("     > ").strip()
        except EOFError:
            answer = ""
        answers.append(QA(question=q.question, answer=answer))
    return answers


def print_result(spec, skills):
    print(f"\n=== {spec.title} ===\n{spec.summary}\n")
    print("Tasks:")
    for t in spec.tasks:
        print(f"  [{t.priority:<12}] {t.task}")
        print(f"                   skills: {', '.join(t.skills)}")
    if spec.flags:
        print("\nRequirements worth challenging:")
        for f in spec.flags:
            print(f"  ! {f.requirement}: {f.concern}")
    print("\nESCO skills (for the recruiter to rank):")
    for s in skills:
        prob = f"p={s['probability']:.2f}" if s.get("probability") is not None else s["confidence"]
        print(f"  [{s['priority']:<12} {prob}] {s['label']}  ({s['skillType']})")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", help="job description or task list (or use --file / stdin)")
    parser.add_argument("--file", help="read the job text from a file")
    parser.add_argument("--no-questions", action="store_true", help="skip clarifying questions")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    args = parser.parse_args()

    if args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()
        sys.stdin = open("/dev/tty")  # text came from a pipe; read answers from the keyboard

    flow = EmployerFlow()
    qa, spec, skills = flow.run(text, ask=None if args.no_questions else ask_in_terminal)

    if args.json:
        print(json.dumps({
            "qa": [x.model_dump() for x in qa],
            "spec": spec.model_dump(),
            "skills": skills,
        }, ensure_ascii=False, indent=2))
    else:
        print_result(spec, skills)


if __name__ == "__main__":
    main()
