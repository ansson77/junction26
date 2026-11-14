-- Supabase schema for the deployed site. Run once in the Supabase SQL editor (the backend also
-- creates missing tables itself on first connect, so this is optional, except for the RLS lines).
-- Same tables as db.py's SQLite schema.

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    tasks_json  TEXT NOT NULL,   -- list of employer.Task
    flags_json  TEXT NOT NULL    -- list of employer.Flag
);

CREATE TABLE IF NOT EXISTS job_skills (
    job_id      TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    uri         TEXT NOT NULL,   -- ESCO skill URI
    label       TEXT NOT NULL,
    skill_type  TEXT NOT NULL,
    priority    TEXT NOT NULL,   -- must_have / learnable / nice_to_have
    points      INTEGER NOT NULL CHECK (points >= 1),
    tasks_json  TEXT NOT NULL,   -- tasks that need this skill
    PRIMARY KEY (job_id, uri)
);
CREATE INDEX IF NOT EXISTS job_skills_uri ON job_skills(uri);

CREATE TABLE IF NOT EXISTS applicants (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL
    -- deliberately no name, contact, photo, age or nationality (blind first contact)
);

CREATE TABLE IF NOT EXISTS applicant_skills (
    applicant_id        TEXT NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    uri                 TEXT NOT NULL,   -- ESCO skill URI
    label               TEXT NOT NULL,
    skill_type          TEXT NOT NULL,
    origin              TEXT NOT NULL,   -- suggested / added
    points              INTEGER NOT NULL CHECK (points >= 1),
    validation_question TEXT NOT NULL,
    validation_answer   TEXT NOT NULL,   -- applicant's own words; for recruiters only, never sent to an LLM
    PRIMARY KEY (applicant_id, uri)
);
CREATE INDEX IF NOT EXISTS applicant_skills_uri ON applicant_skills(uri);

-- Applicants a company has invited to the event's networking session, per job.
-- A recruiter's decision; replacing or deleting the job or the applicant removes it.
CREATE TABLE IF NOT EXISTS invites (
    job_id        TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    applicant_id  TEXT NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (job_id, applicant_id)
);

-- Validation question per ESCO skill and language (key "<uri>|<language>"). Postgres only:
-- locally applicant.py caches them in data/validation_questions.json.
CREATE TABLE IF NOT EXISTS validation_questions (
    key       TEXT PRIMARY KEY,
    question  TEXT NOT NULL
);

-- Row Level Security on, with no policies: Supabase's public REST API (anon key) can't read or
-- write these tables. The backend connects as the postgres role, which bypasses RLS.
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE applicants ENABLE ROW LEVEL SECURITY;
ALTER TABLE applicant_skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE validation_questions ENABLE ROW LEVEL SECURITY;
