# Origin Alignment Check — export-privacy-floor

Date: 2026-11-23 18:12
Trigger: the rebase of PR #513 onto master `f63d655` (#516, the row-level
floor for archived text), with items 3 and 4 of the owner's review of #513.

## Origin sources read

- The owner's review of #513: "(3) Rebase #513 onto that, use the same
  check for export's trace_documents (the fast path can't skip that table),
  and add one line to FR-4 in the export spec. (4) In #513, also apply the
  run-dir path check to sessions.benchmark_run_dir, with a spec line and a
  test."
- Issue #514 and its merged fix (#516): archived text is judged by its
  trace row's own `redaction_mode`.
- The 13:56 record.

## Acceptance criteria — status

- Item 3, the same check for `trace_documents` — **met**. `ExportFloor`
  decides each row's `content` and `redaction_mode` with `archive_floors`
  and `archived_text` on the row's own `redaction_mode`, as MCP
  `get_session_details` and the session-analysis transcript do.
  `test_an_archived_row_is_judged_by_its_own_mode_after_a_reingest` fails on
  the export before this change (the canary key is written as stored) and
  passes with it.
- Item 3, the fast path cannot skip that table — **met**. `trace_documents`
  never takes the unfiltered path, and the test above asserts that the floor
  is inert in the state it checks. A row the floor leaves alone is written as
  stored: `test_an_archived_row_no_looser_than_the_current_mode_is_written_as_stored`
  compares the CSV bytes.
- Item 3, one line in FR-4 of the export spec — **met**. The README's Export
  section says the same in one sentence, since FR-8 has it describe the
  default.
- #516's canary case (ingest and archive under `none`, tighten,
  `ingest --full`, archive not re-run) now reaches export through
  `capture_all`. Before item 3 it failed on `export trace_documents` in both
  subtests (tightened by the project, and globally); it passes now.
- Item 4, the run-dir check on `sessions.benchmark_run_dir` — **met**: FR-3,
  FR-6 and the `sessions` column rule in the spec, and
  `test_a_sessions_benchmark_run_dir_under_an_opted_out_project_is_emptied`,
  which also checks that a path outside the project is kept. The summary
  names what each table emptied.
- The 13:56 record's criteria stand: the tests behind them pass after the
  rebase, apart from the two Parquet tests, which cannot load pyarrow on
  this host.

## Mismatches

None. One consequence was settled here: a `trace_documents` row reduced by
its own mode was counted under "(project tightened since ingest)", which is
wrong after a re-ingest. That table's summary now says "(project tightened
since archive)", and FR-6 says so; the other tables keep "since ingest".

## Verdict

Verdict: aligned
Confidence: high
