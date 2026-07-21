---
spec_mode: full
feature_id: pi-harness-adoption
risk_category: integration
justification: "Adds a first-class executable Pi harness adapter: pi-code launcher, TypeScript enforcement runtime, provider-neutral capability/config schemas, SDD and permission enforcement, agents, and provider/wiki/benchmark/analytics integration across many repository areas. External-harness integration ⇒ spec_mode: full."
status: draft
date: 2026-07-21
issue: TBD
collaboration_mode: single
origin:
  user_message: "Provide a detailed Spec Driven Development plan for supported PI harness in Code Copilot Team and adding the heavy discoverable and flexible configuration for supporting all features available in Claude Code to this PI adoption. [Consolidated across three independent plans + final resolutions R1–R6 + verification addenda V1–V3, 2026-07-21.]"
  date: 2026-07-21
  related_specs:
    - specs/provider-config/plan.md
    - specs/benchmark-adapters-backends/
    - shared/templates/provider-profile-template.toml
  origin_claim: |
    Pi (pi.dev) is a minimal agent harness whose extension API (blockable
    tool_call, project_trust lifecycle, isProjectTrusted(), packages,
    Agent Skills support, prompt templates) allows CCT to become the
    second enforced-tier adapter. Final model: "pi install gives reusable
    CCT content; pi-code gives the enforced CCT harness." Grounded against
    repo state at commit f8acd33 and Pi ≥ 0.79.0 (extension-controlled
    project trust, --approve/--no-approve).
---

# Implementation Plan: Pi Harness Adoption

**Branch**: `feature/pi-harness-adoption`
**Input**: specs/pi-harness-adoption/spec.md

## Summary

Implement Pi as CCT's second enforced-tier adapter through one distribution
with two activation surfaces: a native Pi advisory content package (skills,
prompts, themes) and a `pi-code`-launched enforcement runtime (SDD gates,
permissions, hooks, phases, agents, integrations, capability registry,
layered TOML configuration). Twelve phases, six delivery slices, narrow
early PRs. Nothing merges to `master` until the umbrella Definition of Done
in spec.md holds.

## Technical Context

**Language/Version**: Bash (launcher, setup, generation — matching repo
conventions), TypeScript (runtime, executed by Pi via jiti — no build step
at runtime; `tsconfig.json` is dev/test-only), JSON Schema + YAML (neutral
schemas/capability catalog), TOML (CCT configuration), Python (benchmark
backend, alongside existing backends).
**Primary Dependencies**: upstream `pi` ≥ 0.79.0 at runtime;
`@earendil-works/pi-coding-agent` types (dev-only); `typebox` for tool
schemas; existing CCT scripts (`peer-review-runner.sh`, `validate-spec.sh`,
`providers-health.sh`, `provider-emit.sh`, `generate.sh`, `setup.sh`).
**Testing**: repo bash harness pattern (`tests/test-*.sh`), `node --test`
for runtime units with a mocked ExtensionAPI, integration smoke against a
pinned Pi version (auto-skip with notice when `pi` absent, mirroring the
template-CI auto-skip pattern).
**Constraints**: additive only; deterministic generation (CI drift check
extended to `adapters/pi/`); generated content vs authored runtime strictly
separated; all gates functional in TUI/print/JSON/RPC; Pi trust model
respected; security floor monotonic.

## Constitution Check

| Rule file | Concern | Status |
|-----------|---------|--------|
| `coding-standards.md` | No magic strings (ids/keys from schemas); shellcheck + lint clean | OK |
| `safety.md` | Fail-closed gates; secrets never in output/telemetry; no credentials in source | OK |
| `copilot-conventions.md` | One logical change per commit; generated outputs committed; repo is source of truth | OK |
| `token-efficiency.md` | Always-context bundle measured; skills stay progressive-disclosure | OK |
| `origin-confirmation.md` | origin block present; alignment checks at phase boundaries | OK |

## Architecture Decisions

