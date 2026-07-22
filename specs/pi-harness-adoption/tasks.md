# Tasks: Pi Harness Adoption

Slices map to the consolidated plan §17 (with Slice B redefined per R6 as a
gated integration preview). Priorities: **P0** = gates the phase's
Done-when; **P1** = required for the umbrella DoD; **P2** = polish.
Task IDs: `T<phase>.<n>`.

## Progress — updated 2026-07-22

Every task below must be delivered; the `spec.md` Definition of Done stands as
written. Current state: **17 of 64 complete.** Phase 1 complete (8/8).

Unchecked tasks carry a `_Partial — missing: …_` note naming exactly what is
still absent, so each one can be picked up and finished directly. A task is
checked only when every deliverable named in its own text exists and its tests
pass. Work proceeds in phase order.

## Slice A — Usable Pi adapter (Phases 0–2)

### Phase 0 — Foundation & launcher
- [x] **T0.1 (P0)** `adapters/pi/` skeleton: `package.json` (advisory manifest — no `pi.extensions`), `runtime/index.ts` stub with `CCT_RUNTIME` guard, `resources/` (generated), `README.md` (advisory-mode banner per FR-002a). Files: `adapters/pi/*`.
- [x] **T0.2 (P0)** `bin/pi-code` launcher: upstream `pi` resolution, recursion guard, version validation (≥ 0.79.0), `--no-cct`, `--profile`, `--project`, `--` passthrough, exit-code/signal preservation, `version` command. Security: never overwrite unrelated `pi-code`; `CCT_RUNTIME=1` only when runtime loads. Test: `tests/test-pi-launcher.sh`.
- [x] **T0.3 (P0)** Root `package.json` advisory Pi manifest (keyword `pi-package`; `pi.skills`/`pi.prompts`/`pi.themes` → `adapters/pi/resources/...`).
- [x] **T0.4 (P0)** `adapters/pi/setup.sh` + `scripts/setup.sh --pi` (+ `--all`): install runtime to managed dir, `pi-code` to `~/.local/bin`, PATH check, repair/uninstall, `pi-code doctor` as verification.
- [x] **T0.5 (P1)** Deterministic stub tests: bare-`pi` no-runtime-init assertion, launcher arg forwarding, `--no-cct` equivalence. Fixture: temp HOME + fake `pi` shim.
- [x] **T0.6 (P1)** Pi version compatibility declaration file consumed by launcher + CI.

### Phase 1 — Capability registry, configuration, diagnostics
- [x] **T1.1 (P0)** Neutral capability schema (`shared/schemas/`) + catalog (`shared/capabilities/catalog.yaml`, `pi.yaml`, `claude-code.yaml`) with two-dimensional classification (FR-029).
- [x] **T1.2 (P0)** TOML config schema + loader: layered merge, provenance, redaction, migration, versioning (FR-004). Files: `adapters/pi/runtime/config/*`.
- [x] **T1.3 (P0)** Profiles (`minimal`, `disciplined`, `review-heavy`, `autonomous`, `local-first`, `air-gapped`, `ci`, `peer-reviewer`) with inheritance + cycle rejection.
- [x] **T1.4 (P0)** Security floor engine: monotonic protected-settings chain (FR-009a); recorded overrides.
- [x] **T1.5 (P0)** Trust gating module: `project_trust` observer (defer ownership — V1), `isProjectTrusted()` gate before every project-config load, fail-closed unknown, restart-required messaging after `/trust`, `defaultProjectTrust: "always"` doctor warning + audit origin (FR-004a, V2).
- [x] **T1.6 (P0)** `pi-code doctor` / `config` / `config explain <key>` / `features` (+ `--json` for all).
- [x] **T1.7 (P1)** Config migration mechanism + obsolete-key detection; `validate-cct-config` CI job.
- [x] **T1.8 (P2)** Redacted resolved-configuration `export`.

### Phase 2 — Skills, prompts, always-context
- [x] **T2.1 (P0)** `generate.sh` `[pi]` section: verbatim skills copy → `adapters/pi/resources/skills/`; deterministic ordering; drift check in `sync-check.yml`.
- [ ] **T2.2 (P0)** Command→prompt-template conversion: static/stateful classification, frontmatter normalization (`description`, `argument-hint`), `$ARGUMENTS`/`$1..$n` preservation, collision validation, Claude-only metadata handling.
  - _Partial — missing: `argument-hint` normalization, collision validation, Claude-only metadata handling._
