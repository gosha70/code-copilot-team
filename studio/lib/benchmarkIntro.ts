// What the Benchmark page says at the top, as data — pure, so the states
// script can assert the three states (no runs root; a root but nothing
// linked; sessions linked) without a browser. The page used to open with
// four zero tiles and a CLI command; none of that told a person what a
// benchmark run is or what to press.

import type { BenchmarkSummary } from "@/lib/api";

export type BenchmarkState =
  | "unset"
  | "not-a-dir"
  | "unlinked"
  /** Outcomes stored, but no session is currently linked. WHY is not
   *  known from the counts; see unlinkedCause. */
  | "outcomes-only"
  | "linked";

export interface BenchmarkIntro {
  state: BenchmarkState;
  /** One sentence on what is linked, or that nothing is. */
  headline: string;
  /** WHY nothing is linked — only when the last scan's counters say so;
   *  the counts alone cannot tell a missing session id from an unloaded
   *  session or another backend, so nothing is inferred from them. */
  cause: string;
  /** The page offers the step (a runs root exists), else Settings. */
  canLink: boolean;
  /** The root as text for the page, blank when unset. */
  rootLine: string;
}

export function benchmarkState(d: BenchmarkSummary): BenchmarkState {
  if (d.sessions_linked > 0) return "linked";
  if (d.by_result.length > 0) return "outcomes-only";
  if (!d.runs_root.configured) return "unset";
  if (!d.runs_root.is_dir) return "not-a-dir";
  return "unlinked";
}

/** What the last scan established about unlinked records, from its
 *  counters — the ONLY evidence for a cause. Empty when there is none. */
export function unlinkedCause(job: BenchmarkSummary["link_job"]): string {
  const p = job.progress;
  if (job.state !== "done" || !p) return "";
  const parts: string[] = [];
  if (p.null_session_id)
    parts.push(`${p.null_session_id.toLocaleString()} carried no session id`);
  if (p.unmatched)
    parts.push(
      `${p.unmatched.toLocaleString()} named a session that is not loaded`,
    );
  if (p.out_of_scope)
    parts.push(
      `${p.out_of_scope.toLocaleString()} came from a backend other than Claude Code`,
    );
  if (!parts.length) return "";
  return `The last scan read ${(p.scanned ?? 0).toLocaleString()} run records: ${parts.join("; ")}.`;
}

export function benchmarkIntro(d: BenchmarkSummary): BenchmarkIntro {
  const state = benchmarkState(d);
  const root = d.runs_root;
  const rootLine = root.configured ? root.path : "";
  switch (state) {
    case "linked":
      return {
        state,
        headline: `${d.sessions_linked.toLocaleString()} of ${d.sessions_total.toLocaleString()} sessions are linked to ${d.distinct_benchmark_attempts.toLocaleString()} benchmark attempt${
          d.distinct_benchmark_attempts === 1 ? "" : "s"
        }; the other ${d.sessions_unlinked.toLocaleString()} are not linked to a benchmark attempt.`,
        cause: unlinkedCause(d.link_job),
        canLink: root.is_dir,
        rootLine,
      };
    case "outcomes-only": {
      const attempts = d.by_result.reduce((n, r) => n + r.attempts, 0);
      return {
        state,
        headline: `${attempts.toLocaleString()} attempt${attempts === 1 ? " has" : "s have"} an outcome, but no session is currently linked, so cost and duration stay unknown.`,
        cause: unlinkedCause(d.link_job),
        canLink: root.is_dir,
        rootLine,
      };
    }
    case "unset":
      return {
        state,
        headline:
          "Nothing is linked yet: no benchmark runs folder is set. Point Settings → Benchmarks at the folder the harness writes to, then press Link benchmark runs.",
        cause: "",
        canLink: false,
        rootLine: "",
      };
    case "not-a-dir":
      return {
        state,
        headline: `The benchmark runs folder in Settings is not a folder that exists: ${root.path}. Fix it there, then press Link benchmark runs.`,
        cause: "",
        canLink: false,
        rootLine: root.path,
      };
    case "unlinked":
      return {
        state,
        headline:
          "Nothing is linked yet. Press Link benchmark runs to store every attempt's outcome from the folder below and link the Claude Code runs whose records name a loaded session.",
        cause: "",
        canLink: true,
        rootLine: root.path,
      };
  }
}

