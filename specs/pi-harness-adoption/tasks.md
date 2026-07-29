# Tasks: Pi Harness Adoption

Slices map to the consolidated plan §17 (with Slice B redefined per R6 as a
gated integration preview). Priorities: **P0** = gates the phase's
Done-when; **P1** = required for the umbrella DoD; **P2** = polish.
Task IDs: `T<phase>.<n>`.

## Progress — updated 2026-07-25

Every task below must be delivered; the `spec.md` Definition of Done stands as
written. Current state: **40 of 65 complete.** Phases 0–2 and 4 complete; Phase 5 complete; Phase 6 complete; Slice B gate cluster complete (T3.1–T3.4, T3.8 — providers.pi flipped to `enabled`, bound to its acceptance suite). Remaining in Slice B: T3.5–T3.7, T3.9 (benchmark/emit/wiki/preset).

Unchecked tasks carry a `_Partial — missing: …_` note naming exactly what is
still absent, so each one can be picked up and finished directly. A task is
checked only when every deliverable named in its own text exists and its tests
pass — including the security constraints those deliverables are subject to, not
just their happy path. Work proceeds in phase order.

## Execution order (by slice, not phase number)

Work proceeds by **slice**, which deliberately deviates from phase
numbering. Agreed sequence:

1. **Slice A** — Phases 0–2 — ✅ complete
2. **Slice C** — Phases 4–6 — ✅ complete (Phase 4 ✅; Phase 5 ✅; Phase 6 ✅)
3. **Slice B** — Phase 3 — **gated (R6/FR-028); runs last.** The integration
   preview validates against the completed enforcement path; `providers.pi`
   stays `disabled` until T3.2–T3.4 acceptance passes.
4. **Slice D** — Phases 7–8, then **Slice E** — Phases 9–10.

The sections below are ordered to match this sequence (Slice B appears after
Slice C). Phase *numbers* still map to `plan.md` §17 — only the presentation
order deviates.

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
  - _Post-merge fix: `config explain --json` emitted sensitive values verbatim while the
    text path redacted them — a C-3 violation. Redaction now covers the value and every
    history entry on all surfaces, with a planted-secret sweep proven to fail against the
    defective code. Checked only after that fix._
- [x] **T1.7 (P1)** Config migration mechanism + obsolete-key detection; `validate-cct-config` CI job.
- [x] **T1.8 (P2)** Redacted resolved-configuration `export`.

### Phase 2 — Skills, prompts, always-context
- [x] **T2.1 (P0)** `generate.sh` `[pi]` section: verbatim skills copy → `adapters/pi/resources/skills/`; deterministic ordering; drift check in `sync-check.yml`.
- [x] **T2.2 (P0)** Command→prompt-template conversion: static/stateful classification, frontmatter normalization (`description`, `argument-hint`), `$ARGUMENTS`/`$1..$n` preservation, collision validation, Claude-only metadata handling.
- [x] **T2.3 (P0)** Always-context bundle from `ALWAYS_SKILLS` (coding-standards, copilot-conventions, copyright-headers, origin-confirmation, safety, wiki-first-query) loaded before task execution; Pi-specific size limits measured + documented (C-4 — the 32 KiB cap is Codex-only).
- [x] **T2.4 (P1)** Stateful commands registered through the runtime (`/cct:*` family).
- [x] **T2.5 (P1)** Resource provenance reporting (which package/path supplied each skill/prompt).
- [x] **T2.6 (P1)** `tests/test-pi-adapter.sh`: generation goldens, determinism, install idempotency.

## Slice C — Enforced disciplined workflow (Phases 4–6)

### Phase 4 — SDD & phase workflow
- [x] **T4.1 (P0)** Risk classifier (full/lightweight/none), persisted + user-correctable (FR-006).
- [x] **T4.2 (P0)** Frontmatter parser + artifact completeness validator + `[NEEDS CLARIFICATION]` gate; `validate-spec.sh` parity fixtures.
- [x] **T4.3 (P0)** Phase state machine (Research → Plan → Build → Review) with per-phase model/thinking/tools/skills/permissions/context/gates; persistent state.
  - _Resolve + report only: per-phase policy is config-driven and surfaced in status /
    /cct:phase / doctor. Applying model/thinking (session respawn) is Phase 7; live
    per-phase permission switching is Phase 5 — both reported as not-enforced._
- [x] **T4.4 (P1)** `/cct:phase`, `/cct:status`; status UI fields (FR-020).
- [x] **T4.5 (P1)** Cross-adapter SDD fixtures (Claude Code vs Pi agreement).

