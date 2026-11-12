# Origin alignment check — auto-build-hill-chart (approved bundle)

Date: 2026-11-11 23:30 EST

Supersedes the 13:00 record. The owner ruled D1–D5 on 2026-11-11: D1
explicit `(S<n>)` tokens with preflight refusal on a gap (the phase-to-
scope dependency is a planning fact the SDD must state, never inferred
by the driver); D2 unmapped scopes untouched and reported; D3 `done`
after the coverage gate; D4 a failed hill commit is retried once, then
journaled; D5 the driver's gates are the verification that lets it mark
`done`.

Origin sources: issue #405 (body as of 2026-11-11, no comments) and the
repository at `a63bf6d`, recorded in
`origin/2026-11-11-issue-405-origin.md`.

## Issue → bundle

| Issue | Bundle |
|---|---|
| Driver never moves hill-chart scopes; cycles reach `/cooldown` all `uphill` | spec.md § Why; FR-2, FR-5, FR-7 |
| Form 1: map each `## US<n>:` phase to a scope "in `automation.json` (or read the mapping from the pitch)" and set the scope `done` when its phase lands | FR-3 reads the mapping from the pitch's phase titles; FR-4 refuses a run whose mapping is incomplete; FR-5/FR-6 set `done` at landing (D1, D3, D5) |
| Form 2: `/cooldown` states driver-built cycles set all scopes at close, recorded in the bet log | not chosen (D2) |
| Evidence: wiki-studio cycles 03/04 set `done` by hand | FR-7 summary line and `hill_final` |

## Deviations within intent

- Mapping source is the pitch, not `automation.json`; the issue offers
  both. A gap stops the run at preflight, which is stricter than the
  issue asks and follows the owner's rule that dependencies are stated
  in the SDD or confirmed with the developer.
- `downhill` at phase start is added beyond the issue's `done` at
  landing; it rides the build commit.
- The driver marks `done`; the docs say the driver's gates are the
  verification (D5).

Verdict: aligned
Confidence: high
