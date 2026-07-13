# auto-build-loop: Autonomous Build After SDD Spec Confirmation

## Context

Today, everything between "spec approved" and "merged to master" is human-gated by design: manual testing gate, commit gate, wait-for-approval-per-phase (`shared/skills/phase-workflow/SKILL.md`), origin escalation (`shared/skills/origin-confirmation/SKILL.md`), review breakers (`/review-decide`), and manual PR/merge. The goal — matching the agent-loop design in the Claude Agent SDK docs and "loop engineering" practice (goal loops need convergence criteria, caps, and an escalation path) — is a **fully automated build process after spec confirmation**, especially for kick-start projects: build → test → cross-provider review (Codex et al.) → address findings → re-review to PASS → push to PR (or, opt-in later, merge), engaging the human only on unresolvable breakers or at milestone/cool-down checkpoints (where retro + full manual testing are batched).

This is a **policy redesign with explicit opt-in autonomy profiles**, not just a missing orchestrator: the driver never silently bypasses existing human gates — it converts each gate into a configured state transition with escalation rules.

Research based on: https://code.claude.com/docs/en/agent-sdk/agent-loop, "4 Levels of Loop Engineering" (heartbeat/cron/hook/goal loops), Ralph Wiggum loop, Codex CLI structured review (`codex exec --output-schema`), metaswarm escalation patterns (N rounds → human), Claude Code headless mechanics (`claude -p --output-format json`, result subtypes, session resume).

## Confirmed decisions (user, 2026-07-13)

1. **Orchestrator**: bash driver + headless Claude — new `scripts/auto-build-loop.sh`, outside any Claude session (phase-workflow mandates new session per phase); fresh `claude -p` per phase; owns the durable ledger. Agent SDK app may later replace it once the policy contract is proven.
2. **State**: live state in `.cct/auto-build/<feature-id>/` ; durable summaries in `specs/<feature-id>/automation-summary.md` + existing `collaboration/` artifacts. (Wiki: cross-session state must be file-backed.)
3. **Autonomy profiles**: `advisory` (build/test/review, never publish) → `pr` (auto-commit, push branch, open/update PR, never merge) → `merge` (later; branch protection + green CI + explicit config).
   - ⚠️ **Amendment to flag**: user said advisory "stops before commit/push", but the review engine requires committed changes on a clean worktree (`review-round-runner.sh:100-103`, reviews committed diffs). Resolution: **advisory makes local commits on an isolated feature branch and never pushes** — "stop before commit/push" interpreted as "never publish". WIP-push-on-escalation happens only in `pr`/`merge` profiles; advisory parks locally.
4. **Reviewers**: v1 = single cross-vendor gating reviewer (current runner behavior); config declares reviewers as a **list with specializations** (correctness→Codex, security→GPT, style→local Ollama) so a panel lands later without schema change.
5. **Escalation = notify + park + resume**: on breaker or milestone — write escalation record (full failure history) to ledger, pluggable notify command (e.g. Telegram script), halt. Human resolves (`/review-decide`, origin A/B/C, milestone sign-off) → rerun with `--resume`.
6. **Origin gate is non-negotiable**: `check-origin-alignment.sh` exit ≥ 2 always escalates; the driver never authors `origin-divergence.md` or alignment records.

## Verified code facts grounding the design

- Stop hook validates review *completion*, not initiation — exits 0 if review never started (`adapters/claude-code/.claude/hooks/peer-review-on-stop.sh:61-68`) → driver owns a hard "review ran AND PASSed" gate per phase.
- `scripts/validate-collaboration.sh:99` passes a forged `verdict: PASS` with `blocking_findings_open > 0` (runner itself downgrades at :543; CI gap = hand-edited artifacts) → tighten.
- `scripts/review-round-runner.sh` reviews `git diff HEAD~1` truncated at 500 lines (lines 339/344/347) → parameterize base ref + truncation.
- `.cct/` is NOT gitignored (runner only tolerates it *untracked*) → add to `.gitignore`.
- Slash commands are authored directly in `adapters/claude-code/.claude/commands/` (NOT generated from `shared/`); skills in `shared/skills/` are generated into adapters via `scripts/generate.sh` (CI drift check).
- Headless sessions fire the repo's Stop hooks → driver runs build sessions with `CCT_PEER_REVIEW_ENABLED=false` (driver owns the review gate) to avoid stop-hook deadlock.
- Repo tests register expected PASS counts in `tests/test-counts.env` with drift self-check.

## Design

### State machine (ledger: `.cct/auto-build/<feature-id>/state.json`)

```
pending → preflight → per phase N:
  building(N) → testing(N) → committing(N) → in-review(N, round R)
    FAIL → addressing-findings(N) → commit → in-review (next round)
    PASS → phase-gate(N)   # origin re-check + driver hard review gate
  phase-gate → pushing(N) [pr|merge only] → phase-done(N)
  phase-done → milestone-paused (exit 3) → human sign-off → resumed
             → building(N+1) | finalizing
finalizing → pr-open [pr] → done
any state → escalated(reason) → parked (exit 4) → human resolution + --resume → resumed
Terminal: done | parked | aborted
```

