// Session lineage on the session page (#371 A6): the rules the panel
// renders by, kept out of the component so the states check can load
// them without Next's runtime.
//
// THE SHAPE IS A TREE, AND THAT IS LOAD-BEARING. Once forks are
// retained, "the members in order" is a promise the data cannot keep —
// the order is partial. A flat list with a fork flag beside it invites
// exactly the reading the flag denies, so the server sends roots with
// nested children and this file never flattens them.
//
// AND AN EMPTY ANSWER IS NOT A FINDING. Three fields decide what the
// panel says, in this order: whether the source can express lineage at
// all, whether its known sources were actually assessed, and only then
// whether an ancestor was found.

export type LineageSupport = "native" | "unsupported";
export type Assessment = "complete" | "unassessed" | "incomplete";

export interface LineageMember {
  member_ref: number;
  source_key: string;
  native_session_id: string;
  session_ref: number | null;
  source_available: boolean;
  turn_uuid_count: number;
  is_root: boolean;
  is_terminal: boolean;
  join_suspected: boolean;
  children: LineageMember[];
}

export interface LineageEdge {
  ancestor: number;
  descendant: number;
  provenance: "native_group" | "uuid_containment";
  shared_uuids: number;
  ancestor_containment: number;
  descendant_containment: number;
  ancestor_only: number;
  descendant_only: number;
  rule_version: string;
}

export interface RelationCandidate {
  member_a: number;
  member_b: number;
  shared_uuids: number;
  a_only: number;
  b_only: number;
  candidate_kind: "duplicate_identity" | "direction_ambiguous";
  rule_version: string;
}

export interface LineageThread {
  thread_id: string | null;
  fork_suspected: boolean;
  terminal_ambiguous: boolean;
  root_ambiguous: boolean;
  member_count: number;
  roots: LineageMember[];
  edges: LineageEdge[];
  joins: { member_ref: number; ancestors: number[] }[];
}

export interface LineageView {
  session_ref: number;
  copilot: string;
  lineage_support: LineageSupport;
  assessment: Assessment;
  no_ancestor_found: boolean;
  ambiguous: boolean;
  thread_refs: number[];
  sources_known: number;
  sources_assessed: number;
  sources_available: number;
  sources_unavailable: number;
  relation_candidates: RelationCandidate[];
  thread: LineageThread | null;
}

/** The panel's mutually exclusive states. */
export type LineageState =
  | "unsupported"
  | "unassessed"
  | "incomplete"
  | "no-ancestor"
  | "ambiguous"
  | "thread";

export function lineageState(view: LineageView): LineageState {
  // Support first: an aider session has no lineage to look for, so
  // nothing below it is even a question.
  if (view.lineage_support === "unsupported") return "unsupported";
  if (view.ambiguous) return "ambiguous";
  if (view.thread) return "thread";
  // No thread — but only `complete` has earned the word "none".
  if (view.assessment === "unassessed") return "unassessed";
  if (view.assessment === "incomplete") return "incomplete";
  return "no-ancestor";
}

/** One sentence per state. Each must be DISTINGUISHING: the states
 *  check asserts no marker appears in another state's render, so two
 *  states sharing a phrase would let it conflate them silently. */
export function lineageMessage(view: LineageView): string {
  switch (lineageState(view)) {
    case "unsupported":
      return `${view.copilot} transcripts carry no per-turn identifier, so lineage cannot be determined for this source.`;
    case "unassessed":
      return `Lineage has not been assessed yet: ${view.sources_assessed} of ${view.sources_known} known sources were examined. Run \`session-analytics threads --backfill\`.`;
    case "incomplete":
      return `Lineage is incomplete: ${view.sources_unavailable} of ${view.sources_known} known sources could not be read, so an absence cannot be confirmed.`;
    case "no-ancestor":
      return `No ancestor found. All ${view.sources_known} known sources were read and assessed.`;
    case "ambiguous":
      return `This session's sources belong to ${view.thread_refs.length} separate threads; no single lineage can be shown.`;
    case "thread":
      return `Resumed lineage across ${view.thread?.member_count ?? 0} transcripts.`;
  }
}

/** Coverage as the fraction FR-13 requires, never a bare label. */
export function coverageLabel(view: LineageView): string {
  return `${view.sources_assessed}/${view.sources_known} known sources assessed, ${view.sources_available} readable`;
}

/** Flattened ONLY for rendering indentation — depth, never an index.
 *  Siblings come back at the same depth with nothing ordering them. */
export function walk(
  members: LineageMember[],
  depth = 0,
): { member: LineageMember; depth: number }[] {
  const out: { member: LineageMember; depth: number }[] = [];
  for (const member of members) {
    out.push({ member, depth });
    out.push(...walk(member.children, depth + 1));
  }
  return out;
}

export function edgeInto(
  thread: LineageThread,
  member_ref: number,
): LineageEdge | null {
  return thread.edges.find((e) => e.descendant === member_ref) ?? null;
}

/** What an edge proves, in the words the model uses: how the pair was
 *  FOUND, and the counts that decided which way it runs. */
export function edgeEvidence(edge: LineageEdge): string {
  const how =
    edge.provenance === "native_group"
      ? "same session group"
      : "shared turn ids";
  return `${how}: ${edge.shared_uuids} shared, ${edge.descendant_only} added, ${edge.ancestor_only} dropped`;
}

export function candidateNote(candidate: RelationCandidate): string {
  return candidate.candidate_kind === "duplicate_identity"
    ? "identical turn ids — the same conversation under two identities"
    : "neither grew, so which came first cannot be determined; this is not a suggestion to merge them";
}

/** A source file's last segment, for a label that fits. */
export function sourceLabel(member: LineageMember): string {
  const parts = member.source_key.split("/");
  return parts[parts.length - 1] || member.source_key;
}
