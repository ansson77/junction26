"""HTTP endpoints for the Business Developer Agent, mounted by the main api.py under /api/bizdev.

One request per step. The flow is stateless: send back what the previous step returned.

    POST /bizdev/profile    {business_id} | {sample} | {sector, name?, business_id?}   -> Profile
    GET  /bizdev/options                                 -> sample companies, sectors, warnings
    POST /bizdev/diagnose   {profile}                    -> Diagnosis (with current_question)
    POST /bizdev/answer     {diagnosis, answer}          -> Diagnosis ("A" | "B" | "neither")
    POST /bizdev/describe   {diagnosis, text}            -> Diagnosis (when needs_text)
    POST /bizdev/choose     {diagnosis, root_cause}      -> Diagnosis (when needs_choice)
    POST /bizdev/ideas      {diagnosis}                  -> {shift, ideas}
    POST /bizdev/taskcard   {diagnosis}                  -> TaskCard
    POST /bizdev/taskcard/edit {card, remove, edit, add, priority} -> TaskCard
    POST /bizdev/skills     {profile, diagnosis, card}   -> SkillRequirements (the output)

Diagnosis is done when `root_cause` is set. Otherwise exactly one of current_question / needs_text /
needs_choice says what to ask next."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .models import CapabilityShift, Diagnosis, Idea, Priority, Profile, SkillRequirements, TaskCard
from .sources import load_playbook, sample_companies

router = APIRouter(prefix="/bizdev", tags=["bizdev"])


class ProfileIn(BaseModel):
    business_id: str | None = None
    sample: str | None = None
    sector: str | None = None
    name: str | None = None


class DiagnoseIn(BaseModel):
    profile: Profile


class AnswerIn(BaseModel):
    diagnosis: Diagnosis
    answer: str = Field(description='"A", "B" or "neither"')


class DescribeIn(BaseModel):
    diagnosis: Diagnosis
    text: str = Field(min_length=1)


class ChooseIn(BaseModel):
    diagnosis: Diagnosis
    root_cause: str


class DiagnosisIn(BaseModel):
    diagnosis: Diagnosis


class IdeasOut(BaseModel):
    shift: CapabilityShift
    ideas: list[Idea]


class EditIn(BaseModel):
    card: TaskCard
    remove: list[str] = Field(default_factory=list, description="Task ids to remove.")
    edit: dict[str, str] = Field(default_factory=dict, description="{task_id: new text}. Any change makes it a company task.")
    add: list[str] = Field(default_factory=list, description="New tasks in the company's words.")
    priority: dict[str, Priority] = Field(default_factory=dict, description="{task_id: priority}")


class SkillsIn(BaseModel):
    profile: Profile
    diagnosis: Diagnosis
    card: TaskCard


class Options(BaseModel):
    samples: list[dict]
    sectors: dict[str, str]
    warnings: list[str] = Field(description="Show these before the company starts: they make the output incomplete.")


def agent(request):
    return request.app.state.bizdev


def step(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/options", response_model=Options)
def options(request: Request):
    return Options(samples=sample_companies(), sectors=load_playbook()["sectors"], warnings=agent(request).warnings())


@router.post("/profile", response_model=Profile)
def profile(body: ProfileIn, request: Request):
    """404 if the PRH lookup fails: ask the company for its sector and call again with `sector`."""
    try:
        return step(agent(request).profile, **body.model_dump())
    except LookupError as e:
        raise HTTPException(404, f"{e}; send the sector instead")


@router.post("/diagnose", response_model=Diagnosis)
def diagnose(body: DiagnoseIn, request: Request):
    return step(agent(request).diagnose, body.profile)


@router.post("/answer", response_model=Diagnosis)
def answer(body: AnswerIn, request: Request):
    return step(agent(request).answer, body.diagnosis, body.answer)


@router.post("/describe", response_model=Diagnosis)
def describe(body: DescribeIn, request: Request):
    return step(agent(request).describe, body.diagnosis, body.text)


@router.post("/choose", response_model=Diagnosis)
def choose(body: ChooseIn, request: Request):
    return step(agent(request).choose, body.diagnosis, body.root_cause)


@router.post("/ideas", response_model=IdeasOut)
def ideas(body: DiagnosisIn, request: Request):
    shift, items = step(agent(request).ideas, body.diagnosis)
    return IdeasOut(shift=shift, ideas=items)


@router.post("/taskcard", response_model=TaskCard)
def taskcard(body: DiagnosisIn, request: Request):
    return step(agent(request).task_card, body.diagnosis)


@router.post("/taskcard/edit", response_model=TaskCard)
def edit(body: EditIn, request: Request):
    return step(agent(request).edit, body.card, remove=body.remove, edit=body.edit, add=body.add,
                priority=body.priority)


@router.post("/skills", response_model=SkillRequirements, response_model_by_alias=True)
def skills(body: SkillsIn, request: Request):
    """The output. Company-written tasks are mapped live (Gemini), so this can take seconds."""
    return step(agent(request).skills, body.profile, body.diagnosis, body.card)
