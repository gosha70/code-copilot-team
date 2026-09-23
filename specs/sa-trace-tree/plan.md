---
spec_mode: lightweight
feature_id: sa-trace-tree
risk_category: ui
justification: |
  A view over rows the store already holds, plus one timestamp column
  so durations can be shown: one query joined into an existing payload,
  one Studio component, tests. No dependency, no endpoint; the store is
  recreated rather than migrated by the owner's ruling. FR-1..FR-6 in
  spec.md state the behaviour.
status: approved
date: 2026-09-22
issue: "#371"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-trace-tree/origin/2026-09-22-owner-direction.md
  user_messages:
    - "2026-09-22: 'I would rather work on extending capabilities of Session Analysis rather using ML Flow'"
    - "2026-09-22: 'Can you start planing the addressing the features listed in issues/371?'"
  origin_claim: |
    Slice A1 of #371: show tool calls with their results, and subagent
    runs nested, under each turn on the session page, as a view over the
    rows ingest already stores. No new dependency, store or privacy
    change to the privacy rules. Session Analytics is unreleased, so a
    schema change with a recreated store is acceptable; the slice
    delivers the per-tool durations the issue names.
---

# Plan: the trace tree (A1)

## The shape of it

```
scripts/session_analytics/config_data/ddl/postgres/001_core.sql
                                             copilot_tool_result.completed_at TEXT
scripts/session_analytics/relational/db.py   _SCHEMA_VERSION 7 → 8, with the comment line the file keeps per version
scripts/session_analytics/contracts.py       RawToolCall gains result_timestamp
scripts/session_analytics/adapters/claude_code.py
                                             _collect_tool_results keeps the record's timestamp
scripts/session_analytics/relational/store.py
                                             writes completed_at
scripts/session_analytics/mcp/tools.py      get_session_details: one extra query per session
                                             (tool calls ⋈ results ⋈ file accesses), folded into
                                             turns; uuid→sequence map for parent_sequence;
                                             duration_seconds from completed_at − turn timestamp
studio/lib/api.ts                            TurnRow gains tool_calls, is_sidechain, parent_sequence
studio/components/TraceTree.tsx              new: the collapsible calls list under a turn
studio/app/sessions/[id]/page.tsx            Timeline nests sidechain turns; mounts TraceTree
studio/scripts/states-check.mjs              TraceTree added with its states
scripts/session_analytics/tests/test_mcp_tools.py   payload assertions over the fixture + synthetic rows
scripts/session_analytics/README.md          one paragraph
```

## Decisions

**D1 — extend the one payload.** `GET /api/sessions/{id}` already carries
the turns the page renders; tool calls belong on those turns. The MCP
tool grows the same way, additively. A separate `/trace` route would be
a second round trip and a second shape to keep in step. Revisit only if
a session's payload proves too large, which the `output_length` and
preview fields, rather than bodies, make unlikely.

**D2 — one timestamp column, durations at serve time.** The transcript
timestamps every record, and a tool's result arrives in a later record
than its call. Storing that record's timestamp as
`copilot_tool_result.completed_at` is the smallest change that makes a
duration computable: `completed_at − turn.timestamp`. That is wall time
until the result came back; several calls issued in one assistant turn
share a start, so their durations overlap rather than add, and the page
labels them "until result" rather than "ran for". Validity follows the
page's existing rule, `turn_latency` over `_parse_ts`: `null` for a
missing, malformed or backward timestamp.

The DDL is create-if-absent, and `apply_ddl` records the current version
whether or not a new column was applied; an old store would therefore be
stamped 8 while lacking the column, and the first query would fail. So
the slice is the green-field MVP the owner ruled for: `apply_ddl` checks
for `completed_at` when `copilot_tool_result` already exists and, if it
is absent, raises `SchemaMismatch` with the remedy (recreate the store,
`ingest --full`) and records nothing. No read-only degradation; that
would mean column detection and conditional queries for a store the
owner has said not to support. The owner's own store predates the
column: the PR says so, verification uses a scratch store until then,
and their store is recreated only on their word.

**D2a — unfinished calls stay visible.** `RawToolCall` allows a call
whose result never came (a session ended mid-call), and the store writes
no result row for it. The batched query is a `LEFT JOIN` from tool calls
to results, so such a call is returned with null result and duration
fields and the page shows "no result recorded" rather than dropping it.

**D3 — orphans are shown, marked.** A sidechain turn whose parent is not
in the session (ingest boundaries, a resumed session) stays in the list
at top level with a mark, so nothing a person can see in the transcript
disappears from the page.

**D4 — one query, not N.** Tool calls, results and file accesses are read
with one query per session and folded into turns in Python; the existing
turns query is untouched.

## Verification

- `python -m pytest scripts/session_analytics/tests -q` (the smoke
  workflow's suite): new assertions in `test_mcp_tools.py` over the
  fixture (2 calls, 2 results at +1 s each, 1 nested sidechain) and
  synthetic rows for an orphan, an errored call, a call with no result
  row, and results with a missing, malformed and backward timestamp
  (`duration_seconds: null` for each); a version-7 store refused by
  `apply_ddl` with no version row written; every existing key in the
  payload still present and equal; the ingest test asserts
  `completed_at` is written.
- `npm run states-check`, `npm run lint`, `npm run build` in `studio/`.
- A scratch store: ingest the fixture and a copy of a real transcript
  into a fresh SQLite file, start a second API and Studio on other ports
  against it, open a session with tool calls and a subagent run, check
  FR-4 and FR-5 by eye. The owner's own instance is never restarted, and
  their store is not touched until they authorize its recreation; the
  final check against it happens after that.
- `scripts/validate-spec.sh --all`, `scripts/check-origin-alignment.sh
  sa-trace-tree`, `scripts/check-doc-accuracy.sh`, `git diff --check`,
  then `/review-submit` (DeepSeek), then CI.

## Risks

- **Prettier churn on `.ts`/`.tsx`.** Edits to Studio files trigger the
  auto-format hook; diffs are checked after every edit and reformatting
  of untouched lines reverted.
- **The fixture is thin.** Synthetic rows cover what it lacks; a richer
  fixture would be its own change to the smoke workflow's data.
- **The owner's live store predates the column.** Once this ships, the
  API refuses that store with the recreate-and-re-ingest message until
  it is recreated; that is by design, and it means the owner's Studio
  stops working on the old store the moment they update. Said in the PR
  and timed with them.
- **Payload growth for tool-heavy sessions.** Bounded by previews and
  lengths, not bodies; measured on the owner's largest session during
  verification and reported.
