"""HTTP API (FastAPI) over the applicant, employer, storage and matching code.

Local use only: the server listens on 127.0.0.1 and has no login, so only the machine it runs on
can reach it. Every endpoint, including the ones that return validation answers, is open to
anyone who can connect. Do not start it with --host 0.0.0.0.

Run (one process; do not use --workers):
    .venv/bin/uvicorn api:app --reload            # macOS / Linux
    .venv\\Scripts\\uvicorn api:app --reload        # Windows
Then open http://127.0.0.1:8000/docs for the interactive docs.

All endpoints are under /api. If frontend/dist exists (or FRONTEND_DIR points to a built
frontend), it is served at / from the same server, so the frontend needs no CORS. A frontend dev
server on localhost (any port) is also allowed by CORS.

Design rules carried over from the modules:
  - Every flow call blocks (Gemini, CPU embeddings), so those endpoints are plain `def`:
    FastAPI runs them in worker threads.
  - Validation answers are only stored and returned. No endpoint sends them to an LLM.
  - Point-rule violations (points.check_allocation) come back as HTTP 422 with a readable `detail`.
"""

import os
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field, ValidationError

import db
from bizdev import BizDevAgent
from bizdev.api import router as bizdev
from applicant import ApplicantFlow, ApplicantProfile, make_applicant_profile, skills_to_validate
from employer import QA, Clarification, EmployerFlow, JobProfile, JobSpec, make_job_profile
from matching import MatchResult, SkillSimilarity, rank_applicants, rank_jobs

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", ROOT / "frontend" / "dist"))
LOCAL_ORIGINS = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

Priority = Literal["must_have", "learnable", "nice_to_have"]


# ---------- Request / response bodies (the profiles themselves reuse the modules' models) ----------

class EmployerText(BaseModel):
    text: str = Field(min_length=1, description="Job ad or task list, any language.")
    qa: list[QA] = Field(default_factory=list, description="Clarifying questions answered so far.")


class JobSkill(BaseModel):
    """One ESCO skill from /employer/skills (EmployerFlow.map_spec)."""
    uri: str
    label: str
    skillType: str
    priority: Priority
    tasks: list[str] = Field(default_factory=list)
    reuseLevel: str | None = None
    confidence: str | None = None
    probability: float | None = None
    sources: list[str] = Field(default_factory=list)


class SpecIn(BaseModel):
    spec: JobSpec


class JobProfileIn(BaseModel):
    spec: JobSpec
    skills: list[JobSkill] = Field(description="The skills returned by /employer/skills.")
    allocation: dict[str, int] = Field(description="{uri: points}. Exactly 10 points; 0 drops a skill.")


class SavedJob(BaseModel):
    id: str
    profile: JobProfile


class ApplicantText(BaseModel):
    text: str = Field(min_length=1, description="CV, LinkedIn text or free text, any language.")


class Suggestion(BaseModel):
    """One AI suggestion (SkillMapper.map_text). Only a suggestion: the applicant confirms it."""
    uri: str
    label: str
    skillType: str
    reuseLevel: str | None = None
    confidence: str
    probability: float | None = None
    statements: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, description="Quotes from the applicant's text.")


class SearchHit(BaseModel):
    uri: str
    label: str
    skillType: str
    reuseLevel: str | None = None
    altLabels: list[str] = Field(default_factory=list)
    description: str = ""
    score: float


class QuestionsIn(BaseModel):
    allocation: dict[str, int] = Field(description="The applicant's {uri: points}. Questions are returned only "
                                                   "for the skills with the most points (skills_to_validate).")
    language: str = "English"


class ConfirmedSkill(BaseModel):
    uri: str
    label: str
    skillType: str
    origin: Literal["suggested", "added"]


class ApplicantProfileIn(BaseModel):
    skills: list[ConfirmedSkill] = Field(description="Skills the applicant confirmed or added.")
    allocation: dict[str, int] = Field(description="{uri: points}. Exactly 10 points on at most 5 skills.")
    questions: dict[str, str] = Field(default_factory=dict, description="{uri: question} from /applicant/questions.")
    # Stored verbatim and shown to recruiters. NEVER sent to an LLM.
    answers: dict[str, str] = Field(default_factory=dict, description="{uri: the applicant's own words}.")


