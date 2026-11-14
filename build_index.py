"""Embed every ESCO skill once and save the vectors for search.py.

Usage:
    .venv/bin/python build_index.py            # full build (~20-25 min on a laptop CPU)
    .venv/bin/python build_index.py --limit 200  # quick smoke test

Outputs (in esco/, which is gitignored):
    skills.npy        float32 [n_skills, dim], L2-normalised
    skills_meta.json  one dict per row of skills.npy (uri, label, type, ...)

The build is resumable: finished chunks are cached in esco/.index_parts/,
so an interrupted run picks up where it left off.
"""

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
ESCO_DIR = ROOT / "esco"
SKILLS_CSV = ESCO_DIR / "skills_en.csv"
VECTORS_PATH = ESCO_DIR / "skills.npy"
META_PATH = ESCO_DIR / "skills_meta.json"
PARTS_DIR = ESCO_DIR / ".index_parts"

# Multilingual, small enough for a laptop CPU. e5 models expect
# "passage: " / "query: " prefixes. If you change the model, rebuild the index.
MODEL_NAME = "intfloat/multilingual-e5-small"
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

CHUNK_SIZE = 1000


def load_model(name=MODEL_NAME):
    """Load the embedding model from the local Hugging Face cache, without
    contacting the Hub (faster, works offline, no HF_TOKEN warning).
    Downloads it only if it isn't cached yet (e.g. a teammate's first run)."""
    from sentence_transformers import SentenceTransformer
    try:
        return SentenceTransformer(name, device="cpu", local_files_only=True)
    except OSError:
        print(f"Model {name} not cached yet, downloading from Hugging Face...")
        return SentenceTransformer(name, device="cpu")


def load_skills(limit=None):
    with open(SKILLS_CSV, newline="", encoding="utf-8") as f:
        rows = [
            r for r in csv.DictReader(f)
            if r["skillType"] and r["status"] == "released"
        ]
    return rows[:limit] if limit else rows


def skill_text(row):
    """The text that represents a skill in vector space."""
    alt = "; ".join(a.strip() for a in row["altLabels"].splitlines() if a.strip())
    parts = [row["preferredLabel"]]
    if alt:
        parts.append(f"Also known as: {alt}")
    if row["description"]:
        parts.append(row["description"])
    return PASSAGE_PREFIX + ". ".join(parts)


def skill_meta(row):
    return {
        "uri": row["conceptUri"],
        "label": row["preferredLabel"],
        "skillType": row["skillType"],  # "skill/competence" or "knowledge"
        "reuseLevel": row["reuseLevel"],  # transversal / cross-sector / sector-specific / occupation-specific
        "altLabels": [a.strip() for a in row["altLabels"].splitlines() if a.strip()],
        "description": row["description"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="only embed the first N skills (for testing)")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    rows = load_skills(args.limit)
    texts = [skill_text(r) for r in rows]
    print(f"{len(rows)} skills to embed with {MODEL_NAME}")

    model = load_model()

    # Cache key includes the model and row count so a changed setup never reuses stale chunks.
    run_dir = PARTS_DIR / f"{MODEL_NAME.replace('/', '__')}_{len(rows)}"
    run_dir.mkdir(parents=True, exist_ok=True)

    start = time.time()
    chunks = []
    for i in range(0, len(texts), CHUNK_SIZE):
        part = run_dir / f"{i:06d}.npy"
        if part.exists():
            chunks.append(np.load(part))
            print(f"  [{i + CHUNK_SIZE:>6}/{len(texts)}] cached")
            continue
        vecs = model.encode(
            texts[i:i + CHUNK_SIZE],
            batch_size=args.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)
        np.save(part, vecs)
        chunks.append(vecs)
        done = min(i + CHUNK_SIZE, len(texts))
        elapsed = time.time() - start
        print(f"  [{done:>6}/{len(texts)}] {elapsed / 60:.1f} min elapsed", flush=True)

    vectors = np.vstack(chunks)
    np.save(VECTORS_PATH, vectors)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump({"model": MODEL_NAME, "skills": [skill_meta(r) for r in rows]}, f, ensure_ascii=False)

    print(f"Saved {vectors.shape} to {VECTORS_PATH.relative_to(ROOT)} "
          f"and metadata to {META_PATH.relative_to(ROOT)} in {(time.time() - start) / 60:.1f} min")


if __name__ == "__main__":
    main()
