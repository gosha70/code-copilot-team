# Origin alignment check — sa-feedback

Checked 2026-09-23 18:10, after the owner's review of the bundle and
before any implementation. Supersedes the 17:35 record.

Origin: specs/sa-feedback/origin/2026-09-23-owner-direction.md (the
owner's messages, the green-field ruling, and the 2026-09-23 review
with its corrections) and issue #371, row A3.

Origin claim:
> A feedback record on a session, turn or tool call, with a name, a
> value, a rationale, a source (human, judge or code) and a supersedes
> pointer, plus a Studio control; a person can attach named free-text
> feedback to a turn and it is queryable; the rubric becomes one named
> set. Targets by sequence numbers, not row ids; the table lands in
> place, no recreation; supersession under four invariants; the source
> derived by the server's identity precedence; the vocabulary typed by
> the server; no list filter yet; one batched feedback query.

Working claim:
> spec.md FR-1..FR-8 and plan.md D1–D8: one table keyed by
> (session_ref, sequence_num, tool_sequence_num) with typed value
> columns, supersede-only history with the superseded row current, same
> target and name, superseded once (UNIQUE), the source resolved by
> derive_developer_id at request time, POST/GET routes, feedback folded
> from one query onto the detail payload and the MCP tool, an export
> table, a control on each turn card and the header, a vocabulary of
> the nine rubric names (boolean), rating (1–5) and note (text) with
> bounded custom names, human_label and the agreement statistic
> untouched, version 9 applied in place.

Each clause against the plan: session/turn/tool-call targets by
sequence — FR-1, D2; name, value, rationale, source, supersedes —
FR-1..FR-4, D1, D3, D4; invariants — FR-2, D3; server identity — FR-3,
D4; typing — FR-5, D5; Studio control on a turn — FR-6; queryable —
FR-3 (GET), FR-4 (payload, one query, D8), FR-7 (export); the rubric as
one named set — FR-5, D5; no list filter — D6; in-place version 9 —
D7; re-ingest survival and in-place stamping tested — FR-8.

Differences from the origin, surfaced in the bundle:

1. No judge is wired to write feedback (out of scope): the store
   function accepts a judge source, but changing a judge is its own
   change. The issue row lists judge as a source; the record supports
   it, no judge writes it yet.

Verdict: aligned
Confidence: high

High: every design decision now carries the owner's explicit ruling
(D1, D4, D5, D6 accepted; D2, D3, D7 corrected and adopted; D8 added
at their instruction).

Checked by re-reading store._delete_children, check_schema/apply_ddl,
the tool-call DDL and Studio row type, derive_developer_id and its one
caller, and the three judgement tables' DDL.
