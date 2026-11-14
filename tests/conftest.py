"""Tests run offline: the local e5 index (esco/) instead of Gemini query embeddings, and SQLite
instead of Supabase, even when DATABASE_URL is set in the shell."""

import os

os.environ.setdefault("SKILL_INDEX", "local")
os.environ.pop("DATABASE_URL", None)
