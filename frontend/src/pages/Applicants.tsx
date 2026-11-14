import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, formatDate, POINT_BUDGET, type MatchResult } from "../api";
import MatchLinks, { MatchScore } from "../components/MatchLinks";
import { Badge, ErrorBox, PointsBar, Spinner, useAction, useLoad } from "../components/ui";

export function ApplicantList() {
  const { data, error, loading, reload } = useLoad(() => api.applicants.list(), []);
  const [q, setQ] = useState("");
  const rows = (data ?? []).filter(
    (a) => !q || a.id.toLowerCase().includes(q.toLowerCase()) || (a.skills ?? "").toLowerCase().includes(q.toLowerCase()),
  );
  return (
    <div className="page">
      <div className="row-between">
        <h1>Applicants</h1>
        <Link className="btn primary" to="/applicant/new">
          New applicant
        </Link>
      </div>
      <p className="muted small">Profiles are anonymous: skills and points only.</p>
      {data && data.length > 0 && (
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter by id or skill"
          aria-label="Filter applicants"
        />
      )}
      {loading && <Spinner />}
      <ErrorBox error={error} onRetry={reload} />
      {data && data.length === 0 && <p className="muted">No applicants yet.</p>}
      <ul className="rows">
        {rows.map((a) => (
          <li key={a.id}>
            <Link to={`/applicants/${encodeURIComponent(a.id)}`} className="row-link">
              <span className="row-title">{a.id}</span>
              <span className="muted small">{a.skills}</span>
              <span className="muted small nowrap">{formatDate(a.created_at)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ApplicantDetail() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const profile = useLoad(() => api.applicants.get(id), [id]);
  const matches = useLoad(() => api.applicants.matches(id), [id]);
  const jobs = useLoad(() => api.jobs.list(), []);
  const del = useAction();

  const remove = async () => {
    if (!confirm("Delete this profile? This can't be undone.")) return;
    const ok = await del.run(() => api.applicants.remove(id).then(() => true));
    if (ok) nav("/applicants");
  };

  if (profile.loading) return <div className="page"><Spinner /></div>;
  if (profile.error || !profile.data)
    return <div className="page"><ErrorBox error={profile.error} onRetry={profile.reload} /></div>;

  const titles = Object.fromEntries((jobs.data ?? []).map((j) => [j.id, j.title]));
  const results = (matches.data ?? []).filter((m) => m.score > 0);

  return (
    <div className="page">
      <Link to="/applicants" className="back">← All applicants</Link>
      <div className="split">
        <section className="card">
          <h1>Profile</h1>
          <p className="muted small">
            <code>{id}</code>
          </p>
          <h3>Self-ranked skills</h3>
          <ul className="skill-list">
            {profile.data.skills.map((s) => (
              <li key={s.uri}>
                <span className="skill-name">{s.label}</span>
                {s.origin === "added" && <Badge tone="subtle">added</Badge>}
                <PointsBar points={s.points} />
              </li>
            ))}
          </ul>
          {profile.data.skills.some((s) => s.validation_question) && (
            <>
              <h3>In their own words</h3>
              {profile.data.skills
                .filter((s) => s.validation_question)
                .map((s) => (
                  <div key={s.uri} className="answer">
                    <div className="small muted">{s.label}</div>
                    <div className="q-text">{s.validation_question}</div>
                    {s.validation_answer ? (
                      <blockquote>{s.validation_answer}</blockquote>
                    ) : (
                      <p className="muted small">Not answered.</p>
                    )}
                  </div>
                ))}
            </>
          )}
          <ErrorBox error={del.error} />
          <button className="btn danger small" onClick={remove} disabled={del.busy}>
            Delete profile
          </button>
        </section>

        <section>
          <h2>Jobs that fit you</h2>
          <p className="small muted">
            Based on your own skills and points compared with what each employer ranked. Use the gaps to see what
            employers are looking for.
          </p>
          {matches.loading && <Spinner label="Matching…" />}
          <ErrorBox error={matches.error} onRetry={matches.reload} />
          {matches.data && results.length === 0 && <p className="muted">No matching jobs yet.</p>}
          <ol className="matches">
            {results.map((m, i) => (
              <JobMatch key={m.job_id} result={m} title={titles[m.job_id ?? ""] ?? m.job_id ?? ""} defaultOpen={i < 2} />
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}

function JobMatch({ result, title, defaultOpen }: { result: MatchResult; title: string; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const gaps = result.links.filter((l) => l.similarity === 0);
  const gapPoints = gaps.reduce((a, l) => a + l.job_points, 0);
  return (
    <li className={`match card ${open ? "open" : ""}`}>
      <button className="match-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <MatchScore result={result} title={title} />
        <span className="chev" aria-hidden>{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="match-body">
          <MatchLinks result={result} perspective="applicant" />
          {gaps.length > 0 && (
            <p className="small">
              <strong>To grow toward this job:</strong> {gaps.map((g) => g.job_skill).join(", ")} — worth {gapPoints}{" "}
              of the employer's {POINT_BUDGET} points.
            </p>
          )}
          <Link className="small" to={`/jobs/${encodeURIComponent(result.job_id ?? "")}`}>
            View job →
          </Link>
        </div>
      )}
    </li>
  );
}
