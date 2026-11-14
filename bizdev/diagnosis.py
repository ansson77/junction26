"""Step 2: A/B diagnosis -> root cause. Deterministic, no AI.

One question tree for every sector (playbook.json "questions"): each option either leads to the next
question ("next") or locks a root cause ("root_cause").

  start(sector)            the first question
  answer(d, "A"/"B")       follows the option: next question, or root cause
  answer(d, "neither")     at any step: the company describes the problem in one sentence (needs_text)
  from_text(d, text)       keyword match against every root cause; if no single best match, offers
                           the list of root causes to pick from (needs_choice)
  choose(d, root_cause)    the company picks from that list
"""

import re

from .models import Answer, Diagnosis, Hypothesis, RootCauseChoice
from .sources import load_playbook, root_cause


def question(q_id):
    items = load_playbook()["questions"]["items"]
    return Hypothesis.model_validate({"id": q_id, **items[q_id]})


def start(sector):
    return Diagnosis(sector_family=sector, current_question=question(load_playbook()["questions"]["start"]))


def all_choices(order=None):
    causes = load_playbook()["root_causes"]
    ids = order or list(causes)
    return [RootCauseChoice(id=i, name=causes[i]["name"], current=causes[i]["current"]) for i in ids]


def answer(d, choice):
    """choice: "A", "B" or "neither" (case-insensitive)."""
    if d.current_question is None:
        raise ValueError("there is no open A/B question")
    choice = {"a": "A", "b": "B", "neither": "neither", "n": "neither"}.get(str(choice).strip().lower())
    if choice is None:
        raise ValueError('answer must be "A", "B" or "neither"')
    d = d.model_copy(deep=True)
    q = d.current_question
    d.answers.append(Answer(question_id=q.id, answer=choice))
    d.current_question = None
    if choice == "neither":
        d.needs_text = True
        return d
    option = q.a if choice == "A" else q.b
    if option.next:
        d.current_question = question(option.next)
    else:
        d.root_cause = option.root_cause
    return d


def keyword_scores(text):
    """{root_cause: number of its keywords found in the text}, only those > 0."""
    words = text.lower()
    scores = {}
    for rc_id, rc in load_playbook()["root_causes"].items():
        n = sum(1 for kw in rc["keywords"] if re.search(rf"\b{re.escape(kw.lower())}", words))
        if n:
            scores[rc_id] = n
    return scores


def from_text(d, text):
    """The company describes what holds it back. A single best keyword match locks the root cause;
    otherwise the company picks from all root causes, best matches first."""
    if not text or not text.strip():
        raise ValueError("describe the problem in a sentence")
    d = d.model_copy(deep=True)
    d.text = text.strip()
    d.current_question = None
    d.needs_text = False
    scores = keyword_scores(text)
    ranked = sorted(scores, key=lambda rc: -scores[rc])
    if len(ranked) == 1 or (len(ranked) > 1 and scores[ranked[0]] > scores[ranked[1]]):
        d.root_cause = ranked[0]
        return d
    rest = [rc for rc in load_playbook()["root_causes"] if rc not in ranked]
    d.needs_choice = True
    d.choices = all_choices(ranked + rest)
    return d


def choose(d, rc_id):
    root_cause(rc_id)  # raises ValueError if unknown
    d = d.model_copy(deep=True)
    d.root_cause = rc_id
    d.current_question = None
    d.needs_text = False
    d.needs_choice = False
    return d
