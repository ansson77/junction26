"""Copy the local SQLite database (data/app.db) into Supabase Postgres, row by row.

Rows that already exist in Postgres are skipped, so it is safe to run twice.

Usage:
    DATABASE_URL="postgresql://..." .venv/bin/python migrate_to_supabase.py
    DATABASE_URL="postgresql://..." .venv/bin/python migrate_to_supabase.py --db other.db
"""

import argparse

import db

# Parents before children (foreign keys).
TABLES = ["jobs", "job_skills", "applicants", "applicant_skills", "invites"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(db.DB_PATH), help="SQLite file to copy (default data/app.db)")
    args = parser.parse_args()
    if not db.DATABASE_URL:
        raise SystemExit("Set DATABASE_URL to the Supabase connection string first.")

    src = db.connect(args.db)
    dst = db.connect()
    try:
        with dst:
            for table in TABLES:
                rows = src.execute(f"SELECT * FROM {table}").fetchall()
                if not rows:
                    print(f"  {table}: 0 rows")
                    continue
                cols = rows[0].keys()
                sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                       "ON CONFLICT DO NOTHING")
                dst.executemany(sql, [tuple(r) for r in rows])
                print(f"  {table}: {len(rows)} rows")
    finally:
        src.close()
        dst.close()
    print("Done.")


if __name__ == "__main__":
    main()
