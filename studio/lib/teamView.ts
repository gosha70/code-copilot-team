// What the Team tab shows, as data — pure, so the states script can
// assert it: the store note, the liveness legend, a developer's row,
// a window cell that never prints an unknown cost as zero.

import type { TeamDeveloper, TeamRollup, TeamStatus } from "@/lib/api";

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
