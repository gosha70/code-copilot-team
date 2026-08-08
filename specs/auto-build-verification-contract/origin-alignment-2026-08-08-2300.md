# Origin Alignment Check — auto-build-verification-contract

Date: 2026-08-08 23:00
Trigger: first alignment record for this feature (gate exit 4). Planning
artifacts only — no implementation yet, pending user approval.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/222 (the C1
  child issue, scope and acceptance criteria).
- Parent: https://github.com/gosha70/code-copilot-team/issues/190 §6, the
  coverage table, the `skip_is_failure` paragraph, and the
  "floors come from project/template presets" sentence.
- `specs/auto-build-admission/spec.md` § "Increment-C handoff notes" — the
  five items recorded by the #194 review.
- The user's instruction: "start with the plan - I will review/approve -
  then you can build it".

## Origin claim (verbatim, #190 §6)

> **`skip_is_failure`.** Today a missing Playwright degrades `visual-review`
> to an HTTP-200 smoke and reports SKIP. In unattended mode that is
> precisely how a run ships unverified UI. Hard fail.

and

> Floor values come from **project/template presets**, not a global
> hard-code — eleven templates will not share one number.

## Working claim

The declarative half of §6 as an opt-in `automation.json` block: coverage
floors for greenfield and brownfield, preset-sourced floor values,
istanbul/lcov parsing with the other two formats refused rather than
faked, `conformance` accepted-but-inadmissible, plus the two concrete
handoff items (worktree prune, admission `test.command` accounting).

## Mismatches — one, deliberately surfaced for the approver

- **`skip_is_failure` is implemented at ADMISSION, not as a driver-side
  visual failure.** #190 says "hard fail", which reads as a run-time gate.
  The driver has no visual step to fail: `visual-review` is a model-driven
  skill whose SKILL.md instructs the agent to report SKIP when Playwright
  is absent. Adding a driver-side visual step is a slice of its own
  (dev-server lifecycle, Playwright/axe invocation, screenshots), and
  putting the rule in the skill would ask a model to fail itself — the
  trust boundary #193 and #200 spent this arc removing. So C1 refuses to
  ADMIT an unattended run with UI in scope on a host lacking the toolchain.
  Consequence the approver should weigh: such a run becomes un-admittable
  rather than degrading to SKIP. This is strictly fail-closed and matches
  the existing `runtime_conformance` precedent, but it IS a different
  mechanism than the issue's wording implies.

Everything else follows the origin as written. The remaining §6 content
(runtime conformance evaluator) and handoff items 1, 2 and 5 are recorded
as C2 rather than silently dropped.

## Verdict

Verdict: aligned
Confidence: high
