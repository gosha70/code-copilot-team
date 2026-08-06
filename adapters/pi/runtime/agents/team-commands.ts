/**
 * Team command WIRING (issue #185, Slice A of #174; authored).
 *
 * Composes the built, tested `team.ts` (T8.1) + `team-status.ts` (T8.2)
 * libraries into Pi's live `/cct:team` command + `pi-code team` CLI. **Wiring
 * only** — no re-implementation of the coordination/safety model. Corrected
 * across four PR #184 review rounds:
 *
 *  - Canonical team-state root is resolved FAIL-CLOSED via `primaryRepoRoot`
 *    (shared git common dir) — no `?? cwd`, so a git failure / linked worktree
 *    never creates a per-worktree split ledger.
 *  - Identity (`CCT_TEAM_ID` + `CCT_TEAM_MEMBER_ID`, BOTH mandatory) is DECLARED,
 *    ledger-validated ATTRIBUTION — not authentication. The actor is taken from
 *    the declared identity, never a command argument; a co-located session can
 *    still declare any existing member id, so impersonation is not prevented
 *    (documented; authenticated authz is an epic decision).
 *  - Authorization is re-validated against the CURRENT ledger INSIDE the lock on
 *    every mutation (team binding + active actor + lead-only), never cached.
 *  - `create` never overwrites an existing/corrupt team; `message` validates +
 *    appends under the lock without rewriting `team.json`.
 *
 * Teams are coordination STATE, not execution (`degraded`): peers run via the
 * T7.2/T7.4 runners, messaging is a polled append-log, status is a snapshot.
 */

import * as fs from "node:fs";

import {
  activateTeam,
  addTeammate,
  approvePlan,
  claimTask,
  closeTeam,
  completeTask,
  createTeam,
  failTask,
  loadTeamLedger,
  postMessage,
  postTask,
  requestShutdown,
  saveTeamLedger,
  assignTask,
  type TeamLedger,
  type TeamMember,
  type TeamOpResult,
} from "./team.ts";
import {
  markMemberLeft,
  renderTeamStatus,
  reopenOrphanedClaims,
  synthesizeTeam,
  teamStatus,
} from "./team-status.ts";
import { withLedgerLock } from "./ledger-lock.ts";
import { primaryRepoRoot, type LifecycleDeps } from "./worktree-lifecycle.ts";
import { audit } from "../policy/audit.ts";

export const TEAM_AUDIT = {
  create: "team.create",
  join: "team.join",
  task: "team.task",
  assign: "team.assign",
  approve: "team.approve",
  activate: "team.activate",
  claim: "team.claim",
  complete: "team.complete",
  fail: "team.fail",
  message: "team.message",
  leave: "team.leave",
  recover: "team.recover",
  shutdown: "team.shutdown",
  close: "team.close",
  status: "team.status",
  identityInvalid: "team.identity-invalid",
  rootUnresolved: "team.root-unresolved",
} as const;

const AUDIT_ORIGIN = "team";
/** Env contract (declared identity — attribution, NOT authentication). */
export const TEAM_ENV = {
  id: "CCT_TEAM_ID",
  memberId: "CCT_TEAM_MEMBER_ID",
} as const;

/** Mutating subcommands (gated by `agents.teams_enabled`). */
const MUTATIONS = new Set([
  "create",
  "join",
  "task",
  "assign",
  "approve",
  "activate",
  "claim",
  "complete",
  "fail",
  "message",
  "leave",
  "recover",
  "shutdown",
  "close",
]);
/** Subcommands that require the actor to be the ACTIVE LEAD. */
const LEAD_ONLY = new Set([
  "assign",
  "approve",
  "activate",
  "recover",
  "close",
]);

// ── identity + root (fail-closed) ────────────────────────────────────────────

export interface TeamIdentity {
  teamId: string;
  memberId: string;
}

/** Read the DECLARED identity — BOTH ids required, else null. */
export function readTeamIdentity(env: NodeJS.ProcessEnv): TeamIdentity | null {
  const teamId = (env[TEAM_ENV.id] ?? "").trim();
  const memberId = (env[TEAM_ENV.memberId] ?? "").trim();
  if (!teamId || !memberId) return null;
  return { teamId, memberId };
}

export type TeamRootResult =
  { ok: true; root: string } | { ok: false; reason: string };

/**
 * The canonical team-state root — the primary checkout that owns
 * `.cct/team.json`. FAIL-CLOSED: `primaryRepoRoot` returning null (git failure /
 * not a repo) yields `{ ok: false }` — never a `?? cwd` fallback (that would
 * split state per worktree).
 */
