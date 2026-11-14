"""Step 3: root cause -> capability shift (current -> target) and improvement ideas."""

from .models import CapabilityShift, Idea
from .sources import root_cause


def capability_shift(rc_id):
    rc = root_cause(rc_id)
    return CapabilityShift(root_cause=rc_id, name=rc["name"], current=rc["current"],
                           target=rc["target"], benefit=rc.get("benefit"))


def ideas(rc_id):
    return [Idea.model_validate(i) for i in root_cause(rc_id)["ideas"]]
