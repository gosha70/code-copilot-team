# Origin Alignment Check — analysis-recorded-mode

Date: 2026-11-23 16:12
Trigger: first alignment record for this fix (gate exit 4), written with
the fix and its tests, before review.

## Origin sources read

- Issue #515: a stored session analysis survives a re-ingest, records no
  mode, and is returned as stored after a tightening and `ingest --full`,
  with or without an archive.
- The owner's decision of 2026-11-23: option (a), in its own issue and PR,
  not holding #514's fix, with the five conditions quoted in `plan.md`.

## Acceptance criteria — status

- Record the loosest mode of the text the judge was actually sent —
  **met**. Each analysis records the loosest leaving mode over the
  transcript turns the judge saw (after elision; the elision marker
  carries no session text) and, when sent, the steering excerpts. Facts
  and the stamp are metadata.
- Old rows count as `none` — **met**. An analysis with no row in the new
  table reads back with `None`, which readers count as `none`
  (`test_an_analysis_with_no_recorded_mode_counts_as_none`,
  `test_an_analysis_stored_before_schema_14_reads_back_with_no_mode`).
- Cover `error_text` as well as `result_json` — **met**. Ask
  `session_analyses` judges both, and failures record their mode
  (`test_a_parse_failure_records_its_mode_too`).
- A canary case: a stored analysis quoting a canary, then tighten and
  re-ingest — **met**:
  `test_an_analysis_stored_before_a_tightening_and_reingest_sends_no_canary`,
  with the quote in the result and in the error, with and without an
  archive. It fails in all four subtests before this change.
- An inventory of every stored text column derived from session content,
  with a ruling on `copilot_session_metadata.value` — **met**, in
  `plan.md`.
- A test that re-ingest rewrites `input_preview` and `error_message` —
  **met**:
  `test_a_reingest_rewrites_tool_inputs_and_tool_errors_under_the_current_mode`.

## Mismatches

- The owner's option (a) named a column on `session_analysis`. A new table
  is used instead: a column would make `check_schema` refuse every
  existing store until it is recreated, and a recreate drops sessions
  whose transcripts were pruned (schema 11's note). The behaviour the
  owner asked for is unchanged. The plan lists this under "Decided here,
  for review".

## Verdict

Verdict: aligned
Confidence: high
