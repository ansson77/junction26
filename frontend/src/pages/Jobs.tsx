import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, formatDate, type MatchResult } from "../api";
import MatchLinks, { MatchScore } from "../components/MatchLinks";
import { Badge, ErrorBox, PointsBar, PriorityBadge, Spinner, useAction, useLoad } from "../components/ui";

export function JobList() {
  const { data, error, loading, reload } = useLoad(() => api.jobs.list(), []);
  return (
    <div className="page">
      <div className="row-between">
        <h1>Jobs</h1>
        <Link className="btn primary" to="/employer/new">
          New job
        </Link>
      </div>
      {loading && <Spinner />}
      <ErrorBox error={error} onRetry={reload} />
      {data && data.length === 0 && <p className="muted">No jobs yet.</p>}
      {data && data.length > 0 && (
        <ul className="rows">
          {data.map((j) => (
            <li key={j.id}>
              <Link to={`/jobs/${encodeURIComponent(j.id)}`} className="row-link">
                <span className="row-title">{j.title}</span>
                <span className="muted small">
                  {j.n_skills} skills · {formatDate(j.created_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function JobDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const job = useLoad(() => api.jobs.get(id), [id]);
  const matches = useLoad(() => api.jobs.matches(id), [id]);
  const del = useAction();
  const [showAll, setShowAll] = useState(false);

  const remove = async () => {
    if (!confirm("Delete this job? This can't be undone.")) return;
    const ok = await del.run(() => api.jobs.remove(id).then(() => true));
    if (ok) nav("/jobs");
  };

  if (job.loading) return <div className="page"><Spinner /></div>;
  if (job.error || !job.data) return <div className="page"><ErrorBox error={job.error} onRetry={job.reload} /></div>;
  const j = job.data;

  const results = matches.data ?? [];
  const visible = showAll ? results : results.filter((m) => m.score > 0);

  return (
    <div className="page">
      <Link to="/jobs" className="back">← All jobs</Link>
      <div className="split">
        <section className="card">
          <h1>{j.title}</h1>
          <p>{j.summary}</p>
          <h3>Skills the employer ranked</h3>
          <ul className="skill-list">
            {j.skills.map((s) => (
              <li key={s.uri}>
                <span className="skill-name">{s.label}</span>
                <PriorityBadge priority={s.priority} />
                <PointsBar points={s.points} />
              </li>
            ))}
          </ul>
          <h3>Tasks</h3>
          <ul className="plain">
            {j.tasks.map((t, i) => (
              <li key={i}>
                {t.task} <PriorityBadge priority={t.priority} />
              </li>
            ))}
          </ul>
          {j.flags.length > 0 && (
            <div className="flags">
              <h3>Worth reconsidering</h3>
              <ul>
                {j.flags.map((f, i) => (
                  <li key={i}>
                    <strong>{f.requirement}</strong> — {f.concern}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <ErrorBox error={del.error} />
          <button className="btn danger small" onClick={remove} disabled={del.busy}>
            Delete job
          </button>
        </section>

        <section>
          <div className="row-between">
            <h2>Applicants, best match first</h2>
            <label className="inline small">
              <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show
              non-matches
            </label>
          </div>
          <p className="small muted">
            A fixed formula over self-declared skills and points — no AI scores people. Open a card to see why.
          </p>
          {matches.loading && <Spinner label="Matching…" />}
          <ErrorBox error={matches.error} onRetry={matches.reload} />
          {matches.data && visible.length === 0 && <p className="muted">No matching applicants yet.</p>}
          <ol className="matches">
            {visible.map((m, i) => (
              <ApplicantMatch key={m.applicant_id} rank={i + 1} result={m} />
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}

function ApplicantMatch({ rank, result }: { rank: number; result: MatchResult }) {
  const [open, setOpen] = useState(false);
  const id = result.applicant_id ?? "";
  return (
    <li className={`match card ${open ? "open" : ""}`}>
      <button className="match-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="rank">#{rank}</span>
        <MatchScore result={result} title={id} />
        {result.missing_must_haves.length > 0 && (
          <Badge tone="warn">{result.missing_must_haves.length} must-have missing</Badge>
        )}
        <span className="chev" aria-hidden>{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="match-body">
          <MatchLinks result={result} perspective="recruiter" />
          <ApplicantAnswers id={id} />
        </div>
      )}
    </li>
  );
}

/** The applicant's own words, verbatim. Loaded when the card is opened. */
function ApplicantAnswers({ id }: { id: string }) {
  const { data, error, loading } = useLoad(() => api.applicants.get(id), [id]);
  if (loading) return <Spinner />;
  if (error) return <ErrorBox error={error} />;
  const answered = (data?.skills ?? []).filter((s) => s.validation_question);
  return (
    <div className="answers">
      <h4>In the applicant's own words</h4>
      {answered.length === 0 && <p className="muted small">No validation questions.</p>}
      {answered.map((s) => (
        <div key={s.uri} className="answer">
          <div className="small muted">
            {s.label} · {s.points} pts
          </div>
          <div className="q-text">{s.validation_question}</div>
          {s.validation_answer ? (
            <blockquote>{s.validation_answer}</blockquote>
          ) : (
            <p className="muted small">Not answered.</p>
          )}
        </div>
      ))}
      <Link className="small" to={`/applicants/${encodeURIComponent(id)}`}>
        Full profile →
      </Link>
    </div>
  );
}
