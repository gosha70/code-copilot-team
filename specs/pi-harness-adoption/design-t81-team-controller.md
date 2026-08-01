# T8.1 Design Read — Team controller (FR-012)

Status: **design read — approval needed on the capability status, the two-file
state model, and the claiming/approval semantics before implementing.** T8.1 is
P0. Same boundary discipline as T7.x: **teams are CCT-first-party coordination
STATE, not Pi-native execution.**

## FR-012 (verbatim)

> Opt-in agent teams: lead/teammate identities, shared task ledger,
> assignment/claiming, peer messaging, plan approval, bounded concurrency,
> lifecycle visibility, controlled shutdown, result synthesis, partial-failure
> handling; **distinct from subagent delegation**.

T8.1 owns: identities, shared task ledger, assignment/claiming, messaging, plan
approval, controlled shutdown. **T8.2** owns status UI, result synthesis,
failure recovery, and the distinct-from-subagents tests.

## Teams ≠ subagents (kept explicit)

| | Subagents (T7.2) | Teams (FR-012, T8.1) |
|---|---|---|
| shape | parent → child (hierarchical) | **peers** (lead + teammates) |
| who runs whom | parent spawns the child | no spawning here — peers execute via the T7.2/T7.4 runners **separately** |
| state | ephemeral child session | a **shared, durable ledger** peers claim from |
| coordination | parent integrates results | **claiming / messaging / approval / shutdown** over shared state |

The existing `agent-team-protocol` skill uses "team" loosely for *in-session*
subagent delegation and even flags that multi-session coordination is a separate,
"tool-specific… not wire-compatible" thing. FR-012 is that separate thing. **Pi
exposes no native team primitive** (same class as "no subagent primitive"), so
the team controller is coordination *state*, not a live peer bus.

## Grounding (reuse patterns, do NOT merge concepts)

- `.cct/*.json` ledgers already established: `worktrees.json` (T7.3 worker
  ledger), `worker-analytics.jsonl` (T7.4 append log), `memory.json`,
  `pi-session.json`. Team state is a **new, separate** `.cct/team.json` +
  `.cct/team-messages.jsonl`.
- Config already reserves **`agents.teams_enabled`** (lint.ts), off by default.
- **Relation to T7.3/T7.4, without merging:** a team `Task` MAY carry an optional
  `workerId` linking to a T7.3 `WorkerRecord` (the worktree where a claimant
  executes). The team ledger *references* worker/worktree records; it does not
  own worktree lifecycle and does not duplicate their fields. Two ledgers, one
  link field.

## State model (needs approval)

Two files, mirroring the ledger + append-log split (worktrees.json +
worker-analytics.jsonl):

### `.cct/team.json` — the coordination ledger
```ts
export const TEAM_LEDGER_VERSION = 1;
export type TeamStatus = "forming" | "planning" | "active" | "shutting-down" | "closed";
export type MemberRole = "lead" | "teammate";
export type MemberStatus = "active" | "left";
export type ClaimStatus = "open" | "claimed" | "done" | "failed";

export interface TeamMember {
  memberId: string;   // unique, kebab
  role: MemberRole;    // exactly one lead
  status: MemberStatus;
  joinedAt: string;
}
export interface TeamTask {
  taskId: string;      // unique, kebab
  title: string;
  assignedTo: string | null;   // lead's intent (a memberId) or null (open pool)
  claimStatus: ClaimStatus;
  claimedBy: string | null;    // the single claimant
  claimedAt: string | null;
  workerId: string | null;     // optional link to a T7.3 WorkerRecord
}
export interface PlanApproval {
  required: boolean;
  approved: boolean;
  approvedBy: string | null;   // must be the lead
  approvedAt: string | null;
}
export interface Shutdown {
  requested: boolean;
  requestedBy: string | null;
  reason: string;
  at: string | null;
}
export interface TeamLedger {
  version: number;
  teamId: string;
  createdAt: string;
  status: TeamStatus;
  members: TeamMember[];
  tasks: TeamTask[];
  planApproval: PlanApproval;
  shutdown: Shutdown;
}
```

### `.cct/team-messages.jsonl` — peer messaging (append-only, redacted)
```ts
export interface TeamMessage {
  at: string;
  from: string;            // memberId
  to: string;              // memberId | "all"
  body: string;            // redacted via containsSecret before persist
}
```

## Operations (enforceable invariants)

- `createTeam(teamId, leadId, nowIso)` → `forming`, lead added (role lead).
- `addTeammate(ledger, memberId, nowIso)` → unique id; role teammate. (Exactly
  one lead; a second lead is refused.)
- `postTask(ledger, task)` → `open`, unique taskId.
- `assignTask(ledger, taskId, memberId)` → sets `assignedTo` (lead intent).
- **`claimTask(ledger, taskId, memberId)` → the coordination-safety gate.** A
  task moves `open → claimed` by **exactly one** active member, and only if the
  team is `active` (plan approved when required) and the task is unassigned **or**
  assigned to that member. A double-claim, a claim by a non-member, a claim of a
  task assigned to someone else, or a claim before plan approval is **refused
  (fail-closed)** — the analogue of T7.3's ownership-overlap refusal.
