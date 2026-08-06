# Spec: Wire the T8.1/T8.2 local team ledger into Pi (issue #185, Slice A of #174)

Source: GitHub issue **#185** — Slice A of the **#174** epic (a centralized team
management plane). This slice is the foundation: wire the **already-built,
tested** local team libraries (`agents/team.ts` = T8.1, `agents/team-status.ts` =
T8.2) into Pi's live session as the `/cct:team` command + `pi-code team` CLI. It
**does not** close #174 — the centralized/cross-developer plane is shaped in
`plane-shaping.md` and delivered by later slices. No re-implementation of the
libraries — wiring only, in the same discipline as the merged #172.

> Revised across two PR #184 review rounds. Resolved: scope (Slice A), split
> ledger, unsafe create, op signatures, CLI gate, lock. This revision adds:
> a fail-closed canonical root, per-mutation authorization re-validation, an
> honest attribution (not authentication) identity model, the create bootstrap,
> and `--no-plan-approval`.

## Context (do NOT rebuild)

`agents/team.ts` ships the two-file state model + ops over `.cct/team.json` +
`.cct/team-messages.jsonl`; `agents/team-status.ts` ships status/synthesis/
recovery. The `agents.teams` capability (`degraded`) + `agents.teams_enabled`
(off by default) exist.

**Known library facts the wiring must respect** (verified against the code):
- Most ops are pure over the ledger → `TeamOpResult { ok, ledger, error? }`.
  **`postMessage(projectRoot, from, to, body, nowIso): boolean` is NOT** — a
  side-effecting redacted append returning a boolean.
- `completeTask/failTask(ledger, taskId, memberId)` require `memberId`;
  `approvePlan(ledger, byLeadId)` checks the id is the recorded lead **but not
  active status**; `requestShutdown` accepts **any** member id; `assignTask` is
  **not** lead-restricted; `markMemberLeft` lets **any** member (incl. the sole
  lead) go `left`. There is **no credential, worker-binding, or session token**
  in the library — IDs and roles only. **There is no lead-transfer op.**
- `loadTeamLedger` returns **`null` for both missing AND corrupt**.
- `createTeam(teamId, leadId, nowIso, {planRequired})` builds a **fresh** ledger,
  storage-unaware; **`planRequired` defaults to `true`**.
- Teams are coordination STATE, not execution — `degraded`. A `TeamTask` links to
  a T7.3 worker by an optional `workerId`; the two ledgers stay separate.

## Identity model (honest scope — read first)

