"""Storage for job profiles (employers) and applicant profiles.

Two backends with the same functions:
  - Postgres (Supabase) when the DATABASE_URL environment variable is set: the deployed site.
    Use Supabase's connection pooler URL (port 6543). Schema: supabase/schema.sql.
  - SQLite otherwise: one local file (data/app.db, gitignored), no server. Profiles go in and come out as the
validated Pydantic models (employer.JobProfile, applicant.ApplicantProfile), so the database
never holds an allocation that breaks the point rules.

Skills are stored one row per skill with their points, indexed by ESCO URI, so matching can
look up "who has skill X" directly.

Usage from code (one connection per request/thread):
    import db
    with db.connect() as conn:
        job_id = db.save_job(conn, job_profile)
        job = db.get_job(conn, job_id)
        applicant_id = db.save_applicant(conn, applicant_profile)

Terminal:
    .venv/bin/python db.py list
    .venv/bin/python db.py show <id>
    .venv/bin/python db.py delete <id>

Privacy: applicant rows have no name, contact details, age or nationality. Validation answers
can still contain personal details, so delete the database after the event.
"""

import json
import os
import sqlite3
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "app.db"

SCHEMA = """
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

-- Languages the applicant speaks (self-declared, outside the point budget). Employers filter on them.
CREATE TABLE IF NOT EXISTS applicant_languages (
    applicant_id  TEXT NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    language      TEXT NOT NULL,
    position      INTEGER NOT NULL,   -- order the applicant listed them in
    PRIMARY KEY (applicant_id, language)
);

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
"""

DATABASE_URL = os.environ.get("DATABASE_URL")
_pool = None
_pool_lock = threading.Lock()


class PgConnection:
    """psycopg connection with the small sqlite3 surface db.py uses: execute/executemany with `?`
    placeholders, dict rows, `with conn:` = one transaction, close() returns it to the pool."""
    pg = True

    def __init__(self, pool):
        self._pool = pool
        self._conn = pool.getconn()

    def execute(self, sql, params=()):
        return self._conn.execute(sql.replace("?", "%s"), params)

    def executemany(self, sql, rows):
        with self._conn.cursor() as cur:
            cur.executemany(sql.replace("?", "%s"), rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()

    def close(self):
        if self._conn is not None:
            self._conn.rollback()  # end read-only transactions quietly (writes are committed by `with conn:`)
            self._pool.putconn(self._conn)
            self._conn = None


def _pg_pool():
    """One small pool per process (Vercel reuses warm instances), created on first use."""
    global _pool
    with _pool_lock:
        if _pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            # prepare_threshold=None: Supabase's transaction pooler can't keep prepared statements.
            _pool = ConnectionPool(DATABASE_URL, min_size=0, max_size=4, open=True,
                                   kwargs={"row_factory": dict_row, "prepare_threshold": None})
            import atexit
            atexit.register(_pool.close)
            with _pool.connection() as conn:
                conn.execute(SCHEMA)
                # RLS on with no policies: Supabase's public REST API (anon key) can't touch these
                # tables. This backend connects as the postgres role, which bypasses RLS.
                for table in ("jobs", "job_skills", "applicants", "applicant_skills", "applicant_languages",
                              "invites", "validation_questions"):
                    conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    return _pool


def connect(path=None):
    """Open (and if needed create) the database. Use one connection per request or thread.
    As a context manager it commits on success and rolls back on error (it does not close).
    An explicit `path` always means SQLite (tests); otherwise Postgres if DATABASE_URL is set."""
    if path is None and DATABASE_URL:
        return PgConnection(_pg_pool())
    path = path or DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
    conn.executescript(SCHEMA)
    return conn


def _concat(conn):
    return "string_agg" if getattr(conn, "pg", False) else "GROUP_CONCAT"


# ---------- Validation question cache (Postgres) ----------

def get_questions(conn, keys):
    """{key: question} for the keys that are cached."""
    keys = list(keys)
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    return {r["key"]: r["question"] for r in conn.execute(
        f"SELECT key, question FROM validation_questions WHERE key IN ({marks})", keys)}


def save_questions(conn, questions):
    """Cache {key: question}. The first question stored for a key wins, so everyone gets the same one."""
    with conn:
        conn.executemany("INSERT INTO validation_questions (key, question) VALUES (?, ?) ON CONFLICT DO NOTHING",
                         list(questions.items()))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id():
    return str(uuid.uuid4())


# ---------- Jobs ----------

def save_job(conn, job, job_id=None):
    """Store a JobProfile. Pass job_id to replace an existing job. Returns the id."""
    job_id = job_id or _new_id()
    with conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.execute(
            "INSERT INTO jobs (id, created_at, title, summary, tasks_json, flags_json) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, _now(), job.title, job.summary,
             json.dumps([t.model_dump() for t in job.tasks], ensure_ascii=False),
             json.dumps([f.model_dump() for f in job.flags], ensure_ascii=False)),
        )
        conn.executemany(
            "INSERT INTO job_skills (job_id, uri, label, skill_type, priority, points, tasks_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(job_id, s.uri, s.label, s.skillType, s.priority, s.points, json.dumps(s.tasks, ensure_ascii=False))
             for s in job.skills],
        )
    return job_id


