# Spec: Wire the T8.1/T8.2 team controller into Pi's session lifecycle

Source: GitHub issue **#174** (`design-t81-team-controller.md` + `design-t82-team-status.md`).
Wires the **already-built, tested** team libraries
(`adapters/pi/runtime/agents/team.ts` = T8.1, `agents/team-status.ts` = T8.2)
into Pi's live session — the **"live `/cct:team` command wiring"** both design
docs explicitly deferred as out-of-scope. **No** re-implementation of the
libraries or their coordination/safety model — only the missing live wiring, in
the same discipline as #172 (worktree lifecycle).

## Context (do NOT rebuild)

`agents/team.ts` already ships the two-file state model and every operation:
`createTeam`, `addTeammate`, `postTask`, `assignTask`, `claimTask`,
`completeTask`, `failTask`, `approvePlan`, `activateTeam`, `requestShutdown`,
`closeTeam`, `postMessage` (redacted append), `loadTeamLedger`/`saveTeamLedger`
(tamper-safe), over `.cct/team.json` + `.cct/team-messages.jsonl`.
`agents/team-status.ts` ships `teamStatus` + `renderTeamStatus`,
`synthesizeTeam`, `markMemberLeft`, `reopenOrphanedClaims`. Each op is a pure
function over a `TeamLedger` returning `TeamOpResult { ok, ledger, error? }`.
The `agents.teams` capability record and the `agents.teams_enabled` config key
(off by default) already exist.

**Known library facts the wiring must respect** (verified for this spec):
- Ops are pure — the wiring owns `loadTeamLedger → op → saveTeamLedger`. Ledger
  I/O has **no lock/CAS** (same as the worktree ledger did).
- Teams are **coordination STATE, not execution**: the controller never spawns
  peers (they run via the T7.2/T7.4 runners separately), messaging is a polled
  append-log, and status is an on-demand snapshot — all `degraded` by design.
- A `TeamTask` links to a T7.3 worker only by an optional `workerId`; the team
  ledger and the worktree ledger stay **separate**.
- The library's built-in choices settle the design docs' "approval-needed"
  questions: exactly one lead; single-claimant tasks (double-claim /
  cross-assignment / over-cap / pre-approval claims refused fail-closed); a
  plan-approval gate on activation and claiming; synthesis verdict
  `complete | partial | failed | empty` (fail-closed); recovery **reopens**
  a departed member's claims (never auto-`done`/`failed`).

## User Scenarios

- **US1 — Form and run a team.** As a lead orchestrating peers, I create a team,
  add teammates, post/assign tasks, approve the plan, and activate it via
  `/cct:team` — each action recorded fail-closed in the shared ledger, audited,
  and refused when the coordination contract is violated (e.g. a second claim on
  an already-claimed task).
- **US2 — Claim and complete work.** As a teammate, I claim an open task
  assigned to me (or from the open pool), respecting the concurrency cap and the
  plan-approval gate, then mark it done/failed — exactly one claimant wins.
- **US3 — Observe and recover.** As a lead/operator, I view a team status
  snapshot + fail-closed result synthesis, and recover a departed member's
  orphaned claims (reopened, never silently completed); teardown is an explicit,
  recorded shutdown/close that refuses to close while work is still claimed.

## Requirements

- **FR-1 — Feature-gated command surface.** Register `/cct:team <sub>` covering
  the full T8.1 + T8.2 op set: `create`, `join`, `task`, `assign`, `claim`,
  `complete`, `fail`, `approve`, `activate`, `message`, `status`, `synthesize`,
  `recover`, `leave`, `shutdown`, `close`. Every subcommand is **gated by
  `agents.teams_enabled`** (off by default) — disabled ⇒ a clear "teams are
  opt-in; set agents.teams_enabled" reply and **no** ledger side effect.
- **FR-2 — Wiring composes the library; never re-implements it.** Each mutating
  subcommand runs `loadTeamLedger → <op> → saveTeamLedger` and surfaces the op's
  `error` verbatim on failure. Read subcommands (`status`, `synthesize`) are pure
  reads over the loaded ledger. The wiring adds no new coordination rule.
- **FR-3 — Serialized ledger mutations (concurrency-safe).** Because
  `saveTeamLedger` has no CAS, every mutating subcommand runs inside a
  **repo-scoped lock** so two peers acting at once cannot lose each other's
  writes or both win a single-claimant task. Reuse the existing pid/token lock
  (generalized to a `team` lock file, separate from `worktrees.lock`).
- **FR-4 — Read-only CLI surface.** Add `pi-code team status [--json]` (and
  `synthesize`) mirroring the `pi-code worktree`/`features` diagnostic pattern,
  so a driver/dashboard can poll team state outside a session.
- **FR-5 — Audit every action.** Each create/join/task/assign/claim/complete/
  fail/approve/activate/message/shutdown/close/recover/leave emits a `team.*`
  audit record (decision, rule, subject `<teamId>:<taskOrMember>`).
- **FR-6 — Session-start advisory (fail-closed).** On `session_start`, when
  `agents.teams_enabled` and a `.cct/team.json` exists, surface a one-line team
  status warning (member/task counts, approval/shutdown state) — read-only,
  never mutating. No auto-recovery of claims on start (recovery is explicit).
- **FR-7 — Honesty.** Docs + diagnostics state the `degraded` boundary: no live
  peer execution (T7.2/T7.4 run peers separately), messaging is a polled log,
  status is an on-demand snapshot — degraded by construction, not a bug.

## Constraints

- No re-implementation of `team.ts` / `team-status.ts` or their guarantees;
  wiring composes them. A **small additive** lock generalization is permitted.
- Wiring uses **only** `registerCommand` + `session_start` + the CLI — no
  invented Pi event, no live message transport.
- Runtime is TypeScript strict; the launcher/env stays bash 3.2 compatible.
- The team ledger stays **separate** from the worktree ledger (link by
  `Task.workerId` only); message content stays redacted on append.
- `agents.teams` capability stays `degraded` (Pi) / `disabled` (Claude Code);
  no status/kind drift.

## Out of scope (per the design docs)

- **Live peer execution / real message transport** — not Pi primitives; peers
  run via the T7.2/T7.4 runners; messaging is the polled append-log.
- **FR-020 general status-line integration** and **FR-021 team analytics** —
  separate follow-ups; this issue delivers the `/cct:team` + CLI surface only.

## Acceptance criteria

1. **Gated surface:** with `agents.teams_enabled` off, every `/cct:team` mutating
   subcommand refuses with the opt-in message and writes nothing; with it on, the
   full lifecycle (create→join→task→assign→approve→activate→claim→complete→
   shutdown→close) works end-to-end against a temp project.
2. **Contract enforced through the wiring:** a double-claim, a cross-assignment
   claim, an over-cap claim, and a pre-approval claim are each **refused**
   (library error surfaced), and `close` is refused while a task is still
   `claimed`.
3. **Concurrency:** two simultaneous claims on one task (real processes) → exactly
   one wins; both survive to the ledger for distinct tasks.
4. **Status/synthesis:** `status`/`synthesize` render correct counts and a
   fail-closed verdict (`complete` only when all `done`); `recover`/`leave`
   reopen a departed member's claims (never auto-complete).
5. **Audit + CLI:** each action emits one `team.*` record; `pi-code team status
   --json` returns the snapshot read-only.
6. **No new event source:** wiring uses only `registerCommand` / `session_start`
   / the CLI; gates green (runtime + typecheck + launcher).
