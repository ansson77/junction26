import { Link } from "react-router-dom";
import { api, POINT_BUDGET } from "../api";
import { useLoad } from "../components/ui";

export default function Home() {
  const health = useLoad(() => api.health(), []);
  return (
    <>
    <section className="hero">
      <div className="hero-inner">
        <h1>Match on what people can actually do.</h1>
        <p className="lead">
          Employers describe the work. Applicants describe their experience. Both spend {POINT_BUDGET} points on the{" "}
          <a href="https://esco.ec.europa.eu/" target="_blank" rel="noreferrer">ESCO</a> skills that matter most — and
          the match is a transparent formula over those points.
        </p>
      </div>
    </section>
    <div className="page">
      <div className="choices">
        <Link to="/applicant/new" className="choice card">
          <div className="choice-kicker">I'm looking for work</div>
          <h2>Build my skill profile</h2>
          <p className="muted">
            Paste your CV or write freely. Confirm the skills, rank your strongest, and show one in your own words.
          </p>
          <span className="choice-go">Start →</span>
        </Link>
        <Link to="/employer/new" className="choice card">
          <div className="choice-kicker">I'm hiring</div>
          <h2>Describe a job</h2>
          <p className="muted">
            Paste a job ad or list the tasks. Answer a few questions, then rank the skills that matter most.
          </p>
          <span className="choice-go">Start →</span>
        </Link>
        <Link to="/bizdev" className="choice card">
          <div className="choice-kicker">I run a company</div>
          <h2>Find what holds growth back</h2>
          <p className="muted">
            Answer a few either-or questions, get ideas to fix it, and see which skills the work takes.
          </p>
          <span className="choice-go">Start →</span>
        </Link>
      </div>

      <section className="principles">
        <div>
          <h3>AI suggests, people decide</h3>
          <p className="muted small">AI only helps describe skills and jobs. Every suggestion is confirmed by a person.</p>
        </div>
        <div>
          <h3>No AI judges people</h3>
          <p className="muted small">Matching is a fixed rule over self-declared skills. Answers are never sent to AI.</p>
        </div>
        <div>
          <h3>Skills first</h3>
          <p className="muted small">No names, photos, ages or nationalities in profiles — just skills and points.</p>
        </div>
      </section>

      <p className="muted small status">
        {health.loading
          ? "Connecting to the server…"
          : health.error
            ? "Server not reachable. Start it with: .venv/bin/uvicorn api:app --reload"
            : `Connected · ${health.data?.esco_skills.toLocaleString()} ESCO skills indexed`}
      </p>
    </div>
    </>
  );
}
