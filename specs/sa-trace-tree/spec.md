---
feature_id: sa-trace-tree
spec_mode: lightweight
status: approved
date: 2026-09-22
issue: "#371 (slice A1; separate PR; leaves #371 open)"
origin:
  issue: "#371"
  transcripts:
    - specs/sa-trace-tree/origin/2026-09-22-owner-direction.md
  user_messages:
    - "2026-09-22: 'I would rather work on extending capabilities of Session Analysis rather using ML Flow. Could you please identified ML Flow features which we can add'"
    - "2026-09-22: 'Can you start planing the addressing the features listed in issues/371?'"
---

# Spec: the trace tree on the session page (A1)

## Why

A session page shows what was said, turn by turn, and a boolean chip
saying a turn used tools. What the agent did with those tools, which
files it touched, whether a call failed, and which turns were a
subagent's rather than the main thread's, are all ingested and stored,
and never shown. That is the one thing MLflow's trace view has that
Session Analytics does not (`doc_internal/plans/session-analytics-mlflow-gaps-2026-09-22.md`, A1).

## Verified facts (2026-09-22, master 905d263)

| Fact | Where |
|---|---|
| `copilot_tool_call` stores `tool_name`, `tool_name_raw`, `input_preview`, `sequence_num` per turn; `copilot_tool_result` stores `status`, `is_error`, `output_length`, `error_message`; `copilot_file_access` stores `file_path`, `access_type`, `language` with turn and tool-call refs | `scripts/session_analytics/config_data/ddl/postgres/001_core.sql` |
| `copilot_turn` stores `uuid`, `parent_uuid`, `is_sidechain`, tokens, `cost_usd`, `timestamp`; the Claude Code adapter fills `parent_uuid` and `is_sidechain` at ingest | `001_core.sql`; `adapters/claude_code.py:153-154` |
| `input_preview` is produced by `redaction.redact_tool_input(...)` under the session's redaction mode before the row is written | `relational/store.py:300` |
| Tool result bodies are not stored, by the trace-archive rule ("tool I/O is explicitly not archived") | `scripts/session_analytics/README.md` (E10) |
| `get_session_details` returns turns (sequence, role, preview, `has_tool_use`, judge fields, timestamp, archived content) and an aggregate `tool_usage` map; no tool calls, no results, no sidechain fields | `mcp/tools.py:258-300` |
| `GET /api/sessions/{id}` returns that dict unchanged; the same function is the MCP tool | `api/server.py:1357` |
| The Timeline lives inside the session page and renders `TurnRow` (typed in `studio/lib/api.ts:465`) with a `tools` chip and per-turn `latency_seconds` | `studio/app/sessions/[id]/page.tsx:143` |
| The test fixture `tiny-session.jsonl` has 8 records: 1 sidechain turn, 2 tool uses, 2 tool results | `tests/fixtures/claude_code/project-hash/` |
| Python tests run in `session-analytics-smoke.yml`; Studio components are rendered to markup by `npm run states-check` in the same workflow | `.github/workflows/session-analytics-smoke.yml:65,370` |
| No per-tool-call timestamp exists in the store; the transcript has one per record, and a tool result arrives in a later record than its tool use (the fixture: results at +1 s) | `001_core.sql` (absent); `adapters/claude_code.py:253` collects results without their record's timestamp |
| The DDL is create-if-absent with no migration step; a column added to an existing table is not applied to an existing store, and `apply_ddl` then records the current version regardless, so an old store would be stamped 8 while missing the column. `_SCHEMA_VERSION` is 7 | `relational/db.py:92-107, 236-262` |
| A tool call whose result never arrived (a session that ended mid-call) has a `copilot_tool_call` row and **no** `copilot_tool_result` row | `relational/store.py:312-330`; `contracts.py` `RawToolCall` (result fields optional) |
| The page's latency rule already exists: `turn_latency` returns `None` unless both timestamps parse (`_parse_ts`, ISO-8601 with `Z`) and the interval is not negative | `mcp/tools.py:868-884` |
| Session Analytics is unreleased; the owner ruled backward compatibility and data migration out of scope (origin record) | origin |

