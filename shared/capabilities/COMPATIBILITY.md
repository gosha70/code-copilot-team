# CCT Capability Compatibility Matrix

> **GENERATED — do not edit.** Run `scripts/generate-capability-docs.sh` to
> regenerate. Source of truth: `shared/capabilities/catalog.yaml` +
> `pi.yaml` + `claude-code.yaml`. To change a status or its wording, edit the
> registry `reason`, not this file (a drift guard fails the build otherwise).

Two-dimensional classification (FR-029): **implementation kind** (`native` /
`cct-first-party` / `optional-bridge` / `external-platform`) × **runtime
status** (`enabled` / `disabled` / `degraded` / `unavailable` / `misconfigured`
/ `unsupported`). Cells read `status (kind)`.

## Matrix

| Capability | Default | Security | Pi | Claude Code |
|---|---|---|---|---|
| `skills.shared` | disabled | advisory | enabled (native) | enabled (native) |
| `prompts.commands` | disabled | advisory | enabled (native) | enabled (native) |
| `config.layered` | disabled | advisory | enabled (cct-first-party) | degraded (native) |
| `config.trust-gating` | disabled | critical | enabled (cct-first-party) | enabled (native) |
| `workflow.sdd` | disabled | enforcing | enabled (cct-first-party) | enabled (cct-first-party) |
| `workflow.phases` | disabled | enforcing | enabled (cct-first-party) | enabled (cct-first-party) |
| `permissions.engine` | disabled | critical | enabled (cct-first-party) | enabled (native) |
| `permissions.protected-paths` | disabled | critical | enabled (cct-first-party) | enabled (cct-first-party) |
| `providers.pi` | disabled | enforcing | enabled (cct-first-party) | disabled (optional-bridge) |
| `review.enforcement` | disabled | enforcing | degraded (cct-first-party) | enabled (cct-first-party) |
| `verification.enforcement` | disabled | enforcing | degraded (cct-first-party) | enabled (cct-first-party) |
| `integrations.mcp` | disabled | enforcing | degraded (optional-bridge) | enabled (native) |
| `integrations.hosted-platform` | unavailable | none | unavailable (external-platform) | enabled (native) |
| `memory.session-state` | disabled | advisory | degraded (cct-first-party) | enabled (cct-first-party) |
| `security.sandbox` | disabled | enforcing | degraded (cct-first-party) | disabled (cct-first-party) |
| `security.env-scrub` | disabled | enforcing | degraded (cct-first-party) | disabled (cct-first-party) |
| `memory.promotion` | disabled | advisory | degraded (cct-first-party) | enabled (cct-first-party) |
| `agents.subagents` | disabled | advisory | degraded (cct-first-party) | enabled (native) |
| `agents.worktrees` | disabled | advisory | degraded (cct-first-party) | disabled (cct-first-party) |
| `agents.teams` | disabled | advisory | degraded (cct-first-party) | disabled (cct-first-party) |

## Capabilities

### `skills.shared`

Shared CCT skills are discoverable by the agent as first-class instruction resources.

**Default:** disabled · **Security:** advisory · **Claude equivalent:** ~/.claude/skills + rules

- **Pi:** `enabled` (native)
  - _status probe:_ Agent Skills directory present in the installed package resources.
- **Claude Code:** `enabled` (native)
  - _status probe:_ Skills installed under ~/.claude/skills by setup.sh.

### `prompts.commands`

CCT slash commands are available as prompt templates or commands.

**Default:** disabled · **Security:** advisory · **Claude equivalent:** ~/.claude/commands

- **Pi:** `enabled` (native)
  - _status probe:_ Prompt templates present in the installed package resources.
- **Claude Code:** `enabled` (native)
  - _status probe:_ Commands installed under ~/.claude/commands by setup.sh.

### `config.layered`

Configuration resolves through an explicit layer precedence, and every resolved value can be explained with its provenance.

**Default:** disabled · **Security:** advisory · **Claude equivalent:** settings.json precedence (no provenance reporting)

- **Pi:** `enabled` (cct-first-party)
  - _status probe:_ Runtime resolved a layered configuration with provenance.
- **Claude Code:** `degraded` (native) — settings.json resolves through a documented precedence, but resolved values carry no provenance and there is no explain surface.
  - _status probe:_ settings.json present; no provenance API exists to probe.

