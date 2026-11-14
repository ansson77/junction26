"""bizdev tests. Offline: no Gemini, no index (a fake mapper stands in for live mapping).
The API test at the end needs the embedding index, like tests/test_api.py."""

import json

import pytest

from bizdev import BizDevAgent, SkillRequirements
from bizdev import sources
from bizdev.skills import LiveMapper, map_tasks, merge
from bizdev.taskcard import propose

STORED = {"phrases": {
    "analyse business processes": [
        {"uri": "esco:analyse", "label": "analyse business processes", "skillType": "skill/competence",
         "reuseLevel": "cross-sector", "confidence": "high", "probability": 0.9}],
    "identify process improvements": [
        {"uri": "esco:improve", "label": "identify process improvements", "skillType": "skill/competence",
         "reuseLevel": "cross-sector", "confidence": "medium", "probability": 0.6}],
    "train employees": [
        {"uri": "esco:train", "label": "train employees", "skillType": "skill/competence",
         "reuseLevel": "transversal", "confidence": "high", "probability": 0.95}],
}}


class FakeMapper:
    """Just enough of SkillMapper for extract_statements + EmployerFlow.map_spec."""

    def __init__(self):
        self.extracted = []

    def extract_statements(self, text, role="applicant"):
        from map_skills import Statement
        self.extracted.append((text, role))
        return [Statement(esco_phrase="train employees", evidence=text)]

    def retrieve(self, statements, k=15):
        return [[{"uri": f"esco:{s.esco_phrase.split()[0]}", "label": s.esco_phrase,
                  "skillType": "skill/competence", "reuseLevel": "cross-sector"}] for s in statements]

    def select_skills(self, statements, candidates, mode="evidence"):
        return [(i, {**c[0], "probability": 0.85}, "high") for i, c in enumerate(candidates)]


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(sources, "load_playbook_esco", lambda: STORED)
    monkeypatch.setattr("bizdev.agent.load_playbook_esco", lambda: STORED)
    return BizDevAgent(live=False)


# ---------- Step 1 ----------

@pytest.mark.parametrize("raw", ["1234560-4", "12345604", " 1234560 - 4 "])
def test_business_id_normalized(raw):
    assert sources.normalize_business_id(raw) == "1234560-4"


@pytest.mark.parametrize("raw", ["1234560-5", "abc", "", "123"])
def test_business_id_rejected(raw):
    with pytest.raises(ValueError):
        sources.normalize_business_id(raw)


def test_sample_ids_are_valid():
    for s in sources.sample_companies():
        assert sources.normalize_business_id(s["business_id"]) == s["business_id"]
        assert sources.sector_family(s["tol_code"]) == s["sector_family"]


def test_sector_family():
    assert sources.sector_family("62010") == "software"
    assert sources.sector_family("70220") == "professional_services"
    assert sources.sector_family("25110") == "manufacturing"
    assert sources.sector_family("01110") == "general"
    assert sources.sector_family(None) == "general"


def test_registry_failure_is_lookup_error(monkeypatch):
    monkeypatch.setattr(sources, "fetch_prh", lambda bid: None)
    with pytest.raises(LookupError):
        BizDevAgent(live=False).profile(business_id="1234560-4")


# ---------- Playbook integrity ----------

def test_playbook_references():
    pb = sources.load_playbook()
    task_ids = [t["id"] for rc in pb["root_causes"].values() for t in rc["tasks"]]
    assert len(task_ids) == len(set(task_ids))
    items = pb["questions"]["items"]
    assert pb["questions"]["start"] in items
    for q in items.values():
        for opt in (q["a"], q["b"]):
            assert (opt.get("next") in items) != (opt.get("root_cause") in pb["root_causes"])


# ---------- Step 2 ----------

