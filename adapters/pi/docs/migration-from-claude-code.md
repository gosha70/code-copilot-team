# Migrating from Claude Code to Pi

Practical guide for teams already running CCT on Claude Code. The short version:
**the engineering contract is the same** (SDD, phases, permissions, review,
verification), the *mechanism* differs (Pi runs a runtime extension instead of
native agents/hooks), and a few capabilities are honestly `degraded` because Pi
lacks the underlying primitive.

The authoritative per-capability comparison is the generated matrix:
[`../../../shared/capabilities/COMPATIBILITY.md`](../../../shared/capabilities/COMPATIBILITY.md)
(Pi vs Claude Code, status × implementation kind, with verbatim reasons). This
guide is the narrative.

## What maps directly (same behavior)

| Claude Code | Pi | Notes |
|---|---|---|
| SDD classification + phase workflow | `workflow.sdd` / `workflow.phases` | same contract; both `enabled`. Cross-adapter contract tests assert agreement. |
| permission profiles (`permissions/*.json`) | the permission engine | imported via `importClaudePermissions()` — allow/ask/deny, bare tools, `Bash(<prefix>:*)`, path-scoped denies. Entries with no faithful Pi target are reported, never silently dropped. |
| protected paths | `security.protected_paths` + the path matcher | traversal/symlink-safe. |
| `.claude/agents/*.md` subagents | agent **manifests** (`importClaudeAgents()`) | frontmatter → neutral manifest; model tier carried verbatim; fields Claude can't express are flagged not-sourced. |
| peer review | the provider-neutral review runner | same review-artifact contract. |
| skills + prompts | generated into `adapters/pi/resources/` | same `shared/` source. |

## What is degraded on Pi (and why)

Pi is **Enforced** but honest. These are `degraded` — they work, with a named
limitation, not a fake:

| Capability | Degraded because | Practical impact |
|---|---|---|
| `verification.enforcement` / `review.enforcement` | **no Pi Stop event** — gates fire at explicit CCT actions (`/cct:phase-complete`, review→next), not session end | run the gate command; don't rely on an automatic stop hook |
| `memory.session-state` | **no observable compaction event** — checkpoints at explicit actions, recovery at session_start | durable, but not a true pre-compaction hook |
| `security.sandbox` | Pi **cannot create a sandbox** — it detects + rejects | run under a container/micro-VM/remote sandbox and declare `CCT_SANDBOX=...` |
| `agents.subagents` | **no native subagent primitive** — out-of-process `pi --mode json` children | model/thinking/tools/isolation/timeout/cancel enforced; permissions/skills reported not-enforced |
| `agents.teams` | **no team primitive** — coordination state + separate runners + polled message log | identities/claiming/approval/shutdown enforced; live transport/UI is not |
| `integrations.mcp` | live JSON-RPC flows through Pi's own transport | opt in with `integrations.mcp.enabled` |

## What is Pi-native (different from Claude Code)

- **The launcher** `pi-code` wraps upstream `pi` (version-gated, recursion-guard,
  `--no-cct`, `--profile`, `--project`, `--` passthrough).
- **In-process trust resolution** (FR-004a) instead of Claude's native trust.
- **The runtime is a Pi extension** (`pi --extension`), so enforcement is a
  `tool_call` gate, not shell hooks. Existing CCT shell hooks are reused as
  subprocesses where the semantics match.
- **`--mode json` / print / RPC** headless operation for CI, SDK, and autonomous
  runs.

## A sensible migration path

1. `pi install …@<tag>` for advisory content; confirm skills/prompts feel right.
2. `./scripts/setup.sh --pi`; `pi-code doctor` until green.
3. `pi-code features` — read the honest capability report; note the `degraded`
   rows above so expectations match reality.
4. Import your Claude permission profile / agents (the importers are pure
   converters; check the reported warnings).
5. Start with `--profile disciplined`; move to `review-heavy` / `autonomous`
   deliberately (autonomous requires an isolation policy — see the security
   model).
