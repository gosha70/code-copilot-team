# Origin alignment check — auto-build-result-array

- date: 2026-08-08 (post PR-#198 review round)
- trigger: the review proved acceptance criterion 4 ("PI backend fixed
  identically") was NOT satisfied by the array-or-object normalizer —
  pi's `--mode json` emits JSON LINES (this repo's own
  adapters/pi/docs/headless-harness.md), on which per-document jq
  produced a multi-line subtype and parked successful pi sessions with
  a silently-dropped cost write. plan.md wording updated; the helper
  now slurp-normalizes all three shapes; the mock pi-code emits its
  documented JSON-LINES contract (its legacy-object mock was the same
  blind spot the PR indicts on the claude side).

## Origin claim (from plan.md, unchanged origin)

Issue #197: normalize the CLI result before extraction in BOTH
backends; success advances for real output shapes; cost accrues;
session_id chains --resume; "PI backend fixed identically";
300+-element regression.

## Working claim

session_result_obj() slurp-normalizes claude's array, pi's JSON-LINES,
and the legacy object to the result element (`.[-1]` fallback per the
issue's own proposal, deliberately kept — it only matters for a
type-less result envelope and every real non-result tail still parks);
both backends use it; both mocks emit their real shapes; regressions
cover the 344-element scale, legacy object, NDJSON cost accrual, and
--resume chaining.

## Mismatches

none — criterion 4 is now satisfied in effect, not just claimed.

Verdict: aligned
Confidence: high
