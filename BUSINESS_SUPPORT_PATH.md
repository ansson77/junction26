# `bizdev/`: Business Developer Agent, demo module plan

Demo version of the deck *"From event organizer to business developer"* (V1.1, Junction Espoo 2026),
planned as one new folder on the `esco-skill-mapping` branch.

## Scope

**In scope:** a process where the company works out **what it needs** and **which skills that takes**:

```
Who are you?  ──►  What is holding you back?  ──►  What would fix it?  ──►  What work needs doing?  ──►  Which skills?
 1 Profile          2 A/B diagnosis                 3 Ideas                  4 Task card (confirmed)       5 ESCO skills
                                                                                                          = OUTPUT
```

**Out of scope:** everything that uses the skills afterwards (candidate matching, shortlists, event
registration, routing to training). Those are built separately and read the output file described in
section 5.

**Rules**
- `bizdev/` only imports from existing code. No existing file is edited, and nothing existing imports `bizdev`.
- Key figures (revenue, headcount, % benefits, candidate counts) are not part of the demo.
- The whole process runs offline from editable JSON. Gemini and the ESCO index are only needed to
  prepare the data once, and for tasks the company writes itself.

---

## 1. The process, step by step

| # | Step | What the company does | What the module does |
|---|---|---|---|
| 1 | Profile | Enters a Business ID (or picks a sample / a sector) | Looks up the sector from the PRH registry (TOL code) and age from the registration date |
| 2 | Diagnosis | Answers 1–2 A/B questions ("which is holding you back more?") | Picks the question from the sector table; the answer locks a **root cause** |
| 3 | Ideas | Reads current → target state and 3 improvement ideas | Looks them up for the root cause |
| 4 | Task card | **Confirms the work**: keeps, removes or rewrites the 2–3 proposed tasks, can add its own | Proposes tasks for the root cause; each task carries its skill phrases |
| 5 | Skills | Sees the skills behind the tasks, marks each task must have / learnable / nice to have | Turns the confirmed tasks into ESCO skills and writes the **output file** |

Step 4 is where "what the company needs" becomes concrete; step 5 is the hand-off to further development.

### How each step decides
- **Step 1:** TOL two-digit prefix → one of 8 sector families (software, professional services, manufacturing,
  construction, retail, hospitality, health care, general). No network → sample companies or manual sector.
- **Step 2:** deterministic. Each A/B option points to a root cause id. "Neither" → next question for the
  sector. When questions run out, the company describes the problem in a sentence, matched to a root cause
  by keywords (or Gemini, if available). No AI in the decision when an option is clicked.
- **Step 3–4:** lookups in the playbook by root cause id.
- **Step 5:**
  - *Playbook tasks (unchanged or only reworded):* ESCO skills are **already stored** in the playbook
    (prepared once, see section 4), so this is a lookup and works offline.
  - *Tasks the company added or rewrote substantially:* go through the existing pipeline,
    `EmployerFlow.map_spec()`, live. Without Gemini/index they are output with `"status": "unmapped"`
    so downstream code knows to map them later.

---

## 2. Folder structure

```
bizdev/
├── PLAN.md                    this file
├── __init__.py                exports BizDevAgent and the models
├── __main__.py                CLI: python -m bizdev <business-id> | --sample | --sector <name> [--out needs.json]
├── agent.py                   BizDevAgent: one method per step, stateless
├── models.py                  pydantic schemas incl. the output contract (section 5)
├── sources.py                 Business ID check, PRH lookup, TOL → sector, sample loader
├── diagnosis.py               A/B questions, "neither", free-text fallback → root cause
├── ideas.py                   root cause → capability shift + 3 ideas
├── taskcard.py                root cause → proposed tasks; company edits; → employer.JobSpec
├── skills.py                  confirmed tasks → ESCO skills (stored lookup, or live via EmployerFlow.map_spec)
├── prepare.py                 one-off: maps every playbook task with the existing pipeline, stores the result
├── llm.py                     optional Gemini client, same .generate() as SkillMapper
└── data/
    ├── playbook.json          sectors, A/B questions, root causes, ideas, tasks + skill phrases
    ├── playbook_esco.json     written by prepare.py: ESCO skills per playbook task
    └── sample_companies.json  3–4 fictional companies for offline demos
```

---

## 3. What each file does

| File | Responsibility | Uses existing code |
|---|---|---|
| `sources.py` | `normalize_business_id()`, `fetch_prh()` (best effort, no key), `sector_family()`, `age_band()`, `load_sample()` | — |
| `diagnosis.py` | `start(profile)`, `answer(diagnosis, "A"/"B"/"neither")`, `from_text(text)` | `EmployerFlow.clarify()` as last fallback |
| `ideas.py` | `capability_shift(root_cause)`, `ideas(root_cause, profile, generator=None)` | — |
| `taskcard.py` | `propose(root_cause)`, `apply_edits(card, keep/remove/edit/add)`, `TaskCard.to_job_spec()` | `employer.JobSpec`, `employer.Task` |
| `skills.py` | `skills_for(card)`: stored ESCO skills for playbook tasks, live mapping for new ones, merged per URI | `EmployerFlow.map_spec()` |
| `prepare.py` | Run once by whoever has the index + key: maps all playbook tasks, writes `playbook_esco.json`, reports phrases that mapped to nothing so they can be fixed | `EmployerFlow.map_spec()` |
| `agent.py` | Orchestration, below | — |
| `__main__.py` | Terminal demo; `--answers A,neither,B` for non-interactive runs; `--out` writes the output file | — |
| `llm.py` | Optional: rewords ideas for the company, matches free text to a root cause | Same signature as `SkillMapper.generate()` |

