# Review Loop Protocol

Agent-driven peer review loop for Build and Plan phases. The Build agent drives the loop; the reviewer is a separate, read-only LLM.

## Loop Architecture

The review loop is **agent-driven**: the Build agent calls `/review-submit`, which invokes `review-round-runner.sh` as a synchronous subprocess. The runner executes one round and returns. The agent reads the result and decides the next action. There is no long-running orchestrator.

```
Agent completes work → /review-submit → review-round-runner.sh (one round)
                                              ↓
                         EXIT 0 (PASS) → loop-summary.json → /phase-complete
                         EXIT 1 (FAIL) → findings-round-N.json → agent fixes → /review-submit
                         EXIT 2 (BREAKER) → breaker-tripped.json → agent stops → /review-decide
```

## File Contract

All review-loop artifacts live under `.cct/review/` during the active loop.

| File | Written By | Purpose |
|------|-----------|---------|
| `state.json` | `/review-submit` (init), runner (update) | Loop state: round, attempt, findings, breaker counters |
| `findings-round-N.json` | Runner | Structured findings for round N |
| `resolution-round-N.json` | Build agent | Builder's response to each finding |
| `breaker-tripped.json` | Runner | Breaker context, awaiting `/review-decide` |
| `decision.json` | `/review-decide` | Human's decision: approve, reject, or retry |
| `loop-summary.json` | Runner (PASS) or agent (bypass) | Final record of all rounds |

On loop completion, the completing actor copies `loop-summary.json` and writes a `build-review.md` artifact to `specs/<feature-id>/collaboration/`.

## Finding Schema

Each finding has a stable ID computed from `SHA-256(file + category + normalized_description)` truncated to 8 hex chars, prefixed with `f-`. Line numbers are excluded from the ID to remain stable across edits.

```json
{
  "id": "f-a1b2c3d4",
  "severity": "blocking|warning|note",
  "category": "correctness|security|style|performance|design|testing|documentation",
  "file": "path/relative/to/project",
  "line_hint": "semantic anchor (display only)",
  "description": "clear description",
  "suggested_fix": "actionable fix",
  "first_seen_round": 1,
  "disposition": null
}
```

### Severity Levels

| Severity | Blocks PASS? | Builder must respond? |
|----------|-------------|----------------------|
| `blocking` | Yes | Yes — must set disposition |
| `warning` | No | Optional |
| `note` | No | No — informational |

## Disposition Values

The builder responds to each blocking finding with a disposition in `resolution-round-N.json`:

| Disposition | Meaning | Required fields |
|-------------|---------|----------------|
| `fixed` | Builder addressed the finding | `commit_ref` (SHA of fix commit) |
| `disputed` | Builder disagrees | `detail` (explanation) |
| `deferred` | Acknowledged, fix later | `detail` (optional) |
| `not-applicable` | Finding doesn't apply | `detail` (optional) |

## Circuit Breakers

All breakers escalate to human — there is no path to automatic acceptance of unresolved work.

| Breaker | Default | Env Var | Behavior |
|---------|---------|---------|----------|
| Max rounds | 5 | `CCT_REVIEW_MAX_ROUNDS` | Escalate to `/review-decide` |
| Wall-clock timeout | 900s | `CCT_REVIEW_TIMEOUT_SEC` | Escalate to `/review-decide` |
| Stale findings | 2 consecutive | `CCT_REVIEW_STALE_THRESHOLD` | Escalate to `/review-decide` |
| Provider unavailable | — | — | Escalate to `/review-decide` |

A **stale finding** is one that appears in N consecutive rounds with disposition `fixed` each time (builder thinks they fixed it, reviewer disagrees). Stale findings remain blocking — they do not auto-downgrade.

## Human Decision Channel

When a breaker fires, the agent stops and the human runs `/review-decide`:

| Decision | Effect |
|----------|--------|
| `approve` | Agent writes `loop-summary.json` with `bypass: true`. Proceeds to `/phase-complete`. |
| `reject` | Agent logs rejection. No merge. |
| `retry` | Reset breaker state. Round numbering continues monotonically (next round is N+1, not 1). |

## Commit Lifecycle

### Commit-Strategy Modes

| Mode | Flag | Behavior |
|------|------|----------|
| `single` | `--review-commits single` | Amend same commit each round |
| `per-round` | `--review-commits per-round` | New commit per fix round: `fix(review): round N — <summary>` |
| `squash` | `--review-commits squash` (default) | Per-round during loop; `git reset --soft` to pre-review commit on PASS |

### Rules

1. The review system does NOT auto-commit. The Build agent commits following `phase-workflow.md` commit-gate rules.
2. Before each `/review-submit`, the worktree must be clean (all fixes committed).
3. Squash mode presents the final commit for user approval before creating it.
4. If `git reset --soft` fails, fall back to a merge commit — never force-reset or lose work.

## Plan-Phase Review

**Product decision**: Plan review is advisory and single-round.

- Run exactly one `/review-submit` round
- A FAIL verdict is logged but does **not** gate Build entry
- No fix loop, no circuit breakers, no commit strategies
- Artifact written as `plan-consult.md` with `mode: consult`
- Stop hook does not block plan-phase session stop based on review outcome

This is deliberately narrower than Build-phase review. Plan artifacts are already approved by the human via the Plan Approval Gate before Build begins.

## Read-Only Enforcement

The reviewer runs in a snapshot copy of the working tree:
- Working directory: `cp -R` to temp dir
- No `.git` directory (reviewer cannot create commits)
- `SSH_AUTH_SOCK` and `GPG_AGENT_INFO` unset
- `CCT_READ_ONLY=true` set in environment
- Post-review validation: runner compares real repo HEAD and status before/after. If changed, round is marked INVALID and findings are discarded.