@pytest.mark.parametrize("answers,expected", [
    ("AA", "key_person_dependency"), ("AB", "manual_work"),
    ("BA", "unclear_offering"), ("BB", "no_sales_process"),
])
def test_question_tree(offline, answers, expected):
    d = offline.diagnose(offline.profile(sample="consulting"))
    assert d.current_question.id == "capacity_or_demand"
    d = offline.answer(d, answers[0])
    assert d.current_question.id == ("capacity" if answers[0] == "A" else "demand")
    d = offline.answer(d, answers[1])
    assert d.done and d.root_cause == expected


def test_same_tree_for_every_sector(offline):
    d = offline.diagnose(offline.profile(sector="retail"))
    assert d.current_question.id == "capacity_or_demand"


@pytest.mark.parametrize("answers", [["neither"], ["A", "neither"], ["B", "neither"]])
def test_neither_then_text_keyword_match(offline, answers):
    d = offline.diagnose(offline.profile(sample="consulting"))
    for a in answers:
        d = offline.answer(d, a)
    assert d.needs_text and d.current_question is None
    d = offline.describe(d, "We only get new customers through referrals and contacts")
    assert d.root_cause == "no_sales_process"


def test_customers_is_not_custom_work():
    from bizdev.diagnosis import keyword_scores
    assert list(keyword_scores("we can't find new customers")) == ["no_sales_process"]


def test_unclear_text_offers_choice(offline):
    d = offline.answer(offline.diagnose(offline.profile(sector="retail")), "neither")
    d = offline.describe(d, "Everything is fine, honestly")
    assert d.needs_choice and not d.done
    assert [c.id for c in d.choices] == list(sources.load_playbook()["root_causes"])
    d = offline.choose(d, "manual_work")
    assert d.root_cause == "manual_work"
    with pytest.raises(ValueError):
        offline.choose(d, "nope")


def test_bad_answer(offline):
    d = offline.diagnose(offline.profile(sample="consulting"))
    with pytest.raises(ValueError):
        offline.answer(d, "maybe")


# ---------- Step 4 ----------

def test_edits_exact_match_rule(offline):
    card = propose("key_person_dependency")
    same = offline.edit(card, edit={"key_person_dependency.1": card.tasks[0].task})
    assert same.tasks[0].origin == "playbook" and same.tasks[0].skills
    changed = offline.edit(card, edit={"key_person_dependency.1": card.tasks[0].task + "s"})
    assert changed.tasks[0].origin == "company" and changed.tasks[0].skills == []


def test_edits_remove_add_priority(offline):
    card = offline.edit(propose("key_person_dependency"), remove=["key_person_dependency.2"],
                        add=["Train the team"], priority={"key_person_dependency.1": "learnable"})
    assert [t.id for t in card.tasks] == ["key_person_dependency.1", "key_person_dependency.3", "company.1"]
    assert card.tasks[0].priority == "learnable"
    with pytest.raises(ValueError):
        offline.edit(card, remove=["nope"])
    with pytest.raises(ValueError):
        offline.edit(card, remove=[t.id for t in card.tasks])


# ---------- Step 5 ----------

def test_offline_output(offline, tmp_path):
    profile = offline.profile(sample="consulting")
    d = offline.answer(offline.answer(offline.diagnose(profile), "A"), "A")
    card = offline.edit(offline.task_card(d), remove=["key_person_dependency.2"], add=["Write the new playbook"])
    needs = offline.skills(profile, d, card)

    status = {t.id: t.status for t in needs.tasks}
    assert status["key_person_dependency.1"] == "mapped"
    assert status["key_person_dependency.3"] == "unmapped"   # "delegate activities" isn't in STORED
    assert status["company.1"] == "unmapped"
    assert {s.uri for s in needs.skills} == {"esco:analyse", "esco:train"}
    assert all(s.sources == ["bizdev:key_person_dependency"] for s in needs.skills)
    assert needs.skills[0].priority == "must_have"

    path = tmp_path / "needs.json"
    needs.save(path)
    data = json.loads(path.read_text())
    assert data["schema"] == "bizdev.skill_requirements/v1"
    assert data["job_spec"]["tasks"][0]["source"] == "bizdev:key_person_dependency"
    assert SkillRequirements.model_validate(data).need.root_cause == "key_person_dependency"


