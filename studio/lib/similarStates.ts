// Similar-panel state classification + copy (#293 T3; FR-C, FR-E).
//
// Mirrors clusterStates.ts: JSX-free so the D8 script can assert the
// copy, and the markers must be mutually exclusive for the same reason
// — a shared sentence between two states would let every per-state
// assertion pass while the two were conflated.
//
// The classification needs NO text matching. The states FR-C names here
// are structurally distinct at the transport: a healthy session with no
// stored neighbours is a 200 with an empty list, while a session absent
// from the graph is a 503 carrying a prerequisite.

import type { ApiOutcome, SimilarResponse } from "./api";

export interface SimilarPrerequisite {
  error: string;
  prerequisite: string;
  guidance: string;
}

export type SimilarOutcome =
  | { kind: "neighbours"; response: SimilarResponse }
  | { kind: "none"; response: SimilarResponse }
  | { kind: "prerequisite"; detail: SimilarPrerequisite }
  | { kind: "failed"; message: string };

/** One marker per state; asserted mutually exclusive by the D8 script. */
export const SIMILAR_COPY = {
  neighbours: "Sessions whose stored embedding neighbours this one",
  none: "No stored neighbours for this session yet",
  prerequisite: "Similar sessions cannot be computed yet",
  failed: "The similar-sessions request did not complete",
  // FR-E: neighbours are a producer snapshot, never an all-pairs claim.
  notPairwise:
    "Neighbours are recorded pairwise scores from the last similar pass; " +
    "they do not assert that these sessions are similar to each other.",
} as const;

export const SIMILAR_MARKERS: readonly string[] = [
  SIMILAR_COPY.neighbours,
  SIMILAR_COPY.none,
  SIMILAR_COPY.prerequisite,
  SIMILAR_COPY.failed,
];

export function classifySimilar(
  outcome: ApiOutcome<SimilarResponse>,
): SimilarOutcome {
  if (outcome.ok) {
    return outcome.report.neighbors.length === 0
      ? { kind: "none", response: outcome.report }
      : { kind: "neighbours", response: outcome.report };
  }
  const detail = outcome.detail;
  if (detail && detail.prerequisite) {
    return { kind: "prerequisite", detail };
  }
  return { kind: "failed", message: outcome.message };
}
