---
spec_mode: lightweight
feature_id: analysis-recorded-mode
risk_category: bug
justification: |
  Privacy bug fix (#515). A stored session analysis leaves the machine as
  stored after a tightened project is re-ingested, because it records no
  mode. It touches more than two files and adds a table (schema 14,
  created in place), but it adds no feature surface and no configuration,
  so lightweight rather than full; the owner can rule otherwise. It builds
  on #514's row-level floor (PR #516).
status: approved
date: 2026-11-23
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/515
  origin_claim: |
    The owner, 2026-11-23, on #515: "option (a), in its own issue and PR;
    don't hold the trace fix for it. Conditions: record the loosest mode of
    the text the judge was actually sent; old rows count as `none`; cover
    `error_text` as well as `result_json`; add a canary case (a stored
    analysis quoting a canary, then tighten and re-ingest); put an inventory
    of every stored text column derived from session content in the plan,
    with a ruling on `copilot_session_metadata.value` and a test that
    re-ingest rewrites `input_preview` and `error_message`."
---

# Plan: a stored session analysis is judged by the mode it was computed under (#515)

The requirements are in `spec.md`. This plan gives the approach, the
inventory the owner asked for, and the decisions taken here.

## Approach

1. **Schema 14** (`relational/db.py`, `014_session_analysis_mode.sql`): a
   new table, `session_analysis_mode`, one row per `(session_ref, kind)`
   like `session_analysis`. A schema-13 store gains it in place.
2. **The policy** (`ingest/redaction.py`): #514's row-level check is
   generalised to any text recorded under a known mode, as
   `recorded_text` and `recorded_floors`. `archived_text` and
   `archive_floors` delegate to them. `leaving_mode(session, mode)` gives
   the mode a text actually leaves under.
3. **Recording** (`judge/session_analysis.py`):
   - each `TranscriptTurn` carries the mode its text left under;
   - `Transcript.loosest_mode` is taken over the turns the judge saw;
   - `ProjectContext` carries the mode its excerpts were read under;
   - `analyze_session` takes the loosest of them, and `_store` writes it
     beside the analysis, failures included;
   - `get_analysis` returns it, as `redaction_mode` (`None` before
     schema 14).
4. **Reading** (`ask/tools.py`): `session_analyses` judges the stored
   result and error by that mode, with `None` counting as `none`, and still
   floors a floored session's analyses.
5. **Tests**: as in FR-5, with the canary case run against master first,
   where it must fail.

## Inventory: stored text derived from session content

"Rewritten by `ingest --full`" means a re-ingest replaces the value under
the project's current mode. "Session floor" is #457's check against the
session's recorded mode. "Row floor" is the check against the text's own
recorded mode (#514, and this PR).

| Stored text | What it holds | Rewritten by `ingest --full` | Leaves the machine through | Ruling |
|---|---|---|---|---|
| `copilot_turn.content_preview` | turn text, up to 500 characters, redacted at ingest | yes | judges, Ask, embeddings, MCP | session floor; the session's recorded mode is its mode |
| `copilot_tool_call.input_preview` | tool input, redacted at ingest | yes (tested in this PR) | MCP `get_session_details` | session floor |
| `copilot_tool_result.error_message` | tool error text, redacted at ingest | yes (tested in this PR) | MCP `get_session_details` | session floor |
| `copilot_error.error_message`, `error_type` | session errors; `error_type` keeps a first line under `none` | yes | Ask, MCP | session floor (`text`, `error_type`) |
| `trace_document.content`, and its search index | full archived turn text | **no**, only `archive --full` | session analysis, Ask `session_turns` and `search_text`, MCP, export | row floor by its own `redaction_mode` (#514) |
| `session_analysis.result_json`, `error_text` | judge output, which may quote what it was sent | **no**: it survives a re-ingest | Ask `session_analyses` | row floor by its recorded mode (this PR) |
| `copilot_session_metadata.value` | adapter metadata: git branch, feature id, Pi workflow analytics, Aider's format | yes, replaced whole | nothing reads it today | **ruling below** |
| `copilot_turn.slash_command`, `copilot_file_access.file_path`, `copilot_session.project_path` and other identity columns | metadata | yes | many | not content; no mode governs it (#457's spec) |
| `copilot_session.session_embedding` | an embedding vector | no | none as text; similarity returns ids and scores | not text |
| Kùzu graph (`ErrorNode.error_type`, `Session` and `Turn` properties) | derived from the store when the graph is built | no, until a rebuild | the curated Ask graph questions, which return no `error_type` and drop opted-out names | constraint below |
| `heuristic_label` | labels; no free text | deleted, re-judged | counts only | not text |
| `feedback.value_text`, `rationale`; `auto_build_verdict.note` | a person's own words | not derived from session content | not by the off-machine paths | not session content (#487 D4) |
| `expectation.statement`, `expectation_result.detail`, `evidence` | spec and verifier text | not derived from session content | MCP `list_expectations` | project text, outside #457 (its spec records the follow-up) |

**Ruling on `copilot_session_metadata.value`:** it stays outside the floor.

- It is adapter metadata, which the adapter neutralises before storing (004's redaction boundary).
- A re-ingest replaces it whole, so it cannot outlive a tightening.
- No path reads it to send it anywhere; only the Pi adapter writes a key that has one.

A future reader that sends it off the machine takes the session floor, which is right for a value the re-ingest rewrites. The canary coverage guard flags a new transport.

**Constraint on the graph:** a future curated question that returns `ErrorNode.error_type` must judge it by the mode it was built under, since a graph built before a tightening keeps the old value until it is rebuilt.

## Decided here, for review

- **A side table rather than a column on `session_analysis`.** The owner's
  option (a) named a column. A column would make every existing store fail
  `check_schema` until it is recreated, and a recreate drops every session
  whose transcript has been pruned. Schemas 11 to 13 avoided this the same
  way.
- **A request with no content-derived text records the session's outbound
  mode.** Its output cannot quote content.
- **Elided turns do not count.** The mode is taken over the turns the
  judge saw (`Transcript.turns`), as "actually sent" asks.

## Files

- `scripts/session_analytics/config_data/ddl/postgres/014_session_analysis_mode.sql`,
  `relational/db.py`, `constants.py`
- `ingest/redaction.py`, `judge/session_analysis.py`, `ask/tools.py`
- tests: `test_canary_floor.py`, `test_session_analysis.py` (or the suite
  that covers it), `test_redaction.py`, `test_db_dialect.py`
- `CHANGELOG.md`, and `specs/analysis-recorded-mode/`
