---
spec_mode: full
feature_id: infra-verification-gate
risk_category: integration
status: draft
date: 2026-03-07
---

# Spec: Infrastructure Verification Gate

## Problem Statement

The Build agent treats `./gradlew build` (or equivalent) as the sole quality gate. When a build phase introduces infrastructure artifacts — Dockerfiles, docker-compose files, CI workflows, Helm charts, Terraform configs — these artifacts are committed without being executed. The agent relies on mental simulation instead of actually running the infrastructure.

This was observed in a real ai-atlas session where Docker support (Dockerfile + docker-compose.yml + .dockerignore) was committed after **three untested revisions**, then failed on the user's first `docker compose up --build`. When the failure was reported, the agent suggested skipping Docker and testing with `./gradlew :demo:bootRun` instead — bypassing the deliverable entirely.

The root cause: the existing `verify-on-stop.sh` hook and `phase-workflow.md` rules only cover language-level test runners (Gradle, npm, pytest, cargo). Infrastructure artifacts have no verification path.

## User Scenarios

### US1: Build agent adds a Dockerfile and it must pass before commit (Priority: HIGH)

**Given** a Build agent creates or modifies a Dockerfile in the project
**When** the agent reaches the verification step before declaring the task done
**Then** the agent runs `docker build` (or `docker compose build` if compose exists) and reports the result; if the build fails, the agent fixes the issue before proceeding

### US2: Build agent adds a docker-compose.yml with a healthcheck (Priority: HIGH)

**Given** a Build agent creates a docker-compose.yml with service definitions
**When** the agent reaches the verification step
**Then** the agent runs `docker compose up --build -d`, waits for the healthcheck to pass (or the service to respond on its declared port), then runs `docker compose down`; failure blocks the commit

### US3: Build agent adds a CI workflow and it must be syntactically valid (Priority: MEDIUM)

**Given** a Build agent creates or modifies a `.github/workflows/*.yml` file
**When** the agent reaches the verification step
**Then** the agent runs `actionlint` (if available) or YAML schema validation against the workflow file; syntax errors block the commit

### US4: Build agent encounters an environment issue during infra verification (Priority: HIGH)

**Given** a Build agent runs `docker build` and it fails due to the user's environment (missing Docker daemon, credential helper misconfiguration, network timeout)
**When** the agent identifies the root cause as environmental rather than a Dockerfile bug
**Then** the agent diagnoses and fixes the environment issue (with user permission if needed), then re-runs the verification — it does NOT suggest skipping the test or falling back to a non-Docker workflow

### US5: Build agent modifies only application code, no infra files (Priority: LOW)

**Given** a Build agent modifies Java/Python/TypeScript source files but does not touch any infrastructure files
**When** the stop hook runs
**Then** the infrastructure verification is skipped — only the existing test runner verification runs (no performance regression)

### US6: Demo app stubs must return meaningful data (Priority: MEDIUM)

**Given** a Build agent creates or modifies a demo/example application with REST endpoints
**When** the agent reaches the verification step
**Then** the agent exercises each exposed endpoint with a test request and verifies the response is non-empty and structurally correct (not `[]` or `null`); empty stubs must be flagged and fixed before commit

## Requirements

- **FR-001**: Build agent MUST execute `docker build` after creating or modifying any Dockerfile
- **FR-002**: Build agent MUST execute `docker compose up --build` and verify service health after creating or modifying any `docker-compose.yml` or `compose.yml`
- **FR-003**: Build agent MUST run `docker compose down` to clean up after verification passes or fails
- **FR-004**: Build agent MUST NOT suggest skipping infrastructure verification when a failure occurs — it must diagnose and fix the issue
- **FR-005**: Build agent MUST validate CI workflow YAML syntax after creating or modifying `.github/workflows/*.yml`
- **FR-006**: Build agent MUST exercise each exposed endpoint in a demo/example app and verify non-empty, structurally valid responses
- **FR-007**: `verify-on-stop.sh` MUST detect infrastructure files in the current git diff and run appropriate verification commands
- **FR-008**: `verify-on-stop.sh` MUST skip infrastructure checks when no infra files were changed (zero overhead for normal code changes)
- **FR-009**: Infrastructure verification failures MUST block the agent from declaring the task done (exit code 2 when HOOK_STOP_BLOCK=true)
- **FR-010**: A new rule in the rules library MUST define the "build it, run it" principle and the specific verification commands per artifact type
- **FR-011**: Docker healthchecks MUST use proper health probes (`/actuator/health`, `/healthz`, etc.) — not business endpoints
- **FR-012**: All existing tests (834+) MUST continue to pass after changes
- **FR-013**: Codex AGENTS.md output MUST stay under 32 KiB