class SavedApplicant(BaseModel):
    id: str
    profile: ApplicantProfile


class JobRow(BaseModel):
    id: str
    created_at: str
    title: str
    n_skills: int


class ApplicantRow(BaseModel):
    id: str
    created_at: str
    n_skills: int
    skills: str | None


# ---------- Helpers ----------

# validation_questions() rewrites data/validation_questions.json; one writer at a time.
_questions_lock = threading.Lock()


@contextmanager
def open_db(request):
    """One SQLite connection per request, opened and closed in the endpoint's own thread
    (sqlite3 connections can't move between threads)."""
    conn = db.connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def rule_error(e):
    """ValueError / pydantic ValidationError -> HTTP 422 with a message a person can read."""
    if isinstance(e, ValidationError):
        msgs = [err["msg"].removeprefix("Value error, ") for err in e.errors()]
        return HTTPException(422, "; ".join(msgs))
    return HTTPException(422, str(e))


def check_known(request, uris):
    unknown = sorted(set(uris) - request.app.state.known_uris)
    if unknown:
        raise HTTPException(422, f"not ESCO skills in our index: {unknown}")


def not_found(kind, item_id):
    return HTTPException(404, f"no {kind} with id {item_id}")


# ---------- Employer ----------

employer = APIRouter(prefix="/employer", tags=["employer"])


@employer.post("/clarify", response_model=Clarification)
def clarify(body: EmployerText, request: Request):
    """Step 1, in rounds: what is still unclear? Send earlier answers in `qa`. Stop when
    `is_clear_enough` is true or after 2 rounds, then call /employer/spec."""
    return request.app.state.employer.clarify(body.text, body.qa)


@employer.post("/spec", response_model=JobSpec)
def spec(body: EmployerText, request: Request):
    """Step 2: text + answers -> concrete tasks with priorities, and flags."""
    return request.app.state.employer.build_spec(body.text, body.qa)


@employer.post("/skills", response_model=list[JobSkill])
def skills(body: SpecIn, request: Request):
    """Step 3: the JobSpec -> ESCO skills, must-haves first. The recruiter ranks them next."""
    return request.app.state.employer.map_spec(body.spec)


@employer.post("/profile", response_model=SavedJob)
def job_profile(body: JobProfileIn, request: Request):
    """Step 4: the recruiter's points -> JobProfile, stored in the database."""
    check_known(request, body.allocation)
    try:
        job = make_job_profile(body.spec, [s.model_dump() for s in body.skills], body.allocation)
    except ValueError as e:
        raise rule_error(e)
    with open_db(request) as conn:
        return SavedJob(id=db.save_job(conn, job), profile=job)


# ---------- Applicant ----------

applicant = APIRouter(prefix="/applicant", tags=["applicant"])


@applicant.post("/suggest", response_model=list[Suggestion])
def suggest(body: ApplicantText, request: Request):
    """Step 1: AI suggestions from the applicant's text. The applicant keeps or removes each one."""
    return request.app.state.applicant.suggest_skills(body.text)


@applicant.get("/search", response_model=list[SearchHit])
def search(request: Request, q: str = Query(min_length=1), k: int = Query(5, ge=1, le=50)):
    """Step 2: the applicant searches for skills the AI missed. No Gemini."""
    return request.app.state.applicant.search_skills(q, k)


@applicant.post("/questions", response_model=dict[str, str])
def questions(body: QuestionsIn, request: Request):
    """Step 3: validation questions for the 1-2 skills with the most points, {uri: question}.
    Generated from the ESCO skill only (no applicant data) and cached, so everyone gets the
    same question."""
    check_known(request, body.allocation)
    uris = skills_to_validate(body.allocation)
    with _questions_lock:
        return request.app.state.applicant.questions_for([{"uri": u} for u in uris], body.language)


