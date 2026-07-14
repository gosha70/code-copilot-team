# Spec: auto-build-loop driver core (advisory profile)

Increment B (#69) of the auto-build-loop series. Design reference:
specs/auto-build-loop/design.md. Terminology: "driver" =
scripts/auto-build-loop.sh; "ledger" = .cct/auto-build/<feature-id>/state.json.

## User Scenarios

- US1: As a project owner with an approved SDD spec, I run
  `scripts/auto-build-loop.sh <feature-id>` and the driver refuses to start
  unless every preflight gate passes (spec approved, origin aligned, provider
  healthy, clean worktree, not on the default branch), so an unattended run
  can never begin from an unsafe state.
- US2: As a project owner, the driver builds my feature phase-by-phase from
  tasks.md — each phase a fresh headless Claude session, tests run by the
  driver, changes committed by the driver on an isolated feature branch —
  and I can watch progress in the ledger and events journal.
- US3: As a project owner, every phase is peer-reviewed by a cross-vendor
  reviewer over the whole phase diff, findings are fixed and re-reviewed
  automatically, and the phase cannot complete without a verified PASS with
  zero open blocking findings.
- US4: As a project owner, the loop pauses at milestones for my batched
  manual testing/retro sign-off, parks fail-closed on any breaker or cap, and
  never pushes anything anywhere (advisory profile).
- US5: As a future maintainer, the protocol is documented as a skill, the
  gate mapping is explicit in phase-workflow, and /auto-build scaffolds the
  config so any session can set up a run.

## Requirements

Driver CLI + preflight (US1):
- FR-1: CLI `auto-build-loop.sh <feature-id> [--profile advisory] [--config
  <path>] [--resume] [--dry-run] [--max-phases N] [--start-phase N]`; exit
  codes 0=done, 3=milestone-paused, 4=escalated/parked, 1=usage/preflight.
  Profiles other than `advisory` MUST be rejected in this increment with a
  pointer to the later increments.
- FR-2: Preflight MUST verify, in order: jq/git/claude available
  (CCT_CLAUDE_BIN override); specs/<id>/plan.md frontmatter `status:
  approved`; `validate-spec.sh --feature-id <id>` passes; no unresolved
  [NEEDS CLARIFICATION] markers; `check-origin-alignment.sh <id>` exit <= 1
  (>= 2 parks with reason origin_gate, never auto-resolved); targeted
  provider health (FR-2a); clean worktree; then branch setup in this order:
  resolve the base branch/ref from config `branch.base` → create or checkout
  the configured feature branch (`branch.name`, default `feature/<id>`) →
  after branch setup, refuse to run any build session or commit if the
  current branch is still master/main. Starting from a clean default branch
  is a normal, supported entry state.
- FR-2a: Provider health MUST be targeted: validate only the selected gating
  reviewer and its fallback chain — via a new `providers-health.sh
  --provider <name>` mode (checks that provider plus its
  `fallback_chain.<subject>` entries only). An unhealthy provider unrelated
  to the gating reviewer MUST NOT block the driver.
- FR-3: On start, the driver MUST snapshot the config to
  config.snapshot.json and initialize the ledger with schema_version,
  profile, branch, branch_base_ref, caps, and status transitions journaled
  to events.jsonl (append-only).

Phase loop (US2):
- FR-4: Phases MUST be enumerated from `## US<n>:` groups in
  specs/<id>/tasks.md; `phases` array in automation.json overrides;
  missing tasks.md with no override is a preflight failure.
- FR-5: Each phase MUST run a fresh `claude -p` session with
  --output-format json, --permission-mode acceptEdits, --max-turns from
  config, and CCT_PEER_REVIEW_ENABLED=false in its environment; the composed
  phase prompt MUST scope work to the phase's US group + spec FRs and forbid
  the session from committing.
- FR-6: The driver MUST parse the result JSON: subtype success continues;
  error_max_turns gets exactly one --resume <session_id> continuation, then
  parks (build_session_error); total_cost_usd MUST be accumulated and the
  cost cap checked before every session start, along with wall-clock.
- FR-7: The driver MUST run config test.command after each build/fix
  session; on failure run a fix session (findings = failing output tail),
  bounded by build.max_fix_sessions_per_phase, then park (test_failure).
- FR-8: The driver (not the session) MUST commit phase work:
  `feat(<id>): phase <N> — <title> [auto-build]`; an empty diff after a
  build session parks (git_anomaly). Commits on master/main MUST be refused.

Review integration (US3):
- FR-9: Per phase, the driver MUST initialize .cct/review/state.json
  (phase=build, feature_id, subject_provider=claude, peer_provider=gating
  reviewer) and invoke review-round-runner.sh with
  CCT_REVIEW_BASE_REF=<phase_base_ref> so the whole phase diff (build + fix
  commits) is reviewed.
- FR-10: On runner exit 1 (FAIL) the driver MUST run a fix session with the
  findings + disposition contract, commit the fixes, inject the commit sha as
  commit_ref into every `fixed` disposition in resolution-round-N.json, and
  re-invoke the runner — bounded by max_fix_sessions_per_phase and
  CCT_REVIEW_MAX_ROUNDS. On exit 2 (BREAKER) the driver parks
  (review_breaker, detail from breaker-tripped.json).
- FR-11: On runner exit 0 the driver MUST independently verify
  loop-summary.json verdict == PASS, bypass == false, and the collaboration
  artifact's blocking_findings_open == 0 — any mismatch parks. The
  .cct/review/ dir MUST then be archived to the phase dir and removed so the
  next phase starts a fresh loop.
- FR-12: v1 reviewer selection: the first reviewer with gating=true in
  automation.json review.reviewers; the reviewers key MUST be a list
  (specialization/scope/gating fields) even with one entry.

Gates, milestones, parking (US4):
- FR-13: After review PASS, the driver MUST re-run check-origin-alignment.sh;
  exit >= 2 or 4 (stale) parks (origin_gate). Then commit the collaboration
  artifact + an automation-summary.md update
  (`docs(<id>): phase <N> review artifact [auto-build]`).
- FR-14: At milestone boundaries (config milestone_every, default 2, or an
  explicit `<!-- milestone -->` marker in tasks.md) the driver MUST write a
  milestone checkpoint (batched manual-testing checklist + retro stub) into
  specs/<id>/automation-summary.md, set status milestone-paused, and exit 3.
  `--resume` after a human `approved-by:` line in the checkpoint continues;
  resume without it MUST print what is missing and exit non-zero.
- FR-15: Every park MUST write escalations/esc-<n>.json (reason, phase,
  history file refs) before exit 4; there is no proceed-anyway code path. The
  advisory profile MUST NOT push, create PRs, or invoke gh anywhere.
- FR-16: --dry-run MUST print the planned phase/transition sequence and
  create no commits, sessions, or ledger writes.

Tests + docs (US5):
- FR-17: tests/test-auto-build-loop.sh MUST cover, with mock claude
  (CCT_CLAUDE_BIN) and mock reviewer (CCT_PROVIDER_PROFILE): 2-phase advisory
  happy path (transitions journaled, per-phase commits, review archived,
  summary written); FAIL→fix→PASS with commit_ref injection; review breaker →
  exit 4 + escalation record; origin partial → park; caps (max phases, fix
  sessions, cost); dirty-worktree preflight rejection; profile != advisory
  rejected; --dry-run zero side effects; milestone pause + sign-off resume;
  resume idempotency after kill-post-commit (no duplicate commit). Suite
  registered in tests/test-counts.env and added to sync-check.yml (run step +
  bash -n).
- FR-18: shared/skills/auto-build-loop/SKILL.md documents protocol, gate
  map, ledger schema, resume playbook, config schema, safety rails;
  phase-workflow SKILL.md gains the Autonomy Profiles gate-mapping section;
  agent-team-protocol and review-loop skills gain driver-as-submitter notes;
  adapters regenerated via generate.sh with zero drift in CI.
- FR-19: /auto-build command (adapters/claude-code/.claude/commands/
  auto-build.md) validates plan approval + origin, scaffolds automation.json
  from the template, prints the driver command, and never runs the driver
  in-session.

## Constraints

- Bash 3.2 compatible (no associative arrays); jq for all JSON.
- No changes to origin-confirmation semantics; the driver never authors
  origin-divergence.md or alignment records.
- Sessions run with acceptEdits (never bypassPermissions) so PreToolUse
  protect hooks stay active.
- No gh/push/PR/notification code in this increment (#70/#71 scope).
- All durable cross-session state file-backed (wiki:
  cross-session-state-must-be-file-backed); nothing under .cct/ committed.
- One issue per PR: this bundle covers exactly #69.
- CI runs no real claude and no network: all suite coverage via mocks.
