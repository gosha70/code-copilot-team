# T11.5 Design Read — Security test battery + cross-adapter contract (DoD §18.5 / items 10–12)

Status: **design read — approval needed on the battery grouping, the manifest,
and the cross-adapter scope before implementing.** T11.5 is P1 and is
**consolidation, not new behavior**: it indexes what is already enforced, adds a
thin *executable battery* that proves each invariant in one place, fills the few
genuine gaps, and honestly calls out what is intentionally degraded.

## The requirement (spec Definition of Done, the §18.5-equivalent)

- **Item 11 (security tests):** path traversal, symlinks, shell-wrapper bypass,
  injection via docs/tool output, package substitution, fork bombs, worktree
  cross-contamination, analytics secret leakage.
- **Item 12 (cross-adapter contract):** Claude Code and Pi agree on SDD
  classification, artifacts, phase order, gate/permission decisions, review
  artifact formats, provider dispatch, verification outcomes, analytics
  semantics — **behavioral parity, not identical text**.
- **Item 10:** subagents/teams bounded + isolated; autonomous/CI require an
  isolation policy.

## Inventory — what is ALREADY covered (the point: little is missing)

| Security category (your list) | Enforced by | Covered by test |
|---|---|---|
| trust gating | `config/trust.ts`, index recovery trust-gate | `config.test.mjs`, `session-recovery.test.mjs` |
| protected paths | `policy/protected.ts` | `enforcement.test.mjs` ("traversal and symlinks cannot bypass"), `fuzz.test.mjs` |
| command denial | `policy/protected-ops.ts` | `protected-ops.test.mjs`, `fuzz.test.mjs` (chaining/priv-prefix bypass) |
| sandbox fail-closed | `policy/sandbox.ts` | `sandbox.test.mjs` |
| secret redaction | `workflow/memory.ts` `containsSecret`; T7.4/T8.1 emit-redaction | `memory.test.mjs`, `worker-analytics.test.mjs`, `team.test.mjs` |
| lifecycle hook honesty | `hooks/events.ts` (`unsupported`/`degraded`) | `hooks.test.mjs`, `fuzz.test.mjs` |
| tamper-safe ledgers | `agents/worktree.ts` `loadLedger`, `agents/team.ts` `loadTeamLedger`+`reconcileLedger` | `worktree-planners.test.mjs`, `team.test.mjs` |
| fail-closed team/worktree | `claimTask`, `cleanupEligibility`, ownership overlap | `team.test.mjs`, `worktree-git.test.mjs` |

| DoD-11 vector | Status |
|---|---|
| path traversal / symlinks | **covered** (enforcement + fuzz + worktree symlink-escape) |
| shell-wrapper bypass | **covered** (fuzz priv/env prefixes; `stripPrivilegePrefix`) |
| injection via docs/tool output | **covered** for the persistence surface (`checkpoint.test.mjs` "tampered checkpoint sanitized"; memory/message redaction) — battery adds one consolidating assertion |
| package substitution | **covered** (`protected-ops` package-install classification) |
| worktree cross-contamination | **covered** (ownership conflict refusal, isolation, foreign-worktree protection) |
| analytics secret leakage | **covered** (worker-analytics + team-message redaction) |
| **fork bombs** | **INTENTIONALLY DEGRADED** — Pi "cannot itself create a sandbox"; fork-bomb containment is an OS/sandbox concern. Called out, not forced. |

**Cross-adapter contract already partly enforced:** `validate-capabilities.sh`
requires *every catalog id classified by every adapter* (Pi and Claude agree on
the capability SET); `sdd-cross-adapter/` + `sdd-parity/` fixtures cover SDD
classification/artifacts/phase-order parity. T11.5 names + consolidates these.

## Proposed grouping (smallest battery + audit manifest + contract)

