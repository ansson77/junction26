"""Matching behaviour on synthetic profiles built from real ESCO skills.
Needs the embedding index (esco/skills.npy); no Gemini, no database."""

import pytest

from build_index import VECTORS_PATH

if not VECTORS_PATH.exists():
    pytest.skip("embedding index not built (run build_index.py)", allow_module_level=True)

from matching import DEMO_APPLICANTS, DEMO_JOB, SkillSimilarity, match


@pytest.fixture(scope="module")
def sim():
    return SkillSimilarity()


@pytest.fixture(scope="module")
def uris(sim):
    by_label = {v: k for k, v in sim.label.items()}
    return lambda d: {by_label[label]: p for label, p in d.items()}


# ---------- Skill similarity calibration ----------

SAME = [
    ("handle complaints", "handle customer complaints"),
    ("train employees", "coach employees"),
    ("JavaScript", "JavaScript Framework"),
    ("debug software", "troubleshoot"),
    ("troubleshoot", "solve technical problems"),
    ("accounting", "maintain financial records"),
    ("Finnish", "interact verbally in Finnish"),
]
UNRELATED = [
    ("debug software", "accounting"),
    ("JavaScript", "Finnish"),
    ("train employees", "JavaScript"),
    ("handle customer complaints", "debug software"),
    ("lay pipe installation", "web programming"),
    ("troubleshoot", "supervise sales activities"),   # weak (0.14) -> below SIM_MIN
    ("communicate with customers", "supervise sales activities"),
]


@pytest.mark.parametrize("a,b", SAME)
def test_similar_skills_get_partial_credit(sim, uris, a, b):
    (ua,), (ub,) = uris({a: 1}), uris({b: 1})
    assert sim.matrix([ua], [ub])[0, 0] > 0


@pytest.mark.parametrize("a,b", UNRELATED)
def test_unrelated_skills_get_none(sim, uris, a, b):
    (ua,), (ub,) = uris({a: 1}), uris({b: 1})
    assert sim.matrix([ua], [ub])[0, 0] == 0


def test_identical_and_unknown_uris(sim):
    u = next(iter(sim.row))
    assert sim.matrix([u, "x:unknown"], [u, "x:unknown"]).tolist() == [[1, 0], [0, 1]]


# ---------- Match scores ----------

def run(sim, uris, applicant, job=DEMO_JOB, must=()):
    """Match by skill labels. `must`: labels of the job's must-have skills."""
    return match(uris(job), uris(applicant), sim, must_haves=list(uris({m: 1 for m in must})))


def test_identical_profile_is_perfect(sim, uris):
    r = run(sim, uris, DEMO_JOB)
    assert r.score == pytest.approx(1) and r.coverage == pytest.approx(1)


def test_unrelated_profile_is_zero(sim, uris):
    r = run(sim, uris, DEMO_APPLICANTS["unrelated"])
    assert r.score == 0 and r.coverage == 0
    assert all(link.applicant_skill is None for link in r.links)


def test_ranking_order(sim, uris):
    scores = {name: run(sim, uris, app).score for name, app in DEMO_APPLICANTS.items()}
    assert (scores["same skills, same priorities"]
            > scores["same skills, other priorities"]
            > scores["near-synonyms"]
            > scores["partial + extra"]
            > scores["unrelated"])


def test_near_synonyms_are_not_zero(sim, uris):
    """The reason for soft cosine: plain cosine would give 0 here."""
    r = run(sim, uris, DEMO_APPLICANTS["near-synonyms"])
    assert 0.2 < r.score < 1 and 0 < r.coverage < 1


def test_priorities_change_score_but_not_coverage(sim, uris):
    r = run(sim, uris, DEMO_APPLICANTS["same skills, other priorities"])
    assert r.coverage == pytest.approx(1)
    assert r.score < 0.9


def test_extra_skills_lower_score_but_not_coverage(sim, uris):
    focused = run(sim, uris, {"JavaScript": 10})
    spread = run(sim, uris, {"JavaScript": 4, "Finnish": 3, "accounting": 3})
    assert focused.coverage == pytest.approx(spread.coverage)
    assert focused.score > spread.score


def test_score_is_symmetric(sim, uris):
    a, b = DEMO_JOB, DEMO_APPLICANTS["near-synonyms"]
    assert match(uris(a), uris(b), sim).score == pytest.approx(match(uris(b), uris(a), sim).score)


def test_links_explain_every_job_skill(sim, uris):
    r = run(sim, uris, DEMO_APPLICANTS["near-synonyms"])
    assert [link.job_points for link in r.links] == sorted(DEMO_JOB.values(), reverse=True)
    js = next(link for link in r.links if link.job_skill == "JavaScript")
    assert js.applicant_skill == "JavaScript Framework" and 0 < js.similarity < 1


def test_missing_must_haves(sim, uris):
    r = run(sim, uris, DEMO_APPLICANTS["partial + extra"], must=["debug software", "JavaScript"])
    assert r.missing_must_haves == ["debug software"]
