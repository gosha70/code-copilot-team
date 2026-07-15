---
applyTo: "**"
---


# Auto-Build Loop (Autonomous Build After Spec Approval)

Once a feature's SDD bundle is approved, `scripts/auto-build-loop.sh` runs the
build loop unattended. The driver lives OUTSIDE any copilot session (the phase
workflow mandates a fresh session per phase): it starts headless build
sessions, runs tests, commits, submits each phase to cross-provider review,
re-checks origin alignment, and pauses for humans only at milestones or
breakers. Design: `specs/auto-build-loop/design.md`.

## Autonomy Profiles (explicit opt-in — no silent gate bypass)

| Gate (phase-workflow step) | advisory | pr | merge |
|---|---|---|---|
| Manual testing (6) | deferred to milestone checkpoint | deferred to milestone | deferred to milestone |
| Commit gate (8) | auto-commit, local only, isolated branch | auto-commit | auto-commit |
| Wait-for-approval (9) | auto-advance; hard pause at milestones | same | same |
| Origin gate exit >= 2 (10) | **always escalate to human** | **always escalate** | **always escalate** |
| Peer review (11) | driver-run, gating, driver verifies PASS | same | same + green CI |
| Push / PR / merge | never / never / never | auto / auto / never | auto / auto / gated auto |

All three profiles — `advisory`, `pr`, and `merge` — are implemented.

### `merge` profile specifics

`merge` does everything `pr` does, then arms a **gated, GitHub-native**
auto-merge at finalize (the driver never merges locally):

- `merge.enabled` (default **false**) is the final switch. When false, `merge`
  behaves exactly like `pr` — the PR is opened, nothing is merged.
- With `enabled: true` and `merge.require_branch_protection` (default true),
  the driver verifies the base branch is protected
  (`gh api repos/{owner}/{repo}/branches/{base}/protection`) and parks
  (`merge_blocked`) if it is not.
- It then runs `gh pr merge <n> --auto --<merge.method>` (default `squash`);
  GitHub performs the merge only once the branch-protection required checks
  pass — so `merge.require_green_ci` is delegated to GitHub's own rules. The
  driver never polls CI and never force-merges.
- The arm is idempotent (ledger `pr.auto_merge_armed`, else `gh pr view
  --json autoMergeRequest`); resume never re-arms. A `merge_blocked` park
  resolves once branch protection exists (or `merge.enabled` is flipped).

### `pr` profile specifics

- **`gh` preflight**: `gh auth status` (via `$CCT_GH_BIN`, default `gh`) must
  succeed — checked only when the profile can push. `advisory` never invokes
  `gh`.
- **Branch push**: after each phase gate the driver runs a plain
  `git push -u <branch.remote> <branch>` (no `--force` code path anywhere),
  refusing to push `master`/`main` or the base branch — so milestone pauses
  are inspectable remotely.
- **PR create/update**: at finalize the driver composes a deterministic PR
  body, runs `pre-pr-check.sh` (close-keyword + body/title audit), then
  `gh pr create` exactly once — recording `pr.number`/`pr.url` in the ledger.
  Re-runs and `--resume` detect the existing PR (ledger, else
  `gh pr view <branch>`) and `gh pr edit --body-file` instead of duplicating.
  The driver never merges.
- **Close target**: the PR title's `(Closes #N)` marker comes from config
  `pr.closes` (a list), else the spec's `origin:` issue number; missing →
  parks `pr_config`. Optional `pr.title` overrides the title prefix.
- **WIP-push-on-escalation**: parking under `pr`/`merge` pushes the feature
  branch (best-effort — a push failure is journaled and never blocks the
  park); `advisory` parks locally only.

## Invocation

```bash
scripts/auto-build-loop.sh <feature-id> \
    [--profile advisory|pr] [--config <path>] \
    [--resume] [--dry-run] [--max-phases N] [--start-phase N]
# Exit: 0 done | 3 milestone-paused | 4 escalated/parked | 1 usage/preflight
```

Config lives at `specs/<feature-id>/automation.json` (template:
`shared/templates/sdd/automation-template.json`; scaffold with `/auto-build`).
Reviewers are a list with `specialization`, `scope`, and `gating` fields,
resolved through `~/.code-copilot-team/providers.toml`. The panel is **one
gating reviewer + N advisory (non-gating) reviewers**:

- The single `gating: true` reviewer drives the review round loop and decides
  PASS/FAIL/breaker (exactly one gating reviewer is allowed; more is an error).
- Each `gating: false` reviewer runs per phase as **advisory** — in an
  isolated review dir (via `CCT_REVIEW_DIR`/`CCT_REVIEW_COLLAB_DIR`, so the
  gating state is never touched). Its findings are folded into the fix-session
  prompt (tagged by specialization) but never block PASS or trigger a round.
- Preflight health-checks the whole panel: the gating reviewer down parks the
  run; an advisory reviewer down is a warning and that lens is skipped.
