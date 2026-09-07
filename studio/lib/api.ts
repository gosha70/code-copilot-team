// Typed client for the session-analytics FastAPI backend.
// The Studio is pure presentation — it never touches a DB directly.

export const BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
  return r.json();
}

// #293 FR-C: the clusters/similar endpoints answer a missing
// prerequisite with 503 AND a {error, prerequisite, guidance} body. The
// plain `get` above discards that body — it throws a message carrying
// only the status — which would force the page to infer the state from
// text. This variant PRESERVES the body so the mapping stays explicit.
export interface ApiFailure {
  ok: false;
  status: number;
  detail?: { error: string; prerequisite: string; guidance: string };
  message: string;
}

export type ApiOutcome<T> = { ok: true; report: T } | ApiFailure;

async function getOrFailure<T>(path: string): Promise<ApiOutcome<T>> {
  let r: Response;
  try {
    r = await fetch(`${BASE}${path}`, { cache: "no-store" });
  } catch (e) {
    return { ok: false, status: 0, message: String(e) };
  }
  if (r.ok) return { ok: true, report: (await r.json()) as T };
  let detail: ApiFailure["detail"];
  try {
    const body = await r.json();
    // FastAPI wraps HTTPException detail; only a fully-shaped
    // prerequisite counts, so a partial body cannot masquerade as one.
    const d = body?.detail;
    if (d && typeof d === "object" && "prerequisite" in d) detail = d;
  } catch {
    // non-JSON error body: fall through to the plain failure
  }
  return {
    ok: false,
    status: r.status,
    detail,
    message: `GET ${path} → ${r.status}`,
  };
}

// Same body-preserving discipline for POSTs whose failure carries a
// prerequisite (the session-analysis run: an unreachable judge is a
// 503 with guidance the page must show verbatim).
async function postOrFailure<T>(
  path: string,
  body: unknown,
): Promise<ApiOutcome<T>> {
  let r: Response;
  try {
    r = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    return { ok: false, status: 0, message: String(e) };
  }
  if (r.ok) return { ok: true, report: (await r.json()) as T };
  let detail: ApiFailure["detail"];
  let message = `POST ${path} → ${r.status}`;
  try {
    const parsed = await r.json();
    const d = parsed?.detail;
    if (d && typeof d === "object" && "prerequisite" in d) detail = d;
    else if (typeof d === "string") message = d;
  } catch {
    // non-JSON error body: keep the status-only message
  }
  return { ok: false, status: r.status, detail, message };
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`POST ${path} → ${r.status}`);
  return r.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`PUT ${path} → ${r.status}`);
  return r.json();
}

export interface ConfigField {
  key: string;
  value: string;
  secret: boolean;
  has_value: boolean;
}

export interface ConfigResponse {
  /** The store the running server is ACTUALLY reading. */
  effective_dsn?: string;
  /** True when a --db flag overrides what .env says. */
  dsn_overridden?: boolean;
  // True when the tool can actually be USED — a reachable store holding
  // sessions — not merely when a .env file exists. See readiness below
  // for which half is missing.
  configured: boolean;
  readiness?: {
    store_reachable: boolean;
    sessions: number;
    env_file_present: boolean;
  };
  fields: ConfigField[];
  judge_default: string;
  judge_backends: string[];
  redaction_modes: string[];
}

// ── shapes (mirror the API JSON) ─────────────────────────────────────
export interface DashboardKpis {
  totals: {
    sessions: number;
    turns: number;
    tool_calls: number;
    errors: number;
    avg_duration_seconds: number;
    total_cost_usd: number;
    cost_per_session: number;
    priced_sessions: number;
    /** Sessions the noise rule left out of every figure above (#307). */
    excluded_noise: number;
  };
  by_copilot: { copilot: string; sessions: number; errors: number }[];
  by_day: { day: string; sessions: number }[];
  tool_usage: { tool: string; count: number; errors: number }[];
  sentiment_distribution: { sentiment: string; count: number }[];
}

