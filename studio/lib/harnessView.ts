// The harness stamp on a session (#371 A4): how the header and the
// compare panel read the six columns. Kept out of the components so
// the states check can load it without Next's runtime.
import type { HarnessRow, SessionRow } from "@/lib/api";

/** The five facts and the mixed flag, as the API serves them. */
export type HarnessFields = Pick<
  SessionRow,
  | "cli_version"
  | "cct_version"
  | "cct_sha"
  | "instructions_digest"
  | "providers_digest"
  | "harness_mixed"
>;

/** Unstamped = no fact at all (no ledger line and no CLI version). */
export function isUnstamped(h: HarnessFields): boolean {
  return (
    h.cli_version == null &&
    h.cct_version == null &&
    h.cct_sha == null &&
    h.instructions_digest == null &&
    h.providers_digest == null
  );
}

/** A sha or digest shortened for display; the full value goes on hover. */
export function short(value: string | null | undefined, chars = 12): string {
  if (!value) return "—";
  return value.length > chars ? value.slice(0, chars) : value;
}

export interface HarnessFact {
  label: string;
  value: string;
  /** The full value when the shown one is shortened. */
  title?: string;
}

/** The facts a header lists, in order: release, commit, instructions,
 *  providers, CLI. An absent fact reads "—" rather than disappearing,
 *  so a partial stamp (a CLI version with no ledger line) is visible as
 *  partial. */
export function harnessFacts(h: HarnessFields): HarnessFact[] {
  return [
    { label: "CCT release", value: h.cct_version ?? "—" },
    { label: "CCT commit", value: short(h.cct_sha), title: h.cct_sha ?? undefined },
    {
      label: "Instructions",
      value: short(h.instructions_digest),
      title: h.instructions_digest ?? undefined,
    },
    {
      label: "Providers",
      value: short(h.providers_digest),
      title: h.providers_digest ?? undefined,
    },
    { label: "CLI", value: h.cli_version ?? "—" },
  ];
}

/** One line for the header's badge: what kind of stamp this is. MIXED
 *  FIRST, the same precedence the compare and the filter use — a session
 *  whose harness changed mid-run is mixed even when its earliest stamp
 *  carries no facts, and calling that "unstamped" would contradict the
 *  group it is counted in. */
export function harnessState(h: HarnessFields): "unstamped" | "mixed" | "stamped" {
  if (h.harness_mixed) return "mixed";
  return isUnstamped(h) ? "unstamped" : "stamped";
}

export const UNSTAMPED_NOTE =
  "No harness stamp: the session ran before harness-stamp.sh was installed, under a plugin-only install, or under a copilot without the hook.";
export const MIXED_NOTE =
  "The harness changed while this session ran (a resume under new instructions, or a CLI update); the earliest stamp is shown.";

// ── the compare (#371 A4b) ────────────────────────────────────────────

/** The named groups the compare reports beside real values. Kept in step
 *  with constants.HARNESS_GROUPS on the server. */
export const GROUP_MIXED = "mixed";
export const GROUP_UNSTAMPED = "unstamped";
export const GROUP_ABSENT = "absent";

const DIMENSION_LABELS: Record<string, string> = {
  instructions_digest: "Instructions",
  cct_sha: "CCT commit",
  cct_version: "CCT release",
  cli_version: "CLI version",
  providers_digest: "Providers",
};

export function dimensionLabel(dimension: string): string {
  return DIMENSION_LABELS[dimension] ?? dimension;
}

/** Everything below reads row.KIND, never the string in row.value: a
 *  cli_version may legitimately BE "mixed", and it must stay an ordinary
 *  value row that links to its own sessions. */
type Row = Pick<HarnessRow, "kind" | "value">;

/** A stable React key: two rows can share a value only across kinds. */
export function rowKey(row: Row): string {
  return `${row.kind}:${row.value ?? ""}`;
}

/** How a row is titled. A digest is shortened; a named group gets a
 *  sentence, because "mixed" alone reads as a value someone chose. */
export function rowLabel(row: Row, dimension: string): string {
  if (row.kind === GROUP_MIXED) return "changed mid-session";
  if (row.kind === GROUP_ABSENT) return `no ${dimensionLabel(dimension).toLowerCase()} recorded`;
  if (row.kind === GROUP_UNSTAMPED) return "no harness stamp";
  return short(row.value);
}

export function rowTitle(row: Row, dimension: string): string {
  if (row.kind === GROUP_MIXED) return MIXED_NOTE;
  if (row.kind === GROUP_ABSENT)
    return `These sessions carry a stamp, but not ${dimensionLabel(dimension)} — grouping them under "no harness stamp" would claim they carry none.`;
  if (row.kind === GROUP_UNSTAMPED) return UNSTAMPED_NOTE;
  return row.value ?? "";
}

/** The `harness` filter value that selects exactly this row's sessions,
 *  so every row of every dimension can link to them. */
export function rowFilter(row: Row, dimension: string): string {
  if (row.kind === GROUP_ABSENT) return `${GROUP_ABSENT}:${dimension}`;
  if (row.kind === GROUP_MIXED || row.kind === GROUP_UNSTAMPED) return row.kind;
  return `${dimension}:${row.value}`;
}

