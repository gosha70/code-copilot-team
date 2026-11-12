# Origin alignment check — auto-build-hill-chart (after the build)

Date: 2026-11-11 23:59 EST

Supersedes the 23:30 record. The build is complete on
`feat/405-auto-build-hill-chart`; two details learned while building
are recorded in the bundle and change nothing the owner ruled:

- The mapping-gap refusal exits 1, the driver's configuration-refusal
  code (the same as a missing `tasks.md`), where the approved text said
  2 (FR-4, plan interfaces).
- The review-round runner built its collaboration path from the bare
  feature id, which created a stray `specs/<id>/` beside a pitch and
  made the origin gate fail at the first phase gate. The runner now
  resolves `specs/pitches/<id>` the same way, and the driver passes it
  the resolved collaboration directory (FR-1).

Origin sources: issue #405 (body as of 2026-11-11, no comments) and the
repository at `a63bf6d`, recorded in
`origin/2026-11-11-issue-405-origin.md`.

## Issue → bundle → build

| Issue | Bundle | Built |
|---|---|---|
| Driver never moves hill-chart scopes | FR-2, FR-5, FR-7 | `hill_phase_start`, `hill_phase_landed`, `hill_final`; suite: full run ends `S1=done S2=done S3=uphill` |
| Form 1: map each phase to a scope, read from the pitch; `done` when the phase lands | FR-3, FR-4, FR-5, FR-6 (D1, D3, D5) | `(S<n>)` tokens; preflight refusal; `done` after the coverage gate; scoped commit retried once |
| Form 2: `/cooldown` sets all scopes at close | not chosen (D2) | unmapped scope stays `uphill`, reported |
| Evidence: cycles 03/04 set `done` by hand | FR-7 | summary `Hill chart:` line, `hill_final` event |

## Deviations within intent

- Mapping source is the pitch, with preflight refusal on a gap (D1).
- `downhill` at phase start, riding the build commit.
- The driver marks `done`; docs say the driver's gates are the
  verification (D5).
- A failed hill commit is retried once, then journaled (D4).

Verdict: aligned
Confidence: high
