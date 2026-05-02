---
spec_mode: full
feature_id: code-reviewer-assistant
risk_category: integration
justification: "Cross-session, cross-provider orchestration layer introducing bidirectional LLM communication, circuit breakers, and commit-strategy modes. Touches hooks, runner, rules, agent manifests, launcher, and generation pipeline. Replaces/completes the partially-implemented peer-review system."
status: approved
date: 2026-03-28
---

# Implementation Plan: Code Reviewer Assistant

**Branch**: `code-reviewer-assistant`
**Input**: Existing peer-review scaffolding (`peer-review-runner.sh`, `peer-review-on-stop.sh`, `provider-collaboration-protocol.md`), Ralph/Sonic Loop patterns, Sprint 2 incident review

## Summary

Replace the partially-implemented peer-review system with a fully functional **Code Reviewer Assistant** — a separate, read-only LLM that reviews plan artifacts and build increments produced by the primary AI Copilot. The review loop follows the Ralph/Sonic Loop pattern: the primary session produces work → a separate reviewer session critiques it → findings return to the primary session for resolution → updated work goes back for re-review. The loop continues until the reviewer passes or a circuit breaker fires.

The implementation is **provider-agnostic** (Claude ↔ Codex, Claude ↔ Ollama, Claude ↔ remote GPU host, any combination), includes **configurable circuit breakers** to prevent infinite recursion, and offers **three commit-strategy modes** for managing the review-fix cycle.

## Problem Statement

1. **Peer-review doesn't work.** The current system is ~70% built but non-functional end-to-end. Key gaps: no actual provider backends, missing CI validator (`validate-collaboration.sh`), no failure-resolution workflow, runtime bugs (env vars lost in tmux, invisible banner), and no dedicated runner tests.

2. **No review loop.** The existing design is fire-and-forget: trigger review → get verdict → block on FAIL. There's no mechanism for the primary session to receive findings, address them, and re-submit for review.

3. **No recursion safety.** Without circuit breakers, a disagreeable reviewer and an over-eager builder could loop indefinitely.

4. **No commit-strategy flexibility.** Teams have different preferences: some want a clean single commit, others want an audit trail of each review round.

5. **Provider configuration is too rigid.** The current `providers.toml` only supports a flat command template. Real-world setups include local CLI tools, remote LLMs on LAN (e.g., GDX Spark), and cloud APIs — each with different connectivity, auth, and prompt formatting needs.

## Technical Context

**Language/Version**: Bash (hooks, scripts, launcher), Markdown (rules, agent manifests, commands)
**Primary Dependencies**: `peer-review-runner.sh`, `peer-review-on-stop.sh`, `provider-collaboration-protocol.md`, `phase-workflow.md`, `ralph-loop.md`, `build.md` agent manifest, `scripts/generate.sh`
**Testing**: `test-hooks.sh` (existing peer-review-on-stop tests), new `test-peer-review.sh`, new `test-review-loop.sh`
**Constraints**: All shared rule changes flow through `shared/ → generate.sh → adapters/`. Agent manifest changes are Claude Code adapter-specific. Reviewer session must be **read-only** (no commits, no file writes to working tree).

---

## Current State Audit

### What Exists (keep and extend)

| Component | Status | Lines | Notes |
|-----------|--------|-------|-------|
| `scripts/peer-review-runner.sh` | Implemented | 288 | Marker parsing, provider resolution, verdict extraction, artifact writing |
| `adapters/claude-code/.claude/hooks/peer-review-on-stop.sh` | Implemented | 103 | Loop guard, feature flag, staleness check, runner invocation |
| `adapters/claude-code/claude-code` launcher flags | Implemented | ~20 | `--peer-review`, `--peer-review-off`, `--peer-review-scope` |
| `adapters/claude-code/.claude/commands/phase-complete.md` | Implemented | 52 | Marker creation, post-phase checklist |
| `shared/rules/on-demand/provider-collaboration-protocol.md` | Implemented | 110 | Session flags, marker contract, artifact schema |
| `shared/templates/provider-profile-template.toml` | Implemented | 35 | Provider command templates, healthcheck, timeout |
| `scripts/providers-health.sh` | Implemented | 109 | Provider availability diagnostics |
| `tests/test-hooks.sh` (peer-review section) | Implemented | ~25 cases | Hook-level tests only |

### What's Broken or Missing (fix or build)

