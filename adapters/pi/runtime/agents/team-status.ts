/**
 * Team status view + result synthesis + failure recovery (T8.2, FR-012/FR-020).
 *
 * A READ-MODEL / RECOVERY layer over the T8.1 team ledger — no live UI transport
 * and no peer execution (those are not Pi primitives). The status view is an
 * on-demand SNAPSHOT (like the doctor/features CLI commands), synthesis is pure
 * and fail-closed, and recovery only REOPENS claims from left/inactive members
 * (never auto-succeeds or auto-fails work). See
 * specs/pi-harness-adoption/design-t82-team-status.md.
 */

import type {
  ClaimStatus,
  TeamLedger,
  TeamOpResult,
  TeamStatus,
  TeamTask,
} from "./team.ts";

const CLAIM_STATUSES: ClaimStatus[] = ["open", "claimed", "done", "failed"];

// ── 1. status view (snapshot) ────────────────────────────────────────────────

export interface TeamStatusView {
  teamId: string;
  status: TeamStatus;
  planRequired: boolean;
  planApproved: boolean;
  shuttingDown: boolean;
  members: { total: number; lead: string | null; active: number; left: number };
  tasks: Record<ClaimStatus, number>;
  workerCount: number; // distinct non-null workerId links (FR-020 field)
}

/** Pure snapshot of the current ledger — an on-demand read, not a live panel. */
export function teamStatus(ledger: TeamLedger): TeamStatusView {
  const tasks = Object.fromEntries(CLAIM_STATUSES.map((s) => [s, 0])) as Record<
    ClaimStatus,
    number
  >;
  const workerIds = new Set<string>();
  for (const t of ledger.tasks) {
    tasks[t.claimStatus] += 1;
    if (t.workerId) workerIds.add(t.workerId);
  }
  const lead = ledger.members.find((m) => m.role === "lead") ?? null;
  return {
    teamId: ledger.teamId,
    status: ledger.status,
    planRequired: ledger.planApproval.required,
    planApproved: ledger.planApproval.approved,
    shuttingDown: ledger.status === "shutting-down",
    members: {
      total: ledger.members.length,
      lead: lead ? lead.memberId : null,
      active: ledger.members.filter((m) => m.status === "active").length,
      left: ledger.members.filter((m) => m.status === "left").length,
    },
    tasks,
    workerCount: workerIds.size,
  };
}

/** Render a status view as text (mirrors the doctor/features CLI) or JSON. */
export function renderTeamStatus(view: TeamStatusView, json: boolean): string {
  if (json) return JSON.stringify(view, null, 2);
  const approval = view.planRequired
    ? view.planApproved
      ? "approved"
      : "PENDING"
    : "not required";
  return [
    `=== team ${view.teamId} ===`,
    `status:     ${view.status}${view.shuttingDown ? " (shutting down)" : ""}`,
    `lead:       ${view.members.lead ?? "(none)"}`,
    `members:    ${view.members.total} (${view.members.active} active, ${view.members.left} left)`,
    `plan:       ${approval}`,
    `tasks:      open ${view.tasks.open} · claimed ${view.tasks.claimed} · done ${view.tasks.done} · failed ${view.tasks.failed}`,
    `workers:    ${view.workerCount}`,
  ].join("\n");
}

// ── 2. result synthesis (pure, fail-closed) ──────────────────────────────────

export type TeamVerdict = "complete" | "partial" | "failed" | "empty";

export interface TeamSynthesis {
  total: number;
  done: number;
  failed: number;
  open: number;
  claimed: number;
  verdict: TeamVerdict;
  failedTasks: string[];
}

/**
 * Aggregate task outcomes into a fail-closed team verdict:
 *   empty    — no tasks
 *   complete — every task is `done`
 *   failed   — all tasks terminal (done/failed) with NONE done
 *   partial  — anything else (in-flight open/claimed, or a mix)
 * Never `complete` while a task is open/claimed/failed.
 */
export function synthesizeTeam(ledger: TeamLedger): TeamSynthesis {
  const count = (s: ClaimStatus): number =>
    ledger.tasks.filter((t) => t.claimStatus === s).length;
  const total = ledger.tasks.length;
  const done = count("done");
  const failed = count("failed");
  const open = count("open");
  const claimed = count("claimed");

  let verdict: TeamVerdict;
  if (total === 0) verdict = "empty";
  else if (done === total) verdict = "complete";
  else if (open + claimed === 0 && done === 0) verdict = "failed";
  else verdict = "partial";

  return {
    total,
    done,
    failed,
    open,
    claimed,
    verdict,
    failedTasks: ledger.tasks
      .filter((t) => t.claimStatus === "failed")
      .map((t) => t.taskId),
  };
}

// ── 3. failure recovery (local state) ────────────────────────────────────────

/**
 * Reopen a claimed task for reclaim. `isInactive` decides which member ids no
 * longer count — a claim held by an inactive member is reset to open, AND an
 * `assignedTo` pointing at an inactive member is cleared, so a peer can actually
 * reclaim it (`claimTask` rejects a task assigned to someone else). Terminal
 * (done/failed) tasks are never touched.
 */
function recoverTask(
  t: TeamTask,
  isInactive: (id: string) => boolean,
): TeamTask {
  const assignedTo =
    t.assignedTo && isInactive(t.assignedTo) ? null : t.assignedTo;
  if (t.claimStatus === "claimed" && (!t.claimedBy || isInactive(t.claimedBy)))
    return {
      ...t,
      claimStatus: "open",
      claimedBy: null,
      claimedAt: null,
      assignedTo,
    };
  // An OPEN task assigned to a departed member is also stranded -> unassign.
  if (t.claimStatus === "open") return { ...t, assignedTo };
  return t;
}

/**
 * Mark a member as `left` and REOPEN the tasks it had claimed, so a peer can
 * reclaim them — clearing an `assignedTo` that points at the departing member so
 * the task is truly reclaimable. Never auto-succeeds or auto-fails work.
 */
export function markMemberLeft(
  ledger: TeamLedger,
  memberId: string,
  nowIso: string,
): TeamOpResult {
  if (!ledger.members.some((m) => m.memberId === memberId))
    return { ok: false, ledger, error: `no member '${memberId}'` };
  void nowIso; // reserved for a future left-at timestamp; kept in the signature
  const isInactive = (id: string): boolean => id === memberId;
  return {
    ok: true,
    ledger: {
      ...ledger,
      members: ledger.members.map((m) =>
        m.memberId === memberId ? { ...m, status: "left" } : m,
      ),
      tasks: ledger.tasks.map((t) => recoverTask(t, isInactive)),
    },
  };
}

/**
 * Sweep: reopen any task still `claimed` by a member who is now left/inactive or
 * gone (and clear an `assignedTo` pointing at such a member). The explicit
 * recovery pass (loadTeamLedger does the tamper-safe version passively). Always
 * succeeds; ledger unchanged if nothing was orphaned.
 */
export function reopenOrphanedClaims(ledger: TeamLedger): TeamOpResult {
  const active = new Set(
    ledger.members.filter((m) => m.status === "active").map((m) => m.memberId),
  );
  const isInactive = (id: string): boolean => !active.has(id);
  return {
    ok: true,
    ledger: {
      ...ledger,
      tasks: ledger.tasks.map((t) => recoverTask(t, isInactive)),
    },
  };
}
