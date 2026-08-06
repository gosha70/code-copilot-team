---
spec_mode: full
feature_id: pi-team-controller
risk_category: security
justification: |
  Slice A of #174: wires the T8.1 team controller + T8.2 status/synthesis/recovery
  libraries into the live Pi session. Safety-sensitive coordination STATE — it
  must resolve one canonical ledger across linked worktrees (no split state),
  derive the actor from a session-declared identity rather than command arguments
  (attribution, not authentication), validate the declared team id against the
  ledger, enforce lead-only administration, never overwrite an existing/corrupt
  team on create, and keep the single-claimant / approval / bounded-concurrency /
  close-while-claimed guarantees fail-closed and lock-serialized. Peer messages
  stay redacted. The libraries + their safety model already exist and are tested;
  this is wiring only, revised per the PR #184 review. The centralized plane
  (#174's later slices) is shaped separately in plane-shaping.md.
status: draft
date: 2026-08-06
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/185
  epic: https://github.com/gosha70/code-copilot-team/issues/174
  slice: "A — local team coordination wiring (foundation)"
  review: https://github.com/gosha70/code-copilot-team/pull/184
  design:
    - specs/pi-harness-adoption/design-t81-team-controller.md
    - specs/pi-harness-adoption/design-t82-team-status.md
  origin_claim: |
    #174 is an epic (a centralized, cross-developer management plane with cost
    rollups + budget alerting). The PR #184 reviews established that wiring the
    LOCAL t81/t82 libraries is a prerequisite SLICE, so this bundle targets the
    narrower sub-issue #185 and does NOT close the epic #174. The centralized
    plane (topology + identity/auth undecided) is shaped in plane-shaping.md
    before its own SDD. All PR #184 review findings (both rounds) are resolved
    here — incl. a fail-closed canonical root, per-mutation authz re-validation,
    an honest attribution-not-authentication identity model, the create
    bootstrap, and --no-plan-approval.
---

# Plan: Wire the T8.1/T8.2 local team ledger into Pi (Slice A of #174)

## Existing facts (verified against the code)

- `team.ts` ops are pure `(ledger, …) → TeamOpResult { ok, ledger, error? }`
  EXCEPT `postMessage(projectRoot, from, to, body, nowIso): boolean` (locked
  append, redacts fields). `completeTask`/`failTask` take `memberId`;
  `approvePlan(ledger, byLeadId)`; `assignTask` is NOT lead-restricted.
  `loadTeamLedger` returns `null` for missing AND corrupt. `createTeam` builds a
  fresh ledger with no storage awareness.
- `team-status.ts`: `teamStatus`(pure) + `renderTeamStatus`, `synthesizeTeam`
  (`complete|partial|failed|empty`), `markMemberLeft`, `reopenOrphanedClaims`.
- Config: `agents.teams_enabled` (off by default), `autonomy.max_concurrency`
  (claim cap). Capability `agents.teams` (`degraded`) — already covers T8.1+T8.2.
- `#172` shipped `primaryRepoRoot(cwd)` + the pid/token `withLedgerLock` in
  `agents/worktree-lifecycle.ts`; `index.ts` has `session_start` + the
  `registerCommand`/`emit` pattern + the `tool_call` gate; `cli.ts` has the
  `pi-code <cmd> [--json]` diagnostic router with a trust note.

## Design (wiring only; every #184 review finding resolved)

### D0 — Extract + constrain the lock (review "lock decision")
Move the pid/token `withLedgerLock` into `agents/ledger-lock.ts`, parameterized:
`withLedgerLock(repoRoot, fn, { lockName }: { lockName: LedgerLockName })` with
`export type LedgerLockName = "worktrees" | "team"` (constrained union → no
path-shaped names; error messages name the right ledger). `worktree-lifecycle.ts`
imports it (default `"worktrees"`); its concurrency + stale-owner tests run
unchanged against the extracted helper.

