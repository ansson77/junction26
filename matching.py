"""Match jobs and applicants on their 10-point skill allocations.

Both sides spend exactly 10 points, so each profile is a priority distribution over ESCO skills.

score    = soft cosine between the two distributions: do they care about the same things,
           in the same proportions? Different but similar skills count partly
           (e.g. 'troubleshoot' ~ 'debug software').
           score = e.S.a / sqrt(e.S.e * a.S.a)
coverage = how much of the EMPLOYER's 10 points the applicant covers:
           sum_i e_i * max_j S[i, j] / 10. Used to explain the score.

S (skill similarity) comes only from the precomputed ESCO skill embeddings (esco/skills.npy):
it is data about skills, never about people. No LLM is involved. The whole match is a fixed,
deterministic formula that can be inspected and explained skill by skill.

Usage:
    .venv/bin/python matching.py job <job_id>            # applicants for a job, best first
    .venv/bin/python matching.py applicant <applicant_id> # jobs for an applicant, best first
    .venv/bin/python matching.py demo                     # synthetic examples, no database needed
"""

import argparse
import math

import numpy as np
from pydantic import BaseModel

from points import POINT_BUDGET

# Calibration of raw embedding similarity (multilingual-e5-small over ESCO label + alt labels +
# description). Measured on hand-picked pairs: same/near-synonym skills 0.85-0.95, unrelated
# skills 0.79-0.83, random pairs median 0.80 and 99th percentile 0.86.
# Below SIM_FLOOR -> 0 (unrelated), at or above SIM_FULL -> 1 (same skill), linear in between.
SIM_FLOOR = 0.84
SIM_FULL = 0.94
# Calibrated similarities below this are noise (e.g. 'troubleshoot' ~ 'supervise sales activities'
# at 0.14) and count as not covered.
SIM_MIN = 0.15


class SkillSimilarity:
    """Calibrated similarity between ESCO skills, from the embedding index."""

    def __init__(self, index=None):
        if index is None:
            from search import SkillIndex
            index = SkillIndex()
        self.vectors = index.vectors
        self.row = {s["uri"]: i for i, s in enumerate(index.skills)}
        self.label = {s["uri"]: s["label"] for s in index.skills}

    def matrix(self, uris_a, uris_b):
        """[len(uris_a), len(uris_b)] similarities in 0..1. Identical URIs are always 1.
        Skills missing from the index only match themselves."""
        S = np.zeros((len(uris_a), len(uris_b)))
        ia = [self.row.get(u) for u in uris_a]
        ib = [self.row.get(u) for u in uris_b]
        known_a = [k for k, r in enumerate(ia) if r is not None]
        known_b = [k for k, r in enumerate(ib) if r is not None]
        if known_a and known_b:
            raw = self.vectors[[ia[k] for k in known_a]] @ self.vectors[[ib[k] for k in known_b]].T
            calibrated = np.clip((raw - SIM_FLOOR) / (SIM_FULL - SIM_FLOOR), 0, 1)
            calibrated[calibrated < SIM_MIN] = 0
            S[np.ix_(known_a, known_b)] = calibrated
        for i, u in enumerate(uris_a):
            for j, v in enumerate(uris_b):
                if u == v:
                    S[i, j] = 1.0
        return S


# ---------- Result models (also the API response schema) ----------

class SkillLink(BaseModel):
    """One employer skill and the applicant skill that covers it best."""
    job_skill_uri: str
    job_skill: str
    job_points: int
    applicant_skill_uri: str | None
    applicant_skill: str | None
    applicant_points: int
    similarity: float  # 1.0 = same ESCO skill, 0 = not covered


class MatchResult(BaseModel):
    score: float      # soft cosine, 0..1
    coverage: float   # share of the employer's points covered, 0..1
    links: list[SkillLink]          # one per employer skill, most important first
    missing_must_haves: list[str] = []
    job_id: str | None = None
    applicant_id: str | None = None


# ---------- Core ----------

def match(job_points, applicant_points, sim, must_haves=()):
    """job_points / applicant_points: {uri: points}. must_haves: URIs the employer marked must_have.
    Returns a MatchResult (without ids)."""
    J, A = list(job_points), list(applicant_points)
    e = np.array([job_points[u] for u in J], dtype=float)
    a = np.array([applicant_points[u] for u in A], dtype=float)

    S_ja = sim.matrix(J, A)
    num = e @ S_ja @ a
    den = math.sqrt((e @ sim.matrix(J, J) @ e) * (a @ sim.matrix(A, A) @ a))
    score = float(np.clip(num / den, 0, 1)) if den > 0 else 0.0

    links = []
    for i, u in enumerate(J):
        # Best applicant skill for this requirement; ties go to the skill they put more points on.
        j = max(range(len(A)), key=lambda k: (S_ja[i, k], a[k])) if A else None
        s = float(S_ja[i, j]) if j is not None else 0.0
        links.append(SkillLink(
            job_skill_uri=u, job_skill=sim.label.get(u, u), job_points=int(e[i]),
            applicant_skill_uri=A[j] if s > 0 else None,
            applicant_skill=sim.label.get(A[j], A[j]) if s > 0 else None,
            applicant_points=int(a[j]) if s > 0 else 0,
            similarity=round(s, 3),
        ))
    links.sort(key=lambda l: (-l.job_points, -l.similarity))

    coverage = sum(l.job_points * l.similarity for l in links) / e.sum() if e.sum() else 0.0
    missing = [l.job_skill for l in links if l.job_skill_uri in set(must_haves) and l.similarity == 0]
    return MatchResult(score=round(score, 3), coverage=round(coverage, 3), links=links,
                       missing_must_haves=missing)


