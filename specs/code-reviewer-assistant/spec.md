---
spec_mode: full
feature_id: code-reviewer-assistant
risk_category: integration
status: approved
date: 2026-03-28
---

# Spec: Code Reviewer Assistant

<!-- Project constitution: shared/rules/always/ — copilot-conventions.md, coding-standards.md, safety.md -->

## Problem Statement

The current peer-review system is ~70% built but non-functional end-to-end. It cannot complete a single real review. The runner has no provider backends, the loop is fire-and-forget (no mechanism for the builder to receive findings, fix them, and resubmit), and the stop hook launches a synchronous process that would deadlock the session if it ever tried to hand work back.

Meanwhile, AI coding sessions operate without any external quality check. The same LLM that writes the code also decides it's correct. A separate reviewer — structurally unable to modify the code — catches classes of errors that the author cannot see.

## User Scenarios

### US1: Build agent submits work for review and receives structured findings (Priority: HIGH)

**Given** a Build agent has completed a feature and committed its work
**When** the agent runs `/review-submit`
**Then** `review-round-runner.sh` spawns a reviewer LLM in a read-only sandbox, captures its output, parses it into structured findings with stable IDs, writes `findings-round-1.json`, and returns the verdict (PASS/FAIL) to the agent

### US2: Build agent addresses FAIL findings and resubmits (Priority: HIGH)

**Given** the agent received a FAIL verdict with two blocking findings in `findings-round-1.json`
**When** the agent fixes one finding and disputes the other, writes `resolution-round-1.json`, commits, and runs `/review-submit` again
**Then** `review-round-runner.sh` executes round 2 with the delta diff and prior findings context, and the reviewer re-evaluates — dropping the fixed finding and re-assessing the disputed one

### US3: Review passes and commits are squashed (Priority: HIGH)

**Given** a 2-round review loop where round 1 was FAIL and round 2 is PASS, with `--review-commits squash`
**When** the runner writes `loop-summary.json` with verdict PASS
**Then** the agent squashes the fix-round commits into a single clean commit via `git reset --soft`, and proceeds to `/phase-complete`

### US4: Circuit breaker fires and human decides (Priority: HIGH)

**Given** the review loop has reached round 5 (the `CCT_REVIEW_MAX_ROUNDS` default)
**When** `review-round-runner.sh` detects the round limit
**Then** the runner writes `breaker-tripped.json` with full context (rounds completed, unresolved findings, stale findings), the agent prints the context to the user and stops, and the session waits for the human to run `/review-decide approve|reject|retry`

### US5: Stale findings escalate to human (Priority: HIGH)

**Given** finding `f-a1b2c3d4` has appeared in rounds 1, 2, and 3 with builder disposition `fixed` each time but the reviewer persists it
**When** round 3 completes and the stale-findings threshold (default: 2 consecutive rounds) is exceeded
**Then** the breaker fires, the finding remains blocking (not auto-downgraded), and the human must run `/review-decide` to resolve the disagreement

### US6: Reviewer cannot modify the working tree (Priority: HIGH)

**Given** `review-round-runner.sh` spawns a reviewer process
**When** the reviewer attempts to write files or create commits
**Then** those writes land in the snapshot copy, not the real working tree; the runner validates post-review that the real repo is unchanged; if the snapshot differs (indicating the reviewer tried to modify files), the round is marked INVALID and findings are discarded

### US7: Builder submits with dirty worktree (Priority: MEDIUM)

**Given** the Build agent has uncommitted changes in the working tree
**When** the agent runs `/review-submit`
**Then** `review-round-runner.sh` rejects the submission with error `"uncommitted_changes — commit or stash before submitting for review"` before spawning any reviewer process

### US8: Developer configures GDX Spark as reviewer (Priority: HIGH)

**Given** a developer has a GDX Spark GPU server on their LAN running an OpenAI-compatible endpoint
**When** they run `./scripts/setup.sh --configure-providers` and select type `openai-compatible` with base URL `http://192.168.1.50:8000/v1`
**Then** the provider is written to `~/.code-copilot-team/providers.toml`, healthcheck confirms reachability, and subsequent `--peer-review gdx-spark` sessions use it

