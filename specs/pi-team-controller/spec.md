# Spec: Wire the T8.1/T8.2 local team ledger into Pi (Slice A of #174)

Source: GitHub issue **#174** (epic — a centralized team management plane).
**This is Slice A only**, the foundation: wire the **already-built, tested** local
team libraries (`agents/team.ts` = T8.1, `agents/team-status.ts` = T8.2) into
Pi's live session as the `/cct:team` command + CLI surface. It **does not** close
#174 — the centralized/cross-developer plane (registry, cross-machine
aggregation, cost rollups, budget alerting, dashboard) is shaped separately in
`plane-shaping.md` and delivered by later slices. No re-implementation of the
libraries — wiring only, in the same discipline as the merged #172.

> Revised per the PR #184 review. The four P1 blockers (scope, split ledger,
> untrusted identity, unsafe create) and the two P2 gaps (signatures, CLI gate)
> are all resolved below.

## Context (do NOT rebuild)

`agents/team.ts` ships the two-file state model + ops
(`createTeam`, `addTeammate`, `postTask`, `assignTask`, `claimTask`,
`completeTask`, `failTask`, `approvePlan`, `activateTeam`, `requestShutdown`,
`closeTeam`, `postMessage`, `loadTeamLedger`/`saveTeamLedger`) over
`.cct/team.json` + `.cct/team-messages.jsonl`. `agents/team-status.ts` ships
`teamStatus`/`renderTeamStatus`, `synthesizeTeam`, `markMemberLeft`,
`reopenOrphanedClaims`. The `agents.teams` capability (`degraded`) and the
`agents.teams_enabled` config key (off by default) already exist.

**Known library facts the wiring must respect** (verified against the code):
- **Most ops are pure over the ledger** returning `TeamOpResult { ok, ledger,
  error? }`. **`postMessage(projectRoot, from, to, body, nowIso): boolean` is
  NOT** — it is a side-effecting append to `team-messages.jsonl` returning a
  boolean (redacts from/to/body on write).
- `completeTask(ledger, taskId, memberId)` and `failTask(ledger, taskId,
  memberId)` **require `memberId`**; `approvePlan(ledger, byLeadId)` and the other
  actor-scoped ops validate only that the **supplied** id matches ledger state —
  they do **not** prove the caller *is* that member.
- `assignTask` does **not** enforce lead-only; any id can assign.
- `loadTeamLedger(projectRoot)` returns **`null` for both a missing file AND a
  corrupt/tampered one** — indistinguishable without a separate existence check.
- `createTeam` constructs a **fresh** ledger with no knowledge of storage — a
  naive `load→op→save` would silently overwrite an existing team.
- Teams are **coordination STATE, not execution** (peers run via T7.2/T7.4;
  messaging is a polled append-log; status is a snapshot) — `degraded` by design.
- A `TeamTask` links to a T7.3 worker only by an optional `workerId`; the two
  ledgers stay separate.

## User Scenarios

- **US1 — Form and run a team (identity-safe).** As a lead, I create a team, add
  teammates, post/assign tasks, approve, and activate via `/cct:team` — every
  actor-scoped action is attributed to my **trusted session identity**, not a
  typed-in id, and the coordination contract is enforced fail-closed.
- **US2 — Claim and complete (one canonical ledger).** As a teammate running in
  my **own linked worktree**, I claim/complete tasks against the **primary
  repo's** single team ledger — never a per-worktree copy — so two workers
  cannot both claim the same task.
- **US3 — Observe and recover.** As a lead/operator, I view a status snapshot +
  fail-closed synthesis and reopen a departed member's orphaned claims; teardown
  is an explicit, recorded shutdown/close that refuses to close over
  still-claimed work.

## Requirements

- **FR-1 — Feature-gated command surface.** Register `/cct:team <sub>` covering
  the T8.1 + T8.2 op set. **Mutations are gated by `agents.teams_enabled`** (off
  by default) — disabled ⇒ opt-in message + **no** side effect. (Read-only
  `status`/`synthesize` follow FR-8.)
