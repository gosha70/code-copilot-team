# Origin alignment check — auto-build-branded-launcher

- date: 2026-08-08
- trigger: initial gate for the #195 bugfix SDD. Origin source read in
  full this session: issue #195 body (summary, expected/actual, impact,
  root cause, proposed fix parts 1-3, acceptance criteria).

## Origin claim (from plan.md `origin:`)

The driver invokes generic `claude` instead of the branded
`claude-code` (PI already uses `pi-code`); fix = driver default
`claude-code`, launcher headless passthrough (no cmux/tmux, no
path-consumption of -p, config parity), and a branded autonomous entry
(`claude-code build`) so no-human-in-loop never reaches
`--dangerously-skip-permissions`. pi-code unchanged.

## Working claim (from spec.md)

FR-1..FR-5 implement exactly those three parts plus the acceptance
criteria (verifiable headless invocation via claude-code, documented
headless mode, config inheritance, pi-code untouched, branded
autonomous trigger).

## Mismatches

none — scope is the issue's own proposed fix; the "Symmetrically for
pi-code" aside in part 3 is not in the acceptance criteria (which pin
"pi-code behavior is unchanged") and is left to a follow-up if wanted.

Verdict: aligned
Confidence: high
