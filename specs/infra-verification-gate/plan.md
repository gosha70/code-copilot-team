---
spec_mode: full
feature_id: infra-verification-gate
risk_category: integration
justification: "Framework-level change affecting the Build agent manifest, verify-on-stop hook, rules library, and phase-workflow verification steps. Touches the core quality gate pipeline."
status: draft
date: 2026-03-07
---

# Implementation Plan: Infrastructure Verification Gate

**Branch**: `infra-verification-gate`
**Input**: specs/infra-verification-gate/spec.md, real-world failure transcript from ai-atlas Build session (March 2026)

## Summary

Add infrastructure artifact verification to the Build agent workflow and the `verify-on-stop.sh` hook. When a build phase creates or modifies Docker, Compose, or CI workflow files, the agent and hook automatically execute those artifacts to verify they work — rather than relying on mental simulation. This closes the gap where `./gradlew build` passes but `docker compose up --build` fails, and the failure is only discovered by the human.

## Technical Context

**Language/Version**: Bash (hooks, scripts), Markdown (rules, agent manifests)
**Primary Dependencies**: `verify-on-stop.sh`, `phase-workflow.md`, `build.md` agent manifest, `integration-testing.md`
**Testing**: `test-shared-structure.sh`, `test-generate.sh`, `test-hooks.sh` (existing), plus new hook test cases
**Constraints**: All shared rule changes must flow through `shared/ → generate.sh → adapters/`. Agent manifest changes are Claude Code adapter-specific.

## Scope

### Task 1: Create `infra-verification.md` Rule [US1, US2, US3, US4, US6]

**File to create:**

- `shared/rules/on-demand/infra-verification.md`

**Content — "Build It, Run It" Principle:**

The rule defines three categories of infrastructure artifacts and their mandatory verification commands:

**Docker artifacts:**
| File pattern | Verification command | Success criteria |
|---|---|---|
| `Dockerfile`, `*.Dockerfile` | `docker build -t <project>-verify .` | Exit code 0 |
| `docker-compose.yml`, `compose.yml` | `docker compose up --build -d && sleep 10 && docker compose ps` | All services "running" or "healthy" |
| Post-compose | `docker compose down -v` | Cleanup (always, even on failure) |

**CI workflow artifacts:**
| File pattern | Verification command | Success criteria |
|---|---|---|
| `.github/workflows/*.yml` | `actionlint <file>` (if available) or `python -c "import yaml; yaml.safe_load(open('<file>'))"` | Exit code 0, no syntax errors |

**Demo/example endpoints:**
| Trigger | Verification command | Success criteria |
|---|---|---|
| Any REST endpoint in a demo app | `curl -s <endpoint>` | Response is non-empty, valid JSON, and not `[]`/`null`/`{}` |

**Environment failure protocol:**
- When verification fails, DIAGNOSE the root cause before acting
- If environmental (Docker daemon down, credential helper broken, network timeout): fix the environment issue, then re-run verification
- If artifact bug (bad COPY path, missing dependency, wrong base image): fix the artifact, then re-run verification
- NEVER suggest skipping infrastructure verification or falling back to a different workflow
- NEVER declare the task done until verification passes

**Health probe rule:**
- Docker healthchecks MUST use dedicated health endpoints: `/actuator/health` (Spring Boot), `/healthz` (generic), `/health` (Rails/Express)
- If the application does not have a health endpoint, ADD one (e.g., add `spring-boot-starter-actuator` to dependencies) rather than using a business endpoint
- Business endpoints (e.g., `/api/v1/orders/find-by-id?id=1`) are NOT acceptable healthchecks because they couple infrastructure liveness to business logic and demo data

**Acceptance criteria:**
- [ ] File exists in `shared/rules/on-demand/`
- [ ] Defines verification commands for Docker, Compose, CI workflows, and demo endpoints
- [ ] Defines environment failure protocol with "never skip" principle
- [ ] Defines health probe requirements
- [ ] Contains at minimum one example verification sequence for each artifact type

### Task 2: Update `phase-workflow.md` Rule [US1, US2, US5]

**File to modify:**

- `shared/rules/on-demand/phase-workflow.md`

**Changes:**

Add a new section **"Infrastructure Verification"** between the existing "Dependency verification" (step 2) and "Build verification" (step 3) in the Post-Phase Steps:

```
2.5. **Infrastructure verification.** After any phase that creates or modifies Docker, Compose, or CI
     workflow files — run the artifact to verify it works. This is NOT optional. If you introduced
     a Dockerfile, run `docker build`. If you introduced a compose file, run `docker compose up
     --build` and verify health. If you introduced a CI workflow, validate the YAML syntax. See
     `infra-verification.md` for the full command reference.
     - Infrastructure verification failures block the commit, just like test failures.
     - Environment issues are diagnosed and fixed, not worked around.
```

