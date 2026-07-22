# Origin alignment check — pi-harness-adoption

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
> explainable configuration (8-layer precedence, provenance, profiles,
> monotonic security floor), risk-scaled SDD enforcement, the
> Research→Plan→Build→Review phase workflow, permission/protected-path
> policy, and gated provider/wiki/benchmark/analytics integration.
> Claude Code feature coverage is expressed as a two-dimensional
> capability model with honest machine-readable parity reporting;
> Anthropic-hosted platform services are declared external-platform /
> unavailable rather than claimed as parity.

Mismatches:
  - none. The origin's "all features available in Claude Code" is
    realised via the capability model; the exclusions in spec.md
    Non-Goals (hosted services, Remote Control, transcript-identical
    parity) were fixed by resolutions R1–R6, which are part of the
    consolidated origin input itself (same date), not later drift.

Verdict: aligned
Confidence: medium

Note: confidence is medium, not high, because the originating session
transcript is auth-gated and was not re-read this session; the verbatim
recorded directive, the origin_claim, and the three related_specs
references were read/verified in full. Scope note: this record scores
spec/plan-vs-origin alignment only. The separately measured
delivered-vs-spec gap on PR #107 (7/30 tasks full, 17 partial, 6
absent; Phases 3/6 deferred by design) is a Definition-of-Done matter
outside this gate.
