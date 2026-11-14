# Junction 2026: Espoo skills matching

Helou pöytäläiset! We match applicants and employers on real job requirements and on skills people rank themselves. The vision is in [PLAN.md](PLAN.md), the background research in [RESEARCH.md](RESEARCH.md), and the challenge in [CHALLENGE.md](CHALLENGE.md).

## How it works

Both sides describe themselves in plain language. The AI turns that text into [ESCO](https://esco.ec.europa.eu/) skills, and the person then decides what is true.

- **Applicant:** CV or free text → AI suggests skills → applicant keeps, removes or adds skills → spends 10 points on at most 5 skills → answers one validation question per skill in their own words.
- **Employer:** job ad or task list → AI asks clarifying questions (up to 2 rounds) → concrete tasks with priorities → ESCO skills → recruiter spends 10 points on the skills that matter most.

**Matching:** both sides spend 10 points, so each profile is a priority distribution over ESCO skills. The score is a *soft cosine* between the two distributions: similar but different ESCO skills count partly (e.g. *troubleshoot* ≈ *debug software*), using calibrated similarities between the precomputed skill embeddings. Next to the score, *coverage* says how many of the employer's 10 points the applicant covers, and every employer skill is explained ("covered by X", "similar to Y", "not covered"). Matching is a fixed formula over skill data, with no LLM.

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
| [matching.py](matching.py) | Matches jobs and applicants on their points: soft cosine score + coverage, with a per-skill explanation. No LLM |
| [db.py](db.py) | SQLite storage (`data/app.db`, gitignored) for job profiles and applicant profiles, one row per skill with its points |
| [api.py](api.py) | FastAPI app: the HTTP API for the frontend, see [Backend API](#backend-api-for-the-frontend) |
| [tests/](tests/) | `pytest` tests for matching and the API (need the index; no Gemini, the API tests use a stub) |
| `data/validation_questions.json` | Cache of validation questions, one per skill and language. Same skill → same question for everyone |

Both flows are stateless. Each step takes the data it needs as arguments and returns it, so a web backend can call them one request at a time.

## Setup

Needs Python 3.14 and [uv](https://docs.astral.sh/uv/). Runs on Linux, Windows and Apple Silicon Macs. It does not run on Intel Macs, see [Windows and macOS](#windows-and-macos).

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements.txt --index-strategy unsafe-best-match
export GEMINI_API_KEY=...
```

Get the ESCO index. The easiest way is to copy `esco/skills.npy` and `esco/skills_meta.json` from a teammate into `esco/`. The files work on every platform. That folder is gitignored. To build the index yourself, download the ESCO CSVs (English) into `esco/` and run the command below. It takes about 18 minutes on a laptop CPU and can be resumed if interrupted.

```bash
.venv/bin/python build_index.py
```

The first search downloads the embedding model (`intfloat/multilingual-e5-small`) from Hugging Face, so it needs internet once.

### Windows and macOS

| Platform | Works? |
|---|---|
| Linux x86_64 | Yes |
| Windows x86_64 | Yes (CPU build of PyTorch) |
| Mac with Apple Silicon (M1 or later), macOS 14 or newer | Yes |
| Mac with an Intel CPU | **No.** PyTorch publishes no Intel Mac wheels for `torch==2.14.1`. Use another machine, or run it in Docker with a Linux image |

These results come from resolving `requirements.txt` with `uv pip compile` for each platform. We haven't installed or run the code on a real Windows or Mac machine yet.

**Windows differences.** Every command in this README uses the macOS/Linux path `.venv/bin/...`. On Windows, use `.venv\Scripts\...` instead. In PowerShell:

```powershell
uv venv --python 3.14 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt --index-strategy unsafe-best-match
$env:GEMINI_API_KEY="..."            # this terminal only; use setx GEMINI_API_KEY "..." to keep it
.venv\Scripts\python build_index.py
.venv\Scripts\python employer.py --file job_ad.txt
.venv\Scripts\uvicorn api:app --reload
```

On Windows, give `applicant.py` and `employer.py` the text with `--file` or as an argument. Piping it in (`type cv.txt | ... applicant.py`) fails, because after reading the pipe they reopen the keyboard through `/dev/tty`, which Windows doesn't have.

## Usage (terminal)

On Windows, replace `.venv/bin/python` with `.venv\Scripts\python`.

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

# Matching
.venv/bin/python matching.py job <job-id>              # applicants for a job, best first, with explanations
.venv/bin/python matching.py applicant <applicant-id>  # jobs for an applicant
.venv/bin/python matching.py demo                      # synthetic examples, no database needed
.venv/bin/python -m pytest tests/

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

[api.py](api.py) serves everything over HTTP with FastAPI. The frontend calls the endpoints below and builds the screens. Each endpoint is a thin wrapper around the Python call shown, and the request and response bodies reuse the Pydantic models in the modules.

### Run it

```bash
export GEMINI_API_KEY=...
.venv/bin/uvicorn api:app --reload          # Windows: .venv\Scripts\uvicorn api:app --reload
```

Startup takes a few seconds while it loads the ESCO index and the embedding model. Then open **http://127.0.0.1:8000/docs** to try every endpoint with its exact schema. The server stops at startup with a clear message if `GEMINI_API_KEY` or `esco/skills.npy` is missing.

- **Local only.** The server listens on `127.0.0.1` and has no login, so only your own machine can reach it. Every endpoint is open to anyone who can connect, including the ones that return validation answers. Don't start it with `--host 0.0.0.0`.
- **One process.** Don't use `--workers`. Each worker would load its own copy of the index and the model, and they would share one SQLite file and one question cache.

### Hosting the frontend on the same machine

Both setups below avoid hard-coded hosts: call the API with relative URLs such as `/api/applicant/suggest`, never `http://localhost:8000/...`.

- **Built frontend:** put the build output in `frontend/dist`, or set `FRONTEND_DIR` to another folder. `api.py` serves it at `http://127.0.0.1:8000/` from the same server. This needs no CORS and has one URL to open.
- **Dev server** (Vite, Next and so on): run it next to the API and proxy `/api` to `http://127.0.0.1:8000`. CORS also allows any `localhost` or `127.0.0.1` origin, so calling the API directly works too.

### Endpoints

All paths start with `/api`. Every flow call blocks for seconds (Gemini, CPU embeddings), so show a loading state.

**Employer**

| Method and path | Body | Calls | Returns |
|---|---|---|---|
| `POST /api/employer/clarify` | `{text, qa: [{question, answer}]}` | `EmployerFlow.clarify` | `Clarification`: `understood_so_far`, `is_clear_enough`, `questions` |
| `POST /api/employer/spec` | `{text, qa}` | `EmployerFlow.build_spec` | `JobSpec`: `title`, `summary`, `tasks`, `flags` |
| `POST /api/employer/skills` | `{spec}` | `EmployerFlow.map_spec` | Skills, must-haves first, each with `uri`, `label`, `priority`, `tasks`, `confidence` |
| `POST /api/employer/profile` | `{spec, skills, allocation: {uri: points}}` | `make_job_profile` + `db.save_job` | `{id, profile: JobProfile}` |

The flow is stateless, so the frontend sends back what it received. `spec` from `/employer/spec` goes to `/employer/skills`. Then `spec` and `skills` both go to `/employer/profile` with the recruiter's allocation.

Clarification runs in rounds. Call `clarify` first. If `is_clear_enough` is false, show `questions` (each has `why` and `example_answers` to help the employer), and call `clarify` again with all answers so far in `qa`. Stop after 2 rounds, or when `is_clear_enough` is true, then call `spec`.

**Applicant**

| Method and path | Body | Calls | Returns |
|---|---|---|---|
| `POST /api/applicant/suggest` | `{text}` | `ApplicantFlow.suggest_skills` | AI suggestions, each with `uri`, `label`, `skillType`, `evidence` (quotes from the text) |
| `GET /api/applicant/search?q=...&k=5` | — | `ApplicantFlow.search_skills` | Matching skills, each with `uri`, `label`, `skillType`, `description`, `score`. No Gemini |
| `POST /api/applicant/questions` | `{skills: [{uri}], language: "English"}` | `ApplicantFlow.questions_for` | `{uri: question}` |
| `POST /api/applicant/profile` | `{skills, allocation: {uri: points}, questions: {uri: question}, answers: {uri: answer}}` | `make_applicant_profile` + `db.save_applicant` | `{id, profile: ApplicantProfile}` |

`skills` lists the confirmed skills, each with `uri`, `label`, `skillType` and `origin` (`"suggested"` for a kept AI suggestion, `"added"` for one found with search). The applicant confirms suggestions before spending points, so only confirmed skills are sent.

**Stored profiles and matching**

| Method and path | Returns |
|---|---|
| `GET /api/jobs` | All jobs: `id`, `created_at`, `title`, `n_skills` |
| `GET /api/jobs/{id}` | `JobProfile` |
| `GET /api/jobs/{id}/matches` | Applicants for this job, best first: list of `MatchResult` |
| `DELETE /api/jobs/{id}` | 204 |
| `GET /api/applicants` | All applicants: `id`, `created_at`, `n_skills`, `skills` (labels) |
| `GET /api/applicants/{id}` | `ApplicantProfile`, including the validation answers |
| `GET /api/applicants/{id}/matches` | Jobs for this applicant, best first: list of `MatchResult` |
| `DELETE /api/applicants/{id}` | 204 |
| `GET /api/health` | `{status, esco_skills}` |

A `MatchResult` has these fields:
- `score` (0–1).
- `coverage` (0–1): the share of the employer's points the applicant covers.
- `links`: one per employer skill, with the applicant skill that covers it, both sides' points, and `similarity`, where 1 means the same skill and 0 means not covered.
- `missing_must_haves`.

Show `links` to explain each match. `explain(result)` in [matching.py](matching.py) shows the wording.

### Errors

| Status | When | `detail` |
|---|---|---|
| 422 | A point rule is broken, the text is empty, or a URI is not in the ESCO index | A readable message, e.g. `spend exactly 10 points (got 9)`. Show it to the person |
| 404 | No job or applicant with that id | `no job with id ...` |
| 502 | The Gemini request failed | `Gemini request failed: ...`. Let the person retry |

### Rules the frontend must follow

The backend enforces these rules. The UI should also respect them, so people see a problem before they submit.

- **Points:** every allocation adds up to exactly **10** (`POINT_BUDGET`). Each chosen skill gets at least 1 point. Skills with 0 points are dropped.
- **Applicant limit:** at most **5** skills (`MAX_SKILLS`). Employers have no skill limit.
- **Uniqueness:** each skill URI appears once.
- **Never send validation answers to an AI endpoint.** Answers go only to `/api/applicant/profile` and on to recruiters. Do not add an endpoint that sends answers to Gemini or any other LLM.
- **AI suggestions are not decisions.** Show them as suggestions. The applicant or recruiter confirms each one.
- **No personal details.** Profiles have no name, photo, age or nationality. Don't add those fields in the UI.

### Good to know

- **First calls for new skills are slow.** The first `questions` call for a skill nobody has chosen before asks Gemini. After that, the question comes from `data/validation_questions.json`. Writes to that file are serialised inside the server.
- **Storage is one SQLite file**, `data/app.db`, created on first use. `db.py list` and `db.py show <id>` read it from the terminal while the server runs. Validation answers can contain personal details, so delete the file after the event.
- **Terminal-only helpers.** `allocate_in_terminal`, `ask_in_terminal` and `allocate_job_points` are for the CLI. The web version replaces them with forms that send `allocation` and `answers`.

### Quick test

With the server running:

```bash
curl -X POST 127.0.0.1:8000/api/applicant/suggest -H 'content-type: application/json' \
  -d '{"text": "I kept the books for my family shop and trained 3 new staff"}'
curl '127.0.0.1:8000/api/applicant/search?q=bookkeeping&k=3'
```

`.venv/bin/python -m pytest tests/` runs the API tests without Gemini. They use a stub for the Gemini calls and a temporary database.
