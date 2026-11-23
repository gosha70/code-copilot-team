# Origin Alignment Check — export-privacy-floor

Date: 2026-11-23 04:01
Trigger: the plan was approved with changes, so `plan.md` and `spec.md`
are newer than the 03:49 record.

## Origin sources read

- Everything the 03:49 record read: issue #487, the owner's ruling of
  2026-11-20, the answers to D1 to D4, and the seven additions.
- The owner's approval of 2026-11-23, with two changes and one optional
  point:
  - Build on a fresh branch from master, in a new PR, after this plan's PR
    (#512) merges, not on #512's branch.
  - The stderr summary counts what the written tables actually changed:
    rows dropped, text replaced, `session_ref` emptied. `--table kpis` with
    a tightened project then prints nothing, and a test says so.
  - Optional: in D3, keep `run_dir` as stored, or empty it when it sits
    under an opted-out project's path.

## Acceptance criteria — status (plan stage)

- Every criterion in the 03:49 record: still **planned** where it said.
- The summary counts the written tables' changes: **planned**, FR-6 and
  `plan.md` step 3. A row reduced to `metadata-only` counts once, whether
  its text, its mode or both changed. Under `--raw` the one line counts only
  sessions whose rows in the written tables the default would have dropped
  or changed.
- The `--table kpis` test: **planned**, `plan.md` step 4.
- `run_dir`: **planned** as emptied when it sits under an opted-out
  project's path (FR-3, the column table, D3).
- `status: approved`; the build happens in a new PR from master.

## Mismatches

- None against the approval. Two readings were taken where the approval
  leaves room, and they are recorded in the spec:
  - its "text replaced" is counted together with the `metadata-only` mode
    label, as one reduced row;
  - its optional point is taken as "empty", whatever `session_ref` holds.

## Verdict

Verdict: aligned
Confidence: high