```python
agent = BizDevAgent()                       # generator optional
profile   = agent.profile("1234560-4")
diagnosis = agent.diagnose(profile)         # -> diagnosis.current_question
diagnosis = agent.answer(diagnosis, "A")
shift, ideas = agent.ideas(profile, diagnosis)
card      = agent.task_card(diagnosis)      # proposed tasks
card      = agent.edit(card, remove=[2], add=["Train the team in the new playbook"])
needs     = agent.skills(profile, diagnosis, card)   # -> SkillRequirements (the output)
needs.save("needs.json")
```

Every method takes and returns pydantic models, so a web front end can call one step per request.

---

## 4. Playbook (`data/playbook.json`)

```jsonc
{
  "sectors":     { "<sector>": "display name" },
  "hypotheses":  { "<sector>": [ { "id", "prompt", "a": {label, root_cause}, "b": {label, root_cause} } ] },
  "root_causes": { "<id>": {
      "name", "keywords": [...], "current", "target", "benefit",
      "ideas": [ {title, why, first_step} ],
      "tasks": [ { "id", "task", "skills": ["ESCO-style phrase", ...], "priority" } ] } }
}
```

Demo content: 2 A/B questions per sector → 9 root causes (key-person dependency, network-only sales,
process debt in delivery, admin overload, custom work vs product, weak digital channel, production
bottleneck, know-how held by seniors, project overruns), each with 3 ideas and 3 tasks. The deck's
professional-services path ("Founders run out of time" → "Productize service delivery") is the first one.

**Preparing the skills once:** `python -m bizdev.prepare` sends every playbook task through
`EmployerFlow.map_spec()` and writes `playbook_esco.json` (task id → ESCO skills in `map_spec` format).
It lists tasks whose phrases mapped to nothing or to an unexpected skill. The team fixes the phrase and
reruns. After that, the demo needs neither Gemini nor the index for playbook tasks, and the result is the
same every time.

---

## 5. Output contract (hand-off to further development)

`SkillRequirements`, saved as JSON. Skill entries use **exactly the format `EmployerFlow.map_spec()` returns
today**, and the ESCO URIs are the same IDs stored in `applicant.ApplicantProfile`, so later code can read
company needs and candidate profiles side by side.

```jsonc
{
  "schema": "bizdev.skill_requirements/v1",
  "created": "2026-11-14T14:30:00+02:00",
  "company": { "business_id": "1234560-4", "name": "Demo Consulting Oy", "sector_family": "professional_services" },
  "need": {
    "root_cause": "manual_delivery",
    "name": "Process debt in delivery",
    "current": "Service delivery is manual, ad hoc and relies on key people's tacit knowledge.",
    "target": "The service is productized into repeatable modules, so delivery can be delegated."
  },
  "ideas": [ { "title": "...", "why": "...", "first_step": "..." } ],
  "tasks": [
    { "id": "t1", "task": "Audit current manual delivery projects and identify recurring workflow stages",
      "priority": "must_have", "origin": "playbook", "status": "mapped" },
    { "id": "t4", "task": "Train the team in the new playbook",
      "priority": "learnable", "origin": "company", "status": "unmapped" }
  ],
  "skills": [
    { "uri": "http://data.europa.eu/esco/skill/…", "label": "…", "skillType": "skill/competence",
      "reuseLevel": "cross-sector", "priority": "must_have", "confidence": "high", "probability": 0.91,
      "tasks": ["Audit current manual delivery projects …"], "sources": ["bizdev:manual_delivery"] }
  ],
  "job_spec": { /* employer.JobSpec, so existing employer-side code can take it as is */ }
}
```

What downstream code can rely on:
- `skills[].uri` is always an ESCO skill URI from the same index the applicant side uses.
- `skills[].priority` follows the existing values (`must_have` / `learnable` / `nice_to_have`); a skill used by
  several tasks takes the strongest priority (same rule as `employer.map_spec`).
- `skills[].tasks` says why each skill is needed (traceability for recruiters and applicants).
- `tasks[].status == "unmapped"` marks company-written tasks that still need mapping.
- `schema` is versioned; fields are only added, never renamed, within `v1`.

---

## 6. Build order

| # | Task | Done when |
|---|---|---|
| 1 | `playbook.json` with the deck's professional-services path, `models.py` incl. `SkillRequirements` | Output contract fixed and agreed with whoever builds matching |
| 2 | `diagnosis.py`, `ideas.py`, `taskcard.py`, `agent.py`, `__main__.py` | Sample company → A/B → ideas → confirmed tasks, offline |
| 3 | `prepare.py` + `skills.py` | Running prepare once gives ESCO skills; demo writes `needs.json` offline |
| 4 | Rest of the playbook (all 8 sectors), rerun prepare | Every sample company gets its own path and skills |
| 5 | `sources.py` PRH lookup, live mapping of company-written tasks | Real Business ID works; added tasks get skills when the pipeline is available |
| 6 | Optional `llm.py`: idea rewording, free-text → root cause | Ideas mention the company's own offering |

Steps 1–3 give a complete demo: company in, needed skills out.