| Gap | Severity | Action |
|-----|----------|--------|
| No actual provider backends | **Critical** | Build provider adapters (Phase 1) |
| No review loop / resolution workflow | **Critical** | New: agent-driven loop via `/review-submit` + `review-round-runner.sh` (Phase 2) |
| No structured finding schema | **Critical** | New: finding IDs, severities, dispositions, resolution protocol (Phase 2) |
| No reviewer read-only enforcement | **Critical** | New: snapshot/bind-mount sandbox, post-review validation (Phase 2) |
| No circuit breakers | **Critical** | New: human-decision escalation, not fail-open (Phase 2) |
| No commit-strategy modes | **High** | New: single-commit / per-round / squash with lifecycle rules (Phase 2) |
| Provider config too rigid for diverse topologies | **High** | Redesign providers.toml (Phase 1) |
| `validate-collaboration.sh` missing | **High** | Implement CI gate (Phase 3) |
| `test-peer-review.sh` missing | **High** | Implement runner tests (Phase 3) |
| Env vars lost in tmux | **Medium** | Fix launcher env propagation (Phase 1) |
| Banner invisible in tmux | **Low** | Fix banner timing (Phase 1) |
| Collaboration template not wired | **Low** | Wire into init flow (Phase 3) |
| Other adapters lack peer-review | **Low** | Generate advisory content (Phase 4) |

---

## Architecture

### Review Loop (Ralph/Sonic Pattern)

```
┌──────────────────────┐         ┌───────────────────────┐
│  PRIMARY SESSION     │         │  REVIEWER SESSION     │
│  (Read-Write)        │         │  (Read-Only)          │
│                      │         │                       │
│  1. Produce work     │────────▶│  2. Review changes    │
│     (plan or code)   │  diff   │     (read-only LLM)   │
│                      │         │                       │
│  4. Address findings │◀────────│  3. Return verdict    │
│     (fix/explain)    │ findings│     + findings list   │
│                      │         │                       │
│  5. Re-submit        │────────▶│  6. Re-review delta   │
│     (if not passed)  │  diff   │     (focused scope)   │
│                      │         │                       │
│  ... loop until PASS │         │  ... or circuit break │
│  or circuit breaker  │         │                       │
└──────────────────────┘         └───────────────────────┘
```

### Session Handoff Contract

The review loop is **driven by the Build agent** within the active primary session. There is no long-running orchestrator process. Each review round is a discrete, stateless subprocess call. Loop state is maintained in `.cct/review/` files, not in process memory.

This avoids the stop-hook deadlock: the agent is never blocked by a hook while also needing to do work. The agent calls out to the reviewer, gets results back, and keeps working.

```
┌───────────────────────────────────────────────────────────────┐
│  PRIMARY SESSION (active, agent-driven)                       │
│                                                               │
│  1. Builder completes work, runs /review-submit               │
│     → writes .cct/review/pending.json                         │
│     → invokes review-round-runner.sh (synchronous subprocess) │
│     → runner spawns REVIEWER in read-only sandbox             │
│     → runner captures output, writes:                         │
│       .cct/review/findings-round-N.json                       │
│     → runner returns exit code + verdict to agent             │
│                                                               │
│  2. If verdict == PASS → runner writes loop-summary.json      │
│     → agent continues to /phase-complete (normal flow)        │
│                                                               │
│  3. If verdict == FAIL → agent reads findings-round-N.json    │
│     → agent addresses each finding (fix / dispute / defer)    │
│     → agent writes resolution-round-N.json                    │
│     → agent commits fixes                                     │
│     → agent runs /review-submit again (next round)            │
│                                                               │
│  4. If circuit breaker trips → runner writes                  │
│     .cct/review/breaker-tripped.json                          │
│     → agent prints breaker context to user                    │
│     → agent STOPS and waits for human to run                  │
│       /review-decide approve|reject|retry                     │
│     → on approve: agent writes loop-summary with bypass log   │
│     → on reject: agent aborts, no merge                       │
│     → on retry: agent runs /review-submit again               │
│                                                               │
│  STOP HOOK (peer-review-on-stop.sh) — role changed:           │
│  → Does NOT initiate review                                   │
│  → Validates that loop-summary.json exists with verdict PASS  │
│    (or an approved bypass)                                     │
│  → Blocks session stop if review was required but not done    │
└───────────────────────────────────────────────────────────────┘
```

**Why agent-driven, not orchestrator-driven**: The orchestrator-outside-both-sessions model creates a deadlock. The stop hook is synchronous — it blocks the session until it returns. A long-running orchestrator launched from the stop hook cannot hand work back to the blocked primary session. By making the agent the loop driver, every review round is a simple call-and-return: the agent calls `review-round-runner.sh`, it returns findings, the agent acts on them, and calls again. No process needs to outlive a single round.

**Reviewer read-only enforcement** (Phase 2, not Phase 4):
The `review-round-runner.sh` spawns the reviewer subprocess in a restricted environment:
- Working directory is a **snapshot copy** (macOS: `cp -R` to temp dir; Linux: read-only bind mount or `cp -R`)
- `GIT_DIR` pointed at the snapshot (reviewer cannot affect real repo)
- No SSH/GPG agent forwarding (prevents signing commits)
- Reviewer process runs with `CCT_READ_ONLY=true` in its environment
- Runner validates post-review: compares snapshot state to pre-review state. If any files changed, the round is marked INVALID and findings are discarded

This is enforced from the first review round in Phase 2, not deferred to Phase 4.

**File protocol**:

| File | Written By | Read By | Purpose |
|------|-----------|---------|---------|
| `.cct/review/pending.json` | Agent (via /review-submit) | review-round-runner.sh | Round metadata: feature_id, phase, round number, provider |
| `.cct/review/findings-round-N.json` | review-round-runner.sh | Build agent | Structured findings for this round |
| `.cct/review/resolution-round-N.json` | Build agent | review-round-runner.sh (next round) | Builder's response to each finding |
| `.cct/review/breaker-tripped.json` | review-round-runner.sh | Build agent → human | Breaker context, awaiting `/review-decide` |
| `.cct/review/decision.json` | `/review-decide` command | review-round-runner.sh (on retry) | Human's decision: approve, reject, or retry |
| `.cct/review/loop-summary.json` | review-round-runner.sh (on PASS) or agent (on approved bypass) | Stop hook, CI gate | Final record of all rounds, verdicts, dispositions |
| `.cct/review/state.json` | review-round-runner.sh | review-round-runner.sh | Persistent loop state: current round, accumulated findings, breaker counters, timing |

### Structured Finding Schema

Every finding has a stable identity and a lifecycle. This enables the stale-findings breaker, focused delta re-review, and auditable resolution tracking.

**Finding object** (in `findings-round-N.json`):

```json
{
  "round": 2,
  "verdict": "FAIL",
  "reviewer_provider": "gdx-spark",
  "findings": [
    {
      "id": "f-a1b2c3d4",
      "severity": "blocking",
      "category": "correctness",
      "file": "src/auth/login.sh",
      "line_hint": "near variable expansion in query function",
      "description": "Unquoted variable expansion in SQL query allows injection",
      "suggested_fix": "Use parameterized query or quote with printf %q",
      "first_seen_round": 1,
      "disposition": null
    },
    {
      "id": "f-e5f6g7h8",
      "severity": "warning",
      "category": "style",
      "file": "src/auth/login.sh",
      "line_hint": "checkAuth function definition",
      "description": "Function name doesn't follow project snake_case convention",
      "suggested_fix": "Rename checkAuth to check_auth",
      "first_seen_round": 2,
      "disposition": null
    }
  ]
}
```

**Finding ID**: SHA-256 truncated to 8 hex chars of `(file + category + normalized_description)`. **Line numbers are excluded from the fingerprint** because edits between rounds shift line numbers, which would give the same logical issue a different ID and break stale-finding detection and resolution tracking.

- `file`: path relative to project root
- `category`: semantic category (correctness, security, style, performance, design, etc.)
- `normalized_description`: description lowercased, whitespace-collapsed, line-number references stripped

The `line_hint` field is **display-only** — it helps the builder locate the issue but does not contribute to the ID. It uses semantic anchors ("near variable expansion in query function") rather than numeric line references where possible, falling back to line numbers as a convenience hint only.

**Severity levels**:

| Severity | Blocks PASS? | Builder must respond? |
|----------|-------------|----------------------|
| `blocking` | Yes | Yes — must set disposition to `fixed` or `disputed` |
| `warning` | No | Optional — can acknowledge or ignore |
| `note` | No | No — informational only |

**Resolution object** (in `resolution-round-N.json`):

```json
{
  "round": 2,
  "resolutions": [
    {
      "finding_id": "f-a1b2c3d4",
      "disposition": "fixed",
      "detail": "Replaced string interpolation with parameterized query at line 45",
      "commit_ref": "abc1234"
    },
    {
      "finding_id": "f-e5f6g7h8",
      "disposition": "disputed",
      "detail": "Function is part of public API; renaming would break callers. Filed as tech-debt issue #142."
    }
  ]
}
```

**Disposition values**:

| Disposition | Meaning | Reviewer behavior on re-review |
|-------------|---------|-------------------------------|
| `fixed` | Builder addressed the finding | Reviewer verifies the fix; drops finding if resolved |
| `disputed` | Builder disagrees with the finding | Reviewer re-evaluates; may downgrade, sustain, or escalate |
| `deferred` | Builder acknowledges but will fix later | Reviewer accepts for this round; finding logged in loop-summary |
| `not-applicable` | Finding doesn't apply (e.g., wrong file) | Reviewer drops the finding |

**Stale-findings breaker**: If a finding with the same ID appears in N consecutive rounds (default: 2) with disposition `fixed` each time (builder thinks they fixed it, reviewer disagrees), the finding is marked `stale` in `state.json`. **Stale findings do not auto-downgrade.** They remain blocking. When the stale threshold is reached, the breaker fires and **escalates to human decision** — same as every other breaker. The human sees which specific findings are stale and can approve (accepting the disagreement), reject, or retry.

This ensures there is **no path to automatic acceptance of unresolved reviewer disagreement**, regardless of how many rounds pass.

### Circuit Breakers

Circuit breakers **do not silently accept unreviewed work**. Every breaker escalates to the human for an explicit decision. The agent stops working and waits for the human to run `/review-decide`.