- [ ] **T2.3 (P0)** Always-context bundle from `ALWAYS_SKILLS` (coding-standards, copilot-conventions, copyright-headers, origin-confirmation, safety, wiki-first-query) loaded before task execution; Pi-specific size limits measured + documented (C-4 — the 32 KiB cap is Codex-only).
  - _Partial — missing: runtime/launcher loading of the generated `always-context.md`; measured + documented Pi size limits._
- [ ] **T2.4 (P1)** Stateful commands registered through the runtime (`/cct:*` family).
  - _Partial — missing: runtime registration of the six stateful commands the generator defers (`auto-build`, `phase-complete`, `ralph-start`, `review-decide`, `review-submit`, `cycle-start`)._
- [ ] **T2.5 (P1)** Resource provenance reporting (which package/path supplied each skill/prompt).
  - _Not started._
- [x] **T2.6 (P1)** `tests/test-pi-adapter.sh`: generation goldens, determinism, install idempotency.

## Slice B — Repository integration preview (Phase 3, gated per R6/FR-028)

- [ ] **T3.1 (P0)** `[providers.pi]` seed + `peer_for.pi` in `shared/templates/provider-profile-template.toml`; `providers-health.sh` Pi check (`pi-code version`).
- [ ] **T3.2 (P0)** `pi-review-provider` adapter script (FR-015b): validates `{review_request}` path, no shell interpolation, invokes `pi-code --profile peer-reviewer`, normalizes output, stderr diagnostics, runner exit codes. Flag validation vs pinned Pi version (V3: `--no-session` or temp `--session` fallback).
- [ ] **T3.3 (P0)** `peer-reviewer` profile enforcement (FR-015a): read-only tools (`read,grep,find,ls`), ephemeral session, no SDD/teams/subagents/write/packages, timeout + token budget; `peer-reviewer-exec` variant gated on runner sandbox confirmation.
- [ ] **T3.4 (P0)** No-recursion verification tests (reviewer cannot start reviews, launcher recursion markers).
- [ ] **T3.5 (P1)** Benchmark backend `scripts/benchmark_runner/backends/pi.py` over `--mode json`; run-record schema fields per provider-config spec; stub-benchmark CI smoke.
- [ ] **T3.6 (P1)** `provider-emit.sh` `pi` target (settings fragments / custom provider entries).
- [ ] **T3.7 (P1)** Wiki backend: explicit `--backend pi` first; auto-detect insertion (`claude → codex → pi → cursor`) only when capability `enabled` (FR-025/FR-028).
- [ ] **T3.8 (P1)** Capability flip logic: `providers.pi` reports `disabled` with reason until T3.2–T3.4 acceptance passes; PATH presence never implies `enabled`.
- [ ] **T3.9 (P2)** Bench preset featuring a Pi-driven comparison.

## Slice C — Enforced disciplined workflow (Phases 4–6)

### Phase 4 — SDD & phase workflow
- [ ] **T4.1 (P0)** Risk classifier (full/lightweight/none), persisted + user-correctable (FR-006).
  - _Not started._
- [ ] **T4.2 (P0)** Frontmatter parser + artifact completeness validator + `[NEEDS CLARIFICATION]` gate; `validate-spec.sh` parity fixtures.
  - _Partial — missing: `validate-spec.sh` parity fixtures (parity is asserted in comments only)._
- [ ] **T4.3 (P0)** Phase state machine (Research → Plan → Build → Review) with per-phase model/thinking/tools/skills/permissions/context/gates; persistent state.
  - _Partial — missing: per-phase model/thinking/tools/skills/permissions/context routing (deferred to Phase 7 per `phases.ts`)._
- [x] **T4.4 (P1)** `/cct:phase`, `/cct:status`; status UI fields (FR-020).
- [ ] **T4.5 (P1)** Cross-adapter SDD fixtures (Claude Code vs Pi agreement).
  - _Not started._

### Phase 5 — Hooks, permissions, protected operations
- [ ] **T5.1 (P0)** Neutral lifecycle-event schema + Pi event translator + shell-hook adapter (reuse existing hooks where semantics match; degraded/unsupported reporting otherwise) (FR-010).
  - _Not started._
