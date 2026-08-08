# Origin Alignment Check — cost-cap-visibility

Date: 2026-08-08 15:05
Trigger: plan.md and spec.md revised after the user's P2/P3 on PR #208;
the previous record (`origin-alignment-2026-08-08-1420.md`) is stale.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/201.
- The user's P2/P3 review of PR #208.

## Origin claim (the user's P2, verbatim)

> A live cap decrease below already-spent total is accepted but not
> enforced at the phase gate. … If the final phase has already spent
> `$4.24` and the live config is changed to `$1`, the run can still finish
> as done while reporting spend over the new cap. Since this is a safety
> cap, either only accept raises (`live_cost > CAP_COST`) or immediately
> re-run `check_caps` after applying a lower cap so the phase gate parks
> before publish/finalization.

## Working claim

Of the two remedies offered, the second: a decrease is accepted — winding
an expensive run down is a legitimate operator action — and enforced
immediately by re-running `check_caps` straight after the new cap is
applied, so an over-budget run parks at that gate instead of committing
and finishing `done`. The spend line now formats the cap with the same
`%.2f` as the other figures, matching the documented output.

## Mismatches

- none against the findings.

Rejecting decreases outright (the first remedy) would have been simpler,
but it removes a legitimate control: an operator watching a run get
expensive should be able to stop it from the same file they would use to
raise it. Accepting the change and enforcing it immediately keeps both,
and the re-check also covers a RAISE that still leaves spend over the new
value.

Both findings are pinned by regressions that fail against `694dbbe`,
including the exact scenario: against the reviewed commit the run finished
`done` (exit 0) with spend over the lowered cap; it now parks
`cap_exceeded` (exit 4).

## Verdict

Verdict: aligned
Confidence: high