export interface CostByOutcome {
  by_phase: { phase: string; cost_usd: number; sessions: number }[];
  by_sentiment: { sentiment: string; cost_usd: number; turns: number }[];
}

// ── #307 Studio Phase 2: numbers a person can trust ─────────────────
export interface LatencySummary {
  measured_turns: number;
  p50: number | null;
  p90: number | null;
  max: number | null;
}
export interface DashboardLatency extends LatencySummary {
  sessions: number;
  by_copilot: ({ copilot: string } & LatencySummary)[];
  basis: string;
}
export interface SessionsResponse {
  sessions: SessionRow[];
  /** How many the same filters would add with include_noise. */
  excluded_noise: number;
  include_noise: boolean;
}
export interface RecentError {
  error_type: string;
  tool_name: string | null;
  message: string | null;
  copilot: string;
  project_path: string | null;
}
export interface LabelDistribution {
  labels: { label: string; true: number; total: number }[];
}
export interface EffortSummary {
  observations: number;
  sufficient: boolean;
  median: number | null;
  p90: number | null;
  max: number | null;
}
export interface EffortEstimate {
  scope: string;
  sessions: number;
  turns: EffortSummary;
  tool_calls: EffortSummary;
  errors: EffortSummary;
  duration_seconds: EffortSummary;
  cost_usd: EffortSummary;
  cost_usd_coverage: {
    sessions_with_any_priced_turn: number;
    sessions_fully_priced: number;
    sessions_with_priceable_turns: number;
  };
  min_observations: number;
  basis: string;
}
export interface OutcomePrediction {
  projects: {
    project_path: string | null;
    attempts: number;
    by_result: Record<string, number>;
    predicted_pass_rate: number | null;
    sufficient: boolean;
  }[];
  sessions_total: number;
  sessions_with_outcome: number;
  min_observations: number;
  basis: string;
}
export interface LabelCorrelation {
  coverage: {
    labelled_turns: number;
    archived_turns: number;
    labelled_turns_with_trace: number;
  };
  labels: {
    label: string;
    correlated_turns: number;
    true_count: number;
    true_rate: number | null;
    avg_trace_chars: number | null;
    avg_interaction_quality: number | null;
    sufficient: boolean;
  }[];
  rubric_name: string | null;
  min_support: number;
  sufficient_labels: number;
}
export interface LabelTrace {
  copilot: string;
  session_id: string;
  project_path: string | null;
  sequence_num: number;
  role: string;
  redaction_mode: string;
  snippet: string;
  sentiment: string | null;
  /** copilot_session.id — links to /sessions/{session_ref}#turn-N. */
  session_ref: number;
}
export interface PhaseProcessReport {
  projects: {
    project_path: string;
    has_workflow_history: boolean;
    features: {
      feature_id: string;
      entries: number;
      phases_seen: string[];
      oscillations: number;
      rework_cycles: number;
      review_observed: boolean;
      occupancy_seconds: { phase: string; seconds: number }[];
    }[];
    history_may_be_truncated: boolean;
  }[];
  projects_with_history: number;
  retention_cap: number;
  any_history_may_be_truncated: boolean;
  absence_note: string;
  source_root_configured: boolean;
}
// ── #309 Learn center ─────────────────────────────────────────────────
export interface DocEntry {
  slug: string;
  /** Repo-relative POSIX path — the client resolves cross-doc links against it. */
  path: string;
  section: string;
  kind: "doc" | "wiki" | "skill" | "agent";
  title: string;
  description: string;
  page_type: string | null;
  generated: boolean;
}
export interface DocSection {
  id: string;
  title: string;
  kind: DocEntry["kind"];
  entries: DocEntry[];
}
export interface DocsIndex {
  sections: DocSection[];
  intents: { id: string; title: string; blurb: string; slug: string }[];
  /** finding category / lever → slug, or "section:<id>". */
  finding_links: Record<string, string>;
  repo_url: string;
  repo_branch: string;
  image_route: string;
}
export interface DocPayload extends DocEntry {
  frontmatter: Record<string, string>;
  body: string;
}
export interface GraphExpand {
  label: string;
  neighbors: { label: string; node: Record<string, unknown> }[];
}