### Phase 5 — Hooks, permissions, protected operations
- [x] **T5.1 (P0)** Neutral lifecycle-event schema + Pi event translator + shell-hook adapter (reuse existing hooks where semantics match; degraded/unsupported reporting otherwise) (FR-010).
  - _Boundary (source-read verified, design-t51-events.md): supported =
    SessionStart (<- session_start), PreToolUse (<- tool_call); degraded =
    Notification (outbound-only); unsupported = PostToolUse / Stop / PreCompact /
    PostCompact (no observable Pi event) — reported + audited, never
    approximated. project_trust stays Pi-internal. Existing `.sh` hooks reused
    as subprocesses (no logic ported); support gate + timeout/retry/fail-mode +
    audit._
- [x] **T5.2 (P0)** allow/ask/deny engine (FR-009) + deterministic headless ask; reuse `permissions/*.json` profile content via importer.
  - _Engine + deterministic headless ask: done (pre-existing). Importer:
    delivered — `importClaudePermissions()` pure converter maps Claude
    allow/deny/ask (bare tools, `Bash(<prefix>:*)` -> commandsDeny/Ask,
    path-scoped -> protected_paths) to Pi rule lists, with structured warnings
    for no-Pi-target entries and read-vs-write `notEnforced` reporting;
    balanced/relaxed/web-dynamic fixtures + adversarial path/Bash tests.
    LIVE-WIRING (this slice): `Profile.importPermissions?: string[]`
    (`disciplined`/`peer-reviewer`/`air-gapped`→balanced, `autonomous`→relaxed;
    most-derived wins); a new `policy/permission-profiles.ts` resolver reads the
    reused JSON (managed install first — bundled by `setup.sh` — repo fallback),
    runs the converter, and the loader injects a computed `imported` layer above
    defaults / below the profile. Imported denies compose through the monotonic
    floor as `base ∪ imported` (audited `strengthened`); non-floor allow/ask are
    the base a profile may override; `warnings`/`notEnforced` surface in
    `LoadResult.warnings`. Engine unchanged. 10 live-wiring tests + full sweep
    green. See design-t52-live-wiring.md._
- [x] **T5.3 (P0)** Protected paths: canonicalization, symlink defenses, git command protection, secret-path protection, package-install protection, network policy.
  - _Package-install (`allow_package_install`) + network (`deny_network`)
    enforcement now live at the bash exec path (`checkExecPolicy`): manager+verb
    package classification (never the manager alone), network-binary/git-subcommand
    denylist, `sudo`/`env`-prefix stripping, `security.fail_closed` governs the
    ambiguous tail; audited as `package-policy`/`network-policy`. `deny_network`
    is a command-name denylist, NOT a sandbox (P5) — doctor reports that
    boundary. Default config (allow_package_install=true, deny_network=false)
    blocks nothing new. Canonicalization/symlink/git/secret-path pre-existed._
- [x] **T5.4 (P0)** Audit log (C-9) + fail-open/fail-closed tests; four-mode (tui/print/json/rpc) blocker matrix.
- [x] **T5.5 (P1)** Property/fuzz tests: shell parsing, chained/quoted commands, traversal, wildcards, malformed events.
  - _Seeded (reproducible) property/fuzz harness (`fuzz.test.mjs`): never-throw
    invariants over command parsers / path matchers / event translators;
    no-smuggling of denied / network / install commands via chaining + prefixes;
    protected basenames caught through `../` traversal + wildcards; malformed
    lifecycle events. Exposed and fixed one security bug — `sudo` / `env` /
    assignment prefixes bypassed the `denied_commands` denylist (`checkCommand`
    now strips via `stripPrivilegePrefix` before matching)._

### Phase 6 — Verification & review workflow
- [x] **T6.1 (P0)** Peer-review runner integration + bounded review-loop state machine + existing artifact formats (FR-015).
  - _Delivered via #126 + #127 (design d021ccf; thin driver over `review-round-runner.sh`; mandatory-review gate at `/cct:phase-complete` + `review→next` as the Stop-hook replacement). Post-merge fix (PR #127): `/cct:review-submit` initially reset loop state each round, neutralizing all three breakers — now init-or-continue with a monotonic-round regression test. Checked only after that fix._
- [x] **T6.2 (P0)** Verification gates: build/unit/integration/lint/type-check/dependency-audit/security/visual/docs/drift (FR-016).
  - _Thin driver over `scripts/verify-runner.sh` (mirror T6.1): `verifyGate`
    joins the phase-complete conjunction (`sdd && review && verify`) + the
    review→next block; new `/cct:verify`; `verification.required` list config +
    array-union floor; `verification.enforcement` capability (degraded — no Stop
    event, and lint/type-check/dependency-audit report `unsupported`, never
    faked). Fail-closed: absent runner + non-empty required = FAIL, and
    required+unsupported = a hard config error (leak-shaped tests cover both)._
