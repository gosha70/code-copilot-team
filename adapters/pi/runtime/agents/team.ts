/**
 * Team controller (T8.1, FR-012) — CCT-first-party coordination STATE, not
 * Pi-native execution. Pi has no team primitive, so a "team" here is a shared,
 * durable ledger that peers claim from; teammates EXECUTE via the T7.2/T7.4
 * runners SEPARATELY — this module never spawns them. Distinct from subagent
 * delegation (parent→child): teams are peers (lead + teammates) coordinating
 * over shared state.
 *
 * Two files, mirroring the T7.3/T7.4 ledger + append-log split, kept SEPARATE
 * from worktrees.json (a Task links to a worker only by an optional workerId —
 * no merged lifecycle):
 *   - `.cct/team.json`           the coordination ledger (identities/tasks/…)
 *   - `.cct/team-messages.jsonl` peer messaging, append-only + redacted
 *
 * Coordination is fail-closed: single-claimant claiming, a plan-approval gate on
 * BOTH activation and claims, bounded concurrency, controlled shutdown. Reported
 * `degraded` — live peer execution + real message transport are not Pi
 * primitives. See specs/pi-harness-adoption/design-t81-team-controller.md.
 */

import * as fs from "node:fs";
import * as path from "node:path";

import { containsSecret } from "../workflow/memory.ts";
import { DEFAULT_MAX_CONCURRENCY } from "./caps.ts";

export const TEAM_LEDGER_VERSION = 1;
export const TEAM_LEDGER_REL = path.join(".cct", "team.json");
export const TEAM_MESSAGES_REL = path.join(".cct", "team-messages.jsonl");

export type TeamStatus =
  "forming" | "planning" | "active" | "shutting-down" | "closed";
export type MemberRole = "lead" | "teammate";
export type MemberStatus = "active" | "left";
export type ClaimStatus = "open" | "claimed" | "done" | "failed";