- **FR-2 — Canonical team-state root (no split ledger).** ALL team state resolves
  through **`primaryRepoRoot(cwd)`** (the shared git common dir, from #172) —
  `team.json`, `team-messages.jsonl`, `team.lock`, status, synthesis, the
  session advisory, and CLI reads. A teammate in a linked worktree operates on
  the **primary** ledger, never a per-worktree copy.
- **FR-3 — Trusted session identity (no impersonation).** The actor for
  actor-scoped subcommands (`claim`, `complete`, `fail`, `approve`, `message`,
  `leave`, `shutdown`) is derived from a **session identity contract**
  (`CCT_TEAM_ID` + `CCT_TEAM_MEMBER_ID`), validated at `session_start` against the
  ledger (member exists / matches team) — **not** from command arguments. A
  mismatch/absent identity fails closed for those subcommands.
- **FR-4 — Explicit authorization for admin subcommands.** `assign`, `activate`,
  `close`, `recover`, and plan-`approve` are **lead-only** (the wiring enforces
  it — the library does not); `create`/`join`/`task` are open local
  administration. The chosen authz for each subcommand is documented; commands
  that provide **attribution only** (not authenticated authorization) say so.
- **FR-5 — Safe create/corrupt/missing ledger paths.** `create` acquires the
  lock, then: `team.json` exists + valid ⇒ refuse "team already exists";
  exists + corrupt ⇒ refuse "team ledger invalid", **never overwrite**; absent ⇒
  create + save. Every other mutation: load ⇒ `null` ⇒ refuse (no save); else op;
  save only on `ok`. Reads/advisory: missing ⇒ "no team"; corrupt ⇒ fail-closed
  warning (never pass `null` into `teamStatus`).
- **FR-6 — Serialized mutations + correct message path.** Every mutation runs its
  full `load → op → save` inside a repo-scoped lock (`lockName: "team"`).
  `message` uses a **dedicated locked append** via `postMessage(primaryRoot, …)`,
  surfaces `postMessage === false` as failure, and does **not** rewrite
  `team.json`.
- **FR-7 — Audit every action.** Each action emits a `team.*` audit record
  (decision, rule, subject `<teamId>:<actor|task>`).
- **FR-8 — CLI surface with honest gate semantics.** `pi-code team status|
  synthesize [--json]` is **read-only** and works whenever a **valid ledger
  exists**, regardless of the (out-of-session, project-untrusted)
  `agents.teams_enabled` value; JSON includes `enabled: true|false|unknown` + the
  standard CLI trust note. Ignored project config is **never** reported as an
  authoritative `false`.
- **FR-9 — Session-start advisory (fail-closed).** On `session_start`, when teams
  are enabled and a valid `.cct/team.json` exists (at the primary root), push a
  one-line `teamStatus` summary + audit `team.status`; read-only, no recovery.
- **FR-10 — Honesty.** Docs + diagnostics state the `degraded` boundary and that
  this slice is **local** team coordination (the centralized plane is #174's
  later slices, shaped in `plane-shaping.md`).

## Constraints

- No re-implementation of `team.ts` / `team-status.ts`. A **small additive** lock
  generalization is permitted: `withLedgerLock(repoRoot, fn, { lockName })` with
  `type LedgerLockName = "worktrees" | "team"` (constrained union — no
  path-shaped names); the worktree module imports it, behavior unchanged.
- Wiring uses **only** `registerCommand` + `session_start` + the CLI — no invented
  Pi event, no live message transport.
- Runtime is TypeScript strict; launcher/env stays bash 3.2 compatible.
- Team ledger separate from the worktree ledger (link by `Task.workerId` only);
  message content stays redacted on append.
- `agents.teams` capability stays `degraded` (Pi) / `disabled` (Claude).

## Out of scope (→ #174's later slices, see plane-shaping.md)

- **Centralized / cross-developer plane:** shared registry, cross-machine
  aggregation, developer identity population, developer/team/repo cost rollups,
  budget + runaway-loop alerting, a team dashboard. These need the topology +
  identity/auth decisions shaped first.
- **Live peer execution / real message transport** — not Pi primitives.

## Acceptance criteria

1. **Gated + safe create:** with `agents.teams_enabled` off, mutations refuse and
   write nothing; with it on, the full lifecycle works. A second `create`, and a
   `create` over a **corrupt** `team.json`, both refuse and leave the file
   **byte-for-byte unchanged**.
2. **Canonical ledger across worktrees:** integration test with **two real linked
   worktrees** — worker A claims `task-1` from worktree A; worker B reads status
   from worktree B and sees `task-1` claimed; A and B claim `task-2`
   simultaneously ⇒ exactly one wins in the **primary** ledger.
3. **Identity enforced:** an actor-scoped subcommand with an identity that does
   not match the ledger member is **refused**; the actor is taken from
   `CCT_TEAM_MEMBER_ID`, not the argument; lead-only admin subcommands refuse a
   non-lead.
4. **Contract:** double-claim, cross-assignment claim, over-cap claim,
   pre-approval claim, and close-while-claimed each refused.
5. **Status/synthesis/recovery + message:** correct counts + fail-closed verdict;
   `leave`/`recover` reopen (never auto-complete); `message` appends via the
   locked path, surfaces a `false` return as failure, and does not touch
   `team.json`.
6. **CLI gate semantics:** `pi-code team status` renders a valid ledger even when
   `agents.teams_enabled` is only in (untrusted) project config; JSON reports
   `enabled: true|false|unknown` + the trust note.
7. **No new event source:** wiring uses only `registerCommand` / `session_start`
   / the CLI; gates green; the extracted lock leaves the worktree concurrency +
   stale-owner tests passing unchanged.