export interface SessionRow {
  id: number;
  copilot: string;
  session_id: string;
  project_path: string | null;
  model: string | null;
  turn_count: number;
  tool_call_count: number;
  error_count: number;
  started_at: string | null;
  ended_at?: string | null;
  duration_seconds?: number | null;
  cost_usd: number | null;
}

export interface TurnRow {
  sequence_num: number;
  role: string;
  content_preview: string | null;
  /** Full archived text when the project opted into trace_archive; null
   *  when there is no archive row (distinct from an empty turn). */
  content: string | null;
  archived: boolean;
  timestamp: string | null;
  /** Seconds since the previous turn; null for the first turn or when a
   *  timestamp is missing. */
  latency_seconds: number | null;
  has_tool_use: boolean;
  slash_command: string | null;
  sentiment: string | null;
  interaction_quality: number | null;
  user_corrects_agent: boolean | null;
  rework_detected: boolean | null;
}

export interface SessionLatency {
  measured_turns: number;
  p50: number;
  p90: number;
  max: number;
  slowest: { sequence_num: number; seconds: number }[];
}

export interface SessionDetail extends SessionRow {
  turns: TurnRow[];
  tool_usage: { tool: string; count: number }[];
  errors: { error_type: string; tool_name: string; message: string }[];
  /** Over assistant turns only; null when no turn carries a timestamp. */
  latency: SessionLatency | null;
}

// ── session-level analysis (#65 Phase 1) ──────────────────────────────
export type AnalysisKind = "tuning" | "coaching" | "efficiency";
export const ANALYSIS_KINDS: AnalysisKind[] = [
  "tuning",
  "coaching",
  "efficiency",
];

export interface TuningFinding {
  category:
    "steering" | "permissions" | "hooks" | "skills" | "model" | "workflow";
  severity: "high" | "medium" | "low";
  title: string;
  evidence_turns: number[];
  explanation: string;
  recommendation: string;
  config_change: { file: string; diff: string } | null;
}
export interface CoachingPrompt {
  turn: number | null;
  original: string;
  issue: string;
  improved: string;
}
export interface Inefficiency {
  title: string;
  evidence_turns: number[];
  wasted_turns: number | null;
  wasted_seconds: number | null;
  lever: "SCRIPT" | "HOOK" | "SKILL" | "STEERING";
  starter: { file: string; content: string } | null;
}
export interface AnalysisResult {
  summary: string;
  findings?: TuningFinding[];
  overall_score?: number | null;
  prompts?: CoachingPrompt[];
  patterns?: string[];
  inefficiencies?: Inefficiency[];
  /** Items the model offered that the contract dropped (bad enum, blank
   *  coaching row, repeat). An empty list with dropped > 0 is not "clean". */
  dropped_items?: number;
}
export interface AnalysisRow {
  kind: AnalysisKind;
  judge_id: string;
  judge_model: string;
  prompt_version: string;
  transcript_source: "archive" | "preview" | "mixed";
  transcript_chars: number;
  truncated: boolean;
  parse_status: string;
  result: AnalysisResult | null;
  error: string | null;
  created_at: string;
  /** A failed re-run: the earlier parsed result is still stored. */
  kept_previous?: boolean;
}
export interface SessionAnalysisResponse {
  judge: string;
  archive: { archived_turns: number; turns: number };
  kinds: Record<AnalysisKind, AnalysisRow | null>;
  titles: Record<AnalysisKind, string>;
}

export interface GraphCounts {
  node_counts: Record<string, number>;
  tool_failures: { tool: string; invocations: number; errors: number }[];
}

export interface ProjectRedactionRow {
  project_path: string;
  session_count: number;
  redaction_modes: Record<string, number>;
  effective_redaction_mode: string;
}

