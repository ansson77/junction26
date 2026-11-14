import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  allocationProblem,
  ApiError,
  nonZero,
  POINT_BUDGET,
  PRIORITY_LABEL,
  type Allocation,
  type BizOptions,
  type CapabilityShift,
  type CompanyProfile,
  type Diagnosis,
  type Idea,
  type Priority,
  type SkillRequirements,
  type TaskCard,
  type TaskCardEdit,
} from "../api";
import PointAllocator from "../components/PointAllocator";
import { Badge, ErrorBox, PriorityBadge, Spinner, Steps, useAction } from "../components/ui";

const STEPS = ["Company", "Diagnosis", "Ideas", "Work to do", "Skills"];
const PRIORITIES = Object.keys(PRIORITY_LABEL) as Priority[];

interface Row {
  id: string;
  original: string;
  origin: "playbook" | "company";
  text: string;
  priority: Priority;
  removed: boolean;
}

export default function BizDevFlow() {
  const [step, setStep] = useState(0);
  const { busy, error, run, clearError } = useAction();
  const [options, setOptions] = useState<BizOptions | null>(null);

  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [shift, setShift] = useState<CapabilityShift | null>(null);
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [card, setCard] = useState<TaskCard | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [added, setAdded] = useState<{ text: string; priority: Priority }[]>([]);
  const [output, setOutput] = useState<SkillRequirements | null>(null);

  useEffect(() => {
    api.bizdev.options().then(setOptions).catch(() => setOptions(null));
  }, []);

  const go = (n: number) => {
    clearError();
    setStep(n);
    window.scrollTo({ top: 0 });
  };

  const sectorName = (key: string) => options?.sectors[key] ?? key.replace(/_/g, " ");

  // ---- Step 1: company -> diagnosis starts ----
  const startWith = async (p: CompanyProfile) => {
    const d = await api.bizdev.diagnose(p);
    setProfile(p);
    setDiagnosis(d);
    go(1);
  };

  // ---- Step 2: diagnosis; when a root cause is locked, load the ideas ----
  const advance = async (d: Diagnosis) => {
    if (!d.root_cause) {
      setDiagnosis(d);
      return;
    }
    const res = await api.bizdev.ideas(d);
    setDiagnosis(d);
    setShift(res.shift);
    setIdeas(res.ideas);
    go(2);
  };

  // ---- Step 3 -> 4: proposed tasks ----
  const toTasks = async () => {
    if (!diagnosis) return;
    const c = await run(() => api.bizdev.taskcard(diagnosis));
    if (!c) return;
    setCard(c);
    setRows(c.tasks.map((t) => ({ id: t.id, original: t.task, origin: t.origin, text: t.task, priority: t.priority, removed: false })));
    setAdded([]);
    go(3);
  };

  // ---- Step 4 -> 5: apply the company's edits, then map to ESCO skills ----
  const toSkills = async () => {
    if (!card || !profile || !diagnosis) return;
    const res = await run(async () => {
      const changes: TaskCardEdit = {
        remove: rows.filter((r) => r.removed).map((r) => r.id),
        edit: Object.fromEntries(rows.filter((r) => !r.removed && r.text.trim() !== r.original).map((r) => [r.id, r.text.trim()])),
        priority: Object.fromEntries(
          rows.filter((r) => !r.removed && r.priority !== card.tasks.find((t) => t.id === r.id)?.priority).map((r) => [r.id, r.priority]),
        ),
        add: added.map((a) => a.text.trim()).filter(Boolean),
      };
      const changed = changes.remove!.length + Object.keys(changes.edit!).length + Object.keys(changes.priority!).length + changes.add!.length;
      let final = changed ? await api.bizdev.edit(card, changes) : card;
      // New tasks come back last, as must-haves; set the priorities the company chose.
      const newTasks = added.filter((a) => a.text.trim());
      const fresh = final.tasks.slice(final.tasks.length - newTasks.length);
      const prio = Object.fromEntries(fresh.map((t, i) => [t.id, newTasks[i].priority]).filter(([, p]) => p !== "must_have"));
      if (Object.keys(prio).length) final = await api.bizdev.edit(final, { priority: prio });
      const out = await api.bizdev.skills(profile, diagnosis, final);
      return { final, out };
    });
    if (!res) return;
    setCard(res.final);
    setOutput(res.out);
    go(4);
  };

  const willMapLive = rows.some((r) => !r.removed && (r.origin === "company" || r.text.trim() !== r.original)) ||
    added.some((a) => a.text.trim());

  return (
    <div className="page narrow">
      <h1>Business development</h1>
      <p className="lead">
        Find out what's holding your company back, what would fix it, and which skills that work takes. No AI judges
        your company: the diagnosis is a fixed set of questions.
      </p>
      <Steps steps={STEPS} current={step} />

      {profile && step > 0 && (
        <div className="company-strip">
          <strong>{profile.name ?? profile.business_id ?? "Your company"}</strong>
          <span className="muted small">
            {sectorName(profile.sector_family)}
            {profile.age_band ? ` · ${profile.age_band}` : ""}
            {profile.business_id ? ` · ${profile.business_id}` : ""}
          </span>
          <Link to="/bizdev" className="small">Change</Link>
        </div>
      )}

      {step === 0 && <CompanyStep options={options} onProfile={startWith} />}

      {step === 1 && diagnosis && (
        <DiagnosisStep diagnosis={diagnosis} onNext={advance} onRestart={() => profile && startWith(profile)} />
      )}

      {step === 2 && shift && (
        <section className="card">
          <h2>{shift.name}</h2>
          <div className="shift">
            <div>
              <div className="small muted">Now</div>
              <p>{shift.current}</p>
            </div>
            <div className="shift-arrow" aria-hidden>→</div>
            <div>
              <div className="small muted">Goal</div>
              <p>{shift.target}</p>
            </div>
          </div>
          {shift.benefit && <p className="small">{shift.benefit}</p>}
          <h3>Three ideas to get there</h3>
          <ol className="ideas">
            {ideas.map((i) => (
              <li key={i.title}>
                <div className="skill-name">{i.title}</div>
                <div className="muted small">{i.why}</div>
                <div className="small">
                  <strong>First step:</strong> {i.first_step}
                </div>
              </li>
            ))}
          </ol>
          <ErrorBox error={error} />
          <div className="actions">
            <button className="btn ghost" onClick={() => go(1)} disabled={busy}>
              Back
            </button>
            <button className="btn primary" onClick={toTasks} disabled={busy}>
              What work does this take?
            </button>
          </div>
          {busy && <Spinner />}
        </section>
      )}

      {step === 3 && card && (
        <section className="card">
          <h2>Confirm the work</h2>
          <p className="muted">
            These tasks are a starting point. Keep, rewrite or remove them, and add your own. Tasks you rewrite or add
            are matched to skills with AI, which takes a few seconds.
          </p>
          <ul className="tasks">
            {rows.map((r, i) => (
              <li key={r.id} className={r.removed ? "removed" : ""}>
                <div className="task-main">
                  <input
                    type="text"
                    value={r.text}
                    disabled={r.removed}
                    aria-label="Task"
                    onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
                  />
                  {!r.removed && (r.origin === "company" || r.text.trim() !== r.original) && (
                    <Badge tone="subtle">your wording</Badge>
                  )}
                </div>
                <div className="task-controls">
                  <select
                    value={r.priority}
                    disabled={r.removed}
                    aria-label="Priority"
                    onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, priority: e.target.value as Priority } : x)))}
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>
                    ))}
                  </select>
                  <button
                    className="btn small"
                    onClick={() => setRows(rows.map((x, j) => (j === i ? { ...x, removed: !x.removed } : x)))}
                  >
                    {r.removed ? "Undo" : "Remove"}
                  </button>
                </div>
              </li>
            ))}
            {added.map((a, i) => (
              <li key={`new-${i}`}>
                <div className="task-main">
                  <input
                    type="text"
                    value={a.text}
                    placeholder="Describe a task in your own words"
                    aria-label="New task"
                    autoFocus
                    onChange={(e) => setAdded(added.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
                  />
                </div>
                <div className="task-controls">
                  <select
                    value={a.priority}
                    aria-label="Priority"
                    onChange={(e) => setAdded(added.map((x, j) => (j === i ? { ...x, priority: e.target.value as Priority } : x)))}
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>
                    ))}
                  </select>
                  <button className="btn small" onClick={() => setAdded(added.filter((_, j) => j !== i))}>
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <button className="btn small" onClick={() => setAdded([...added, { text: "", priority: "must_have" }])}>
            + Add a task
          </button>
          {options?.warnings.map((w) => (
            <p key={w} className="hint">
              <strong>Setup note:</strong> {w}
            </p>
          ))}
          <ErrorBox error={error} />
          <div className="actions">
            <button className="btn ghost" onClick={() => go(2)} disabled={busy}>
              Back
            </button>
            <button
              className="btn primary"
              onClick={toSkills}
              disabled={busy || rows.every((r) => r.removed) && !added.some((a) => a.text.trim())}
            >
              Find the skills
            </button>
          </div>
          {busy && <Spinner label={willMapLive ? "Matching your tasks to ESCO skills…" : "Looking up skills…"} />}
        </section>
      )}

      {step === 4 && output && <OutputStep output={output} />}
    </div>
  );
}

