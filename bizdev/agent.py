"""BizDevAgent: one stateless method per step. Each takes and returns pydantic models (models.py).

    agent = BizDevAgent()
    profile   = agent.profile(business_id="1234560-4")      # or sample="consulting", or sector="retail"
    diagnosis = agent.diagnose(profile)                     # -> diagnosis.current_question
    diagnosis = agent.answer(diagnosis, "A")                # or "neither"; then describe() / choose()
    shift, ideas = agent.ideas(diagnosis)
    card      = agent.task_card(diagnosis)
    card      = agent.edit(card, remove=["key_person_dependency.3"], add=["Train the team in the new playbook"])
    needs     = agent.skills(profile, diagnosis, card)      # -> SkillRequirements (the output)
    needs.save("needs.json")
"""

from . import diagnosis as diag
from . import ideas as ideas_mod
from . import taskcard
from .models import CardTask, Company, Need, OutputTask, RequiredSkill, SkillRequirements
from .skills import LiveMapper, map_tasks, merge
from .sources import (PLAYBOOK_ESCO_PATH, load_playbook_esco, load_sample, manual_profile,
                      profile_from_registry, root_cause)


class BizDevAgent:
    def __init__(self, mapper=None, live=True):
        """mapper: an existing SkillMapper to reuse (the API passes its own). live=False never maps
        live, so company tasks always come out "unmapped"."""
        self.live = LiveMapper(mapper) if live else None

    # ---------- Warnings the caller should show early ----------

    def warnings(self):
        """Things that make the output incomplete, known before the company starts."""
        out = []
        if load_playbook_esco() is None:
            out.append(f"{PLAYBOOK_ESCO_PATH.name} not found: run `python -m bizdev.prepare` once. "
                       "Until then playbook tasks are mapped live, or marked unmapped.")
        reason = self.live_reason()
        if reason:
            out.append(f"Live skill mapping is off ({reason}). Tasks you add or rewrite will be saved as "
                       "unmapped, without ESCO skills.")
        return out

    def live_reason(self):
        if self.live is None:
            return "turned off"
        return self.live.reason

    # ---------- Step 1 ----------

    def profile(self, business_id=None, sample=None, sector=None, name=None):
        """Exactly one source: sample key, sector (manual), or business_id (PRH lookup).
        business_id + sector: use the sector as given (no lookup). Raises LookupError if PRH fails."""
        if sample is not None:
            return load_sample(sample)
        if sector is not None:
            return manual_profile(sector, name=name, business_id=business_id)
        if business_id is not None:
            return profile_from_registry(business_id)
        raise ValueError("give a business_id, a sample or a sector")

    # ---------- Step 2 ----------

    def diagnose(self, profile):
        return diag.start(profile.sector_family)

    def answer(self, diagnosis, choice):
        return diag.answer(diagnosis, choice)

    def describe(self, diagnosis, text):
        return diag.from_text(diagnosis, text)

    def choose(self, diagnosis, root_cause_id):
        return diag.choose(diagnosis, root_cause_id)

    # ---------- Steps 3-4 ----------

    @staticmethod
    def _root_cause(diagnosis):
        if not diagnosis.root_cause:
            raise ValueError("the diagnosis is not finished (no root cause yet)")
        return diagnosis.root_cause

    def ideas(self, diagnosis):
        rc = self._root_cause(diagnosis)
        return ideas_mod.capability_shift(rc), ideas_mod.ideas(rc)

    def task_card(self, diagnosis):
        return taskcard.propose(self._root_cause(diagnosis))

    def edit(self, card, remove=(), edit=None, add=(), priority=None):
        return taskcard.apply_edits(card, remove=remove, edit=edit, add=add, priority=priority)

    # ---------- Step 5 ----------

    def map_tasks(self, card):
        """Per-task skills. Separate from build_output so a UI can change priorities and re-merge
        without mapping again."""
        return map_tasks(card, load_playbook_esco(), self.live)

    def build_output(self, profile, diagnosis, card, per_task):
        rc_id = self._root_cause(diagnosis)
        if card.root_cause != rc_id:
            raise ValueError("the task card belongs to a different root cause than the diagnosis")
        rc = root_cause(rc_id)
        # Company tasks get the phrases found for them, so job_spec is complete for employer-side code.
        card = card.model_copy(update={"tasks": [
            CardTask(**{**t.model_dump(), "skills": per_task[t.id]["phrases"]}) for t in card.tasks]})
        return SkillRequirements(
            company=Company(business_id=profile.business_id, name=profile.name, sector_family=profile.sector_family),
            need=Need(root_cause=rc_id, name=rc["name"], current=rc["current"], target=rc["target"]),
            ideas=ideas_mod.ideas(rc_id),
            tasks=[OutputTask(id=t.id, task=t.task, priority=t.priority, origin=t.origin,
                              status=per_task[t.id]["status"], skill_phrases=per_task[t.id]["phrases"])
                   for t in card.tasks],
            skills=[RequiredSkill.model_validate(s) for s in merge(card, per_task)],
            job_spec=taskcard.to_job_spec(card),
        )

    def skills(self, profile, diagnosis, card):
        return self.build_output(profile, diagnosis, card, self.map_tasks(card))