export function rowHref(row: Row, dimension: string): string {
  return `/sessions?harness=${encodeURIComponent(rowFilter(row, dimension))}`;
}

/** A judge figure, or the reason there is none. Never "0" for absent. */
export function judged(value: number | null, sessionsJudged: number, digits = 2): string {
  if (value == null || sessionsJudged === 0) return "—";
  return value.toFixed(digits);
}

/** What the panel says instead of a comparison when there is nothing to
 *  compare: the store has one harness version, or none recorded. */
export function compareState(
  rows: HarnessRow[],
  comparableValues: number,
): "empty" | "none-recorded" | "single" | "comparable" {
  if (rows.length === 0) return "empty";
  if (comparableValues === 0) return "none-recorded";
  if (comparableValues === 1) return "single";
  return "comparable";
}

export function stateLine(state: string, dimension: string): string {
  if (state === "empty") return "No sessions to compare yet.";
  if (state === "none-recorded")
    return `No session records ${dimensionLabel(dimension)} yet, so there is nothing to compare on it. Only sessions that started after the stamp hook was installed carry it — run setup.sh --sync if you have not, then compare once new sessions have run.`;
  if (state === "single")
    return `Every stamped session ran under one ${dimensionLabel(dimension)}. A comparison needs a second one — the figures below are this version's, not a difference.`;
  return "";
}


// ── expectations on a harness row (#371 A5) ───────────────────────────

/** What one row's Expectations cell shows. ONE column, not three: the
 *  rate is meaningless without the evidence behind it, so the counts
 *  ride with it rather than widening the table. */
export interface ExpectationCell {
  /** The SUCCESS rate — met/evaluated — as a percentage, or "—" when
   *  nothing was evaluated. Never "0%" for absent evidence, which would
   *  claim every expectation failed; and never "100%" unless every
   *  evaluated expectation was met. */
  primary: string;
  /** EVALUATION COVERAGE — evaluated out of every expectation the runs
   *  carried — plus what was not established. A different ratio from
   *  the percentage above, and deliberately so: "4/4 evaluated · 22
   *  unevaluated" contradicts itself, "4/26 evaluated · 22 unevaluated"
   *  does not. */
  secondary: string;
  /** Runs, distinct sessions and the full counts. */
  title: string;
}

/** met/evaluated as a percentage, preserving one invariant: 100% means
 *  EVERY evaluated expectation was met. Rounding alone would render
 *  999/1000 as "100%", so a rate below 1 is capped just under it. */
export function successPercent(rate: number): string {
  if (rate >= 1) return "100%";
  return `${Math.min(99, Math.round(rate * 100))}%`;
}

type ExpectationFields = Pick<
  HarnessRow,
  | "expectations_met"
  | "expectations_evaluated"
  | "expectations_unknown"
  | "expectations_unevaluated"
  | "runs_with_expectations"
  | "sessions_with_expectations"
  | "expectation_rate"
>;

export function expectationCell(row: ExpectationFields): ExpectationCell {
  const {
    expectations_met: met,
    expectations_evaluated: evaluated,
    expectations_unknown: unknown,
    expectations_unevaluated: unevaluated,
    runs_with_expectations: runs,
    sessions_with_expectations: sessions,
    expectation_rate: rate,
  } = row;
  const notEstablished: string[] = [];
  if (unevaluated > 0) notEstablished.push(`${unevaluated} unevaluated`);
  if (unknown > 0) notEstablished.push(`${unknown} unknown`);

  if (runs === 0) {
    return {
      primary: "—",
      secondary: "no runs",
      title: "No auto-build run is attributed to this harness version.",
    };
  }
  const primary = rate == null ? "—" : successPercent(rate);
  // COVERAGE, not the success ratio: how many of the expectations these
  // runs carried were actually evaluated at all.
  const carried = evaluated + unknown + unevaluated;
  const evaluatedPart = `${evaluated}/${carried} evaluated`;
  return {
    primary,
    secondary: [evaluatedPart, ...notEstablished].join(" · "),
    title:
      `${runs} run${runs === 1 ? "" : "s"}, ` +
      `${sessions} session${sessions === 1 ? "" : "s"}. ` +
      `${met} met, ${evaluated - met} not met, ${unknown} unknown, ` +
      `${unevaluated} unevaluated. The rate is met/evaluated; unknown and ` +
      `unevaluated are in neither side of it.`,
  };
}

/** The note under the table: runs that belong to no row at all. Shown
 *  only when there are any, and it says what each exclusion means —
 *  "unmatched" covers a session that was never ingested AND one that
 *  falls outside the list's current noise population. */
export function exclusionNote(
  spanning: number,
  unmatched: number,
): string | null {
  if (spanning === 0 && unmatched === 0) return null;
  const parts: string[] = [];
  if (spanning > 0)
    parts.push(
      `${spanning} run${spanning === 1 ? "" : "s"} spanned more than one harness version`,
    );
  if (unmatched > 0)
    parts.push(
      `${unmatched} run${unmatched === 1 ? "" : "s"} could not be placed (a session was never ingested, is outside the current noise population, or the run recorded none)`,
    );
  return `Not counted in any row: ${parts.join("; ")}.`;
}