Add to the **"Phase N Checklist (General Build Phase)"**:
```
- [ ] **Infrastructure files verified** — all Docker/Compose/CI files introduced in this phase have been executed successfully
- [ ] **Docker healthchecks use proper probes** — not business endpoints
- [ ] **Demo endpoints return meaningful data** — no empty stubs (`[]`, `null`, `{}`)
```

**Acceptance criteria:**
- [ ] `phase-workflow.md` contains the Infrastructure Verification step
- [ ] Phase N Checklist includes infra verification items
- [ ] Existing steps are unchanged (no regressions)

### Task 3: Update `integration-testing.md` Rule [US6]

**File to modify:**

- `claude_code/.claude/rules-library/integration-testing.md`

**Changes:**

Add a new section **"Demo / Example Application Verification"** after the existing "When to Create Smoke Test Scripts" section:

```
## Demo / Example Application Verification

When a build phase creates or modifies a demo or example application:

1. **Exercise every exposed endpoint** after the app starts. Use curl or the project's test
   framework.
2. **Verify responses are non-empty.** Empty arrays (`[]`), null, or empty objects (`{}`) indicate
   a stub that was never implemented. Stubs MUST be replaced with meaningful sample data before
   commit.
3. **Verify PII exclusion** (if applicable). Ensure sensitive fields declared as hidden are absent
   from the response.
4. **Log the verification output** in the build summary so the reviewer can confirm.

Common trap: demo services with stub methods (e.g., `return List.of()`) that compile and pass
type checks but return nothing at runtime. The type checker cannot catch this — only an actual
HTTP request reveals it.
```

**Acceptance criteria:**
- [ ] `integration-testing.md` contains the Demo Verification section
- [ ] Mentions empty stub detection specifically
- [ ] Existing sections unchanged

### Task 4: Update Build Agent Manifest [US1, US2, US4, US6]

**File to modify:**

- `adapters/claude-code/.claude/agents/build.md` (or `claude_code/.claude/agents/build.md` — verify correct path)

**Changes:**

Add to the **"What to Do"** section, after step 6 (Integrate):

```
6.5. **Verify infrastructure.** If any agent created or modified Docker, Compose, or CI workflow
     files, run the verification commands from `infra-verification.md`. This is mandatory — do NOT
     declare the build done until infrastructure artifacts have been executed and verified. If
     verification fails due to an environment issue, diagnose and fix it (with user permission) and
     re-run — never suggest skipping.
```

Add to the **"Verification After Each Agent"** section:

```
5. If the agent created Docker/Compose files, run `docker build` or `docker compose up --build`
   and verify the service starts. Run `docker compose down` after.
6. If the agent created CI workflow files, run `actionlint` or validate YAML syntax.
7. If the agent modified a demo app, exercise each endpoint and verify non-empty responses.
```

Add a new **"Infrastructure Failure Protocol"** section:

```
## Infrastructure Failure Protocol

When an infrastructure verification step fails:

1. **Diagnose.** Determine if the failure is in the artifact (Dockerfile bug, bad COPY path) or
   the environment (Docker daemon not running, credential helper broken, network timeout).
2. **Fix.** For artifact bugs, fix and re-run. For environment issues, diagnose the root cause,
   ask the user for permission if needed (e.g., editing ~/.docker/config.json), apply the fix,
   and re-run.
3. **Never skip.** Do not suggest "just test with `./gradlew bootRun` instead" or "Docker isn't
   required." If you introduced the infrastructure, you own its verification.
4. **Never declare done until passing.** The task is incomplete until the infrastructure artifact
   has been executed successfully.
```

**Acceptance criteria:**
- [ ] `build.md` includes infrastructure verification in the main workflow
- [ ] `build.md` includes infrastructure items in the per-agent verification checklist
- [ ] `build.md` includes the Infrastructure Failure Protocol section
- [ ] Existing steps unchanged

### Task 5: Update `verify-on-stop.sh` Hook [US1, US2, US3, US5]

**File to modify:**

- `claude_code/.claude/hooks/verify-on-stop.sh`

**Changes:**

After the existing test runner detection and execution block, add an **infrastructure verification block** that:

1. **Detects infra files in the current diff:**
   ```bash
   INFRA_FILES=$(git diff --name-only HEAD~1 2>/dev/null | grep -E '(Dockerfile|docker-compose\.yml|compose\.yml|\.github/workflows/.*\.yml)' || true)
   ```
   If `INFRA_FILES` is empty, skip infrastructure checks (FR-008 — zero overhead).

2. **Runs Docker build** if any Dockerfile is in the diff:
   ```bash
   if echo "$INFRA_FILES" | grep -q 'Dockerfile'; then
     docker build -t "${PROJECT_NAME}-verify" . 2>&1
   fi
   ```

3. **Runs Compose verification** if any compose file is in the diff:
   ```bash
   if echo "$INFRA_FILES" | grep -q -E 'docker-compose\.yml|compose\.yml'; then
     docker compose up --build -d 2>&1
     sleep 15
     docker compose ps --format json 2>&1
     docker compose down -v 2>&1
   fi
   ```