### US9: Primary provider is down, fallback engages (Priority: MEDIUM)

**Given** the default peer for Claude is `codex`, and `codex` fails its healthcheck
**When** the runner resolves the provider at review time
**Then** it walks the fallback chain (`openai` → `ollama` → `gdx-spark`), uses the first healthy provider, and logs which provider was actually used in `findings-round-N.json`

### US10: Plan review provides advisory input (Priority: MEDIUM)

**Given** a Plan agent has completed spec artifacts and runs `/review-submit`
**When** the reviewer returns findings (PASS or FAIL)
**Then** the findings are written as a `plan-consult.md` artifact; a FAIL verdict is logged but does **not** gate Build entry; the agent proceeds without a fix loop — this is a product decision, not a missing feature

### US11: Stop hook validates review was completed (Priority: MEDIUM)

**Given** `CCT_PEER_REVIEW_ENABLED=true` and the Build session is ending
**When** `peer-review-on-stop.sh` fires
**Then** the hook checks that `loop-summary.json` exists with verdict `PASS` or an approved bypass; if missing or verdict is `FAIL` without bypass, the hook blocks session stop (exit 2)

### US12: Human approves bypass after breaker trip (Priority: MEDIUM)

**Given** a circuit breaker has fired and `breaker-tripped.json` exists
**When** the human runs `/review-decide approve`
**Then** `decision.json` is written with `{"decision": "approve", ...}`, the agent writes `loop-summary.json` with `bypass: true` and the breaker type, and the session proceeds to `/phase-complete`

### US13: Human retries after fixing provider connectivity (Priority: LOW)

**Given** a breaker fired with `"reason": "provider_unavailable"` and the human has fixed their network
**When** the human runs `/review-decide retry`
**Then** breaker state is reset (round-within-attempt counter, wall-clock timer, stale-finding consecutive count) but round numbering continues monotonically (next round is 6, not 1), and the agent runs `/review-submit` again with the same diff

## Requirements

### Review Loop

- **FR-001**: Build agent MUST run `/review-submit` after completing work and before `/phase-complete` when `CCT_PEER_REVIEW_ENABLED=true`
- **FR-002**: `/review-submit` MUST invoke `review-round-runner.sh` as a synchronous subprocess and return the verdict to the agent
- **FR-003**: `review-round-runner.sh` MUST execute exactly one review round per invocation — the agent drives the loop, not the runner
- **FR-004**: On FAIL verdict, the Build agent MUST read `findings-round-N.json`, address each blocking finding (fix, dispute, defer, or mark not-applicable), write `resolution-round-N.json`, commit, and run `/review-submit` again
- **FR-005**: On PASS verdict, the runner MUST write `loop-summary.json` with all rounds, findings, dispositions, and provider metadata
- **FR-005a**: All review-loop artifacts (`findings-round-N.json`, `resolution-round-N.json`, `state.json`, `loop-summary.json`, `breaker-tripped.json`, `decision.json`) MUST be stored under `.cct/review/` during the active loop. On loop completion, the **completing actor** MUST copy `loop-summary.json` and generate a consolidated `build-review.md` artifact to `specs/<feature-id>/collaboration/`. The completing actor is: the **runner** on PASS verdict (FR-005), or the **agent** on approved bypass after `/review-decide approve` (FR-026). This integrates with the repo's existing collaboration-artifact model and is what `validate-collaboration.sh` reads at CI time
- **FR-005b**: The `build-review.md` collaboration artifact MUST follow the existing artifact schema (YAML frontmatter with `feature_id`, `date`, `status`, `phase`, `mode`, `subject_provider`, `peer_provider`, `peer_profile`, `runner_fingerprint`, `verdict`, `blocking_findings_open`, `target_ref`) plus new fields: `rounds_completed`, `attempt_count`, `bypass`, `breaker_type` (if bypassed). All fields from the current `provider-collaboration-protocol.md` artifact contract are retained for backward compatibility. The body MUST contain a human-readable summary of all rounds and final dispositions
- **FR-005c**: Plan-phase advisory review MUST write its artifact as `plan-consult.md` under `specs/<feature-id>/collaboration/` — same location, same frontmatter schema, but with `mode: consult` and no loop metadata