// ---------- Step 1 ----------

function CompanyStep({ options, onProfile }: { options: BizOptions | null; onProfile: (p: CompanyProfile) => Promise<void> }) {
  const { busy, error, run } = useAction();
  const [businessId, setBusinessId] = useState("");
  const [lookupFailed, setLookupFailed] = useState(false);
  const [sector, setSector] = useState("");
  const [name, setName] = useState("");

  const lookup = () =>
    run(async () => {
      try {
        await onProfile(await api.bizdev.profile({ business_id: businessId.trim() }));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          setLookupFailed(true);
          return;
        }
        throw e;
      }
    });

  const manual = () =>
    run(async () =>
      onProfile(
        await api.bizdev.profile({
          sector,
          name: name.trim() || undefined,
          business_id: lookupFailed && businessId.trim() ? businessId.trim() : undefined,
        }),
      ),
    );

  const sample = (key: string) => run(async () => onProfile(await api.bizdev.profile({ sample: key })));

  return (
    <>
      <section className="card">
        <h2>Who are you?</h2>
        <p className="muted">Enter your Business ID (Y-tunnus). We look up your sector and age in the PRH registry.</p>
        <div className="inline-form">
          <input
            type="text"
            value={businessId}
            onChange={(e) => {
              setBusinessId(e.target.value);
              setLookupFailed(false);
            }}
            onKeyDown={(e) => e.key === "Enter" && businessId.trim() && lookup()}
            placeholder="1234567-8"
            aria-label="Business ID"
          />
          <button className="btn primary" onClick={lookup} disabled={busy || !businessId.trim()}>
            Look up
          </button>
        </div>
        {lookupFailed && <p className="hint">We couldn't find it in the PRH registry. Pick your sector below instead.</p>}

        <h3>{lookupFailed ? "Your sector" : "Or pick your sector"}</h3>
        <div className="inline-form">
          <select value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector">
            <option value="">Choose a sector…</option>
            {Object.entries(options?.sectors ?? {}).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Company name (optional)"
            aria-label="Company name"
          />
          <button className="btn" onClick={manual} disabled={busy || !sector}>
            Continue
          </button>
        </div>
        <ErrorBox error={error} />
        {busy && <Spinner />}
      </section>

      {options && options.samples.length > 0 && (
        <section className="card">
          <h2>Try a demo company</h2>
          <div className="samples">
            {options.samples.map((s) => (
              <button key={s.key} className="sample" onClick={() => sample(s.key)} disabled={busy}>
                <span className="skill-name">{s.name}</span>
                <span className="muted small">{options.sectors[s.sector_family] ?? s.sector_family}</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

// ---------- Step 2 ----------

function DiagnosisStep({
  diagnosis,
  onNext,
  onRestart,
}: {
  diagnosis: Diagnosis;
  onNext: (d: Diagnosis) => Promise<void>;
  onRestart: () => void;
}) {
  const { busy, error, run } = useAction();
  const [text, setText] = useState("");
  const q = diagnosis.current_question;

  return (
    <section className="card">
      {q && (
        <>
          <h2>{q.prompt}</h2>
          <div className="ab">
            {(["A", "B"] as const).map((k) => (
              <button
                key={k}
                className="ab-option"
                disabled={busy}
                onClick={() => run(async () => onNext(await api.bizdev.answer(diagnosis, k)))}
              >
                <span className="ab-key">{k}</span>
                <span>{k === "A" ? q.a.label : q.b.label}</span>
              </button>
            ))}
          </div>
          <button
            className="btn ghost small"
            disabled={busy}
            onClick={() => run(async () => onNext(await api.bizdev.answer(diagnosis, "neither")))}
          >
            Neither of these
          </button>
        </>
      )}

      {diagnosis.needs_text && (
        <>
          <h2>In one sentence, what's holding you back?</h2>
          <textarea
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="E.g. Everything waits for the owner, who makes every decision."
          />
          <div className="actions">
            <span />
            <button
              className="btn primary"
              disabled={busy || !text.trim()}
              onClick={() => run(async () => onNext(await api.bizdev.describe(diagnosis, text)))}
            >
              Continue
            </button>
          </div>
        </>
      )}

      {diagnosis.needs_choice && (
        <>
          <h2>Which of these fits best?</h2>
          {diagnosis.text && (
            <p className="muted small">
              You wrote: <q>{diagnosis.text}</q>
            </p>
          )}
          <div className="ab">
            {diagnosis.choices.map((c) => (
              <button
                key={c.id}
                className="ab-option"
                disabled={busy}
                onClick={() => run(async () => onNext(await api.bizdev.choose(diagnosis, c.id)))}
              >
                <span>
                  <span className="skill-name">{c.name}</span>
                  <br />
                  <span className="muted small">{c.current}</span>
                </span>
              </button>
            ))}
          </div>
        </>
      )}

      <ErrorBox error={error} />
      {busy && <Spinner />}
      {diagnosis.answers.length > 0 && (
        <div className="actions">
          <button className="btn ghost small" onClick={onRestart} disabled={busy}>
            Start the questions over
          </button>
        </div>
      )}
    </section>
  );
}

// ---------- Step 5 ----------

function OutputStep({ output }: { output: SkillRequirements }) {
  const download = () => {
    const blob = new Blob([JSON.stringify(output, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "needs.json";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const unmapped = output.tasks.filter((t) => t.status !== "mapped");

  return (
    <>
      <section className="card">
        <h2>Skills this work takes</h2>
        <p className="muted">
          To fix <strong>{output.need.name.toLowerCase()}</strong>, these are the skills behind the work you confirmed.
        </p>
        {output.skills.length === 0 ? (
          <p className="muted">No ESCO skills were found for these tasks.</p>
        ) : (
          <ul className="skill-list">
            {output.skills.map((s) => (
              <li key={s.uri} className="biz-skill">
                <div className="skill-name">
                  {s.label} <Badge>{s.skillType}</Badge>
                  {s.confidence === "medium" && <Badge tone="subtle">related</Badge>}
                </div>
                <PriorityBadge priority={s.priority} />
                <div className="small muted biz-skill-tasks">for: {s.tasks.join("; ")}</div>
              </li>
            ))}
          </ul>
        )}

        {unmapped.length > 0 && (
          <div className="flags">
            <h3>Tasks without skills</h3>
            <ul>
              {unmapped.map((t) => (
                <li key={t.id}>
                  <strong>{t.task}</strong> —{" "}
                  {t.status === "unmapped"
                    ? "not mapped yet: AI skill mapping wasn't available."
                    : "no ESCO skill fitted. Try describing it more concretely."}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="actions">
          <Link className="btn" to="/bizdev">
            Start over
          </Link>
          <button className="btn" onClick={download}>
            Download as JSON
          </button>
        </div>
      </section>

      {output.skills.length > 0 && <PublishJob output={output} />}
    </>
  );
}

/** Optional: rank the skills with points and save them as a job, so the existing matching finds people. */
function PublishJob({ output }: { output: SkillRequirements }) {
  const { busy, error, run } = useAction();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(
    output.company.name ? `${output.need.name} at ${output.company.name}` : output.need.name,
  );
  const [allocation, setAllocation] = useState<Allocation>({});
  const [saved, setSaved] = useState<string | null>(null);
  const problem = allocationProblem(allocation);

  const save = async () => {
    const res = await run(() =>
      api.employer.profile({ ...output.job_spec, title: title.trim() || output.job_spec.title }, output.skills, nonZero(allocation)),
    );
    if (res) setSaved(res.id);
  };

  if (saved)
    return (
      <section className="card">
        <h2>Saved as a job</h2>
        <p>
          <strong>{title}</strong> is now matched against applicants' self-ranked skills.
        </p>
        <Link className="btn primary" to={`/jobs/${encodeURIComponent(saved)}`}>
          See matching people
        </Link>
      </section>
    );

  return (
    <section className="card">
      <h2>Find people for this work</h2>
      {!open ? (
        <>
          <p className="muted">
            Spend {POINT_BUDGET} points on the skills that matter most, and we'll match them against applicants'
            self-ranked skills.
          </p>
          <button className="btn primary" onClick={() => setOpen(true)}>
            Rank skills
          </button>
        </>
      ) : (
        <>
          <label className="q-text" htmlFor="job-title">Job title</label>
          <input id="job-title" type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
          <PointAllocator
            items={output.skills.map((s) => ({ uri: s.uri, label: s.label, meta: <PriorityBadge priority={s.priority} /> }))}
            allocation={allocation}
            onChange={setAllocation}
          />
          <ErrorBox error={error} />
          <div className="actions">
            {problem ? <span className="muted">{problem}</span> : <span />}
            <button className="btn primary" onClick={save} disabled={!!problem || busy}>
              Save as job
            </button>
          </div>
        </>
      )}
    </section>
  );
}