| Breaker | Default | Config Key | Behavior on Trip |
|---------|---------|------------|------------------|
| Max review rounds | 5 | `CCT_REVIEW_MAX_ROUNDS` | **Escalate**: write `breaker-tripped.json`, agent stops, wait for `/review-decide` |
| Max total review time | 15 min | `CCT_REVIEW_TIMEOUT_SEC` | **Escalate**: write `breaker-tripped.json`, agent stops, wait for `/review-decide` |
| Stale findings | 2 consecutive rounds | `CCT_REVIEW_STALE_THRESHOLD` | **Escalate**: write `breaker-tripped.json` listing stale finding IDs, agent stops, wait for `/review-decide` |
| Provider unreachable (all fallbacks exhausted) | — | — | **Escalate**: write `breaker-tripped.json` with `"reason": "provider_unavailable"`, wait for `/review-decide` |

**Human decision channel**: The `/review-decide` command (new Claude Code command). The human runs `/review-decide approve`, `/review-decide reject`, or `/review-decide retry` within the active session. The command writes `.cct/review/decision.json` and the Build agent reads it to determine next action. This replaces the previous environment-variable-based approach, which cannot work because a running process cannot observe env vars set after its launch.

| Decision | Effect |
|----------|--------|
| `/review-decide approve` | Accept current state. Agent writes `loop-summary.json` with `bypass: true`, breaker type, and unresolved findings. Proceeds to `/phase-complete`. |
| `/review-decide reject` | Abort. Agent logs rejection in `loop-summary.json`. No merge. |
| `/review-decide retry` | Reset round counter and breaker state. Agent runs `/review-submit` again. Useful after fixing provider connectivity or after manually addressing the stale disagreement. |

**`breaker-tripped.json`** includes full context for the human:

```json
{
  "breaker": "stale_findings",
  "rounds_completed": 4,
  "unresolved_blocking_findings": 2,
  "stale_findings": [
    {
      "id": "f-a1b2c3d4",
      "description": "Unquoted variable expansion in SQL query allows injection",
      "rounds_seen": [1, 2, 3, 4],
      "builder_dispositions": ["fixed", "fixed", "fixed", "fixed"],
      "reviewer_persisted": true
    }
  ],
  "last_verdict": "FAIL",
  "action": "Run /review-decide approve|reject|retry"
}
```

### Commit-Strategy Modes

| Mode | Flag Value | Behavior |
|------|-----------|----------|
| **Single commit** | `--review-commits single` | Amend the same commit each round. Final state is one clean commit. |
| **Per-round commits** | `--review-commits per-round` | Each fix round creates a new commit (`fix(review): round N — ...`). Full audit trail. |
| **Squash on pass** | `--review-commits squash` | Per-round commits during the loop, auto-squash into one commit when reviewer passes. Best of both worlds. (Default) |

**Commit lifecycle rules**:

1. **First commit ownership**: The primary Build agent creates the initial commit as part of its normal workflow *before* review starts. The review loop operates on commits that already exist — it never creates the first commit.

2. **Review-round commits**: Before running `/review-submit` for the next round, the Build agent must have committed its fixes. The agent manifest instructs it to commit with message format: `fix(review): round N — <summary of changes>`. In `single` mode, the builder amends the previous commit instead. The `review-round-runner.sh` checks for uncommitted changes before starting the review and rejects with a clear error if the worktree is dirty.

3. **User approval**: The review system does **not** auto-commit on behalf of the user. The Build agent commits (following its existing commit-gate rules from `phase-workflow.md`). Squash operations happen after the final PASS via `git reset --soft` to the pre-review commit followed by a single `git commit` — no interactive rebase.

4. **Dirty worktree handling**: If the builder runs `/review-submit` with uncommitted changes, `review-round-runner.sh` exits with error code and message: `"error": "uncommitted_changes — commit or stash before submitting for review"`. The agent reads this and acts accordingly.

5. **Plan-review rounds**: **Product decision**: Commit strategies apply **only to Build phase** review. Plan-phase review is **advisory and single-round** — it does not gate Build entry. This is a deliberate narrowing from the original dual-mode protocol in `provider-collaboration-protocol.md`, which expected a passing `plan-consult.md` before Build. The rationale: plan artifacts are already approved by the human via the Plan Approval Gate (SDD Sprint 1) before Build begins, so the external reviewer's input on plans is supplementary, not authoritative. If this decision is revisited, extending plan review to multi-round gating is a Phase 4 item — the file protocol and finding schema support it, only the agent manifest instructions and stop-hook validation would need to change.

6. **Squash failure recovery**: If `git reset --soft` fails (e.g., upstream changes), the agent falls back to creating a merge commit with message `chore(review): squash failed, merge commit for review rounds 1-N` and logs a warning. It does not force-reset or lose work.

---

## Provider Configuration Architecture

### Design Principles

1. **Shell command is the universal interface.** Every provider ultimately resolves to a shell command. This keeps the runner simple and provider-agnostic.
2. **Typed providers reduce boilerplate.** Common topologies (CLI tool, OpenAI-compatible API, Ollama) get first-class `type` support with sensible defaults.
3. **Environment variables for secrets.** API keys never live in the TOML. The config references env var names; the runner resolves them at invocation time.
4. **Profiles are composable.** A user can define multiple providers and switch between them per-session with `--peer-review <name>`.
5. **Healthcheck validates the full path.** For remote providers, healthcheck must verify network reachability, not just binary existence.

