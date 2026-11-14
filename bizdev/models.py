"""Pydantic models for every step, and the output contract (SkillRequirements).

Every BizDevAgent method takes and returns these, so a web front end can call one step per request
and send the previous step's result back."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from employer import JobSpec

Priority = Literal["must_have", "learnable", "nice_to_have"]
SCHEMA = "bizdev.skill_requirements/v1"


# ---------- Step 1: profile ----------

class Profile(BaseModel):
    business_id: str | None = None
    name: str | None = None
    sector_family: str
    tol_code: str | None = None
    registered: str | None = Field(None, description="Registration date, YYYY-MM-DD.")
    age_band: str | None = None
    source: Literal["prh", "sample", "manual"] = Field(
        description="prh: looked up in the PRH registry. sample: a demo company. manual: sector picked by hand.")


# ---------- Step 2: diagnosis ----------

class Option(BaseModel):
    """Either leads to the next question or locks a root cause."""
    label: str
    next: str | None = None
    root_cause: str | None = None


class Hypothesis(BaseModel):
    id: str
    prompt: str
    a: Option
    b: Option


class Answer(BaseModel):
    question_id: str
    answer: Literal["A", "B", "neither"]


class RootCauseChoice(BaseModel):
    id: str
    name: str
    current: str


class Diagnosis(BaseModel):
    """State of the A/B diagnosis. Exactly one of these is set while it is open:
    current_question (answer A/B/neither), needs_text (describe the problem), or needs_choice
    (pick one of `choices`). Done when root_cause is set."""
    sector_family: str
    answers: list[Answer] = Field(default_factory=list)
    current_question: Hypothesis | None = None
    needs_text: bool = False
    needs_choice: bool = False
    choices: list[RootCauseChoice] = Field(default_factory=list)
    text: str | None = Field(None, description="The company's own description, if it gave one.")
    root_cause: str | None = None

    @property
    def done(self):
        return self.root_cause is not None


# ---------- Step 3: ideas ----------

class Idea(BaseModel):
    title: str
    why: str
    first_step: str


class CapabilityShift(BaseModel):
    root_cause: str
    name: str
    current: str
    target: str
    benefit: str | None = None


# ---------- Step 4: task card ----------

class CardTask(BaseModel):
    id: str
    task: str
    priority: Priority
    origin: Literal["playbook", "company"] = Field(
        description="playbook: proposed and kept word for word. company: added or rewritten by the company.")
    skills: list[str] = Field(default_factory=list, description="ESCO-style skill phrases. Empty for company tasks until mapped.")


class TaskCard(BaseModel):
    root_cause: str
    tasks: list[CardTask]


# ---------- Step 5: output contract ----------

class Company(BaseModel):
    business_id: str | None
    name: str | None
    sector_family: str


class Need(BaseModel):
    root_cause: str
    name: str
    current: str
    target: str


class OutputTask(BaseModel):
    id: str
    task: str
    priority: Priority
    origin: Literal["playbook", "company"]
    status: Literal["mapped", "unmapped", "no_match"] = Field(
        description="mapped: has ESCO skills. unmapped: still needs mapping (pipeline was unavailable). "
                    "no_match: mapped, but no ESCO skill fitted.")
    skill_phrases: list[str] = Field(default_factory=list)


class RequiredSkill(BaseModel):
    """Same fields as one entry of employer.EmployerFlow.map_spec()."""
    uri: str
    label: str
    skillType: str
    reuseLevel: str | None = None
    priority: Priority
    confidence: Literal["high", "medium"]
    probability: float | None = None
    tasks: list[str]
    sources: list[str]


class SkillRequirements(BaseModel):
    schema_: str = Field(SCHEMA, alias="schema")
    created: str = Field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    company: Company
    need: Need
    ideas: list[Idea]
    tasks: list[OutputTask]
    skills: list[RequiredSkill]
    job_spec: JobSpec

    model_config = {"populate_by_name": True, "serialize_by_alias": True}

    def to_json(self):
        return self.model_dump_json(indent=2, by_alias=True)

    def save(self, path):
        Path(path).write_text(self.to_json(), encoding="utf-8")
