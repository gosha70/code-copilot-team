# Origin Alignment Check — review-provider-error

Date: 2026-08-08 11:40
Trigger: first alignment record for this feature (gate exit 4).

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/204
  (`gh issue view 204` — summary, root cause with line references,
  reproduction, and the real-run evidence: findings-round-1.json with
  `verdict: FAIL`, `findings: []`, and a usage error in `raw_output`).
- The user's instruction: "start fixing the next highest bug".

## Origin claim (verbatim)

> When the reviewer **CLI itself fails to run** (non-zero exit, no review
> performed), `scripts/review-round-runner.sh` reports a normal
> code-review **`FAIL`** instead of surfacing a provider error. The driver
> then treats it as real review feedback: it spawns fix sessions against
> **zero findings**, makes unplanned commits, burns review rounds and
> money, and finally parks with a **misleading** `git_anomaly` reason that
> names nothing about the actual cause.

## Working claim

A non-zero reviewer exit yields INCONCLUSIVE plus a recorded
`provider_error`, and exits 3. The driver parks that as
`provider_unavailable`, naming provider, exit code and message, without
spawning a fix session. A failed invocation is never charged the
conservative estimate. Genuine review failures still exit 1.

## Mismatches

- **The provider-timeout path was also fixed**, though the issue names
  only the non-zero-exit path. Exit 124/143 previously returned 1 and so
  drove the identical wasted-fix-session behaviour; fixing one and
  leaving the other would have left the reported symptom reachable.
- **Spend accounting was included.** The issue's evidence shows
  `cost_review ... $2.0 (estimated: true — unmetered invocation)` for a
  reviewer that never ran. The issue does not ask for this explicitly,
  but "burns … money" is part of its claim and the estimate is the
  mechanism.
- Scope held: no retry logic, no text-based error inference, no change to
  the healthcheck park path, and #205 (the wall-clock defect from the
  same run) is deliberately left for its own change.

## Verdict

Verdict: aligned
Confidence: high
