// The harness stamp on a session (#371 A4): how the header and, later,
// the compare panel read the six columns. Kept out of the components so
// the states check can load it without Next's runtime.
import type { SessionRow } from "@/lib/api";

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

/** One line for the header's badge: what kind of stamp this is. */
export function harnessState(h: HarnessFields): "unstamped" | "mixed" | "stamped" {
  if (isUnstamped(h)) return "unstamped";
  return h.harness_mixed ? "mixed" : "stamped";
}

export const UNSTAMPED_NOTE =
  "No harness stamp: the session ran before harness-stamp.sh was installed, under a plugin-only install, or under a copilot without the hook.";
export const MIXED_NOTE =
  "The harness changed while this session ran (a resume under new instructions, or a CLI update); the earliest stamp is shown.";
