# T8.2 Design Read — Team status UI, result synthesis, failure recovery (FR-012/FR-020)

Status: **design read — approval needed on the module, the synthesis verdict
taxonomy, the recovery model, and the capability decision before implementing.**
T8.2 is P1 and closes Phase 8 / Slice D. It is a **read model + pure aggregation
+ local-state recovery** over the T8.1 team ledger — no live UI transport and no
peer execution (those aren't Pi primitives), so it stays within the `degraded`
`agents.teams` boundary.

## FR-012 (T8.2 clauses) + FR-020

FR-012: "…lifecycle visibility, result synthesis, partial-failure handling…"
FR-020 (status UI): lists "**worker count**" among the fields — a team
contributes member/task counts to that view. T8.2 delivers the **team** status
surface + synthesis + recovery; the general status-line UI is a separate
concern (there is **no dedicated status-UI capability id** — status is rendered
via the `doctor`/`features` CLI commands, and T8.2 mirrors that render pattern).

## What T8.2 builds on (reuse, no rebuild)

- **T8.1 `team.ts`**: `TeamLedger` + `loadTeamLedger` (already reconciles/tamper-
  hardens on load), all statuses, `TeamOpResult`. The status view and synthesis
  are pure reads over a loaded ledger; recovery returns a `TeamOpResult`.
- **CLI render pattern** (`cli.ts` `features()`): text lines + `--json →
  jsonOut`. The team status renderer mirrors it.
- **T7.4 `summarizeBatch`**: the *shape* to echo for synthesis (fail-closed
  verdict + per-bucket counts) — a parallel, not a literal reuse (that one is
  over `WorkerOutcome`; team synthesis is over `TeamTask.claimStatus`).

## Three deliverables

### 1. Team status UI (read model + renderer)
```ts
export interface TeamStatusView {
  teamId: string;
  status: TeamStatus;
  planApproved: boolean;
  planRequired: boolean;
  shuttingDown: boolean;
  members: { total: number; lead: string | null; active: number; left: number };
  tasks: Record<ClaimStatus, number>; // open/claimed/done/failed counts
  workerCount: number;                 // distinct workerId links (FR-020 field)
}
export function teamStatus(ledger: TeamLedger): TeamStatusView; // pure
export function renderTeamStatus(view: TeamStatusView, json: boolean): string;
```
**Snapshot, not live.** Pi has no UI event stream, so this renders the current
ledger on demand (like `doctor`/`features`) — accurate read, not a live-updating
panel. That "snapshot vs live" gap is the degraded part.

### 2. Result synthesis (pure, fail-closed)
```ts
export type TeamVerdict = "complete" | "partial" | "failed" | "empty";
export interface TeamSynthesis {
  total: number;
  done: number; failed: number; open: number; claimed: number;
  verdict: TeamVerdict;
  failedTasks: string[];
}
export function synthesizeTeam(ledger: TeamLedger): TeamSynthesis; // pure
```
**Fail-closed verdict** (parallel to T7.4): `empty` when no tasks; `complete`
ONLY when every task is `done`; `failed` when all tasks are terminal
(`done`/`failed`), none done; otherwise `partial` (any in-flight, or a mix). A
team is never reported `complete` while a task is `open`/`claimed`/`failed`.

### 3. Failure recovery (local-state, returns TeamOpResult)
```ts
export function markMemberLeft(ledger, memberId, nowIso): TeamOpResult;   // + reopen their claims
export function reopenOrphanedClaims(ledger): TeamOpResult;               // claims held by left/inactive
```
When a teammate drops, its in-flight work must be reclaimable: `markMemberLeft`
sets the member `left` AND **reopens the tasks it had `claimed`** (→ `open`,
`claimedBy` null) so a peer can pick them up. `reopenOrphanedClaims` scans for
any `claimed` task whose claimant is `left`/inactive and reopens it (the explicit
recovery sweep; `loadTeamLedger` already does the tamper-safe version passively).
Recovery **reopens** (reclaimable), never silently marks work `done`.

## Distinct-from-subagents tests (an explicit T8.2 deliverable)

Tests that assert the conceptual separation, not just behavior:
- a team task is advanced by a **peer claim**, with **no spawn** (team ops are
  pure state — the module imports no child-session/spawn surface);
- the team ledger file (`.cct/team.json`) is a **different** path from the
  worktree ledger (`.cct/worktrees.json`) — separate state;
- `TeamTask.workerId` is an **optional link**, not an owned lifecycle (a team can
  resolve a task with `workerId: null`);
- a team is **peers** (one lead + teammates), not a parent→child hierarchy.

## Enforceable vs degraded (T8.2)

| element | status | how |
|---|---|---|
| team status snapshot (counts / roles / approval / shutdown / worker count) | **enforced read** | pure `teamStatus` over the loaded ledger |
| live-updating UI panel | **degraded** | no Pi UI event stream — on-demand snapshot render, like doctor/features |
| result synthesis + fail-closed verdict | **enforced** | pure `synthesizeTeam` |
| failure recovery (reopen a dropped member's claims) | **enforced** | local-state `markMemberLeft` / `reopenOrphanedClaims` |
| live peer execution / real message transport | **degraded** | not Pi primitives (T7.2/T7.4 runners; polled log) — unchanged from T8.1 |

## Capability

**No new id.** Fold into **`agents.teams`** (stays **`degraded`**): refresh the
reason to add "status snapshot + result synthesis + failure recovery present;
live-updating UI + live peer execution remain absent." Claude Code stays
`disabled`. No status/kind drift.

## Scope (in / out)

**In:** `agents/team-status.ts` — `teamStatus` + `renderTeamStatus`,
`synthesizeTeam`, `markMemberLeft` + `reopenOrphanedClaims`; the `agents.teams`
reason refresh; tests (status snapshot counts, synthesis verdicts incl.
fail-closed edges, recovery reopens orphaned claims, distinct-from-subagents);
design doc.

**Out (→ later):** wiring team status into the general FR-020 status-line / a
live `/cct:team` command (thin follow-up); live peer execution + message
transport (T7.2/T7.4 + not-a-Pi-primitive); FR-021 analytics.

## Open questions for approval

1. **Module** — one cohesive `agents/team-status.ts` (view + synthesis +
   recovery) vs putting the recovery mutators in `team.ts`. Lean: **one
   module** (`team.ts` is already ~650 lines; keep the read/recovery surface
   separate but importing its types).
2. **Synthesis verdict** — `complete | partial | failed | empty`, fail-closed
   (`complete` only when all tasks `done`; `failed` only when all terminal and
   none done; else `partial`). Confirm.
3. **Recovery model** — `markMemberLeft` reopens that member's `claimed` tasks
   (reclaimable by peers); `reopenOrphanedClaims` sweeps claims held by
   left/inactive members. **Reopen**, never auto-`done`/auto-`failed`. Confirm.
4. **Capability** — fold into `agents.teams` (reason refresh, stays `degraded`),
   no new id; Claude Code stays `disabled`. Confirm.
