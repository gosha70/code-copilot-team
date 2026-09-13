# Feature Index

> **GENERATED — do not edit.** Run `scripts/cct list --write` (or
> `scripts/generate-feature-index.sh`) to regenerate. Sources of truth:
> `shared/features/catalog.yaml`, `shared/skills/`,
> `adapters/claude-code/.claude/commands/`, and
> `shared/capabilities/catalog.yaml`. To change an entry, edit the source —
> a drift guard (`--check`) fails the build if this file is stale.

_19 features · 14 slash commands · 24 skills · 20 capabilities_

New here? Start with the [Quick Start](../README.md#quick-start), then browse the
tables below. In a session, run `scripts/cct list` to print this on demand.

## Features

What the harness offers, one row per user-facing feature. The title links to
the primary guide. Maturity, release state and adapter support are defined in
[maturity.md](maturity.md); `—` is unsupported and `n/a` means the feature
runs outside any adapter.

| Feature | What you get | Maturity | Since | aider | claude-code | codex | cursor | github-copilot | pi | windsurf |
|---------|--------------|----------|-------|---|---|---|---|---|---|---|
| [Spec-driven development](../docs/sdd-vs-code-copilot-team.md) | A feature is specified, planned and task-listed in `specs/<feature-id>/` before any code is written, with an origin-alignment gate that stops the build when the working spec drifts from what the user asked for. | stable | v1.1.0 | advisory | enforced | advisory | advisory | advisory | enforced | advisory |
| [Four-phase agent workflow](../shared/skills/phase-workflow/SKILL.md) | Work moves through Research, Plan, Build and Review with a single agent in every phase but Build, where a Team Lead delegates to sub-agents; phase transitions are gated on verification. | stable | v1.1.0 | advisory | enforced | advisory | advisory | advisory | enforced | advisory |
| [Shape-Up product bets](../docs/shape-up-workflow.md) | Rough ideas become pitches with an appetite, scopes and a circuit breaker; bets run against a hill chart and end in a retrospective and a cooldown report. | stable | v1.1.0 | advisory | enforced | advisory | advisory | advisory | advisory | advisory |
| [Peer review by a second model](../docs/auto-code-review-setup.md) | A second provider reviews the diff in a read-only sandbox and returns a PASS, FAIL or INCONCLUSIVE verdict with findings; the phase cannot complete on a FAIL, and a failed reviewer falls back down a chain. | stable | v1.1.0 | advisory | enforced | advisory | advisory | advisory | advisory | advisory |
| [Unattended auto-build runs](../shared/skills/auto-build-loop/SKILL.md) | An approved feature is built phase by phase by a driver outside the session, with a gating reviewer per phase, bounded fix sessions, a cost and wall-clock cap, a ledger, and a PR at the end. | beta | unreleased | — | enforced | enforced | — | — | enforced | — |
| [Cost and safety caps](../shared/skills/auto-build-loop/SKILL.md) | An unattended run stops on its own when spend, wall-clock, review rounds or session turns exceed the caps frozen at admission, and the Studio raises an alert at 80% and 100%. | beta | unreleased | — | enforced | enforced | — | — | enforced | — |
| [Coverage contract](../shared/skills/auto-build-loop/SKILL.md) | A run's verification.yaml binds each requirement to the test that proves it, and the driver refuses a phase whose coverage fell below the frozen contract. | beta | unreleased | — | enforced | enforced | — | — | enforced | — |
| [Runtime conformance evaluator](../shared/skills/auto-build-loop/SKILL.md) | The built application is started and probed against the contract's runtime criteria before the phase can land, so a green unit suite cannot hide a service that does not come up. | experimental | unreleased | — | enforced | enforced | — | — | enforced | — |
| [Visual verification gate](../shared/skills/auto-build-loop/SKILL.md) | A UI feature's run captures screenshots against the contract's visual criteria and parks rather than passes when the capture cannot be made. | experimental | unreleased | — | enforced | enforced | — | — | enforced | — |
| [Ralph Loop single-agent iteration](../shared/docs/ralph-loop-guide.md) | One agent iterates on a task until the verification command passes or the iteration cap is reached, with no delegation. | stable | v1.1.0 | advisory | enforced | advisory | advisory | advisory | advisory | advisory |
| [Project templates and sync](../adapters/claude-code/docs/claude-config-guide.md) | A new project starts from a stack-specific CLAUDE.md with an agent team, slash commands and CI workflows, and an existing project can be re-synced to the latest template. | stable | v1.1.0 | advisory | enforced | advisory | advisory | advisory | advisory | advisory |
| [UI design harness](../shared/templates/ui-harness/DESIGN.md) | Generated UI is steered by a committed DESIGN.md and design tokens and gated by a visual-review loop with an accessibility check and an anti-slop rubric. | stable | v1.1.0 | advisory | enforced | advisory | advisory | advisory | advisory | advisory |
| [LLM wiki maintainer](../knowledge/README.md) | Lessons and decisions are promoted into a curated project wiki that agents consult before re-reading raw sources, with an ingest pipeline and a lint. | stable | v1.1.0 | advisory | enforced | advisory | advisory | advisory | advisory | advisory |
| [Benchmark harness](../benchmarks/README.md) | Coding agents are run against a task set through pluggable backends and scored with a judge, so a configuration change is measured rather than felt. | beta | v1.1.0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| [Session analytics](../docs/session-analytics-cookbook.md) | Claude Code, Pi and Aider sessions are ingested into a store and queried for cost, turns, tool use, phases, labels and struggle signals from a CLI or an MCP server. | stable | v1.1.0 | n/a | n/a | — | — | — | n/a | — |
| [Studio web UI](../docs/session-analytics-cookbook.md) | The analytics, benchmarks, auto-build runs, team alerts and the project's own documentation are browsed in one local web app with a settings page for the judge and embedding providers. | beta | unreleased | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| [LLM routing profiles](../shared/templates/routing/routing.toml.example) | Auto-build tasks are routed to a backend by route class and role under an execution profile, with validate, status and explain commands and a scheduled tick. | experimental | unreleased | — | enforced | enforced | — | — | enforced | — |
| [MemKernel persistent memory](../shared/skills/memkernel-memory/SKILL.md) | Session context is recalled at start, checkpointed before compaction and recovered after it by hooks that activate only when MemKernel is installed. | experimental | v1.1.0 | advisory | enforced | advisory | advisory | advisory | — | advisory |
| [cct command-line front door](../docs/features.md) | One provider-neutral command lists every slash command, skill and capability and drives routing; doctor and config are planned. | experimental | unreleased | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Slash commands

Type these in an agent session (e.g. Claude Code).

| Command | What it does |
|---------|--------------|
| `/auto-build` | Scaffold and explain an autonomous build run for an approved SDD feature. Validates the approval + origin gates, writes `specs/<feature-id>/automation.json` from the template, and prints the driver command — the driver itself runs OUTSIDE this session. |
| `/bet` | Lock a shaped Shape-Up pitch as a bet for the next cycle. |
| `/cooldown` | Close out a cycle — invoke `cooldown-report` and finalize the active pitch's bet status. |
| `/cycle-start` | Begin a cycle for a bet pitch — initializes the hill chart and transitions the pitch to `building`. |
| `/hill` | Update a scope's status on the hill chart of the active pitch. |
| `/list-agents` | List the custom subagents installed on this machine and in this project — the replacement for the built-in `/agents` command removed from recent Claude Code versions. |
| `/origin-check` | Run the origin-confirmation circuit breaker for a feature. Validates that the working spec/plan is a faithful realisation of the user's original idea, and surfaces an interactive escalation if it has drifted. |
| `/phase-complete` | Signal phase completion. Validates that the review loop has passed (if peer review is enabled) and runs the post-phase checklist. |
| `/promote-lesson` | Promote a session-level lesson into the project wiki at `knowledge/wiki/`. Follows the canonical curator procedure; never edits the wiki without it. |
| `/ralph-start` | Start a Ralph Loop for autonomous task completion. |
| `/retro` | Run a structured retrospective for the current session. Proposes rule and documentation changes but does not apply them. |
| `/review-decide` | Resolve a circuit breaker in the review loop. Accepts exactly one argument: approve, reject, or retry. |
| `/review-submit` | Submit work for peer review. Validates clean worktree, initializes or continues the review loop, invokes review-round-runner.sh, and returns the verdict. |
| `/shape` | Shape a rough idea into a Shape-Up pitch via the `pitch-shaper` agent. |

## Skills

On-demand instruction modules the agent loads by phase or when relevant.

| Skill | Description |
|-------|-------------|
| `agent-team-protocol` | Multi-agent delegation rules, three-phase workflow (Plan/Build/Review), model selection, collaboration gates, and Ralph Loop integration. |
| `auto-build-loop` | Autonomous build driver after SDD spec approval: phase-scoped headless build sessions, driver-owned commits, cross-provider review gates, milestone pauses, and fail-closed escalation — under explicit opt-in autonomy profiles. |
| `clarification-protocol` | When and how to ask clarifying questions before implementing. Data model review gate and ambiguity resolution rules. |
| `coding-standards` | Quality gates, prohibited patterns, verification discipline, and self-audit rules for all code generation and review sessions. |
| `copilot-conventions` | Cross-copilot portable conventions: target alignment, complexity control, minimal changes, git discipline, and project structure. |
| `copyright-headers` | Copyright header rules for generated source files. Applies the company name from providers.toml to new files. |
| `design-system` | Derive a unique, domain-fit design direction and enforce design-token + anti-slop discipline. Read/author DESIGN.md before building any UI; override framework defaults so output is bespoke by construction, not generic. |
| `environment-setup` | Environment variable patterns, config file validation, and setup verification for new project scaffolding. |
| `infra-verification` | Infrastructure artifact verification: Docker builds, CI workflows, and launcher flags must be executed, not just syntax-checked. |
| `integration-testing` | Test integration points early. Verify cross-service contracts, API boundaries, and data flow before declaring done. |
| `memkernel-memory` | MemKernel persistent memory protocol. Self-guarding: activates only when the memkernel MCP server is configured. |
| `opus-4-7-features` | Optional guidance for sessions using Claude Opus 4.7: adaptive thinking, xhigh effort, prompt caching, /btw side questions. |
| `origin-confirmation` | Origin-confirmation circuit breaker: machine-checkable origin frontmatter, alignment-check protocol, three gates (plan-approval, build-entry, phase-complete), and interactive escalation on deviation. |
| `phase-workflow` | Phase transition rules, post-phase verification steps, peer review validation, and commit-gate approval flow. |
| `provider-collaboration-protocol` | Cross-provider peer review protocol: session flags, review flow, collaboration artifacts, fail-closed enforcement, and CI validation. |
| `ralph-loop` | Single-agent autonomous iteration loop: PRD-driven, self-verifying, with configurable iteration limits and completion criteria. |
| `review-loop` | Agent-driven peer review loop: structured findings, dispositions, circuit breakers, commit strategies, sandbox isolation, and plan-phase advisory mode. |
| `safety` | Non-negotiable safety constraints: destructive action guards, blocked operations, secrets policy, password storage, input validation, and dependency review. |
| `spec-workflow` | SDD specification protocol: risk-based spec_mode classification, required sections per mode, plan approval gate, and artifact directory conventions. |
| `stack-constraints` | Stack version pinning and dependency compatibility guards. Prevents silent version drift across project boundaries. |
| `team-lead-efficiency` | Build team lead efficiency rules: limit sub-agents, polling discipline, no redundant re-work, parallel task launching. |
| `token-efficiency` | Token economy rules: diff-over-rewrite, context compression, avoid verbose re-explanations, minimize round-trips. |
| `visual-review` | Closed visual-review loop for generated UI: render the running app, screenshot per breakpoint, run an axe-core a11y gate, critique against the DESIGN.md rubric, triage findings, and iterate to a quality bar with a hard cap. Drives the shippable harness/ runner. |
| `wiki-first-query` | Wiki-first query convention: consult knowledge/wiki/index.md and the linked pages BEFORE re-reading raw sources for a project topic. The wiki is the canonical project memory layer. |

## Capabilities

Tool-agnostic capabilities resolved per adapter. Full compatibility matrix:
[shared/capabilities/COMPATIBILITY.md](../shared/capabilities/COMPATIBILITY.md).

| Capability | Description | Default |
|------------|-------------|---------|
| `skills.shared` | Shared CCT skills are discoverable by the agent as first-class instruction resources. | disabled |
| `prompts.commands` | CCT slash commands are available as prompt templates or commands. | disabled |
| `config.layered` | Configuration resolves through an explicit layer precedence, and every resolved value can be explained with its provenance. | disabled |
| `config.trust-gating` | Project-supplied configuration is loaded only after positive trust resolution; unknown trust fails closed. | disabled |
| `workflow.sdd` | Risk-scaled SDD artifacts gate protected work; unresolved clarification markers block it. | disabled |
| `workflow.phases` | A persistent Research -> Plan -> Build -> Review phase machine governs what the agent may do in each phase. | disabled |
| `permissions.engine` | Tool, command, and path requests resolve to allow / ask / deny, with a deterministic resolution for headless sessions. | disabled |
| `permissions.protected-paths` | Sensitive paths are protected against write and traversal, with symlink and canonicalization defenses. | disabled |
| `providers.pi` | Pi can act as a peer-review provider for cross-provider review, under a read-only reviewer contract. | disabled |
| `review.enforcement` | Mandatory peer review is enforced before a build/review phase can complete, via the provider-neutral review-loop runner. | disabled |
| `verification.enforcement` | Verification gates (tests, drift, docs, ...) block phase completion when required; gate types with no runnable substrate are reported, not faked. | disabled |
| `integrations.mcp` | Model Context Protocol servers can be attached, with their provenance and permissions reported. | disabled |
| `integrations.hosted-platform` | Anthropic-hosted platform services. CCT does not implement these; they are reported as external-platform so parity is never overclaimed. | unavailable |
| `memory.session-state` | Session state (workflow phase, active feature) persists across restarts and is recovered into context at session start. Pre-compaction checkpoint when the harness exposes a compaction event; otherwise checkpoints are taken at explicit CCT actions. | disabled |
| `security.sandbox` | Sandbox detection (host-unrestricted / permission-gated-only / containerized / micro-vm / remote-sandboxed) and the autonomous/ci rejection of unrestricted host execution absent an explicit override. Permissions are NOT sandboxing (reported separately, spec P5). | disabled |
| `security.env-scrub` | Name-based scrubbing of credential-shaped environment variables at harness-controlled spawn boundaries (subagent child sessions, worker handoffs), with a trust-asymmetric configuration surface: in-repo configuration may tighten but never loosen the policy. Values are never read or logged; the primary interactive session's environment is out of scope by design. | disabled |
| `memory.promotion` | Explicit promotion/deletion of durable memories with provenance, wiki-first retrieval, and sensitive-memory controls (a fact carrying a secret is refused). Optional MemKernel (MCP) backend for code-aware retrieval. | disabled |
| `agents.subagents` | Named subagents with separate context and per-agent model/thinking/tools/permissions/skills, expressed as neutral manifests; Claude `.claude/agents` files import into that schema. Live child-session execution (spawn, result contracts, caps, cancellation) is a separate concern gated on the runner surface. | disabled |
| `agents.worktrees` | Parallel workers isolated in git worktrees, with worker / branch / worktree / task / owned-area / verification / merge / cleanup state tracked. Verification and merge EXECUTION are separate concerns; this capability is the isolation + tracked state + safe lifecycle. | disabled |
| `agents.teams` | Opt-in agent teams: lead/teammate identities, a shared task ledger with assignment/claiming, peer messaging, plan approval, bounded concurrency, controlled shutdown, result synthesis and partial-failure handling. DISTINCT from subagent delegation (peers coordinating over shared state, not a parent spawning children). | disabled |