// E9 (#96): GET /api/dashboard/benchmark — correlation coverage (#91) +
// by-result outcome comparison (#92). Mirrors the server payload exactly;
// the Studio never re-derives these figures client-side.
export interface BenchmarkResultRow {
  result: string;
  attempts: number;
  linked_sessions: number;
  total_cost_usd: number;
  avg_duration_seconds: number;
}

export interface BenchmarkSummary {
  sessions_total: number;
  sessions_linked: number;
  sessions_unlinked: number;
  distinct_benchmark_attempts: number;
  by_result: BenchmarkResultRow[];
}

// routing-shadow (#261): shadow-mode routing evidence. The Studio renders
// E1 evidence sets and derived recommendations READ-ONLY — nothing here
// carries execution authority, and every figure the API serves is bound to
// its artifact source server-side. Shapes mirror the server payloads
// exactly; the Studio never re-derives a figure client-side.
export interface RoutingEvidenceSettings {
  configured: boolean;
  root_count: number;
}

export interface RoutingEvidenceSetSummary {
  state: "valid";
  set_id: string;
  registry_digest: string;
  preset_digest: string;
  task_set_revision: string;
  // E1 permits a null toolchain identity (report/manifest schemas both
  // declare ["string","null"]) — consumers must render it, not crash.
  toolchain_digest: string | null;
  tasks: string[];
  arms: string[];
  pareto_status: string | null;
  record_count: number;
}

// A SET-level invalid_evidence state: rendered, never skipped. `label` is
// the directory basename and `detail` is sanitized server-side — neither
// ever carries a filesystem path.
export interface RoutingInvalidEvidenceSet {
  state: "invalid_evidence";
  label: string;
  code: string;
  artifact: string;
  detail: string;
}

export type RoutingEvidenceEntry =
  RoutingEvidenceSetSummary | RoutingInvalidEvidenceSet;

export interface RoutingPerTrialFigures {
  trial: number;
  quality: number | null;
  cost: number | null;
}

export interface RoutingTaskFigures {
  quality: number | null;
  cost: number | null;
  per_trial: RoutingPerTrialFigures[];
}

export interface RoutingArm {
  quality: number | null;
  metrics: Record<string, number | string | null>;
  cost: { value: number | null; status: string; reason: string | null };
  insufficient: Record<string, string>;
  selections: Record<string, string | Record<string, string>>;
  tasks: Record<string, RoutingTaskFigures>;
}

export type RoutingPareto =
  | { status: "ok"; frontier: { arm: string; quality: number; cost: number }[] }
  | { status: "insufficient_evidence"; reason: string };

export interface RoutingReport {
  schema_version: number;
  quality_fn: string;
  components_included: string[];
  cost_basis: string;
  preset_digest: string;
  fingerprint: {
    registry_digest: string;
    preset_digest: string;
    execution_identity: unknown[];
    task_set_revision: string;
    toolchain_digest: string | null;
  };
  source_artifacts: {
    routing_runs_sha256: string;
    outcome_matrix_sha256: string;
  };
  arms: Record<string, RoutingArm>;
  pareto: RoutingPareto;
}

export interface RoutingEvidenceDetail {
  set_id: string;
  report: RoutingReport;
  record_count: number;
}

export interface RoutingFigureSource {
  artifact: "report";
  pointer: string;
}

export interface RoutingDeltaSource {
  operation: "subtract";
  lhs: RoutingFigureSource;
  rhs: RoutingFigureSource;
}

// The closed locator vocabulary (recommendation.schema.json): record
// indices into routing-runs, arm-by-task report figures, or matrix cell
// coordinates. No shape is ever a filesystem path.
export type RoutingEvidenceLocator =
  | { record: number; decision?: number }
  | { arm: string; task: string }
  | { cell: { task: string; profile: string; trial: number } };

export type RoutingOutcome =
  "switch_profile" | "no_change_recommended" | "insufficient_data";

