// What the Runs tab shows, as data — pure, so the states script can
// assert it: the page state from the payload alone, the outcome in the
// driver's own words (never pass/fail), the cost split into metered and
// estimated against the cap, the verifier state, and when to poll.

import type { AutoBuildRun, AutoBuildRuns, RunVerdict } from "@/lib/api";

export type RunsPageState = "no-root" | "empty" | "runs";

export function pageState(d: AutoBuildRuns): RunsPageState {
  if (!d.root.is_dir) return "no-root";
  if (d.runs.length === 0) return "empty";
  return "runs";
}

/** The opening card: what a run is and where these come from. */
export function intro(d: AutoBuildRuns): { headline: string; body: string } {
  const where = `${d.root.path} (${d.root.subdirs.join(", ")})`;
  const what =
    "A run is one attempt of the auto-build driver (scripts/auto-build-loop.sh) on one feature: " +
    "it builds a phase, tests it, has a reviewer gate it, runs the verifiers, then pushes and opens a PR " +
    "— or stops at a policy boundary and says why. Each run leaves a ledger; this page reads them.";
  switch (pageState(d)) {
    case "no-root":
      return {
        headline: "No ledger root yet",
        body:
          `${what} The ledger root ${where} is not a directory: nothing has run on this machine, ` +
          "or the driver writes elsewhere — set CCT_SA_AUTO_BUILD_ROOT in Settings → Auto-build runs.",
      };
    case "empty":
      return {
        headline: "No runs recorded",
        body: `${what} ${where} exists but holds no ledger. Run a feature with the driver and it appears here.`,
      };
    default:
      return {
        headline: `${d.summary.total} run${d.summary.total === 1 ? "" : "s"} under ${where}`,
        body: `${what} ${outcomeSummary(d)}`,
      };
  }
}

/** "1 landed, 3 terminated_policy; 0 without an outcome yet; 1 live" —
 *  the driver's outcome words, counted, never pass/fail. */
export function outcomeSummary(d: AutoBuildRuns): string {
  const s = d.summary;
  const parts = Object.keys(s.by_outcome)
    .sort()
    .map((k) => `${s.by_outcome[k]} ${k}`);
  const head = parts.length ? parts.join(", ") : "no run has an outcome";
  return `${head}; ${s.no_outcome} without an outcome yet; ${s.live} live.`;
}

/** The outcome as the driver wrote it; a run that has not concluded
 *  shows its status instead, marked as not an outcome. */
export function outcomeLabel(run: AutoBuildRun): string {
  if (run.outcome) return run.outcome;
  return `no outcome yet · ${run.status ?? "unknown"}`;
}

export const OUTCOME_STYLE: Record<string, string> = {
  landed: "bg-emerald-100 text-emerald-800",
  terminated_policy: "bg-amber-100 text-amber-900",
  failed: "bg-rose-100 text-rose-800",
};

export function outcomeStyle(run: AutoBuildRun): string {
  return (
    (run.outcome && OUTCOME_STYLE[run.outcome]) || "bg-slate-100 text-slate-700"
  );
}

/** "provider_unavailable — reviewer 'codex' failed …" or "" when the
 *  run recorded no disposition. */
export function dispositionLine(run: AutoBuildRun): string {
  const d = run.disposition;
  if (!d.reason) return "";
  const where = d.phase !== null ? ` (phase ${d.phase})` : "";
  return d.detail ? `${d.reason}${where} — ${d.detail}` : `${d.reason}${where}`;
}

function usd(v: number | null): string {
  return v === null ? "—" : `$${v.toFixed(2)}`;
}

/** "metered $5.30 + estimated $2.00 of $10.00 cap (73%)". The estimated
 *  part is the driver's conservative debit for an unmetered reviewer —
 *  named, never folded into the metered figure. */
export function costLine(run: AutoBuildRun): string {
  const { metered_usd, estimated_usd } = run.cost;
  const cap = run.caps.cost_usd;
  let line = `metered ${usd(metered_usd)}`;
  if (estimated_usd > 0) line += ` + estimated ${usd(estimated_usd)}`;
  if (cap === null || cap <= 0) return `${line} (no cap recorded)`;
  const pct = Math.round(((metered_usd + estimated_usd) / cap) * 100);
  return `${line} of ${usd(cap)} cap (${pct}%)`;
}

/** Widths for a two-segment bar against the cap; both clamp so an
 *  over-cap run fills the bar and says so in `over`. */
export function costSegments(run: AutoBuildRun): {
  metered: number;
  estimated: number;
  over: boolean;
} {
  const cap = run.caps.cost_usd;
  const { metered_usd, estimated_usd } = run.cost;
  if (cap === null || cap <= 0)
    return { metered: 0, estimated: 0, over: false };
  const total = metered_usd + estimated_usd;
  const metered = Math.min(100, (metered_usd / cap) * 100);
  const estimated = Math.min(100 - metered, (estimated_usd / cap) * 100);
  return {
    metered: Math.round(metered),
    estimated: Math.round(estimated),
    over: total > cap,
  };
}