- Advisory reviewers are consulted only when a gating FAIL triggers a fix; a
  clean gating PASS ends the phase. All reviewer outputs are archived per
  phase (`phase-N/review/` gating, `phase-N/review-advisory/<provider>/`).

## The loop, per phase

1. **Preflight** (first run): plan.md `status: approved`, `validate-spec.sh`
   passes, origin gate exit <= 1, targeted provider health
   (`providers-health.sh --provider <gating-reviewer>`), clean worktree, then
   base-ref resolve → feature-branch create/checkout → refuse to proceed on
   `master`/`main`.
2. **Build**: fresh `claude -p` session scoped to one `## US<n>:` group from
   tasks.md (`--permission-mode acceptEdits`, `CCT_PEER_REVIEW_ENABLED=false`
   — the driver owns the review gate). One `--resume` continuation on
   `error_max_turns`, then park.
3. **Test**: driver runs `test.command`; failures get bounded fix sessions
   (`build.max_fix_sessions_per_phase`), then park.
4. **Commit**: the DRIVER commits (`feat(<id>): phase N — <title>
   [auto-build]`); sessions never commit. Empty diff parks (`git_anomaly`).
5. **Review**: driver initializes `.cct/review/state.json` and invokes
   `review-round-runner.sh` with `CCT_REVIEW_BASE_REF=<phase-base>` so the
   whole phase diff is reviewed. FAIL → fix session + driver commit +
   `commit_ref` injection into `fixed` dispositions → re-review. BREAKER →
   park. PASS → driver hard gate (verdict PASS, no un-approved bypass,
   `blocking_findings_open: 0`), archive `.cct/review/` into the ledger.
6. **Phase gate**: origin re-check (exit >= 2 or stale → park), commit the
   collaboration artifact + `automation-summary.md` update.
7. **Milestone** (every `milestone_every` phases or `<!-- milestone -->`
   marker in tasks.md): write a checkpoint into `automation-summary.md`,
   exit 3. Resume requires an `approved-by:` line under the checkpoint —
   the driver commits that sign-off itself on `--resume`.

## Ledger (file-backed, machine-local)

`.cct/auto-build/<feature-id>/` — `state.json` (single source of truth:
status, per-phase commits/reviews, caps, totals), `events.jsonl` (append-only
transitions), `config.snapshot.json`, `phase-N/` artifacts (prompts, raw
result JSON, test logs, archived review), `escalations/esc-<n>.json`.
Durable human-facing output goes to `specs/<feature-id>/automation-summary.md`
and `specs/<feature-id>/collaboration/` (committed).

## Notification

`notify.command` (config; `CCT_AUTOBUILD_NOTIFY_CMD` overrides) fires on every
park, milestone pause, and run completion with placeholders `{feature_id}
{reason} {phase} {status} {summary}`. Values are substituted as quoted
env-var references — they never enter the command string, so spaces/quotes
cannot inject shell syntax. Notification failure is journaled
(`notify_failed`) and never blocks parking; the ledger is the durable record.

## Escalation & resume playbook

Every breaker parks fail-closed (exit 4) with an escalation record naming the
reason. There is no proceed-anyway path and no bypass flag: `--resume`
re-derives resolution from human-produced artifacts, per reason:

| Reason | Human action | `--resume` detects |
|---|---|---|
| `review_breaker` | `/review-decide approve\|reject\|retry` in a session (works for runner breakers AND driver fix-exhaustion — the driver writes `breaker-tripped.json` for its own breakers) | `decision.json`: approve → single-use, phase-scoped bypass accepted by the PASS gate; reject → run `aborted`; retry → review loop re-entered on the live state (attempt/round numbering preserved) |
| `origin_gate` | rescope / restart / document divergence — the driver NEVER picks for you | `check-origin-alignment.sh` exit <= 1 (fresh aligned record or committed `origin-divergence.md`) |
| `test_failure` / `build_session_error` / `git_anomaly` | fix manually, commit | clean worktree AND `test.command` green |
| `provider_unavailable` | fix providers.toml or the provider service | targeted health (`--provider` chain) passes |
| `cap_exceeded` | raise `caps.*` / `phases.max_phases` in `automation.json` | refreshed caps no longer exceeded (wall-clock guard restarts on resume) |

Unresolved: `--resume` prints exactly what is still needed and exits 1 with
no side effects. On resolution the escalation is marked `resolved`, journaled,
and a `resumed` notification fires. `review_breaker` parking leaves
`.cct/review/` in place — `/review-decide` operates on that live state.

**milestone-paused** (exit 3, not an escalation): manual-test + retro, add
`approved-by: <name> <date>` under the checkpoint, rerun with `--resume`
(the driver commits the sign-off itself).

## Safety rails (hard-coded)

Default-on caps (max phases 8, review rounds 5, fix sessions 3/phase,
wall-clock 4h, cost $25); `advisory` cannot push even on escalation; no
`--force` code path; commits refused on `master`/`main` and pushes refused
to `master`/`main`/the base branch; sessions run with
`acceptEdits` so PreToolUse protect hooks stay active; origin escalations are
clearable only by human-authored artifacts.
