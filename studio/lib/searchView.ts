// The Search page's rules (#371 A2), kept out of the page so the states
// check can load them without Next's runtime.
import type { SearchHit, SearchResponse } from "@/lib/api";

/** Where a hit lives: the session page, scrolled to the turn. */
export function hitHref(h: SearchHit): string {
  return `/sessions/${h.session_ref}#turn-${h.sequence_num}`;
}

/** Search is deterministic ranked matching over archived turns, with no
 *  model call; Ask interprets the wider store through one. */
export const SEARCH_VS_ASK =
  "Search finds turns whose archived text matches your words, ranked, with no model involved. " +
  "Ask answers questions about the whole store through a model.";

export type SearchState =
  | { kind: "idle" }
  | { kind: "nothing-archived"; eligible: number }
  | { kind: "no-match"; archivedSessions: number; archivedTurns: number }
  | { kind: "hits"; count: number; archivedSessions: number };

/** What the page says, from the response: the coverage figures are what
 *  tell "no match" (there was something to search) from "nothing
 *  archived yet" (there was not). */
export function searchState(query: string, r: SearchResponse | null): SearchState {
  if (!query.trim() || !r) return { kind: "idle" };
  const c = r.coverage;
  if (c.archived_turns === 0) return { kind: "nothing-archived", eligible: c.eligible_sessions };
  if (r.results.length === 0)
    return { kind: "no-match", archivedSessions: c.archived_sessions, archivedTurns: c.archived_turns };
  return { kind: "hits", count: r.results.length, archivedSessions: c.archived_sessions };
}

export function stateLine(s: SearchState): string {
  switch (s.kind) {
    case "idle":
      return "";
    case "nothing-archived":
      return `Nothing is archived yet, so there is nothing to search: ${s.eligible} session${s.eligible === 1 ? "" : "s"} could be. Turn on trace_archive for a project in Settings and re-run Load sessions.`;
    case "no-match":
      return `No match in ${s.archivedTurns.toLocaleString()} archived turn${s.archivedTurns === 1 ? "" : "s"} across ${s.archivedSessions} session${s.archivedSessions === 1 ? "" : "s"}.`;
    case "hits":
      return `${s.count} match${s.count === 1 ? "" : "es"}, best first, across ${s.archivedSessions} archived session${s.archivedSessions === 1 ? "" : "s"}.`;
  }
}
