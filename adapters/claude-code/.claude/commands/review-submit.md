Submit work for peer review. Validates clean worktree, initializes or continues the review loop, invokes review-round-runner.sh, and returns the verdict.

## Prerequisites

- `CCT_PEER_REVIEW_ENABLED` must be `true` (set by `--peer-review` launcher flag)
- Working tree must have no uncommitted changes (except `.cct/` review state)
- `jq` must be installed

## Steps

### 1. Validate Environment

Check that peer review is enabled:
- If `CCT_PEER_REVIEW_ENABLED` is not `true`, inform the user and stop.

### 2. Validate Clean Worktree

Run `git status --porcelain` and check for uncommitted changes (excluding `.cct/`):
- If dirty, tell the user: "Commit or stash your changes before submitting for review."
- Do not proceed until the worktree is clean.

### 3. Check for Active Breaker

If `.cct/review/breaker-tripped.json` exists:
- Read and display the breaker context to the user.
- Tell the user: "A circuit breaker has fired. Run `/review-decide approve|reject|retry` to proceed."
- Do not invoke the runner. Stop here.

### 4. Initialize or Continue State

If `.cct/review/state.json` does not exist, create it:

```json
{
  "current_round": 0,
  "attempt": 1,
  "loop_start": <current-unix-timestamp>,
  "feature_id": "<from specs/*/plan.md or ask user>",
  "phase": "<plan|build — infer from current agent or ask>",
  "subject_provider": "claude",
  "peer_provider": "<from CCT_PEER_PROVIDER env or empty for profile default>",
  "review_scope": "<from CCT_PEER_REVIEW_SCOPE env or 'both'>",
  "target_ref": "<current git branch or HEAD>",
  "last_verdict": null,
  "findings": {}
}
```

If `state.json` already exists, the runner will read it and continue from the current round.

### 5. Invoke the Runner

Run `review-round-runner.sh <project-dir>` as a synchronous subprocess.

The runner exits with:
- **0** = PASS — review passed. Read `.cct/review/loop-summary.json` and inform the user. Proceed to `/phase-complete`.
- **1** = FAIL — review failed. Read `.cct/review/findings-round-N.json` (where N is the current round from `state.json`). Present each finding to the user. For blocking findings, address them (fix, dispute, defer, or mark not-applicable), write `.cct/review/resolution-round-N.json`, commit fixes, then run `/review-submit` again.
- **2** = BREAKER — circuit breaker tripped. Read `.cct/review/breaker-tripped.json` and present the context. Tell the user to run `/review-decide approve|reject|retry`. Stop and wait.

### 6. On FAIL — Address Findings

Read `findings-round-N.json` and for each blocking finding:
1. Assess whether it is valid
2. If valid: fix the code
3. If invalid: prepare a dispute with explanation

Then write `.cct/review/resolution-round-N.json`:

```json
{
  "round": N,
  "resolutions": [
    {
      "finding_id": "f-xxxxxxxx",
      "disposition": "fixed|disputed|deferred|not-applicable",
      "detail": "<explanation>",
      "commit_ref": "<sha — required for 'fixed' disposition>"
    }
  ]
}
```

Commit the fixes, then run `/review-submit` again for the next round.

### 7. On PASS — Proceed

Inform the user:
- Review passed after N rounds
- `loop-summary.json` written
- Collaboration artifact written to `specs/<feature-id>/collaboration/`
- Proceed to `/phase-complete`

### Plan-Phase Behavior

For plan-phase review (`phase: plan`):
- Run exactly one round (advisory only)
- A FAIL verdict is logged but does **not** trigger a fix loop
- Write the result as `plan-consult.md` artifact
- Proceed regardless of verdict — this is a product decision, not a missing feature
