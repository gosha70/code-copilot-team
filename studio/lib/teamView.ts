// What the Team tab shows, as data — pure, so the states script can
// assert it: the store note, the liveness legend, a developer's row,
// a window cell that never prints an unknown cost as zero.

import type { TeamAlert, TeamAlerts, TeamDeveloper, TeamRollup, TeamStatus } from "@/lib/api";

export const LIVENESS_LABEL: Record<TeamDeveloper["liveness"], string> = {
  active: "active",
  idle: "idle",
  unknown: "no heartbeat yet",
};

export const LIVENESS_DOT: Record<TeamDeveloper["liveness"], string> = {
  active: "bg-emerald-500",
  idle: "bg-slate-300",
  unknown: "bg-slate-200 border border-slate-300",
};

/** "active = a heartbeat in the last 5 minutes", never "online". */
export function activeLegend(seconds: number): string {
  const m = Math.round(seconds / 60);
  return `active = a heartbeat in the last ${m} minute${m === 1 ? "" : "s"}; idle = seen before that; last-seen, not a liveness verdict`;
}

/** What the page says about the store it is reading. */
export function storeNote(status: TeamStatus): string {
  if (status.store.shared)
    return `Shared team store (${status.store.dialect}): every developer whose CCT_SA_DB points here appears below.`;
  return "Local store (SQLite): this shows one developer's data. For a team view, point every developer's CCT_SA_DB at one Postgres (cookbook → A team store).";
}

/** A window cell: "$12.34", "$12.34*" when some priceable turns were
 *  unpriced, "—" when nothing in the window was priced. */
export function costCell(r: TeamRollup): string {
  if (r.cost_usd === null) return "—";
  const partial = r.priced_turns < r.priceable_turns ? "*" : "";
  return `$${r.cost_usd.toFixed(2)}${partial}`;
}

export function sessionsCell(r: TeamRollup): string {
  if (!r.sessions) return "—";
  return `${r.sessions.toLocaleString()} · ${r.turns.toLocaleString()} turns`;
}

/** "code-copilot-team · build · 174-team-store" from a heartbeat. */
export function currentWork(d: TeamDeveloper): string {
  const c = d.current;
  if (!c) return "—";
  const parts = [
    c.project_path ? c.project_path.replace(/\/+$/, "").split("/").pop() : "",
    c.phase ?? "",
    c.feature_id ?? "",
  ].filter(Boolean);
  return parts.join(" · ") || "—";
}

export function developerName(d: TeamDeveloper): string {
  return d.display_name ? `${d.display_name} (${d.developer_id})` : d.developer_id;
}

/** True when any window has partial pricing, so the page explains "*". */
export function anyPartial(status: TeamStatus): boolean {
  const rows = [...status.developers.map((d) => d.windows), status.totals.windows];
  return rows.some((w) =>
    (["today", "7d", "30d"] as const).some(
      (k) => w[k].cost_usd !== null && w[k].priced_turns < w[k].priceable_turns,
    ),
  );
}

// ── alerts (#174 Slice D) ─────────────────────────────────────────────

export const ALERT_STYLE: Record<TeamAlert["level"], string> = {
  breach: "border-rose-300 bg-rose-50 text-rose-900",
  warning: "border-amber-300 bg-amber-50 text-amber-900",
};

/** Where an alert points: a session page for runaway kinds, nothing
 *  for a budget scope or an auto-build run. Keyed on the KIND, not on
 *  the subject's shape: an auto-build alert's subject is an object too
 *  (the run), and DeepSeek's review of the first revision found this
 *  helper would have sent it to /sessions/undefined. */
export function alertHref(a: TeamAlert): string | null {
  if (!a.kind.startsWith("runaway-")) return null;
  return typeof a.subject === "object" && "session_id" in a.subject
    ? `/sessions/${a.subject.session_id}`
    : null;
}

/** "2 breaches, 1 warning" / "1 warning" / "" */
export function alertSummary(al: TeamAlerts): string {
  const parts: string[] = [];
  if (al.breaches) parts.push(`${al.breaches} breach${al.breaches === 1 ? "" : "es"}`);
  if (al.warnings) parts.push(`${al.warnings} warning${al.warnings === 1 ? "" : "s"}`);
  return parts.join(", ");
}

const BUDGET_LABEL: Record<string, string> = {
  team_daily_usd: "team per day",
  team_monthly_usd: "team per 30 days",
  developer_daily_usd: "per developer per day",
  project_daily_usd: "per project per day",
};

/** What the empty state says: which budgets are set, which are not,
 *  and that runaway detection always runs. */
export function alertsEmptyNote(al: TeamAlerts): string {
  const set = Object.entries(al.budgets)
    .filter(([, v]) => v !== null)
    .map(([k, v]) => `${BUDGET_LABEL[k] ?? k} $${(v as number).toFixed(2)}`);
  const budgets = set.length
    ? `Budgets: ${set.join(", ")}.`
    : "No budgets set (Settings → Team): only runaway detection is on.";
  const r = al.runaway;
  return `No alerts. ${budgets} A session is a runaway past ${r.max_turns_recent} turns or $${Number(r.max_cost_recent_usd).toFixed(2)} in ${r.recent_minutes} minutes, or ${Math.round(Number(r.max_error_share) * 100)}% errors over its last ${r.recent_turns} turns. Alerts are derived from the store on every read; nothing is stored.`;
}
