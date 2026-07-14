---
spec_mode: full
feature_id: auto-build-loop-driver
risk_category: integration
justification: |
  New ~600-800 line orchestrator script driving headless Claude sessions,
  git commits, and the review runner; a new config schema + template; a new
  skill + slash command; skill-text changes that regenerate adapters; a new
  test suite wired into CI. No push/PR capability in this increment (advisory
  profile only), but the driver auto-commits on an isolated branch — a policy
  change to the repo's commit gate, explicitly opt-in. Full design:
  specs/auto-build-loop/design.md (user-approved 2026-07-13).
status: approved
date: 2026-07-13
issue: 69
origin:
  issue: gosha70/code-copilot-team#69
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/69
  origin_claim: |
    Issue #69 (increment B of the auto-build-loop series): deliver
    scripts/auto-build-loop.sh — a Bash 3.2 + jq driver that, given an
    approved SDD spec, runs the build loop unattended under the ADVISORY
    profile only: preflight gates (spec approved, origin aligned, providers
    healthy, clean worktree, isolated feature branch), phase enumeration from
    tasks.md US-groups, per-phase headless claude -p build sessions
    (acceptEdits, CCT_PEER_REVIEW_ENABLED=false), driver-run tests with
    bounded fix sessions, driver-owned commits, review rounds via
    review-round-runner.sh with CCT_REVIEW_BASE_REF=<phase_base_ref>, a
    driver hard review gate, per-phase origin re-checks (exit >= 2 always
    escalates), milestone pauses, a file-backed ledger under
    .cct/auto-build/<feature-id>/, default-on caps, fail-closed parking on
    any breaker, and --dry-run. Plus: automation.json config + template,
    auto-build-loop skill + phase-workflow autonomy-profiles section +
    adapter regeneration, /auto-build command, tests/test-auto-build-loop.sh
    wired into CI. Advisory never pushes; no gh/PR code in this increment.
---

# Plan: auto-build-loop driver core (advisory profile)

Architecture, state machine, ledger schema, config schema, and safety rails
are specified in `specs/auto-build-loop/design.md` §1-§3 and §6 (user-approved
2026-07-13). This plan binds that design to concrete build tasks; spec.md
carries the testable requirements.

## Deliverables

1. `scripts/auto-build-loop.sh` — the driver (design §2): CLI, preflight,
   phase enumeration, per-phase loop (build session → test → commit → review
   rounds → phase gate), milestone pause, ledger + events journal, escalation
   parking (records + `--resume` for the milestone/sign-off path only; the
   full escalation/notify/resume surface is increment C, #70), `--dry-run`.
2. `shared/templates/sdd/automation-template.json` — config template
   (design §3); consumed as `specs/<feature-id>/automation.json`.
3. `shared/skills/auto-build-loop/SKILL.md` — protocol doc; plus the
   "Autonomy Profiles" gate-mapping section in
   `shared/skills/phase-workflow/SKILL.md` and one-paragraph driver-as-
   submitter notes in `agent-team-protocol` + `review-loop` skills; then
   `scripts/generate.sh` and commit regenerated adapters.
4. `adapters/claude-code/.claude/commands/auto-build.md` — `/auto-build`
   scaffolding command (validates approval + origin, writes automation.json,
   prints the driver invocation; the driver runs OUTSIDE sessions).
5. `tests/test-auto-build-loop.sh` — suite per test-review-loop.sh
   conventions (mock claude via CCT_CLAUDE_BIN, mock reviewer via
   CCT_PROVIDER_PROFILE); registered in tests/test-counts.env; wired into
   .github/workflows/sync-check.yml (run step + bash -n).
6. `adapters/claude-code/.claude/settings.json` — document
   CCT_AUTOBUILD_PROFILE / CCT_AUTOBUILD_NOTIFY_CMD env keys (defaults empty).
7. `scripts/providers-health.sh` — new `--provider <name>` mode (named
   provider + its fallback chain only) so driver preflight is not blocked by
   unrelated unhealthy providers; no-arg behavior unchanged.

## Out of scope (later increments)

- Notification plumbing + full breaker `--resume` resolution detection (#70).
- `pr` profile: push, gh, PR create/update (#71).
- Reviewer panel; `merge` profile (issues to be created when reached).

## Delegation & sequencing

Single PR for #69 (one issue per PR). Build order: T-groups US1 → US5 in
tasks.md; the driver script grows across US1-US4 with the test suite
developed alongside each group, docs/skills last (US5).

## Test strategy

Every driver behavior lands with a same-PR assertion in
tests/test-auto-build-loop.sh (see spec.md FR-14..FR-17). Mocks only — no
real claude/network in CI. End-to-end toy run per design §9 is a manual
verification step before requesting review.
