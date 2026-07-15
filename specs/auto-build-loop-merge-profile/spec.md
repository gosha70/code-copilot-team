# Spec: auto-build-loop `merge` profile — gated auto-merge (increment F)

Issue #80. Base: `pr` profile + reviewer panel merged in #75/#79. Design:
`specs/auto-build-loop/design.md` §F, decision 3, Finalize + Safety rails.
The profile ladder and the `merge{enabled, require_green_ci,
require_branch_protection}` config slots are reserved; this increment unlocks
`merge` as an autonomous, fail-closed, GitHub-native auto-merge.

## User Scenarios

- US1: As a project owner running the `merge` profile with `merge.enabled:
  true` on a branch-protected base, the driver builds → reviews → opens the PR
  and then **arms GitHub auto-merge** — GitHub performs the merge only once the
  branch-protection required checks pass. The driver never merges locally and
  never blocks waiting on CI.
- US2: As a cautious operator, I keep `merge.enabled: false` (the default) so
  the `merge` profile behaves exactly like `pr` — the PR is opened but nothing
  is merged — until I explicitly flip the switch. And if I require branch
  protection but the base branch is unprotected, the driver refuses to arm a
  merge and parks, rather than merging into an unprotected branch.

## Requirements

Gated auto-merge (US1):
- FR-1: Unlock `merge` in the profile ladder (`can_push`/`can_open_pr`/
  `can_merge` all true). `merge` inherits every `pr` behavior (per-phase push,
  PR create/update, WIP-push-on-escalation, panel review) unchanged.
- FR-2: `merge.enabled` (default **false**) is the final switch. When false,
  the `merge` profile behaves exactly like `pr` — opens/updates the PR, arms
  no merge — and the finalize summary/notify says so. Only `enabled: true`
  arms a merge.
- FR-3: When `enabled` and `merge.require_branch_protection` (default true),
  the driver MUST verify the base branch is protected via
  `$CCT_GH_BIN api repos/{owner}/{repo}/branches/{base}/protection` BEFORE
  arming. Required + unprotected → park (`merge_blocked`), never merge.
- FR-4: Arm GitHub-native auto-merge:
  `$CCT_GH_BIN pr merge <n> --auto --<method>` (method from `merge.method`,
  default `squash`). GitHub merges only when the branch-protection required
  checks pass — delegating `merge.require_green_ci` to GitHub's own rules. A
  `gh pr merge` failure parks (`merge_blocked`) with diagnostics. The driver
  NEVER force-merges, NEVER merges locally, and NEVER commits/pushes to the
  base branch (the existing master/base refusals hold).
- FR-5: The ledger records `pr.auto_merge_armed` + `pr.merge_method`. Resume
  detects an already-armed PR (ledger, else `gh pr view <n> --json
  autoMergeRequest`) and does NOT re-arm — `pr merge` runs at most once across
  a resume cycle.

Safety, tests, docs (US2):
- FR-6: `advisory` and `pr` profiles NEVER invoke `gh pr merge`. The merge is
  a GitHub PR operation, never a local merge/commit to the base branch; no
  `--force`/force-merge code path exists.
- FR-7: Tests (`tests/test-auto-build-loop.sh`) via the `gh` argv stub + an
  `api` stub: `pr merge --auto --squash` invoked exactly once when `enabled`
  and the base is protected; NOT invoked when `enabled: false` (behaves as
  `pr`, PR opened, ledger `auto_merge_armed=false`); parked (`merge_blocked`)
  when `require_branch_protection` and the base is unprotected; idempotent on
  resume (no second `pr merge`); `advisory`/`pr` invoke `pr merge` zero times.
  Counts registered in `tests/test-counts.env` + README.
- FR-8: `shared/skills/auto-build-loop/SKILL.md` + the `merge` config block
  docs (template + settings) updated with the merge-profile semantics and
  safety; adapters regenerated with zero drift.

## Constraints

- Bash 3.2 compatible; jq for JSON; no new dependencies.
- Merge is GitHub-native `gh pr merge --auto` only — the driver never merges
  locally, never forces, never commits/pushes to `master`/`main`/the base.
- Fail-closed: `merge.enabled` defaults false; `require_branch_protection`
  defaults true; every gate failure parks (no proceed-anyway path).
- `advisory` and `pr` behavior is byte-for-byte unchanged.
- One issue per PR: this bundle covers exactly #80.
- Linux parity verified in an ubuntu container before review.
