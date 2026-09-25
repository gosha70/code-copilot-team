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