def get_job(conn, job_id):
    """Return the JobProfile, or None if there is no such job."""
    from employer import JobProfile

    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    skills = conn.execute(
        "SELECT * FROM job_skills WHERE job_id = ? ORDER BY points DESC, label", (job_id,)
    ).fetchall()
    return JobProfile(
        title=row["title"],
        summary=row["summary"],
        tasks=json.loads(row["tasks_json"]),
        flags=json.loads(row["flags_json"]),
        skills=[{"uri": s["uri"], "label": s["label"], "skillType": s["skill_type"], "priority": s["priority"],
                 "points": s["points"], "tasks": json.loads(s["tasks_json"])} for s in skills],
    )


def list_jobs(conn):
    return [dict(r) for r in conn.execute(
        "SELECT j.id, j.created_at, j.title, COUNT(s.uri) AS n_skills "
        "FROM jobs j LEFT JOIN job_skills s ON s.job_id = j.id GROUP BY j.id ORDER BY j.created_at DESC"
    )]


def delete_job(conn, job_id):
    with conn:
        return conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,)).rowcount > 0


def job_points(conn, job_id):
    """{uri: points} for one job: the employer's weighted requirements, ready for matching."""
    return {r["uri"]: r["points"] for r in conn.execute(
        "SELECT uri, points FROM job_skills WHERE job_id = ?", (job_id,))}


# ---------- Applicants ----------

def save_applicant(conn, profile, applicant_id=None):
    """Store an ApplicantProfile. Pass applicant_id to replace an existing one. Returns the id."""
    applicant_id = applicant_id or _new_id()
    with conn:
        conn.execute("DELETE FROM applicants WHERE id = ?", (applicant_id,))
        conn.execute("INSERT INTO applicants (id, created_at) VALUES (?, ?)", (applicant_id, _now()))
        conn.executemany(
            "INSERT INTO applicant_skills (applicant_id, uri, label, skill_type, origin, points, "
            "validation_question, validation_answer) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(applicant_id, s.uri, s.label, s.skillType, s.origin, s.points, s.validation_question, s.validation_answer)
             for s in profile.skills],
        )
        conn.executemany(
            "INSERT INTO applicant_languages (applicant_id, language, position) VALUES (?, ?, ?)",
            [(applicant_id, lang, i) for i, lang in enumerate(profile.languages)],
        )
    return applicant_id


def get_applicant(conn, applicant_id):
    """Return the ApplicantProfile, or None if there is no such applicant."""
    from applicant import ApplicantProfile

    if conn.execute("SELECT 1 FROM applicants WHERE id = ?", (applicant_id,)).fetchone() is None:
        return None
    skills = conn.execute(
        "SELECT * FROM applicant_skills WHERE applicant_id = ? ORDER BY points DESC, label", (applicant_id,)
    ).fetchall()
    languages = [r["language"] for r in conn.execute(
        "SELECT language FROM applicant_languages WHERE applicant_id = ? ORDER BY position", (applicant_id,))]
    return ApplicantProfile(languages=languages, skills=[
        {"uri": s["uri"], "label": s["label"], "skillType": s["skill_type"], "origin": s["origin"],
         "points": s["points"], "validation_question": s["validation_question"],
         "validation_answer": s["validation_answer"]}
        for s in skills
    ])


