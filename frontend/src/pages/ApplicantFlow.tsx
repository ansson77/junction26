import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  allocationProblem,
  MAX_APPLICANT_SKILLS,
  nonZero,
  POINT_BUDGET,
  type Allocation,
  type ApplicantProfile,
  type ConfirmedSkill,
  type SearchHit,
  type Suggestion,
} from "../api";
import PointAllocator from "../components/PointAllocator";
import { Badge, ErrorBox, PointsBar, Spinner, Steps, useAction } from "../components/ui";

const STEPS = ["Experience", "Confirm skills", "Spend points", "Show it", "Done"];
const LANGUAGES = ["English", "Finnish", "Swedish"];

type Decision = "keep" | "remove";

export default function ApplicantFlow() {
  const [step, setStep] = useState(0);
  const { busy, error, run, clearError } = useAction();

  // Step 1
  const [text, setText] = useState("");
  // Step 2
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [added, setAdded] = useState<ConfirmedSkill[]>([]);
  // Step 3
  const [allocation, setAllocation] = useState<Allocation>({});
  // Step 4
  const [language, setLanguage] = useState("English");
  const [questions, setQuestions] = useState<Record<string, string>>({});
  const [answers, setAnswers] = useState<Record<string, string>>({});
  // Step 5
  const [saved, setSaved] = useState<{ id: string; profile: ApplicantProfile } | null>(null);

  const confirmed: ConfirmedSkill[] = useMemo(
    () => [
      ...suggestions
        .filter((s) => decisions[s.uri] === "keep")
        .map((s) => ({ uri: s.uri, label: s.label, skillType: s.skillType, origin: "suggested" as const })),
      ...added,
    ],
    [suggestions, decisions, added],
  );

  const go = (n: number) => {
    clearError();
    setStep(n);
    window.scrollTo({ top: 0 });
  };

  // ---- step actions ----

  const suggest = async () => {
    const res = await run(() => api.applicant.suggest(text));
    if (!res) return;
    setSuggestions(res);
    setDecisions({});
    go(1);
  };

  const toAllocation = () => {
    // Keep points for skills that are still confirmed, drop the rest.
    const next: Allocation = {};
    for (const s of confirmed) next[s.uri] = allocation[s.uri] ?? 0;
    setAllocation(next);
    go(2);
  };

  // Order matters: ties in points go to the skill listed first (skills_to_validate).
  const orderedAllocation = () => nonZero(Object.fromEntries(confirmed.map((s) => [s.uri, allocation[s.uri] ?? 0])));

  const fetchQuestions = async (lang: string) => {
    const res = await run(() => api.applicant.questions(orderedAllocation(), lang));
    if (!res) return false;
    setQuestions(res);
    return true;
  };

  const toQuestions = async () => {
    if (await fetchQuestions(language)) go(3);
  };

  const changeLanguage = async (lang: string) => {
    setLanguage(lang);
    await fetchQuestions(lang);
  };

  const submit = async () => {
    const chosen = orderedAllocation();
    const skills = confirmed.filter((s) => chosen[s.uri]);
    const trimmed = Object.fromEntries(
      Object.entries(answers)
        .filter(([uri]) => uri in questions)
        .map(([uri, a]) => [uri, a.trim()]),
    );
    const res = await run(() => api.applicant.profile(skills, chosen, questions, trimmed));
    if (!res) return;
    setSaved(res);
    go(4);
  };

  const problem = allocationProblem(allocation, MAX_APPLICANT_SKILLS);
  const labelOf = (uri: string) => confirmed.find((s) => s.uri === uri)?.label ?? uri;

  return (
    <div className="page narrow">
      <h1>Applicant profile</h1>
      <p className="lead">
        Describe what you've done in your own words. AI suggests skills from it — you decide what's true.
      </p>
      <Steps steps={STEPS} current={step} />

      {step === 0 && (
        <section className="card">
          <h2>Tell us about your experience</h2>
          <p className="muted">
            Paste your CV or LinkedIn text, or just write freely, in any language. Leave out your name, age and
            other personal details — profiles are anonymous.
          </p>
          <textarea
            rows={10}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="E.g. I kept the books for my family's shop for six years and trained three new staff members…"
          />
          <ErrorBox error={error} onRetry={text.trim() ? suggest : undefined} />
          <div className="actions">
            <button className="btn ghost" onClick={() => go(1)} disabled={busy}>
              Skip — I'll search skills myself
            </button>
            <button className="btn primary" onClick={suggest} disabled={busy || !text.trim()}>
              Suggest skills
            </button>
          </div>
          {busy && <Spinner label="Reading your text and looking up ESCO skills… this can take a little while." />}
        </section>
      )}

      {step === 1 && (
        <>
          <section className="card">
            <h2>Suggested skills</h2>
            {suggestions.length === 0 ? (
              <p className="muted">No suggestions. Search for your skills below.</p>
            ) : (
              <>
                <p className="muted">
                  These are only suggestions. Keep the ones that are true for you and remove the rest.
                </p>
                <ul className="suggestions">
                  {suggestions.map((s) => {
                    const d = decisions[s.uri];
                    return (
                      <li key={s.uri} className={d ? `decided-${d}` : ""}>
                        <div className="sugg-main">
                          <div className="skill-name">
                            {s.label} <Badge>{s.skillType}</Badge>
                          </div>
                          {s.evidence.length > 0 && (
                            <div className="evidence">
                              {s.evidence.map((q, i) => (
                                <q key={i}>{q}</q>
                              ))}
                            </div>
                          )}
                        </div>
                        <div className="toggle">
                          <button
                            className={`btn small ${d === "keep" ? "primary" : ""}`}
                            aria-pressed={d === "keep"}
                            onClick={() => setDecisions({ ...decisions, [s.uri]: "keep" })}
                          >
                            Keep
                          </button>
                          <button
                            className={`btn small ${d === "remove" ? "danger" : ""}`}
                            aria-pressed={d === "remove"}
                            onClick={() => setDecisions({ ...decisions, [s.uri]: "remove" })}
                          >
                            Remove
                          </button>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </section>

          <section className="card">
            <h2>Add skills the AI missed</h2>
            <SkillSearch
              exclude={new Set(confirmed.map((s) => s.uri))}
              onAdd={(h) => {
                if (suggestions.some((s) => s.uri === h.uri)) {
                  setDecisions({ ...decisions, [h.uri]: "keep" });
                } else {
                  setAdded([...added, { uri: h.uri, label: h.label, skillType: h.skillType, origin: "added" }]);
                }
              }}
            />
            {added.length > 0 && (
              <ul className="chips">
                {added.map((s) => (
                  <li key={s.uri} className="chip">
                    {s.label}
                    <button
                      aria-label={`Remove ${s.label}`}
                      onClick={() => setAdded(added.filter((a) => a.uri !== s.uri))}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <div className="actions sticky">
            <button className="btn ghost" onClick={() => go(0)}>
              Back
            </button>
            <span className="muted">{confirmed.length} skills confirmed</span>
            <button className="btn primary" onClick={toAllocation} disabled={confirmed.length === 0}>
              Continue
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <section className="card">
          <h2>Where are you strongest?</h2>
          <p className="muted">
            Spend {POINT_BUDGET} points on up to {MAX_APPLICANT_SKILLS} skills. More points means you're more confident in
            that skill. Skills with 0 points are left out.
          </p>
          <PointAllocator
            items={confirmed.map((s) => ({
              uri: s.uri,
              label: s.label,
              meta: (
                <>
                  <Badge>{s.skillType}</Badge>
                  {s.origin === "added" && <Badge tone="subtle">added by you</Badge>}
                </>
              ),
            }))}
            allocation={allocation}
            onChange={setAllocation}
            maxSkills={MAX_APPLICANT_SKILLS}
          />
          <ErrorBox error={error} />
          <div className="actions">
            <button className="btn ghost" onClick={() => go(1)} disabled={busy}>
              Back
            </button>
            {problem && <span className="muted">{problem}</span>}
            <button className="btn primary" onClick={toQuestions} disabled={!!problem || busy}>
              Continue
            </button>
          </div>
          {busy && <Spinner label="Getting questions…" />}
        </section>
      )}

      {step === 3 && (
        <section className="card">
          <div className="row-between">
            <h2>Show it in your own words</h2>
            <label className="inline">
              Language{" "}
              <select value={language} onChange={(e) => changeLanguage(e.target.value)} disabled={busy}>
                {LANGUAGES.map((l) => (
                  <option key={l}>{l}</option>
                ))}
              </select>
            </label>
          </div>
          <p className="muted">
            One question for each of your top skills. Recruiters read your answer exactly as you write it.{" "}
            <strong>Your answers are never processed by AI.</strong> You can leave a question empty.
          </p>
          {Object.entries(questions).map(([uri, q]) => (
            <div key={uri} className="question">
              <div className="q-skill">
                {labelOf(uri)} <PointsBar points={allocation[uri] ?? 0} />
              </div>
              <label htmlFor={`a-${uri}`} className="q-text">
                {q}
              </label>
              <textarea
                id={`a-${uri}`}
                rows={4}
                value={answers[uri] ?? ""}
                onChange={(e) => setAnswers({ ...answers, [uri]: e.target.value })}
              />
            </div>
          ))}
          <ErrorBox error={error} />
          <div className="actions">
            <button className="btn ghost" onClick={() => go(2)} disabled={busy}>
              Back
            </button>
            <button className="btn primary" onClick={submit} disabled={busy}>
              Save my profile
            </button>
          </div>
          {busy && <Spinner label="Saving…" />}
        </section>
      )}

      {step === 4 && saved && (
        <section className="card">
          <h2>Profile saved</h2>
          <p>
            Your profile id is <code>{saved.id}</code>. Keep it to see how you match after the event.
          </p>
          <ul className="skill-list">
            {saved.profile.skills.map((s) => (
              <li key={s.uri}>
                <span className="skill-name">{s.label}</span>
                <PointsBar points={s.points} />
              </li>
            ))}
          </ul>
          <div className="actions">
            <Link className="btn" to="/applicant/new">
              New profile
            </Link>
            <Link className="btn primary" to={`/applicants/${encodeURIComponent(saved.id)}`}>
              See matching jobs
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}

function SkillSearch({ exclude, onAdd }: { exclude: Set<string>; onAdd: (h: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const query = q.trim();
    if (!query) {
      setHits([]);
      return;
    }
    let alive = true;
    const t = setTimeout(() => {
      setLoading(true);
      setError(null);
      api.applicant
        .search(query, 8)
        .then((h) => alive && setHits(h))
        .catch((e) => alive && setError(e))
        .finally(() => alive && setLoading(false));
    }, 300);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q]);

  return (
    <div className="search">
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search ESCO skills, e.g. bookkeeping, Python, customer service"
        aria-label="Search skills"
      />
      {loading && <Spinner label="Searching…" />}
      <ErrorBox error={error} />
      {hits.length > 0 && (
        <ul className="hits">
          {hits.map((h) => (
            <li key={h.uri}>
              <div>
                <div className="skill-name">
                  {h.label} <Badge>{h.skillType}</Badge>
                </div>
                {h.description && <div className="muted small clamp">{h.description}</div>}
              </div>
              <button className="btn small" disabled={exclude.has(h.uri)} onClick={() => onAdd(h)}>
                {exclude.has(h.uri) ? "Added" : "Add"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