### ADR-1: Advisory package / enforced runtime split (R1)
**Context**: Registering the runtime in Pi's package manifest would load
enforcement in bare `pi`, breaking the "bare pi stays plain" guarantee.
**Decision**: Native manifest exposes only `pi.skills`/`pi.prompts`/
`pi.themes`; runtime lives outside auto-discovered paths and is loaded
explicitly by `pi-code --extension <managed>/runtime/index.ts` with
`CCT_RUNTIME=1` as defense-in-depth (refuse enforcement init without it,
except test/SDK bootstrap).
**Consequences**: two documented install modes (FR-002a); tests must prove
bare `pi` executes no runtime init code.

### ADR-2: In-process trust gating; launcher stays trust-ignorant (R2, V1, V2)
**Context**: Pi 0.79.0 exposes `project_trust` and `isProjectTrusted()`
publicly; global/CLI extensions load before project trust resolves; the
first extension answering `project_trust` owns the decision.
**Decision**: launcher never reads project CCT config; runtime observes
trust (defers ownership by default), gates every project-config load on
`isProjectTrusted()`, fails closed on unknown, requires restart after
mid-session `/trust`, warns on `defaultProjectTrust: "always"`.
**Consequences**: no dependency on `trust.json` internals; minimum Pi
pinned at 0.79.0.

### ADR-3: Dedicated non-recursive `peer-reviewer` profile + adapter script (R3, V3)
**Context**: a CCT-enforced session reviewing another CCT-enforced session
would recurse gates; shell redirection in `providers.toml` is unsafe.
**Decision**: built-in `peer-reviewer` profile (read-only tools, ephemeral
session, no SDD/teams/subagents/write, strict budgets) invoked via
`pi-review-provider {review_request}`; runner remains the artifact writer;
print-mode first, JSON/RPC typed contract later; exact flags validated
against the pinned Pi version.
**Consequences**: provider capability stays `disabled` until this passes
acceptance (FR-028).

### ADR-4: Launcher symmetry with `claude-code` (R4)
**Decision**: `pi-code` mirrors `claude-code` for `init`/`sync`/peer-review
flags and the `CCT_PEER_*` env contract, reusing the existing scaffolder
and sync implementations rather than forking them.

### ADR-5: CCT-owned TOML config; Pi settings minimal
**Decision**: policy lives in `~/.code-copilot-team/config.toml` and
trusted `.code-copilot-team/` project files (consistent with
`providers.toml`); `.pi/settings.json` carries only registration and
Pi-native options. Ordinary and protected-security precedence chains are
distinct; the security floor is monotonic (P7).

### ADR-6: Behavioral parity via neutral schemas + contract tests
**Decision**: capabilities, agent manifests, lifecycle events, permission
policies get provider-neutral schemas under `shared/`; Claude-specific
resources are imported/mapped, not rewritten; the same fixture features run
through Claude Code and Pi and must agree on classifications, gates,
artifacts, and analytics semantics.

## Concrete Integration Points (verified @ f8acd33)

| Area | Change |
|---|---|
| `scripts/generate.sh` | new `[pi]` section: skills copy, prompt-template conversion, always-context bundle, default config, capability docs |
| `scripts/setup.sh` | `--pi` flag (+ `--all` includes pi) |
| `adapters/pi/` | package.json, bin/pi-code, runtime/, resources/ (generated), schemas/, tests fixtures |
| repo root `package.json` | advisory Pi manifest (`pi.skills`/`prompts`/`themes` → `adapters/pi/resources/...`), keyword `pi-package`, **no** `pi.extensions` |
| `shared/capabilities/`, `shared/schemas/` | neutral catalog + schemas (new) |
| `shared/templates/pi/` | config template, project settings template |
| `scripts/provider-adapters/` → `pi-review-provider` | dedicated reviewer adapter |
| `shared/templates/provider-profile-template.toml` | `[providers.pi]` seed + `peer_for.pi` |
| `scripts/providers-health.sh` | Pi health check |
| `scripts/provider-emit.sh` (provider-config Phase 2) | `pi` target |
| `scripts/benchmark_runner/backends/pi.py` | new backend beside `claude_code.py`/`codex.py`/`aider.py`/`stub.py` |
| `scripts/wiki` | backend order `claude → codex → pi → cursor` (gated per FR-028) |
| `tests/` | `test-pi-adapter.sh`, `test-pi-launcher.sh`, runtime unit tests, security + cross-adapter fixtures |
| `.github/workflows/sync-check.yml` | drift check covers `adapters/pi/resources/` |