export interface RoutingRecommendation {
  schema_version: 1;
  evidence_set_id: string;
  task_id: string;
  actual: {
    per_trial: {
      trial: number;
      chain: string[];
      delegated: boolean;
      reconciled: boolean;
    }[];
  };
  suggested: {
    arm: "always_best" | "always_cheapest";
    profile_id: string;
  } | null;
  oracle_ceiling: {
    quality: number | null;
    cost: number | null;
    sources: {
      quality: RoutingFigureSource | null;
      cost: RoutingFigureSource | null;
    };
  };
  divergence: Record<
    string,
    {
      quality_delta: number | null;
      cost_delta: number | null;
      cost_basis: string;
      sources: {
        quality_delta: RoutingDeltaSource | null;
        cost_delta: RoutingDeltaSource | null;
      };
    }
  >;
  outcome: RoutingOutcome;
  confidence: {
    grade: "high" | "moderate" | "low";
    basis: {
      trials: number;
      agreement: number | null;
      components_included: string[];
      insufficiency_refs: string[];
      unevaluated_trials?: number[];
    };
  };
  evidence_refs: {
    evidence_set_id: string;
    artifact: string;
    locator: RoutingEvidenceLocator;
  }[];
}

// The closed read-only artifact surface (T4 round-2): every locator is
// followable — each validated artifact serves verbatim, addressed only by
// set id and the closed artifact name, never a path.
export type RoutingArtifactName = "report" | "routing_runs" | "outcome_matrix";

export interface RoutingArtifactPayload {
  set_id: string;
  artifact: RoutingArtifactName;
  content:
    | RoutingReport
    | { records: Record<string, unknown>[] }
    | Record<string, unknown>;
}

export interface RoutingRecommendationsPayload {
  set_id: string;
  recommendations: RoutingRecommendation[];
}

// routing-calibration (#266): the calibration gates and the shadow kNN
// recommender. Read-only, like everything above it — no surface here
// changes a routing decision, and no payload carries a filesystem path.
export type RoutingGateId =
  | "telemetry_complete"
  | "labeled_volume"
  | "heldout_evaluated"
  | "false_downgrade"
  | "floors_authoritative";

export type RoutingGateStatus = "pass" | "fail" | "insufficient_data";

// Addressable gate evidence (FR-E3-1): a closed set of coordinates the
// panel opens through the existing read-only surfaces — never an opaque
// string, never a path.
export type RoutingGateEvidenceRef =
  | { kind: "evidence_set"; evidence_set_id: string }
  | { kind: "task"; evidence_set_id: string; task_id: string }
  | { kind: "evaluation_report" }
  | { kind: "evaluation_result"; evidence_set_id: string; task_id: string };

export interface RoutingGate {
  id: RoutingGateId;
  status: RoutingGateStatus;
  measured: number | string | null;
  threshold: number | string | null;
  reason: string | null;
  evidence_refs: RoutingGateEvidenceRef[];
}

export interface RoutingCalibrationReport {
  schema_version: 1;
  corpus_id: string;
  policy_id: string;
  corpus: { sets: number; invalid_sets: number; labeled_tasks: number };
  gates: RoutingGate[];
  calibrated: boolean;
}

// The evaluation aggregates rendered BESIDE the verdicts. `agreement` is
// here on purpose: no gate consumes it, and a recommender that keeps
// everything clears every gate honestly while proposing nothing — the
// gates are the safety reading, agreement is the usefulness one.
export interface RoutingEvaluationSummary {
  present: boolean;
  stale: boolean;
  stale_reasons: string[];
  agreement: number | null;
  compared: number | null;
  evaluated: number | null;
  refused: number | null;
  unresolved_tier: number | null;
  unevaluable: number | null;
  false_downgrades: number | null;
  false_downgrade_rate: number | null;
  floor_violations: number | null;
}

export interface RoutingEvaluationPolicy {
  feature_vocabulary: string;
  k: number;
  k_min: number;
  distance_metric: string;
  vote_epsilon: number;
  normalization: string;
  tier_floor: string;
  policy_source_digest: string | null;
  max_false_downgrade_rate: number;
}

export type RoutingPayloadState = "report" | "insufficient_data";

export interface RoutingCalibrationPayload {
  state: RoutingPayloadState;
  reason: string | null;
  report: RoutingCalibrationReport | null;
  evaluation: RoutingEvaluationSummary;
  policy: RoutingEvaluationPolicy | null;
}