export interface TeamMember {
  memberId: string;
  role: MemberRole;
  status: MemberStatus;
  joinedAt: string;
}
export interface TeamTask {
  taskId: string;
  title: string;
  assignedTo: string | null;
  claimStatus: ClaimStatus;
  claimedBy: string | null;
  claimedAt: string | null;
  workerId: string | null; // optional LINK to a T7.3 WorkerRecord (not merged)
}
export interface PlanApproval {
  required: boolean;
  approved: boolean;
  approvedBy: string | null;
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

export interface TeamOpResult {
  ok: boolean;
  ledger: TeamLedger;
  error?: string;
}

const ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const MAX_ID = 64;
const MAX_TITLE = 200;
const MAX_REASON = 200;
const MAX_BODY = 2000;

const TEAM_STATUSES: TeamStatus[] = [
  "forming",
  "planning",
  "active",
  "shutting-down",
  "closed",
];
const MEMBER_STATUSES: MemberStatus[] = ["active", "left"];
const CLAIM_STATUSES: ClaimStatus[] = ["open", "claimed", "done", "failed"];

function isId(s: unknown): s is string {
  return typeof s === "string" && s.length <= MAX_ID && ID_RE.test(s);
}
function sanitizeText(value: unknown, max: number): string {
  if (typeof value !== "string") return "";
  return (
    value
      .replace(/[\r\n\t]+/g, " ")
      // eslint-disable-next-line no-control-regex
      .replace(/[\x00-\x1f\x7f]/g, "")
      .slice(0, max)
      .trim()
  );
}

// ── constructors + membership ────────────────────────────────────────────────

export function emptyTeam(teamId: string, nowIso = ""): TeamLedger {
  return {
    version: TEAM_LEDGER_VERSION,
    teamId,
    createdAt: nowIso,
    status: "forming",
    members: [],
    tasks: [],
    planApproval: {
      required: true,
      approved: false,
      approvedBy: null,
      approvedAt: null,
    },
    shutdown: { requested: false, requestedBy: null, reason: "", at: null },
  };
}

/** Create a team with its lead. `planRequired` defaults to true (approval-gated). */
export function createTeam(
  teamId: string,
  leadId: string,
  nowIso: string,
  opts: { planRequired?: boolean } = {},
): TeamOpResult {
  if (!isId(teamId))
    return {
      ok: false,
      ledger: emptyTeam(teamId),
      error: `teamId '${teamId}' is not kebab-case`,
    };
  if (!isId(leadId))
    return {
      ok: false,
      ledger: emptyTeam(teamId),
      error: `leadId '${leadId}' is not kebab-case`,
    };
  const ledger = emptyTeam(teamId, nowIso);
  ledger.planApproval.required = opts.planRequired ?? true;
  ledger.members.push({
    memberId: leadId,
    role: "lead",
    status: "active",
    joinedAt: nowIso,
  });
  return { ok: true, ledger };
}

function isOpen(l: TeamLedger): boolean {
  return l.status !== "closed" && l.status !== "shutting-down";
}

export function addTeammate(
  ledger: TeamLedger,
  memberId: string,
  nowIso: string,
): TeamOpResult {
  if (!isId(memberId))
    return {
      ok: false,
      ledger,
      error: `memberId '${memberId}' is not kebab-case`,
    };
  if (!isOpen(ledger))
    return { ok: false, ledger, error: `team is ${ledger.status}` };
  if (ledger.members.some((m) => m.memberId === memberId))
    return { ok: false, ledger, error: `member '${memberId}' already exists` };
  return {
    ok: true,
    ledger: {
      ...ledger,
      members: [
        ...ledger.members,
        { memberId, role: "teammate", status: "active", joinedAt: nowIso },
      ],
    },
  };
}

// ── tasks: post / assign / claim / complete / fail ───────────────────────────

export interface PostTaskInput {
  taskId: string;
  title: string;
  assignedTo?: string | null;
  workerId?: string | null;
}

export function postTask(
  ledger: TeamLedger,
  input: PostTaskInput,
): TeamOpResult {
  if (!isId(input.taskId))
    return {
      ok: false,
      ledger,
      error: `taskId '${input.taskId}' is not kebab-case`,
    };
  if (!isOpen(ledger))
    return { ok: false, ledger, error: `team is ${ledger.status}` };
  if (ledger.tasks.some((t) => t.taskId === input.taskId))
    return {
      ok: false,
      ledger,
      error: `task '${input.taskId}' already exists`,
    };
  const assignedTo = input.assignedTo ?? null;
  if (
    assignedTo !== null &&
    !ledger.members.some(
      (m) => m.memberId === assignedTo && m.status === "active",
    )
  )
    return {
      ok: false,
      ledger,
      error: `cannot assign to unknown/inactive member '${assignedTo}'`,
    };
  const task: TeamTask = {
    taskId: input.taskId,
    title: sanitizeText(input.title, MAX_TITLE),
    assignedTo,
    claimStatus: "open",
    claimedBy: null,
    claimedAt: null,
    workerId: input.workerId
      ? sanitizeText(input.workerId, MAX_ID) || null
      : null,
  };
  return { ok: true, ledger: { ...ledger, tasks: [...ledger.tasks, task] } };
}

function mapTask(
  ledger: TeamLedger,
  taskId: string,
  fn: (t: TeamTask) => TeamTask,
): TeamLedger {
  return {
    ...ledger,
    tasks: ledger.tasks.map((t) => (t.taskId === taskId ? fn(t) : t)),
  };
}

export function assignTask(
  ledger: TeamLedger,
  taskId: string,
  memberId: string,
): TeamOpResult {
  const task = ledger.tasks.find((t) => t.taskId === taskId);
  if (!task) return { ok: false, ledger, error: `no such task '${taskId}'` };
  if (
    !ledger.members.some(
      (m) => m.memberId === memberId && m.status === "active",
    )
  )
    return { ok: false, ledger, error: `no active member '${memberId}'` };
  if (task.claimStatus !== "open")
    return {
      ok: false,
      ledger,
      error: `task '${taskId}' is ${task.claimStatus}, not open`,
    };
  return {
    ok: true,
    ledger: mapTask(ledger, taskId, (t) => ({ ...t, assignedTo: memberId })),
  };
}

function planSatisfied(l: TeamLedger): boolean {
  return !l.planApproval.required || l.planApproval.approved;
}

/**
 * Claim a task — the fail-closed coordination gate. All required:
 *   team is `active`; plan approval satisfied (if required); claimer is an
 *   active member; task is `open`; task is unassigned OR assigned to the
 *   claimer; the concurrency cap is not exceeded. Exactly one claimant results.
 */
export function claimTask(
  ledger: TeamLedger,
  taskId: string,
  memberId: string,
  nowIso: string,
  opts: { maxConcurrency?: number } = {},
): TeamOpResult {
  const max = opts.maxConcurrency ?? DEFAULT_MAX_CONCURRENCY;
  if (ledger.status !== "active")
    return { ok: false, ledger, error: `team is ${ledger.status}, not active` };
  if (!planSatisfied(ledger))
    return {
      ok: false,
      ledger,
      error: "plan approval required before claiming",
    };
  if (
    !ledger.members.some(
      (m) => m.memberId === memberId && m.status === "active",
    )
  )
    return { ok: false, ledger, error: `no active member '${memberId}'` };
  const task = ledger.tasks.find((t) => t.taskId === taskId);
  if (!task) return { ok: false, ledger, error: `no such task '${taskId}'` };
  if (task.claimStatus !== "open")
    return {
      ok: false,
      ledger,
      error: `task '${taskId}' already ${task.claimStatus}`,
    };
  if (task.assignedTo !== null && task.assignedTo !== memberId)
    return {
      ok: false,
      ledger,
      error: `task '${taskId}' is assigned to '${task.assignedTo}'`,
    };
  const claimed = ledger.tasks.filter(
    (t) => t.claimStatus === "claimed",
  ).length;
  if (claimed >= max)
    return {
      ok: false,
      ledger,
      error: `concurrency cap ${max} reached (${claimed} claimed)`,
    };
  return {
    ok: true,
    ledger: mapTask(ledger, taskId, (t) => ({
      ...t,
      claimStatus: "claimed",
      claimedBy: memberId,
      claimedAt: nowIso,
    })),
  };
}

function resolveClaimed(
  ledger: TeamLedger,
  taskId: string,
  memberId: string,
  to: "done" | "failed",
): TeamOpResult {
  const task = ledger.tasks.find((t) => t.taskId === taskId);
  if (!task) return { ok: false, ledger, error: `no such task '${taskId}'` };
  if (task.claimStatus !== "claimed")
    return {
      ok: false,
      ledger,
      error: `task '${taskId}' is ${task.claimStatus}, not claimed`,
    };
  if (task.claimedBy !== memberId)
    return {
      ok: false,
      ledger,
      error: `task '${taskId}' is claimed by '${task.claimedBy}', not '${memberId}'`,
    };
  return {
    ok: true,
    ledger: mapTask(ledger, taskId, (t) => ({ ...t, claimStatus: to })),
  };
}

export function completeTask(
  ledger: TeamLedger,
  taskId: string,
  memberId: string,
): TeamOpResult {
  return resolveClaimed(ledger, taskId, memberId, "done");
}
export function failTask(
  ledger: TeamLedger,
  taskId: string,
  memberId: string,
): TeamOpResult {
  return resolveClaimed(ledger, taskId, memberId, "failed");
}

// ── approval / activation / shutdown ─────────────────────────────────────────

/** Only the lead approves the plan. */
export function approvePlan(
  ledger: TeamLedger,
  byLeadId: string,
  nowIso: string,
): TeamOpResult {
  const lead = ledger.members.find((m) => m.role === "lead");
  if (!lead || lead.memberId !== byLeadId)
    return { ok: false, ledger, error: `only the lead may approve the plan` };
  return {
    ok: true,
    ledger: {
      ...ledger,
      planApproval: {
        ...ledger.planApproval,
        approved: true,
        approvedBy: byLeadId,
        approvedAt: nowIso,
      },
    },
  };
}

/** Move the team to `active` — blocked until the plan is approved (if required). */
export function activateTeam(ledger: TeamLedger): TeamOpResult {
  if (ledger.status === "active") return { ok: true, ledger };
  if (ledger.status !== "forming" && ledger.status !== "planning")
    return {
      ok: false,
      ledger,
      error: `cannot activate a ${ledger.status} team`,
    };
  if (!planSatisfied(ledger))
    return {
      ok: false,
      ledger,
      error: "plan approval required before activation",
    };
  return { ok: true, ledger: { ...ledger, status: "active" } };
}

export function requestShutdown(
  ledger: TeamLedger,
  byId: string,
  reason: string,
  nowIso: string,
): TeamOpResult {
  if (ledger.status === "closed")
    return { ok: false, ledger, error: "team is closed" };
  if (!ledger.members.some((m) => m.memberId === byId))
    return { ok: false, ledger, error: `no member '${byId}'` };
  return {
    ok: true,
    ledger: {
      ...ledger,
      status: "shutting-down",
      shutdown: {
        requested: true,
        requestedBy: byId,
        reason: sanitizeText(reason, MAX_REASON),
        at: nowIso,
      },
    },
  };
}

/** Close the team — only once no task is still `claimed` (in flight). */
export function closeTeam(ledger: TeamLedger): TeamOpResult {
  const inFlight = ledger.tasks
    .filter((t) => t.claimStatus === "claimed")
    .map((t) => t.taskId);
  if (inFlight.length > 0)
    return {
      ok: false,
      ledger,
      error: `cannot close: tasks still claimed (${inFlight.join(", ")})`,
    };
  return { ok: true, ledger: { ...ledger, status: "closed" } };
}

// ── messaging (append-only, redacted) ────────────────────────────────────────

export interface TeamMessage {
  at: string;
  from: string;
  to: string; // memberId | "all"
  body: string;
}

/** Append a redacted peer message. Best-effort; never throws into the caller. */
export function postMessage(
  projectRoot: string,
  from: string,
  to: string,
  body: string,
  nowIso: string,
): boolean {
  try {
    // Redact EVERY persisted string field — from/to are caller-provided and
    // could carry a secret value, not just the body.
    const redact = (v: string, max: number): string =>
      containsSecret(v) ? "[REDACTED]" : sanitizeText(v, max);
    const msg: TeamMessage = {
      at: nowIso,
      from: redact(from, MAX_ID),
      to: to === "all" ? "all" : redact(to, MAX_ID),
      body: redact(body, MAX_BODY),
    };
    const file = path.join(projectRoot, TEAM_MESSAGES_REL);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.appendFileSync(file, JSON.stringify(msg) + "\n");
    return true;
  } catch {
    return false;
  }
}

// ── ledger I/O (versioned, tamper-safe) ──────────────────────────────────────

function pick<T extends string>(v: unknown, allowed: T[], fallback: T): T {
  return typeof v === "string" && (allowed as string[]).includes(v)
    ? (v as T)
    : fallback;
}

function sanitizeMember(raw: unknown): TeamMember | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (!isId(r.memberId)) return null;
  return {
    memberId: r.memberId,
    role: r.role === "lead" ? "lead" : "teammate",
    status: pick(r.status, MEMBER_STATUSES, "active"),
    joinedAt: sanitizeText(r.joinedAt, 40),
  };
}

