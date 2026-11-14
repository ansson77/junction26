# Junction 2026: Espoo skills matching

Helou pöytäläiset! The vision is in [PLAN.md](PLAN.md) and the background research in [RESEARCH.md](RESEARCH.md).

## Free text → ESCO skills

Turns a CV, job ad or task list (in any language) into [ESCO](https://esco.ec.europa.eu/) skill codes, with the sentence that supports each skill.

```
text ──► 1. Extract ──► 2. Retrieve ──► 3. Select ──► ESCO skills + evidence
         Gemini         local           Gemini
                        embeddings      Decisions API
```

1. **Extract** (`gemini-flash-latest`): splits the text into short, English, ESCO-style statements ("perform bookkeeping"), each with the exact quote it came from. There are separate prompts for applicants and employers.
2. **Retrieve** (`multilingual-e5-small`, runs locally): finds the 15 most similar of the 13,955 ESCO skills for each statement. These candidates are similar in wording but not necessarily correct.
3. **Select** (`gemini-decision-1`): asks one yes/no question per statement–candidate pair and gets a calibrated probability. Probability ≥ 0.8 is `high`, ≥ 0.5 is `medium`, and anything lower is dropped. The model can only choose from the candidates, so it can't invent skill codes.

| File | What it does |
|---|---|
| [build_index.py](build_index.py) | Embeds `esco/skills_en.csv` once and saves `esco/skills.npy` and `esco/skills_meta.json` |
| [search.py](search.py) | Step 2 on its own: embedding search over the index |
| [map_skills.py](map_skills.py) | The full pipeline, steps 1–3 |

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

## Usage

```bash
.venv/bin/python map_skills.py "Pidin kirjanpitoa perheen kaupassa ja koulutin 3 uutta työntekijää"
.venv/bin/python map_skills.py --file job_ad.txt --role employer --json
.venv/bin/python map_skills.py "..." --debug    # also show statements and search candidates
.venv/bin/python search.py                      # interactive search, no Gemini needed
```

From Python: `SkillMapper().map_text(text, role="applicant")` returns a list of `{uri, label, skillType, confidence, probability, evidence}`.
