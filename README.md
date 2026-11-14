# Junction 2026: Espoo skills matching

Helou pöytäläiset! We match applicants and employers on real job requirements and on skills people rank themselves. The vision is in [PLAN.md](PLAN.md), the background research in [RESEARCH.md](RESEARCH.md), and the challenge in [CHALLENGE.md](CHALLENGE.md).

## How it works

Both sides describe themselves in plain language. The AI turns that text into [ESCO](https://esco.ec.europa.eu/) skills, and the person then decides what is true.

- **Applicant:** CV or free text → AI suggests skills → applicant keeps, removes or adds skills → spends 10 points on at most 5 skills → answers one validation question per skill in their own words.
- **Employer:** job ad or task list → AI asks clarifying questions (up to 2 rounds) → concrete tasks with priorities → ESCO skills → recruiter spends 10 points on the skills that matter most.

**AI Act principle:** our AI never evaluates people (EU AI Act, Annex III 4(a), high-risk). It only helps applicants describe themselves and helps employers describe jobs. Points and answers are self-declared. Validation answers are shown to recruiters verbatim and are never sent to an LLM.

## Components

### Free text → ESCO skills

```
text ──► 1. Extract ──► 2. Retrieve ──► 3. Select ──► ESCO skills + evidence
         Gemini         local           Gemini
                        embeddings      Decisions API
```

1. **Extract** (`gemini-flash-latest`): splits the text into short, English, ESCO-style statements ("perform bookkeeping"), each with the exact quote it came from. There are separate prompts for applicants and employers.
2. **Retrieve** (`multilingual-e5-small`, runs locally): finds the 15 most similar of the 13,955 ESCO skills for each statement. These candidates are similar in wording but not necessarily correct.
3. **Select** (`gemini-decision-1`): asks one yes/no question per statement–candidate pair and gets a calibrated probability. Probability ≥ 0.8 is `high`, ≥ 0.5 is `medium`, and anything lower is dropped. The model can only choose from the candidates, so it can't invent skill codes.

### Files

| File | What it does |
|---|---|
| [build_index.py](build_index.py) | Embeds `esco/skills_en.csv` once and saves `esco/skills.npy` and `esco/skills_meta.json` |
| [search.py](search.py) | `SkillIndex`: embedding search over the index (step 2 on its own, no Gemini) |
| [map_skills.py](map_skills.py) | `SkillMapper`: the full pipeline, steps 1–3 |
| [points.py](points.py) | Point budget rules (10 points) shared by applicants and employers |
| [applicant.py](applicant.py) | `ApplicantFlow` and `ApplicantProfile`: suggestions, search, validation questions; `make_applicant_profile()` builds the profile from the applicant's choices |
| [employer.py](employer.py) | `EmployerFlow` and `JobProfile`: clarify, build spec, map skills; `make_job_profile()` builds the job profile from the recruiter's points |
| [db.py](db.py) | SQLite storage (`data/app.db`, gitignored) for job profiles and applicant profiles, one row per skill with its points |
| `data/validation_questions.json` | Cache of validation questions, one per skill and language. Same skill → same question for everyone |

Both flows are stateless. Each step takes the data it needs as arguments and returns it, so a web backend can call them one request at a time.

## Setup

Needs Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements.txt --index-strategy unsafe-best-match
export GEMINI_API_KEY=...
```

Download the ESCO CSVs (English) into `esco/`. That folder is gitignored. Then build the index once. It takes about 18 minutes on a laptop CPU and can be resumed if interrupted. Alternatively, ask a teammate for `esco/skills.npy` and `esco/skills_meta.json`.

```bash
.venv/bin/python build_index.py
```

## Usage (terminal)

```bash
# Free text → ESCO skills (no point allocation)
.venv/bin/python map_skills.py "Pidin kirjanpitoa perheen kaupassa ja koulutin 3 uutta työntekijää"
.venv/bin/python map_skills.py --file job_ad.txt --role employer --json
.venv/bin/python map_skills.py "..." --debug    # also show statements and search candidates
.venv/bin/python search.py                      # interactive search, no Gemini needed

# Applicant: suggest, search, allocate points, answer questions, see the recruiter card
.venv/bin/python applicant.py --file cv.txt --out profile.json   # --save stores it in the database

# Employer: clarify, map, allocate points, see the job card
.venv/bin/python employer.py --file job_ad.txt --save
.venv/bin/python employer.py --file job_ad.txt --no-questions --json

# Database
.venv/bin/python db.py list          # all jobs and applicants
.venv/bin/python db.py show <id>     # one profile as JSON
.venv/bin/python db.py delete <id>
```

From Python:

```python
from map_skills import SkillMapper
SkillMapper().map_text(text, role="applicant")
# → [{uri, label, skillType, reuseLevel, confidence, probability, statements, evidence}, ...]
```

## Backend API for the frontend

The Python code is not yet served over HTTP. This section is the plan for wrapping it in a FastAPI app. The frontend developer needs to build the screens and call the endpoints below. The backend developer maps each endpoint to the Python call shown.

### 1. Add the dependencies

FastAPI and Uvicorn are not in `requirements.txt` yet. Add them, then install:

```
fastapi
uvicorn
```

Run the server with `.venv/bin/uvicorn api:app --reload`. The app object lives in `api.py`, which does not exist yet.

### 2. Load heavy objects once, at startup

Creating a `SkillMapper()` loads the ESCO index (`esco/skills.npy`, `esco/skills_meta.json`). The first search also loads the embedding model. Do this once in a FastAPI `lifespan` handler and store it on `app.state`, not per request.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from map_skills import SkillMapper

@asynccontextmanager
async def lifespan(app):
    app.state.mapper = SkillMapper()        # Gemini client + ESCO index
    app.state.mapper.index.search("warm up", k=1)  # load the embedding model now
    yield

app = FastAPI(lifespan=lifespan)
```

`SkillMapper()` and `SkillIndex()` call `SystemExit` when `GEMINI_API_KEY` or `esco/skills.npy` is missing. Let the server fail at startup with that message, rather than catching it.

### 3. Use `def`, not `async def`, for endpoints that call the flows

Every flow call is blocking: Gemini requests take seconds and the embedding model runs on the CPU. Declare these endpoints with plain `def` so FastAPI runs them in a worker thread. Otherwise, the server freezes while one request waits.

### 4. Endpoints

The request and response bodies are the Pydantic models already in the code. Reuse them so the schema stays in one place. Each route is a thin wrapper.

**Employer** (`employer.py`)

| Method and path | Body | Calls | Returns |
|---|---|---|---|
| `POST /employer/clarify` | `{text, qa: [{question, answer}]}` | `EmployerFlow.clarify(text, qa)` | `Clarification`: `understood_so_far`, `is_clear_enough`, `questions` |
| `POST /employer/spec` | `{text, qa}` | `EmployerFlow.build_spec(text, qa)` | `JobSpec`: `title`, `summary`, `tasks`, `flags` |
| `POST /employer/skills` | `{spec}` (the `JobSpec` from the previous step) | `EmployerFlow.map_spec(spec)` | List of skills, each with `uri`, `label`, `priority`, `tasks`, `confidence` |
| `POST /employer/profile` | `{spec, skills, allocation: {uri: points}}` | `make_job_profile(spec, skills, allocation)` | `JobProfile` (what gets stored and matched) |

The flow is stateless, so the frontend sends back what it received. For example, `spec` from `/employer/spec` goes to `/employer/skills`, and then `spec` and `skills` both go to `/employer/profile` with the recruiter's allocation.

Clarification runs in rounds. Use `clarify` first. If `is_clear_enough` is false, show `questions` and collect answers. Call `clarify` again with the answers in `qa`. Stop after 2 rounds (`MAX_ROUNDS`), then call `build_spec`.

**Applicant** (`applicant.py`)

| Method and path | Body | Calls | Returns |
|---|---|---|---|
| `POST /applicant/suggest` | `{text}` | `ApplicantFlow.suggest_skills(text)` | List of AI suggestions, each with `uri`, `label`, `evidence` |
| `GET /applicant/search?q=...&k=5` | — | `ApplicantFlow.search_skills(q, k)` | Skills matching the query, each with `uri`, `label`, `description`, `score` |
| `POST /applicant/questions` | `{skills: [{uri}]}` | `ApplicantFlow.questions_for(skills, language)` | `{uri: question}` |
| `POST /applicant/profile` | `{skills, allocation: {uri: points}, questions: {uri: question}, answers: {uri: answer}}` | `make_applicant_profile(skills, allocation, questions, answers)` | `ApplicantProfile` (what gets stored and matched) |

`skills` is the list of confirmed skills, each with `uri`, `label`, `skillType` and `origin` (`"suggested"` or `"added"`). The applicant sees their suggestions and confirms them before any points are spent, so only confirmed skills are sent. This mirrors `/employer/profile`: the frontend sends back what it received, plus the person's decisions.

### 5. Rules the frontend must follow

These rules are enforced by the backend. The UI should also respect them, so people see the problem before they submit.

- **Points:** every allocation adds up to exactly **10** (`POINT_BUDGET`). Each chosen skill gets at least 1 point. Skills with 0 points are dropped.
- **Applicant limit:** at most **5** skills (`MAX_SKILLS`). Employers have no skill limit.
- **Uniqueness:** each skill URI appears once.
- **Validation errors:** rule violations raise `ValueError`. Return them as HTTP 422 with the message, so the frontend can show it.
- **Never send validation answers to an AI endpoint.** Answers go only to `/applicant/profile` and on to recruiters. Do not add an endpoint that sends answers to Gemini or any other LLM.
- **AI suggestions are not decisions.** Show them as suggestions. The applicant or recruiter confirms each one.
- **No personal details.** Profiles have no name, photo, age or nationality. Don't add those fields in the UI.

### 6. Things that will surprise you

- **First calls are slow.** The first search loads the embedding model. The first `questions_for` call for an unseen skill calls Gemini. Warm up at startup, as in step 2, and show a loading state for the rest.
- **The question cache is a file.** `validation_questions()` writes `data/validation_questions.json`. Two concurrent first requests for the same new skill can overwrite each other. Losing a cached question is harmless, since it is regenerated later, but avoid running several servers against the same folder.
- **Terminal-only steps.** `allocate_in_terminal`, `ask_in_terminal`, and `allocate_job_points` are for the CLI. The web version replaces them with UI forms that send `allocation` or `answers`. Do not call them from the API.
- **Storage is SQLite** ([db.py](db.py)), one file at `data/app.db` with no server. In the profile endpoints, call `db.save_job(conn, job)` or `db.save_applicant(conn, profile)` and return the id along with the profile. Open one connection per request with `db.connect()`, because SQLite connections can't be shared between threads. `db.get_job`, `db.get_applicant`, `db.list_jobs` and `db.list_applicants` cover the read endpoints. For matching, `db.job_points(conn, job_id)` and `db.applicant_points(conn, uris)` return `{uri: points}`. Run a single server process. Validation answers can contain personal details, so delete the database after the event.
- **CORS.** The frontend runs on a different origin during development. Enable `CORSMiddleware` for that origin.

### 7. Quick test

Once the server runs, check the API from the terminal before building the screens:

```bash
curl -X POST localhost:8000/applicant/suggest -H 'content-type: application/json' \
  -d '{"text": "I kept the books for my family shop and trained 3 new staff"}'
```

FastAPI serves interactive docs at `http://localhost:8000/docs`. Use them to try each endpoint with the exact schema.