export interface RoutingEvaluationReport {
  schema_version: 1;
  corpus_id: string;
  policy_id: string;
  policy: RoutingEvaluationPolicy;
  split: "leave_one_task_out";
  results: {
    evidence_set_id: string;
    task_id: string;
    predicted: { outcome: RoutingOutcome; suggested: RoutingSuggestion };
    truth: { outcome: RoutingOutcome; suggested: RoutingSuggestion };
    downgrade_flag: boolean;
  }[];
  agreement: number | null;
  false_downgrades: number;
  evaluated: number;
  unevaluable: number;
  false_downgrade_rate: number | null;
  floor_violations: number;
  compared: number;
  refused: number;
  unresolved_tier: number;
}

export interface RoutingEvaluationPayload {
  state: RoutingPayloadState;
  reason: string | null;
  report: RoutingEvaluationReport | null;
  staleness: { stale: boolean; reasons: string[] } | null;
}

export type RoutingSuggestion = {
  arm: "always_best" | "always_cheapest";
  profile_id: string;
} | null;

export interface RoutingKnnRecommendation {
  schema_version: 1;
  evidence_set_id: string;
  task_id: string;
  policy_id: string;
  outcome: RoutingOutcome;
  suggested: RoutingSuggestion;
  neighbors: {
    evidence_set_id: string;
    task_id: string;
    distance: number;
    label: { outcome: RoutingOutcome; suggested: RoutingSuggestion };
    evidence_refs: {
      evidence_set_id: string;
      artifact: string;
      locator: RoutingEvidenceLocator;
    }[];
  }[];
  k: number;
  k_min: number;
  distance_metric: string;
  insufficient_reason: string | null;
}

export interface RoutingKnnPayload {
  state: RoutingPayloadState;
  reason: string | null;
  set_id: string;
  recommendations: RoutingKnnRecommendation[];
}

// #293: mirrors the server payloads exactly (the Studio never
// re-derives a figure — see ClustersView's FR-A note).
export type { ClusterReport, ClusterRow } from "./clusterStates";
import type { ClusterReport } from "./clusterStates";

export interface SimilarNeighbor {
  session_key: string;
  id: number | null;
  project_path: string | null;
  started_at: string | null;
  score: number;
  basis: string;
  kpi: Record<string, unknown> | null;
}

export interface SimilarResponse {
  session_id: number;
  basis: string;
  scores_are: string;
  neighbors: SimilarNeighbor[];
}

// E1 (#65): per-developer rollup. `is_single_developer` is not a
// convenience flag — every real store is single-developer today, so the
// UI has to explain that rather than render an empty-looking team view.
export interface DeveloperRow {
  developer_id: string;
  display_name: string | null;
  sessions: number;
  turns: number;
  tool_calls: number;
  errors: number;
  projects: number;
  first_seen: string | null;
  last_seen: string | null;
  // null = no priced turns. Unknown cost, NOT zero cost — the panel
  // renders an em dash rather than $0.00.
  cost_usd: number | null;
  // Coverage is priced_turns out of priceable_turns — turns that were
  // pricing candidates (they carry token counts). NOT out of `turns`:
  // user turns have no model and are never priced, so that ratio would
  // show a fully-priced developer as permanently partial.
  priced_turns: number;
  priceable_turns: number;
}

export interface DeveloperAggregates {
  developers: DeveloperRow[];
  developer_count: number;
  is_single_developer: boolean;
  unattributed_sessions: number;
  registered_without_sessions: string[];
}

// The Analysis pipeline (#65 UX): each step reports whether it has been
// DONE (derived from the store, not a flag) and whether a run is in
// flight, so the page can be operated rather than merely read.
export interface PipelineStep {
  id: string;
  title: string;
  blurb: string;
  done: boolean;
  optional: boolean;
  job: { state: "idle" | "running" | "done" | "failed"; message?: string; seconds?: number };
}