export function resolveTeamRoot(
  cwd: string,
  deps: LifecycleDeps = {},
): TeamRootResult {
  const root = primaryRepoRoot(cwd, deps);
  return root
    ? { ok: true, root }
    : { ok: false, reason: "no canonical repository root (not a git repo?)" };
}

function auditTeam(
  mode: string,
  decision: string,
  rule: string,
  subject: string,
): void {
  audit({
    mode,
    actor: "cct:team",
    decision,
    rule,
    subject,
    origin: AUDIT_ORIGIN,
  });
}

const TEAM_JSON_REL = ".cct/team.json";

// ── in-session command handler ───────────────────────────────────────────────

export interface TeamCommandCtx {
  cwd: string;
  env: NodeJS.ProcessEnv;
  mode: string;
  teamsEnabled: boolean;
  /** Claim cap; when undefined, `claimTask` applies its own default. */
  maxConcurrency?: number;
  now: string;
  /** Test-injection for forcing a git failure. */
  deps?: LifecycleDeps;
}

const USAGE =
  "usage: /cct:team create <teamId> [--no-plan-approval] | join <memberId> | " +
  "task <taskId> <title…> [--assign <m>] [--worker <w>] | assign <taskId> <m> | " +
  "approve | activate | claim <taskId> | complete <taskId> | fail <taskId> | " +
  "message <to|all> <body…> | leave | recover | shutdown [--reason …] | close | " +
  "status | synthesize";

/**
 * Handle `/cct:team <argv...>` and return the reply text. Mutations are gated by
 * `agents.teams_enabled`, resolve the fail-closed root, and run their full
 * load → team-binding → active-actor authz → op → save inside the team lock.
 */
export function runTeamCommand(ctx: TeamCommandCtx, argv: string[]): string {
  const sub = (argv[0] ?? "").toLowerCase();
  const rest = argv.slice(1);
  if (!sub) return USAGE;

  // Reads (status/synthesize) are not gated — they render whenever a valid
  // ledger exists (mirrors the CLI's honest gate semantics).
  if (sub === "status" || sub === "synthesize") {
    return readReport(ctx, sub === "synthesize", flagPresent(rest, "--json"))
      .out;
  }
  if (!MUTATIONS.has(sub)) return `unknown subcommand '${sub}'\n${USAGE}`;

  if (!ctx.teamsEnabled) {
    return "teams are opt-in: set `agents.teams_enabled = true` to use /cct:team.";
  }

  const rootRes = resolveTeamRoot(ctx.cwd, ctx.deps);
  if (!rootRes.ok) {
    auditTeam(ctx.mode, "deny", TEAM_AUDIT.rootUnresolved, sub);
    return `refused: ${rootRes.reason} — team state needs a canonical repo root.`;
  }
  const root = rootRes.root;

  const identity = readTeamIdentity(ctx.env);
  if (!identity) {
    auditTeam(ctx.mode, "deny", TEAM_AUDIT.identityInvalid, sub);
    return `refused: set ${TEAM_ENV.id} and ${TEAM_ENV.memberId} (both required) to run team commands.`;
  }

  // create is the bootstrap path (no pre-existing membership).
  if (sub === "create") return handleCreate(ctx, root, identity, rest);

  // Every other mutation: full transaction under the lock.
  return withLedgerLock(root, () => mutate(ctx, root, identity, sub, rest), {
    lockName: "team",
  });
}

function handleCreate(
  ctx: TeamCommandCtx,
  root: string,
  identity: TeamIdentity,
  rest: string[],
): string {
  const teamIdArg = rest.find((a) => !a.startsWith("--")) ?? "";
  if (!teamIdArg)
    return "usage: /cct:team create <teamId> [--no-plan-approval]";
  if (teamIdArg !== identity.teamId) {
    auditTeam(
      ctx.mode,
      "deny",
      TEAM_AUDIT.identityInvalid,
      `${teamIdArg}!=${identity.teamId}`,
    );
    return `refused: create <${teamIdArg}> must match ${TEAM_ENV.id}='${identity.teamId}'.`;
  }
  const planRequired = !flagPresent(rest, "--no-plan-approval");

  return withLedgerLock(
    root,
    () => {
      const file = `${root}/${TEAM_JSON_REL}`;
      if (fs.existsSync(file)) {
        const existing = loadTeamLedger(root);
        const why = existing
          ? "a team already exists"
          : "existing team ledger is invalid";
        auditTeam(ctx.mode, "deny", TEAM_AUDIT.create, `${teamIdArg}:${why}`);
        return `refused: ${why} at ${TEAM_JSON_REL} — not overwriting.`;
      }
      const res = createTeam(teamIdArg, identity.memberId, ctx.now, {
        planRequired,
      });
      if (res.ok) saveTeamLedger(root, res.ledger);
      auditTeam(
        ctx.mode,
        res.ok ? "created" : "deny",
        TEAM_AUDIT.create,
        `${teamIdArg}:${identity.memberId}`,
      );
      return res.ok
        ? `created team '${teamIdArg}' (lead ${identity.memberId}${planRequired ? "; plan approval required" : ""}).`
        : `refused: ${res.error}`;
    },
    { lockName: "team" },
  );
}