### `config.trust-gating`

Project-supplied configuration is loaded only after positive trust resolution; unknown trust fails closed.

**Default:** disabled · **Security:** critical · **Requires:** config.layered · **Claude equivalent:** workspace trust prompt

- **Pi:** `enabled` (cct-first-party)
  - _status probe:_ project_trust observer registered and isProjectTrusted() gate active.
- **Claude Code:** `enabled` (native)
  - _status probe:_ Workspace trust prompt is enforced by the host application.

### `workflow.sdd`

Risk-scaled SDD artifacts gate protected work; unresolved clarification markers block it.

**Default:** disabled · **Security:** enforcing · **Claude equivalent:** plan/build agent frontmatter gating

- **Pi:** `enabled` (cct-first-party)
  - _status probe:_ SDD build gate registered on tool_call.
- **Claude Code:** `enabled` (cct-first-party)
  - _status probe:_ Plan/build agent manifests gate on plan.md frontmatter.

### `workflow.phases`

A persistent Research -> Plan -> Build -> Review phase machine governs what the agent may do in each phase.

**Default:** disabled · **Security:** enforcing · **Requires:** workflow.sdd · **Claude equivalent:** phase agents + /phase-complete

- **Pi:** `enabled` (cct-first-party)
  - _status probe:_ Phase state loaded or initialized for the project.
- **Claude Code:** `enabled` (cct-first-party)
  - _status probe:_ Phase agents plus the /phase-complete command are installed.

### `permissions.engine`

Tool, command, and path requests resolve to allow / ask / deny, with a deterministic resolution for headless sessions.

**Default:** disabled · **Security:** critical · **Claude equivalent:** settings.json permissions

- **Pi:** `enabled` (cct-first-party)
  - _status probe:_ Permission rule set built from resolved configuration.
- **Claude Code:** `enabled` (native)
  - _status probe:_ settings.json permissions block resolved by the host application.

### `permissions.protected-paths`

Sensitive paths are protected against write and traversal, with symlink and canonicalization defenses.

**Default:** disabled · **Security:** critical · **Requires:** permissions.engine · **Claude equivalent:** protect-files.sh / protect-git.sh hooks

- **Pi:** `enabled` (cct-first-party)
  - _status probe:_ Protected-path matcher active on write and edit tool calls.
- **Claude Code:** `enabled` (cct-first-party)
  - _status probe:_ protect-files.sh and protect-git.sh registered as PreToolUse hooks.

### `providers.pi`

Pi can act as a peer-review provider for cross-provider review, under a read-only reviewer contract.

**Default:** disabled · **Security:** enforcing · **Requires:** permissions.engine · **Claude equivalent:** peer-review-runner provider entry

- **Pi:** `enabled` (cct-first-party) — The read-only reviewer execution contract (T3.1-T3.4) passes its acceptance suite (scripts/pi-provider-acceptance.sh) — the single source of truth. Enablement is bound to that suite by test-pi-provider-gate.sh; PATH presence never implies enabled. pi binary availability is gated separately by the pi-code doctor health probe.
  - _status probe:_ scripts/pi-provider-acceptance.sh (bound by tests/test-pi-provider-gate.sh).
- **Claude Code:** `disabled` (optional-bridge) — Claude Code can invoke Pi as a peer-review provider, but the reviewer execution contract has not passed its acceptance gates.
  - _status probe:_ providers-health.sh check for a working pi-code.

### `review.enforcement`

Mandatory peer review is enforced before a build/review phase can complete, via the provider-neutral review-loop runner.

**Default:** disabled · **Security:** enforcing · **Requires:** workflow.phases · **Claude equivalent:** peer-review-on-stop.sh Stop-hook gate

- **Pi:** `degraded` (cct-first-party) — Mandatory review is gated at /cct:phase-complete and the review->next transition — the only Pi-observable seam, since Pi emits no Stop/turn-end event. Weaker than Claude's Stop-hook gate, which fires even when the workflow commands are never run.
  - _status probe:_ reviewGate() at /cct:phase-complete and the review->next transition.
- **Claude Code:** `enabled` (cct-first-party)
  - _status probe:_ peer-review-on-stop.sh blocks session end until loop-summary.json is PASS/bypass.

### `verification.enforcement`

