# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-08 23:45
Trigger: plan.md and spec.md rewritten (rev 2) after the user's four
findings on the draft; the previous record is stale.

## Origin sources read

- #222 (C1 scope + acceptance criteria) and #190 §6.
- The user's review: four findings plus the decision "My visual call is
  **(c) as a prerequisite, not a substitute for (a)**. Either add the
  driver-owned visual result in this slice, or narrow C1 and explicitly
  defer the `skip_is_failure` acceptance criterion."

## Working claim

C1 delivers `verification.coverage` only — floors for greenfield and
brownfield, preset-resolved via an explicit portable key, istanbul/lcov
parsing — plus an admission-result channel and the two handoff items. Every
other sub-block is REJECTED by name. `skip_is_failure` is explicitly
deferred to C3.

## Mismatches against #222 — one, deliberate and declared

**#222's `skip_is_failure` acceptance criterion is NOT met by this slice.**
The user's instruction offered narrow-and-defer or build-the-runner; I chose
narrow-and-defer. #222 stays open for it, C3 owns the driver-owned visual
result, and the toolchain prerequisite goes with it since it only has
meaning as a gate on that result.

My rev-1 claim that admission-time toolchain checking *implemented*
`skip_is_failure` was wrong: an installed Playwright does not prove the
review ran, produced evidence, or avoided SKIP. That is the same error as
#220's "import proves startup" — a prerequisite asserted as the property.

## What rev 2 changed, per finding

1. `skip_is_failure` deferred rather than approximated; the criterion is
   named as unmet in the spec and in T8.
2. Inert fields removed: `test`, `app`, `visual`, `conformance` are now
   REJECTED by name. `conformance.required` was additionally wrong in rev 1
   — #190 derives it from verification.yaml, never operator config.
3. An explicit admission-result channel: admission parses inside the
   throwaway worktree, writes a machine-readable file BEFORE cleanup, and
   the driver imports it only after the ledger exists — preserving
   increment B's "refused admission creates no ledger" invariant, which
   rev 1 would have broken.
4. Preset resolution now uses an explicit portable `preset` key rather than
   an assumed template identity (`.claude/template.json` is
   Claude-specific), and fails closed when absent/unknown unless every floor
   is supplied.

## Verdict

Verdict: aligned
Confidence: high