- [x] **T6.3 (P1)** Audited human override; `CCT_PEER_*` env contract via launcher flags (FR-000a).
  - _pi-code mirrors `--peer-review [provider]` / `--peer-review-off` /
    `--peer-review-scope` (spaced + equals; optional-provider heuristic; scope
    validated) and exports the FR-000a trio on the enforced path only. The
    launcher OWNS the peer env (clears ambient `CCT_PEER_*` — no shell backdoor,
    guardrail A). `/cct:review-submit` reads provider/scope as session intent
    (ARG > env > profile). `--peer-review-off` / `CCT_PEER_BYPASS` = an AUDITED
    peer-review-only override at the phase-complete + review→next gates — never a
    silent `review.mandatory` downgrade, no verify/permission reach._
- [x] **T6.4 (P1)** `pi-code init` (Pi-native `.code-copilot-team/config.toml` + `.cct-init.json` ownership manifest) + `pi-code sync [--dry-run]` (literal `generate.sh`/`setup.sh --sync` contract; manifest-driven ownership; `--dry-run` no-write/no-stage) (FR-000a).
- [x] **T6.5 (P1)** CCT-scoped type-check gate: `tsc --noEmit` over `adapters/pi/runtime`, promoting the T6.2 `type-check` gate from `unsupported` to `supported`. Follow-up from T6.2's honesty model; prioritized because `--experimental-strip-types` strips without checking (the T1.5 undefined defect shipped for exactly this reason).
  - _New `adapters/pi/runtime/tsconfig.json` (ESM + bundler resolution + extension-ful `.ts` imports, mirroring the strip-types runtime; `strict` enforced; `noUncheckedIndexedAccess` deferred with a note — it flags ~28 safe-in-practice index sites out of scope here). Fixed the one real `strict` error it surfaced (`profiles.ts` self-referential initializer → explicit `Profile | undefined`). `verify-runner.sh` `type-check` gate now runs `tsc --noEmit -p` when a runnable tsc + the runtime tsconfig are present (supported/pass), else `unsupported` — never a fake pass. `typescript`/`@types/node` pinned as devDeps (+ lockfile); CI installs them and runs the gate with `CCT_REQUIRE_TSC=1` so the supported path is always exercised. Capability `verification.enforcement` reason updated (stays `degraded` — Pi still has no Stop event). Test: `tests/test-typecheck-gate.sh` (green baseline + supported/unsupported honesty)._

## Slice B — Repository integration preview (Phase 3, gated per R6/FR-028)

_Sequenced after Slice C per the execution-order note at the top: the gated
integration preview validates against the completed enforcement path;
`providers.pi` stays `disabled` until T3.2–T3.4 acceptance passes._

- [x] **T3.1 (P0)** `[providers.pi]` seed + `peer_for.pi` in `shared/templates/provider-profile-template.toml`; `providers-health.sh` Pi check (`pi-code version`).
- [x] **T3.2 (P0)** `pi-review-provider` adapter script (FR-015b): validates `{review_request}` path, no shell interpolation, invokes `pi-code --profile peer-reviewer`, normalizes output, stderr diagnostics, runner exit codes. Flag validation vs pinned Pi version (V3: `--no-session` or temp `--session` fallback).
- [x] **T3.3 (P0)** `peer-reviewer` profile enforcement (FR-015a): read-only tools (`read,grep,find,ls`), ephemeral session, no SDD/teams/subagents/write/packages, timeout + token budget; `peer-reviewer-exec` variant gated on runner sandbox confirmation.
  - _ENFORCED now, tested through the real policy path (`checkTool`/`checkCommand`/the `/cct:review-submit` handler): read-only tool allowlist (write/edit/bash denied), `allow_package_install:false`, and no-recursion (a reviewer session is blocked from starting reviews — T3.4). `timeout_sec` flows to the review-runner spawn. HONESTLY NOT YET ENFORCED: `session.ephemeral`, `agents.teams_enabled`/`subagents_enabled`, `max_tokens` — those operations don't exist until Slice D (Phases 7–8); the checks land with them. `peer-reviewer-exec` (sandboxed exec variant) is deferred to the runner-sandbox work. The declared flags remain honest config, not faked enforcement._
- [x] **T3.4 (P0)** No-recursion verification tests (reviewer cannot start reviews, launcher recursion markers).
- [ ] **T3.5 (P1)** Benchmark backend `scripts/benchmark_runner/backends/pi.py` over `--mode json`; run-record schema fields per provider-config spec; stub-benchmark CI smoke.
- [ ] **T3.6 (P1)** `provider-emit.sh` `pi` target (settings fragments / custom provider entries).
- [ ] **T3.7 (P1)** Wiki backend: explicit `--backend pi` first; auto-detect insertion (`claude → codex → pi → cursor`) only when capability `enabled` (FR-025/FR-028).
- [x] **T3.8 (P1)** Capability flip logic: `providers.pi` reports `disabled` with reason until T3.2–T3.4 acceptance passes; PATH presence never implies `enabled`.
- [ ] **T3.9 (P2)** Bench preset featuring a Pi-driven comparison.

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
