# Origin alignment check — sa-trace-tree

Checked 2026-09-22 13:00, before plan approval and before any implementation.

Origin: specs/sa-trace-tree/origin/2026-09-22-owner-direction.md (the
owner's messages in this session) and issue #371, row A1.

Origin claim:
> Show tool calls with results and durations under each turn, and nest
> subagent (sidechain) turns under their parent, as a view over rows the
> store already holds. No new dependency, no new store, no privacy
> change. One PR under #371.

Working claim:
> spec.md FR-1..FR-6 and plan.md: extend the existing session-detail
> payload (and so the MCP tool, additively) with tool calls, results,
> file accesses and sidechain nesting; render them in the Timeline with
> every existing behaviour kept; tests over the fixture plus synthetic
> rows; no schema, endpoint or dependency.

Differences from the origin, each surfaced in the bundle:

1. "Durations" per tool call are not delivered. The store has no
   per-call timestamp; delivering them means a migration and a
   re-ingest, which the issue's "no new store" constraint and the
   slice's view-only shape rule out. The slice keeps the per-turn
   latency the page already shows and proposes per-tool timing as a
   follow-up (plan D2). The owner has not ruled on this.
2. The payload is extended in place rather than served from a new
   endpoint (plan D1). The issue did not specify; this is a design
   choice put to the owner.
3. Orphan sidechain turns are shown at top level with a mark (plan D3);
   the issue did not address them.

Verdict: aligned
Confidence: medium

Medium, not high: difference 1 narrows the issue's wording and the owner
has not yet accepted it.

Checked by re-reading the owner's messages and the issue row, reading
the DDL for the four tables involved, get_session_details and its route,
the Timeline and its TurnRow type, the ingest adapter's sidechain
handling, the redaction of input_preview at write time, the fixture's
contents, and the two workflows that test the Python and Studio layers.
