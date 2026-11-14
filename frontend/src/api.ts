// Typed client for the FastAPI backend (api.py). Types mirror the Pydantic models.
// All URLs are relative (/api/...), so the same build works behind the Vite proxy and
// when api.py serves frontend/dist itself.

export const POINT_BUDGET = 10; // points.POINT_BUDGET
export const MAX_APPLICANT_SKILLS = 5; // applicant.MAX_SKILLS

export type Priority = "must_have" | "learnable" | "nice_to_have";
export type Allocation = Record<string, number>;

// ---------- Employer ----------

export interface QA {
  question: string;
  answer: string;
}

export interface ClarifyingQuestion {
  question: string;
  why: string;
  example_answers: string[];
}

export interface Clarification {
  understood_so_far: string;
  is_clear_enough: boolean;
  questions: ClarifyingQuestion[];
}

export interface Task {
  task: string;
  priority: Priority;
  source: string;
  skills: string[];
}

export interface Flag {
  requirement: string;
  concern: string;
}

export interface JobSpec {
  title: string;
  summary: string;
  tasks: Task[];
  flags: Flag[];
}

export interface JobSkill {
  uri: string;
  label: string;
  skillType: string;
  priority: Priority;
  tasks: string[];
  reuseLevel?: string | null;
  confidence?: string | null;
  probability?: number | null;
  sources: string[];
}

export interface RequiredSkill {
  uri: string;
  label: string;
  skillType: string;
  priority: Priority;
  points: number;
  tasks: string[];
}

export interface JobProfile extends JobSpec {
  skills: RequiredSkill[];
}

// ---------- Applicant ----------

export interface Suggestion {
  uri: string;
  label: string;
  skillType: string;
  reuseLevel?: string | null;
  confidence: string;
  probability?: number | null;
  statements: string[];
  evidence: string[];
}

export interface SearchHit {
  uri: string;
  label: string;
  skillType: string;
  reuseLevel?: string | null;
  altLabels: string[];
  description: string;
  score: number;
}

export interface ConfirmedSkill {
  uri: string;
  label: string;
  skillType: string;
  origin: "suggested" | "added";
}

export interface SkillClaim extends ConfirmedSkill {
  points: number;
  validation_question: string;
  validation_answer: string;
}

export interface ApplicantProfile {
  skills: SkillClaim[];
}

// ---------- Stored profiles and matching ----------

export interface JobRow {
  id: string;
  created_at: string;
  title: string;
  n_skills: number;
}

export interface ApplicantRow {
  id: string;
  created_at: string;
  n_skills: number;
  skills: string | null;
}

export interface SkillLink {
  job_skill_uri: string;
  job_skill: string;
  job_points: number;
  applicant_skill_uri: string | null;
  applicant_skill: string | null;
  applicant_points: number;
  similarity: number;
}

export interface MatchResult {
  score: number;
  coverage: number;
  links: SkillLink[];
  missing_must_haves: string[];
  job_id: string | null;
  applicant_id: string | null;
}

// ---------- Business developer (bizdev/models.py) ----------

export interface CompanyProfile {
  business_id: string | null;
  name: string | null;
  sector_family: string;
  tol_code: string | null;
  registered: string | null;
  age_band: string | null;
  source: "prh" | "sample" | "manual";
}

export interface SampleCompany {
  key: string;
  business_id: string;
  name: string;
  sector_family: string;
  tol_code?: string;
  registered?: string;
}

export interface BizOptions {
  samples: SampleCompany[];
  sectors: Record<string, string>;
  warnings: string[];
}

export interface DiagnosisOption {
  label: string;
  next: string | null;
  root_cause: string | null;
}

export interface Hypothesis {
  id: string;
  prompt: string;
  a: DiagnosisOption;
  b: DiagnosisOption;
}

export interface RootCauseChoice {
  id: string;
  name: string;
  current: string;
}

export interface Diagnosis {
  sector_family: string;
  answers: { question_id: string; answer: "A" | "B" | "neither" }[];
  current_question: Hypothesis | null;
  needs_text: boolean;
  needs_choice: boolean;
  choices: RootCauseChoice[];
  text: string | null;
  root_cause: string | null;
}

export interface Idea {
  title: string;
  why: string;
  first_step: string;
}

export interface CapabilityShift {
  root_cause: string;
  name: string;
  current: string;
  target: string;
  benefit: string | null;
}

export interface CardTask {
  id: string;
  task: string;
  priority: Priority;
  origin: "playbook" | "company";
  skills: string[];
}

export interface TaskCard {
  root_cause: string;
  tasks: CardTask[];
}

export interface TaskCardEdit {
  remove?: string[];
  edit?: Record<string, string>;
  add?: string[];
  priority?: Record<string, Priority>;
}

export interface BizSkill {
  uri: string;
  label: string;
  skillType: string;
  reuseLevel: string | null;
  priority: Priority;
  confidence: "high" | "medium";
  probability: number | null;
  tasks: string[];
  sources: string[];
}

export interface SkillRequirements {
  schema: string;
  created: string;
  company: { business_id: string | null; name: string | null; sector_family: string };
  need: { root_cause: string; name: string; current: string; target: string };
  ideas: Idea[];
  tasks: {
    id: string;
    task: string;
    priority: Priority;
    origin: "playbook" | "company";
    status: "mapped" | "unmapped" | "no_match";
    skill_phrases: string[];
  }[];
  skills: BizSkill[];
  job_spec: JobSpec;
}

