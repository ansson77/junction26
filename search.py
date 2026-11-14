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

import numpy as np

from build_index import META_PATH, QUERY_PREFIX, VECTORS_PATH

SKILL_TYPES = {"skill": "skill/competence", "knowledge": "knowledge"}


class SkillIndex:
    def __init__(self):
        if not VECTORS_PATH.exists():
            raise SystemExit(f"{VECTORS_PATH} not found. Run build_index.py first.")
        self.vectors = np.load(VECTORS_PATH)
        with open(META_PATH, encoding="utf-8") as f:
            meta = json.load(f)
        self.skills = meta["skills"]
        self.model_name = meta["model"]
        self._model = None  # loaded on first query

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def embed(self, texts):
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
        scores = self.embed(texts) @ self.vectors.T  # cosine similarity (vectors are normalised)
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