### Provider Topologies

The framework supports three provider types, each with a dedicated configuration shape:

#### Type 1: `cli` — Local CLI Tool

For tools installed on the same machine (Codex CLI, Claude Code in headless mode, Aider).

```toml
[providers.codex]
type = "cli"
command = "codex --model o4-mini --quiet --prompt-file {review_request}"
timeout_sec = 300
healthcheck = "codex --version"
```

The `command` template receives `{review_request}` (path to temp file with review prompt) and `{model}` (optional model override). Output is captured from stdout.

#### Type 2: `openai-compatible` — HTTP API (Local or Remote)

For any OpenAI-compatible endpoint: OpenAI itself, Azure OpenAI, vLLM, llama.cpp server, text-generation-inference, GDX Spark hosting an OpenAI-compatible server, LM Studio, etc.

```toml
[providers.gdx-spark]
type = "openai-compatible"
base_url = "http://192.168.1.50:8000/v1"     # LAN address of GDX Spark
api_key_env = "GDX_SPARK_API_KEY"              # env var name (not the key itself)
model = "deepseek-coder-v2"
timeout_sec = 600
max_tokens = 4096
temperature = 0.2
healthcheck = "curl -sf http://192.168.1.50:8000/v1/models"

[providers.openai]
type = "openai-compatible"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
model = "gpt-4o"
timeout_sec = 300
max_tokens = 4096
temperature = 0.1
healthcheck = "curl -sf -H 'Authorization: Bearer $OPENAI_API_KEY' https://api.openai.com/v1/models | jq -e '.data | length > 0'"

[providers.azure-openai]
type = "openai-compatible"
base_url = "https://mycompany.openai.azure.com/openai/deployments/gpt-4o"
api_key_env = "AZURE_OPENAI_API_KEY"
model = "gpt-4o"
timeout_sec = 300
extra_headers = "api-version=2024-02-01"
healthcheck = "curl -sf -H 'api-key: $AZURE_OPENAI_API_KEY' '$base_url?api-version=2024-02-01'"
```

For `openai-compatible` providers, the runner constructs the API call internally using a provider adapter script (`scripts/provider-adapters/openai-compatible.sh`). This script:
- Reads `base_url`, resolves `api_key_env` from environment
- Formats the review request as a chat completion (`messages: [{role: "user", content: ...}]`)
- Sends via `curl` with proper headers
- Extracts the assistant response from the JSON
- Returns it to stdout for the runner to parse

#### Type 3: `ollama` — Ollama-Specific

Ollama has its own CLI and API conventions. While it *can* be reached via `openai-compatible` (Ollama exposes an OpenAI-compatible endpoint), the native CLI is simpler for local use.

```toml
[providers.ollama]
type = "ollama"
model = "llama3.1:70b"
timeout_sec = 600
host = "localhost:11434"                       # default; override for remote Ollama
healthcheck = "ollama list"

[providers.ollama-remote]
type = "ollama"
model = "codellama:34b"
timeout_sec = 900
host = "192.168.1.50:11434"                    # Ollama running on GDX Spark
healthcheck = "curl -sf http://192.168.1.50:11434/api/tags"
```

For `ollama` providers, the runner uses `scripts/provider-adapters/ollama.sh` which:
- Uses `ollama run {model}` for local (when `host` is localhost)
- Uses `curl` to the Ollama HTTP API for remote hosts
- Sets `OLLAMA_HOST` env var if non-default host specified

#### Type 4: `custom` — Escape Hatch

For anything else: proprietary APIs, SSH tunnels to remote machines, Docker containers, MCP servers, etc.

```toml
[providers.my-custom-reviewer]
type = "custom"
command = "ssh gpubox 'cd /opt/reviewer && python review.py --input {review_request}'"
timeout_sec = 900
healthcheck = "ssh gpubox 'nvidia-smi' 2>/dev/null"
```

`custom` behaves exactly like the current flat `command` template — full backward compatibility.

### Defaults and Fallback Chain

```toml
[defaults]
# Primary mapping: when using Claude as subject, who reviews?
peer_for.claude = "codex"
peer_for.codex = "claude"

# Fallback chain: if primary peer is unavailable, try these in order
fallback_chain.claude = ["openai", "ollama", "gdx-spark"]
fallback_chain.codex = ["ollama"]
```

When the runner can't reach the primary peer (healthcheck fails), it walks the fallback chain and uses the first available provider. This prevents sessions from blocking when a single provider is down.

### Provider Resolution Flow

```
1. User runs: ./claude-code --peer-review gdx-spark ~/project
   └─ Explicit provider name → use [providers.gdx-spark]

2. User runs: ./claude-code --peer-review ~/project
   └─ No name → look up defaults.peer_for.claude → "codex"
   └─ Healthcheck [providers.codex]
      ├─ PASS → use codex
      └─ FAIL → walk defaults.fallback_chain.claude
               → try "openai" → healthcheck → PASS → use openai
               → try "ollama" → healthcheck → ...

3. User runs: ./claude-code --peer-review-off ~/project
   └─ Skip peer review entirely
```

