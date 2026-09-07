"use client";

import { useEffect, useState } from "react";

export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`bg-white rounded-lg border border-slate-200 shadow-sm p-4 ${className}`}>
      {title && <h3 className="text-sm font-semibold text-slate-500 mb-3">{title}</h3>}
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  note,
  tone = "default",
}: {
  label: string;
  value: string | number;
  /** The denominator or caveat behind the figure. A headline number
   *  whose basis is not stated invites the wrong reading — e.g. a cost
   *  averaged over PRICED sessions read as a cost per session. */
  note?: string;
  /** "warn" for figures where a high number is bad. Colour carries the
   *  judgement so the reader does not have to know which way is good. */
  tone?: "default" | "warn";
}) {
  // Raw counts get thousands separators: 90440 and 9044 are hard to
  // tell apart at a glance, and this is the largest text on the page.
  const shown = typeof value === "number" ? value.toLocaleString() : value;
  return (
    <Card>
      <div
        className={
          "text-3xl font-bold tabular-nums " +
          (tone === "warn" && value !== 0 ? "text-rose-600" : "")
        }
      >
        {shown}
      </div>
      <div className="text-sm text-slate-500 mt-1">{label}</div>
      {note && <div className="text-xs text-slate-400 mt-0.5">{note}</div>}
    </Card>
  );
}

const BADGE_COLORS: Record<string, string> = {
  POSITIVE: "bg-green-100 text-green-800",
  NEUTRAL: "bg-slate-100 text-slate-700",
  NEGATIVE: "bg-orange-100 text-orange-800",
  FRUSTRATED: "bg-red-100 text-red-800",
  command: "bg-blue-100 text-blue-800",
  question: "bg-purple-100 text-purple-800",
  correction: "bg-amber-100 text-amber-900",
  rework: "bg-rose-100 text-rose-800",
  // E9 (#96): benchmark result classes (server's closed vocabulary;
  // "(none)" falls through to the default slate).
  pass: "bg-green-100 text-green-800",
  fail: "bg-rose-100 text-rose-800",
  error: "bg-amber-100 text-amber-900",
  timeout: "bg-purple-100 text-purple-800",
  // routing-shadow (#261): the three recommendation outcomes must be
  // visually DISTINCT — insufficient_data (amber, "cannot conclude") never
  // renders like no_change_recommended (slate, "concluded: keep") — plus
  // the confidence grades and the set-level invalid_evidence state.
  switch_profile: "bg-blue-100 text-blue-800",
  no_change_recommended: "bg-slate-100 text-slate-700",
  insufficient_data: "bg-amber-100 text-amber-900",
  valid: "bg-green-100 text-green-800",
  high: "bg-green-100 text-green-800",
  moderate: "bg-yellow-100 text-yellow-800",
  low: "bg-slate-100 text-slate-700",
  invalid_evidence: "bg-rose-100 text-rose-800",
  // routing-calibration (#266): the overall gate verdict and the stale
  // state. "not calibrated" is the ordinary resting state of an honest
  // corpus, not a failure — it stays slate so it never reads as an alarm,
  // while a stale binding is amber ("cannot conclude"), matching
  // insufficient_data above.
  calibrated: "bg-green-100 text-green-800",
  not_calibrated: "bg-slate-100 text-slate-700",
  stale: "bg-amber-100 text-amber-900",
};

export function Badge({ kind, children }: { kind: string; children: React.ReactNode }) {
  const cls = BADGE_COLORS[kind] || "bg-slate-100 text-slate-700";
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>{children}</span>;
}

//: A categorical palette for charts whose rows are DIFFERENT THINGS.
//: One colour for every bar makes a chart read as a single quantity
//: split up, when "bash" and "file_edit" are unrelated categories.
export const SERIES_COLORS = [
  "bg-blue-500", "bg-violet-500", "bg-emerald-500", "bg-amber-500",
  "bg-rose-500", "bg-cyan-500", "bg-indigo-500", "bg-teal-500",
  "bg-orange-500", "bg-fuchsia-500",
];