def list_applicants(conn):
    rows = [dict(r) for r in conn.execute(
        f"SELECT a.id, a.created_at, COUNT(s.uri) AS n_skills, {_concat(conn)}(s.label, ', ') AS skills "
        "FROM applicants a LEFT JOIN applicant_skills s ON s.applicant_id = a.id "
        "GROUP BY a.id ORDER BY a.created_at DESC"
    )]
    languages = {}
    for r in conn.execute("SELECT applicant_id, language FROM applicant_languages ORDER BY applicant_id, position"):
        languages.setdefault(r["applicant_id"], []).append(r["language"])
    for row in rows:
        row["languages"] = languages.get(row["id"], [])
    return rows


def delete_applicant(conn, applicant_id):
    with conn:
        return conn.execute("DELETE FROM applicants WHERE id = ?", (applicant_id,)).rowcount > 0


def applicant_points(conn, uris=None):
    """{applicant_id: {uri: points}} for all applicants, or only the skill rows whose URI is in `uris`
    (e.g. a job's required skills). Applicants with none of those skills are left out."""
    if uris is None:
        rows = conn.execute("SELECT applicant_id, uri, points FROM applicant_skills")
    else:
        uris = list(uris)
        marks = ",".join("?" * len(uris))
        rows = conn.execute(
            f"SELECT applicant_id, uri, points FROM applicant_skills WHERE uri IN ({marks})", uris)
    result = {}
    for r in rows:
        result.setdefault(r["applicant_id"], {})[r["uri"]] = r["points"]
    return result


# ---------- Networking invites ----------

def list_invites(conn, job_id):
    """Applicant ids invited to networking for this job, in the order they were invited."""
    return [r["applicant_id"] for r in conn.execute(
        "SELECT applicant_id FROM invites WHERE job_id = ? ORDER BY created_at, applicant_id", (job_id,))]


def set_invite(conn, job_id, applicant_id, invited=True):
    """Invite (or un-invite) an applicant for a job. Idempotent. The job and the applicant must exist."""
    with conn:
        if invited:
            conn.execute("INSERT INTO invites (job_id, applicant_id, created_at) VALUES (?, ?, ?) "
                         "ON CONFLICT DO NOTHING",
                         # microseconds: list_invites orders by this (Postgres has no rowid)
                         (job_id, applicant_id, datetime.now(timezone.utc).isoformat()))
        else:
            conn.execute("DELETE FROM invites WHERE job_id = ? AND applicant_id = ?", (job_id, applicant_id))


# ---------- CLI ----------

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"list", "show", "delete"}:
        sys.exit(__doc__)
    conn = connect()
    cmd = sys.argv[1]

    if cmd == "list":
        print("Jobs:")
        for j in list_jobs(conn):
            print(f"  {j['id']}  {j['created_at']}  {j['title']} ({j['n_skills']} skills)")
        print("\nApplicants:")
        for a in list_applicants(conn):
            print(f"  {a['id']}  {a['created_at']}  {a['skills']}")
        return

    if len(sys.argv) < 3:
        sys.exit(f"usage: db.py {cmd} <id>")
    item_id = sys.argv[2]

    if cmd == "show":
        item = get_job(conn, item_id) or get_applicant(conn, item_id)
        if item is None:
            sys.exit(f"No job or applicant with id {item_id}")
        print(item.model_dump_json(indent=2))
    elif cmd == "delete":
        if delete_job(conn, item_id) or delete_applicant(conn, item_id):
            print(f"Deleted {item_id}")
        else:
            sys.exit(f"No job or applicant with id {item_id}")


if __name__ == "__main__":
    main()