export function duration(seconds: number | null): string {
  if (seconds === null) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

/** "9m 43s of 1h 30m cap", with "over the cap" when it is. */
export function wallLine(run: AutoBuildRun): string {
  const cap = run.caps.wall_clock_sec;
  const base = duration(run.elapsed_sec);
  if (cap === null) return `${base} (no wall-clock cap recorded)`;
  const over =
    run.elapsed_sec !== null && run.elapsed_sec > cap ? " — over the cap" : "";
  return `${base} of ${duration(cap)} cap${over}`;
}

/** "1 of 1 planned phases done (cap 2)". */
export function phasesLine(run: AutoBuildRun): string {
  const p = run.phases;
  const planned = p.planned === null ? "?" : String(p.planned);
  const cap = run.caps.phases !== null ? ` (cap ${run.caps.phases})` : "";
  return `${p.done} of ${planned} planned phase${p.planned === 1 ? "" : "s"} done${cap}`;
}

/** "phase 1: US1 … — done; 1 review round, PASS; 0 fix sessions; 2 commits". */
export function phaseLine(p: AutoBuildRun["phases"]["items"][number]): string {
  const review =
    p.rounds === null
      ? "no review yet"
      : `${p.rounds} review round${p.rounds === 1 ? "" : "s"}, ${p.review_verdict ?? "no verdict"}`;
  return (
    `phase ${p.n ?? "?"}: ${p.title ?? "untitled"} — ${p.status ?? "unknown"}; ${review}; ` +
    `${p.fix_sessions} fix session${p.fix_sessions === 1 ? "" : "s"}; ${p.commits} commit${p.commits === 1 ? "" : "s"}`
  );
}

/** "4 requirements mapped at admission; 4 of 4 green" — or the honest
 *  absence: "verifiers not run" / "no admission contract". */
export function verifierLine(run: AutoBuildRun): string {
  const v = run.verifiers;
  const head =
    v.admission_mapped === null
      ? "no admission contract"
      : `${v.admission_mapped} requirement${v.admission_mapped === 1 ? "" : "s"} mapped at admission`;
  if (!v.results) return `${head}; verifiers not run`;
  return `${head}; ${v.results.green} of ${v.results.total} green`;
}

export function policyLine(run: AutoBuildRun): string {
  const n = run.policy_decisions.length;
  if (!n) return "no policy decisions recorded";
  return `${n} policy decision${n === 1 ? "" : "s"}`;
}

/** No ledger writes a score today; say so rather than draw nothing. */
export function scoresLine(run: AutoBuildRun): string {
  return run.scores === null ? "no scores recorded" : "scores recorded";
}

/** For a run that has not concluded: "in progress — status building,
 *  last state write 12s ago". The driver writes its state at status
 *  transitions, not during a build, so a long phase goes quiet; the
 *  line says how long, and never calls quiet "stopped". */
export function liveLine(run: AutoBuildRun, now: Date = new Date()): string {
  if (run.concluded) return "";
  const ago = run.updated_at
    ? Math.max(0, Math.round((now.getTime() - Date.parse(run.updated_at)) / 1000))
    : null;
  const write = ago === null ? "no state write recorded" : `last state write ${duration(ago)} ago`;
  return `in progress — status ${run.status ?? "unknown"}, ${write}`;
}

export const VERDICT_LABEL: Record<RunVerdict, string> = {
  merged_unmodified: "merged unmodified",
  merged_with_fixes: "merged with fixes",
  rejected: "rejected",
};

export const VERDICT_OPTIONS: { value: RunVerdict; label: string }[] = (
  ["merged_unmodified", "merged_with_fixes", "rejected"] as RunVerdict[]
).map((value) => ({ value, label: VERDICT_LABEL[value] }));

/** "merged with fixes · 2026-09-09 · note" or "no verdict yet". */
export function verdictLine(run: AutoBuildRun): string {
  const v = run.verdict;
  if (!v) return "no verdict yet";
  const when = v.set_at ? ` · ${v.set_at.slice(0, 10)}` : "";
  return `${VERDICT_LABEL[v.verdict]}${when}${v.note ? ` · ${v.note}` : ""}`;
}

/** Poll while any run has not concluded; stop on the first payload
 *  where every run has. Freshness (`live`) is not the test: a build
 *  phase longer than the active window is stale and still running, and
 *  a page that stopped polling on staleness would never see it end. */
export function shouldPoll(d: AutoBuildRuns | null): boolean {
  return !!d && d.runs.some((r) => !r.concluded);
}

/** Small print under the list: skipped directories and verdicts whose
 *  ledger is gone — said, not hidden. */
export function footnotes(d: AutoBuildRuns): string[] {
  const out: string[] = [];
  if (d.skipped.length)
    out.push(
      `${d.skipped.length} director${d.skipped.length === 1 ? "y" : "ies"} without a readable state.json skipped: ${d.skipped.map((s) => s.ledger).join(", ")}.`,
    );
  if (d.duplicates)
    out.push(
      `${d.duplicates} director${d.duplicates === 1 ? "y" : "ies"} carrying an attempt id already listed ignored.`,
    );
  if (d.verdicts_without_ledger)
    out.push(
      `${d.verdicts_without_ledger} verdict${d.verdicts_without_ledger === 1 ? "" : "s"} kept for a run whose ledger is gone.`,
    );
  return out;
}
