# Deploying to Vercel + Supabase

The whole site (FastAPI backend + built React frontend) deploys as **one Vercel project**. The data lives in **Supabase Postgres**.

## What is different from running it locally

| | Local (default) | Vercel |
|---|---|---|
| Skill search (query embedding) | Gemini API (`gemini-embedding-001`) against `index/search.npy` | same |
| Skill similarity in matching | e5 vectors in `index/match.npy` (same numbers as `esco/skills.npy`) | same |
| Database | `data/app.db` (SQLite) | Supabase Postgres (`DATABASE_URL`) |
| Validation-question cache | `data/validation_questions.json` | that file (read-only) + `validation_questions` table |

PyTorch and the local e5 model don't fit a serverless function, so search embeds the query with Gemini instead. The skills' Gemini vectors were computed once by `build_deploy_index.py` and are committed in `index/` (about 40 MB). Matching still uses the original e5 vectors, so the calibration in `matching.py` is unchanged. `SKILL_INDEX=local` switches search back to the local e5 model (needs `requirements-local.txt`).

## 1. Supabase

1. Create a project. Pick the **Frankfurt (eu-central-1)** region, which matches `"regions": ["fra1"]` in `vercel.json`. If you pick another region, change `vercel.json` to the nearest [Vercel region](https://vercel.com/docs/regions). Every request makes several database queries, so the two must be close.
2. **Connect → Connection string → Transaction pooler** (port **6543**). Copy the URI and fill in the database password:
   `postgresql://postgres.<ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:6543/postgres`
3. Tables are created automatically on first connect (with Row Level Security on, so Supabase's public REST API can't read them). You can also run `supabase/schema.sql` in the SQL editor.
4. Optional: copy the current local data (mock jobs, applicants, invites) into Supabase:
   ```bash
   DATABASE_URL="postgresql://...:6543/postgres" .venv/bin/python migrate_to_supabase.py
   ```

## 2. Vercel

1. Push this repo to GitHub, then in Vercel: **Add New → Project → import the repo**. Keep the root directory at the repo root. Vercel detects FastAPI from `pyproject.toml` (`entrypoint = "api:app"`, Python from `.python-version`).
2. **Environment variables** (Production and Preview):
   - `GEMINI_API_KEY`: your Gemini key
   - `DATABASE_URL`: the Supabase pooler URI from step 1
3. Deploy. The build runs `cd frontend && npm ci && npm run build` (from `pyproject.toml`), and `api.py` serves `frontend/dist` at `/`.
4. Check `https://<project>.vercel.app/api/health`. It should report `"esco_skills": 13934`.

Or from the terminal: `npx vercel` (link and preview), then `npx vercel --prod`. Set the env vars with `npx vercel env add GEMINI_API_KEY` and `npx vercel env add DATABASE_URL`.

## Limits and caveats

- **No login.** Anyone with the URL can use the site, read validation answers and spend the Gemini quota. Share the URL only with participants, and delete the data after the event (Supabase: `TRUNCATE jobs, applicants, validation_questions CASCADE;`).
- AI steps (suggest, clarify, skills) take about 10–30 s. `maxDuration` is 300 s.
- The first request after a cold start loads the index (about 1 s).

## Rebuilding the deploy index

Only needed if the ESCO data or the e5 index changes (needs `esco/skills.npy`, `esco/skills_meta.json` and `GEMINI_API_KEY`):
```bash
.venv/bin/python build_deploy_index.py   # ~5 min, resumable
```
