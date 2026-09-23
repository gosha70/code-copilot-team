// The Timeline's nesting rule (#371 A1), kept out of the page so the
// states check can load it without Next's runtime.
import type { TurnRow } from "@/lib/api";

// Subagent (sidechain) turns sit under the turn that spawned them; every
// other turn, and a sidechain turn whose parent is not in this session,
// stays at the top level in transcript order. Numbering is untouched, so
// #turn-N links keep working.
export function nestTurns(
  turns: TurnRow[],
): { turn: TurnRow; children: TurnRow[] }[] {
  // A subagent run is several turns, each pointing at the one before it
  // (main → A → B → …). All of them belong under the main-thread turn
  // that started the run, so each sidechain turn is walked up its parent
  // chain to the first turn that is not a sidechain, and listed there in
  // transcript order. A chain that never reaches such a turn (its root is
  // not in this session) stays at the top level, marked by the card.
  const bySeq = new Map(turns.map((t) => [t.sequence_num, t]));
  const childrenOf = new Map<number, TurnRow[]>();
  const top: TurnRow[] = [];
  for (const t of turns) {
    let anchor: TurnRow | null = null;
    if (t.is_sidechain) {
      const seen = new Set<number>([t.sequence_num]);
      let cur: TurnRow | undefined = t;
      while (cur && cur.is_sidechain) {
        const p: number | null = cur.parent_sequence;
        cur = p != null && !seen.has(p) ? bySeq.get(p) : undefined;
        if (cur) seen.add(cur.sequence_num);
      }
      anchor = cur ?? null;
    }
    if (anchor) {
      const list = childrenOf.get(anchor.sequence_num) ?? [];
      list.push(t);
      childrenOf.set(anchor.sequence_num, list);
    } else {
      top.push(t);
    }
  }
  return top.map((turn) => ({
    turn,
    children: childrenOf.get(turn.sequence_num) ?? [],
  }));
}
