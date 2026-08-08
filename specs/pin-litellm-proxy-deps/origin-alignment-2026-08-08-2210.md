# Origin Alignment Check — pin-litellm-proxy-deps

Date: 2026-08-08 22:10
Trigger: plan.md revised after the user's fourth-round P2 on PR #221; the
previous record (`origin-alignment-2026-08-08-2130.md`) is stale.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/220
  ("Temporary environments continue to be removed automatically").
- The user's P2: "Signal traps clean up but do not stop the test. …
  `proxy_selftest_cleanup` … returns `0`. Bash therefore resumes execution
  after handling the signal … It does not reliably produce the claimed exit
  `130`."

## Working claim

`trap proxy_selftest_cleanup EXIT` plus `trap 'exit 130' INT` and
`trap 'exit 143' TERM`. The EXIT trap still does the reaping; the signal
handlers terminate with the conventional status instead of returning into
the middle of the script.

## Mismatches

- none against the finding.

Reproduced the reported behaviour with a real signal before fixing:

```
OLD (cleanup handles TERM): exit=0
     cleanup / CONTINUED AFTER SIGNAL / cleanup
NEW (exit 143 on TERM):     exit=143
     cleanup
```

Then verified on the real test: SIGTERM sent mid-install exits **143**,
leaving zero `cct-proxydeps-*` venvs and zero stray `litellm --config`
processes.

**Why round 3 missed it.** My "verified by interrupting" probe used an
explicit `exit 130`, which exercises only the EXIT trap — the INT/TERM path
it claimed to prove was never signalled. Two further traps for the record:
bash ignores SIGINT in background (async) commands, so an INT probe from a
test harness silently proves nothing; and a trap does not fire until the
running foreground command (e.g. `sleep 5`) returns, so a probe must use
short-lived commands or it measures normal completion instead.

That is the fourth instance in this arc of a check whose LABEL outran what
it exercised (#212's stub, #220's import-as-startup, round 3's simulated
interrupt, and this one). The rule I am applying from here: a verification
must exercise the same mechanism the claim names — the real signal, the real
adapter, the real process — not a stand-in that merely reaches the same
line.

## Verdict

Verdict: aligned
Confidence: high
