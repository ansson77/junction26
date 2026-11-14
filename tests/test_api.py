"""API tests with a stub mapper: no Gemini calls, a temporary database and question cache.
Needs the embedding index (esco/skills.npy) for search, map_spec and matching."""

import pytest

from build_index import VECTORS_PATH

if not VECTORS_PATH.exists():
    pytest.skip("embedding index not built (run build_index.py)", allow_module_level=True)

from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

import applicant
from api import create_app
from employer import Clarification, JobSpec
from search import SkillIndex

JOB_TEXT = "We need someone to fix bugs in our JavaScript web shop and talk to customers."
SPEC = {
    "title": "Web developer",
    "summary": "Fixes bugs in the web shop and gathers requirements from customers.",
    "tasks": [
        {"task": "Fix bugs reported by customers in the web shop", "priority": "must_have",
         "source": "fix bugs in our JavaScript web shop", "skills": ["debug software", "JavaScript"]},
        {"task": "Talk to customers about what they need", "priority": "learnable",
         "source": "talk to customers", "skills": ["interact with users to gather requirements"]},
    ],
    "flags": [],
}


class StubMapper:
    """Stands in for map_skills.SkillMapper: real index, canned Gemini answers."""

    def __init__(self, index):
        self.index = index
        self.fail = False

    def generate(self, system, user, schema):
        if schema is Clarification:
            return Clarification(understood_so_far="A web developer.", is_clear_enough=False, questions=[
                {"question": "Which framework?", "why": "Not stated.", "example_answers": ["React", "Vue"]}])
        if schema is JobSpec:
            return JobSpec.model_validate(SPEC)
        # applicant._Questions: one question per numbered line
        n = len(user.splitlines())
        return schema.model_validate({"questions": [{"index": i, "question": f"Q{i}?"} for i in range(n)]})

    def map_text(self, text, role="applicant"):
        if self.fail:
            raise genai_errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        top = self.index.search("debug software", k=1)[0]
        return [{**{k: top[k] for k in ("uri", "label", "skillType", "reuseLevel")},
                 "confidence": "high", "probability": 0.9, "statements": ["debug software"],
                 "evidence": [text[:40]]}]

    def retrieve(self, statements, k=3):
        return self.index.search_many([s.esco_phrase for s in statements], k=k)

    def select_skills(self, statements, candidates, mode="evidence"):
        return [(i, {**c[0], "probability": 0.9}, "high") for i, c in enumerate(candidates) if c]


@pytest.fixture(scope="module")
def index():
    return SkillIndex()


@pytest.fixture
def stub(index):
    return StubMapper(index)


@pytest.fixture
def client(stub, tmp_path, monkeypatch):
    monkeypatch.setattr(applicant, "QUESTION_CACHE", tmp_path / "questions.json")
    app = create_app(mapper=stub, db_path=tmp_path / "test.db", frontend_dir=tmp_path / "no-frontend")
    with TestClient(app) as c:
        yield c


def uri_of(index, label):
    return next(s["uri"] for s in index.skills if s["label"] == label)


def make_job(client):
    skills = client.post("/api/employer/skills", json={"spec": SPEC}).json()
    allocation = {s["uri"]: 0 for s in skills}
    allocation[skills[0]["uri"]] = 10
    r = client.post("/api/employer/profile", json={"spec": SPEC, "skills": skills, "allocation": allocation})
    assert r.status_code == 200, r.text
    return r.json()


def make_applicant(client, index, labels_points, languages=None):
    skills = [{"uri": uri_of(index, l), "label": l, "skillType": "skill/competence", "origin": "added"}
              for l in labels_points]
    allocation = {s["uri"]: p for s, p in zip(skills, labels_points.values())}
    r = client.post("/api/applicant/profile", json={
        "skills": skills, "allocation": allocation,
        "questions": {s["uri"]: "Describe one time." for s in skills},
        "answers": {s["uri"]: "I did it once." for s in skills},
        "languages": languages or [],
    })
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Employer ----------

def test_employer_flow(client):
    c = client.post("/api/employer/clarify", json={"text": JOB_TEXT}).json()
    assert c["questions"][0]["question"] == "Which framework?"

    spec = client.post("/api/employer/spec", json={
        "text": JOB_TEXT, "qa": [{"question": "Which framework?", "answer": "React"}]}).json()
    assert spec["title"] == "Web developer"

    skills = client.post("/api/employer/skills", json={"spec": spec}).json()
    assert skills and skills[0]["priority"] == "must_have"
    assert all(s["tasks"] for s in skills)

    saved = make_job(client)
    assert client.get(f"/api/jobs/{saved['id']}").json()["title"] == "Web developer"
    assert [j["id"] for j in client.get("/api/jobs").json()] == [saved["id"]]


def test_employer_point_rules_are_422(client):
    skills = client.post("/api/employer/skills", json={"spec": SPEC}).json()
    r = client.post("/api/employer/profile", json={
        "spec": SPEC, "skills": skills, "allocation": {skills[0]["uri"]: 9}})
    assert r.status_code == 422
    assert "spend exactly 10 points" in r.json()["detail"]