Slice A provides **declared, ledger-validated ATTRIBUTION — not authentication.**
The `CCT_TEAM_*` env below is a *declared* identity: a co-located session can
declare any member id that exists in the ledger, so Slice A **does not prevent a
local session from impersonating another member or the lead.** That is acceptable
for **local coordination among cooperating agents**. **Authenticated
authorization** — binding a member to an unforgeable credential (a
controller-issued capability, or the *validated* T7.3 worker identity from #172) —
is an **epic-level decision** that folds into #174's identity/auth topology
shaping. Slice A must not claim to prevent impersonation.

What Slice A **does** enforce (a real improvement over id-in-args): the actor is
taken from the **session-declared** identity (`teamId` **and** `memberId`, both
mandatory), the declared `teamId` is **validated against `ledger.teamId`** on
every mutation (team binding — a session cannot act on a team it does not
declare, nor on a replacement team that reuses a member id), and authorization is
**re-validated against the current ledger inside the lock on every mutation** —
never a cached role/status.

## User Scenarios

- **US1 — Form and run a team.** As a lead, I create a team, add teammates,
  post/assign tasks, approve, and activate via `/cct:team`; each actor-scoped
  action is attributed to my session-declared identity and re-checked against the
  live ledger; the coordination contract is enforced fail-closed.
- **US2 — Claim and complete on one canonical ledger.** As a teammate running in
  my own linked worktree, I claim/complete against the **primary** repo's single
  team ledger; if the primary root can't be resolved, the command **refuses**
  rather than writing a per-worktree copy.
- **US3 — Observe and recover.** As a lead/operator, I view a status snapshot +
  fail-closed synthesis and reopen a departed member's orphaned claims; teardown
  is an explicit, recorded shutdown/close that refuses to close over still-claimed
  work; the sole lead cannot strand the team.

## Requirements

- **FR-1 — Feature-gated command surface.** Register `/cct:team <sub>` over the
  T8.1+T8.2 op set. **Mutations are gated by `agents.teams_enabled`** (off by
  default) — disabled ⇒ opt-in message + no side effect. (Read-only follows FR-8.)
- **FR-2 — Canonical team-state root, FAIL-CLOSED.** All team state resolves
  through `resolveTeamRoot(cwd) → { ok: true, root } | { ok: false, reason }`,
  where `root` is `primaryRepoRoot(cwd)` (the shared git common dir, #172). When
  it **cannot** be resolved (git failure / not a repo), **mutations refuse, audit
  `team.root-unresolved`, and write nothing** — never fall back to `cwd` (that is
  the split-ledger FR-2 prevents). Reads report "no canonical repository root".
  Every path — load/save/message/lock/status/synthesis/advisory/CLI — uses the
  resolved `root`.
- **FR-3 — Declared identity (both ids MANDATORY); actor never from args.** The
  declared identity contract is `{ teamId: string; memberId: string }` — **both
  `CCT_TEAM_ID` and `CCT_TEAM_MEMBER_ID` are required** for any actor-scoped or
  membership-requiring subcommand; a missing/empty declared id ⇒ refuse + audit
  `team.identity-invalid`. The actor comes from this contract, never a command
  argument. Session state stores **only these two immutable declared ids** — not
  a cached role/status. (Attribution, not authentication — see the identity model
  above.)
- **FR-4 — Authorization re-validated per mutation, inside the lock.** Every
  mutation, after loading the ledger under the lock, requires
  `identity.teamId === ledger.teamId` (**team binding** — else refuse + audit
  `team.identity-invalid`; prevents a stale session operating on a replacement
  team), then resolves `actor = members.find(identity.memberId)` and requires
  `actor?.status === "active"`. Authorization tiers:
  - **`create`** — bootstrap exception: requires the declared identity and
    `<teamId arg> === identity.teamId`; does **not** require pre-existing
    membership (it establishes the lead).
  - **`join` / `task`** — require the declared identity + the actor to be an
    **active member** under the lock; do **not** require lead.
  - **`assign` / `approve` / `activate` / `recover` / `close`** — require the
    actor to be the **active lead** as of the loaded ledger (never a session-start
    cache; a lead that has since `left` loses authority).
  `message` likewise loads the ledger under the lock and validates
  team-binding / sender-active / recipient-valid / team-not-closed before
  appending. **Sole-lead guard:** `leave` by the only active lead of a non-closed
  team is **refused** (no lead-transfer op in Slice A); document it.
- **FR-5 — Safe create + bootstrap.** `create <teamId> [--no-plan-approval]`
  (approval **required by default**, matching the library; the flag opts out).
  The `<teamId>` argument **must equal `identity.teamId`** (else refuse) — a
  session cannot create a team it does not declare itself part of. Under the lock:
  if `team.json` exists — valid ⇒ refuse "already exists"; corrupt ⇒ refuse
  "ledger invalid", **never overwrite**. Absent ⇒
  `createTeam(teamId, identity.memberId, now, {planRequired: !noPlanApproval})`
  (lead = the declared member); save. **Bootstrap:** the declared member becomes
  a valid active lead in the just-saved ledger; because session state holds only
  the declared ids, subsequent commands re-validate against that ledger with
  **no restart** required.
- **FR-6 — Serialized mutations + correct message path.** Every mutation runs
  `resolve-root → lock → load → authz → op → save` (create per FR-5). `message`
  uses the dedicated locked append `postMessage(root, actor, to, body, now)`,
  surfaces `false` as failure, and does **not** rewrite `team.json`.
- **FR-7 — Audit every action** (`team.*` incl. `root-unresolved`,
  `identity-invalid`), subject `<teamId>:<actor|task>`.
- **FR-8 — CLI surface with honest gate semantics.** `pi-code team status|
  synthesize [--json]` is **read-only**, at the resolved root, and renders
  whenever a **valid ledger exists** regardless of the (out-of-session,
  project-untrusted) `agents.teams_enabled`; JSON includes
  `enabled: true|false|unknown` + the CLI trust note. Ignored project config is
  never reported as authoritative `false`. Unresolved root ⇒ "no canonical
  repository root".
- **FR-9 — Session-start advisory (fail-closed).** On `session_start`, when teams
  are enabled and a **valid** `.cct/team.json` exists at the resolved root, push a
  one-line `teamStatus` summary + audit; read-only, never `null`→`teamStatus`;
  unresolved root ⇒ silent (no advisory).
- **FR-10 — Honesty.** Docs/diagnostics state: this is the **local** slice of the
  #174 epic; the identity is **attribution, not authentication**; and the
  `degraded` boundary (no live execution/transport, snapshot status).

## Constraints

- No re-implementation of `team.ts` / `team-status.ts`. Additive lock:
  `withLedgerLock(repoRoot, fn, { lockName })`, `type LedgerLockName =
  "worktrees" | "team"` (constrained union); worktree module imports it, behavior
  unchanged.
- Wiring uses **only** `registerCommand` + `session_start` + the CLI.
- Team ledger separate from the worktree ledger; messages redacted on append.
- `agents.teams` stays `degraded` (Pi) / `disabled` (Claude).

## Out of scope (→ #174 epic, plane-shaping.md)

- Centralized/cross-developer plane; **authenticated** identity/authorization;
  live peer execution / real message transport; lead transfer.

## Acceptance criteria

1. **Fail-closed root:** forcing `gitCommonDir()` to fail from a linked worktree
   ⇒ a mutation refuses + audits `team.root-unresolved` and creates **no**
   `team.json` / message file / lock in that worktree; a read reports "no
   canonical repository root".
2. **Canonical ledger across worktrees:** two real linked worktrees — claim in A
   is visible from B; concurrent claim of one task ⇒ exactly one wins in the
   **primary** ledger.
3. **Authorization is live, not cached:** an **active teammate** who becomes
   `left` is **refused** on its next actor-scoped command (re-validated, not
   cached); the same stale-cache property for a **lead** is proven with an
   externally-modified/reloaded ledger fixture (the normal lifecycle cannot make
   the sole lead `left`); a non-member / non-active actor and a non-lead admin
   command are refused. The **sole active lead cannot `leave`** a non-closed team.
4. **Team binding + join/task authz:** declared `CCT_TEAM_ID=A` + `create B` ⇒
   refused, **no ledger**; declared `teamId=A` against an existing ledger `B` ⇒
   **all** mutations refused (`team.identity-invalid`); `join`/`task` with a
   **missing, unknown, or inactive** declared identity ⇒ refused; a valid active
   member (non-lead) **can** `join`/`task`.
5. **Identity is attribution (documented):** actor from `CCT_TEAM_MEMBER_ID` (not
   the argument); a declared id absent from the ledger is refused. A session
   declaring another *existing* member's id in the *same* team is NOT prevented —
   asserted as a documented limitation, not a bug.
6. **Safe create + bootstrap:** duplicate `create` and `create` over a corrupt
   `team.json` refuse and leave the file **byte-for-byte unchanged**; after a
   successful `create`, the declared lead can immediately run a lead-only command
   (no restart). `--no-plan-approval` sets `planRequired:false`; default keeps
   `true`.
7. **Contract + message + CLI:** double/cross/over-cap/pre-approval claims and
   close-while-claimed refused; `message` appends via the locked path (validates
   team-binding/sender-active/recipient/team-open), surfaces `false` as failure,
   no `team.json` rewrite; `pi-code team status` renders under project-only opt-in
   with JSON `enabled`/trust.
8. **No new event source / no regression:** wiring uses only `registerCommand` /
   `session_start` / the CLI; the extracted lock keeps the worktree concurrency +
   stale-owner tests green.