/** Runs INSIDE the team lock: load → team-binding → active-actor → authz → op → save. */
function mutate(
  ctx: TeamCommandCtx,
  root: string,
  identity: TeamIdentity,
  sub: string,
  rest: string[],
): string {
  const ledger = loadTeamLedger(root);
  if (!ledger) {
    auditTeam(ctx.mode, "deny", teamRule(sub), `${identity.teamId}:no-ledger`);
    return `refused: no team ledger at ${TEAM_JSON_REL} (create one first).`;
  }
  // Team binding — the declared team must match the ledger.
  if (identity.teamId !== ledger.teamId) {
    auditTeam(
      ctx.mode,
      "deny",
      TEAM_AUDIT.identityInvalid,
      `${identity.teamId}!=${ledger.teamId}`,
    );
    return `refused: ${TEAM_ENV.id}='${identity.teamId}' does not match this team ('${ledger.teamId}').`;
  }
  // Actor must be an active member (re-validated now, never cached).
  const actor: TeamMember | undefined = ledger.members.find(
    (m) => m.memberId === identity.memberId,
  );
  if (!actor || actor.status !== "active") {
    auditTeam(
      ctx.mode,
      "deny",
      teamRule(sub),
      `${ledger.teamId}:${identity.memberId}:not-active`,
    );
    return `refused: '${identity.memberId}' is not an active member of '${ledger.teamId}'.`;
  }
  // Lead-only tier.
  if (LEAD_ONLY.has(sub) && actor.role !== "lead") {
    auditTeam(
      ctx.mode,
      "deny",
      teamRule(sub),
      `${ledger.teamId}:${identity.memberId}:not-lead`,
    );
    return `refused: '${sub}' is lead-only; '${identity.memberId}' is not the lead.`;
  }
  // Sole-lead guard — the only active lead cannot strand a non-closed team.
  if (sub === "leave" && actor.role === "lead" && ledger.status !== "closed") {
    auditTeam(
      ctx.mode,
      "deny",
      TEAM_AUDIT.leave,
      `${ledger.teamId}:${identity.memberId}:sole-lead`,
    );
    return "refused: the lead cannot leave a non-closed team (no lead transfer in this slice — close it instead).";
  }

  const me = identity.memberId;
  let res: TeamOpResult;
  let rule = teamRule(sub);

  switch (sub) {
    case "join": {
      const newMember = rest.find((a) => !a.startsWith("--")) ?? "";
      if (!newMember) return "usage: /cct:team join <memberId>";
      res = addTeammate(ledger, newMember, ctx.now);
      break;
    }
    case "task": {
      const pos = rest.filter((a) => !a.startsWith("--"));
      const taskId = pos[0] ?? "";
      const title = pos.slice(1).join(" ");
      if (!taskId || !title)
        return "usage: /cct:team task <taskId> <title…> [--assign <m>] [--worker <w>]";
      res = postTask(ledger, {
        taskId,
        title,
        assignedTo: flagValue(rest, "--assign") ?? null,
        workerId: flagValue(rest, "--worker") ?? null,
      });
      break;
    }
    case "assign": {
      const [taskId, member] = rest.filter((a) => !a.startsWith("--"));
      if (!taskId || !member)
        return "usage: /cct:team assign <taskId> <memberId>";
      res = assignTask(ledger, taskId, member);
      break;
    }
    case "approve":
      res = approvePlan(ledger, me, ctx.now);
      break;
    case "activate":
      res = activateTeam(ledger);
      break;
    case "claim": {
      const taskId = rest.find((a) => !a.startsWith("--")) ?? "";
      if (!taskId) return "usage: /cct:team claim <taskId>";
      res = claimTask(ledger, taskId, me, ctx.now, {
        maxConcurrency: ctx.maxConcurrency,
      });
      break;
    }
    case "complete":
    case "fail": {
      const taskId = rest.find((a) => !a.startsWith("--")) ?? "";
      if (!taskId) return `usage: /cct:team ${sub} <taskId>`;
      res = (sub === "complete" ? completeTask : failTask)(ledger, taskId, me);
      break;
    }
    case "message":
      return handleMessage(ctx, root, ledger, me, rest);
    case "leave":
      res = markMemberLeft(ledger, me, ctx.now);
      break;
    case "recover":
      res = reopenOrphanedClaims(ledger);
      break;
    case "shutdown":
      res = requestShutdown(
        ledger,
        me,
        flagValue(rest, "--reason") ?? "",
        ctx.now,
      );
      break;
    case "close":
      res = closeTeam(ledger);
      break;
    default:
      return `unknown subcommand '${sub}'\n${USAGE}`;
  }

  if (res.ok) saveTeamLedger(root, res.ledger);
  auditTeam(ctx.mode, res.ok ? sub : "deny", rule, `${ledger.teamId}:${me}`);
  return res.ok ? `${sub}: ok.` : `refused: ${res.error}`;
}