Ledger holds: profile, branch + `branch_base_ref`, per-phase `{phase_base_ref, last_reviewed_ref, build_sessions[{session_id, subtype, total_cost_usd}], test_runs, fix_sessions, review{rounds, verdict}, commits}`, caps `{max_phases 8, max_review_rounds 5, max_fix_sessions_per_phase 3, wall_clock 4h, cost_usd 25}`, totals, milestones, escalations[], pr{}. Plus `events.jsonl` (append-only transitions), per-phase artifact dirs (`build-prompt.md`, raw claude JSON results, test logs, archived `.cct/review/`), `escalations/esc-<n>.json` + `-resolution.json`.

**Resume semantics**: write-target-status-then-act; on `--resume` re-derive reality (commit exists? branch pushed? PR open? review archived?) and skip completed side effects. Parked resume requires the matching human artifact (decision.json from `/review-decide`, fresh origin record/divergence, milestone `approved-by` note) — else print what's missing, exit non-zero. Fail-closed everywhere.

### Driver: `scripts/auto-build-loop.sh` (new, Bash 3.2-compatible, jq-based)

```
auto-build-loop.sh <feature-id> [--profile advisory|pr|merge] [--config <path>]
                   [--resume] [--dry-run] [--max-phases N] [--start-phase N]
Exit: 0 done | 3 milestone-paused | 4 escalated | 1 usage/preflight
```
Test knobs: `CCT_CLAUDE_BIN`, `CCT_GH_BIN`, `CCT_AUTOBUILD_DIR`, pass-through `CCT_PROVIDER_PROFILE`, `CCT_REVIEW_*`.

- **Preflight**: jq/git/claude present; `gh auth status` iff ≥ pr; `plan.md status: approved` + `validate-spec.sh` pass + no `[NEEDS CLARIFICATION]`; origin check (≥2 escalates); `providers-health.sh`; clean worktree; create/checkout `feature/<id>` branch (never operate on default branch); snapshot config; init ledger.
- **Phase enumeration**: `## US<n>:` story groups in `specs/<id>/tasks.md` (fallback `### Task N:` in plan.md; overridable `phases` array in config). Milestones every `milestone_every` phases (default 2) or explicit `<!-- milestone -->` marker.
- **Per phase**: compose phase-scoped prompt (spec→PRD bridge from ralph-loop §PRD Source: US stories + FR acceptance checks + plan constraints + "do NOT commit; driver commits") → `claude -p --output-format json --permission-mode acceptEdits --max-turns N` with `CCT_PEER_REVIEW_ENABLED=false`; parse subtype (`error_max_turns` → one `--resume <session_id>` continuation then escalate); check cost/wall-clock caps before every session → run `test.command` (fix sessions ≤ cap, else escalate) → driver commits `feat(<id>): phase N — <title> [auto-build]` (empty diff → escalate `git_anomaly`) → review rounds: init `.cct/review/state.json` as `/review-submit` does, invoke runner with `CCT_REVIEW_BASE_REF=<phase_base_ref>`; on FAIL run fix session with findings + disposition contract, driver commits and injects `commit_ref` into `fixed` dispositions, re-invoke; on BREAKER escalate; on PASS apply **driver hard gate** (loop-summary PASS, no un-approved bypass, `blocking_findings_open: 0`), archive `.cct/review/` → `phase-N/review/`, reset for next phase → origin re-check (≥2 or stale → escalate) → commit collaboration artifact + summary → push (profile-gated) → milestone check (pause exit 3 + notify) or next phase.
- **Finalize**: advisory = summary + "nothing pushed"; pr = `pre-pr-check.sh` then run its printed `gh pr create` (idempotent via `gh pr view`/`pr edit`), record pr in ledger, never merge; merge = v-later (config slots reserved: green CI + branch protection + `merge.enabled`).

### Config: `specs/<feature-id>/automation.json` (JSON, not YAML — repo is jq/Bash-3.2)

Committed with the spec, reviewed at plan approval. Keys: `profile`, `branch{name,base,remote}`, `phases{source,milestone_every,max_phases}`, `build{max_turns,permission_mode,max_fix_sessions_per_phase}`, `test{command,timeout_sec}`, `review{reviewers:[{provider,specialization,scope,gating}],max_rounds,round_timeout_sec}`, `caps{wall_clock_sec,cost_usd}`, `notify{command}` (placeholders `{feature_id} {reason} {phase} {status} {summary}`; notify failure never blocks parking), `merge{enabled,require_green_ci,require_branch_protection}`. v1 uses first `gating: true` reviewer; providers resolve through existing `~/.code-copilot-team/providers.toml` incl. fallback chains. `CCT_AUTOBUILD_*` env overrides.

### Minimal diffs to existing components