def test_merge_takes_strongest_priority():
    card = propose("key_person_dependency")
    card.tasks[0].priority = "nice_to_have"
    train = STORED["phrases"]["train employees"][0]
    per_task = {
        "key_person_dependency.1": {"skills": [train]},
        "key_person_dependency.2": {"skills": []},
        "key_person_dependency.3": {"skills": [{**train, "confidence": "medium", "probability": 0.99}]},
    }
    [skill] = merge(card, per_task)
    assert skill["priority"] == "learnable"
    assert skill["confidence"] == "high" and skill["probability"] == 0.99
    assert len(skill["tasks"]) == 2


def test_live_mapping_company_and_missing_phrases():
    fake = FakeMapper()
    card = BizDevAgent(live=False).edit(propose("key_person_dependency"), add=["Run playbook workshops"])
    per_task = map_tasks(card, STORED, LiveMapper(fake))

    assert fake.extracted == [("Run playbook workshops", "employer")]
    assert per_task["company.1"]["phrases"] == ["train employees"]
    assert "esco:train" in {s["uri"] for s in per_task["company.1"]["skills"]}
    # Phrases missing from the stored file were mapped live, so nothing stays unmapped.
    assert all(r["status"] == "mapped" for r in per_task.values())
    assert "esco:document" in {s["uri"] for s in per_task["key_person_dependency.2"]["skills"]}
    assert "esco:delegate" in {s["uri"] for s in per_task["key_person_dependency.3"]["skills"]}


def test_live_reason_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    live = LiveMapper()
    assert not live.available and "GEMINI_API_KEY" in live.reason
    assert any("GEMINI_API_KEY" in w for w in BizDevAgent().warnings())


# ---------- HTTP ----------

def test_api_flow(monkeypatch, tmp_path):
    from build_index import VECTORS_PATH
    if not VECTORS_PATH.exists():
        pytest.skip("embedding index not built (run build_index.py)")
    from fastapi.testclient import TestClient

    from api import create_app
    from search import SkillIndex

    fake = FakeMapper()
    fake.index = SkillIndex()
    monkeypatch.setattr("bizdev.agent.load_playbook_esco", lambda: STORED)
    app = create_app(mapper=fake, db_path=tmp_path / "t.db", frontend_dir=tmp_path / "none")
    with TestClient(app) as c:
        assert c.get("/api/bizdev/options").json()["warnings"] == []
        profile = c.post("/api/bizdev/profile", json={"sample": "consulting"}).json()
        d = c.post("/api/bizdev/diagnose", json={"profile": profile}).json()
        d = c.post("/api/bizdev/answer", json={"diagnosis": d, "answer": "A"}).json()
        d = c.post("/api/bizdev/answer", json={"diagnosis": d, "answer": "A"}).json()
        assert d["root_cause"] == "key_person_dependency"
        assert len(c.post("/api/bizdev/ideas", json={"diagnosis": d}).json()["ideas"]) == 3
        card = c.post("/api/bizdev/taskcard", json={"diagnosis": d}).json()
        card = c.post("/api/bizdev/taskcard/edit", json={"card": card, "add": ["Run workshops"]}).json()
        out = c.post("/api/bizdev/skills", json={"profile": profile, "diagnosis": d, "card": card})
        assert out.status_code == 200, out.text
        assert out.json()["schema"] == "bizdev.skill_requirements/v1"
        assert c.post("/api/bizdev/answer", json={"diagnosis": d, "answer": "A"}).status_code == 422
        assert c.post("/api/bizdev/profile", json={"business_id": "1234560-5"}).status_code == 422
