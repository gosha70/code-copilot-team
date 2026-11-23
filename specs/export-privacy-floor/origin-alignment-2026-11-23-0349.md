# Origin Alignment Check — export-privacy-floor

Date: 2026-11-23 03:49
Trigger: first alignment record for this feature (gate exit 4), written with
the draft plan for the plan-only PR. Build waits for the plan's approval.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/487. Export
  writes rows of a project opted out or tightened after ingest, planted
  secrets included (reproduced on `caa7ad7` with the canary corpus). The
  proposal: apply the off-machine floor by default (drop an opted-out
  project's sessions from every table, write a tightened session's stored
  text as a `metadata-only` marker), with a flag for the store as it is, and
  a summary saying how many sessions were left out and why.
- The owner's ruling of 2026-11-20: "#487 waits until after 2.1.0: write a
  lightweight plan for it first."
- The owner's answers of 2026-11-23 to the plan's open decisions: filter by
  default with `--raw` (D1), `metadata-only` in a tightened session's
  `redaction_mode` (D2), a `benchmark_results` row of an opted-out session
  kept with `session_ref` empty (D3), feedback text as stored (D4).
- The seven additions relayed on 2026-11-23 before the plan-only PR: a
  column-by-column table; counts-only summaries; one `--raw` line; #478's
  combined check, tested under each key; an explicit D4 test; "same bytes"
  for CSV and "same rows" for Parquet; the docs to change and the 2.1.0
  visual pages to leave alone.

## Acceptance criteria — status (plan stage)

- An opted-out project's sessions are not exported from any table:
  **planned**, FR-3 and the column table.
- A tightened session's stored text leaves as a `metadata-only` marker:
  **planned**, FR-4 and the column table (`turns.content_preview`,
  `trace_documents.content`).
- A flag exports the store as it is: **planned**, FR-5 (`--raw`).
- The output says how many sessions were left out and why: **planned**,
  FR-6, in counts only.
- A store with no opted-out or tightened project is unchanged: **planned**,
  FR-7 (CSV bytes, Parquet rows).
- The README's Export section is updated: **planned**, FR-8, with the
  cookbook examples and an Unreleased CHANGELOG entry.

## Mismatches

- The issue's "not exported, from any table" is narrowed for
  `benchmark_results` by the owner's D3: the benchmark outcome stays and
  only its link to the session is emptied.
- D2 and D4 settle what the issue left open: the mode column of a tightened
  session, and feedback, which no off-machine path sends.
- The issue suggested `spec_mode: none` or an amendment to
  `specs/redaction-canaries/`; the owner ruled a lightweight plan, and the
  two earlier specs get pointer lines (FR-8).

## Verdict

Verdict: aligned
Confidence: high
