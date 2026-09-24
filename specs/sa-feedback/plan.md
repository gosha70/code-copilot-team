---
spec_mode: lightweight
feature_id: sa-feedback
risk_category: data
justification: |
  One new table with a version bump, one store function, two routes,
  an export table, a Studio control, tests. The green-field ruling makes
  the schema change ordinary. FR-1..FR-8 in spec.md state the behaviour.
status: approved
date: 2026-09-23
issue: "#371"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-feedback/origin/2026-09-23-owner-direction.md
  user_messages:
    - "2026-09-22: 'I would rather work on extending capabilities of Session Analysis rather using ML Flow'"
    - "2026-09-22: 'Can you start planing the addressing the features listed in issues/371?'"
  origin_claim: |
    Slice A3 of #371: a feedback record on a session, turn or tool call,
    with a name, a value, a rationale, a source (human, judge or code)
    and a supersedes pointer, plus a Studio control, so a person can
    attach named free-text feedback to a turn and it is queryable. The
    rubric becomes one named set. Schema change allowed; a new table
    lands in place through the create-if-absent DDL, no recreation.
---

# Plan: feedback (A3)

## The shape of it

```
scripts/session_analytics/config_data/ddl/postgres/010_feedback.sql   the table
scripts/session_analytics/relational/db.py                            _SCHEMA_VERSION 9; the DDL list
scripts/session_analytics/constants.py                                TBL_FEEDBACK, FEEDBACK_SOURCE_*, FEEDBACK_VOCABULARY, EXPORT_TABLE_FEEDBACK
scripts/session_analytics/feedback.py                                 add_feedback(db, ...) with typing + supersession checks, list_feedback(db, session_id), current_feedback(db, session_id) (one query)
scripts/session_analytics/api/server.py                               POST/GET /api/sessions/{id}/feedback, GET /api/feedback/vocabulary; source_id from derive_developer_id at request time
scripts/session_analytics/mcp/tools.py                                get_session_details: feedback folded onto session, turns, tool calls from current_feedback
scripts/session_analytics/export.py                                   the feedback export table
studio/lib/api.ts                                                     Feedback types; addFeedback, sessionFeedback
studio/lib/feedbackView.ts                                            current-vs-superseded, value rendering, vocabulary rules (for states-check)
studio/components/FeedbackControl.tsx                                 the control + the list under a target
studio/app/sessions/[id]/page.tsx                                     the control on each turn card and on the header
studio/components/JudgeQuality.tsx                                    the note points at the session page for turn feedback
studio/scripts/states-check.mjs                                       feedbackView + FeedbackControl states
scripts/session_analytics/tests/test_feedback.py, test_api.py        store, API, payload, export
scripts/session_analytics/README.md                                   one section
```

## Decisions

**D1 — one table, three value columns.** `value_bool`, `value_num`,
`value_text`, exactly one set per row (a CHECK). Typed columns keep
booleans and numbers queryable and comparable (A4 will average ratings
and count booleans by version); a single JSON text column would not.
Recommended over MLflow's untyped `value`.

**D2 — three target levels in one row shape, keyed by sequence
numbers.** `(session_ref, sequence_num?, tool_sequence_num?)`: session
`(NULL, NULL)`, turn `(seq, NULL)`, tool call `(seq, tseq)`. One table,
one read path, one control. No FK to `copilot_turn` or
`copilot_tool_call`: re-ingest deletes and reinserts both with fresh
ids (`store._delete_children`), so an id would go stale and an id FK
would make re-ingest of any session with feedback fail. `human_label`
and `trace_document` anchor the same way, and the Studio already
addresses tool calls by `sequence_num`. Owner's correction, 2026-09-23.

**D3 — supersede, never edit or delete, under four invariants.** The
replaced row stays and the new one names it; "current" is computed,
not stored (rows not named by any `supersedes`). The store checks that
the superseded row is in the same session, is current, and has the
same target and `name`; the table adds `UNIQUE (supersedes)` so a row
cannot be superseded twice even by a racing writer. Any source may
correct any source (a person correcting a judge is the point). History
is what makes a judge's feedback comparable with the person's later
correction (A4/A5). Owner's addition, 2026-09-23.

