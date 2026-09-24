# Origin alignment check — sa-feedback

Checked 2026-09-23 19:35, after the build and before review. Supersedes
the 18:10 record; the origin and the claims are unchanged from it, this
record confirms the built artifact against them.

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

Working claim (as built):
> 010_feedback.sql keyed by (session_ref, sequence_num,
> tool_sequence_num) with three typed value columns, a CHECK, UNIQUE
> (supersedes); _SCHEMA_VERSION 9 applied in place (a scratch copy of
> the owner's schema-8 store gained the table and was stamped 9 with
> its 158 sessions intact); feedback.py: add_feedback with typing per
> name (bool before int), target existence, the four supersession
> invariants; current_feedback as one self-LEFT-JOIN query, folded onto
> the detail payload (_attach_feedback); POST/GET
> /api/sessions/{id}/feedback with source_id from derive_developer_id
> at request time and a spoofed body ignored; GET /api/feedback/
> vocabulary serving the one list; the feedback export table;
> FeedbackControl on the header, every turn card and every tool call in
> the trace tree; feedback survives re-ingest (test and a live
> re-ingest of a real session).

Each clause against the artifact: session/turn/tool-call targets by
sequence — 010_feedback.sql, feedback._check_target; name, value,
rationale, source, supersedes — feedback.add_feedback; invariants —
feedback._check_supersedes + UNIQUE; server identity —
server._current_developer; typing — feedback.coerce_value; Studio
control on a turn — FeedbackControl in page.tsx; queryable — GET route,
detail payload, export.iter_feedback; the rubric as one named set —
constants.FEEDBACK_VOCABULARY over LABEL_BOOL_NAMES; no list filter —
nothing added to _session_filters; in-place version 9 —
db._SCHEMA_VERSION, TestSchemaBump.

One addition beyond the plan, recorded here: GET /api/feedback/vocabulary,
so the Studio reads the vocabulary from the server's one list instead
of carrying a copy (the constants rule). One fixed test:
test_db_dialect's "fresh store is stamped current" now reads the
module's version instead of the literal 8.

Differences from the origin: no judge is wired to write feedback (out
of scope, as before).

Verdict: aligned
Confidence: high