### Read-Only Enforcement

- **FR-006**: `review-round-runner.sh` MUST spawn the reviewer in a snapshot copy of the working tree (macOS: `cp -R` to temp dir; Linux: read-only bind mount or `cp -R`)
- **FR-007**: The reviewer process MUST NOT have access to the real `.git` directory or SSH/GPG agent forwarding
- **FR-008**: `review-round-runner.sh` MUST validate post-review that no files in the real working tree changed and no new commits appeared in the real repo
- **FR-009**: If the post-review validation detects changes, the round MUST be marked INVALID and findings MUST be discarded

### Structured Finding Schema

- **FR-010**: Each finding MUST have an `id` field: SHA-256 truncated to 8 hex chars of `(file + category + normalized_description)` — line numbers MUST NOT be included in the fingerprint
- **FR-011**: Each finding MUST have a `severity` field with value `blocking`, `warning`, or `note`
- **FR-012**: Each finding MUST have `category`, `file`, `line_hint` (display-only), `description`, and `suggested_fix` fields
- **FR-013**: `line_hint` MUST use semantic anchors where possible ("near variable expansion in query function") rather than numeric line references
- **FR-014**: The builder's `resolution-round-N.json` MUST include a `disposition` for each blocking finding: `fixed`, `disputed`, `deferred`, or `not-applicable`
- **FR-015**: `disputed` disposition MUST include a `detail` field explaining the disagreement
- **FR-016**: `fixed` disposition MUST include a `commit_ref` field referencing the fix commit

### Circuit Breakers

- **FR-017**: `review-round-runner.sh` MUST check the round counter against `CCT_REVIEW_MAX_ROUNDS` (default: 5) before starting each round
- **FR-018**: `review-round-runner.sh` MUST check cumulative wall-clock time against `CCT_REVIEW_TIMEOUT_SEC` (default: 900) before starting each round
- **FR-019**: `review-round-runner.sh` MUST detect stale findings (same ID appearing in `CCT_REVIEW_STALE_THRESHOLD` consecutive rounds with disposition `fixed`) and fire the breaker
- **FR-020**: Stale findings MUST NOT be auto-downgraded from blocking to non-blocking — they remain blocking and the breaker escalates to human
- **FR-021**: Every breaker trip MUST write `breaker-tripped.json` with: breaker type, rounds completed, unresolved blocking findings, stale finding details, and the instruction `"Run /review-decide approve|reject|retry"`
- **FR-022**: Every breaker trip MUST cause the agent to stop and wait — there is no path to automatic acceptance of unreviewed or disputed work
- **FR-023**: If all providers in the fallback chain fail healthcheck, the runner MUST fire a breaker with `"reason": "provider_unavailable"` — not silently skip review

### Human Decision Channel

- **FR-024**: `/review-decide` MUST accept exactly one argument: `approve`, `reject`, or `retry`
- **FR-025**: `/review-decide` MUST write `.cct/review/decision.json` with the decision value and timestamp
- **FR-026**: On `approve`, the agent MUST write `loop-summary.json` with `bypass: true`, breaker type, and all unresolved findings
- **FR-027**: On `reject`, the agent MUST log rejection in `loop-summary.json` and abort — no merge
- **FR-028**: On `retry`, the agent MUST increment the `attempt` counter in `state.json`, reset breaker state (round-within-attempt counter, wall-clock timer, stale-finding consecutive count), and run `/review-submit` again. Round numbering MUST remain globally monotonic across attempts — if the breaker fired after round 5, the next round is 6, not 1. This preserves the full audit trail in `findings-round-N.json` and `resolution-round-N.json` and prevents artifact overwrites
- **FR-029**: The human MUST NOT be required to set environment variables or edit files manually — `/review-decide` is the sole decision channel

### Commit-Strategy Modes

