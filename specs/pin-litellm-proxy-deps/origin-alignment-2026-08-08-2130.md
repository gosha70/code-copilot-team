# Origin Alignment Check — pin-litellm-proxy-deps

Date: 2026-08-08 21:30
Trigger: plan.md revised after the user's third-round P2 on PR #221; the
previous record (`origin-alignment-2026-08-08-2050.md`) is stale.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/220 — in
  particular "Temporary environments continue to be removed automatically".
- The user's P2: "The online regression's isolation and cleanup are not
  fail-safe. … selects a random port from a fixed `8800–9199` range … Cleanup
  has no trap, ignores the generated `log=` path, and merely records a
  failure if SIGTERM does not stop the proxy … Verify the port is no longer
  reachable rather than equating parent-PID disappearance with 'no leaked
  listener.'"

## Working claim

The online test now: asks the OS for a free port; registers an
`EXIT/INT/TERM` trap before creating the venv or proxy; captures and removes
both `config=` and `log=`; escalates SIGTERM to SIGKILL; and asserts the port
itself is closed rather than inferring it from the parent PID. Process
teardown and venv removal are separate functions, because the test reaps the
proxy mid-run and keeps using the venv afterwards.

## Mismatches

- none against the finding; all four remedies were taken as specified.

Verified rather than reasoned: an interrupted run (`exit 130` immediately
after startup) leaves no process, no config, no log, and a free port.
Online suite 24/24.

Note this finding is about the ACCEPTANCE CRITERION "temporary environments
continue to be removed automatically" — my test was the one leaking, which
is a fair reading of the issue rather than scope creep.

## Verdict

Verdict: aligned
Confidence: high
