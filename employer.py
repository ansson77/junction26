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
  4. make_job_profile()  The recruiter spends POINT_BUDGET points on the skills that matter
                   most (points.py). Skills with 0 points are dropped. -> JobProfile

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

from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from map_skills import SkillMapper, Statement
from points import POINT_BUDGET, allocate_in_terminal, check_allocation, points_bar

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


# ---------- Job profile (what gets stored and matched; mirror of applicant.ApplicantProfile) ----------

class RequiredSkill(BaseModel):
    uri: str
    label: str
    skillType: str
    priority: Literal["must_have", "learnable", "nice_to_have"]
    points: int = Field(ge=1, description="How much this skill matters for the job, from the employer's point budget.")
    tasks: list[str] = Field(default_factory=list, description="The tasks that need this skill.")


class JobProfile(BaseModel):
    title: str
    summary: str
    tasks: list[Task]
    flags: list[Flag]
    skills: list[RequiredSkill]

    @model_validator(mode="after")
    def check_budget(self):
        check_allocation([s.points for s in self.skills], POINT_BUDGET)
        if len({s.uri for s in self.skills}) != len(self.skills):
            raise ValueError("each skill can be chosen only once")
        return self


def make_job_profile(spec, skills, allocation):
    """spec: JobSpec, skills: map_spec() output, allocation: {uri: points}.
    Skills with 0 points are dropped. Raises ValueError if the allocation breaks the rules."""
    by_uri = {s["uri"]: s for s in skills}
    unknown = set(allocation) - set(by_uri)
    if unknown:
        raise ValueError(f"unknown skills: {sorted(unknown)}")
    required = [
        RequiredSkill(uri=uri, label=by_uri[uri]["label"], skillType=by_uri[uri]["skillType"],
                      priority=by_uri[uri]["priority"], points=p, tasks=by_uri[uri]["tasks"])
        for uri, p in allocation.items() if p > 0
    ]
    return JobProfile(title=spec.title, summary=spec.summary, tasks=spec.tasks, flags=spec.flags, skills=required)


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
def allocate_job_points(skills):
    """Terminal: the recruiter spends POINT_BUDGET points on the mapped skills. Returns {uri: points}."""
    lines = [f"[{s['priority']:<12}] {s['label']}  ({s['skillType']})" for s in skills]
    allocation = allocate_in_terminal(
        lines, POINT_BUDGET,
        intro="ESCO skills found for this job. What matters most? Put more points on the most important skills.",
    )
    return {skills[i]["uri"]: p for i, p in allocation.items()}


def print_job_card(job):
    print(f"\n=== Job card: {job.title} ===")
    for s in sorted(job.skills, key=lambda s: -s.points):
        print(f"{points_bar(s.points)}  {s.points:>2}  {s.label}  [{s.priority}]")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", help="job description or task list (or use --file / stdin)")
    parser.add_argument("--file", help="read the job text from a file")
    parser.add_argument("--no-questions", action="store_true", help="skip clarifying questions")
    parser.add_argument("--json", action="store_true", help="print raw JSON (skips point allocation)")
    parser.add_argument("--out", help="save the job profile (with points) as JSON")
    parser.add_argument("--save", action="store_true", help="store the job profile in the database (data/app.db)")
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
        return

    print_result(spec, skills)
    if not skills:
        sys.exit("No ESCO skills found, nothing to allocate.")
    job = make_job_profile(spec, skills, allocate_job_points(skills))
    print_job_card(job)
    if args.out:
        Path(args.out).write_text(job.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nSaved to {args.out}")
    if args.save:
        import db
        conn = db.connect()
        print(f"\nStored in the database as job {db.save_job(conn, job)}")
        conn.close()


if __name__ == "__main__":
    main()