- **FR-030**: The `--review-commits` flag MUST accept values `single`, `per-round`, or `squash` (default: `squash`)
- **FR-031**: In `per-round` mode, the Build agent MUST commit after each fix round with message format `fix(review): round N — <summary>`
- **FR-032**: In `single` mode, the Build agent MUST amend the previous commit after each fix round
- **FR-033**: In `squash` mode, the agent MUST use per-round commits during the loop. On final PASS, the agent MUST: (1) run `git reset --soft` to the pre-review commit, staging all changes, (2) present the squash commit message to the user for approval via the existing `phase-workflow.md` commit-approval step (which precedes `/phase-complete`), (3) only create the final squash commit after the user approves. The reviewer PASS verdict authorizes the code; the user authorizes the commit.
- **FR-034**: If `git reset --soft` fails, the agent MUST fall back to a merge commit — it MUST NOT force-reset or lose work. The merge commit also goes through the commit-gate approval step.
- **FR-035**: `/review-submit` MUST reject submission if the worktree has uncommitted changes — error before spawning reviewer
- **FR-036**: The review system MUST NOT auto-commit on behalf of the user — the Build agent commits following existing `phase-workflow.md` commit-gate rules. This applies to both per-round fix commits (which the agent creates as part of its normal workflow with user oversight) and the final squash commit (which requires explicit user approval per FR-033)
- **FR-037**: Commit strategies MUST apply only to Build-phase review — plan review does not participate in fix loops or commit strategies

### Provider Configuration

- **FR-038**: `providers.toml` MUST support typed providers: `cli`, `openai-compatible`, `ollama`, `custom`
- **FR-039**: `openai-compatible` providers MUST be configurable with `base_url`, `api_key_env`, `model`, `timeout_sec`, `max_tokens`, `temperature`
- **FR-040**: `api_key_env` MUST reference an environment variable name — API keys MUST NOT appear in the TOML file
- **FR-041**: `ollama` providers MUST support a `host` field (default: `localhost:11434`) for remote Ollama instances
- **FR-042**: `custom` providers MUST accept a `command` template with `{review_request}` and `{model}` placeholders — backward compatible with current flat format
- **FR-043**: `defaults.fallback_chain.<subject>` MUST define an ordered list of fallback providers tried when the primary fails healthcheck
- **FR-044**: `setup.sh --configure-providers` MUST provide an interactive flow for adding, testing, and setting default providers

### Stop Hook & CI Gate

- **FR-045**: `peer-review-on-stop.sh` MUST NOT initiate review — it MUST only validate that `loop-summary.json` exists with verdict PASS or approved bypass when `CCT_PEER_REVIEW_ENABLED=true` **and the completing phase is Build**. Plan-phase sessions are exempt: the stop hook MUST NOT block session stop based on plan-review outcomes, because plan review is advisory (see FR-037, US10)
- **FR-046**: `validate-collaboration.sh` MUST distinguish Build-phase review (gating: PASS or approved bypass required) from Plan-phase review (advisory: FAIL logged, does not block PR)
- **FR-047**: `validate-collaboration.sh` MUST fail the PR when bypass artifacts are present without a logged breaker type and decision

### Compatibility

- **FR-048**: All 834+ existing tests MUST continue to pass after changes
- **FR-049**: Codex AGENTS.md output MUST stay under 32 KiB
- **FR-050**: `generate.sh` MUST propagate `review-loop.md` to all 6 adapters

## Constraints / What NOT to Build

- No Kubernetes, Helm, or Terraform provider integrations — providers are user-configured, not framework-shipped
- No interactive rebase for squash mode — `git reset --soft` only; fall back to merge commit on failure
- No multi-round gating for plan review — advisory single-round only (product decision, revisitable in Phase 4)
- No reviewer-to-reviewer chaining — one reviewer per round, not a panel
- No changes to `shared/rules/always/*` — new rules go in `on-demand/`
- No changes to `shared/templates/sdd/` templates
- No wrapper-level spoofing detection for provider identity (acknowledged as out of scope for v1)
- No Docker/container-based reviewer isolation — snapshot copy is sufficient for v1; container sandboxing is a Phase 4 candidate
- No GUI or web interface for `/review-decide` — CLI command only

## Key Entities