def explain(result):
    """Plain-language lines for the recruiter (or, mirrored, for the applicant)."""
    covered = round(result.coverage * POINT_BUDGET, 1)
    lines = [f"match {result.score:.2f} · covers {covered:g} of the employer's {POINT_BUDGET} points"]
    for l in result.links:
        if l.similarity == 0:
            lines.append(f"  - {l.job_skill} (job: {l.job_points}): not covered")
        elif l.similarity == 1:
            lines.append(f"  + {l.job_skill} (job: {l.job_points}, applicant: {l.applicant_points})")
        else:
            lines.append(f"  ~ {l.job_skill} (job: {l.job_points}) <- {l.applicant_skill} "
                         f"(applicant: {l.applicant_points}, similarity {l.similarity:.2f})")
    if result.missing_must_haves:
        lines.append(f"  ! missing must-haves: {', '.join(result.missing_must_haves)}")
    return lines


# ---------- With the database ----------

def rank_applicants(conn, job_id, sim):
    """All applicants for one job, best first."""
    import db
    job = db.get_job(conn, job_id)
    if job is None:
        raise ValueError(f"no job with id {job_id}")
    job_pts = {s.uri: s.points for s in job.skills}
    must = [s.uri for s in job.skills if s.priority == "must_have"]
    results = []
    for applicant_id, pts in db.applicant_points(conn).items():
        r = match(job_pts, pts, sim, must)
        r.job_id, r.applicant_id = job_id, applicant_id
        results.append(r)
    return sorted(results, key=lambda r: (-r.score, -r.coverage, r.applicant_id))


def rank_jobs(conn, applicant_id, sim):
    """All jobs for one applicant, best first."""
    import db
    pts = db.applicant_points(conn).get(applicant_id)
    if pts is None:
        raise ValueError(f"no applicant with id {applicant_id}")
    results = []
    for j in db.list_jobs(conn):
        job = db.get_job(conn, j["id"])
        r = match({s.uri: s.points for s in job.skills}, pts, sim,
                  [s.uri for s in job.skills if s.priority == "must_have"])
        r.job_id, r.applicant_id = j["id"], applicant_id
        results.append(r)
    return sorted(results, key=lambda r: (-r.score, -r.coverage, r.job_id))


# ---------- Demo with synthetic profiles ----------

DEMO_JOB = {"debug software": 4, "JavaScript": 3, "interact with users to gather requirements": 2,
            "solve technical problems": 1}
DEMO_APPLICANTS = {
    "same skills, same priorities": dict(DEMO_JOB),
    "same skills, other priorities": {"debug software": 1, "JavaScript": 1,
                                      "interact with users to gather requirements": 4, "solve technical problems": 4},
    "near-synonyms": {"troubleshoot": 5, "JavaScript Framework": 5},
    "partial + extra": {"JavaScript": 4, "Finnish": 3, "accounting": 3},
    "unrelated": {"accounting": 5, "handle customer complaints": 3, "train employees": 2},
}


def demo(sim):
    by_label = {v: k for k, v in sim.label.items()}
    to_uris = lambda d: {by_label[l]: p for l, p in d.items()}
    job = to_uris(DEMO_JOB)
    print("Job:", ", ".join(f"{l} {p}" for l, p in DEMO_JOB.items()))
    results = [(name, match(job, to_uris(app), sim)) for name, app in DEMO_APPLICANTS.items()]
    for name, r in sorted(results, key=lambda x: -x[1].score):
        print(f"\n[{name}]  ({', '.join(f'{l} {p}' for l, p in DEMO_APPLICANTS[name].items())})")
        print("\n".join(explain(r)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["job", "applicant", "demo"])
    parser.add_argument("id", nargs="?")
    parser.add_argument("-n", type=int, default=10, help="how many results to show")
    args = parser.parse_args()

    sim = SkillSimilarity()
    if args.mode == "demo":
        demo(sim)
        return
    if not args.id:
        parser.error(f"{args.mode} needs an id (see: db.py list)")

    import db
    conn = db.connect()
    if args.mode == "job":
        for r in rank_applicants(conn, args.id, sim)[:args.n]:
            print(f"\napplicant {r.applicant_id}")
            print("\n".join(explain(r)))
    else:
        for r in rank_jobs(conn, args.id, sim)[:args.n]:
            print(f"\njob {r.job_id}: {db.get_job(conn, r.job_id).title}")
            print("\n".join(explain(r)))


if __name__ == "__main__":
    main()
