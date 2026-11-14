"""Build the compact, committed skill index in index/ that the deployed app (Vercel) uses.

The full local index (esco/, gitignored) needs PyTorch to embed queries, which doesn't fit a
serverless function. The deploy index splits the two jobs embeddings do:

  index/search.npy     float16 [n, 768]  Gemini embeddings (gemini-embedding-001) of every skill.
                                         Search embeds the QUERY with the same Gemini model, so
                                         no local model is needed (search.py).
  index/match.npy      float16 [n, 384]  The existing multilingual-e5-small vectors from esco/skills.npy.
                                         Only skill-to-skill similarity (matching.py) uses them, so
                                         the calibration in matching.py stays valid.
  index/skills_meta.json                 One dict per row (uri, label, type, ...), same order.

Usage (needs GEMINI_API_KEY and an existing esco/skills.npy + esco/skills_meta.json):
    .venv/bin/python build_deploy_index.py            # ~14k skills, a few minutes, resumable
    .venv/bin/python build_deploy_index.py --limit 300
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
ESCO_VECTORS = ROOT / "esco" / "skills.npy"
ESCO_META = ROOT / "esco" / "skills_meta.json"
OUT_DIR = ROOT / "index"
PARTS_DIR = ROOT / "esco" / ".index_parts" / "gemini"

GEMINI_MODEL = "gemini-embedding-001"
GEMINI_DIM = 768
BATCH = 100  # max texts per embed_content call


def skill_text(s):
    parts = [s["label"]]
    if s["altLabels"]:
        parts.append("Also known as: " + "; ".join(s["altLabels"]))
    if s["description"]:
        parts.append(s["description"])
    return ". ".join(parts)


def embed_documents(client, texts):
    from google.genai import types
    for attempt in range(6):
        try:
            r = client.models.embed_content(
                model=GEMINI_MODEL, contents=texts,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=GEMINI_DIM))
            return np.array([e.values for e in r.embeddings], dtype=np.float32)
        except Exception as e:  # rate limits: back off and retry
            wait = 2 ** attempt * 5
            print(f"    {type(e).__name__}: {e}; retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit("Gemini embedding kept failing; rerun to resume.")


def normalise(v):
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    from google import genai
    client = genai.Client()

    meta = json.loads(ESCO_META.read_text(encoding="utf-8"))
    skills = meta["skills"][:args.limit] if args.limit else meta["skills"]
    e5 = np.load(ESCO_VECTORS)[:len(skills)]

    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    texts = [skill_text(s) for s in skills]
    chunks, start = [], time.time()
    for i in range(0, len(texts), BATCH):
        part = PARTS_DIR / f"{i:06d}_{len(texts[i:i + BATCH])}.npy"
        if part.exists():
            chunks.append(np.load(part))
            continue
        vecs = embed_documents(client, texts[i:i + BATCH])
        np.save(part, vecs)
        chunks.append(vecs)
        print(f"  [{i + len(vecs):>6}/{len(texts)}] {time.time() - start:.0f}s", flush=True)

    OUT_DIR.mkdir(exist_ok=True)
    np.save(OUT_DIR / "search.npy", normalise(np.vstack(chunks)).astype(np.float16))
    np.save(OUT_DIR / "match.npy", e5.astype(np.float16))
    (OUT_DIR / "skills_meta.json").write_text(
        json.dumps({"search_model": GEMINI_MODEL, "search_dim": GEMINI_DIM,
                    "match_model": meta["model"], "skills": skills}, ensure_ascii=False),
        encoding="utf-8")
    print(f"Wrote {len(skills)} skills to {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