function sanitizeTask(raw: unknown): TeamTask | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (!isId(r.taskId)) return null;
  return {
    taskId: r.taskId,
    title: sanitizeText(r.title, MAX_TITLE),
    assignedTo: isId(r.assignedTo) ? r.assignedTo : null,
    claimStatus: pick(r.claimStatus, CLAIM_STATUSES, "open"),
    claimedBy: isId(r.claimedBy) ? r.claimedBy : null,
    claimedAt: sanitizeText(r.claimedAt, 40) || null,
    workerId: isId(r.workerId) ? r.workerId : null,
  };
}

/**
 * Re-enforce the ledger invariants AFTER field sanitization, fail-closed. Field
 * sanitization alone does not stop a tampered ledger from loading as active +
 * approved with a bogus lead, which would let `claimTask` bypass approval. So:
 *   - unique members (dedupe by id) + unique tasks; exactly ONE lead or the
 *     whole ledger is rejected (returns null — a team must have one lead);
 *   - `approved` is trusted ONLY when `approvedBy` is that canonical lead, else
 *     approval is dropped (claims stay blocked);
 *   - a task's `assignedTo`/`claimedBy` must reference an ACTIVE member, else it
 *     is cleared (a claim by a ghost member is reset to open).
 */
function reconcileLedger(l: TeamLedger): TeamLedger | null {
  const seenM = new Set<string>();
  const members = l.members.filter((m) =>
    seenM.has(m.memberId) ? false : (seenM.add(m.memberId), true),
  );
  const leads = members.filter((m) => m.role === "lead");
  if (leads.length !== 1) return null; // no single lead -> not a valid team
  const lead = leads[0].memberId;
  const activeIds = new Set(
    members.filter((m) => m.status === "active").map((m) => m.memberId),
  );

  const approvalOk =
    l.planApproval.approved && l.planApproval.approvedBy === lead;
  const planApproval: PlanApproval = approvalOk
    ? l.planApproval
    : {
        ...l.planApproval,
        approved: false,
        approvedBy: null,
        approvedAt: null,
      };

  const seenT = new Set<string>();
  const tasks = l.tasks
    .filter((t) => (seenT.has(t.taskId) ? false : (seenT.add(t.taskId), true)))
    .map((t) => {
      const assignedTo =
        t.assignedTo && activeIds.has(t.assignedTo) ? t.assignedTo : null;
      // A claim by a non-active/unknown member is invalid -> reset to open.
      if (
        t.claimStatus === "claimed" &&
        (!t.claimedBy || !activeIds.has(t.claimedBy))
      )
        return {
          ...t,
          assignedTo,
          claimStatus: "open" as ClaimStatus,
          claimedBy: null,
          claimedAt: null,
        };
      return { ...t, assignedTo };
    });

  return { ...l, members, tasks, planApproval };
}