### Provider Adapter Scripts

Each provider type gets a dedicated adapter script in `scripts/provider-adapters/`:

```
scripts/provider-adapters/
├── openai-compatible.sh   # Handles all OpenAI-compatible APIs (local & cloud)
├── ollama.sh              # Handles Ollama CLI and HTTP API
└── README.md              # How to add a new provider adapter
```

CLI and custom types don't need adapter scripts — the runner executes their `command` directly.

The runner dispatches based on `type`:

```bash
case "$PROVIDER_TYPE" in
    cli|custom)
        # Execute command template directly (existing behavior)
        REVIEW_OUTPUT=$(bash -c "$RESOLVED_CMD" 2>&1)
        ;;
    openai-compatible)
        # Delegate to adapter script
        REVIEW_OUTPUT=$(scripts/provider-adapters/openai-compatible.sh \
            --base-url "$BASE_URL" \
            --api-key-env "$API_KEY_ENV" \
            --model "$MODEL" \
            --max-tokens "$MAX_TOKENS" \
            --temperature "$TEMPERATURE" \
            --input "$REVIEW_REQUEST" 2>&1)
        ;;
    ollama)
        REVIEW_OUTPUT=$(scripts/provider-adapters/ollama.sh \
            --model "$MODEL" \
            --host "$HOST" \
            --input "$REVIEW_REQUEST" 2>&1)
        ;;
esac
```

### Interactive Setup

`scripts/setup.sh --configure-providers` walks the user through provider setup:

```
$ ./scripts/setup.sh --configure-providers

Code Copilot Team — Provider Configuration
═══════════════════════════════════════════

Current providers in ~/.code-copilot-team/providers.toml:
  (none configured)

Add a provider? [y/N] y

Provider name (e.g., codex, ollama, openai, my-gpu): gdx-spark

Provider type:
  1. cli           — Local CLI tool (codex, aider, etc.)
  2. openai-compatible — Any OpenAI-compatible API (OpenAI, Azure, vLLM, LM Studio, GDX Spark)
  3. ollama        — Ollama (local or remote)
  4. custom        — Custom shell command

Choice: 2

Base URL: http://192.168.1.50:8000/v1
Model name: deepseek-coder-v2
API key environment variable (leave blank if none): GDX_SPARK_API_KEY
Timeout (seconds) [300]: 600

Testing connection... ✓ Reachable (3 models available)

Set as default reviewer for Claude sessions? [Y/n] y

✓ Provider 'gdx-spark' configured
✓ Default peer for claude: gdx-spark

Add another provider? [y/N] n
```

---

## Scope — Phased Implementation

### Phase 1: Fix Foundations & Provider Config (Prerequisite)

**Goal**: Make the existing peer-review infrastructure actually work with diverse provider topologies.

| # | Task | Files | Est. |
|---|------|-------|------|
| 1.1 | Redesign `providers.toml` with typed providers (`cli`, `openai-compatible`, `ollama`, `custom`) | `shared/templates/provider-profile-template.toml` | M |
| 1.2 | Create `openai-compatible.sh` provider adapter (curl-based, handles auth, chat completions format) | `scripts/provider-adapters/openai-compatible.sh` (new) | M |
| 1.3 | Create `ollama.sh` provider adapter (CLI for local, HTTP for remote) | `scripts/provider-adapters/ollama.sh` (new) | M |
| 1.4 | Update `peer-review-runner.sh` with type-based dispatch and fallback chain | `scripts/peer-review-runner.sh` | L |
| 1.5 | Add `--configure-providers` interactive flow to `setup.sh` | `scripts/setup.sh` | M |
| 1.6 | Fix tmux env-var propagation in launcher | `adapters/claude-code/claude-code` | S |
| 1.7 | Add review banner after tmux attach (not before) | `scripts/peer-review-runner.sh` | S |
| 1.8 | Wire `collaboration-template.md` into `/phase-complete` | `adapters/claude-code/.claude/commands/phase-complete.md` | S |
| 1.9 | Update `providers-health.sh` to handle typed providers and fallback chain | `scripts/providers-health.sh` | S |
| 1.10 | Create `test-peer-review.sh` for runner unit tests (provider dispatch, TOML parsing, fallback) | `tests/test-peer-review.sh` (new) | M |
| 1.11 | End-to-end smoke test: plan review with real provider | manual verification | M |

**Exit criteria**: `./claude-code --peer-review gdx-spark ~/test-project` reaches a real LLM on the network, produces a collaboration artifact with a parseable verdict after `/phase-complete`. Fallback chain engages when primary is unreachable.

### Phase 2: Review Loop, Handoff, & Enforcement (Core Feature)

**Goal**: Implement the agent-driven review loop with structured findings, read-only enforcement, circuit breakers, and commit-strategy modes.