- `completeTask` / `failTask(ledger, taskId, memberId)` → `claimed → done|failed`
  by the claimant.
- `postMessage(projectRoot, from, to, body)` → append **redacted** JSONL.
- **`approvePlan(ledger, byLeadId)`** → only the lead; flips `planApproval.approved`
  and unblocks `active`. Claiming is blocked until approved (when required).
- **`requestShutdown(ledger, byId, reason)`** → `shutting-down`, recorded (who/why);
  `closeTeam` → `closed` once no task is still `claimed`.
- Bounded concurrency: at most `autonomy.max_concurrency` (existing config) tasks
  `claimed` at once — a claim past the cap is refused.

All string fields sanitized on load (single-line, bounded, control-stripped),
tamper-safe ledger (drops malformed records), same discipline as T7.3.

## Enforceable vs degraded (T8.1)

| element | status | how |
|---|---|---|
| unique lead/teammate identities (exactly one lead) | **enforced** | ledger validation |
| shared task ledger + assignment | **enforced** | `.cct/team.json` |
| **single-claimant claiming** (atomic on the ledger, double-claim refused) | **enforced** | `claimTask` fail-closed gate |
| plan-approval gate (no claiming/active until lead approves) | **enforced** | `approvePlan` + claim guard |
| controlled shutdown (recorded who/why; close only when no task claimed) | **enforced** | `requestShutdown`/`closeTeam` |
| bounded concurrency (≤ max_concurrency claimed) | **enforced** | claim guard |
| peer messaging | **degraded** | a shared **append-log peers poll**, NOT a live transport/bus — Pi has no cross-session message delivery |
| live peer **execution** | **degraded/declared** | the controller coordinates STATE; teammates run via the T7.2/T7.4 runners **separately** — the controller never spawns them |
| lifecycle visibility at a Stop event | **degraded** | no Pi Stop event — state changes at explicit actions, not a hook |
| result synthesis, failure recovery, status UI | **out → T8.2** | — |

**Honesty statement:** T8.1 enforces the team **coordination contract** on local
shared state — identities, a single-claimant task ledger, plan-approval and
shutdown gates, bounded concurrency — all fail-closed and tamper-safe. It does
**not** execute teammates or deliver messages over a live transport (Pi has no
team primitive); execution flows through the subagent/worker runners separately,
and messaging is a polled append-log. Reported **degraded**, never as live team
execution.

## Capability

New id **`agents.teams`**.
- **Pi: `degraded`** (my/your default) — coordination state enforced; live peer
  execution + real message transport are not Pi primitives; synthesis/recovery/UI
  are T8.2.
- **Claude Code: lean `disabled`** — Claude Code has native "Agent Team"
  configs, but the **CCT team-coordination ledger** (FR-012 shared ledger /
  claiming / approval / shutdown) is not implemented in the Claude adapter —
  parallel to how `agents.worktrees` is `disabled` there (native mechanism
  exists, CCT ledger does not). Open to `enabled` if you'd rather credit the
  native mechanism (as `agents.subagents` does).

## Scope (in / out)

**In:** `agents/team.ts` — the two-file state model + operations above (create /
addTeammate / postTask / assignTask / claimTask / complete / fail / approvePlan /
requestShutdown / closeTeam) + `postMessage` (redacted append) + tamper-safe
ledger I/O; one `agents.teams` capability entry across the four files; tests
(claim atomicity + double-claim refusal, approval gate, shutdown transitions,
concurrency cap, messaging redaction, tamper-safe load); design doc.

**Out (→ T8.2 / later):** status UI, result synthesis, failure recovery, the
distinct-from-subagents integration tests; live peer execution (uses T7.2/T7.4);
a real message transport; live `/cct:` command wiring.

## Open questions for approval

1. **Capability status** — Pi `degraded` (confirm). Claude Code `disabled`
   (lean, parallel to `agents.worktrees`) vs `enabled` (credit native Agent
   Teams like `agents.subagents`). My lean: **`disabled`**.
2. **Two-file state model** — `.cct/team.json` (ledger) + `.cct/team-messages.jsonl`
   (redacted append), kept **separate** from `worktrees.json`, linked only by an
   optional `Task.workerId`. Confirm.
3. **Claiming semantics** — a task is claimable only when the team is `active`
   (plan approved when required), it is `open`, and it is unassigned **or**
   assigned to the claimer; exactly one claimant; double-claim / cross-assignment
   claim / over-cap claim / pre-approval claim all **refused fail-closed**.
   Confirm this is the coordination contract you want.
4. **Plan-approval gate placement** — block `claimTask` (and the transition to
   `active`) until the lead approves, when `planApproval.required`. Confirm.