## Phases

Phase numbering matches the consolidated plan; delivery slices in tasks.md.

- **Phase 0 — Foundation & launcher**: adapters/pi skeleton, `pi-code`
  (upstream discovery, recursion guard, version validation, arg forwarding,
  exit/signal preservation, `--no-cct`), installer, root advisory manifest,
  stub tests. *Done when*: setup installs launcher+package; `pi-code
  version` works; `--no-cct` ≡ bare pi; native args forwarded; bare `pi`
  unaffected.
- **Phase 1 — Capability registry, configuration, diagnostics**: neutral
  capability schema (two-dimensional), TOML schema, layered merge +
  provenance + redaction + migration, profiles (with inheritance, no
  cycles), security floor, trust-gated project loading (ADR-2), `doctor`,
  `config [explain]`, `features`. *Done when*: every resolved value
  explainable; untrusted project config ignored; floor unweakenable;
  capability state machine-readable.
- **Phase 2 — Skills, prompts, always-context**: generate.sh `[pi]` target,
  verbatim skills, command conversion (static vs stateful classification,
  collision validation), always-context bundle, resource provenance, drift
  checks. *Done when*: all skills discoverable; always-on policy present
  before task execution; substitutions preserved; output deterministic.
- **Phase 3 — Provider/wiki/peer-review/benchmark plumbing** (R6: plumbing,
  not stable support): `provider-emit.sh` pi target, `[providers.pi]` seed,
  `peer_for.pi`, health checks, `pi-review-provider` adapter,
  `peer-reviewer` profile, backend `pi.py`, wiki order (gated), analytics
  identifiers. *Done when*: rollout sequence 1–10 of R6 complete; provider
  capability flips `enabled` only after reviewer safety tests pass.
- **Phase 4 — SDD & phase workflow**: risk classifier, frontmatter parser,
  artifact validator, clarification gate, phase state machine, per-phase
  routing, `/cct:phase`, `/cct:status`, `validate-spec.sh` parity,
  persistent workflow state. *Done when*: full-risk work cannot enter Build
  without artifacts; state survives resume; headless gates deterministic;
  Claude/Pi agree on shared SDD fixtures.
- **Phase 5 — Hooks, permissions, protected operations**: neutral
  lifecycle-event schema, Pi event translator, shell-hook adapter,
  allow/ask/deny engine, deterministic headless ask, protected paths,
  canonicalization + symlink defenses, git protection, secret-path
  protection, package-install protection, network policy, audit log.
  *Done when*: no path/shell-trick bypass; floor monotonic; decisions
  auditable; headless never blocks on a prompt.
- **Phase 6 — Verification & review workflow**: peer-review runner
  integration, bounded review-loop state machine, build/test/lint/
  type-check/dependency/security/visual/docs/drift gates, audited human
  override. *Done when*: required gates block completion; artifacts match
  existing formats; loops bounded; overrides recorded.
- **Phase 7 — Subagents & worktrees**: neutral agent schema, Claude-agent
  importer, SDK child sessions, per-agent routing/restrictions, timeout/
  cancellation/recursion/concurrency, worktree manager, ownership, result
  contracts, worker analytics.
- **Phase 8 — Agent teams**: team controller, identities, task ledger,
  assignment/claiming, messaging, plan approval, shutdown, status UI,
  synthesis, failure recovery. Distinct from subagent delegation.
- **Phase 9 — Memory & context durability**: session-state persistence,
  pre/post-compaction checkpoint/recovery, CCT compaction prompt, memory
  promotion/deletion, MemKernel adapter, wiki-first retrieval, provenance,
  sensitive-memory controls.
