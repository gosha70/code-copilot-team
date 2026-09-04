// Cluster view state classification + copy (#293 T2; FR-C, FR-D).
//
// WHY THIS IS A SEPARATE, JSX-FREE MODULE. FR-C requires three states
// to be genuinely distinguishable — prerequisite-missing, healthy-empty
// and populated — and the D8 script has to be able to prove that. Copy
// living inline in JSX can only be checked by eye; copy living here is
// assertable, and the mutual-exclusivity of the markers below is itself
// a test rather than an intention.
//
// THE MAPPING IS EXPLICIT, NEVER INFERRED FROM MESSAGE TEXT. The API
// answers a prerequisite with 503 and a {error, prerequisite, guidance}
// body; the classifier branches on that structure. Sniffing an error
// string for the word "absent" would reintroduce exactly the fragility
// the endpoint's typed body exists to remove.

export interface ClusterRow {
  identity: string;
  size: number;
  members: string[];
  directed_edge_count: number;
}

export interface ClusterReport {
  clusters: ClusterRow[];
  cluster_count: number;
  clustered_sessions: number;
  unclustered_sessions: number;
  graph_sessions: number;
  basis: string;
  membership_basis: string;
  inventory_basis: string;
  limitations: string[];
}

export interface PrerequisiteDetail {
  error: string;
  prerequisite: string;
  /** Which prerequisite state the SERVER determined it was in.
   *
   * The endpoint constructs its prerequisite at three distinct sites —
   * the pre-open existence check, the TOCTOU open failure, and the
   * unbuilt-store branch — and knows unambiguously which applies at
   * each. Carrying that as a field rather than only as prose is what
   * lets this client read it instead of re-deriving it from a substring
   * match on the error text.
   */
  state?: "absent" | "unopenable" | "unbuilt";
  guidance: string;
}

/** The three FR-C states, plus an honest failure that is none of them. */
export type ClustersState =
  | { kind: "populated"; report: ClusterReport }
  | { kind: "empty"; report: ClusterReport }
  // A prerequisite the server NAMED. `state` carries which one.
  | { kind: "prerequisite"; detail: PrerequisiteDetail; unbuilt: boolean }
  // A prerequisite the server did NOT name — an older server that
  // predates the `state` discriminator. Deliberately its own state, not
  // a default into one of the named ones: folding an unknown into a
  // known is the FR-C collapse this slice exists to prevent, and a
  // renderer that guesses "absent" would show a confident wrong remedy.
  | { kind: "prerequisiteUnnamed"; detail: PrerequisiteDetail }
  | { kind: "failed"; message: string };

/** Marker copy, one per state.
 *
 * Each string must appear in ITS state's render and in no other's —
 * asserted by the D8 script. A shared sentence between graph-absent and
 * graph-unbuilt would let the script pass while conflating precisely
 * the two states FR-C names, so the markers are deliberately disjoint
 * and machine-checked rather than assumed.
 */
export const COPY = {
  populatedMarker: "Clusters of mutually-reachable sessions",
  emptyMarker: "No clusters yet — this is a healthy result",
  absentMarker: "The graph database has not been created",
  unbuiltMarker: "The graph store exists but holds no sessions",
  failedMarker: "The clusters request did not complete",
  // The server reported a prerequisite but did not say which. Claim
  // nothing; show what it did send.
  unnamedMarker: "Clusters need a prerequisite that this server did not name",
  // FR-D: a bounded response says so. Never silently truncated.
  cap: (shown: number, total: number) =>
    `Showing ${shown} of ${total} clusters`,
} as const;

/** Every marker, for the mutual-exclusivity check. */
export const STATE_MARKERS: readonly string[] = [
  COPY.populatedMarker,
  COPY.emptyMarker,
  COPY.absentMarker,
  COPY.unbuiltMarker,
  COPY.unnamedMarker,
  COPY.failedMarker,
];

/** Recognises the unbuilt-store case.
 *
 * A FIELD READ, not a substring match. Both unbuilt and absent answer
 * `prerequisite: "graph"` — #289 FR-F forbids a new prerequisite
 * literal for a missing graph node, and that vocabulary is preserved —
 * but the endpoint additionally annotates WHICH state it determined,
 * so this client reads it rather than reconstructing it from prose.
 */
export function isUnbuilt(detail: PrerequisiteDetail): boolean {
  return detail.state === "unbuilt";
}

/** Classify an API outcome into exactly one state. */
export function classify(
  outcome:
    | { ok: true; report: ClusterReport }
    | {
        ok: false;
        status: number;
        detail?: PrerequisiteDetail;
        message: string;
      },
): ClustersState {
  if (outcome.ok) {
    return outcome.report.clusters.length === 0
      ? { kind: "empty", report: outcome.report }
      : { kind: "populated", report: outcome.report };
  }
  const detail = outcome.detail;
  if (detail && detail.prerequisite) {
    // TypeScript erases at runtime, so a required `state` field would
    // not make a missing one impossible — only unrepresentable in code
    // we control. The runtime check is what actually decides.
    if (detail.state === undefined) {
      return { kind: "prerequisiteUnnamed", detail };
    }
    return { kind: "prerequisite", detail, unbuilt: isUnbuilt(detail) };
  }
  return { kind: "failed", message: outcome.message };
}

/** FR-D: the cap notice, or null when nothing was truncated. */
export function capNotice(report: ClusterReport): string | null {
  const shown = report.clusters.length;
  return shown < report.cluster_count
    ? COPY.cap(shown, report.cluster_count)
    : null;
}
