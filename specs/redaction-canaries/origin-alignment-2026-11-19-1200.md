# Origin Alignment Check — redaction-canaries

Date: 2026-11-19 12:00
Trigger: the owner's review of PR #475 revised FR-004, FR-005, FR-006 and
FR-007, ruled D1–D3 and approved the bundle; spec, plan and tasks changed
after the previous record (2026-11-19 03:30).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/457.
- `origin/2026-11-19-owner-decisions.md`: the three scoping rulings and the
  review of the spec (verbatim).
- The previous alignment record, `origin-alignment-2026-11-19-0330.md`.

## Origin claim (verbatim)

> Plant canary secrets in test fixtures and assert they never appear in any
> excerpt or judge-bound output. … If a future contributor adds a new
> excerpt path that skips redaction, the canary will surface in the test
> output and fail the build.

## What changed since the previous record

- **FR-004 under `code`.** Now asserts every canary except prose: fenced
  and straddle canaries, steering fences, the tool-input value, tool output
  and the error message. `code` mode reduces the last three to a hash marker,
  so their absence is a promise of the mode (owner's review point 1). This
  narrows the previous record's "prose under `code`" divergence to the prose
  canaries alone.
- **FR-005 / FR-006, D2.** Sessions of a project currently `ingest: "off"`
  are skipped on every outbound path (no row, text, marker or identifier),
  not sent as markers. US4 and a floor test for the opt-out were added.
  Aggregates over the store are stated as not per-session data. Stored rows
  are not deleted.
- **FR-007.** The guard's limits are stated: aliases, dynamic lookup, new
  transport method names, direct HTTP (owner's review point 2).
- **D1, D3.** Recorded as agreed in spec.md, "Decisions".
- **Status.** spec, plan and tasks are `approved`.

## Acceptance against the origin

- Canary per placement, asserted on every excerpt and judge-bound output,
  including steering files and the harness stamp: FR-001–FR-004 (judge
  paths in FR-003).
- A new path that skips redaction fails the build: canaries on every path
  the suite runs (FR-004), plus the coverage guard for paths it does not run
  (FR-007), with the guard's static-scan limits stated rather than implied.

## Mismatches / resolved divergences

- Coverage wider than the issue (everything off-machine) and the
  current-mode floor: owner's scoping rulings, unchanged.
- Prose canaries under `code`: still not asserted, because `code` keeps
  prose by definition; the owner's review confirmed "only prose canaries are
  exempt".
- The guard cannot prove completeness for aliased, dynamic, newly named or
  direct-HTTP transports; FR-007 says so and leaves those to review.

## Revision (owner's second review, same day)

- Success criterion 1 now reads "Under `code`, no canary except the prose
  ones does", matching FR-004.
- FR-005 and the matching plan sentence now say: "Totals may include them,
  but no aggregate is broken down by, or names, an opted-out project or its
  sessions." This tightens D2 for aggregates: an Ask or MCP answer may count
  an opted-out project's sessions in a total, but no per-project or
  per-session breakdown, and no list of project paths, includes it.

Both edits are the owner's wording; the bundle stays `approved`.

## Verdict

Verdict: aligned
Confidence: high
