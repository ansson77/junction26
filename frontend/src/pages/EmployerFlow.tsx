import { useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  allocationProblem,
  nonZero,
  POINT_BUDGET,
  PRIORITY_LABEL,
  type Allocation,
  type Clarification,
  type JobProfile,
  type JobSkill,
  type JobSpec,
  type Priority,
  type QA,
} from "../api";
import PointAllocator from "../components/PointAllocator";
import { Badge, ErrorBox, PointsBar, PriorityBadge, Spinner, Steps, useAction } from "../components/ui";

const STEPS = ["Describe", "Clarify", "Review tasks", "Rank skills", "Done"];
const MAX_ROUNDS = 2;

export default function EmployerFlow() {
  const [step, setStep] = useState(0);
  const { busy, error, run, clearError } = useAction();

  const [text, setText] = useState("");
  const [qa, setQa] = useState<QA[]>([]);
  const [round, setRound] = useState(0);
  const [clar, setClar] = useState<Clarification | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [spec, setSpec] = useState<JobSpec | null>(null);
  const [skills, setSkills] = useState<JobSkill[]>([]);
  const [allocation, setAllocation] = useState<Allocation>({});
  const [saved, setSaved] = useState<{ id: string; profile: JobProfile } | null>(null);

  const go = (n: number) => {
    clearError();
    setStep(n);
    window.scrollTo({ top: 0 });
  };

  const startClarify = async () => {
    const res = await run(() => api.employer.clarify(text, []));
    if (!res) return;
    setQa([]);
    setClar(res);
    setAnswers({});
    setRound(1);
    go(1);
  };

  const buildSpec = async (allQa: QA[]) => {
    const res = await run(() => api.employer.spec(text, allQa));
    if (!res) return;
    setQa(allQa);
    setSpec(res);
    go(2);
  };

  const answerRound = async () => {
    if (!clar) return;
    const newQa = [
      ...qa,
      ...clar.questions
        .map((q, i) => ({ question: q.question, answer: (answers[i] ?? "").trim() }))
        .filter((x) => x.answer),
    ];
    if (round >= MAX_ROUNDS) return buildSpec(newQa);
    const res = await run(() => api.employer.clarify(text, newQa));
    if (!res) return;
    setQa(newQa);
    setClar(res);
    setAnswers({});
    setRound(round + 1);
  };

  const mapSkills = async () => {
    if (!spec) return;
    const res = await run(() => api.employer.skills(spec));
    if (!res) return;
    setSkills(res);
    setAllocation(Object.fromEntries(res.map((s) => [s.uri, 0])));
    go(3);
  };

  const save = async () => {
    if (!spec) return;
    const res = await run(() => api.employer.profile(spec, skills, nonZero(allocation)));
    if (!res) return;
    setSaved(res);
    go(4);
  };

  const updateTask = (i: number, priority: Priority | null) => {
    if (!spec) return;
    const tasks =
      priority === null ? spec.tasks.filter((_, j) => j !== i) : spec.tasks.map((t, j) => (j === i ? { ...t, priority } : t));
    setSpec({ ...spec, tasks });
  };

  const problem = allocationProblem(allocation);
  const clear = clar && (clar.is_clear_enough || clar.questions.length === 0);

  return (
    <div className="page narrow">
      <h1>Job profile</h1>
      <p className="lead">
        Describe the work in plain language. AI helps turn it into concrete tasks and ESCO skills — you decide what
        matters.
      </p>
      <Steps steps={STEPS} current={step} />

      {step === 0 && (
        <section className="card">
          <h2>What will the person do?</h2>
          <p className="muted">Paste a job ad you already have, or list the tasks in your own words. Any language.</p>
          <textarea
            rows={10}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="E.g. We need someone to fix bugs in our JavaScript web shop and talk to customers about what they need…"
          />
          <ErrorBox error={error} onRetry={text.trim() ? startClarify : undefined} />
          <div className="actions">
            <span />
            <button className="btn primary" onClick={startClarify} disabled={busy || !text.trim()}>
              Continue
            </button>
          </div>
          {busy && <Spinner label="Reading the description…" />}
        </section>
      )}

      {step === 1 && clar && (
        <section className="card">
          <h2>
            Clarify <span className="muted small">round {round} of {MAX_ROUNDS}</span>
          </h2>
          <div className="understood">
            <div className="small muted">Understood so far</div>
            <p>{clar.understood_so_far}</p>
          </div>

          {clear ? (
            <p>The tasks are clear enough to find the skills.</p>
          ) : (
            <>
              <p className="muted">
                A few questions make the tasks concrete. Answer what you can; empty answers are skipped.
              </p>
              {clar.questions.map((q, i) => (
                <div key={i} className="question">
                  <label htmlFor={`cq-${i}`} className="q-text">
                    {q.question}
                  </label>
                  <div className="muted small">{q.why}</div>
                  <textarea
                    id={`cq-${i}`}
                    rows={2}
                    value={answers[i] ?? ""}
                    onChange={(e) => setAnswers({ ...answers, [i]: e.target.value })}
                  />
                  {q.example_answers.length > 0 && (
                    <div className="examples">
                      <span className="small muted">For example:</span>
                      {q.example_answers.map((ex) => (
                        <button key={ex} className="chip-btn" onClick={() => setAnswers({ ...answers, [i]: ex })}>
                          {ex}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </>
          )}

          <ErrorBox error={error} />
          <div className="actions">
            <button className="btn ghost" onClick={() => go(0)} disabled={busy}>
              Back
            </button>
            {clear ? (
              <button className="btn primary" onClick={() => buildSpec(qa)} disabled={busy}>
                Build task list
              </button>
            ) : (
              <>
                <button className="btn" onClick={() => buildSpec(qa)} disabled={busy}>
                  Skip questions
                </button>
                <button className="btn primary" onClick={answerRound} disabled={busy}>
                  {round >= MAX_ROUNDS ? "Build task list" : "Continue"}
                </button>
              </>
            )}
          </div>
          {busy && <Spinner label="Thinking…" />}
        </section>
      )}

      {step === 2 && spec && (
        <section className="card">
          <h2>{spec.title}</h2>
          <p>{spec.summary}</p>

          {spec.flags.length > 0 && (
            <div className="flags">
              <h3>Worth reconsidering</h3>
              <p className="small muted">These requirements may exclude suitable candidates unnecessarily.</p>
              <ul>
                {spec.flags.map((f, i) => (
                  <li key={i}>
                    <strong>{f.requirement}</strong> — {f.concern}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <h3>Tasks</h3>
          <p className="small muted">Check the priorities and remove anything that's wrong.</p>
          <ul className="tasks">
            {spec.tasks.map((t, i) => (
              <li key={i}>
                <div className="task-main">
                  <div>{t.task}</div>
                  {t.source && t.source !== "mock" && (
                    <div className="evidence">
                      <q>{t.source}</q>
                    </div>
                  )}
                </div>
                <div className="task-controls">
                  <select
                    value={t.priority}
                    onChange={(e) => updateTask(i, e.target.value as Priority)}
                    aria-label="Priority"
                  >
                    {(Object.keys(PRIORITY_LABEL) as Priority[]).map((p) => (
                      <option key={p} value={p}>
                        {PRIORITY_LABEL[p]}
                      </option>
                    ))}
                  </select>
                  <button className="btn icon" aria-label="Remove task" onClick={() => updateTask(i, null)}>
                    ×
                  </button>
                </div>
              </li>
            ))}
          </ul>

          <ErrorBox error={error} />
          <div className="actions">
            <button className="btn ghost" onClick={() => go(1)} disabled={busy}>
              Back
            </button>
            <button className="btn primary" onClick={mapSkills} disabled={busy || spec.tasks.length === 0}>
              Find ESCO skills
            </button>
          </div>
          {busy && <Spinner label="Matching tasks to ESCO skills…" />}
        </section>
      )}

      {step === 3 && (
        <section className="card">
          <h2>What matters most?</h2>
          <p className="muted">
            Spend {POINT_BUDGET} points on the skills that matter most for this job. Skills with 0 points are left
            out. Applicants are matched on these points.
          </p>
          <PointAllocator
            items={skills.map((s) => ({
              uri: s.uri,
              label: s.label,
              meta: (
                <>
                  <PriorityBadge priority={s.priority} />
                  <Badge>{s.skillType}</Badge>
                  {s.tasks.length > 0 && <span className="small muted">for: {s.tasks.join("; ")}</span>}
                </>
              ),
            }))}
            allocation={allocation}
            onChange={setAllocation}
          />
          <ErrorBox error={error} />
          <div className="actions">
            <button className="btn ghost" onClick={() => go(2)} disabled={busy}>
              Back
            </button>
            {problem && <span className="muted">{problem}</span>}
            <button className="btn primary" onClick={save} disabled={!!problem || busy}>
              Save job
            </button>
          </div>
          {busy && <Spinner label="Saving…" />}
        </section>
      )}

      {step === 4 && saved && (
        <section className="card">
          <h2>Job saved</h2>
          <p>
            <strong>{saved.profile.title}</strong> — id <code>{saved.id}</code>
          </p>
          <ul className="skill-list">
            {saved.profile.skills.map((s) => (
              <li key={s.uri}>
                <span className="skill-name">{s.label}</span>
                <PriorityBadge priority={s.priority} />
                <PointsBar points={s.points} />
              </li>
            ))}
          </ul>
          <div className="actions">
            <Link className="btn" to="/employer/new">
              New job
            </Link>
            <Link className="btn primary" to={`/shortlist/${encodeURIComponent(saved.id)}`}>
              See matching applicants
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}
