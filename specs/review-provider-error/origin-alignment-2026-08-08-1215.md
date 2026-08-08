# Origin Alignment Check — review-provider-error

Date: 2026-08-08 12:15
Trigger: plan.md and spec.md revised after the user's P1/P2 on PR #206;
the previous record (`origin-alignment-2026-08-08-1140.md`) is stale.

## Origin sources read

- Issue: https://github.com/gosha70/code-copilot-team/issues/204.
- The user's P1/P2 review of PR #206, reproduced locally by them with
  `command = "exit 1"` and `command = "exit 124"`.

## Origin claim (the user's P1, verbatim)

> Empty provider output still exits through the old `FAIL` path. …
> `PROVIDER_ERROR=$(printf ... | grep -v ... | head -1 | cut ...)` runs
> under `set -euo pipefail`. If the reviewer exits non-zero with no
> stdout/stderr, `grep` returns 1, the assignment aborts the script, and
> the later `"no output"` fallback is never reached. … That reopens the
> bug class for quiet infrastructure failures.

And P2:

> Timeout provider errors don't write the artifact the driver expects. …
> the new driver arm reads provider, exit code, and message from
> `post_frf` … the diagnostic becomes `reviewer '?' failed (exit ?) ...
> unknown error`, contrary to the PR's stated "naming provider, exit
> code, and error" contract.

## Working claim

The error extraction can no longer abort the runner (`|| true`, with the
`no output` fallback now reachable), and every provider-failure path —
non-zero exit, silent failure, timeout — writes `findings-round-N.json`
before exiting 3, so the driver's park names the provider, its exit code
and its cause.

## Mismatches

- none against the findings.

Both were defects in this change's own first cut, not in the origin
issue. Twelve regressions now pin them, all verified to fail against
`15f9c8c`: the driver reproduction shows `no fix session runs on a silent
failure (expected '0', got '2')`, i.e. P1 left #204's reported symptom
fully reachable, and `the park names the provider, not '?' (expected
'0', got '1')` for P2.

Note for future work: P1 is the same `set -o pipefail` + non-matching
`grep` trap fixed two commits earlier in this same file for the
verdict-anchor lookup. The first fix was applied locally instead of being
generalised. Any `$(... | grep ... | ...)` assignment in these runners
needs `|| true` unless a no-match is genuinely fatal.

## Verdict

Verdict: aligned
Confidence: high
