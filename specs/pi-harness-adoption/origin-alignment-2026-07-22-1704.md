# Origin alignment check — pi-harness-adoption

Supersedes `origin-alignment-2026-07-21-2314.md`, which went stale when the
rescope note was removed from `spec.md`. Re-assessed after that removal.

Origin: specs/pi-harness-adoption/origin/2026-07-21-user-directive.md
(verbatim user directive; originating session
https://claude.ai/code/session_01FHuNSqq7gphscrchWGUY7D is auth-gated
and could not be re-read from this repo).

Origin claim:
> Provide a detailed Spec Driven Development plan for supported PI
> harness in Code Copilot Team and adding the heavy discoverable and
> flexible configuration for supporting all features available in
> Claude Code to this PI adoption. [Consolidated across three
> independent plans + final resolutions R1–R6 + verification addenda
> V1–V3, 2026-07-21.]

Working claim:
> spec.md delivers Pi as a first-class executable adapter at enforced
> tier through one distribution with two activation surfaces — a Pi
> advisory content package (`pi install`) and the `pi-code` launcher
> loading an authored enforcement runtime — with discoverable, layered,
> explainable configuration, risk-scaled SDD enforcement, the
> Research→Plan→Build→Review phase workflow, permission/protected-path
> policy, and provider/wiki/benchmark/analytics integration.

What changed since the superseded record:
  - The rescope note was removed from `spec.md`. The Acceptance Criteria
    stand as originally written and are the gate for this feature; no
    slice is treated as out of scope.
  - `tasks.md` no longer defers Slice B or Phase 6. Every task is to be
    delivered; the progress header tracks completion against all 64.
  - Phase 0 completed: T0.1 (adapter advisory manifest, no
    `pi.extensions`), T0.3 (`pi.themes` + `resources/themes/`), T0.4
    (`setup.sh --repair`), T0.6 (CI consumption of `compat.env` with a
    launcher-fallback drift guard). 11 of 64 tasks complete.

Mismatches:
  - none. The origin's "all features available in Claude Code" is
    realised via the capability model; the exclusions in spec.md
    Non-Goals (hosted services, Remote Control, transcript-identical
    parity) were fixed by resolutions R1–R6, which are part of the
    consolidated origin input itself (same date), not later drift.
  - The previously recorded rescope of the Definition of Done has been
    withdrawn. Removing it moves the working artifacts closer to the
    origin, not further from it: the origin asked for support of all
    Claude Code features, and the full Acceptance Criteria express that.

Verdict: aligned
Confidence: medium

Note: confidence is medium, not high, because the originating session
transcript is auth-gated and was not re-read this session; the verbatim
recorded directive, the origin_claim, and the three related_specs
references were read/verified in full. Scope note: this record scores
spec/plan-vs-origin alignment only. Delivery progress against the spec
(11 of 64 tasks) is tracked in `tasks.md`, not here.