Verification gates (tests, drift, docs, ...) block phase completion when required; gate types with no runnable substrate are reported, not faked.

**Default:** disabled · **Security:** enforcing · **Requires:** workflow.phases · **Claude equivalent:** verify-on-stop.sh Stop-hook verification gate

- **Pi:** `degraded` (cct-first-party) — Verification gates block at /cct:phase-complete and the review->next transition (Pi emits no Stop/turn-end event); type-check runs `tsc --noEmit` over the runtime when typescript is installed (else `unsupported`); generic lint and dependency audit still report `unsupported`, never a fake pass.
  - _status probe:_ verifyGate() over the configured verification.required list.
- **Claude Code:** `enabled` (cct-first-party)
  - _status probe:_ verify-on-stop.sh runs the gate suite at session end (blocking when HOOK_STOP_BLOCK=true).

### `integrations.mcp`

Model Context Protocol servers can be attached, with their provenance and permissions reported.

**Default:** disabled · **Security:** enforcing · **Claude equivalent:** MCP server support

- **Pi:** `degraded` (optional-bridge) — MCP provider interface present (FR-018 modes) with MemKernel as the first audited backend — declared, connectivity-probed (PATH, never spawned), trust-gated, reported via /cct:mcp; no backend is silent (P6). Degraded because live tool invocation flows through Pi's own MCP transport, which the extension does not own. Opt in with integrations.mcp.enabled.
  - _status probe:_ resolveMcpBackends()/probeBackend()/mcpReport(); /cct:mcp reports each declared backend.
- **Claude Code:** `enabled` (native)
  - _status probe:_ MCP servers configured in settings.json are attached by the host.

### `integrations.hosted-platform`

Anthropic-hosted platform services. CCT does not implement these; they are reported as external-platform so parity is never overclaimed.

**Default:** unavailable · **Security:** none · **Claude equivalent:** Claude Code hosted features

- **Pi:** `unavailable` (external-platform) — Anthropic-hosted services are external platforms; never claimed as Pi parity.
  - _status probe:_ Not probed — external platform by definition.
- **Claude Code:** `enabled` (native) — Claude Code is the first-party client for these services, so they are native here and external-platform elsewhere.
  - _status probe:_ Provided by the host application.

### `memory.session-state`

Session state (workflow phase, active feature) persists across restarts and is recovered into context at session start. Pre-compaction checkpoint when the harness exposes a compaction event; otherwise checkpoints are taken at explicit CCT actions.

**Default:** disabled · **Security:** advisory · **Requires:** workflow.phases

- **Pi:** `degraded` (cct-first-party) — Session state persists to .cct/pi-session.json and recovers into context at session start; checkpoints are taken at explicit CCT actions (phase transitions, /cct:checkpoint) because Pi emits no observable compaction event — not a pre-compaction hook, hence degraded.
  - _status probe:_ loadCheckpoint()/recoveryDigest() at session_start; writeCheckpoint() on /cct:checkpoint + phase transition.
- **Claude Code:** `enabled` (cct-first-party) — Claude Code's PreCompact/PostCompact hooks checkpoint before compaction and recover after — a true pre-compaction hook (Pi has no such event).
  - _status probe:_ PreCompact/PostCompact hooks checkpoint + recover session state.

### `security.sandbox`

Sandbox detection (host-unrestricted / permission-gated-only / containerized / micro-vm / remote-sandboxed) and the autonomous/ci rejection of unrestricted host execution absent an explicit override. Permissions are NOT sandboxing (reported separately, spec P5).

**Default:** disabled · **Security:** enforcing

- **Pi:** `degraded` (cct-first-party) — Enforces the autonomous/ci no-unrestricted-host rule — rejects tool execution (fail-closed) when a sandbox is required but the environment is host-unrestricted and no override is set. Detection is best-effort: Docker via cgroup/.dockerenv; micro-vm / remote-sandboxed via an operator CCT_SANDBOX declaration. The runtime cannot itself create a sandbox.
  - _status probe:_ detectSandbox()/sandboxGate() at session_start; tool_call denial when blocked.
- **Claude Code:** `disabled` (cct-first-party) — Pi-runtime sandbox provider (FR-019). The Claude Code adapter relies on host + permission-mode controls and does not implement the CCT sandbox detection/gate; reported disabled rather than overclaimed.
  - _status probe:_ Not implemented in the Claude Code adapter.