4. **Runs workflow validation** if any CI workflow is in the diff:
   ```bash
   if echo "$INFRA_FILES" | grep -q '\.github/workflows/'; then
     for wf in $(echo "$INFRA_FILES" | grep '\.github/workflows/'); do
       if command -v actionlint &>/dev/null; then
         actionlint "$wf" 2>&1
       else
         python3 -c "import yaml; yaml.safe_load(open('$wf'))" 2>&1
       fi
     done
   fi
   ```

5. **Respects HOOK_STOP_BLOCK** — uses the same exit-code convention as the existing test runner block (exit 2 for blocking, exit 0 for report-only).

6. **Guards against missing Docker** — if `docker` command is not found, emits a warning and skips Docker checks (don't fail the hook on machines without Docker).

**Acceptance criteria:**
- [ ] `verify-on-stop.sh` detects infra files via git diff
- [ ] Runs `docker build` when Dockerfiles are in the diff
- [ ] Runs `docker compose up/down` when compose files are in the diff
- [ ] Validates CI workflows when `.github/workflows/*.yml` is in the diff
- [ ] Skips all infra checks when no infra files changed (zero overhead)
- [ ] Gracefully skips when Docker is not installed
- [ ] Uses existing HOOK_STOP_BLOCK convention

### Task 5b: Add Shell Script Verification to `verify-on-stop.sh` [US7, Sprint 2 Addendum]

**File to modify:**

- `claude_code/.claude/hooks/verify-on-stop.sh`

**Changes:**

After the infrastructure verification block (Task 5), add a **shell script verification block** that:

1. **Detects modified `.sh` scripts in the current diff:**
   ```bash
   SCRIPT_FILES=$(git diff --name-only HEAD~1 2>/dev/null | grep -E '\.sh$' || true)
   ```
   If `SCRIPT_FILES` is empty, skip script checks.

2. **Runs `bash -n` syntax check** on each modified script:
   ```bash
   for script in $SCRIPT_FILES; do
     if [[ -f "$script" ]]; then
       bash -n "$script" 2>&1
     fi
   done
   ```

3. **Runs a safe smoke invocation** for executable scripts that accept `--help`:
   ```bash
   for script in $SCRIPT_FILES; do
     if [[ -x "$script" ]] && head -5 "$script" | grep -q 'usage\|--help\|Usage'; then
       bash "$script" --help 2>&1 || true
     fi
   done
   ```

**Acceptance criteria:**
- [ ] `verify-on-stop.sh` detects modified `.sh` scripts via git diff
- [ ] Runs `bash -n` syntax check on each modified script
- [ ] Skips when no `.sh` files changed (zero overhead)
- [ ] Uses existing HOOK_STOP_BLOCK convention

### Task 6: Update Generation Pipeline [All]

**File to modify:**

- `scripts/generate.sh`

**Changes:**

Add `infra-verification.md` to the on-demand rule propagation, so all 6 adapters receive the "build it, run it" guidance:
- Claude Code: enforced via agent manifest + hook
- Other adapters: advisory content (consistent with SDD Sprint 1 pattern)

**Acceptance criteria:**
- [ ] `generate.sh` propagates `infra-verification.md` to all adapters
- [ ] `git diff adapters/` shows the new rule in all adapter outputs
- [ ] Codex AGENTS.md stays under 32 KiB

### Task 7: Verify [All]

- [ ] Run: `bash scripts/generate.sh` — clean exit
- [ ] Run: `git diff --exit-code adapters/` — shows expected changes only
- [ ] Run: `bash tests/test-shared-structure.sh` — all existing tests pass
- [ ] Run: `bash tests/test-generate.sh` — all existing tests pass
- [ ] Run: `bash tests/test-hooks.sh` — all existing tests pass
- [ ] Run: `bash scripts/validate-spec.sh --feature-id infra-verification-gate` — passes
- [ ] Total: 834+ existing tests green
- [ ] Manual pilot: create a Dockerfile in a test project, verify the hook detects and runs it

## File Ownership (Non-Overlapping)

| Agent / Owner | Files |
|---|---|
| Rules agent | `shared/rules/on-demand/infra-verification.md`, `shared/rules/on-demand/phase-workflow.md` |
| Integration-testing agent | `claude_code/.claude/rules-library/integration-testing.md` |
| Agent-manifest agent | `adapters/claude-code/.claude/agents/build.md` |
| Hook agent | `claude_code/.claude/hooks/verify-on-stop.sh` |
| Pipeline agent | `scripts/generate.sh` |

## Risk

- `verify-on-stop.sh` modification could break existing hook behavior → mitigate by running full test suite after, plus manual test of existing test-runner detection
- Docker commands in the hook could hang → mitigate with timeout wrapper (reuse existing `$TIMEOUT_CMD` pattern from the hook)
- `docker compose up` could leave orphaned containers on failure → mitigate with `trap` to ensure `docker compose down -v` always runs
- Codex AGENTS.md could exceed 32 KiB with the new rule → verify size after generation
- Machines without Docker installed → graceful skip with warning, not a hard failure
