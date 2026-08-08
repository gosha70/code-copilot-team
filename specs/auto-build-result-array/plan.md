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

`session_result_obj()` slurp-normalizes all three real result shapes —
the claude CLI's message ARRAY, pi's JSON-LINES stream (documented in
adapters/pi/docs/headless-harness.md), and the legacy single object —
to the last `type=="result"` element (`.[-1]` fallback per the issue's
proposal), else `{}`; used by both backends before extracting
subtype/cost/session_id. The test suite's
mock claude now emits the ARRAY shape by default (the prior
single-object mock was the blind spot that let this ship), with a
legacy-object mode, a 344-element captured-scale case, and a
continuation case proving session_id chains `--resume`; the mock
pi-code emits its documented JSON-LINES shape (its legacy-object mock
was the same blind spot on the pi side).

The same bug class is folded on the review runner's `CCT_REVIEW_COST_FILE`
reader, which a cli provider may legitimately wire to a whole CLI result.
It slurps too, but does NOT copy the driver's tail fallback: the two sites
fail in opposite directions. In the driver a type-less tail element merely
parks (fail-closed); in the cost reader it would promote a non-result
document's `total_cost_usd` to a "measurement", and per #193's trust
boundary a bogus measurement is exactly what suppresses the driver's
conservative estimate. The reader falls back only to a lone document
carrying no `type` key — the canonical purpose-written
`{"total_cost_usd": N}` file — and otherwise resolves to `{}` → unmetered.
Slurping is load-bearing beyond shape support: per-document evaluation
emitted one line per cost-bearing document, and a multi-line cost was not
a clean degrade to unmetered — it blanked the cost state and wrote
`findings-round-N.json` as a 1-byte file that still satisfied downstream
`-f` checks, which the regression shows driving the driver to exit 6.