//: SEMANTIC colours, where the value already means good or bad. Errors
//: are not "just another series" and should not be the same blue as a
//: session count.
export const SEMANTIC_COLORS: Record<string, string> = {
  POSITIVE: "bg-emerald-500",
  NEUTRAL: "bg-slate-400",
  NEGATIVE: "bg-orange-500",
  FRUSTRATED: "bg-rose-500",
};

export function Bar({
  value,
  max,
  label,
  color = "bg-blue-500",
}: {
  value: number;
  max: number;
  label: string;
  color?: string;
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="group relative flex items-center gap-2 text-sm py-0.5">
      {/* HEAD truncation loses the identifying half of a label. Three
          different tools all rendered as "mcp__claude-in-…", which makes
          the chart unable to answer the question it exists for. Keeping
          the END (direction: rtl) shows the part that differs, and the
          full name is always available on hover. */}
      <span
        className="w-32 truncate text-slate-600 cursor-default"
        style={{ direction: "rtl", textAlign: "left" }}
      >
        {label}
      </span>
      {/* A truncated label must still be readable SOMEWHERE. The native
          title attribute is slow and easy to miss, so the full name
          appears on hover as a real tooltip — and only when it is
          actually needed. */}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 -top-1 z-20 hidden group-hover:block
                   bg-slate-800 text-white text-xs rounded px-2 py-1 shadow-lg whitespace-nowrap"
      >
        {label} — {value.toLocaleString()}
      </span>
      <div className="flex-1 bg-slate-100 rounded h-4 overflow-hidden">
        <div className={`${color} h-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-16 text-right tabular-nums text-slate-500">
        {value.toLocaleString()}
      </span>
    </div>
  );
}

/**
 * Tiny data hook: returns {data, error, loading} for an async loader.
 *
 * `refreshMs` is an OPTIONAL auto-refresh interval (ms). When omitted (or
 * not positive), behavior is exactly the one-shot fetch-on-mount/deps-change
 * from before this option existed. When set, the same loader is re-invoked
 * on a `setInterval` after the initial fetch; the interval is cleared on
 * unmount and reset whenever `deps` or `refreshMs` changes. Background
 * refreshes update `data`/`error` silently — `loading` is only toggled by
 * the initial (or deps-triggered) fetch, never by the periodic poll.
 */
export function useApi<T>(
  loader: () => Promise<T>,
  deps: unknown[] = [],
  refreshMs?: number
): {
  data: T | null;
  error: string | null;
  loading: boolean;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    const fetchOnce = () => {
      loader()
        .then((d) => live && (setData(d), setError(null)))
        .catch((e) => live && setError(String(e)))
        .finally(() => live && setLoading(false));
    };
    setLoading(true);
    fetchOnce();
    let intervalId: ReturnType<typeof setInterval> | undefined;
    if (refreshMs && refreshMs > 0) {
      intervalId = setInterval(fetchOnce, refreshMs);
    }
    return () => {
      live = false;
      if (intervalId) clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refreshMs]);
  return { data, error, loading };
}

/** Cost is NULL for unpriced turns/sessions (never silently 0) — render an
 * em dash rather than "$0.00" so "no price data" is visually distinct from
 * "priced at zero". */
export function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return "—";
  return `$${usd.toFixed(usd < 1 ? 4 : 2)}`;
}

/** Humanized duration (E9, #96): "—" for unavailable (null/zero — some
 * endpoints coerce SQL NULL to 0), "<1s" for sub-second, "Xs" / "Xm Ys"
 * otherwise. Lives beside formatCost so duration rendering can't fork
 * per-page. */
export function formatDuration(seconds: number | null | undefined): string {
  // The UNIT FOLLOWS THE MAGNITUDE. "2283m 47s" is arithmetically right
  // and useless — nobody reads thousands of minutes as 38 hours. Two
  // significant units at every scale, so the number stays legible from
  // seconds to days.
  if (!seconds || seconds <= 0) return "—";
  const s = Math.round(seconds);
  if (s < 1) return "<1s";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}

export function Loading() {
  return <div className="text-slate-400 text-sm py-8">Loading…</div>;
}

export function ErrorNote({ error }: { error: string }) {
  return (
    <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">
      {error}
      <div className="text-red-400 mt-1">
        Is the API running? Start it with <code>./scripts/session-analytics serve</code>.
      </div>
    </div>
  );
}