/** `message` — validate under the lock, append via postMessage; no team.json rewrite. */
function handleMessage(
  ctx: TeamCommandCtx,
  root: string,
  ledger: TeamLedger,
  from: string,
  rest: string[],
): string {
  if (ledger.status === "closed") return "refused: the team is closed.";
  const to = rest[0] ?? "";
  const body = rest.slice(1).join(" ");
  if (!to || !body) return "usage: /cct:team message <to|all> <body…>";
  if (to !== "all" && !ledger.members.some((m) => m.memberId === to)) {
    return `refused: no member '${to}' (use a member id or 'all').`;
  }
  const ok = postMessage(root, from, to, body, ctx.now);
  auditTeam(
    ctx.mode,
    ok ? "message" : "deny",
    TEAM_AUDIT.message,
    `${ledger.teamId}:${from}->${to}`,
  );
  return ok ? `message sent to ${to}.` : "refused: message not delivered.";
}

// ── read reports (in-session + CLI) ──────────────────────────────────────────

export interface CliResult {
  out: string;
  code: number;
}

/** Read-only status/synthesis at the resolved root; renders any valid ledger. */
export function readReport(
  ctx: { cwd: string; deps?: LifecycleDeps },
  synth: boolean,
  json: boolean,
): CliResult {
  const rootRes = resolveTeamRoot(ctx.cwd, ctx.deps);
  if (!rootRes.ok) return { out: rootRes.reason, code: 69 };
  const file = `${rootRes.root}/${TEAM_JSON_REL}`;
  if (!fs.existsSync(file)) {
    return {
      out: json
        ? JSON.stringify({ team: null }, null, 2)
        : "no team (create one with /cct:team create).",
      code: 0,
    };
  }
  const ledger = loadTeamLedger(rootRes.root);
  if (!ledger) return { out: "team ledger is invalid (fail-closed).", code: 1 };
  if (synth) {
    const s = synthesizeTeam(ledger);
    return {
      out: json ? JSON.stringify(s, null, 2) : `verdict: ${s.verdict}`,
      code: 0,
    };
  }
  return { out: renderTeamStatus(teamStatus(ledger), json), code: 0 };
}

/**
 * Session-start advisory — a one-line status summary when teams are enabled and
 * a valid ledger exists at the canonical root. Read-only; never `null`→status;
 * silent on an unresolved root.
 */
export function teamAdvisory(
  cwd: string,
  opts: { enabled: boolean; mode: string },
  deps: LifecycleDeps = {},
): string | null {
  if (!opts.enabled) return null;
  const rootRes = resolveTeamRoot(cwd, deps);
  if (!rootRes.ok) return null;
  const file = `${rootRes.root}/${TEAM_JSON_REL}`;
  if (!fs.existsSync(file)) return null;
  const ledger = loadTeamLedger(rootRes.root);
  if (!ledger)
    return `team ledger at ${TEAM_JSON_REL} is invalid (fail-closed)`;
  const v = teamStatus(ledger);
  auditTeam(opts.mode, "status", TEAM_AUDIT.status, `${v.teamId}:${v.status}`);
  return (
    `team '${v.teamId}' [${v.status}] — ${v.members.active} active member(s), ` +
    `tasks ${v.tasks.open} open / ${v.tasks.claimed} claimed / ${v.tasks.done} done / ${v.tasks.failed} failed`
  );
}

// ── small parse helpers ──────────────────────────────────────────────────────

function flagPresent(argv: string[], flag: string): boolean {
  return argv.includes(flag);
}
function flagValue(argv: string[], flag: string): string | undefined {
  const i = argv.indexOf(flag);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : undefined;
}
function teamRule(sub: string): string {
  return (TEAM_AUDIT as Record<string, string>)[sub] ?? `team.${sub}`;
}
