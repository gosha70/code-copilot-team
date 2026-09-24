// Feedback on the session page (#371 A3): the rules the control renders
// by, kept out of the component so the states check can load them
// without Next's runtime. The typing rule itself lives on the server
// (constants.FEEDBACK_VOCABULARY, feedback.coerce_value); this file only
// shapes a draft to send and a row to show.
import type { FeedbackRow } from "@/lib/api";

export type FeedbackType = "bool" | "num" | "text";

/** One offered name and the type it takes, as the server lists them. */
export interface VocabularyEntry {
  name: string;
  type: FeedbackType;
  min?: number;
  max?: number;
}

/** The option the name picker uses for a name outside the vocabulary. */
export const CUSTOM_NAME = "__custom__";

export function typeFor(
  vocabulary: VocabularyEntry[],
  name: string,
): VocabularyEntry | null {
  return vocabulary.find((v) => v.name === name) ?? null;
}

/** The key the page files rows under: one per target. */
export function targetKey(
  seq: number | null | undefined,
  tseq: number | null | undefined,
): string {
  if (seq == null) return "session";
  return tseq == null ? `turn:${seq}` : `call:${seq}:${tseq}`;
}

export function targetLabel(
  seq: number | null | undefined,
  tseq: number | null | undefined,
): string {
  if (seq == null) return "this session";
  return tseq == null ? `turn #${seq}` : `turn #${seq}, call ${tseq}`;
}

/** The current rows after one write: the row it superseded leaves, the
 *  new one joins at the end. */
export function applyWrite(rows: FeedbackRow[], written: FeedbackRow): FeedbackRow[] {
  return [...rows.filter((r) => r.id !== written.supersedes), written];
}

export function formatValue(row: Pick<FeedbackRow, "value">): string {
  if (typeof row.value === "boolean") return row.value ? "yes" : "no";
  return String(row.value);
}

/** Who said it: a person by developer id, a judge or a script by name. */
export function sourceLabel(row: Pick<FeedbackRow, "source_type" | "source_id">): string {
  if (row.source_type === "human") return row.source_id;
  return `${row.source_type} ${row.source_id}`;
}

/** Turn what the form holds into the value to send, or say why not.
 *  A custom name takes the type the person picked for it. */
export function draftValue(
  type: FeedbackType,
  raw: string,
  entry: VocabularyEntry | null,
): { value: boolean | number | string } | { error: string } {
  if (type === "bool") {
    if (raw === "true") return { value: true };
    if (raw === "false") return { value: false };
    return { error: "choose yes or no" };
  }
  if (type === "num") {
    const n = Number(raw.trim());
    if (raw.trim() === "" || !Number.isFinite(n)) return { error: "enter a number" };
    if (entry && entry.min != null && entry.max != null) {
      if (!Number.isInteger(n) || n < entry.min || n > entry.max)
        return { error: `an integer from ${entry.min} to ${entry.max}` };
    }
    return { value: n };
  }
  const text = raw.trim();
  if (!text) return { error: "write something" };
  return { value: text };
}