- **Phase 10 — Sandbox, MCP, CI, autonomy**: sandbox provider interface
  (Docker backend first; evaluate Gondolin/OpenShell/remote), MCP provider
  interface + first backend, autonomous + ci profiles,
  unrestricted-host rejection, auto-build Pi backend, scheduler contract,
  budget/timeout enforcement.
- **Phase 11 — Analytics, documentation, release**: Pi→CCT analytics
  mapping, correlation, redaction tests, Studio ingestion, generated
  capability parity docs, quickstart, config reference, security model,
  migration guide, extension guide, SBOM, checksums, compatibility matrix,
  changelog, release workflow.

## Phase Boundaries

Phase 0 blocks all. Phase 1 blocks 2–11 (everything consumes registry +
config). Phase 2 blocks 3 (resources needed by reviewer/wiki) and 4
(prompts/commands). Phases 4 and 5 are parallelizable after 2; Phase 6
depends on 3 + 5; Phase 7 depends on 5; Phase 8 depends on 7; Phases 9–10
depend on 5; Phase 11 last. Provider capability enablement (FR-028) gates
on Phase 3 acceptance regardless of landing order.

## Pull-Request Decomposition

Umbrella issue remains the specification of record. Child issues 1–12 per
the consolidated plan §21. The first three PRs stay narrow:

1. **PR-1**: adapter skeleton, package loading, `pi-code`, setup
   integration, generated skills + prompt templates, capability registry
   skeleton, deterministic stub tests. *(Phase 0 + parts of 1–2)*
2. **PR-2**: configuration, trust gating, security floor, profiles,
   doctor/explain, resource synchronization. *(rest of Phase 1)*
3. **PR-3**: SDD gating, phase state machine, permissions, protected
   paths, sandbox-status reporting. *(Phases 4–5 core)*

Agents, teams, MCP, memory, analytics, and autonomy follow only after the
configuration and enforcement foundations are stable. **No merge to
`master` until the umbrella Definition of Done holds; all work lands on
`feature/pi-harness-adoption` (or child branches merged into it).**

## Risks

| Risk | Mitigation |
|---|---|
| Rebuilding Claude instead of using Pi | Map outcomes to Pi-native primitives (P4) |
| Config overwhelm | Profiles, schemas, doctor, provenance, explain |
| Executable package compromise | First-party package, pinned versions, SBOM, checksums, explicit opt-in |
| Permissions mistaken for sandboxing | Separate trust/permission/sandbox reporting (P5, FR-019/020) |
| Claude/Pi drift | Neutral schemas + cross-adapter contract tests (ADR-6) |
| Hook semantic mismatch | Explicit degraded/unsupported status (FR-010) |
| Parallel agents damage workspace | Worktrees, ownership, concurrency caps (FR-013) |
| Excessive always-on context | Always-context bundle separate from progressive skills; size measured (C-4) |
| Third-party package abandonment | Provider interfaces + first-party fallbacks (P6) |
| Pi API churn | ≥ 0.79.0 pin, compatibility CI matrix, feature detection (C-2) |
| Headless bypass of prompts | Deterministic ask resolution; fail-closed security (FR-009/022) |
| Overclaimed parity | Two-dimensional capability reporting (FR-029) |
| Project config weakens security | Monotonic floor (FR-009a) |
| Context files inject policy | Context-policy separation (FR-004b) |
| Runaway agents | Budget/timeout/recursion/concurrency limits (C-5) |
| Secret leakage via telemetry | Redaction before persistence + tests (FR-021, C-3) |
| Launcher masks upstream Pi | Bare `pi` preserved; `--no-cct`; visible reporting (FR-002) |
| Trust hijack of user extensions | Runtime defers project_trust ownership by default (P10/V1) |
| `defaultProjectTrust: "always"` headless surprise | Doctor warning + audit origin (V2) |
| Reviewer recursion | `peer-reviewer` profile + adapter isolation (FR-015a/b) |