1. `scripts/review-round-runner.sh` — `BASE_REF="${CCT_REVIEW_BASE_REF:-HEAD~1}"` replacing lines 339/344/347 literals; `DIFF_MAX_LINES="${CCT_REVIEW_DIFF_MAX_LINES:-500}"` for both 500s. No default behavior change (existing 31 assertions keep passing); add 2-3 assertions + bump `tests/test-counts.env`.
2. `scripts/validate-collaboration.sh:99` — fail `blocking_findings_open > 0` regardless of verdict unless approved bypass (catches forged artifacts).
3. `.gitignore` — add `.cct/`.
4. `shared/skills/phase-workflow/SKILL.md` — add "Autonomy Profiles" gate-mapping table (manual-testing + wait-for-approval → deferred to milestone; commit gate → auto-commit on isolated branch; origin ≥2 → always escalate; peer review → driver-run hard gate; push/PR/merge per profile ladder). One paragraph each in `agent-team-protocol` + `review-loop` SKILL.md (driver-as-submitter, `CCT_REVIEW_BASE_REF`). **No changes to origin-confirmation semantics.** Then `scripts/generate.sh` + commit regenerated adapters (CI drift check).
5. `adapters/claude-code/.claude/settings.json` — document `CCT_AUTOBUILD_PROFILE`, `CCT_AUTOBUILD_NOTIFY_CMD` (defaults empty).
6. `peer-review-on-stop.sh` — unchanged in v1 (driver neutralizes the initiation gap); tightening = optional follow-up.

### New skill + command

- `shared/skills/auto-build-loop/SKILL.md` — protocol doc: profiles + gate map, ledger schema, escalation reasons + human resume playbook, config schema, safety rails, driver invocations. (Picked up by generate.sh / setup.sh --sync.)
- `adapters/claude-code/.claude/commands/auto-build.md` — `/auto-build <feature-id> [profile]`: validates approval + origin, scaffolds `automation.json` from new `shared/templates/sdd/automation-template.json`, prints the driver command to run **outside** the session, explains resume.

### Safety rails (hard-coded)

Single `can_push/can_open_pr/can_merge` profile ladder; advisory never pushes even on escalation; refuse commit on `master`/`main` and any push to base branch; no `--force` code path; all caps default-on; every breaker/cap/anomaly parks (no proceed-anyway branch); origin ≥2 clearable only by human-authored artifacts; sessions use `acceptEdits` (never `bypassPermissions`) so PreToolUse hooks (`protect-files.sh`, `protect-git.sh`) stay active.

## Phasing (one GitHub issue per increment; each PR fully addresses its issue)

- **A — Review-engine generalization + CI tightening** (enabler, tiny): diffs 1-3 above + tests.
- **B — Driver core, advisory profile** (largest): driver script, ledger/state machine, config + template, `/auto-build` command, `auto-build-loop` + `phase-workflow` skill updates + regen, `tests/test-auto-build-loop.sh`, CI wiring. Split B1 (state machine + build/test/commit + dry-run) / B2 (review integration + gates) if needed.
- **C — Escalation, notification, resume**: escalation records, pluggable notify, `--resume` resolution detection, WIP-push for pr profile.
- **D — `pr` profile**: push, pre-pr-check integration, idempotent gh PR create/edit, mock-gh tests.
- **E — Reviewer panel**: specialization-scoped multi-reviewer rounds (non-gating = advisory findings folded into fix prompt); fix stale providers.toml template comment.
- **F — `merge` profile** (later): branch-protection + green-CI gated auto-merge.

Each increment follows the repo's own SDD flow: issue → `specs/auto-build-loop-<x>/` bundle with `origin:` frontmatter → plan approval → build.

## Testing / verification

- `tests/test-auto-build-loop.sh` per `test-review-loop.sh` conventions: mock `claude` (CCT_CLAUDE_BIN stub writing fixture files + canned result JSON incl. `error_max_turns`/cost variants), mock reviewer (existing PASS/FAIL/mutator TOML profiles via CCT_PROVIDER_PROFILE), mock `gh` (argv logger). Cases: 2-phase advisory happy path, FAIL→fix→PASS with commit_ref, breaker→exit 4→resume-after-decision, origin-partial escalate, caps, dirty preflight, `--dry-run` zero side effects, resume idempotency (kill after commit, no duplicate), base-ref coverage. Register count in `tests/test-counts.env`. CI: add step to `sync-check.yml` + `bash -n` the driver.
- **End-to-end toy run** (advisory, mocked): scaffold `specs/auto-build-demo/` (plan approved, `origin: {type: internal}`, 2 US phases, automation.json) → `--dry-run` → real run → expect exit 3 at milestone; inspect ledger, `events.jsonl`, `automation-summary.md`, `git log feature/auto-build-demo` (nothing pushed) → breaker path with FAIL reviewer → `/review-decide approve` → `--resume`.

## First execution steps

1. Persist this plan into the project per Plan Artifact Locality: this file, `specs/auto-build-loop/design.md` (tracked; committed with increment A). Seed `specs/auto-build-loop-review-engine/` SDD bundle for increment A.
2. Create GitHub issues A-D (E/F when reached). (Done: #68, #69, #70, #71.)
3. Implement increment A on a feature branch (never master), with diff shown before any commit per user rules.