def test_empty_text_is_422(client):
    assert client.post("/api/employer/clarify", json={"text": ""}).status_code == 422


# ---------- Applicant ----------

def test_applicant_flow(client, index):
    s = client.post("/api/applicant/suggest", json={"text": "I fixed bugs in our shop's website."}).json()
    assert s[0]["confidence"] == "high"

    hits = client.get("/api/applicant/search", params={"q": "bookkeeping", "k": 3}).json()
    assert len(hits) == 3 and {"uri", "label", "description", "score"} <= hits[0].keys()

    # Questions only for the 2 skills with the most points.
    uris = [s[0]["uri"], hits[0]["uri"], hits[1]["uri"]]
    q = client.post("/api/applicant/questions",
                    json={"allocation": {uris[0]: 2, uris[1]: 5, uris[2]: 3}}).json()
    assert set(q) == {uris[1], uris[2]}

    saved = make_applicant(client, index, {"debug software": 6, "JavaScript": 4})
    profile = client.get(f"/api/applicants/{saved['id']}").json()
    assert {x["validation_answer"] for x in profile["skills"]} == {"I did it once."}


def test_applicant_languages(client, index):
    saved = make_applicant(client, index, {"debug software": 6, "JavaScript": 4},
                           languages=[" Finnish ", "English", "english", "Tigrinya"])
    assert saved["profile"]["languages"] == ["Finnish", "English", "Tigrinya"]
    assert client.get(f"/api/applicants/{saved['id']}").json()["languages"] == ["Finnish", "English", "Tigrinya"]
    row = next(a for a in client.get("/api/applicants").json() if a["id"] == saved["id"])
    assert row["languages"] == ["Finnish", "English", "Tigrinya"]
    # Languages are outside the point budget: none is fine too.
    plain = make_applicant(client, index, {"debug software": 10})
    assert plain["profile"]["languages"] == []


def test_only_top_skills_keep_answers(client, index):
    saved = make_applicant(client, index, {"debug software": 2, "JavaScript": 5, "accounting": 3})
    answered = {x["label"]: x["validation_answer"] for x in saved["profile"]["skills"]}
    assert answered == {"JavaScript": "I did it once.", "accounting": "I did it once.", "debug software": ""}


def test_applicant_max_skills_is_422(client, index):
    labels = ["debug software", "JavaScript", "accounting", "Finnish", "train employees", "troubleshoot"]
    skills = [{"uri": uri_of(index, l), "label": l, "skillType": "skill/competence", "origin": "added"}
              for l in labels]
    allocation = {s["uri"]: p for s, p in zip(skills, [5, 1, 1, 1, 1, 1])}
    r = client.post("/api/applicant/profile", json={"skills": skills, "allocation": allocation})
    assert r.status_code == 422
    assert "at most 5 skills" in r.json()["detail"]


def test_unknown_uri_is_422(client):
    r = client.post("/api/applicant/questions", json={"allocation": {"http://example.com/nope": 10}})
    assert r.status_code == 422


def test_gemini_failure_is_502(client, stub):
    stub.fail = True
    r = client.post("/api/applicant/suggest", json={"text": "anything"})
    assert r.status_code == 502


# ---------- Stored profiles and matching ----------

def test_matching_and_delete(client, index):
    job = make_job(client)
    good = make_applicant(client, index, {job["profile"]["skills"][0]["label"]: 10})
    bad = make_applicant(client, index, {"accounting": 10})

    matches = client.get(f"/api/jobs/{job['id']}/matches").json()
    assert [m["applicant_id"] for m in matches] == [good["id"], bad["id"]]
    assert matches[0]["score"] == 1.0 and matches[0]["links"]

    assert client.get(f"/api/applicants/{good['id']}/matches").json()[0]["job_id"] == job["id"]

    assert client.delete(f"/api/applicants/{bad['id']}").status_code == 204
    assert client.get(f"/api/applicants/{bad['id']}").status_code == 404
    assert client.get("/api/jobs/does-not-exist/matches").status_code == 404


def test_networking_invites(client, index):
    job = make_job(client)
    a = make_applicant(client, index, {job["profile"]["skills"][0]["label"]: 10})
    b = make_applicant(client, index, {"accounting": 10})
    url = f"/api/jobs/{job['id']}/invites"

    assert client.get(url).json() == []
    assert client.put(f"{url}/{a['id']}").status_code == 204
    assert client.put(f"{url}/{a['id']}").status_code == 204          # idempotent
    assert client.put(f"{url}/{b['id']}").status_code == 204
    assert client.get(url).json() == [a["id"], b["id"]]

    assert client.delete(f"{url}/{a['id']}").status_code == 204
    assert client.delete(f"{url}/{a['id']}").status_code == 204       # idempotent
    assert client.get(url).json() == [b["id"]]

    # Deleting the applicant removes their invite.
    assert client.delete(f"/api/applicants/{b['id']}").status_code == 204
    assert client.get(url).json() == []

    assert client.put(f"{url}/does-not-exist").status_code == 404
    assert client.get("/api/jobs/does-not-exist/invites").status_code == 404


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"