### `security.env-scrub`

Name-based scrubbing of credential-shaped environment variables at harness-controlled spawn boundaries (subagent child sessions, worker handoffs), with a trust-asymmetric configuration surface: in-repo configuration may tighten but never loosen the policy. Values are never read or logged; the primary interactive session's environment is out of scope by design.

**Default:** disabled · **Security:** enforcing

- **Pi:** `degraded` (cct-first-party) — Subagent child sessions spawn with a scrubbed env by default (fail-safe ON; scrub:false is the trusted opt-out), and the worktree-run handoff unsets the CLI-computed scrub list before exec — fail-closed on a scrub-list failure, removed NAMES (never values) audited at the worker's session_start (env.scrub). Config is trust-asymmetric (FR-004a): both in-repo layers may only tighten (security.env_scrub/_keep/_extra); loosening requires user-controlled scopes (global config, CCT_CONFIG__* env, --set). Degraded because the primary interactive session's env is untouched by design and the runtime cannot verify what the OS/sandbox exposes beneath it.
  - _status probe:_ scrubEnv() at the runChildSession spawn; pi-code env scrub-list + unset at the worktree-run handoff; env.scrub audit at worker session_start.
- **Claude Code:** `disabled` (cct-first-party) — Pi-runtime env scrubbing (#173). The Claude Code adapter does not implement the CCT spawn-boundary scrub (its sandboxing and subagent spawning are native surfaces); reported disabled rather than overclaimed.
  - _status probe:_ Not implemented in the Claude Code adapter.

### `memory.promotion`

Explicit promotion/deletion of durable memories with provenance, wiki-first retrieval, and sensitive-memory controls (a fact carrying a secret is refused). Optional MemKernel (MCP) backend for code-aware retrieval.

**Default:** disabled · **Security:** advisory · **Requires:** memory.session-state

- **Pi:** `degraded` (cct-first-party) — Built-in store (.cct/memory.json) is authoritative: /cct:remember, /cct:memory, /cct:memory-forget, wiki-first /cct:recall, provenance, and a fail-closed sensitive-memory control (a secret-bearing fact is refused). MemKernel is an MCP server, so code-aware delegation waits on the Pi MCP provider (integrations.mcp, T10.2); until then it reports pending-MCP.
  - _status probe:_ promoteMemory()/recall() over .cct/memory.json + knowledge/wiki; memkernelStatus() reports MCP availability.
- **Claude Code:** `enabled` (cct-first-party) — Claude Code promotes memories to its persistent memory layer and can reach MemKernel over MCP for code-aware retrieval.
  - _status probe:_ Native memory + MemKernel MCP server.

### `agents.subagents`

Named subagents with separate context and per-agent model/thinking/tools/permissions/skills, expressed as neutral manifests; Claude `.claude/agents` files import into that schema. Live child-session execution (spawn, result contracts, caps, cancellation) is a separate concern gated on the runner surface.

**Default:** disabled · **Security:** advisory · **Claude equivalent:** .claude/agents/*.md + the Agent tool

- **Pi:** `degraded` (cct-first-party) — Subagents run as isolated out-of-process `pi --mode json` child sessions over T7.1 manifests (T7.2, FR-011). ENFORCED via verified pi CLI flags: per-agent model (--model), thinking (--thinking), tools (--tools) and separate context (--no-session); plus CCT-imposed wall-clock timeout, AbortSignal cancellation, and concurrency/recursion caps (autonomy.max_concurrency / max_recursion). Degraded because pi exposes no native subagent primitive, no result contract, and no permission-mode/skills/max-turns surface — the delegation, caps, and typed result are CCT-first-party scaffolding, and permissions/skills/context beyond isolation are reported not-enforced, never faked. Opt in with the agents.subagents_enabled config gate.
  - _status probe:_ buildChildArgv()/runChildSession() spawn pi --mode json with a typed ChildResult; caps.ts bounds concurrency/recursion. T7.1 importClaudeAgents()/validateManifest() over .claude/agents frontmatter.
- **Claude Code:** `enabled` (native) — Claude Code runs subagents as native SDK child sessions defined by `.claude/agents/*.md` manifests, dispatched through the Agent tool.
  - _status probe:_ Native Agent tool + .claude/agents/*.md manifests.

### `agents.worktrees`

Parallel workers isolated in git worktrees, with worker / branch / worktree / task / owned-area / verification / merge / cleanup state tracked. Verification and merge EXECUTION are separate concerns; this capability is the isolation + tracked state + safe lifecycle.

**Default:** disabled · **Security:** advisory · **Claude equivalent:** Agent isolation: "worktree"

- **Pi:** `degraded` (cct-first-party) — Parallel workers run in isolated git worktrees on their own branch (never master/main), tracked in a versioned .cct/worktrees.json ledger (T7.3, FR-013). ENFORCED against the real git CLI: worktree create/isolation, ownership conflict detection (overlap refused on assignment), dirty-worktree-safe cleanup, stale recovery, and the origin:cct deletion boundary — a worktree CCT did not create is never removed, only reported; force/reset/branch-force-delete are never issued. Worker VERIFICATION is now executed in the worktree and its status set (T7.4, reusing the FR-016 runner), with redacted worker->parent correlation records emitted to .cct/worker-analytics.jsonl and fail-closed partial-failure aggregation. Degraded because MERGE execution is still only state-tracked (T8), write-time ownership enforcement (a worker only writes inside its owned area) is the permission layer's job, and the full FR-021 analytics-format translation / DB ingestion / Studio surfacing is a separate task — T7.4 emits neutral correlation records only, never claiming full analytics.
  - _status probe:_ createWorker()/cleanupWorker()/reconcile() over git worktree; runWorkerVerification()/emitCorrelation()/summarizeBatch() (T7.4) set verification + emit .cct/worker-analytics.jsonl; ledger at .cct/worktrees.json.
- **Claude Code:** `disabled` (cct-first-party) — Claude Code isolates parallel subagents in native git worktrees (Agent isolation: "worktree"), but the CCT worker/ownership/verification/merge/ cleanup ledger (FR-013) is not implemented in the Claude adapter; reported disabled rather than overclaimed.
  - _status probe:_ Native Agent worktree isolation; no CCT worktree ledger.

### `agents.teams`

Opt-in agent teams: lead/teammate identities, a shared task ledger with assignment/claiming, peer messaging, plan approval, bounded concurrency, controlled shutdown, result synthesis and partial-failure handling. DISTINCT from subagent delegation (peers coordinating over shared state, not a parent spawning children).

**Default:** disabled · **Security:** advisory · **Claude equivalent:** Agent Team configurations

- **Pi:** `degraded` (cct-first-party) — Opt-in agent teams (T8.1, FR-012) — CCT-first-party coordination STATE, distinct from subagent delegation (peers, not parent->child). A shared ledger (.cct/team.json) + redacted peer-message append-log (.cct/team-messages.jsonl), kept separate from the worktree ledger (a task links to a worker only by workerId). ENFORCED fail-closed on local state: unique lead/teammate identities (exactly one lead), a single-claimant task ledger (double-claim / cross-assignment / over-cap / pre-approval claims all refused), a plan-approval gate on BOTH activation and claiming, bounded concurrency (autonomy.max_concurrency), and controlled shutdown (recorded who/why; close only when no task is still claimed). Degraded because Pi has no team primitive: live peer EXECUTION runs through the T7.2/T7.4 runners separately (the controller never spawns), messaging is a polled append-log not a live transport. A team status SNAPSHOT, fail-closed result synthesis, and failure recovery (reopening a left member's claims) are present (T8.2); still degraded because the status view is an on-demand snapshot, not a live-updating UI (no Pi UI event stream), and live peer execution / real message transport are not Pi primitives. Opt in with the agents.teams_enabled config gate.
  - _status probe:_ createTeam()/claimTask()/approvePlan()/requestShutdown() over .cct/team.json; teamStatus()/synthesizeTeam()/markMemberLeft()/reopenOrphanedClaims() (T8.2) read-model + recovery; postMessage() appends redacted .cct/team-messages.jsonl.
- **Claude Code:** `disabled` (cct-first-party) — Claude Code ships native Agent Team configurations, but the CCT team-coordination ledger (FR-012 shared ledger / claiming / plan approval / controlled shutdown) is not implemented in the Claude adapter; reported disabled rather than overclaimed.
  - _status probe:_ Native Agent Team configs; no CCT team ledger.