### Sprint 2 Addendum: Executable Script Verification

*Added 2026-03-07 after a second incident in the code-copilot-team repo itself (Multi-Copilot Providers Sprint 2). The Build agent created launcher flags, shell hooks, and a provider health script — all passing 893 tests — but two runtime bugs were found on the user's first manual test: (1) peer-review banner invisible in tmux, (2) env vars from `tmux setenv` not reaching the running Claude process. The agent suggested skipping the banner check.*

### US7: Build agent modifies an executable shell script and it must be smoke-tested (Priority: HIGH)

**Given** a Build agent creates or modifies an executable `.sh` script (launcher, hook, health check, runner)
**When** the agent reaches the verification step before declaring the task done
**Then** the agent runs the script with a minimal safe invocation (`--help`, `--dry-run`, or `echo '{}' | bash <script>`) and verifies it exits cleanly and produces expected output

### US8: Build agent must execute its own test plan (Priority: HIGH)

**Given** a Build agent writes a manual test plan as part of the build summary
**When** the plan contains executable commands (curl, bash, docker, etc.)
**Then** the agent executes every command in its own test plan and reports the results before declaring the task done; commands that fail block the commit

### FR-014 through FR-018 (Sprint 2 Addendum)

- **FR-014**: Build agent MUST smoke-test any executable `.sh` script it creates or modifies — at minimum a `--help` or `--dry-run` invocation
- **FR-015**: Build agent MUST execute every command in its own test plan before declaring the task done
- **FR-016**: `verify-on-stop.sh` MUST detect modified `.sh` scripts in the git diff and verify they are syntactically valid (`bash -n <script>`)
- **FR-017**: Build agent MUST NOT suggest skipping ANY verification step — this applies to all artifact types, not just infrastructure (promotion of FR-004 to global scope)
- **FR-018**: When the project uses tmux (detected via `claude-code` launcher), verification of UI-facing features MUST include a tmux-aware check

## Constraints / What NOT to Build

- No Kubernetes/Helm/Terraform verification (future sprint — Docker only for now)
- No new CI workflows (verification is agent-side + hook-side only)
- No changes to `shared/rules/always/*` — the new rule goes in `on-demand/` or the rules-library
- No changes to the Plan agent — this is purely a Build + Review concern
- No Docker installation or setup automation — assume Docker is available or skip gracefully
- No changes to `shared/templates/sdd/` templates

## Key Entities

- **Infrastructure artifact**: Any file whose correctness cannot be verified by a language-level compiler/test runner. Includes: Dockerfile, docker-compose.yml, compose.yml, .github/workflows/*.yml, .dockerignore
- **Executable artifact**: Any `.sh` script or launcher that must be run to verify correctness. Includes: launcher scripts, hook scripts, health check scripts, runner scripts
- **Infrastructure verification**: Running the artifact to confirm it works — `docker build`, `docker compose up`, `actionlint`, YAML validation
- **Script verification**: Running `bash -n <script>` for syntax checking, plus a minimal safe invocation (`--help`, `--dry-run`, or piped empty input) for runtime verification
- **Environment issue**: A failure caused by the user's local setup (missing daemon, broken credentials, network) rather than by the artifact itself
- **Health probe**: A dedicated endpoint (e.g., `/actuator/health`) designed for liveness/readiness checks, as opposed to a business endpoint
- **Empty stub**: A demo endpoint that returns `[]`, `null`, `{}`, or a static placeholder instead of meaningful sample data

## Success Criteria

1. Build agent runs `docker build` automatically after creating/modifying a Dockerfile — verified in a test scenario
2. Build agent runs `docker compose up --build` and checks service health after creating/modifying compose files
3. Build agent diagnoses and fixes environment issues instead of suggesting workarounds
4. `verify-on-stop.sh` detects Docker files in `git diff` and runs appropriate checks
5. Infrastructure verification has zero overhead on sessions that don't touch infra files
6. All 834+ existing tests pass
7. One pilot session demonstrates the full flow: create Dockerfile → auto-verify → fix failure → re-verify → commit
8. *(Sprint 2 Addendum)* Build agent smoke-tests modified `.sh` scripts before declaring done
9. *(Sprint 2 Addendum)* Build agent executes its own test plan commands, not just hands them to the user
10. *(Sprint 2 Addendum)* `verify-on-stop.sh` runs `bash -n` on modified shell scripts
