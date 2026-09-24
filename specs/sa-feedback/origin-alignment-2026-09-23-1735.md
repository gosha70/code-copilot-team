# Origin alignment check — sa-feedback

Checked 2026-09-23 17:35, before plan approval and before any implementation.

Origin: specs/sa-feedback/origin/2026-09-23-owner-direction.md (the
owner's messages, including the green-field ruling) and issue #371,
row A3.

Origin claim:
> A feedback record on a session, turn or tool call, with a name, a
> value, a rationale, a source (human, judge or code) and a supersedes
> pointer, plus a Studio control; a person can attach named free-text
> feedback to a turn and it is queryable; the rubric becomes one named
> set. Schema changes allowed; recreate, not migrate.

Working claim:
> spec.md FR-1..FR-8 and plan.md D1–D7: one table with typed value
> columns and three target levels, supersede-only history, the source
> set by the server, POST/GET routes, feedback in the detail payload and
> the MCP tool, an export table, a control on each turn card and the
> header, a vocabulary of the nine rubric names plus rating and note,
> human_label and the agreement statistic untouched, version 9.

Each clause against the plan: session/turn/tool-call targets — FR-1,
D2; name, value, rationale, source, supersedes — FR-1..FR-4, D1, D3, D4;
Studio control on a turn — FR-6; queryable — FR-3 (GET), FR-4 (payload),
FR-7 (export); the rubric as one named set — FR-5, D5; schema change
under the ruling — D7.

Differences from the origin, surfaced in the bundle:

1. No feedback filter on the sessions list (D6): the issue row does not
   ask for one and A4 needs the semantics; deferred with the reason.
2. No judge is wired to write feedback (out of scope): the store
   function accepts a judge source, but changing a judge is its own
   change.
3. Typed value columns rather than a single value (D1): a design choice
   the issue did not address, made for A4.

Verdict: aligned
Confidence: medium

Medium, not high: D1, D5 and D6 are design choices the owner has not
ruled on yet.

Checked by reading the three judgement tables' DDL, the human-label
import and agreement code, the session-flag route, the schema-version
rule and the A1 refusal, identity derivation, the export table set, and
the session page's turn card.
