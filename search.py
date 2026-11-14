"""Find the ESCO skills that best match a piece of free text.

Usage:
    .venv/bin/python search.py "kept the books for my family's shop"
    .venv/bin/python search.py "pidin kirjanpitoa" -k 5 --type skill
    .venv/bin/python search.py            # interactive mode, model stays loaded

From code:
    from search import SkillIndex
    index = SkillIndex()
    index.search("built ETL pipelines in Airflow", k=10)

Works best on short, single-skill statements ("built data pipelines"),
not whole CVs. Split long text into statements first (e.g. with an LLM).
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DEPLOY_DIR = ROOT / "index"   # committed; built by build_deploy_index.py

SKILL_TYPES = {"skill": "skill/competence", "knowledge": "knowledge"}


def default_backend():
    """SKILL_INDEX=gemini|local. Default: gemini (the committed index/, same as the deployed site).
    local = the full e5 index in esco/ with sentence-transformers (needs requirements-local.txt)."""
    return os.environ.get("SKILL_INDEX") or ("gemini" if (DEPLOY_DIR / "search.npy").exists() else "local")


class SkillIndex:
    """ESCO skill search. Two vector sets:
      search_vectors  what queries are compared with (search / retrieval)
      vectors         multilingual-e5-small vectors, used for skill-to-skill similarity (matching.py)
    With the local backend both are the e5 vectors from esco/; with the gemini backend the search
    vectors are Gemini embeddings and the query is embedded through the Gemini API (no PyTorch)."""

    def __init__(self, backend=None):
        self.backend = backend or default_backend()
        if self.backend == "gemini":
            meta = json.loads((DEPLOY_DIR / "skills_meta.json").read_text(encoding="utf-8"))
            match = np.load(DEPLOY_DIR / "match.npy").astype(np.float32)
            search = np.load(DEPLOY_DIR / "search.npy").astype(np.float32)
            self.model_name = meta["search_model"]
            self._dim = meta["search_dim"]
        else:
            from build_index import META_PATH, VECTORS_PATH
            if not VECTORS_PATH.exists():
                raise SystemExit(f"{VECTORS_PATH} not found. Run build_index.py first.")
            match = search = np.load(VECTORS_PATH)
            with open(META_PATH, encoding="utf-8") as f:
                meta = json.load(f)
            self.model_name = meta["model"]
        # The ESCO CSV lists a few skills twice (e.g. 'SQL'). Keep the first row per URI so
        # search never returns the same skill twice.
        seen, keep = set(), []
        for i, s in enumerate(meta["skills"]):
            if s["uri"] not in seen:
                seen.add(s["uri"])
                keep.append(i)
        self.vectors = match[keep]
        self.search_vectors = self.vectors if search is match else search[keep]
        self.skills = [meta["skills"][i] for i in keep]
        self._model = None  # loaded on first query

    @property
    def model(self):
        if self._model is None:
            if self.backend == "gemini":
                from google import genai
                self._model = genai.Client()
            else:
                from build_index import load_model
                self._model = load_model(self.model_name)
        return self._model

    def embed(self, texts):
        if self.backend == "gemini":
            from google.genai import types
            r = self.model.models.embed_content(
                model=self.model_name, contents=list(texts),
                config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY", output_dimensionality=self._dim))
            v = np.array([e.values for e in r.embeddings], dtype=np.float32)
            return v / np.linalg.norm(v, axis=1, keepdims=True)
        from build_index import QUERY_PREFIX
        return self.model.encode(
            [QUERY_PREFIX + t for t in texts],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

    def search(self, text, k=10, skill_type=None):
        """Return the top-k skills for one statement, best first.

        skill_type: None, "skill" or "knowledge".
        """
        return self.search_many([text], k=k, skill_type=skill_type)[0]

    def search_many(self, texts, k=10, skill_type=None):
        """Batch version of search(): one result list per input text."""
        if not texts:
            return []
        scores = self.embed(texts) @ self.search_vectors.T  # cosine similarity (vectors are normalised)
        if skill_type:
            wanted = SKILL_TYPES[skill_type]
            mask = np.array([s["skillType"] == wanted for s in self.skills])
            scores[:, ~mask] = -np.inf

        results = []
        for row in scores:
            top = np.argpartition(-row, min(k, len(row) - 1))[:k]
            top = top[np.argsort(-row[top])]
            results.append([
                {**self.skills[i], "score": float(row[i])}
                for i in top if np.isfinite(row[i])
            ])
        return results


def print_results(results):
    for r in results:
        print(f"  {r['score']:.3f}  {r['label']:<45} [{r['skillType']}, {r['reuseLevel']}]")
        print(f"         {r['uri']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text", nargs="?", help="text to match (omit for interactive mode)")
    parser.add_argument("-k", type=int, default=10, help="number of results (default 10)")
    parser.add_argument("--type", choices=SKILL_TYPES, help="only return skills or only knowledge")
    parser.add_argument("--json", action="store_true", help="print raw JSON instead of a table")
    args = parser.parse_args()

    index = SkillIndex()

    def run(text):
        results = index.search(text, k=args.k, skill_type=args.type)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_results(results)

    if args.text:
        run(args.text)
        return

    print("Type a statement and press Enter (Ctrl-D to quit).")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            break
        if text:
            run(text)


if __name__ == "__main__":
    main()
