# Specification: Pi Harness Adoption

**Feature ID**: `pi-harness-adoption`
**Input**: Consolidated SDD plan (2026-07-21) + final resolutions R1–R6 + verification addenda V1–V3.

## Summary

Code Copilot Team (CCT) adds [Pi](https://pi.dev/) as a first-class **executable**
harness adapter — the second enforced-tier adapter after Claude Code. The
deliverable is one distribution with two activation surfaces:

> **`pi install` gives reusable CCT content; `pi-code` gives the enforced CCT harness.**

- **Advisory content package** — installable via Pi's native package mechanism
  (`pi install git:github.com/gosha70/code-copilot-team@<tag>`): skills, prompt
  templates, optional themes. No enforcement. Usable from bare `pi`.
- **Enforced runtime** — installed by `./scripts/setup.sh --pi`, launched by the
  canonical `pi-code` launcher: SDD gates, lifecycle hooks, permissions,
  workflow phases, agents, provider/peer-review/wiki/benchmark integration,
  capability registry, diagnostics, and a layered, explainable configuration
  system. Never loaded by bare `pi`.

The objective is **behavioral parity** with the CCT engineering contract as
enforced on Claude Code — not implementation parity and not reimplementation of
Anthropic-hosted platform services.

## User Scenarios

- **US-1 (advisory install)**: `pi install git:github.com/gosha70/code-copilot-team@vX.Y.Z`
  → bare `pi` exposes CCT skills and `/command` prompt templates. No gates, no
  hooks, no runtime. The package README states this is advisory mode.
- **US-2 (enforced install)**: `./scripts/setup.sh --pi` installs the advisory
  resources, the managed enforcement runtime, and `pi-code` (default
  `~/.local/bin/pi-code`). `pi-code doctor` verifies the installation.
- **US-3 (enforced session)**: `pi-code [--profile disciplined] [project]`
  wraps upstream `pi`, explicitly loads the runtime via `--extension`, sets the
  `CCT_RUNTIME=1` marker, and starts an enforced session. Bare `pi` remains an
  unenforced Pi environment; `pi-code --no-cct` is equivalent to bare `pi`.
- **US-4 (SDD gating)**: on `/build` for a `spec_mode: full` feature without
  complete `specs/<id>/` artifacts (or with unresolved `[NEEDS CLARIFICATION]`
  markers), the runtime blocks `edit`/`write`/execution tool calls outside
  `specs/` with an actionable reason.
- **US-5 (safety)**: agent-issued `git push --force` or edits to protected
  paths are blocked deterministically in all Pi modes (TUI, print, JSON, RPC).
- **US-6 (discoverability)**: `pi-code doctor` / `/cct:doctor`,
  `pi-code config explain <key>`, and `pi-code features` explain every resolved
  configuration value (with provenance) and every capability (implementation
  kind × runtime status).
- **US-7 (project trust)**: project CCT configuration under
  `.code-copilot-team/` loads only after Pi's trust lifecycle positively
  resolves the project in-process. `/trust` saved mid-session does not silently
  activate project CCT config; the runtime instructs the user to restart.
- **US-8 (peer review)**: `pi-code --peer-review codex` mirrors the
  `claude-code` launcher contract. Conversely, Pi serves as a reviewer for
  other copilots through the dedicated `pi-review-provider` adapter and the
  non-recursive `peer-reviewer` profile.
- **US-9 (ecosystem)**: Pi appears in `providers-health.sh`, as a
  `provider-emit.sh` target, as benchmark backend
  `scripts/benchmark_runner/backends/pi.py`, and in wiki backend auto-detection
  (`claude → codex → pi → cursor`) — each gated behind acceptance tests before
  its capability reports `enabled`.
- **US-10 (headless/autonomous)**: all gates behave deterministically in `-p`,
  `--mode json`, `--mode rpc`, SDK, CI, and autonomous runs; `ask` permission
  rules resolve to configured `allow`/`deny`/`fail`; `autonomous` and `ci`
  profiles reject unrestricted host execution absent an explicit override.

## Goals

1. Pi as a first-class executable adapter at enforced tier.
2. `pi-code` as the canonical enforced entry point; upstream `pi` untouched.
3. `shared/skills/` and shared semantic resources remain canonical.
4. Provider-neutral schemas: capabilities, agents, lifecycle events,
   permission policies (under `shared/capabilities/`, `shared/schemas/`).
5. Risk-scaled SDD enforcement (full / lightweight / none) on Pi.
6. Research → Plan → Build → Review phase workflow with per-phase model,
   thinking, tools, skills, permissions, and gates.
7. Discoverable, layered, explainable configuration with provenance.
8. Integration with providers, peer review, wiki, benchmarks, analytics.
9. Local-first, air-gapped, CI, and autonomous profiles.
10. Honest, machine-readable capability parity reporting.

## Non-Goals

Reimplementing Anthropic-hosted web/mobile/Slack services or Remote Control;
building a container/VM runtime; replacing the peer-review runner, benchmark,
or analytics formats; rewriting all shell hooks in TypeScript immediately;
silent third-party Pi package dependencies; transcript-identical parity;
forking Pi.

## Architectural Principles

- **P1 Executable adapter** — enforcement, not projection.
- **P2 Shared content canonical** — Pi resources generated from `shared/`.
- **P3 Authored runtime, generated content** — `scripts/generate.sh` never
  overwrites authored runtime code; only content resources are generated.
- **P4 Behavioral parity** — equivalent outcomes, different mechanisms allowed.
- **P5 Permissions ≠ sandboxing** — reported separately, never conflated.
- **P6 Third-party Pi packages are optional audited backends** — never silent
  dependencies of safety or SDD behavior.
- **P7 Security monotonicity** — project config may strengthen, never weaken,
  the user security floor.
- **P8 Advisory/enforced split (R1)** — the native Pi package manifest exposes
  only content resources (`pi.skills`, `pi.prompts`, `pi.themes`); the
  enforcement runtime is **not** listed under `pi.extensions` and does not live
  in an auto-discovered `extensions/` directory. `pi-code` loads it explicitly
  (`--extension <managed-path>/runtime/index.ts`) and sets `CCT_RUNTIME=1` as a
  defense-in-depth activation marker (not a security boundary). The runtime
  refuses enforcement initialization without the marker except under supported
  test/SDK bootstrap.
- **P9 In-process trust gating (R2)** — the launcher never reads project CCT
  configuration and never parses Pi's trust database. The runtime subscribes to
  Pi's public `project_trust` lifecycle event and consults
  `ExtensionContext.isProjectTrusted()` before every load of
  `.code-copilot-team/config.toml`, `.code-copilot-team/config.local.toml`,
  project agent definitions, project policy extensions, or project provider
  overrides. Unresolved or deferred trust ⇒ untrusted, fail closed. Minimum
  supported Pi version ≥ 0.79.0 (introduced extension-controlled project
  trust, `--approve` / `--no-approve`).
- **P10 Trust observation, not ownership (V1)** — Pi grants trust-decision
  ownership to the first extension that answers `project_trust`. The CCT
  runtime **defers by default** (observes the outcome; does not answer) unless
  explicitly configured for policy-driven trust. Doctor reports which extension
  owned the decision.
- **P11 Context-policy separation** — `AGENTS.md`, `CLAUDE.md`, repository
  docs, tool output, and retrieved content are untrusted model-visible context
  and can never alter permissions, sandbox requirements, hook failure modes,
  protected paths, network policy, trust decisions, secret handling, or
  security floors.

## Requirements

### Launcher

- **FR-000** `pi-code` wraps upstream `pi` (resolve executable, recursion
  guard, version validation ≥ pinned minimum, profile resolution, global
  config load, security floor, package/resource sync validation, provider and
  sandbox readiness checks, actionable pre-launch errors, signal forwarding,
  exit-code preservation). Unknown Pi arguments and everything after `--` are
  forwarded unmodified. Syntax:
  `pi-code [CCT_OPTIONS] [PROJECT_PATH] [-- PI_ARGUMENTS]` and
  `pi-code <COMMAND> [ARGS]`. Commands: `init <template> <dir>`,
  `sync [--dry-run]`, `doctor`, `config [explain <key>]`, `features`,
  `profiles`, `agents`, `skills`, `hooks`, `providers`, `permissions`,
  `sandbox`, `export`, `version`. Options include `--profile`, `--project`,
  `--global`, `--no-project-config`, `--no-cct`, `--approve-project` (maps to
  Pi `--approve`), `--config <path>`, `--set <k=v>`, `--strict`,
  `--diagnostic`, and the peer-review trio below.
- **FR-000a (R4)** Enforced-launcher symmetry: for capabilities shared with
  Claude Code, `pi-code` mirrors the `claude-code` launcher's command names,
  option names (`--peer-review [provider]`, `--peer-review-off`,
  `--peer-review-scope <code|design|both>`), environment contract
  (`CCT_PEER_REVIEW_ENABLED`, `CCT_PEER_PROVIDER`, `CCT_PEER_REVIEW_SCOPE`),
  and template behavior (`pi-code init` reuses the existing scaffolder;
  `pi-code sync` reuses the existing sync contract). Divergences are listed by
  `pi-code features` and in generated compatibility docs.
- **FR-001** `setup.sh --pi [--sync|--profile <p>|--scope project <dir>]`
  installs/repairs/synchronizes/uninstalls without damaging unrelated Pi
  configuration, verifies PATH, never overwrites an unrelated `pi-code`
  executable, records compatible Pi/CCT versions, and runs `pi-code doctor` as
  verification.

### Distribution

- **FR-002** Package/runtime registration: native package install may register
  skills, prompts, themes; the enforcement runtime is never auto-loaded by the
  package manifest; `pi-code` loads it explicitly; bare `pi` registers no CCT
  tools, lifecycle handlers, gates, workflow commands, or enforcement UI;
  `--no-cct` omits runtime loading and the marker entirely; tests verify bare
  `pi` executes no runtime initialization code.
- **FR-002a (R5)** Two documented installation modes:
  `pi install git:...@tag` = **Advisory** (no enforcement; README states it);
  `setup.sh --pi` + `pi-code` = **Enforced**. Native install examples pin a
  release tag; unpinned installs are development-only. Capability reporting
  distinguishes package installation from runtime enforcement.
- **FR-003** `scripts/generate.sh` deterministically generates Pi skills,
  prompt templates, always-context bundle, default configuration, and
  capability documentation; CI rejects drift; generation never overwrites
  authored runtime code.

### Configuration

- **FR-004** Layered TOML configuration — locations
  `~/.code-copilot-team/config.toml`, `.code-copilot-team/config.toml`,
  `.code-copilot-team/config.local.toml` (gitignored); precedence
  `defaults < profile < global < trusted project < trusted project-local <
  env < CLI < session`; validated against a versioned schema; migrated;
  redacted; every resolved value explainable with provenance (value, source,
  profile, overridden priors, validation, sensitivity, security-floor status).
  Pi's `.pi/settings.json` carries only package registration and minimal
  Pi-native options. Protected security settings follow the separate
  monotonic precedence chain; relaxation requires a recorded user-controlled
  local/session override.
- **FR-004a (R2)** In-process trust gating per P9/P10. Non-interactive rules:
  `--approve` may authorize project loading for one run; `--no-approve`
  forces project config unavailable; unresolved/deferred/unknown ⇒ untrusted;
  no interactive confirmation is assumed. The implementation never reads or
  writes Pi's internal `trust.json`. `/trust` saved mid-session does not
  activate project CCT config; the runtime reports that a restart is required.
  **(V2)** When Pi's `defaultProjectTrust` is `"always"`, doctor emits a
  warning and the audit log records `defaultProjectTrust` as the trust origin.
- **FR-004b** Context-policy separation per P11.
- **FR-005** Discovery: capabilities, profiles, resources, configuration
  provenance, dependencies, conflicts, providers, packages, trust state,
  sandbox state, security restrictions, and generated-resource sync are all
  inspectable via launcher commands, `/cct:*` commands, and machine-readable
  output (`--json`).

### Workflow

- **FR-006** SDD classification (`full`/`lightweight`/`none`), persisted,
  user-correctable.
- **FR-007** SDD gating: write/execution tools blocked when required artifacts
  are missing or contain unresolved `[NEEDS CLARIFICATION]` markers; `full`
  requires `specs/<id>/{plan.md,spec.md,tasks.md}`; `lessons-learned.md`
  produced at completion per CCT policy; parity with `validate-spec.sh`.
- **FR-008** Phase workflow Research → Plan → Build → Review; per-phase
  primary/fallback models, thinking level, active tools, skills, context,
  permissions, agent policy, review policy, entry/exit gates, stop criteria;
  state persists across sessions; `/cct:phase`, `/cct:status`.
- **FR-009** Permission engine `allow`/`ask`/`deny` over tools, commands,
  paths, git operations, network, MCP servers, agents, teams, external
  executors, package installation, and secret-bearing resources; headless
  `ask` resolves deterministically to configured `allow`/`deny`/`fail`.
- **FR-009a** Security-policy monotonicity per P7.
- **FR-010** Neutral lifecycle-event schema; Pi events mapped to CCT hook
  semantics; existing shell hooks reusable through an event adapter where
  semantics match; mismatches reported `degraded`/`unsupported`, never
  silently approximated; per-hook fail-open/fail-closed, timeout, retry,
  audit logging.

### Agents

- **FR-011** Subagents: SDK child sessions with named manifests, separate
  context, per-agent model/thinking/tools/permissions/skills, result
  contracts, timeout, cancellation, recursion/concurrency limits,
  foreground/background, analytics correlation. Phase agents follow CCT
  doctrine (research/plan/review stay in one mind; delegation during Build).
- **FR-012** Opt-in agent teams: lead/teammate identities, shared task ledger,
  assignment/claiming, peer messaging, plan approval, bounded concurrency,
  lifecycle visibility, controlled shutdown, result synthesis,
  partial-failure handling; distinct from subagent delegation.
- **FR-013** Worktree isolation for parallel workers: worker, branch,
  worktree, tasks, owned areas, verification/merge/cleanup state tracked.
- **FR-014** Checkpoints: save/restore/branch/fork/summarize/compare/cleanup;
  Pi session tree preserves conversation state; git/file snapshots preserve
  workspace state.

### Review & verification

- **FR-015** Reuse the provider-neutral peer-review runner and existing
  collaboration artifact formats; policy supports optional/mandatory review,
  after-phase, before-commit, after-failed-verification, multiple reviewers,
  provider diversity, bounded loops, audited human override.
- **FR-015a (R3)** Reviewer process isolation: a Pi reviewer runs under the
  built-in non-recursive `peer-reviewer` profile — ephemeral session,
  read-only snapshot from the runner, default tools `read,grep,find,ls`, no
  SDD/Build enforcement, no recursive review, no teams, no subagents by
  default, no write/edit, no package installation, strict timeout and token
  budget; the parent runner remains the artifact writer. Optional test
  execution only via `peer-reviewer-exec` inside the runner's disposable
  sandbox.
- **FR-015b (R3)** Provider adapter contract: `providers.toml` invokes a
  dedicated `pi-review-provider` adapter script
  (`command = "pi-review-provider {review_request}"`) — no shell
  interpolation of prompt files in configuration. The adapter validates the
  request path, invokes `pi-code --profile peer-reviewer` (print mode
  initially; JSON event-stream or RPC/SDK with a typed result contract
  later), normalizes output to the CCT review contract, emits diagnostics to
  stderr, and preserves runner exit-code semantics. **(V3)** Exact Pi flags
  (`--no-session` or a temp `--session` directory fallback, stdin piping)
  are validated against the pinned Pi version during implementation.
- **FR-016** Verification gates: build, unit/integration tests, lint, type
  check, security scan, dependency audit, visual review, docs validation,
  generated-drift check; required failures block phase completion.

### Memory & integrations

- **FR-017** Memory: session state, explicit promotion/deletion, MemKernel
  adapter (self-guarding), wiki-first retrieval, pre-compaction checkpoint,
  post-compaction recovery, provenance, sensitive-data controls.
- **FR-018** MCP as optional provider: modes `disabled` /
  `external-package` / `first-party-bridge` / `remote-gateway`; reports
  provenance, trust, permissions, tools, connectivity, version, security.
- **FR-019** Sandbox detection/reporting: `host-unrestricted`,
  `permission-gated-only`, `containerized`, `micro-vm`, `remote-sandboxed`,
  `external-policy-controlled`; `autonomous` and `ci` profiles reject
  unrestricted host execution absent explicit user override.
- **FR-020** Status UI: phase, SDD mode, feature ID, model, thinking, worker
  count, peer-review status, sandbox status, trust status, permission mode,
  profile, context use, current gate failure.
- **FR-021** Analytics: Pi lifecycle/JSON events translated to the neutral
  CCT analytics format (session/task/feature IDs, provider, model, tokens,
  duration, tool calls, permission denials, agent/team activity,
  compactions, review rounds, build/test outcomes, recovery events, final
  outcome); redaction before persistence.
- **FR-022** Headless operation: all gates work in interactive, print, JSON,
  RPC, SDK, CI, benchmark, and autonomous modes; no safety-critical behavior
  depends solely on an interactive prompt.
- **FR-023** Benchmark backend at `scripts/benchmark_runner/backends/pi.py`
  capturing provider, model, tokens, duration, compactions, tool calls,
  agent count, permission denials, review rounds, test/build/lint outcomes,
  recovery behavior, rubric score (judge never overrides deterministic
  verdict, per existing harness rules).
- **FR-024** Provider integration: `pi` target in `provider-emit.sh`,
  `[providers.pi]` seed, Pi health checks in `providers-health.sh`,
  `peer_for.pi` defaults, timeout/failure policy, version validation.
- **FR-025** Wiki: auto-detection order `claude → codex → pi → cursor`; Pi
  enters automatic order only after its backend capability is `enabled`
  (explicit `--backend pi` allowed earlier for development). **(R6)**
- **FR-026** Studio/reporting ingestion compatibility preserved.
- **FR-027** Package provenance: every executable package/extension exposes
  source, version, checksum where available, scope, trust state, enabled
  modules, dependency status, security classification.
- **FR-028 (R6)** Rollout gating: provider/wiki/benchmark plumbing may land
  before full enforcement but reports
  `implementation_kind: cct-first-party, runtime_status: disabled` (with
  reason) until the `peer-reviewer` profile, `pi-review-provider` adapter,
  read-only controls, and provider integration tests pass. Presence of `pi`
  on PATH is never sufficient for `enabled`.

### Capability model

- **FR-029** Two-dimensional classification: implementation kind
  (`native` / `cct-first-party` / `optional-bridge` / `external-platform`)
  × runtime status (`enabled` / `disabled` / `unavailable` / `degraded` /
  `misconfigured` / `unsupported`). Capability records carry id,
  description, kind, default, implementation, requires, conflicts, security
  level, `claude_equivalent`, status probe, documentation link. The registry
  drives `features`, `doctor`, profile validation, generated compatibility
  reports, documentation, benchmark metadata, provenance reports, and
  runtime dependency resolution.

## Constraints

- **C-1** Additive only: existing adapters, setup flags, shared skills,
  Claude Code behavior, review/analytics/benchmark formats, provider
  profiles, and project templates continue to work unchanged.
- **C-2** Minimum supported Pi version ≥ 0.79.0; compatibility CI confirms
  the exact range; feature-detect where possible; exact CLI flags validated
  against the pinned version (V3).
- **C-3** Security gates fail closed; cosmetic integrations fail open;
  secrets never appear in resolved-config output, analytics, benchmarks,
  audit logs, doctor output, or stack traces.
- **C-4** The 32 KiB `AGENTS.md` cap is a Codex-adapter constraint; Pi
  resource-size limits are measured and documented separately. Always-on
  policy loads via a generated always-context bundle (system prompt append /
  runtime injection), not via progressive skill loading.
- **C-5** Bounded autonomy: concurrency, recursion, token budget, cost
  budget, time, tool calls, and review loops are all bounded.
- **C-6** Local-first and air-gapped profiles must work without cloud
  services; `air-gapped` validates providers/resources are local; respect
  `PI_OFFLINE=1`.
- **C-7** Deterministic generation (no timestamps/randomness); startup
  overhead measured and bounded; clean module disablement removes tools,
  commands, hooks, UI, background jobs, resources, and capability status.
- **C-8** Pi project-trust boundary respected (P9/P10); no dependency on
  Pi internals (`trust.json`, private APIs).
- **C-9** Auditability: security-relevant decisions record decision, rule,
  origin, actor, timestamp, runtime mode, and override.
- **C-10** Neutral schemas initially import/map existing Claude-specific
  resources; no repository-wide rewrite.

## Acceptance Criteria (Definition of Done)

> **Scope note — 2026-07-21 (PR #107).** The criteria below define the
> **umbrella** feature and remain the target for the feature branch as a whole.
> They are explicitly **not** the merge gate for PR #107, which delivers a
> rescoped slice: the `pi-code` launcher, layered configuration with the security
> floor and trust gating, generated advisory resources, and the SDD/permission
> enforcement core. Slice B (Phase 3), Phase 6, and Slices D–F are deferred;
> `specs/pi-harness-adoption/tasks.md` records the per-task delivered/partial/
> not-started state. TX.2's "no merge to `master` until the DoD holds" applies to
> the umbrella, and is satisfied for PR #107 by this documented rescope rather
> than by the full criteria below.

The umbrella feature is complete when all of the following hold (each is a
tested gate, not aspiration):

1. `./scripts/setup.sh --pi` installs package + runtime + `pi-code`;
   `pi-code doctor` passes; bare `pi` unaffected; unrelated `pi-code`
   executables never overwritten.
2. Bare `pi` loads no enforcement runtime and executes no runtime
   initialization code (tested); advisory resources appear only when
   explicitly installed; `pi-code --no-cct` ≡ bare `pi`.
3. The launcher never reads project CCT configuration; project config loads
   only after in-process positive trust resolution via the public
   `project_trust` lifecycle + `isProjectTrusted()`; the runtime defers
   trust-decision ownership by default; `/trust` mid-session requires
   restart; `defaultProjectTrust: "always"` triggers a doctor warning.
4. Project policy cannot weaken the user security floor; context files
   cannot become executable policy; every resolved config value is
   explainable with provenance; capability state is machine-readable in two
   dimensions.
5. Full-risk work is blocked without valid SDD artifacts; unresolved
   clarification markers block protected work; phase-specific models,
   tools, skills, permissions, and thinking work; state survives resume
   and compaction.
6. Protected files and destructive commands are blocked in all four Pi
   modes; headless trust/permission behavior is deterministic.
7. `pi-code` mirrors the `claude-code` launcher surface (FR-000a),
   including `init`, `sync --dry-run`, and the peer-review flags/env
   contract.
8. The Pi reviewer runs under the non-recursive `peer-reviewer` profile via
   the `pi-review-provider` adapter; no prompt-file shell interpolation in
   provider configuration; review artifacts match existing CCT formats.
9. Provider, wiki, and benchmark integrations pass their acceptance tests
   before their capabilities report `enabled`; wiki auto-detection never
   selects a disabled Pi backend; benchmark runs produce schema-valid
   records ingested by existing reporting/Studio.
10. Subagents and teams run bounded and isolated (worktrees, ownership,
    recursion/concurrency caps); autonomous/CI profiles require an accepted
    isolation policy.
11. Security tests pass (path traversal, symlinks, shell-wrapper bypass,
    injection via docs/tool output, package substitution, fork bombs,
    worktree cross-contamination, analytics secret leakage).
12. Cross-adapter contract tests pass: Claude Code and Pi agree on SDD
    classification, artifacts, phase order, gate/permission decisions,
    review artifact formats, provider dispatch, verification outcomes,
    analytics semantics (behavioral parity, not identical text).
13. Capability documentation is generated from the registry; SBOM,
    checksums, compatibility matrix, release notes published;
    `lessons-learned.md` records findings.

## Out of Scope

See Non-Goals. Additionally: Windows-native support beyond Pi's documented
platform pages (Linux + macOS are the tested targets, matching other
adapters); IDE integration ships as a separate adapter contract later.
