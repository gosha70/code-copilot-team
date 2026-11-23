# Origin Alignment Check — export-privacy-floor

Date: 2026-11-23 13:56
Trigger: the build of the approved plan (PR #512, merged as `6a876ba`),
before review.

## Origin sources read

- Issue #487, the owner's rulings and decisions D1 to D4, the seven
  additions and the approval's two changes, as listed in the 03:49 and
  04:01 records.
- The approved `spec.md` and `plan.md` on master.

## Acceptance criteria — status

- An opted-out project's sessions have no row in any table of session data
  — **met**. `TestExportFloorColumns` checks all six session tables against
  a policy built for the test, and `TestExportFloorCli` checks the real CLI
  under real configuration.
- A `benchmark_results` row of an opted-out session keeps its outcome with
  `session_ref` empty, and a `run_dir` under an opted-out project's path is
  emptied, in any row (D3) — **met**. A sibling path that only shares a
  prefix is kept.
- A tightened project's `turns.content_preview` and
  `trace_documents.content` leave as the marker, `redaction_mode` reads
  `metadata-only` (D2), and every other column is as stored, `content_hash`
  and `source_path` included — **met**.
- D4: a tightened project's feedback text is exported as stored — **met**,
  in a test of its own.
- #478's combined check: an opt-out filed under the `project_ids` id, and
  one filed under the git root, each apply — **met**.
- The summary counts what the written tables changed, in counts only —
  **met**. `--table kpis` with a tightened project prints nothing,
  `--table sessions` reports one row reduced, `--table all` gives one line
  per changed table, and no line names a project, a path or a session.
- `--raw` writes the store as it is and prints its one line — **met**:
  `--raw --table kpis` with a tightened project reports no tightened session.
- A store with nothing opted out or tightened exports the same CSV bytes,
  and the same Parquet rows — **met** for CSV. The Parquet test is skipped
  on this host, where pyarrow cannot load, and runs in CI.
- Docs: the README's Export section, the cookbook's §9 examples, an
  Unreleased CHANGELOG entry that supersedes the 2.1.0 note, and the two
  spec pointers — **met**. The 2.1.0 visual pages are untouched.
- The issue's reproduction, through the real wrapper with the canary corpus
  ingested under `none`:
  - opted out: `export --table turns` writes no row (0 of 13 canaries) and
    says "7 rows dropped";
  - `--raw`: the store's 5 of 13 canaries, as the issue found;
  - tightened: 0 canaries and 5 markers.

  **Met.**

Against master's export, the new tests fail (20 failures and 23 errors),
the floor's canary cases among them.

## Mismatches

None against the approved plan.

## Verdict

Verdict: aligned
Confidence: high