### D1 — Canonical team-state root, FAIL-CLOSED (review round-2 #2)
`resolveTeamRoot(cwd, deps) → { ok: true; root } | { ok: false; reason }` fronts
EVERY team op. `root = primaryRepoRoot(cwd)` (shared git common dir, #172). When
`primaryRepoRoot` returns `null` (git failure / not a repo), resolve is
`{ ok: false }` — **no `?? cwd` fallback** (that reintroduces the per-worktree
split FR-2 prevents). Mutations on `{ ok: false }` refuse + audit
`team.root-unresolved` + write nothing; reads report "no canonical repository
root"; the advisory stays silent. Tested by forcing `gitCommonDir` to fail from a
linked worktree and asserting nothing is created there.

### D2 — Declared identity, both ids MANDATORY (attribution, NOT authentication) (round-2 #1)
Contract `interface TeamIdentity { teamId: string; memberId: string }` — **both
`CCT_TEAM_ID` and `CCT_TEAM_MEMBER_ID` required**; a missing/empty either ⇒ refuse
+ audit `team.identity-invalid` for any actor-scoped / membership-requiring sub.
Slice A is honest that this is **attribution, not authentication**: a co-located
session can declare any *existing* member id **of the same team**, so
impersonation is **not** prevented (documented limitation; authenticated authz —
a controller-issued capability or the validated T7.3 worker binding — is an
epic/topology decision). `attachTeamIdentity(env)` stores **only** the two
immutable declared ids — **no cached role/status**. Actors come from it, never a
command argument.

### D3 — Authorization re-validated per mutation, inside the lock (round-2 #1/#3)
Every mutation, after `load` under the lock, first requires
`identity.teamId === ledger.teamId` (**team binding** — else refuse + audit
`team.identity-invalid`; blocks a stale session acting on a replacement team that
reuses a member id), then resolves
`actor = ledger.members.find(m => m.memberId === identity.memberId)` and requires
`actor?.status === "active"`. Authorization tiers (explicit, no ambiguity):
- **`create`** — bootstrap: requires the declared identity + `<teamId arg> ===
  identity.teamId`; does NOT require pre-existing membership (establishes the lead).
- **`join` / `task`** — require the declared identity + the actor be an **active
  member** under the lock; NOT lead. (`join <memberId>` = an active member adds
  `<memberId>` as a new teammate; the *actor* is the declared id, the *argument*
  is the added teammate.)
- **`assign` / `approve` / `activate` / `recover` / `close`** — require the actor
  be the **active lead** as of the loaded ledger (never a `session_start` cache,
  so a lead that has since `left` loses authority immediately).
**Sole-lead guard:** `leave` by the only active lead of a non-closed team is
refused (no lead-transfer op; documented).

### D4 — Safe create + bootstrap; `--no-plan-approval` (review #4 + round-2 #5)
`create <teamId> [--no-plan-approval]` — approval **required by default** (matches
`createTeam`'s `planRequired = true`); the flag opts out. Requires the declared
identity and **`<teamId> === identity.teamId`** (else refuse). Under the lock:
`fs.existsSync(team.json)` → present + `loadTeamLedger` valid ⇒ refuse "already
exists"; present + `null` ⇒ refuse "ledger invalid", **no write**; absent ⇒
`createTeam(teamId, identity.memberId, now, { planRequired: !noPlanApproval })`
(the lead is the **declared** member) → save. **Bootstrap:** the declared member
is now a valid active lead in the saved ledger; since session state holds only
the declared id, later commands re-validate against that ledger — **no restart**.
Non-create mutations: `loadTeamLedger`; `null` ⇒ refuse (no save); authz (D3); op;
save on `ok`. Reads/advisory: missing (`!existsSync`) ⇒ "no team"; `existsSync`
but `null` ⇒ fail-closed warning; never pass `null` to `teamStatus`.

### D5 — Command surface with correct signatures (review #5)
`/cct:team <sub>`, under the lock, audited. Actor from session identity where
noted:

All actor-scoped rows take the actor from `state.teamIdentity.memberId` (never an
argument) and re-validate `actor.status === "active"` under the lock (D3):

| sub | op | actor / authz |
|---|---|---|
| `create <teamId> [--no-plan-approval]` | createTeam (D4) | bootstrap; `<teamId> === identity.teamId`; lead = declared member; approval default-on |
| `join <memberId>` | addTeammate | **any active member** adds `<memberId>` as a new teammate (actor = declared id) |
| `task <taskId> <title…> [--assign <m>] [--worker <w>]` | postTask | **any active member** |
| `assign <taskId> <memberId>` | assignTask | **lead-only** (active lead, per D3) |
| `approve` | approvePlan(ledger, actor) | **lead-only** |
| `activate` | activateTeam | **lead-only** |
| `claim <taskId>` | claimTask(ledger, taskId, **actor**, now, {maxConcurrency}) | active actor |
| `complete <taskId>` / `fail <taskId>` | completeTask/failTask(ledger, taskId, **actor**) | active actor |
| `message <to\|all> <body…>` | postMessage(root, **actor**, to, body, now) | active actor; **load ledger under lock** first → validate team-open + sender-active + recipient (`all` or a member); boolean-checked; no `team.json` rewrite |
| `leave` | markMemberLeft(ledger, **actor**) | active actor; **sole-active-lead refused** on a non-closed team |
| `recover` | reopenOrphanedClaims | **lead-only** |
| `shutdown [--reason …]` | requestShutdown(ledger, **actor**, reason, now) | active actor |
| `close` | closeTeam | **lead-only**; refused while a task is `claimed` |
| `status [--json]` | teamStatus + renderTeamStatus | read-only (FR-8) |
| `synthesize [--json]` | synthesizeTeam | read-only |

`message` uses the dedicated locked append (D4 "other" doesn't apply — it does not
load/save `team.json`); a `false` return surfaces as failure.

### D6 — CLI gate semantics (review #6)
`pi-code team status|synthesize [--json]` — read-only, at the resolved root
(unresolved ⇒ "no canonical repository root"). It renders
whenever a **valid ledger exists**, independent of the (out-of-session,
project-untrusted) `agents.teams_enabled`. `--json` includes
`enabled: true|false|unknown` (unknown when only project config could set it and
trust is unavailable) + the existing CLI trust note. In-session mutations stay
gated on the resolved (trust-aware) flag.

### D7 — Audit + honesty (FR-7/FR-10)
Each action audits `team.<create|join|task|assign|claim|complete|fail|approve|
activate|message|shutdown|close|recover|leave|status|identity-invalid>`, subject
`<teamId>:<actor|task>`, origin `team`. Docs + `pi-code doctor` state the
`degraded` boundary and that this is the LOCAL slice of the #174 epic.

## Deliverables

1. `agents/ledger-lock.ts` — extracted, `LedgerLockName`-parameterized lock;
   `worktree-lifecycle.ts` updated to import it (behavior unchanged).
2. `agents/team-commands.ts` — `resolveTeamRoot` (fail-closed), declared-identity
   attach (ids only), per-mutation authz re-validation, safe create/bootstrap,
   gate + lock + audit wrappers, the `/cct:team` + CLI handlers.
3. `index.ts` — `registerCommand("cct:team", …)`; `attachTeamIdentity` (stores
   only `{teamId, memberId}`, both mandatory) + session-start advisory.
4. `cli.ts` — `pi-code team status|synthesize [--json]` (FR-8 semantics).
5. `bin/pi-code` — route `team` to the runtime CLI, recursion-guard entry, help,
   the `CCT_TEAM_*` contract in a driver note.
6. Docs — `adapters/pi/docs/team-coordination.md` (`/cct:team` + CLI, the
   `CCT_TEAM_*` identity contract + per-subcommand authz table, the
   `agents.teams_enabled` gate, the two-file ledger at the primary root, the
   `degraded` boundary, and a pointer to `plane-shaping.md` for the epic); README.
7. Tests (below).

## Sequencing

1. Extract/constrain the lock → `ledger-lock.ts` (+ worktree import; re-run the
   worktree suite unchanged).
2. `team-commands.ts`: `teamRoot`, identity/authz, safe create/corrupt, gate +
   lock + audit wrappers (+ unit tests: lifecycle, each refusal, identity,
   create-over-existing/corrupt byte-for-byte).
3. `index.ts` wiring: `registerCommand` + `attachTeamIdentity` + advisory
   (python-edit to dodge the prettier hook).
4. `cli.ts` `pi-code team …` (FR-8) + launcher route/help/test.
5. Docs + honesty note.

## Test strategy (mapped to the review)

- **Canonical ledger (review #2):** two real linked worktrees — claim/read/
  concurrent-claim resolve to the primary ledger (the prior single-dir test could
  not detect a split).
- **Fail-closed root (round-2 #2):** force `gitCommonDir` to fail from a linked
  worktree ⇒ mutation refuses + audits `team.root-unresolved`, nothing created in
  the worktree; read reports "no canonical repository root".
- **Team binding + join/task authz (round-2 #1/#2):** declared `CCT_TEAM_ID=A` +
  `create B` ⇒ refused, no ledger; declared `teamId=A` against an existing ledger
  `B` ⇒ all mutations refused (`team.identity-invalid`); `join`/`task` with a
  missing / unknown / inactive declared identity ⇒ refused; a valid active member
  (non-lead) can `join`/`task`.
- **Live authz (round-2 #3):** an **active teammate** that becomes `left` is
  refused on its next actor-scoped command (re-validated, not cached); the same
  **lead** stale-cache property uses an **externally-modified/reloaded ledger
  fixture** (the normal lifecycle can't make the sole lead `left`); a declared id
  absent from the ledger and a non-lead admin command are refused; the sole active
  lead cannot `leave` a non-closed team. A session declaring another *existing*
  same-team member's id is NOT prevented (documented attribution-only limitation).
- **Safe create + bootstrap (review #4 + round-2 #5):** duplicate `create` and
  `create` over a corrupt `team.json` refuse + leave the file byte-for-byte
  unchanged; after a successful create the declared lead runs a lead-only command
  with no restart; `--no-plan-approval` ⇒ `planRequired:false`, default `true`.
- **Signatures/message (review #5):** `complete/fail` use the actor; `message`
  appends via the locked path, surfaces `false` as failure, does not rewrite
  `team.json`.
- **CLI gate (review #6):** `agents.teams_enabled=true` only in trusted project
  config ⇒ `pi-code team status` still renders; JSON reports `enabled`/trust.
- **Contract + concurrency:** double/cross/over-cap/pre-approval claims and
  close-while-claimed refused; two real processes claim one task → exactly one
  wins (reuse the #172 spawn-fixture pattern).
- **No-invented-event + no worktree regression:** wiring only `session_start` +
  command; the extracted lock keeps the worktree concurrency/stale tests green.

Home: `tests/pi-runtime/team-commands.test.mjs` (+ a spawn fixture), launcher
assertion in `tests/test-pi-launcher.sh`.

## Resolved decisions

1. **Scope** → Slice A (local wiring), targets sub-issue **#185**; epic **#174**
   stays open; centralized plane shaped in `plane-shaping.md`.
2. **Canonical root** → `resolveTeamRoot` via `primaryRepoRoot(cwd)`,
   **fail-closed** (no `?? cwd`); unresolved ⇒ refuse + `team.root-unresolved`.
3. **Identity** → **declared** `{teamId, memberId}`, **both mandatory** (attribution,
   **NOT** authentication — documented limitation); actor never from args; session
   state = ids only; declared `teamId` validated against `ledger.teamId` (team
   binding).
4. **Authz** → re-validated **inside the lock per mutation**: team-binding + active
   actor; lead-only for assign/approve/activate/recover/close; `join`/`task` = any
   active member; `create` = bootstrap; never cached; sole active lead can't leave
   an open team.
5. **Create safety + bootstrap** → refuse over existing/corrupt (never overwrite);
   lead = declared member; no restart. `create [--no-plan-approval]` (default on).
6. **Lock** → extract + `LedgerLockName = "worktrees" | "team"` union.
7. **CLI gate** → mutations gated; read-only renders a valid ledger with
   `enabled: true|false|unknown`.
8. **Authenticated identity** → out of Slice A; an epic decision (folds into the
   topology/identity shaping — a controller-issued capability or the validated
   T7.3 worker binding).

## Deferred to the epic (plane-shaping.md, decisions still open)

Central topology (shared-Postgres vs export-and-merge vs federated), cross-
developer identity/auth, developer_id population, developer/team/repo cost
rollups, budget + runaway-loop alerting, and the team dashboard. **User chose to
shape these separately before their SDD**; identity/auth folds into the topology
shaping.