// ── polling while the link step runs ──────────────────────────────────
//
// The server's job state is authoritative. `pending` is the response the
// page was holding when it pressed the button: useApi keeps that stale
// object while the next request is in flight, so its "idle" must not end
// polling; only a DIFFERENT response (the first one after the press) can
// settle it, and from then on the server state alone decides.

export function shouldPoll(
  pending: BenchmarkSummary | null,
  data: BenchmarkSummary | null,
): boolean {
  return pending !== null || data?.link_job.state === "running";
}

/** The scan finished since the last response: either the first fresh
 *  response after the press is already terminal (a fast scan the page
 *  never saw running), or the state went running → terminal. Exactly
 *  one of the two fires for a scan, so the caller refetches once. */
export function scanCompleted(
  pending: BenchmarkSummary | null,
  previousState: string | null,
  data: BenchmarkSummary | null,
): boolean {
  if (data === null) return false;
  const now = data.link_job.state;
  if (now === "running") return false;
  if (pending !== null && data !== pending) return true;
  return previousState === "running";
}

export function settleWatch(
  pending: BenchmarkSummary | null,
  data: BenchmarkSummary | null,
): BenchmarkSummary | null {
  return pending !== null && data !== null && data !== pending ? null : pending;
}

/** The link job as one line: "scanned 12 run records: linked 9…" while
 *  done, "linking… 4 s" while running, the reason when skipped/failed. */
export function linkJobLine(job: BenchmarkSummary["link_job"]): string {
  if (job.state === "running") return `linking… ${job.seconds ?? 0} s`;
  if (job.state === "failed")
    return `failed: ${job.message ?? "unknown error"}`;
  if (job.state === "done") return job.message ?? "done";
  return "";
}

// ── the link step's counters, by transaction state ────────────────────
//
// correlate.run commits ONCE at the end. While it runs, the counters
// count work PROCESSED, none of it persisted yet; after a failure the
// transaction rolled back and none of it ever was. Only a finished scan
// may be described as linked / stored.

export interface CorrelateCounters {
  scanned?: number;
  linked?: number;
  unmatched?: number;
  null_session_id?: number;
  scores_ingested?: number;
  skipped_run_records?: number;
}

export function correlateProgressLine(
  progress: CorrelateCounters,
  state: "idle" | "running" | "done" | "failed",
  seconds?: number,
): string {
  const n = (v: number | undefined) => (v ?? 0).toLocaleString();
  const detail = [
    progress.unmatched ? `${n(progress.unmatched)} named a session not loaded` : "",
    progress.null_session_id ? `${n(progress.null_session_id)} without a session id` : "",
    progress.skipped_run_records ? `${n(progress.skipped_run_records)} unreadable` : "",
  ].filter(Boolean);
  if (state === "done") {
    return [
      `${n(progress.scanned)} run records scanned`,
      `${n(progress.linked)} sessions linked`,
      `${n(progress.scores_ingested)} outcomes stored`,
      ...detail,
    ].join(" · ");
  }
  const processed = [
    `${n(progress.scanned)} records processed`,
    `${n(progress.linked)} session-link matches`,
    `${n(progress.scores_ingested)} outcomes processed`,
    ...detail,
  ];
  if (state === "failed") {
    return `${processed.join(" · ")} — rolled back: nothing from this scan was stored`;
  }
  return `${processed.join(" · ")} · commit pending${seconds ? ` · ${Math.round(seconds)}s` : ""}`;
}
