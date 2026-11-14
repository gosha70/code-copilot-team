# Origin alignment check — auto-build-hill-chart (after the second #446 review)

Date: 2026-11-12 06:00 EST

Supersedes the 01:30 record. The second review of PR #446 at c9b2c65
found three durability defects and two wording gaps; all are fixed with
regressions and the bundle says what the code does:

- The frozen mapping is written once, checked and atomic, validated on
  every later attempt, never rewritten; a corrupt or missing map on a
  resume refuses (FR-4).
- A chart write checks for exactly one matching scope in a known
  status, verifies the rewritten file, the mode and the rename, and a
  failure parks as `hill_chart_error` (FR-5).
- The chart is written before the ledger marks the phase done, so a
  `hill_chart_error` park leaves the phase at its coverage gate and the
  coverage-recovery resume arm repairs it: review the repair commit,
  rerun the gate, land the remaining scopes once (FR-5).
- Preflight journals the mapping as the spec says; the refusal code is
  1 everywhere; FR-2 claims what the suite proves (no hill artifact on a
  feature run, pre-existing fixtures unchanged at their pins), not a
  byte-for-byte comparison.

Owner rulings D1–D5 are unchanged. Origin sources unchanged: issue
#405 and the repository at `a63bf6d`; the mapping table of the 23:59
record stands.

Verdict: aligned
Confidence: high
