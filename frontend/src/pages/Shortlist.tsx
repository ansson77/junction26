import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, formatDate, POINT_BUDGET, type MatchResult } from "../api";
import MatchLinks from "../components/MatchLinks";
import { ErrorBox, PriorityBadge, Spinner, useAction, useLoad } from "../components/ui";
import ApplicantAnswers from "../components/ApplicantAnswers";
import { demoName } from "../demoNames";

/** Match score 0-100: the soft-cosine score from matching.py, as a whole number. */
const scoreOf = (m: MatchResult) => Math.round(m.score * 100);

function tier(score: number) {
  if (score >= 70) return { label: "Strong match", cls: "tier-strong" };
  if (score >= 40) return { label: "Partial match", cls: "tier-partial" };
  return { label: "Weak match", cls: "tier-weak" };
}

/** Company view: pick your job, see applicants ordered by match score. */
export default function Shortlist() {
  const { id } = useParams();
  return id ? <JobShortlist id={id} /> : <PickJob />;
}

function PickJob() {
  const { data, error, loading, reload } = useLoad(() => api.jobs.list(), []);
  return (
    <div className="page narrow">
      <h1>Shortlist</h1>
      <p className="lead">Pick your job to see applicants ordered by how well they match it.</p>
      {loading && <Spinner />}
      <ErrorBox error={error} onRetry={reload} />
      {data && data.length === 0 && (
        <p className="muted">
          No jobs yet. <Link to="/employer/new">Describe a job</Link> first.
        </p>
      )}
      <ul className="rows">
        {(data ?? []).map((j) => (
          <li key={j.id}>
            <Link to={`/shortlist/${encodeURIComponent(j.id)}`} className="row-link">
              <span className="row-title">{j.title}</span>
              <span className="muted small">{j.n_skills} skills</span>
              <span className="muted small nowrap">{formatDate(j.created_at)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

function JobShortlist({ id }: { id: string }) {
  const nav = useNavigate();
  const jobs = useLoad(() => api.jobs.list(), []);
  const job = useLoad(() => api.jobs.get(id), [id]);
  const matches = useLoad(() => api.jobs.matches(id), [id]);
  const applicants = useLoad(() => api.applicants.list(), []);

  const [hideZero, setHideZero] = useState(true);
  const [mustHavesOnly, setMustHavesOnly] = useState(false);
  // Anonymous by default: the employer judges skills first, and chooses to see names.
  const [anonymous, setAnonymous] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const del = useAction();

  // Networking invites, saved on the server per job. Toggled optimistically; reverted if saving fails.
  const invites = useLoad(() => api.jobs.invites(id), [id]);
  const [invited, setInvited] = useState<Set<string>>(new Set());
  const [invitedOnly, setInvitedOnly] = useState(false);
  const [inviteError, setInviteError] = useState<unknown>(null);
  useEffect(() => setInvited(new Set(invites.data ?? [])), [invites.data]);

  const toggleInvite = async (aid: string) => {
    const on = !invited.has(aid);
    const flip = (value: boolean) =>
      setInvited((prev) => {
        const next = new Set(prev);
        if (value) next.add(aid);
        else next.delete(aid);
        return next;
      });
    flip(on);
    setInviteError(null);
    try {
      await api.jobs.setInvite(id, aid, on);
    } catch (e) {
      flip(!on);
      setInviteError(e);
    }
  };

  const remove = async () => {
    if (!confirm("Delete this job? This can't be undone.")) return;
    const ok = await del.run(() => api.jobs.remove(id).then(() => true));
    if (ok) nav("/shortlist");
  };

  const mustHaveCount = job.data?.skills.filter((s) => s.priority === "must_have").length ?? 0;
  const skillsOf = useMemo(
    () => Object.fromEntries((applicants.data ?? []).map((a) => [a.id, a.skills ?? ""])),
    [applicants.data],
  );

  const all = matches.data ?? [];
  const rows = all.filter(
    (m) =>
      (!hideZero || m.score > 0) &&
      (!mustHavesOnly || m.missing_must_haves.length === 0) &&
      (!invitedOnly || invited.has(m.applicant_id ?? "")),
  );
  const strong = all.filter((m) => scoreOf(m) >= 70).length;

  return (
    <div className="page">
      <div className="row-between">
        <div>
          <Link to="/shortlist" className="back">← All jobs</Link>
          <h1>{job.data?.title ?? "Shortlist"}</h1>
        </div>
        <label className="inline">
          <span className="small muted">Job</span>
          <select value={id} onChange={(e) => nav(`/shortlist/${encodeURIComponent(e.target.value)}`)}>
            {(jobs.data ?? []).map((j) => (
              <option key={j.id} value={j.id}>{j.title}</option>
            ))}
          </select>
        </label>
      </div>

      <ErrorBox error={job.error} onRetry={job.reload} />

      {job.data && (
        <section className="card job-desc">
          <p className="job-summary">{job.data.summary}</p>
          <div className="job-desc-cols">
            <div>
              <h3>Tasks</h3>
              <ul className="plain">
                {job.data.tasks.map((t, i) => (
                  <li key={i}>
                    {t.task} <PriorityBadge priority={t.priority} />
                  </li>
                ))}
              </ul>
            </div>
            {job.data.flags.length > 0 && (
              <div className="flags">
                <h3>Worth reconsidering</h3>
                <ul>
                  {job.data.flags.map((f, i) => (
                    <li key={i}>
                      <strong>{f.requirement}</strong> — {f.concern}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <ErrorBox error={del.error} />
          <div className="job-desc-foot">
            <button className="btn danger small" onClick={remove} disabled={del.busy}>
              Delete job
            </button>
          </div>
        </section>
      )}

      {matches.data && (
        <div className="stats">
          <div>
            <div className="stat-num">{all.filter((m) => m.score > 0).length}</div>
            <div className="small muted">applicants match at all</div>
          </div>
          <div>
            <div className="stat-num">{strong}</div>
            <div className="small muted">strong matches (70+)</div>
          </div>
          <div>
            <div className="stat-num">{all.filter((m) => m.missing_must_haves.length === 0 && m.score > 0).length}</div>
            <div className="small muted">have every must-have</div>
          </div>
          <div>
            <div className="stat-num">{invited.size}</div>
            <div className="small muted">invited to networking</div>
          </div>
        </div>
      )}

      <div className="filters">
        <label className="inline small">
          <input type="checkbox" checked={hideZero} onChange={(e) => setHideZero(e.target.checked)} /> Hide applicants
          with no match
        </label>
        {mustHaveCount > 0 && (
          <label className="inline small">
            <input type="checkbox" checked={mustHavesOnly} onChange={(e) => setMustHavesOnly(e.target.checked)} /> Only
            applicants with every must-have
          </label>
        )}
        <label className="inline small">
          <input type="checkbox" checked={invitedOnly} onChange={(e) => setInvitedOnly(e.target.checked)} /> Only
          invited ({invited.size})
        </label>
        <label className="switch">
          <input
            type="checkbox"
            role="switch"
            checked={anonymous}
            onChange={(e) => setAnonymous(e.target.checked)}
          />
          <span className="switch-track" aria-hidden />
          <span className="small">
            <strong>Anonymous applications</strong>
            <span className="muted"> · {anonymous ? "skills only" : "names shown"}</span>
          </span>
        </label>
      </div>

      <ErrorBox error={inviteError} />
      <ErrorBox error={invites.error} onRetry={invites.reload} />
      {matches.loading && <Spinner label="Matching applicants…" />}
      <ErrorBox error={matches.error} onRetry={matches.reload} />

      {matches.data && rows.length === 0 && <p className="muted">No applicants match these filters.</p>}

      {rows.length > 0 && (
        <div className="shortlist" role="table" aria-label="Applicants ordered by match score">
          <div className="sl-row sl-head" role="row">
            <span role="columnheader">#</span>
            <span role="columnheader">Match score</span>
            <span role="columnheader">Applicant</span>
            <span role="columnheader" className="sl-num">Your points covered</span>
            <span role="columnheader" className="sl-num">Must-haves</span>
            <span role="columnheader">Matched skills</span>
            <span role="columnheader">Networking</span>
          </div>
          {rows.map((m, i) => {
            const aid = m.applicant_id ?? "";
            const score = scoreOf(m);
            const t = tier(score);
            const covered = Math.round(m.coverage * POINT_BUDGET * 10) / 10;
            const isOpen = open === aid;
            return (
              <div key={aid} className={`sl-item ${isOpen ? "open" : ""}`}>
                <div
                  className="sl-row"
                  role="row"
                  tabIndex={0}
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? null : aid)}
                  onKeyDown={(e) => {
                    if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                      e.preventDefault();
                      setOpen(isOpen ? null : aid);
                    }
                  }}
                >
                  <span className="sl-rank" role="cell">{i + 1}</span>
                  <span className="sl-score" role="cell">
                    <span className={`score-num ${t.cls}`}>{score}</span>
                    <span className="score-side">
                      <span className="score-bar"><span className={t.cls} style={{ width: `${score}%` }} /></span>
                      <span className="small muted">{t.label}</span>
                    </span>
                  </span>
                  <span className="sl-applicant" role="cell">
                    {/* Anonymous: the name line stays, blank, so rows keep the same height. */}
                    <span className="sl-name">{anonymous ? " " : demoName(aid)}</span>
                    <span className="small muted clamp1">{skillsOf[aid]}</span>
                  </span>
                  <span className="sl-num" role="cell">
                    <strong>{covered}</strong>
                    <span className="muted"> / {POINT_BUDGET}</span>
                  </span>
                  <span className={`sl-num ${m.missing_must_haves.length ? "warn" : ""}`} role="cell">
                    {mustHaveCount ? `${mustHaveCount - m.missing_must_haves.length} / ${mustHaveCount}` : "–"}
                  </span>
                  <span className="sl-skills" role="cell">
                    {m.links
                      .filter((l) => l.similarity > 0)
                      .map((l) => (
                        <span
                          key={l.job_skill_uri}
                          className={`mini ${l.applicant_skill_uri === l.job_skill_uri ? "mini-same" : "mini-similar"}`}
                          title={
                            l.applicant_skill_uri === l.job_skill_uri
                              ? `${l.job_skill}: same skill`
                              : `${l.job_skill} ≈ ${l.applicant_skill} (similarity ${l.similarity.toFixed(2)})`
                          }
                        >
                          {l.job_skill}
                        </span>
                      ))}
                  </span>
                  <span className="sl-invite" role="cell" onClick={(e) => e.stopPropagation()}>
                    <label className={`switch ${invited.has(aid) ? "on" : ""}`}>
                      <input
                        type="checkbox"
                        role="switch"
                        checked={invited.has(aid)}
                        disabled={invites.loading}
                        onChange={() => toggleInvite(aid)}
                        aria-label={`Invite ${anonymous ? aid : demoName(aid)} to networking`}
                      />
                      <span className="switch-track" aria-hidden />
                      <span className="small">{invited.has(aid) ? "Invited" : "Invite"}</span>
                    </label>
                  </span>
                </div>
                {isOpen && (
                  <div className="sl-detail">
                    <MatchLinks result={m} perspective="recruiter" />
                    <ApplicantAnswers id={aid} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="small muted legend">
        <strong>Match score</strong> (0–100) compares the points you put on each skill with the points the applicant
        put on theirs. Similar skills count partly, and a 100 means the same skills with the same weighting. It's a fixed
        formula over self-declared skills: no AI rates the applicants. <span className="mini mini-same">same skill</span>{" "}
        <span className="mini mini-similar">similar skill</span>{" "}
        {job.data && job.data.skills.some((s) => s.priority === "must_have") && (
          <>
            · <PriorityBadge priority="must_have" /> skills are marked with a dot.
          </>
        )}
      </p>
    </div>
  );
}