export function loadTeamLedger(projectRoot: string): TeamLedger | null {
  const file = path.join(projectRoot, TEAM_LEDGER_REL);
  try {
    const p = JSON.parse(fs.readFileSync(file, "utf8"));
    if (typeof p !== "object" || p === null || !isId(p.teamId)) return null;
    const members = (Array.isArray(p.members) ? p.members : [])
      .map(sanitizeMember)
      .filter((m: TeamMember | null): m is TeamMember => !!m);
    const tasks = (Array.isArray(p.tasks) ? p.tasks : [])
      .map(sanitizeTask)
      .filter((t: TeamTask | null): t is TeamTask => !!t);
    const pa = (p.planApproval ?? {}) as Record<string, unknown>;
    const sd = (p.shutdown ?? {}) as Record<string, unknown>;
    const sanitized: TeamLedger = {
      version: TEAM_LEDGER_VERSION,
      teamId: p.teamId,
      createdAt: sanitizeText(p.createdAt, 40),
      status: pick(p.status, TEAM_STATUSES, "forming"),
      members,
      tasks,
      planApproval: {
        required: pa.required !== false,
        approved: pa.approved === true,
        approvedBy: isId(pa.approvedBy) ? pa.approvedBy : null,
        approvedAt: sanitizeText(pa.approvedAt, 40) || null,
      },
      shutdown: {
        requested: sd.requested === true,
        requestedBy: isId(sd.requestedBy) ? sd.requestedBy : null,
        reason: sanitizeText(sd.reason, MAX_REASON),
        at: sanitizeText(sd.at, 40) || null,
      },
    };
    // Field sanitization is not enough — enforce the structural invariants.
    return reconcileLedger(sanitized);
  } catch {
    return null;
  }
}

export function saveTeamLedger(projectRoot: string, ledger: TeamLedger): void {
  const file = path.join(projectRoot, TEAM_LEDGER_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(
    file,
    JSON.stringify({ ...ledger, version: TEAM_LEDGER_VERSION }, null, 2) + "\n",
  );
}
