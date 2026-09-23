# Origin alignment check — sa-trace-tree

Checked 2026-09-22 13:44, before plan approval and before any implementation.
Supersedes the 13:00 record: the owner has since ruled that Session
Analytics is unreleased and green-field, so backward compatibility and
data migration are not concerns. The one difference that held the
earlier record at medium is resolved by that ruling.

Origin: specs/sa-trace-tree/origin/2026-09-22-owner-direction.md (the
owner's messages in this session, including the green-field ruling) and
issue #371, row A1.

Origin claim:
> Show tool calls with results and durations under each turn, and nest
> subagent (sidechain) turns under their parent, as a view over rows the
> store already holds. No new dependency, no new store, no privacy
> change. One PR under #371. Schema changes are acceptable; an existing
> store is recreated rather than migrated.

Working claim:
> spec.md FR-1..FR-6 and plan.md: one column (copilot_tool_result.
> completed_at, filled at ingest) and a schema-version bump; the existing
> session-detail payload (and so the MCP tool, additively) gains tool
> calls with results, durations, file accesses and sidechain nesting;
> the Timeline renders them with every existing behaviour kept; tests
> over the fixture plus synthetic rows; no endpoint, no dependency.

Each clause of the origin against the plan:

1. "Tool calls with results and durations": FR-1, FR-1a. Durations are
   wall time until the result record, labelled as such, because calls
   issued in one turn share a start.
2. "Subagent runs nested": FR-2, FR-4; orphans shown and marked (D3).
3. "A view over rows the store already holds": true for everything but
   the one timestamp, which the owner's ruling admits.
4. "No new dependency, no new store, no privacy change": none of the
   three; input previews are served as redacted at ingest, bodies are
   not stored.
5. "Recreated rather than migrated": FR-1b and the README note; the
   owner's own store is recreated only on their word (plan D2, risks).

Differences from the origin: none of substance. D1 (extend the payload
rather than add an endpoint) and D3 (orphans) are design choices the
issue did not address, both put to the owner.

Verdict: aligned
Confidence: high

Checked by re-reading the owner's messages and the issue row, the DDL
for the four tables and the schema-version rule in relational/db.py,
_collect_tool_results in the adapter, the fixture's record timestamps,
get_session_details and its route, the Timeline and its TurnRow type,
and the two workflows that test the Python and Studio layers.

Re-checked after the owner's plan review returned one blocker and two
correctness requirements, all three verified in the code and folded in:
(1) `apply_ddl` would have stamped an old store as version 8 while the
column was missing, so the promised "degrade" was impossible; the slice
now refuses a pre-8 store with the remedy and records nothing (FR-1b),
and verification uses a scratch store until the owner authorizes
recreating theirs. (2) A tool call whose result never arrived has no
result row; the query is a LEFT JOIN and such calls are returned with
null fields (FR-1c). (3) Durations follow the page's existing latency
rule, `null` for missing, malformed or backward timestamps (FR-1a). None
changes what the origin asks for; each makes the slice deliver it
without a false promise. Verdict and confidence unchanged.

Re-checked after the owner's build review returned three findings, all
verified in the code and fixed: (1) create_app caught every exception
from apply_ddl, so a pre-8 store was logged as "unreachable" and the API
then failed on its first query; SchemaMismatch now escapes create_app and
the CLI dispatcher (and ingest's own handler) turns it into the remedy
message and EXIT_RUNTIME, tested through create_app and `ingest`.
(2) nestTurns returned children only for top-level turns, so a multi-turn
subagent run lost every turn after the first; each sidechain turn is now
walked up to its top-level ancestor and listed there, with chain and
cycle cases in states-check. (3) D4 promised one extra query; the trace
is now one LEFT-JOINed query over calls, results and file accesses, with
the parent link taken from the turns query the page already ran.
Payload unchanged (3.4 MB, 53 ms on the largest session). Verdict and
confidence unchanged.

Re-checked once more after the follow-up review: fourteen other CLI
handlers had their own catch-all and would have printed a traceback
before main() could speak; each now lets SchemaMismatch through, the
exception is imported once at module level, and the test drives `kpis`
(a handler with a local catch-all) as well as `ingest`. Every command
that runs apply_ddl was probed against a version-7 store: exit 3, the
remedy, no traceback. Verdict and confidence unchanged.
