---
spec_mode: none
feature_id: auto-build-result-array
risk_category: bugfix
justification: |
  Non-security bug fix (#197): normalize the CLI's array-form
  `--output-format json` result before extraction in both session
  backends; no new surface, no schema change. spec_mode none per the
  spec-workflow table for bug fixes.
status: approved
date: 2026-08-08
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/197
  origin_claim: |
    Bug #197: "auto-build-loop parks successful build sessions — reads
    `.subtype` on the CLI's JSON array (result is `.[-1]`)". The driver
    parses `-p --output-format json` as a single object; the current
    CLI returns an array of messages with the result as the
    type=="result" element. `.subtype` on the array → "unknown" → parks
    a succeeded phase; cost reads 0 (caps never accrue); session_id
    reads empty (breaks --resume chaining). Fix: normalize
    array-or-object to the result element in run_claude_session AND
    run_pi_session; regression with a captured 300+-element array.
---
# Plan: normalize array-form CLI results (#197)

`session_result_obj()` — array → the last `type=="result"` element
(falling back to `.[-1]`), object → itself, else `{}` — used by both
backends before extracting subtype/cost/session_id. The test suite's
mock claude now emits the ARRAY shape by default (the prior
single-object mock was the blind spot that let this ship), with a
legacy-object mode, a 344-element captured-scale case, and a
continuation case proving session_id chains `--resume`.
