# Spec: a stored session analysis is judged by the mode it was computed under (#515)

A stored session analysis (`session_analysis.result_json`, `error_text`)
survives a re-ingest and records no mode. The outbound floor (#457) judges
it only by its session, and `ingest --full` re-records a tightened
project's sessions under the current mode. So an analysis stored while the
project was looser, quoting what the judge was sent, leaves the machine as
stored (#515). This spec records the mode with each analysis and judges
the stored text by it, as #514 does for archived rows.

## Requirements

- **FR-1: the loosest mode the judge was sent is recorded.** Every stored
  analysis, a parse failure included, records the loosest mode among the
  text derived from session content in the request. That is:
  - each transcript turn the judge saw (after elision) that carried text,
    by the mode its text left under: an archived row's own mode, a
    preview's session-recorded mode, or `metadata-only` where the text left
    as the marker;
  - the steering excerpts, when any were sent, under the stricter of the
    session's recorded mode and the project's current mode, which is how
    they are read.

  Facts and the harness stamp are metadata and do not count. A request
  that carried no such text records the session's outbound mode.
- **FR-2: in its own table.** The mode is stored in a new table,
  `session_analysis_mode` (`session_ref`, `kind`, `redaction_mode`,
  `recorded_at`), written with every stored analysis. It is schema 14,
  created in place: an existing store gains the table and keeps every
  session.
- **FR-3: judged on the way out.** An off-machine reader judges a stored
  analysis's `result_json` and `error_text` by its recorded mode against
  the project's current mode. When the current mode is stricter, the text
  leaves as the metadata-only marker. An analysis with no recorded mode,
  stored before schema 14, counts as `none`. A floored session's analyses
  still leave as markers, as before.
- **FR-4: the readers.** Ask `session_analyses` applies FR-3 to both the
  result and the error. Ask `session_summary` reads only each analysis's
  parse status and is unchanged. The Studio analysis API is on-machine and
  applies no floor, per #457's coverage ruling.
- **FR-5: tests.**
  - A canary case: a stored analysis quoting a canary, in `result_json` and
    in `error_text`; then tighten and `ingest --full`, with and without an
    archive. Ask `session_analyses` carries no canary. The case fails on
    master.
  - Unit tests of the recorded mode, and an old row counting as `none`.
  - A test that a re-ingest rewrites `copilot_tool_call.input_preview` and
    `copilot_tool_result.error_message` under the current mode.
- **FR-6: the inventory.** `plan.md` lists every stored text column derived
  from session content, how each is written and rewritten, whether it
  leaves the machine, and its ruling, including `copilot_session_metadata.value`.

## Constraints

- No column on an existing table. `check_schema` refuses a store that has a
  table without a required column, and its only remedy is a recreate,
  which drops every session whose transcript has since been pruned
  (schema 11's note). Schemas 11, 12 and 13 added tables for that reason.
- Stored analyses are not rewritten; the floor is applied on the way out,
  as for every other stored text.
- What each mode removes does not change, and neither do the on-machine
  readers.