| # | Task | Files | Est. |
|---|------|-------|------|
| 2.1 | Create `review-round-runner.sh` — executes one review round: snapshot working tree, spawn reviewer in read-only sandbox, capture output, parse into structured findings, write `findings-round-N.json`, update `state.json` | `scripts/review-round-runner.sh` (new) | XL |
| 2.2 | Implement reviewer read-only enforcement in runner (snapshot copy on macOS, bind mount on Linux, post-review diff validation, INVALID round on violation) | `scripts/review-round-runner.sh` | L |
| 2.3 | Implement structured finding parser: extract findings from reviewer free-text output into finding objects with stable IDs (`file + category + normalized_description`, no line numbers in fingerprint) | `scripts/review-round-runner.sh` | L |
| 2.4 | Create `review-loop.md` rule — documents agent-driven loop protocol, file contract, finding schema, disposition values, circuit breakers, commit lifecycle, plan-review product decision | `shared/rules/on-demand/review-loop.md` (new) | L |
| 2.5 | Create `/review-submit` command — agent triggers a review round: validates clean worktree, checks breaker state, invokes `review-round-runner.sh`, reads verdict | `adapters/claude-code/.claude/commands/review-submit.md` (new) | M |
| 2.6 | Create `/review-decide` command — human escalation channel: writes `decision.json` with approve/reject/retry, agent reads and acts | `adapters/claude-code/.claude/commands/review-decide.md` (new) | M |
| 2.7 | Add circuit breaker logic in runner: round counter, wall-clock timer, stale-finding detection (by stable ID across rounds), all escalate to human via `breaker-tripped.json` | `scripts/review-round-runner.sh` | M |
| 2.8 | Implement commit-strategy modes with lifecycle rules (first-commit ownership, dirty-worktree rejection, squash via `git reset --soft` on PASS, squash-failure recovery) | `scripts/review-round-runner.sh`, launcher | M |
| 2.9 | Update `peer-review-on-stop.sh` — change role from "start review" to "validate review completed" (check `loop-summary.json` exists with PASS or approved bypass) | `adapters/claude-code/.claude/hooks/peer-review-on-stop.sh` | M |
| 2.10 | Update Build agent manifest: after producing work, run `/review-submit`; on FAIL, read `findings-round-N.json`, address each finding, write `resolution-round-N.json`, commit, run `/review-submit` again; on breaker trip, print context and stop for human | `adapters/claude-code/.claude/agents/build.md` | M |
| 2.11 | Update Plan agent manifest (plan review: single advisory round via `/review-submit`, no fix loop — explicit product decision) | `adapters/claude-code/.claude/agents/plan.md` | S |
| 2.12 | Add launcher flags: `--review-commits`, `--review-max-rounds` | `adapters/claude-code/claude-code` | S |
| 2.13 | Create `test-review-loop.sh` — loop tests with mock provider: agent-driven round trips, finding ID stability across line-shifting edits, stale-finding detection and escalation (not auto-accept), breaker escalation via `/review-decide`, read-only violation detection, commit-strategy correctness, dirty-worktree rejection, stop-hook validation-only behavior | `tests/test-review-loop.sh` (new) | XL |

**Exit criteria**:
- A Build session with `--peer-review codex --review-commits squash` completes a 2-round review loop (first round FAIL with structured findings, builder writes resolution, second round PASS), squashes commits, and produces `loop-summary.json` with full round metadata.
- Reviewer process runs in snapshot copy and cannot modify real working tree or create real commits (verified by test that mutates snapshot and confirms no effect on source).
- Circuit breaker fires at round 5 and **escalates to human** (does not auto-accept); session resumes only after human runs `/review-decide approve`.
- Stale-finding breaker escalates to human (does not downgrade blockers to non-blocking or auto-pass).
- Finding IDs are stable across rounds even when edits shift line numbers: same issue produces same `id` because fingerprint uses `(file + category + normalized_description)`, not line ranges.
- Builder running `/review-submit` with uncommitted changes is rejected with error before reviewer is spawned.
- Stop hook blocks session stop if review was required (`CCT_PEER_REVIEW_ENABLED=true`) but `loop-summary.json` is missing or has non-PASS verdict without approved bypass.

### Phase 3: CI Gate & Governance (Quality Assurance)

**Goal**: Enforce review quality in CI and close audit gaps.

| # | Task | Files | Est. |
|---|------|-------|------|
| 3.1 | Implement `validate-collaboration.sh` — CI gate that distinguishes Build review (gating: PASS or approved bypass required) from Plan review (advisory: FAIL logged but does not block PR) | `scripts/validate-collaboration.sh` (new) | M |
| 3.2 | Update `provider-collaboration-protocol.md` with agent-driven loop semantics, provider types, and plan-review advisory carve-out | `shared/rules/on-demand/provider-collaboration-protocol.md` | M |
| 3.3 | Add bypass audit trail (artifact metadata: `bypass: true`, `breaker: <type>`) | `scripts/review-round-runner.sh` | S |
| 3.4 | Add CI workflow step for collaboration validation | `.github/workflows/` | S |
| 3.5 | Write end-to-end documentation: "Getting Started with Code Reviewer Assistant" | `shared/docs/code-reviewer-assistant-guide.md` (new) | M |