- **review-round-runner.sh**: Script that executes one review round. Spawns reviewer in read-only sandbox, captures output, parses findings, writes round artifacts, checks breakers. Stateless per invocation — loop state lives in `state.json`.
- **`/review-submit`**: Claude Code command that the Build agent runs to trigger a review round. Validates clean worktree, invokes runner, returns verdict.
- **`/review-decide`**: Claude Code command that the human runs to resolve a circuit breaker. Writes `decision.json`. Sole decision channel.
- **Finding**: A single issue identified by the reviewer. Has a stable ID (file + category + normalized description), severity, category, and lifecycle (created → dispositioned → resolved or stale).
- **Finding ID**: SHA-256 truncated to 8 hex chars of `(file + category + normalized_description)`. Line numbers excluded to remain stable across edits.
- **Disposition**: Builder's response to a finding: `fixed` (with commit ref), `disputed` (with explanation), `deferred` (acknowledged, fix later), `not-applicable` (wrong target).
- **Stale finding**: A finding that persists across N consecutive rounds despite the builder marking it `fixed`. Indicates builder-reviewer disagreement. Remains blocking; escalates to human.
- **Circuit breaker**: Safety mechanism that halts the review loop and escalates to human decision. Triggers: round limit, time limit, stale findings, provider unavailability.
- **`state.json`**: Persistent loop state file in `.cct/review/`. Tracks current round, accumulated findings by ID, breaker counters, wall-clock start time.
- **`loop-summary.json`**: Final record of a completed review loop. Written by runner on PASS or by agent on approved bypass. Read by stop hook and CI gate.
- **`breaker-tripped.json`**: Written by runner when a breaker fires. Contains full context for human decision. Cleared on `/review-decide`.
- **`decision.json`**: Written by `/review-decide` command. Contains human's decision (approve/reject/retry) and timestamp.
- **Snapshot copy**: Temporary copy of the working tree where the reviewer runs. Ensures read-only enforcement — reviewer's writes cannot affect the real repo.
- **Provider adapter**: Script in `scripts/provider-adapters/` that translates the generic review request into a provider-specific API call. Exists for `openai-compatible` and `ollama` types; `cli` and `custom` execute their command template directly.
- **Fallback chain**: Ordered list of alternative providers tried when the primary fails healthcheck. Defined in `providers.toml` under `defaults.fallback_chain`.

## Success Criteria

1. [US1, US2, US3] A 2-round review loop (FAIL → fix → PASS) completes end-to-end with squash, producing `loop-summary.json` with full metadata — verified with at least two provider combinations (e.g., Claude ↔ GDX Spark, Claude ↔ Ollama)
2. [US6, FR-006–FR-009] Reviewer process runs in snapshot copy; test confirms that reviewer file writes do not affect real working tree; INVALID round on violation
3. [US4, US5, FR-017–FR-023] Circuit breaker fires at round 5 and stale-finding threshold, both escalate to human — no auto-acceptance; session resumes only after `/review-decide`
4. [US12, US13, FR-024–FR-029] `/review-decide approve|reject|retry` all work correctly: approve logs bypass, reject aborts, retry increments attempt counter and continues with monotonic round numbering (no artifact overwrites)
5. [US7, FR-035] Dirty worktree rejected before reviewer spawns
6. [US8, US9, FR-038–FR-044] All four provider types configurable and functional; fallback chain engages on primary failure
7. [US10, FR-037, FR-046] Plan review is advisory single-round; FAIL does not gate Build; CI warns but does not block; stop hook does not block plan-phase session stop
8. [US11, FR-045] Stop hook validates Build-phase review completed — blocks stop if `loop-summary.json` missing or non-PASS without bypass; plan-phase sessions exempt
9. [FR-010–FR-016] Finding IDs stable across rounds even when edits shift line numbers; dispositions tracked per finding per round
10. [FR-030–FR-034, FR-036] All three commit-strategy modes produce correct git history; squash mode presents final commit for user approval before creating it; squash failure falls back to merge commit
11. [FR-005a–FR-005c] On loop completion, `build-review.md` artifact is written to `specs/<feature-id>/collaboration/` with full frontmatter; `validate-collaboration.sh` reads it at CI time
12. [FR-048–FR-050] All 834+ existing tests pass; `generate.sh` propagates new rule to all adapters; Codex output under 32 KiB