// ---------- Transport ----------

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function readDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  // FastAPI request validation: [{loc, msg, type}, ...]
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d))).join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the API running (uvicorn api:app)?");
  }
  if (!res.ok) {
    let detail: string | null = null;
    try {
      detail = readDetail((await res.json()).detail, `${res.status} ${res.statusText}`);
    } catch {
      /* not JSON: the dev proxy couldn't reach uvicorn, or an unhandled server crash */
    }
    if (detail === null) {
      detail =
        res.status >= 500
          ? `The API server didn't answer (HTTP ${res.status}). Is it running? ` +
            "Start it with: .venv/bin/uvicorn api:app --reload"
          : `${res.status} ${res.statusText}`;
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<{ status: string; esco_skills: number }>("/health"),

  employer: {
    clarify: (text: string, qa: QA[]) => post<Clarification>("/employer/clarify", { text, qa }),
    spec: (text: string, qa: QA[]) => post<JobSpec>("/employer/spec", { text, qa }),
    skills: (spec: JobSpec) => post<JobSkill[]>("/employer/skills", { spec }),
    profile: (spec: JobSpec, skills: JobSkill[], allocation: Allocation) =>
      post<{ id: string; profile: JobProfile }>("/employer/profile", { spec, skills, allocation }),
  },

  applicant: {
    suggest: (text: string) => post<Suggestion[]>("/applicant/suggest", { text }),
    search: (q: string, k = 6) =>
      request<SearchHit[]>(`/applicant/search?q=${encodeURIComponent(q)}&k=${k}`),
    questions: (allocation: Allocation, language: string) =>
      post<Record<string, string>>("/applicant/questions", { allocation, language }),
    // `answers` are stored verbatim and shown to recruiters. This is the ONLY place they are sent.
    profile: (
      skills: ConfirmedSkill[],
      allocation: Allocation,
      questions: Record<string, string>,
      answers: Record<string, string>,
    ) => post<{ id: string; profile: ApplicantProfile }>("/applicant/profile", { skills, allocation, questions, answers }),
  },

  bizdev: {
    options: () => request<BizOptions>("/bizdev/options"),
    // One of: {business_id} (PRH lookup, 404 if it fails), {sample}, or {sector, name?, business_id?}.
    profile: (body: { business_id?: string; sample?: string; sector?: string; name?: string }) =>
      post<CompanyProfile>("/bizdev/profile", body),
    diagnose: (profile: CompanyProfile) => post<Diagnosis>("/bizdev/diagnose", { profile }),
    answer: (diagnosis: Diagnosis, answer: "A" | "B" | "neither") =>
      post<Diagnosis>("/bizdev/answer", { diagnosis, answer }),
    describe: (diagnosis: Diagnosis, text: string) => post<Diagnosis>("/bizdev/describe", { diagnosis, text }),
    choose: (diagnosis: Diagnosis, root_cause: string) => post<Diagnosis>("/bizdev/choose", { diagnosis, root_cause }),
    ideas: (diagnosis: Diagnosis) => post<{ shift: CapabilityShift; ideas: Idea[] }>("/bizdev/ideas", { diagnosis }),
    taskcard: (diagnosis: Diagnosis) => post<TaskCard>("/bizdev/taskcard", { diagnosis }),
    edit: (card: TaskCard, changes: TaskCardEdit) => post<TaskCard>("/bizdev/taskcard/edit", { card, ...changes }),
    skills: (profile: CompanyProfile, diagnosis: Diagnosis, card: TaskCard) =>
      post<SkillRequirements>("/bizdev/skills", { profile, diagnosis, card }),
  },

  jobs: {
    list: () => request<JobRow[]>("/jobs"),
    get: (id: string) => request<JobProfile>(`/jobs/${encodeURIComponent(id)}`),
    matches: (id: string) => request<MatchResult[]>(`/jobs/${encodeURIComponent(id)}/matches`),
    remove: (id: string) => request<void>(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }),
    // Networking invites: applicant ids the company invited for this job.
    invites: (id: string) => request<string[]>(`/jobs/${encodeURIComponent(id)}/invites`),
    setInvite: (id: string, applicantId: string, invited: boolean) =>
      request<void>(`/jobs/${encodeURIComponent(id)}/invites/${encodeURIComponent(applicantId)}`, {
        method: invited ? "PUT" : "DELETE",
      }),
  },

  applicants: {
    list: () => request<ApplicantRow[]>("/applicants"),
    get: (id: string) => request<ApplicantProfile>(`/applicants/${encodeURIComponent(id)}`),
    matches: (id: string) => request<MatchResult[]>(`/applicants/${encodeURIComponent(id)}/matches`),
    remove: (id: string) => request<void>(`/applicants/${encodeURIComponent(id)}`, { method: "DELETE" }),
  },
};

// ---------- Small shared helpers ----------

export const PRIORITY_LABEL: Record<Priority, string> = {
  must_have: "Must have",
  learnable: "Can be learned",
  nice_to_have: "Nice to have",
};

export function sumPoints(allocation: Allocation): number {
  return Object.values(allocation).reduce((a, b) => a + b, 0);
}

/** Only skills with points; same check as points.check_allocation. Returns an error or null. */
export function allocationProblem(allocation: Allocation, maxSkills?: number): string | null {
  const chosen = Object.values(allocation).filter((p) => p > 0);
  const total = sumPoints(allocation);
  if (chosen.length === 0) return "Put points on at least one skill.";
  if (maxSkills && chosen.length > maxSkills) return `Choose at most ${maxSkills} skills.`;
  if (total !== POINT_BUDGET) return `Spend exactly ${POINT_BUDGET} points (${total} spent).`;
  return null;
}

export function nonZero(allocation: Allocation): Allocation {
  return Object.fromEntries(Object.entries(allocation).filter(([, p]) => p > 0));
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
