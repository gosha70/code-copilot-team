// Typed client for the session-analytics FastAPI backend.
// The Studio is pure presentation — it never touches a DB directly.

const BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET ${path} → ${r.status}`);
  return r.json();
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
  // error.
  testConnection: (dsn?: string) =>
    post<{
      ok: boolean;
      error?: string;
      error_code?: string;
      sessions?: number;
      dialect?: string;
    }>("/api/settings/test-connection", { dsn }),
  analyze: (body: { judge?: string; limit?: number; session_id?: number }) =>
    post<{ judge?: string; by_copilot?: Record<string, unknown> }>("/api/analyze", body),
};
