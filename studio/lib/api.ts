// Typed client for the session-analytics FastAPI backend.
// The Studio is pure presentation — it never touches a DB directly.

const BASE =
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
  configured: boolean;
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
  cost_usd: number | null;
}

export interface TurnRow {
  sequence_num: number;
  role: string;
  content_preview: string | null;
  has_tool_use: boolean;
  slash_command: string | null;
  sentiment: string | null;
  interaction_quality: number | null;
  user_corrects_agent: boolean | null;
  rework_detected: boolean | null;
}

export interface SessionDetail extends SessionRow {
  turns: TurnRow[];
  tool_usage: { tool: string; count: number }[];
  errors: { error_type: string; tool_name: string; message: string }[];
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

export const api = {
  dashboard: () => get<DashboardKpis>("/api/dashboard/kpis"),
  labels: () => get<{ labels: { label: string; true: number; total: number }[] }>("/api/dashboard/labels"),
  costByOutcome: () => get<CostByOutcome>("/api/dashboard/cost"),
  benchmark: () => get<BenchmarkSummary>("/api/dashboard/benchmark"),
  sessions: (query = "", copilot = "") =>
    get<{ sessions: SessionRow[] }>(
      `/api/sessions?query=${encodeURIComponent(query)}&copilot=${encodeURIComponent(copilot)}`,
    ),
  session: (id: number) => get<SessionDetail>(`/api/sessions/${id}`),
  graphCounts: () => get<GraphCounts>("/api/graph/node-counts"),
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