**Exit criteria**: PR with missing or FAIL **Build-phase** review artifacts is rejected by CI. Plan-phase `plan-consult.md` with FAIL verdict is logged as advisory (CI warns but does not block). Bypass events are logged with breaker type.

### Phase 4: Multi-Adapter & Polish (Expansion)

**Goal**: Extend to other adapters, harden edge cases.

| # | Task | Files | Est. |
|---|------|-------|------|
| 4.1 | Generate advisory peer-review content for Cursor, Copilot, Windsurf, Aider adapters | `scripts/generate.sh`, adapter configs | M |
| 4.2 | Add Codex adapter peer-review support (native, not advisory) | `adapters/codex/` | M |
| 4.3 | Add review scope filtering (code-only, design-only, security-focused) | rule + review-round-runner.sh | S |
| 4.4 | Update all existing tests to pass with new components | `tests/test-shared-structure.sh`, `tests/test-generate.sh` | M |

**Exit criteria**: `generate.sh` produces adapter configs that reference review-loop protocol. Codex adapter can act as both primary and reviewer.

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Reviewer and builder disagree indefinitely | High | Session blocked | Circuit breakers escalate to human via `/review-decide`; stale-finding detection identifies the specific disagreement |
| Reviewer hallucinates false findings | Medium | Wasted fix rounds | Structured verdict format, blocking vs. warning distinction |
| Provider timeout during review | Medium | Session hangs | Per-provider timeout in `providers.toml`, runner-level timeout via `timeout`/`gtimeout` |
| Remote provider unreachable (network, GDX Spark off) | Medium | Review blocked | Fallback chain with automatic failover |
| API key exposed in config | Medium | Security breach | Keys stored in env vars only; TOML references var names |
| Commit-squash fails (merge conflicts) | Low | Broken git state | Squash uses `git reset --soft` to replay, not interactive rebase |
| Env var propagation in tmux | Known | Review never triggers | Phase 1 fix (task 1.6) |
| Different OpenAI-compatible APIs have subtle format differences | Medium | Failed reviews | Adapter script handles known variants (Azure headers, etc.) |

---

## Roadmap Position

| Initiative | Status | Priority | Phase | Dependencies |
|-----------|--------|----------|-------|-------------|
| SDD Sprint 1 — Spec Layer | **In Progress** (approved) | P0 | Now | — |
| MemKernel Integration | **Phase 3 remaining** | P1 | Now | — |
| Infrastructure Verification Gate | **Draft** | P1 | Next | SDD Sprint 1 |
| **Code Reviewer Assistant** | **Draft** | **P1** | **Next** | SDD Sprint 1 (for spec templates), existing peer-review scaffolding |
| Multi-adapter peer-review expansion | Not started | P2 | Later | Code Reviewer Assistant Phase 1-3 |

### Capacity Note

Phase 1 (Fix Foundations) can start in parallel with Infrastructure Verification Gate — they touch different files. Phase 2 (Review Loop) should start after Phase 1 exits and after SDD Sprint 1 is merged, since the review loop rule should follow the new spec-workflow conventions.

---

## Success Criteria

1. **Functional**: A complete build→review→fix→re-review→pass cycle works end-to-end with at least two provider combinations (e.g., Claude ↔ GDX Spark, Claude ↔ Ollama local). Plan review completes as a single advisory round (no fix loop).
2. **Multi-topology**: All four provider types (cli, openai-compatible, ollama, custom) can be configured and used as reviewers
3. **Read-only enforced**: Reviewer process cannot modify the working tree or create commits; violations are detected and the round is invalidated
4. **Structured findings**: Every finding has a stable ID, severity, and disposition lifecycle; findings are machine-readable JSON, not free-text parsing
5. **Safe**: Every circuit breaker (round limit, time limit, stale findings, provider failure) escalates to human via `/review-decide` — no path to automatic acceptance of unreviewed or disputed work
6. **Resilient**: Fallback chain engages when primary provider is unreachable; if all providers fail, session escalates to human via `/review-decide` (not silent acceptance)
7. **Flexible**: All three commit-strategy modes produce correct git history with defined lifecycle rules (first-commit ownership, dirty-worktree rejection, squash-failure recovery)
8. **Auditable**: `loop-summary.json` records all rounds, all findings with dispositions, all breaker events, and all bypass decisions
9. **Secure**: No API keys in config files; all secrets resolved from environment at runtime
10. **Enforceable**: CI rejects PRs with missing or failed **Build-phase** review artifacts. Plan-phase advisory reviews with FAIL verdict produce CI warnings but do not block merge. Bypass events are logged with breaker type.
11. **Tested**: 834+ existing tests pass, plus new test suites for `review-round-runner.sh`, finding schema validation, and loop behavior