**D4 — the source is the server's.** The API server resolves no
identity today; the route calls `derive_developer_id` with the same
inputs the CLI hands it (the loader's env/.env value, the config value,
then git global email, then `local`) at request time, and stores that
as `source_id` with `source_type = human`. Neither field is read from
the body, a header, or the session's own `developer_id`; a body that
carries them is ignored and a test proves it. Judge and code sources
write through the same store function and name themselves; no judge is
wired in this slice.

**D5 — an offered vocabulary, typed by the server; a custom name
allowed.** One list in `constants` maps each offered name to its type:
the nine rubric booleans → boolean, `rating` → integer 1–5, `note` →
non-blank text. A name outside the list is a custom name: non-blank,
≤ 80 characters, with a value of any one supported type (non-blank,
bounded text). The check tests `bool` before `int`/`float`, since a
Python `bool` is an `int`. The rubric "becomes one named set" by being
those nine names; `human_label` is not migrated and the agreement
statistic keeps reading it.

**D6 — no feedback filter in A2's list yet.** GET, the detail payload
and the export make feedback queryable; list filtering waits for A4 to
define the current/source semantics.

**D7 — version 9, applied in place; no recreation.** This slice adds a
table, not a column: the create-if-absent DDL run lands it on a
schema-8 store and stamps 9, exactly as versions 5–7 landed. The A1
refusal (`_REQUIRED_COLUMNS`) does not fire for a missing table and
nothing is added to make it fire. The owner's live store is not
rebuilt. Owner's correction, 2026-09-23.

**D8 — one query for the detail payload.** The session's current
feedback rows come from one query (a self-LEFT-JOIN on `supersedes` to
exclude superseded rows), then are folded onto the session, its turns
and their tool calls in Python by `(sequence_num, tool_sequence_num)`.
No per-turn or per-tool query.

## Verification

- `unittest`: `test_feedback.py` (store: each value type, the CHECK,
  typing per name incl. bool-before-int, supersede chain,
  current-vs-history, supersession refused for wrong target / wrong
  name / non-current row / second supersession of one row, targets
  incl. a tool call, missing targets, feedback at all three levels
  surviving a re-ingest of its session, a schema-8 store gaining the
  table in place and stamped 9), `test_api.py` (write/read, source from
  the server with a spoofed body ignored, 400s, additivity of the
  detail payload and its single feedback query), export of the new
  table; the A1 refusal test still passes with the version now 9.
- `states-check`: `feedbackView` (current filtering, value rendering per
  name, vocabulary rules) and `FeedbackControl` (empty, rows, superseded
  rows, a judge's row, the replace affordance).
- `tsc --noEmit`, `next build`.
- A scratch store on other ports (the A1/A2 method): add feedback to a
  turn, a tool call and the session in the browser, replace one, see
  history; export it; re-ingest the session and see the feedback still
  attached. The owner's instance is never restarted and their store is
  not rebuilt; it gains the table on its next `apply_ddl`.
- `validate-spec.sh --all`, `check-origin-alignment.sh sa-feedback`,
  `check-doc-accuracy.sh`, `git diff --check`, then `/review-submit`.

## Risks

- **A tool-call target is only as stable as the adapter's tool
  `sequence_num`.** Turn and tool sequence numbers are the adapter's
  own ordering and re-ingest reproduces them from the same transcript;
  a future adapter change to that ordering would move feedback, as it
  would move `human_label`. Accepted; the re-ingest test pins today's
  behaviour.
- **Free-text feedback is unredacted by design**: a person's own words.
  The README says it, and the export carries it. If the store is shared
  (Postgres), that is visible to the team; stated, not hidden.
- **Prettier churn on `.tsx`**: diffs checked after every edit.
