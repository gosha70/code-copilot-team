# Origin alignment check — auto-build-hill-chart (planning bundle)

Date: 2026-11-11 13:00 EST

Origin sources: issue #405 (body as of 2026-11-11, no comments) and the
repository at `a63bf6d`, recorded in
`origin/2026-11-11-issue-405-origin.md`.

## Issue → bundle

| Issue | Bundle |
|---|---|
| Driver never moves hill-chart scopes; cycles reach `/cooldown` all `uphill` | spec.md § Why; FR-2, FR-5, FR-7 |
| Suggested form 1: map each `## US<n>:` phase to a scope "in `automation.json` (or read the mapping from the pitch)" and set the scope `done` when its phase lands | FR-3 reads the mapping from the pitch's phase titles; FR-5/FR-6 set `done` at landing (D1, D3) |
| Suggested form 2: `/cooldown` states that driver-built cycles set all scopes at close, recorded in the bet log | not chosen (D2); the chart must not claim verification that did not happen; `/cooldown`'s existing question handles partial cycles |
| Evidence: wiki-studio cycles 03/04 set `done` by hand | FR-7 summary line and `hill_final` make the final state visible |

## Deviations within intent

- The mapping source is the pitch, not `automation.json`; the issue
  offers both. No config key is added.
- `downhill` at phase start is added beyond the issue's `done` at
  landing, so the chart shows live progress; it costs nothing and
  rides the build commit.
- The driver marks `done`, which the `scope-executor` text reserves to
  `/hill`; the driver's own gates are the verification, and the docs
  say so (D5).

## Open decisions

D1–D5 are proposed with recommendations and marked
`[NEEDS CLARIFICATION]` in spec.md. Build does not start until ruled.

Verdict: aligned
Confidence: high
