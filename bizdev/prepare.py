"""One-off: map every skill phrase in playbook.json to ESCO skills and store them in playbook_esco.json.
After this, playbook tasks need neither Gemini nor the index, and give the same skills every time.

Needs GEMINI_API_KEY and the ESCO index. Only phrases not yet in playbook_esco.json are mapped,
so after editing the playbook just run it again. --all remaps everything.

    .venv/bin/python -m bizdev.prepare
    .venv/bin/python -m bizdev.prepare --all

Check the report: fix phrases that map to nothing or to the wrong skill in playbook.json, then rerun."""

import argparse
import json
from datetime import datetime

from .skills import live_unavailable_reason


def playbook_phrases(playbook):
    """{phrase: first task text that uses it} over all root causes."""
    phrases = {}
    for rc in playbook["root_causes"].values():
        for t in rc["tasks"]:
            for p in t["skills"]:
                phrases.setdefault(p, t["task"])
    return phrases


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="remap every phrase, not only new ones")
    args = parser.parse_args()

    reason = live_unavailable_reason()
    if reason:
        raise SystemExit(f"Can't prepare the playbook: {reason}.")

    from employer import EmployerFlow, JobSpec, Task
    from map_skills import SkillMapper

    from .skills import SKILL_FIELDS
    from .sources import PLAYBOOK_ESCO_PATH, load_playbook, load_playbook_esco

    phrases = playbook_phrases(load_playbook())
    old = (load_playbook_esco() or {}).get("phrases", {})
    stored = {} if args.all else {p: s for p, s in old.items() if p in phrases}
    todo = [p for p in phrases if p not in stored]
    print(f"{len(phrases)} phrases in the playbook, {len(todo)} to map.")

    if todo:
        # One task per phrase, so each skill can be traced to its phrase via map_spec's `sources`.
        spec = JobSpec(title="bizdev playbook", summary="", flags=[], tasks=[
            Task(task=phrases[p], priority="must_have", source=p, skills=[p]) for p in todo])
        mapped = {p: [] for p in todo}
        for entry in EmployerFlow(SkillMapper()).map_spec(spec):
            for p in entry["sources"]:
                mapped[p].append({k: entry.get(k) for k in SKILL_FIELDS})
        stored.update(mapped)

    stored = {p: stored[p] for p in phrases}  # playbook order; drops phrases no longer used
    PLAYBOOK_ESCO_PATH.write_text(json.dumps({
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "phrases": stored,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {PLAYBOOK_ESCO_PATH}\n")

    for p in phrases:
        labels = ", ".join(f"{s['label']} ({s['confidence']})" for s in stored[p])
        mark = "  " if stored[p] else "!!"
        print(f"{mark} {p:<45} -> {labels or 'NOTHING: reword this phrase in playbook.json'}")


if __name__ == "__main__":
    main()