@applicant.post("/profile", response_model=SavedApplicant)
def applicant_profile(body: ApplicantProfileIn, request: Request):
    """Step 4: the applicant's points and answers -> ApplicantProfile, stored in the database.
    The answers are stored verbatim and never sent to an LLM."""
    check_known(request, body.allocation)
    try:
        profile = make_applicant_profile([s.model_dump() for s in body.skills], body.allocation,
                                         body.questions, body.answers)
    except ValueError as e:
        raise rule_error(e)
    with open_db(request) as conn:
        return SavedApplicant(id=db.save_applicant(conn, profile), profile=profile)


# ---------- Stored profiles and matching ----------

jobs = APIRouter(prefix="/jobs", tags=["jobs"])


@jobs.get("", response_model=list[JobRow])
def list_jobs(request: Request):
    with open_db(request) as conn:
        return db.list_jobs(conn)


@jobs.get("/{job_id}", response_model=JobProfile)
def get_job(job_id: str, request: Request):
    with open_db(request) as conn:
        job = db.get_job(conn, job_id)
    if job is None:
        raise not_found("job", job_id)
    return job


@jobs.delete("/{job_id}", status_code=204)
def delete_job(job_id: str, request: Request):
    with open_db(request) as conn:
        if not db.delete_job(conn, job_id):
            raise not_found("job", job_id)


@jobs.get("/{job_id}/matches", response_model=list[MatchResult])
def job_matches(job_id: str, request: Request):
    """All applicants for this job, best first, each with a per-skill explanation in `links`."""
    with open_db(request) as conn:
        if db.get_job(conn, job_id) is None:
            raise not_found("job", job_id)
        return rank_applicants(conn, job_id, request.app.state.sim)


applicants = APIRouter(prefix="/applicants", tags=["applicants"])


@applicants.get("", response_model=list[ApplicantRow])
def list_applicants(request: Request):
    with open_db(request) as conn:
        return db.list_applicants(conn)


@applicants.get("/{applicant_id}", response_model=ApplicantProfile)
def get_applicant(applicant_id: str, request: Request):
    with open_db(request) as conn:
        profile = db.get_applicant(conn, applicant_id)
    if profile is None:
        raise not_found("applicant", applicant_id)
    return profile


@applicants.delete("/{applicant_id}", status_code=204)
def delete_applicant(applicant_id: str, request: Request):
    with open_db(request) as conn:
        if not db.delete_applicant(conn, applicant_id):
            raise not_found("applicant", applicant_id)


@applicants.get("/{applicant_id}/matches", response_model=list[MatchResult])
def applicant_matches(applicant_id: str, request: Request):
    """All jobs for this applicant, best first (the applicant's feedback view)."""
    with open_db(request) as conn:
        if db.get_applicant(conn, applicant_id) is None:
            raise not_found("applicant", applicant_id)
        return rank_jobs(conn, applicant_id, request.app.state.sim)


# ---------- App ----------

def create_app(mapper=None, sim=None, db_path=None, frontend_dir=FRONTEND_DIR):
    """Build the app. Tests pass a stub `mapper` and a temporary `db_path`; normally all are None."""

    @asynccontextmanager
    async def lifespan(app):
        if mapper is None:
            from map_skills import SkillMapper
            m = SkillMapper()                 # exits with a message if GEMINI_API_KEY or the index is missing
            m.index.search("warm up", k=1)    # load the embedding model now, not on the first request
        else:
            m = mapper
        app.state.mapper = m
        app.state.applicant = ApplicantFlow(m)
        app.state.employer = EmployerFlow(m)
        app.state.bizdev = BizDevAgent(mapper=m)
        app.state.sim = sim or SkillSimilarity(m.index)
        app.state.known_uris = {s["uri"] for s in m.index.skills}
        app.state.db_path = db_path or db.DB_PATH
        yield

    app = FastAPI(title="Junction 2026 skills matching", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origin_regex=LOCAL_ORIGINS,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(genai_errors.APIError)
    async def gemini_failed(request, exc):
        return JSONResponse(status_code=502, content={"detail": f"Gemini request failed: {exc}"})

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["meta"])
    def health(request: Request):
        return {"status": "ok", "esco_skills": len(request.app.state.known_uris)}

    for router in (employer, applicant, jobs, applicants, bizdev):
        api.include_router(router)
    app.include_router(api)

    # Mounted last so /api routes win.
    if Path(frontend_dir).is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000)
