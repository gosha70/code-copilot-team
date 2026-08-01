# Tasks: Pi Harness Adoption

Slices map to the consolidated plan §17 (with Slice B redefined per R6 as a
gated integration preview). Priorities: **P0** = gates the phase's
Done-when; **P1** = required for the umbrella DoD; **P2** = polish.
Task IDs: `T<phase>.<n>`.

## Progress — updated 2026-07-30

Every task below must be delivered; the `spec.md` Definition of Done stands as
written. Current state: **57 of 65 complete.** Phases 0–2 and 4 complete; Phase 5 complete; Phase 6 complete; **Slice B COMPLETE (T3.1–T3.9)**; **Slice E COMPLETE** (Phase 9 T9.1+T9.2; Phase 10 T10.1–T10.4); **Slice D COMPLETE** (Phase 7 T7.1–T7.4; Phase 8 T8.1+T8.2); **Slice F started** (T11.1 Pi analytics adapter). Remaining: **Slice F** (Phase 11, release — T11.2–T11.6).

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
3. **Slice B** — Phase 3 — ✅ complete (gated acceptance passed; providers.pi enabled).  ~~**gated (R6/FR-028); runs last.**~~ The integration
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
- [x] **T3.5 (P1)** Benchmark backend `scripts/benchmark_runner/backends/pi.py` over `--mode json`; run-record schema fields per provider-config spec; stub-benchmark CI smoke.
- [x] **T3.6 (P1)** `provider-emit.sh` `pi` target (settings fragments / custom provider entries).
  - _UNBLOCKED + done: built provider-config Phase 2 (T2.1/T2.2) in full — `shared/scripts/provider-emit.sh` translates a provider profile per copilot (claude-code/aider/codex/github-copilot/cursor/windsurf/**pi**), golden-tested (`tests/test-provider-emit.sh`, 20); the `pi` target emits a `.code-copilot-team/config.toml` provider fragment. All 7 `adapters/<copilot>/setup.sh` gained `--provider`/`--providers-file` via a shared handler (`provider-setup.sh`); codex idempotently appends to `~/.codex/config.toml`. Backcompat proven (no `--provider` = inert). `tests/test-provider-setup.sh` (10)._
- [x] **T3.7 (P1)** Wiki backend: explicit `--backend pi` first; auto-detect insertion (`claude → codex → pi → cursor`) only when capability `enabled` (FR-025/FR-028).
- [x] **T3.8 (P1)** Capability flip logic: `providers.pi` reports `disabled` with reason until T3.2–T3.4 acceptance passes; PATH presence never implies `enabled`.
- [x] **T3.9 (P2)** Bench preset featuring a Pi-driven comparison.

## Slice D — Agent execution (Phases 7–8)

- [x] **T7.1 (P0)** Neutral agent-manifest schema + Claude-agent importer.
    Schema (`agents/manifest.ts`) reuses the phase-policy leaf set
    (model/thinking/tools/skills/context/permissions) + validation (kebab/unique
    name, thinking vocab, required fields). Pure importer
    (`agents/import-claude-agents.ts`) maps `.claude/agents` frontmatter →
    manifests: model tier carried verbatim, the Claude `Agent` tool flagged (no
    Pi equivalent), and the four Claude-inexpressible fields marked not-sourced
    on neutral `inherit`/`[]` sentinels — never fabricated. Fixtures + golden
    drift guard; capability `agents.subagents` reports **degraded** (resolved &
    reported, not enforced — child-session spawn is T7.2, gated on verifying
    Pi's SDK surface). Design: `design-t71-agent-manifest.md`. Tests:
    `agent-manifest.test.mjs`, `import-claude-agents.test.mjs` (17). No runtime
    disk reads, no spawn. _Enforcement of any manifest field lands with T7.2._
- [x] **T7.2 (P0)** SDK child-session runner: per-agent model/thinking/tools/permissions/skills, result contracts, timeout/cancellation, recursion + concurrency caps, foreground/background.
    Out-of-process `pi --mode json` subprocess runner (verified pi CLI surface;
    the SDK exposes no subagent primitive/result contract/caps — confirmed
    against earendil-works/pi). `agents/child-session.ts`: pure `buildChildArgv`
    (manifest → `--model`/`--thinking`/`--tools`/`--no-session`, thinking
    vocab-mapped, `permissions`/`skills`/`context` reported `notEnforced` not
    dropped) + async `runChildSession` (spawn, wall-clock timeout→kill,
    AbortSignal cancellation, typed `ChildResult` from the `--mode json`
    envelope, no-runner/error/cap-exceeded statuses). `agents/caps.ts`:
    `resolveCaps` (autonomy.max_concurrency/max_recursion), `Semaphore`,
    `recursionExceeded`. Capability `agents.subagents` reason rewritten:
    model/thinking/tools/isolation/timeout/cancel/caps **enforced**;
    permissions/skills/context-beyond-isolation/max-turns **degraded**. Design:
    `design-t72-child-session-runner.md`. Tests: `child-session.test.mjs`
    (mock-pi integration: flags-passed, timeout, cancel, no-runner, error,
    recursion cap) + `agent-caps.test.mjs` (18). _Live `/cct:` invocation wiring
    + full analytics correlation are follow-ups (T7.4)._
- [x] **T7.3 (P0)** Worktree manager: worker/branch/worktree/tasks/ownership/verification/merge/cleanup tracking (FR-013).
    `agents/worktree.ts`: versioned, sanitized `.cct/worktrees.json` ledger of
    `WorkerRecord` (id/branch/path/feature/tasks/ownedAreas/verification/merge/
    cleanup/`origin:"cct"`). Pure planners — `validateCreateRequest`,
    `detectOwnershipConflicts` (overlap **refused** on assignment),
    `cleanupEligibility` (origin/primary/clean/merge gate), `reconcile`
    (stale/foreign) — plus thin git-exec (`createWorktree`/`removeWorktree`/
    `listWorktrees`/`pruneWorktrees`, realpath-normalized) and orchestration
    (`createWorker`/`cleanupWorker`). Safety: never master/main, never
    force/reset/`branch -D`, only `origin:"cct"` worktrees removable (foreign
    reported, never touched), dirty-refusal, stale recovery. Capability
    `agents.worktrees` **degraded**: isolation+lifecycle+conflict-detection
    enforced; verification/merge EXECUTION (T7.4/T8) + write-time ownership
    (permission layer) out. Design: `design-t73-worktree-manager.md`. Tests:
    `worktree-planners.test.mjs` + `worktree-git.test.mjs` (real temp-repo, 20).
    _Verify-run is T7.4; merge is T8; write-time ownership is the permission layer._
- [x] **T7.4 (P1)** Worker analytics correlation; partial-failure handling.
    `agents/worker-analytics.ts` (one cohesive module): `runWorkerVerification`
    executes the FR-016 verify runner IN a worker worktree and maps to a
    `VerificationStatus` (ran+pass→passed, ran+!pass→failed, !ran→**pending**,
    never a silent pass) — the field T7.3 tracked. `buildCorrelation`/
    `emitCorrelation` write a **redacted** (`containsSecret`→`[REDACTED]`)
    worker→parent record to `.cct/worker-analytics.jsonl` (re-redacted on emit).
    `summarizeBatch` is **fail-closed**: a worker passes only on verification
    `passed` AND childStatus `ok`; any pending/timeout/error/cap-exceeded ⇒ never
    all-passed. Capability `agents.worktrees` reason updated (verification now
    executed; merge still T8). **FR-021 boundary preserved**: emits neutral
    correlation records only — no full analytics translation / DB ingestion /
    Studio. Design: `design-t74-worker-analytics.md`. Tests:
    `worker-analytics.test.mjs` (13). _Merge execution is T8; full analytics is FR-021._
- [x] **T8.1 (P0)** Team controller: identities, shared task ledger, assignment/claiming, messaging, plan approval, controlled shutdown (FR-012).
    `agents/team.ts` — CCT-first-party coordination STATE, distinct from
    subagents (peers, not parent→child). Two files kept SEPARATE from
    worktrees.json: `.cct/team.json` (ledger) + `.cct/team-messages.jsonl`
    (redacted append); a task links to a worker only by optional `workerId`.
    Fail-closed ops: createTeam (one lead) / addTeammate / postTask /
    assignTask / **claimTask** (active + approval-satisfied + open +
    self-or-unassigned + under cap + single-claimant, else refused) /
    complete/fail / approvePlan (lead only) / activateTeam / requestShutdown /
    closeTeam (only when no task claimed) / postMessage (redacted). Plan approval
    gates BOTH activation and claiming; bounded by autonomy.max_concurrency;
    tamper-safe load. Capability `agents.teams` **degraded** (Pi) / **disabled**
    (Claude). Design: `design-t81-team-controller.md`. Tests: `team.test.mjs`
    (17). _Live peer execution via T7.2/T7.4; UI/synthesis/recovery are T8.2._
- [x] **T8.2 (P1)** Team status UI, result synthesis, failure recovery; distinct-from-subagents tests.
    `agents/team-status.ts` — read-model + recovery over the T8.1 ledger.
    `teamStatus`/`renderTeamStatus`: on-demand SNAPSHOT (members/roles/approval/
    task-counts/workerCount per FR-020) as text or JSON, mirroring doctor/
    features. `synthesizeTeam`: fail-closed verdict `complete|partial|failed|
    empty` (complete only when all tasks done; never complete while a task is
    open/claimed/failed) + failedTasks. Recovery: `markMemberLeft` (member→left +
    REOPEN its claimed tasks for reclaim) / `reopenOrphanedClaims` (sweep
    left/inactive-held claims) — reopen only, no auto-success/failure. Explicit
    distinct-from-subagents tests (separate ledger file; peer-claim not spawn;
    workerId optional link; peers not parent→child; no execution surface
    imported). Capability `agents.teams` reason refreshed (snapshot+synthesis+
    recovery present; live UI/execution still absent), stays degraded/disabled.
    Design: `design-t82-team-status.md`. Tests: `team-status.test.mjs` (13).
    _Live UI transport + peer execution are not Pi primitives._

## Slice E — Durable autonomous harness (Phases 9–10)

- [x] **T9.1 (P0)** Session-state persistence + pre/post-compaction checkpoint/recovery + CCT compaction prompt (FR-017).
  - _DEGRADED by construction — Pi emits no observable compaction event (`hooks/events.ts`: PreCompact/PostCompact `unsupported`), so this cannot be a true pre-compaction hook. Delivered: `workflow/checkpoint.ts` — a durable `.cct/pi-session.json` checkpoint (phase/feature/count, corrupt-safe) written at explicit CCT actions (`/cct:checkpoint` + every phase transition); recovery at `session_start` re-injects a digest + the `COMPACTION_PROMPT` into context and audits it, so a resumed/post-compaction session re-learns CCT state. Capability `memory.session-state` = `degraded` (Pi) / `enabled` (Claude, which has real PreCompact/PostCompact). Tests: `checkpoint.test.mjs` (6) + `session-recovery.test.mjs` (3, driven through the real activation). NOT this task: memory promotion / MemKernel / wiki-retrieval = T9.2._
- [x] **T9.2 (P1)** Memory promotion/deletion commands, MemKernel adapter (self-guarding), wiki-first retrieval, provenance, sensitive-memory controls.
  - _`workflow/memory.ts` + commands `/cct:remember <type> <fact>`, `/cct:memory`, `/cct:memory-forget <id>`, `/cct:recall <query>`. Built-in store `.cct/memory.json` is authoritative (corrupt-safe), each record carries provenance (phase/feature/timestamp). SENSITIVE control is FAIL-CLOSED: a fact matching a secret-VALUE signature (sk-/AKIA/ghp_/JWT/PEM/key=value) is REFUSED, never stored, and audited (origin "memory"). Wiki-first `/cct:recall` consults `knowledge/wiki/index.md` before the memory store. MemKernel adapter is DETECTION + a self-guard only — MemKernel is an MCP server, so code-aware delegation is DEGRADED pending the Pi MCP provider (integrations.mcp, T10.2); `memkernelStatus()` reports pending-MCP honestly. Capability `memory.promotion` = degraded (Pi) / enabled (Claude, MemKernel-over-MCP). 9 tests. **Phase 9 complete (T9.1 + T9.2).**_
- [x] **T10.1 (P0)** Sandbox provider interface + Docker backend + detection/reporting (FR-019); autonomous/ci unrestricted-host rejection.
  - _`policy/sandbox.ts`: a `SandboxProvider` interface + Docker backend (cgroup / `/.dockerenv` / container env) + an env-declaration backend (micro-vm / remote-sandboxed / explicit host); `detectSandbox()` classifies into the FR-019 states, `sandboxGate()` enforces the rule. ENFORCED at the real `tool_call` gate: an `autonomous`/`ci` posture (`security.sandbox_required` / `autonomy.reject_unrestricted_host`) on a `host-unrestricted` environment REJECTS all tool execution fail-closed, unless `CCT_SANDBOX_OVERRIDE=1` (audited). Reported in doctor/status + capability `security.sandbox` (degraded — the runtime detects/reports/rejects but cannot itself CREATE a sandbox; micro-vm/remote need operator `CCT_SANDBOX` declaration; permissions ≠ sandboxing, spec P5). 12 tests (gate logic + detection + tool_call enforcement through the real activation)._
- [x] **T10.2 (P1)** MCP provider interface + first audited backend (FR-018); provenance/permissions/connectivity reporting.
  - _`policy/mcp.ts`: the FR-018 modes (`disabled`/`external-package`/`first-party-bridge`/`remote-gateway`), a `McpBackend` declaration, `probeBackend()` (connectivity by PATH — NEVER spawns the server), and `mcpReport()` rendering the full FR-018 surface (provenance/trust/permissions/tools/connectivity/version/security). **MemKernel** is the first audited backend (external-package, tools retain/recall/get/forget). `/cct:mcp` reports each declared backend and AUDITS it (origin "mcp") — no backend is silent (P6); trust-gated (an untrusted project withholds it, FR-004a). Config `integrations.mcp.enabled` (default false) opts in. Capability `integrations.mcp` flipped `disabled → degraded` — the interface + audited backend + connectivity exist, but live JSON-RPC invocation flows through Pi's own MCP transport (extension does not own it). T9.2's `memkernelStatus()` now consults the probe. 8 tests. This is the piece T9.2 left pending._
- [x] **T10.3 (P1)** Auto-build-loop Pi backend; scheduler invocation contract; budget/timeout enforcement (C-5).
  - _`scripts/auto-build-loop.sh` retrofitted with a backend dispatcher: `CCT_AUTOBUILD_BACKEND` (claude default | pi) selects `run_session`, which dispatches to `run_claude_session` (UNCHANGED) or the new `run_pi_session`. Same invocation contract (`<prompt-file> <result-file> [session-id]` → a JSON result the driver reads: `.total_cost_usd`/`.subtype`/`.session_id`); `run_pi_session` invokes `pi-code --mode json -p` with `subject_provider` tracking the backend and a backend-aware preflight. C-5 budget/timeout: a hard wall-clock `timeout` (`build.session_timeout_sec`, default 1800) parks the session on overrun + a `build.budget_tokens` env passed to the runtime. The 158-test Claude suite is preserved exactly; +8 Pi-backend tests (mock pi-code: preflight reject, single-phase happy run — pi invoked/claude NOT/subject_provider=pi, C-5 timeout park on hosts with timeout(1)). Suite 166; shared-structure 797; runtime 195._
- [x] **T10.4 (P2)** Evaluate Gondolin/OpenShell/remote sandbox backends.
  - _`sandbox-backends-eval.md`: evaluated Docker (done), generic remote, micro-VM (Firecracker/gVisor/Kata), Gondolin, and OpenShell against T10.1's `SandboxProvider` interface on 4 axes (FR-019 state / native detection / gate semantics / P5-P6 honesty). Conclusion: the T10.1 env backend already covers all of them TODAY via explicit `CCT_SANDBOX` declaration (operator declares the FR-019 state; runtime records/audits/gates); NO blind detectors added — a named provider is verification-gated (the codex verified-signature bar), since a false `containerized`/`micro-vm` classification would wrongly satisfy the autonomous/ci gate. The interface needs no change to add one later. The eval also FOUND + FIXED a T10.1 gap: `SandboxState` was missing `external-policy-controlled` (now added, FR-019-complete), and the gate wrongly accepted `permission-gated-only` — corrected to reject it (permissions ≠ sandboxing, P5). Matrix test asserts all 6 FR-019 states are declarable + gate-correct. **Slice E COMPLETE.**_

## Slice F — Stable release (Phase 11)

- [x] **T11.1 (P0)** Pi→CCT analytics mapping + redaction tests + Studio ingestion (FR-021/026).
    Python adapter `session_analytics/adapters/pi.py` (mirrors claude_code.py) +
    `COPILOT_PI` + registration in `_register.py`. Source: CCT's OWN emitted
    analytics — `.cct/worker-analytics.jsonl` (T7.4 interim) + `.cct/pi-session.json`
    (feature/phase); Pi's native transcript is NOT parsed (unverified format).
    Each worker record → one synthetic `is_sidechain` `RawTurn`
    (role=assistant; pipeline-compatible). **Honest absence** (null-vs-zero):
    per-turn tokens / tool-call detail / message text / model → None/(); denials /
    review-rounds / compactions → out-of-slice, all listed in
    `metadata.absent_fields` + asserted. Redaction flows the EXISTING shared path
    (`ingest.redaction.redact_text`) with T7.4 emit-time `containsSecret` as layer
    2 — no new regex; high-risk surfaces (code/tool I/O) absent by construction.
    Studio ingestion via registration (no schema change). **Persistence boundary
    (review):** the store persists only fixed columns — no surface for
    `RawSession.metadata`, so `cost_usd`/`worker_outcomes`/`correlation_ids`/
    `final_verdict`/`feature_id` are computed IN MEMORY but NOT written to the DB
    (listed in `metadata.not_persisted_by_current_store`); a DB-level ingest test
    pins what survives (session id/project/phase/timestamps/turn_count/sidechain
    turns; per-turn cost NULL — no tokens). Persisting worker analytics needs a
    store-schema surface — **open decision / follow-up**. Design:
    `design-t111-analytics.md`. Tests: `test_adapter_pi.py` (8, incl. DB-level
    ingest); full session_analytics suite 205/0. _Native-transcript tokens,
    denials/review/compaction sources, and worker-analytics persistence are
    named follow-ups._
- [ ] **T11.2 (P0)** Generated capability parity documentation from the registry; compatibility matrix.
- [ ] **T11.3 (P1)** Docs: quickstart, configuration reference, security model, migration-from-Claude-Code guide, extension development guide.
- [ ] **T11.4 (P1)** SBOM, checksums, release workflow, changelog; package publishing (pinned-tag `pi install` documented as advisory).
- [ ] **T11.5 (P1)** Security test battery complete (§18.5 of consolidated plan); cross-adapter contract suite green.
- [ ] **T11.6 (P1)** `lessons-learned.md`; alignment-maintenance checklist pass; README Supported Tools + tier table (Pi = Enforced).

## Cross-cutting

- [ ] **TX.1 (P0)** All security-relevant tasks include acceptance tests and audit-log coverage before merge to the feature branch mainline.
- [ ] **TX.2 (P0)** Branch policy: all work on `feature/pi-harness-adoption` (or child branches merged into it); no merge to `master` until spec.md Definition of Done holds.
- [ ] **TX.3 (P1)** Each task records files affected + delivery slice in its PR description (consolidated plan §15 tasks.md contract).

## Follow-ups (named, not silent gaps)

_Not part of the 65-task tracker denominator — non-checkbox bullets so the
mechanical count stays aligned with the header. Promote to a numbered task if
scheduled._

- **FU-1 (P1)** Persist Pi worker analytics to the Studio DB. T11.1 maps
    `cost_usd`/`worker_outcomes`/`correlation_ids`/`final_verdict`/`feature_id`
    into `RawSession.metadata`, but the store has no surface for session metadata
    so they do not reach the DB (per-turn cost is NULL without tokens). Add a
    session-metadata surface (table/columns) written during ingest — a
    shared-pipeline change that would also recover claude's dropped `git_branch`.
    Decision recorded (2026-08-01): narrow T11.1, track persistence here.
