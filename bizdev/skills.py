"""Step 5: confirmed tasks -> ESCO skills.

  Playbook tasks:  each skill phrase is looked up in playbook_esco.json (written once by prepare.py).
                   Offline and the same every time.
  Company tasks:   live. extract_statements(role="employer") turns the task text into skill phrases,
                   then EmployerFlow.map_spec() maps them, as on the employer side.
  Playbook phrases missing from playbook_esco.json (prepare not rerun) are also mapped live.

Live mapping needs GEMINI_API_KEY and the ESCO index. Without them, those tasks come out with
status "unmapped" so later code knows to map them. `live_unavailable_reason()` says why, so callers
can warn the company before it writes its own tasks.

Skills are merged per URI with the same rule as employer.map_spec: a skill used by several tasks takes
the strongest priority, "high" confidence wins, and the highest probability is kept."""

import os

from employer import PRIORITY_ORDER, EmployerFlow, JobSpec, Task

SKILL_FIELDS = ("uri", "label", "skillType", "reuseLevel", "confidence", "probability")


class LiveMappingUnavailable(RuntimeError):
    pass


def live_unavailable_reason():
    """None if live mapping can run, otherwise a sentence saying what is missing.
    Checked before SkillMapper is built, because SkillMapper exits the process when the key is missing."""
    from build_index import META_PATH, VECTORS_PATH
    from search import DEPLOY_DIR, default_backend
    missing = []
    if not os.environ.get("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY is not set")
    if default_backend() == "gemini":
        if not (DEPLOY_DIR / "search.npy").exists():
            missing.append(f"the deploy index is missing ({DEPLOY_DIR}/; run build_deploy_index.py)")
    elif not VECTORS_PATH.exists() or not META_PATH.exists():
        missing.append(f"the ESCO index is missing ({VECTORS_PATH.parent}/skills.npy and skills_meta.json; "
                       "run build_index.py or copy them from a teammate)")
    return "; ".join(missing) or None


class LiveMapper:
    """Builds the SkillMapper only when a task actually needs live mapping (it loads the index and the
    embedding model, which takes seconds)."""

    def __init__(self, mapper=None):
        self._mapper = mapper
        self.reason = None if mapper is not None else live_unavailable_reason()

    @property
    def available(self):
        return self.reason is None

    def get(self):
        if self._mapper is None:
            if self.reason:
                raise LiveMappingUnavailable(self.reason)
            from map_skills import SkillMapper
            self._mapper = SkillMapper()
        return self._mapper


def _skill(entry):
    return {k: entry.get(k) for k in SKILL_FIELDS}


def _add_skill(skills, new):
    """Append to a task's skill list, merging a URI that is already there."""
    for s in skills:
        if s["uri"] == new["uri"]:
            if new["confidence"] == "high":
                s["confidence"] = "high"
            if new.get("probability") is not None:
                s["probability"] = max(s.get("probability") or 0, new["probability"])
            return
    skills.append(dict(new))


def map_tasks(card, stored=None, live=None):
    """-> {task_id: {"phrases": [...], "skills": [skill, ...], "status": "mapped" | "unmapped" | "no_match"}}.

    stored: load_playbook_esco() output (or None). live: a LiveMapper, or None to stay offline.
    Gemini errors propagate (google.genai.errors.APIError); the caller decides whether to retry
    or continue offline."""
    stored_phrases = (stored or {}).get("phrases", {})
    result, todo = {}, {}  # todo: task_id -> phrases still to map live (None = extract from the text first)
    for t in card.tasks:
        r = result[t.id] = {"phrases": list(t.skills), "skills": []}
        if t.origin == "playbook":
            for phrase in t.skills:
                for s in stored_phrases.get(phrase, []):
                    _add_skill(r["skills"], s)
            missing = [p for p in t.skills if p not in stored_phrases]
            if missing:
                todo[t.id] = missing
        else:
            todo[t.id] = list(t.skills) or None

    if todo and live is not None and live.available:
        mapper = live.get()
        by_id = {t.id: t for t in card.tasks}
        spec_tasks = []
        for task_id, phrases in todo.items():
            t = by_id[task_id]
            if phrases is None:
                phrases = list(dict.fromkeys(
                    s.esco_phrase for s in mapper.extract_statements(t.task, role="employer")))
                result[task_id]["phrases"] = phrases
            if phrases:
                # source = task id, so map_spec's merged `sources` tell which task each skill came from.
                spec_tasks.append(Task(task=t.task, priority=t.priority, source=task_id, skills=phrases))
        if spec_tasks:
            spec = JobSpec(title="bizdev", summary="", tasks=spec_tasks, flags=[])
            for entry in EmployerFlow(mapper).map_spec(spec):
                for task_id in entry["sources"]:
                    _add_skill(result[task_id]["skills"], _skill(entry))
        todo = {}

    for task_id, r in result.items():
        r["status"] = "unmapped" if task_id in todo else ("mapped" if r["skills"] else "no_match")
    return result


def merge(card, per_task):
    """Per-task skills -> one list in map_spec format, must-haves first, then by confidence and probability."""
    source = f"bizdev:{card.root_cause}"
    by_uri = {}
    for t in card.tasks:
        for s in per_task[t.id]["skills"]:
            e = by_uri.setdefault(s["uri"], {**_skill(s), "priority": t.priority, "tasks": [], "sources": [source]})
            if PRIORITY_ORDER[t.priority] < PRIORITY_ORDER[e["priority"]]:
                e["priority"] = t.priority
            if s["confidence"] == "high":
                e["confidence"] = "high"
            if s.get("probability") is not None:
                e["probability"] = max(e["probability"] or 0, s["probability"])
            if t.task not in e["tasks"]:
                e["tasks"].append(t.task)
    return sorted(by_uri.values(),
                  key=lambda e: (PRIORITY_ORDER[e["priority"]], e["confidence"] != "high", -(e["probability"] or 0)))
