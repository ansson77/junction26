"""Step 4: root cause -> proposed tasks; the company keeps, removes, rewrites or adds tasks.

A playbook task keeps its stored skill phrases only while its text is unchanged, word for word.
Any rewrite turns it into a company task, which is mapped from its new text in step 5."""

from employer import JobSpec, Task

from .models import CardTask, TaskCard
from .sources import root_cause


def propose(rc_id):
    rc = root_cause(rc_id)
    return TaskCard(root_cause=rc_id, tasks=[
        CardTask(id=t["id"], task=t["task"], priority=t["priority"], origin="playbook", skills=t["skills"])
        for t in rc["tasks"]
    ])


def _new_id(card):
    used = {t.id for t in card.tasks}
    n = 1
    while f"company.{n}" in used:
        n += 1
    return f"company.{n}"


def apply_edits(card, remove=(), edit=None, add=(), priority=None):
    """remove: task ids. edit: {task_id: new text}. add: texts, or (text, priority) pairs.
    priority: {task_id: "must_have" | "learnable" | "nice_to_have"}. Returns a new TaskCard."""
    card = card.model_copy(deep=True)
    by_id = {t.id: t for t in card.tasks}
    for task_id in [*remove, *(edit or {}), *(priority or {})]:
        if task_id not in by_id:
            raise ValueError(f"no task with id {task_id!r}")

    for task_id, text in (edit or {}).items():
        t = by_id[task_id]
        text = text.strip()
        if not text:
            raise ValueError(f"task {task_id!r}: the new text is empty (remove the task instead)")
        if text != t.task:
            t.task, t.origin, t.skills = text, "company", []

    for task_id, p in (priority or {}).items():
        by_id[task_id].priority = p

    removed = set(remove)
    card.tasks = [t for t in card.tasks if t.id not in removed]

    for item in add:
        text, p = (item, "must_have") if isinstance(item, str) else item
        if not text.strip():
            raise ValueError("a new task can't be empty")
        card.tasks.append(CardTask(id=_new_id(card), task=text.strip(), priority=p, origin="company"))

    if not card.tasks:
        raise ValueError("the task card needs at least one task")
    return TaskCard.model_validate(card.model_dump())


def to_job_spec(card):
    """TaskCard -> employer.JobSpec, so employer-side code (map_spec, make_job_profile) takes it as is.
    Each task's source is "bizdev:<root cause>", which map_spec copies into every skill's `sources`."""
    rc = root_cause(card.root_cause)
    return JobSpec(
        title=rc["name"],
        summary=f"{rc['current']} Goal: {rc['target']}",
        tasks=[Task(task=t.task, priority=t.priority, source=f"bizdev:{card.root_cause}", skills=t.skills)
               for t in card.tasks],
        flags=[],
    )