- [ ] **T5.2 (P0)** allow/ask/deny engine (FR-009) + deterministic headless ask; reuse `permissions/*.json` profile content via importer.
  - _Partial — missing: the `permissions/*.json` importer._
- [ ] **T5.3 (P0)** Protected paths: canonicalization, symlink defenses, git command protection, secret-path protection, package-install protection, network policy.
  - _Partial — missing: package-install protection and network-policy enforcement (`allow_package_install` / `deny_network` are declared in config but read by no enforcement point)._
- [ ] **T5.4 (P0)** Audit log (C-9) + fail-open/fail-closed tests; four-mode (tui/print/json/rpc) blocker matrix.
  - _Partial — missing: audit fail-open/fail-closed tests; the four-mode (tui/print/json/rpc) blocker matrix._
- [ ] **T5.5 (P1)** Property/fuzz tests: shell parsing, chained/quoted commands, traversal, wildcards, malformed events.
  - _Partial — missing: a property/fuzz generator and malformed-event tests (hand-written adversarial cases exist)._

### Phase 6 — Verification & review workflow

## Slice D — Agent execution (Phases 7–8)

- [ ] **T7.1 (P0)** Neutral agent-manifest schema + Claude-agent importer.
- [ ] **T7.2 (P0)** SDK child-session runner: per-agent model/thinking/tools/permissions/skills, result contracts, timeout/cancellation, recursion + concurrency caps, foreground/background.
- [ ] **T7.3 (P0)** Worktree manager: worker/branch/worktree/tasks/ownership/verification/merge/cleanup tracking (FR-013).
- [ ] **T7.4 (P1)** Worker analytics correlation; partial-failure handling.
- [ ] **T8.1 (P0)** Team controller: identities, shared task ledger, assignment/claiming, messaging, plan approval, controlled shutdown (FR-012).
- [ ] **T8.2 (P1)** Team status UI, result synthesis, failure recovery; distinct-from-subagents tests.

## Slice E — Durable autonomous harness (Phases 9–10)

- [ ] **T9.1 (P0)** Session-state persistence + pre/post-compaction checkpoint/recovery + CCT compaction prompt (FR-017).
- [ ] **T9.2 (P1)** Memory promotion/deletion commands, MemKernel adapter (self-guarding), wiki-first retrieval, provenance, sensitive-memory controls.
- [ ] **T10.1 (P0)** Sandbox provider interface + Docker backend + detection/reporting (FR-019); autonomous/ci unrestricted-host rejection.
- [ ] **T10.2 (P1)** MCP provider interface + first audited backend (FR-018); provenance/permissions/connectivity reporting.
- [ ] **T10.3 (P1)** Auto-build-loop Pi backend; scheduler invocation contract; budget/timeout enforcement (C-5).
- [ ] **T10.4 (P2)** Evaluate Gondolin/OpenShell/remote sandbox backends.

## Slice F — Stable release (Phase 11)

- [ ] **T11.1 (P0)** Pi→CCT analytics mapping + redaction tests + Studio ingestion (FR-021/026).
- [ ] **T11.2 (P0)** Generated capability parity documentation from the registry; compatibility matrix.
- [ ] **T11.3 (P1)** Docs: quickstart, configuration reference, security model, migration-from-Claude-Code guide, extension development guide.
- [ ] **T11.4 (P1)** SBOM, checksums, release workflow, changelog; package publishing (pinned-tag `pi install` documented as advisory).
- [ ] **T11.5 (P1)** Security test battery complete (§18.5 of consolidated plan); cross-adapter contract suite green.
- [ ] **T11.6 (P1)** `lessons-learned.md`; alignment-maintenance checklist pass; README Supported Tools + tier table (Pi = Enforced).

## Cross-cutting

- [ ] **TX.1 (P0)** All security-relevant tasks include acceptance tests and audit-log coverage before merge to the feature branch mainline.
- [ ] **TX.2 (P0)** Branch policy: all work on `feature/pi-harness-adoption` (or child branches merged into it); no merge to `master` until spec.md Definition of Done holds.
- [ ] **TX.3 (P1)** Each task records files affected + delivery slice in its PR description (consolidated plan §15 tasks.md contract).
