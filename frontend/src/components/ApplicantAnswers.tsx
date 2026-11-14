import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Spinner, useLoad } from "./ui";

/** The applicant's own words, verbatim. Loaded when the card is opened. */
export default function ApplicantAnswers({ id }: { id: string }) {
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
