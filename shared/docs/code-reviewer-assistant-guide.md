# Getting Started with Code Reviewer Assistant

The Code Reviewer Assistant is a peer review system that uses a separate LLM to review work produced by the primary AI Copilot. The reviewer runs in a read-only sandbox and produces structured findings that the builder addresses in an iterative loop.

## Quick Start

### 1. Enable Peer Review

```bash
./claude-code --peer-review ~/my-project
```

Options:
- `--peer-review [provider]` — enable with optional provider override
- `--peer-review-scope code|design|both` — review focus (default: `both`)
- `--review-commits single|per-round|squash` — commit strategy (default: `squash`)
- `--review-max-rounds N` — max review rounds before circuit breaker (default: 5)

### 2. Configure Providers

Providers are configured in `~/.code-copilot-team/providers.toml`. Run setup to create the default profile:

```bash
bash adapters/claude-code/setup.sh
```

Or add providers interactively:

```bash
bash adapters/claude-code/setup.sh --configure-providers
```

Four provider types are supported:
- **cli** — local CLI tools (Codex, Aider)
- **openai-compatible** — any OpenAI-compatible HTTP endpoint
- **ollama** — Ollama instances (local or remote)
- **custom** — arbitrary command templates

### 3. Check Provider Health

```bash
providers-health.sh
```

## How It Works

### Build Phase — Review Loop

1. Build agent completes work and commits
2. Agent runs `/review-submit`
3. Runner spawns reviewer in a read-only sandbox
4. Reviewer returns structured findings with a verdict
5. On **FAIL**: agent addresses findings, commits fixes, runs `/review-submit` again
6. On **PASS**: proceed to `/phase-complete`
7. On **BREAKER**: agent stops, human runs `/review-decide approve|reject|retry`

### Plan Phase — Advisory Review

Plan review is single-round and advisory. A FAIL verdict is logged but does not block Build entry.

## Commands

| Command | Who runs it | What it does |
|---------|-----------|--------------|
| `/review-submit` | Agent | Start or continue the review loop |
| `/review-decide approve\|reject\|retry` | Human | Resolve a circuit breaker |
| `/phase-complete` | Agent | Signal phase completion (validates review passed) |

## Circuit Breakers

All breakers escalate to human — no automatic acceptance of unresolved work.

| Breaker | Default | Env Var |
|---------|---------|---------|
| Max rounds | 5 | `CCT_REVIEW_MAX_ROUNDS` |
| Wall-clock timeout | 15 min | `CCT_REVIEW_TIMEOUT_SEC` |
| Stale findings | 2 consecutive | `CCT_REVIEW_STALE_THRESHOLD` |
| Provider unavailable | — | — |

When a breaker fires, the human runs `/review-decide`:
- **approve** — accept current state, bypass logged
- **reject** — abort, no merge
- **retry** — reset breaker, continue loop (rounds remain monotonic)

## File Protocol

All review state lives under `.cct/review/` during the active loop:

| File | Purpose |
|------|---------|
| `state.json` | Loop state (round, attempt, accumulated findings) |
| `findings-round-N.json` | Structured findings for round N |
| `resolution-round-N.json` | Builder's response to findings |
| `breaker-tripped.json` | Breaker context (when tripped) |
| `decision.json` | Human's decision (approve/reject/retry) |
| `loop-summary.json` | Final record on completion |

On completion, the collaboration artifact is written to `specs/<feature-id>/collaboration/`:
- `build-review.md` — build phase review
- `plan-consult.md` — plan phase advisory review

## CI Validation

`validate-collaboration.sh` runs in CI and enforces:
- Build review: PASS or approved bypass required
- Plan review: advisory (warns, doesn't block)
- Bypass without logged breaker type fails

## Safety Model

- **Read-only sandbox** — reviewer runs in a `cp -R` snapshot, cannot modify the real repo
- **Fail-closed** — `/phase-complete` requires PASS; stop hook blocks if review started but incomplete
- **Stable finding IDs** — SHA-256 of (file + category + description), line-number independent
- **Audit trail** — all rounds, findings, dispositions, and decisions recorded in `.cct/review/`
