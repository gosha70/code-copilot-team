---
spec_mode: full
feature_id: pi-team-controller
risk_category: security
justification: |
  Slice A of #174: wires the T8.1 team controller + T8.2 status/synthesis/recovery
  libraries into the live Pi session. Safety-sensitive coordination STATE — it
  must resolve one canonical ledger across linked worktrees (no split state),
  derive the actor from a TRUSTED session identity (not impersonatable command
  args), enforce lead-only administration, never overwrite an existing/corrupt
  team on create, and keep the single-claimant / approval / bounded-concurrency /
  close-while-claimed guarantees fail-closed and lock-serialized. Peer messages
  stay redacted. The libraries + their safety model already exist and are tested;
  this is wiring only, revised per the PR #184 review. The centralized plane
  (#174's later slices) is shaped separately in plane-shaping.md.
status: draft
date: 2026-08-06
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/174
  epic: true
  slice: "A — local team coordination wiring (foundation)"
  review: https://github.com/gosha70/code-copilot-team/pull/184
  design:
    - specs/pi-harness-adoption/design-t81-team-controller.md
    - specs/pi-harness-adoption/design-t82-team-status.md
  origin_claim: |
    #174 is an epic (a centralized, cross-developer management plane with cost
    rollups + budget alerting). The PR #184 review established that wiring the
    LOCAL t81/t82 libraries is a prerequisite SLICE, not the whole feature, so
    this bundle is scoped to Slice A and does NOT close #174. Slice A is pointed
    at a narrower sub-issue; #174 stays open as the epic. The centralized plane
    (topology + identity/auth undecided) is shaped in plane-shaping.md before its
    own SDD. Every PR #184 review finding is resolved in this revision.
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

### D1 — Canonical team-state root (review #2)
A single `teamRoot = primaryRepoRoot(cwd) ?? cwd` fronts EVERY team op — load,
save, `postMessage`, `team.lock`, status, synthesis, session advisory, CLI reads.
From a linked worker worktree, `primaryRepoRoot` resolves the shared git common
dir's parent (the primary checkout that owns `.cct/team.json`), so all peers
share one ledger + one lock. Tested with two real linked worktrees.

### D2 — Trusted session identity (review #3)
A session identity contract: `CCT_TEAM_ID` + `CCT_TEAM_MEMBER_ID` (untrusted env,
validated). `attachTeamIdentity(cwd, env)` at `session_start`: if set, load the
ledger at `teamRoot`, assert the member exists and (if `CCT_TEAM_ID` given)
matches the team; store `state.teamMember` on match, else fail closed (warn +
audit `team.identity-invalid`). Actor-scoped subcommands (`claim`, `complete`,
`fail`, `approve`, `message` from, `leave`, `shutdown`) derive the actor from
`state.teamMember` — **never** from a command argument; absent/mismatch ⇒ refuse.

### D3 — Authorization for admin subcommands (review #3)
The wiring adds the lead-only check the library lacks: `assign`, `activate`,
`close`, `recover`, and `approve` require `state.teamMember.role === "lead"`.
`create` / `join` / `task` are open local administration (documented). Each
subcommand's authz level is stated in the docs; attribution-only vs authenticated
is called out honestly.

### D4 — Safe create / corrupt / missing paths (review #4)
Distinct paths, all under the lock:
- **create:** `fs.existsSync(team.json)` → if present: `loadTeamLedger` valid ⇒
  refuse "already exists"; `null` ⇒ refuse "ledger invalid", **no write**. Absent
  ⇒ `createTeam` → save.
- **other mutations:** `loadTeamLedger`; `null` ⇒ refuse (no save); op; save on
  `ok`.
- **reads / advisory:** missing (`!existsSync`) ⇒ "no team"; `existsSync` but
  `null` ⇒ fail-closed warning; valid ⇒ render. Never pass `null` to `teamStatus`.

### D5 — Command surface with correct signatures (review #5)
`/cct:team <sub>`, under the lock, audited. Actor from session identity where
noted:

| sub | op | actor / authz |
|---|---|---|
| `create <teamId> [--require-approval]` | createTeam | lead = the session member; open admin |
| `join <memberId>` | addTeammate | open admin (join records identity) |
| `task <taskId> <title…> [--assign <m>] [--worker <w>]` | postTask | open admin |
| `assign <taskId> <memberId>` | assignTask | **lead-only** (wiring) |
| `approve` | approvePlan(ledger, actor) | **lead-only** |
| `activate` | activateTeam | **lead-only** |
| `claim <taskId>` | claimTask(ledger, taskId, **actor**, now, {maxConcurrency}) | actor from identity |
| `complete <taskId>` / `fail <taskId>` | completeTask/failTask(ledger, taskId, **actor**) | actor from identity |
| `message <to\|all> <body…>` | postMessage(teamRoot, **actor**, to, body, now) | actor from identity; boolean-checked |
| `leave` | markMemberLeft(ledger, **actor**) | actor from identity |
| `recover` | reopenOrphanedClaims | **lead-only** |
| `shutdown [--reason …]` | requestShutdown(ledger, **actor**, reason, now) | actor from identity |
| `close` | closeTeam | **lead-only**; refused while a task is `claimed` |
| `status [--json]` | teamStatus + renderTeamStatus | read-only (FR-8) |
| `synthesize [--json]` | synthesizeTeam | read-only |

`message` uses the dedicated locked append (D4 "other" doesn't apply — it does not
load/save `team.json`); a `false` return surfaces as failure.

### D6 — CLI gate semantics (review #6)
`pi-code team status|synthesize [--json]` — read-only, at `teamRoot`. It renders
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
2. `agents/team-commands.ts` — `teamRoot` resolution, identity/authz, safe
   create/corrupt paths, gate + lock + audit wrappers, the `/cct:team` + CLI
   handlers, session-identity attach.
3. `index.ts` — `registerCommand("cct:team", …)`; `attachTeamIdentity` +
   session-start advisory in the existing `session_start` handler.
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
- **Identity (review #3):** actor derived from `CCT_TEAM_MEMBER_ID`; a mismatched
  identity and a non-lead admin command are refused.
- **Safe create (review #4):** duplicate `create` and `create` over a corrupt
  `team.json` both refuse and leave the file byte-for-byte unchanged; a non-create
  command with no/invalid ledger refuses; advisory never passes `null` in.
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

1. **Scope** → Slice A (local wiring); #174 stays the epic; a narrower sub-issue
   targets this bundle; centralized plane shaped in `plane-shaping.md`.
2. **Canonical root** → `primaryRepoRoot(cwd)` for all team state.
3. **Identity** → trusted `CCT_TEAM_*` session contract; actor never from args.
4. **Authz** → lead-only for assign/activate/close/recover/approve; create/join/
   task open admin (documented).
5. **Create safety** → refuse over existing/corrupt, never overwrite.
6. **Lock** → extract + `LedgerLockName = "worktrees" | "team"` union.
7. **CLI gate** → mutations gated; read-only renders a valid ledger with
   `enabled: true|false|unknown`.

## Deferred to the epic (plane-shaping.md, decisions still open)

Central topology (shared-Postgres vs export-and-merge vs federated), cross-
developer identity/auth, developer_id population, developer/team/repo cost
rollups, budget + runaway-loop alerting, and the team dashboard. **User chose to
shape these separately before their SDD**; identity/auth folds into the topology
shaping.
