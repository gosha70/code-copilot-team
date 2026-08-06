---
spec_mode: full
feature_id: pi-team-controller
risk_category: security
justification: |
  Wires the T8.1 team controller + T8.2 team status/synthesis/recovery libraries
  into the live Pi session. Safety-sensitive coordination STATE: it must enforce
  single-claimant tasks (no double-claim / cross-assignment / over-cap /
  pre-approval claims), the plan-approval gate, bounded concurrency, and a
  controlled shutdown that refuses to close over still-claimed work — all
  fail-closed and tamper-safe. Untrusted CLI/command input mutates a shared
  ledger, and peer messages must stay redacted. The libraries + their safety
  model already exist and are tested (#T8.1/#T8.2); this is wiring only, in the
  same discipline as the merged #172 worktree-lifecycle wiring.
status: draft
date: 2026-08-06
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/174
  design:
    - specs/pi-harness-adoption/design-t81-team-controller.md
    - specs/pi-harness-adoption/design-t82-team-status.md
  origin_claim: |
    The T8.1 team.ts and T8.2 team-status.ts libraries are built and tested; the
    agents.teams capability + agents.teams_enabled config key exist. Both design
    docs explicitly defer "live /cct:team command wiring" as out of scope — that
    deferred wiring is exactly what issue #174 ("deployment of design-t81/t82")
    asks for. This plan wires the command surface + CLI + session advisory +
    audit, composing the libraries without re-implementing them. Live peer
    execution, real message transport, FR-020 status-line, and FR-021 analytics
    stay out of scope (not Pi primitives / separate issues).
---

# Plan: Wire the T8.1/T8.2 team controller into Pi

## Existing facts (verified)

- `agents/team.ts`: pure ops `(ledger, …) → TeamOpResult { ok, ledger, error? }`
  — `createTeam(teamId, leadId, nowIso, {planRequired})`, `addTeammate`,
  `postTask(ledger, PostTaskInput)`, `assignTask`, `claimTask(ledger, taskId,
  memberId, nowIso, {maxConcurrency})`, `completeTask`, `failTask`,
  `approvePlan`, `activateTeam`, `requestShutdown(ledger, byId, reason, nowIso)`,
  `closeTeam`, `postMessage` (redacted), `loadTeamLedger(projectRoot)` /
  `saveTeamLedger(projectRoot, ledger)`. Ledger files: `.cct/team.json` +
  `.cct/team-messages.jsonl`. `loadTeamLedger` tamper-hardens on load.
- `agents/team-status.ts`: `teamStatus(ledger) → TeamStatusView` (pure),
  `renderTeamStatus(view, json)`, `synthesizeTeam(ledger) → TeamSynthesis`
  (verdict `complete|partial|failed|empty`), `markMemberLeft`,
  `reopenOrphanedClaims`.
- Config: `agents.teams_enabled` (lint.ts, off by default). `autonomy.max_concurrency`
  exists (the claim cap).
- Capability `agents.teams` exists, `degraded` (Pi) / `disabled` (Claude), with a
  reason already covering T8.1 **and** T8.2 — **no capability change needed**.
- `index.ts` has the `session_start` handler, the `registerCommand(…)` pattern
  (`cct:doctor|config|worktree|…`), the `emit(ctx, text)` helper, and the
  `tool_call` gate. `cli.ts` has the `pi-code <cmd> [--json]` diagnostic router.
  `withLedgerLock` (pid/token-owned, from the #172 work) lives in
  `agents/worktree-lifecycle.ts`.

## Design (wiring only)

### D1 — Thin command module `agents/team-commands.ts`
Holds the `/cct:team` subcommand handlers and the CLI `team status` handler. It
**composes** `team.ts` + `team-status.ts`, gates on `agents.teams_enabled`,
serializes mutations under the lock, and audits each action. `index.ts` and
`cli.ts` only call into it. Mirrors `agents/worktree-lifecycle.ts`.

### D2 — Feature gate (FR-1)
A single `teamsEnabled(cfg)` check fronts every subcommand. Disabled ⇒ return a
one-line opt-in message, **no** load/save. Read subcommands are also gated (a
disabled feature shows nothing) — consistent with the capability being off.

### D3 — Serialized mutations, shared lock (FR-3, reuse #172)
`saveTeamLedger` has no CAS, so every mutating subcommand runs its full
`load → op → save` inside a repo-scoped lock. **Generalize** the existing
`withLedgerLock(repoRoot, fn)` to `withLedgerLock(repoRoot, fn, { lockName })`
(default `worktrees` — a pure additive refactor keeping the pid/token ownership),
and use `lockName: "team"` here → `.cct/team.lock`, separate from
`worktrees.lock`. Extract the lock into `agents/ledger-lock.ts` so both modules
import it (no behavior change to the worktree path).

### D4 — Command surface (FR-1/FR-2)
`/cct:team <sub>` → the op, under the lock, audited:

| sub | op | notes |
|---|---|---|
| `create <teamId> <leadId> [--require-approval]` | `createTeam` | planRequired from flag |
| `join <memberId>` | `addTeammate` | teammate role |
| `task <taskId> <title…> [--assign <m>] [--worker <w>]` | `postTask` | open-pool or assigned |
| `assign <taskId> <memberId>` | `assignTask` | lead intent |
| `approve <memberId>` | `approvePlan` | plan-approval gate |
| `activate` | `activateTeam` | blocked until approved when required |
| `claim <taskId> <memberId>` | `claimTask({maxConcurrency})` | cap from `autonomy.max_concurrency` |
| `complete <taskId>` / `fail <taskId>` | `completeTask` / `failTask` | terminal |
| `message <from> <text…>` | `postMessage` | redacted append |
| `leave <memberId>` | `markMemberLeft` | reopens that member's claims |
| `recover` | `reopenOrphanedClaims` | sweep orphaned claims |
| `shutdown <byId> [--reason …]` | `requestShutdown` | recorded who/why |
| `close` | `closeTeam` | refused while a task is `claimed` |
| `status [--json]` | `teamStatus` + `renderTeamStatus` | read-only (T8.2) |
| `synthesize [--json]` | `synthesizeTeam` | fail-closed verdict (T8.2) |

Unknown/absent sub ⇒ usage text.

### D5 — CLI surface (FR-4)
`pi-code team status [--json]` and `pi-code team synthesize [--json]` — read-only,
resolve the project root, load the ledger, render. Routes through the launcher's
diagnostic dispatch to `cli.ts` (mirrors `pi-code worktree`), added to the
recursion-guard allow-list + help.

### D6 — Session-start advisory (FR-6)
In the existing `session_start` handler, when teams are enabled and
`.cct/team.json` exists, push a one-line `teamStatus` summary to `state.warnings`
+ audit `team.status`. Read-only; no recovery, no mutation.

### D7 — Audit + honesty (FR-5/FR-7)
Each action audits `team.<create|join|task|assign|claim|complete|fail|approve|
activate|message|shutdown|close|recover|leave|status>` with subject
`<teamId>:<subject>`, origin `team`. Docs + `pi-code doctor` state the `degraded`
boundary (no live execution/transport; snapshot status).

## Deliverables

1. `agents/ledger-lock.ts` — the pid/token lock extracted from
   worktree-lifecycle.ts, parameterized by `lockName` (worktree module updated to
   import it; behavior unchanged).
2. `agents/team-commands.ts` — gate + lock + audit wrappers over team.ts /
   team-status.ts; the `/cct:team` and CLI handlers.
3. `index.ts` — `registerCommand("cct:team", …)`; session-start advisory.
4. `cli.ts` — `pi-code team status|synthesize [--json]`.
5. `bin/pi-code` — route `team` to the runtime CLI, recursion-guard entry, help.
6. Docs — `adapters/pi/docs/team-coordination.md` (the `/cct:team` + CLI surface,
   the `agents.teams_enabled` gate, the two-file ledger, the degraded boundary);
   README link.
7. Tests (below).

## Sequencing

1. Extract/generalize `withLedgerLock` → `ledger-lock.ts` (+ update worktree
   import; re-run the worktree suite unchanged).
2. `team-commands.ts` gate + lock + audit wrappers (+ unit tests over a temp
   project: full lifecycle + each refusal branch).
3. `registerCommand("cct:team", …)` + session-start advisory in `index.ts`
   (python-edit to avoid the prettier hook churn).
4. `pi-code team status|synthesize` in `cli.ts` + launcher route/help + launcher
   test.
5. Docs + honesty note.

## Test strategy

- **Gated surface (AC-1):** disabled ⇒ refusal + zero side effects; enabled ⇒
  end-to-end lifecycle green (temp project).
- **Contract (AC-2):** double-claim, cross-assignment claim, over-cap claim,
  pre-approval claim, and close-while-claimed each refused (library error
  surfaced through the wiring).
- **Concurrency (AC-3):** two real processes claim one task simultaneously
  (barrier-released, reusing the #172 fixture pattern) → exactly one wins.
- **Status/synthesis/recovery (AC-4):** counts + `complete|partial|failed|empty`
  verdict; `leave`/`recover` reopen orphaned claims, never auto-complete.
- **Audit + CLI (AC-5):** one `team.*` record per action (CCT_HOME temp);
  `pi-code team status --json` snapshot read-only.
- **No-invented-event (AC-6):** wiring subscribes only to `session_start` +
  registers the command (asserted); worktree lock behavior unchanged after the
  extraction.

Home: `tests/pi-runtime/team-commands.test.mjs` (+ a spawn fixture), launcher
assertion in `tests/test-pi-launcher.sh`.

## Resolved decisions (settled by the built libraries)

1. **Capability** → `agents.teams`, `degraded` (Pi) / `disabled` (Claude); reason
   already covers T8.1+T8.2 — no change.
2. **State model** → `.cct/team.json` + `.cct/team-messages.jsonl`, separate from
   `worktrees.json`, linked by optional `Task.workerId`.
3. **Claiming/approval/shutdown semantics** → as implemented in team.ts
   (single-claimant, approval-gated, bounded, close-refused-while-claimed).
4. **Synthesis verdict / recovery** → `complete|partial|failed|empty` fail-closed;
   recovery **reopens** (never auto-`done`/`failed`), per team-status.ts.

## Open question for the reviewer

- **Lock generalization vs a second helper:** D3 extracts `withLedgerLock` into a
  shared `ledger-lock.ts` (parameterized `lockName`). Alternative: leave the
  worktree lock untouched and add a tiny sibling `team.lock` helper. Lean:
  **extract + parameterize** (DRY, keeps the proven pid/token ownership in one
  place). Confirm before implementation.
