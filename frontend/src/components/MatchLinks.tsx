import { POINT_BUDGET, type MatchResult, type SkillLink } from "../api";
import { Percent } from "./ui";

type Kind = "same" | "similar" | "missing";

function kindOf(l: SkillLink): Kind {
  if (l.similarity === 0 || !l.applicant_skill_uri) return "missing";
  return l.applicant_skill_uri === l.job_skill_uri ? "same" : "similar";
}

/** Score + coverage summary, shared by both perspectives. */
export function MatchScore({ result, title }: { result: MatchResult; title?: string }) {
  const covered = Math.round(result.coverage * POINT_BUDGET * 10) / 10;
  return (
    <div className="match-score">
      <div className="score-ring" style={{ ["--p" as string]: result.score }}>
        <span>
          <Percent value={result.score} />
        </span>
      </div>
      <div className="score-text">
        <div className="score-title">{title ?? "match"}</div>
        <div className="muted small">
          covers {covered} of the employer's {POINT_BUDGET} points
        </div>
      </div>
    </div>
  );
}

/**
 * One row per employer skill: is it covered, by which applicant skill, how similar.
 * `perspective` only changes the wording ("you" for the applicant's feedback view).
 */
export default function MatchLinks({
  result,
  perspective,
}: {
  result: MatchResult;
  perspective: "recruiter" | "applicant";
}) {
  const who = perspective === "applicant" ? "You" : "Applicant";
  return (
    <div className="links">
      <table>
        <thead>
          <tr>
            <th>Employer needs</th>
            <th className="num">Job pts</th>
            <th>{who}</th>
            <th className="num">{perspective === "applicant" ? "Your pts" : "Their pts"}</th>
          </tr>
        </thead>
        <tbody>
          {result.links.map((l) => {
            const k = kindOf(l);
            return (
              <tr key={l.job_skill_uri} className={`link-${k}`}>
                <td>
                  <span className={`mark mark-${k}`} aria-hidden>
                    {k === "same" ? "✓" : k === "similar" ? "≈" : "–"}
                  </span>
                  {l.job_skill}
                </td>
                <td className="num">{l.job_points}</td>
                <td>
                  {k === "missing" && <span className="muted">not covered</span>}
                  {k === "same" && <span>same skill</span>}
                  {k === "similar" && (
                    <span>
                      {l.applicant_skill}{" "}
                      <span className="muted small">(similarity {l.similarity.toFixed(2)})</span>
                    </span>
                  )}
                </td>
                <td className="num">{k === "missing" ? "" : l.applicant_points}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {result.missing_must_haves.length > 0 && (
        <p className="warn small">
          <strong>Missing must-haves:</strong> {result.missing_must_haves.join(", ")}
        </p>
      )}
    </div>
  );
}