### 1. Executable battery — `tests/pi-runtime/security-battery.test.mjs`
ONE canonical fail-closed assertion per category, importing the SAME real
functions the deep tests use (a thin *invariant index*, not a re-implementation):
1. trust gating — untrusted project-local surface is not injected/read.
2. protected paths — a write under a protected path is refused.
3. command denial — a denied command survives chaining/priv-prefix.
4. sandbox fail-closed — autonomous + host-unrestricted + no override → blocked.
5. secret redaction — a secret value is refused/`[REDACTED]`.
6. lifecycle hook honesty — an unsupported event reports `unsupported`, never a fake pass.
7. tamper-safe ledger — a tampered team ledger loads fail-closed (no bogus-lead approval; no ghost claim).
8. fail-closed team/worktree — `claimTask` / `cleanupEligibility` refuse the unsafe path.

Value: if any category's fail-closed behavior regresses, ONE named battery test
fails — a single security tripwire over the whole surface.

### 2. Audit manifest — `specs/pi-harness-adoption/security-battery.md`
A checked-in map: each DoD-11 vector + each of the 8 categories + each DoD-12
item → the covering test(s), plus a **"Degraded, not parity"** section naming
every intentionally-degraded item with rationale AND the registry status that
reports it honestly (sandbox/fork-bombs, live UI, live peer transport,
Stop/compaction events). This makes coverage auditable and the degraded boundary
explicit.

### 3. Cross-adapter contract — `tests/pi-runtime/cross-adapter-contract.test.mjs`
**Shared semantics ONLY, never native features.** Assert the shared source both
adapters consume is the single source, and Pi's runtime conforms:
- capability contract: the same catalog id SET is classified by both adapters
  (assert via the registry — the identity `validate-capabilities` enforces).
- SDD classification + phase order: Pi's runtime classifies the shared
  `sdd-cross-adapter/` fixtures the way the contract specifies (behavioral
  parity, not text).
- analytics semantics: the neutral CCT format (T11.1) is the shared contract.
- **excluded** (native, not shared): Claude's native subagents/worktrees/teams,
  Pi's `--mode json` internals — anything where the registry says one adapter is
  `native`/`enabled` and the other `degraded`/`disabled` is a *deliberate*
  divergence, asserted as such, not forced to parity.

## What is intentionally degraded (called out, not forced to parity)

Named in the manifest, each tied to its honest registry status:
- **fork-bomb / resource-exhaustion containment** — no sandbox creation
  (`security.sandbox` degraded; Pi cannot create a sandbox).
- **live UI / status transport** — snapshot only (`agents.teams` degraded).
- **live peer execution / message transport** — runners + polled log (`agents.teams`).
- **Stop / compaction lifecycle events** — none observable (`verification.enforcement`,
  `memory.session-state` degraded).
The battery asserts these are reported `degraded`/`unsupported`/`disabled` in the
registry — i.e., the honesty boundary holds — rather than testing a behavior Pi
deliberately does not implement.

## Consolidation, not new behavior (explicit)

T11.5 adds **tests + a manifest only** — no new enforcement, no changed
semantics. Every assertion imports an existing function; every "gap" filled is a
missing *test*, not a missing *behavior*. If the battery reveals a real gap in
enforcement, that becomes its own task, not a silent addition here.

## Scope (in / out)

**In:** `security-battery.test.mjs` (8 canonical invariants),
`cross-adapter-contract.test.mjs` (shared-semantics parity),
`security-battery.md` (audit manifest + degraded call-outs); wiring into the pi
runtime suite; design doc.

**Out:** new enforcement/behavior; native-feature parity; the SBOM/release
(T11.4); README tier table (T11.6); docs site (T11.3); any registry content
change.

## Open questions for approval

1. **Battery form** — a thin executable `security-battery.test.mjs` (8 canonical
   invariants) **plus** the audit manifest, vs a manifest alone (mapping to
   existing tests, no new test). Lean: **both** — the executable battery is the
   single tripwire; the manifest is the audit.
2. **Cross-adapter contract scope** — shared semantics only (capability set, SDD
   classification/phase order, analytics neutral format); native-feature
   divergences asserted as *deliberate*, not forced. Confirm.
3. **Degraded call-outs** — assert honest registry status (degraded/unsupported/
   disabled) for fork-bombs/live-UI/live-transport/Stop-compaction, rather than
   testing behavior Pi doesn't implement. Confirm.
4. **Manifest location** — `specs/pi-harness-adoption/security-battery.md`. Confirm.