## Requirements

- **FR-1** `get_session_details` adds to each turn a `tool_calls` list, in
  `sequence_num` order, each with `tool_name`, `tool_name_raw`,
  `input_preview`, `status`, `is_error`, `output_length`,
  `error_message`, `completed_at`, `duration_seconds`, and `files` (the
  `copilot_file_access` rows linked to that call: `file_path`,
  `access_type`). A turn without tool calls has `tool_calls: []`.
- **FR-1a** `copilot_tool_result` gains `completed_at` (the timestamp of
  the transcript record that carried the result), filled at ingest.
  `duration_seconds` is served as `completed_at` minus the turn's
  `timestamp` under the page's existing latency rule (`turn_latency`
  with `_parse_ts`): `null` when either timestamp is missing or does not
  parse, or when the interval is negative. It is the wall time until the
  result came back, which for several calls issued in one turn overlaps
  rather than adds, and the page says so.
- **FR-1b** `_SCHEMA_VERSION` becomes 8, and `apply_ddl` refuses a store
  that predates it: when `copilot_tool_result` exists without
  `completed_at`, it raises a `SchemaMismatch` naming the store, the
  version found and the remedy (recreate the store, then `ingest
  --full`), and records nothing. Version 8 is recorded only when the
  column exists. The README states the same remedy; there is no
  migration and no read-only degradation.
- **FR-1c** A tool call with no result row is still returned, with
  `status`, `is_error`, `output_length`, `error_message`, `completed_at`
  and `duration_seconds` all `null`; the page shows it as "no result
  recorded". The query is one batched `LEFT JOIN`.
- **FR-2** Each turn gains `is_sidechain` and `parent_sequence`: the
  `sequence_num` of the turn whose `uuid` equals this turn's
  `parent_uuid`, or `null` when there is none in the session. A sidechain
  turn whose parent is absent is still returned, with
  `parent_sequence: null`.
- **FR-3** Nothing already in the payload changes shape or value; the
  additions are additive, so existing Studio tabs, the MCP tool's
  callers and `export` are unaffected.
- **FR-4** The Timeline renders, under each turn that has them, the tool
  calls as a collapsible list: tool name, the input preview, the
  duration, and the result's status, error flag, output length and error
  message; files touched under the call. Sidechain turns render nested under their
  parent turn, marked as a subagent run; an orphan sidechain turn renders
  at top level with a "parent not in this session" mark.
- **FR-5** Everything the Timeline does today survives: hash scrolling to
  a turn, archived text versus preview, judge badges, latency, slash
  command chips. Turn numbering (`sequence_num`) is unchanged by nesting.
- **FR-6** Tests: a Python test over the fixture asserts the tool calls,
  results, durations, files and the sidechain nesting in the payload,
  plus synthetic rows for an orphan sidechain, an errored call, a call
  with no result row, and results whose timestamp is missing, malformed
  or earlier than the turn's (`duration_seconds: null` for each); a test
  that a version-7 store is refused by `apply_ddl` with the remedy in
  the message and no version row written; the new component is added to
  `states-check` with its states (calls, no calls, error, no result,
  orphan). The session README gains a paragraph.

## Constraints

- No new dependency, no new store, no new endpoint (plan D1). One
  column, a schema-version bump and the mismatch refusal are the whole
  schema change (plan D2); the store is recreated, not migrated, by the
  owner's ruling.
- Before the owner's store is recreated on their word, verification
  runs against a scratch store ingested from the fixture and from a copy
  of a transcript; never against the live store with the old schema.
- Redaction is not re-implemented: `input_preview` is served as stored.
  Result bodies are not stored and are not invented.
- The change is verified in the owner's running Studio on separate
  ports, never by restarting their instance.
- One PR under #371, no close marker; #371 stays open for A2 onward.

## Out of scope

A2–A6. A separate trace endpoint. Any change to redaction, the judge
or export. Ingest changes only as far as FR-1a needs.