export interface PipelineStatus {
  steps: PipelineStep[];
  /** State of the whole-pipeline run, tracked server-side so it
   *  survives a page reload. */
  all: { state: "idle" | "running" | "done" | "failed"; message?: string; seconds?: number };
  counts: {
    sessions: number;
    labels: number;
    /** Rows the judge WROTE but could not parse — attempts, not labels. */
    label_failures: number;
    kpis: number;
    graph_nodes: number;
    /** Sessions the noise rule excluded from `sessions` (#307). */
    excluded_noise: number;
  };
  /** False when the store did not answer: the counts above are then
   *  zeros from a failed measurement, not an empty store. */
  store_reachable: boolean;
}

// Ranked full-text search over archived trace text (#65 slice B).
export interface TraceHit {
  session_ref: number;
  sequence_num: number;
  copilot: string;
  session_id: string;
  project_path: string | null;
  redaction_mode: string;
  snippet: string;
}

export interface JudgeModels {
  reachable: boolean;
  url: string;
  models: string[];
  error?: string;
}

export const api = {
  pipelineStatus: () => get<PipelineStatus>("/api/pipeline/status"),
  judgeModels: () => get<JudgeModels>("/api/judge/models"),
  searchTraces: (q: string, limit = 50) =>
    get<{ query: string; results: TraceHit[] }>(
      `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  runAll: async (includeJudge: boolean) => {
    const r = await fetch(
      `${BASE}/api/pipeline/run-all?include_judge=${includeJudge}`,
      { method: "POST" },
    );
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body?.detail || `run-all → ${r.status}`);
    }
    return r.json();
  },
  runStep: async (step: string) => {
    const r = await fetch(`${BASE}/api/pipeline/run/${step}`, { method: "POST" });
    if (!r.ok) {
      // 409 means "already running" — a normal thing to hit by
      // double-clicking, so it is surfaced as text, not thrown as a fault.
      const body = await r.json().catch(() => ({}));
      throw new Error(body?.detail || `run ${step} → ${r.status}`);
    }
    return r.json();
  },
  dashboard: () => get<DashboardKpis>("/api/dashboard/kpis"),
  developers: () => get<DeveloperAggregates>("/api/dashboard/developers"),
  labels: () => get<LabelDistribution>("/api/dashboard/labels"),
  costByOutcome: () => get<CostByOutcome>("/api/dashboard/cost"),
  latency: () => get<DashboardLatency>("/api/dashboard/latency"),
  recentErrors: () => get<{ errors: RecentError[] }>("/api/resources/recent-errors"),
  phaseProcess: () => get<PhaseProcessReport>("/api/dashboard/phase-process"),
  predictEffort: (projectPath = "") =>
    get<EffortEstimate>(`/api/predict/effort?project_path=${encodeURIComponent(projectPath)}`),
  predictOutcome: () => get<OutcomePrediction>("/api/predict/outcome"),
  labelCorrelation: () => get<LabelCorrelation>("/api/labels/correlation"),
  labelTraces: (label: string, limit = 50) =>
    get<{ label: string; traces: LabelTrace[] }>(
      `/api/labels/${encodeURIComponent(label)}/traces?limit=${limit}`,
    ),
  health: () => get<{ status: string }>("/api/health"),
  docs: () => get<DocsIndex>("/api/docs"),
  doc: (slug: string) => get<DocPayload>(`/api/docs/${encodeURIComponent(slug)}`),
  graphExpand: (label: string, keyField: string, keyValue: string) =>
    get<GraphExpand>(
      `/api/graph/expand?label=${encodeURIComponent(label)}&key_field=${encodeURIComponent(keyField)}&key_value=${encodeURIComponent(keyValue)}`,
    ),
  benchmark: () => get<BenchmarkSummary>("/api/dashboard/benchmark"),
  sessions: (query = "", copilot = "", includeNoise = false) =>
    get<SessionsResponse>(
      `/api/sessions?query=${encodeURIComponent(query)}&copilot=${encodeURIComponent(copilot)}&include_noise=${includeNoise}`,
    ),
  session: (id: number) => get<SessionDetail>(`/api/sessions/${id}`),
  sessionAnalysis: (id: number) =>
    get<SessionAnalysisResponse>(`/api/sessions/${id}/analysis`),
  runSessionAnalysis: (
    id: number,
    kind: AnalysisKind,
    opts: { judge?: string; force?: boolean } = {},
  ) =>
    postOrFailure<AnalysisRow & { judge: string }>(
      `/api/sessions/${id}/analysis/${kind}`,
      opts,
    ),
  // Body-preserving: an unbuilt or unopenable store answers 503 with
  // guidance the page must show, not "not available yet".
  graphCounts: () => getOrFailure<GraphCounts>("/api/graph/node-counts"),
  // #293: read-only similarity + clustering. `clusters` uses the
  // body-preserving variant because its prerequisite states are the
  // point (FR-C); a thrown status alone cannot distinguish them.
  clusters: () => getOrFailure<ClusterReport>("/api/clusters"),
  similar: (id: number, limit = 10) =>
    getOrFailure<SimilarResponse>(
      `/api/sessions/${id}/similar?limit=${limit}`,
    ),
  graphQuery: (cypher: string) =>
    post<{ rows: Record<string, unknown>[] }>("/api/graph/query", { cypher }),
  settings: () => get<Record<string, unknown>>("/api/settings"),
  projectRedaction: () => get<{ projects: ProjectRedactionRow[] }>("/api/settings/projects"),
  config: () => get<ConfigResponse>("/api/config"),
  saveConfig: (values: Record<string, string>) =>
    put<{ ok: boolean }>("/api/config", { values }),
  // #100: on failure the server returns a curated `error` message plus a
  // stable `error_code` from a closed set (driver_missing / bad_dsn /
  // auth_failed / unreachable / database_missing / permission_denied /
  // unknown) — never driver exception text. Branch on error_code, render
  // error. #101 added three codes rejected BEFORE any connection is
  // attempted: scheme_not_allowed / host_not_allowed / sqlite_file_missing.
  testConnection: (dsn?: string) =>
    post<{
      ok: boolean;
      error?: string;
      error_code?: string;
      // The probe is READ-ONLY: it never creates the CCT schema, so a
      // connectable target that is not an analytics store reports
      // schema_present=false and sessions=null. Null is not zero — zero
      // would read as an empty CCT store.
      schema_present?: boolean;
      sessions?: number | null;
      dialect?: string;
    }>("/api/settings/test-connection", { dsn }),
  analyze: (body: { judge?: string; limit?: number; session_id?: number }) =>
    post<{ judge?: string; by_copilot?: Record<string, unknown> }>("/api/analyze", body),
  // routing-shadow (#261): read-only shadow-mode surfaces.
  routingEvidence: () =>
    get<{ sets: RoutingEvidenceEntry[] }>("/api/routing/evidence"),
  routingEvidenceSet: (setId: string) =>
    get<RoutingEvidenceDetail>(
      `/api/routing/evidence/${encodeURIComponent(setId)}`,
    ),
  routingRecommendations: (setId: string) =>
    get<RoutingRecommendationsPayload>(
      `/api/routing/evidence/${encodeURIComponent(setId)}/recommendations`,
    ),
  routingArtifact: (setId: string, artifact: RoutingArtifactName) =>
    get<RoutingArtifactPayload>(
      `/api/routing/evidence/${encodeURIComponent(setId)}/artifact/${artifact}`,
    ),
  // routing-calibration (#266): gates, the held-out evaluation, and the
  // shadow kNN recommendations served BESIDE the E2 ones.
  routingCalibration: () =>
    get<RoutingCalibrationPayload>("/api/routing/calibration"),
  routingEvaluation: () =>
    get<RoutingEvaluationPayload>("/api/routing/calibration/evaluation"),
  routingKnn: (setId: string) =>
    get<RoutingKnnPayload>(
      `/api/routing/evidence/${encodeURIComponent(setId)}/knn`,
    ),
};
