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
  /** Outcomes stored, but no run record named a session (older harness
   *  runs do not carry one), so nothing is linked. */
  | "outcomes-only"
  | "linked";

export interface BenchmarkIntro {
  state: BenchmarkState;
  /** One sentence on what is linked, or why nothing is. */
  headline: string;
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

export function benchmarkIntro(d: BenchmarkSummary): BenchmarkIntro {
  const state = benchmarkState(d);
  const root = d.runs_root;
  switch (state) {
    case "linked":
      return {
        state,
        headline: `${d.sessions_linked.toLocaleString()} of ${d.sessions_total.toLocaleString()} sessions came from ${d.distinct_benchmark_attempts.toLocaleString()} benchmark attempt${
          d.distinct_benchmark_attempts === 1 ? "" : "s"
        }; the other ${d.sessions_unlinked.toLocaleString()} are organic work.`,
        canLink: root.is_dir,
        rootLine: root.configured ? root.path : "",
      };
    case "outcomes-only": {
      const attempts = d.by_result.reduce((n, r) => n + r.attempts, 0);
      return {
        state,
        headline: `${attempts.toLocaleString()} attempt${attempts === 1 ? " has" : "s have"} an outcome, but none of their run records names a session, so no session is linked and cost and duration stay unknown. Runs from a harness version that records session ids will link on the next scan.`,
        canLink: root.is_dir,
        rootLine: root.configured ? root.path : "",
      };
    }
    case "unset":
      return {
        state,
        headline:
          "Nothing is linked yet: no benchmark runs folder is set. Point Settings → Benchmarks at the folder the harness writes to, then press Link benchmark runs.",
        canLink: false,
        rootLine: "",
      };
    case "not-a-dir":
      return {
        state,
        headline: `The benchmark runs folder in Settings is not a folder that exists: ${root.path}. Fix it there, then press Link benchmark runs.`,
        canLink: false,
        rootLine: root.path,
      };
    case "unlinked":
      return {
        state,
        headline:
          "Nothing is linked yet. Press Link benchmark runs to scan the folder below for run records and match them to your sessions.",
        canLink: true,
        rootLine: root.path,
      };
  }
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
