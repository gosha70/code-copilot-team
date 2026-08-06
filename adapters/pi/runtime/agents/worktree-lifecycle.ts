/**
 * Pi worktree lifecycle WIRING (issue #172; authored).
 *
 * The T7.3 worktree manager (`./worktree.ts`, merged #154/#155) already owns the
 * safety model — isolation off a base branch, protected-branch refusal, ownership
 * conflicts, dirty/foreign/primary protection, symlink-escape containment, stale
 * reconcile. This module does NOT re-implement any of it. It COMPOSES the manager
 * into Pi's verifiable session lifecycle, corrected per the PR #183 reviews:
 *
 *  - Creation is PRE-SPAWN. Pi captures `ctx.cwd` at session_start and exposes no
 *    API to relocate a running session, so a worktree created at session_start
 *    would leave the agent editing the PRIMARY checkout. Provisioning therefore
 *    happens before the worker Pi is spawned (`provisionWorktree`, driven by
 *    `pi-code worktree create`); the driver launches the worker with
 *    `cwd = worktreePath`.
 *  - The extension VALIDATES on session_start (`attachOnSessionStart`): both
 *    `process.cwd()` and `git rev-parse --show-toplevel` must equal the record's
 *    worktreePath. On failure it does not merely warn — it sets the isolation
 *    state to `invalid`, and the `tool_call` gate (via `isolationToolBlock`)
 *    BLOCKS every edit/write/bash until isolation is corrected (operationally
 *    fail-closed, review #1).
 *  - Every ledger mutation runs its FULL transaction inside a repo-scoped lock
 *    (`withLedgerLock`) with PID/token ownership so a slow-but-live holder's lock
 *    is never stolen (review #2/#3).
 *  - Reconcile is FAIL-CLOSED and PRIMARY-EXCLUDED (`reconcileOnStart`): it runs
 *    only when the git listing is STRUCTURALLY valid (`listWorktreesStrict`
 *    rejects malformed porcelain, review #4), never marks live workers stale on a
 *    git failure, and never auto-removes live work. The whole load→list→prune→
 *    reconcile→save transaction runs inside the lock.
 *
 * Teardown is EXPLICIT-ONLY (`/cct:worktree cleanup`) because Pi exposes no
 * session-end event — degraded by construction, not a bug.
 */

import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

import {
  cleanupWorker,
  createWorker,
  listWorktrees,
  loadLedger,
  pruneWorktrees,
  reconcile,
  resolveWorktreePath,
  saveLedger,
  type CreateRequest,
  type GitOpResult,
  type LiveWorktree,
} from "./worktree.ts";
import { audit } from "../policy/audit.ts";

/** Audit `rule` names (cross module/test boundary — named, never inlined). */
export const WORKTREE_AUDIT = {
  attach: "worktree.attach",
  notIsolated: "worktree.not-isolated",
  create: "worktree.create",
  cleanup: "worktree.cleanup",
  reconcile: "worktree.reconcile",
  reconcileSkipped: "worktree.reconcile-skipped",
} as const;

/** Audit `origin` for every lifecycle action. */
const AUDIT_ORIGIN = "worktree";

/**
 * The `CCT_WORKER_*` env contract set by the spawning driver (FR-3). All values
 * are UNTRUSTED and re-validated by the manager before any git side effect.
 */
export const WORKER_ENV = {
  id: "CCT_WORKER_ID",
  branch: "CCT_WORKER_BRANCH",
  base: "CCT_WORKER_BASE",
  tasks: "CCT_WORKER_TASKS",
  areas: "CCT_WORKER_AREAS",
  path: "CCT_WORKER_PATH",
  featureId: "CCT_FEATURE_ID",
} as const;

const LOCK_REL = path.join(".cct", "worktrees.lock");
const LOCK_OWNER_FILE = "owner.json";
const DEFAULT_LOCK_TIMEOUT_MS = 5000;
const DEFAULT_LOCK_STALE_MS = 60_000;
const LOCK_RETRY_MS = 50;
const MAX_WORKER_ID = 64;

/** Tools that mutate the tree — blocked when worktree isolation is invalid. */
const ISOLATION_GUARDED_TOOLS = new Set(["edit", "write", "bash"]);

/** Recognized `git worktree list --porcelain` attribute keys (strict parse). */
const PORCELAIN_ATTR_KEYS = new Set([
  "HEAD",
  "branch",
  "bare",
  "detached",
  "locked",
  "prunable",
]);

/** Injectable git/list dependencies so temp-repo tests can force failures. */
export interface LifecycleDeps {
  gitToplevel?: (dir: string) => string | null;
  gitCommonDir?: (dir: string) => string | null;
  /** Display-only listing (read commands). */
  listWorktrees?: (repoRoot: string) => LiveWorktree[];
  /** Trust-bearing listing used by reconcile's fail-closed gate. */
  listWorktreesStrict?: (repoRoot: string) => ListWorktreesResult;
  pruneWorktrees?: (repoRoot: string) => GitOpResult;
}

// ── git helpers ──────────────────────────────────────────────────────────────

function gitLine(dir: string, args: string[]): string | null {
  const r = spawnSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  if ((r.status ?? 1) !== 0) return null;
  const out = (r.stdout ?? "").trim();
  return out.length ? out : null;
}

/** `git rev-parse --show-toplevel` for `dir`, or null when it is not a repo. */
export function gitToplevel(dir: string): string | null {
  return gitLine(dir, ["rev-parse", "--show-toplevel"]);
}

/** Resolved path to the shared `.git` common dir, or null. */
export function gitCommonDir(dir: string): string | null {
  const out = gitLine(dir, ["rev-parse", "--git-common-dir"]);
  return out ? path.resolve(dir, out) : null;
}

/**
 * The PRIMARY worktree root — the checkout that owns `.cct/worktrees.json`. From
 * a linked worker worktree, `--git-common-dir` still points at the shared
 * `<primary>/.git`, whose parent is the primary. Returns null outside a repo.
 */
export function primaryRepoRoot(
  cwd: string,
  deps: LifecycleDeps = {},
): string | null {
  const common = (deps.gitCommonDir ?? gitCommonDir)(cwd);
  return common ? path.dirname(common) : null;
}

// ── strict porcelain listing (review #4) ─────────────────────────────────────

export interface ListWorktreesResult {
  ok: boolean;
  worktrees: LiveWorktree[];
  reason?: string;
}

/**
 * STRICT parse of `git worktree list --porcelain`. Unlike the manager's
 * tolerant `listWorktrees()` (which ignores malformed lines and always calls the
 * first block primary), this REJECTS structurally-invalid output so reconcile
 * can fail closed on truncated/garbled porcelain (review #4): a block must open
 * with `worktree <abs-path>`, nothing may precede the first block, an unknown
 * key is rejected, and exactly one primary must result. `{ ok:false, reason }`
 * on any violation. Fail-closed by construction — a rejected listing simply
 * skips reconcile, never touching the ledger.
 */
export function parseWorktreePorcelainStrict(
  stdout: string,
): ListWorktreesResult {
  const worktrees: LiveWorktree[] = [];
  let cur: { path: string; branch: string | null } | null = null;
  const bad = (reason: string): ListWorktreesResult => ({
    ok: false,
    worktrees: [],
    reason,
  });
  const flush = (): void => {
    if (cur) {
      worktrees.push({
        path: cur.path,
        branch: cur.branch,
        isPrimary: worktrees.length === 0,
      });
      cur = null;
    }
  };

  for (const line of stdout.split("\n")) {
    if (line === "") {
      flush(); // a blank line terminates a block
      continue;
    }
    const sp = line.indexOf(" ");
    const key = sp === -1 ? line : line.slice(0, sp);
    const val = sp === -1 ? "" : line.slice(sp + 1);

    if (key === "worktree") {
      flush();
      if (!val || !path.isAbsolute(val)) {
        return bad(`worktree line without an absolute path: '${line}'`);
      }
      cur = { path: val, branch: null };
    } else if (!cur) {
      return bad(`unexpected line before any worktree block: '${line}'`);
    } else if (key === "branch") {
      cur.branch = val.replace(/^refs\/heads\//, "");
    } else if (!PORCELAIN_ATTR_KEYS.has(key)) {
      return bad(`unrecognized porcelain key: '${key}'`);
    }
  }
  flush();

  if (worktrees.length === 0) return bad("no worktree entries parsed");
  if (worktrees.filter((w) => w.isPrimary).length !== 1) {
    return bad("expected exactly one primary worktree");
  }
  return { ok: true, worktrees };
}

/** Run `git worktree list --porcelain` and strictly parse it (review #4). */
export function listWorktreesStrict(repoRoot: string): ListWorktreesResult {
  const r = spawnSync(
    "git",
    ["-C", repoRoot, "worktree", "list", "--porcelain"],
    { encoding: "utf8" },
  );
  if ((r.status ?? 1) !== 0) {
    return {
      ok: false,
      worktrees: [],
      reason: `git worktree list exited ${r.status ?? "?"}`,
    };
  }
  return parseWorktreePorcelainStrict(r.stdout ?? "");
}

// ── lock (review #2/#3: full-transaction, PID/token ownership) ───────────────

/** Block the thread without spinning (legitimate in a CLI / short startup wait). */
function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/**
 * Liveness of a pid: true (alive / exists), false (gone), undefined (unknown /
 * unsupported). Used so a stale-lock is reclaimed ONLY when its owner is not
 * alive — a slow but live worker never has its lock stolen.
 */
function isProcessAlive(pid: number): boolean | undefined {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    const code = (e as NodeJS.ErrnoException).code;
    if (code === "EPERM") return true; // exists, not ours to signal
    if (code === "ESRCH") return false; // no such process
    return undefined; // unsupported / unknown
  }
}

export interface LockOptions {
  timeoutMs?: number;
  staleMs?: number;
}

interface LockOwner {
  pid: number;
  token: string;
  ts: number;
}

/**
 * Run `fn` while holding a repo-scoped `.cct/worktrees.lock` (FR-5). The lock is
 * an atomic `mkdir` plus an `owner.json` recording `{pid, token}`. On contention
 * it retries within a bounded timeout and, on timeout, FAILS CLOSED by throwing.
 * A lock is reclaimed only when its owner is provably NOT alive (crashed), or —
 * when liveness cannot be determined — after `staleMs`; a live owner's lock is
 * never stolen. On release the lock is removed only if THIS call still owns the
 * recorded token (a reclaimer may have taken over). Every ledger mutation runs
 * its full `load → validate → git → save` inside this critical section.
 */
export function withLedgerLock<T>(
  repoRoot: string,
  fn: () => T,
  opts: LockOptions = {},
): T {
  const timeoutMs = opts.timeoutMs ?? DEFAULT_LOCK_TIMEOUT_MS;
  const staleMs = opts.staleMs ?? DEFAULT_LOCK_STALE_MS;
  const lockDir = path.join(repoRoot, LOCK_REL);
  const ownerFile = path.join(lockDir, LOCK_OWNER_FILE);
  fs.mkdirSync(path.dirname(lockDir), { recursive: true });
  const deadline = Date.now() + timeoutMs;
  const myToken = `${process.pid}.${process.hrtime.bigint().toString()}`;

  const readOwner = (): LockOwner | null => {
    try {
      const o = JSON.parse(fs.readFileSync(ownerFile, "utf8"));
      return o && typeof o === "object" ? (o as LockOwner) : null;
    } catch {
      return null;
    }
  };

  for (;;) {
    try {
      fs.mkdirSync(lockDir); // atomic: EEXIST if held
      fs.writeFileSync(
        ownerFile,
        JSON.stringify({ pid: process.pid, token: myToken, ts: Date.now() }),
      );
      break;
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== "EEXIST") throw err;

      const owner = readOwner();
      const alive =
        owner && typeof owner.pid === "number"
          ? isProcessAlive(owner.pid)
          : undefined;
      let reclaim = false;
      if (alive === false) {
        reclaim = true; // owner crashed — safe to reclaim regardless of age
      } else if (alive === undefined) {
        let age = Infinity; // liveness unknown — fall back to age
        try {
          age = Date.now() - fs.statSync(lockDir).mtimeMs;
        } catch {
          age = Infinity; // lock vanished between EEXIST and stat — retry now
        }
        if (age > staleMs) reclaim = true;
      } // alive === true => a live holder; never reclaim

      if (reclaim) {
        try {
          fs.rmSync(lockDir, { recursive: true, force: true });
        } catch {
          /* someone else reclaimed it first — retry */
        }
        continue;
      }
      if (Date.now() >= deadline) {
        throw new Error(
          `could not acquire worktree ledger lock at ${lockDir} within ${timeoutMs}ms`,
        );
      }
      sleepSync(LOCK_RETRY_MS);
    }
  }

  try {
    return fn();
  } finally {
    const owner = readOwner();
    // Release only if we still own it (a reclaimer may have taken over).
    if (!owner || owner.token === myToken) {
      try {
        fs.rmSync(lockDir, { recursive: true, force: true });
      } catch {
        /* already gone — nothing to release */
      }
    }
  }
}

// ── paths + env contract ─────────────────────────────────────────────────────

/** Reduce an untrusted worker id to a safe path segment (kebab, bounded). */
export function sanitizeWorkerId(workerId: string): string {
  const s = String(workerId)
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_WORKER_ID);
  return s || "worker";
}

/**
 * Default worktree path, NAMESPACED by repository so two sibling repos with the
 * same workerId never collide (FR-4):
 * `<repo-parent>/.cct-worktrees/<repo-name>/<sanitized-worker-id>`. This stays
 * inside the managed root (the repo's parent), so it passes the manager's
 * containment check. An explicit `CCT_WORKER_PATH` override is honored but still
 * validated by the manager.
 */
export function defaultWorktreePath(
  repoRoot: string,
  workerId: string,
): string {
  return path.join(
    path.dirname(repoRoot),
    ".cct-worktrees",
    path.basename(repoRoot),
    sanitizeWorkerId(workerId),
  );
}

export interface WorkerEnv {
  workerId: string;
  branch: string;
  base?: string;
  worktreePath?: string;
  tasks: string[];
  areas: string[];
  featureId?: string;
}

/** Parse the `CCT_WORKER_*` env contract (all fields untrusted). */
export function readWorkerEnv(env: NodeJS.ProcessEnv): WorkerEnv {
  const one = (k: string): string | undefined => {
    const v = env[k];
    return v && v.trim() ? v.trim() : undefined;
  };
  const list = (k: string): string[] =>
    (env[k] ?? "")
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
  return {
    workerId: one(WORKER_ENV.id) ?? "",
    branch: one(WORKER_ENV.branch) ?? "",
    base: one(WORKER_ENV.base),
    worktreePath: one(WORKER_ENV.path),
    tasks: list(WORKER_ENV.tasks),
    areas: list(WORKER_ENV.areas),
    featureId: one(WORKER_ENV.featureId),
  };
}

// ── validate/attach on session_start + fail-closed enforcement (FR-1/FR-2) ───

/**
 * Worktree isolation state, resolved at session_start. `invalid` means a worker
 * session failed validation and MUST be prevented from touching the tree.
 */
export type IsolationState = "ok" | "invalid" | "not-a-worker";

export interface AttachResult {
  status: "no-op" | "attached" | "not-isolated";
  workerId?: string;
  worktreePath?: string;
  warning?: string;
}

/** Map an attach outcome to the isolation state the tool_call gate reads. */
export function isolationStateFromAttach(
  status: AttachResult["status"],
): IsolationState {
  if (status === "attached") return "ok";
  if (status === "not-isolated") return "invalid";
  return "not-a-worker";
}

/**
 * The fail-closed enforcement decision (review #1). When isolation is `invalid`,
 * every edit/write/bash tool call is BLOCKED — warn + audit alone is not
 * operationally fail-closed; the worker must not be able to run from the wrong
 * directory. `ok` / `not-a-worker` never block (a primary session is not a
 * worker); read-only tools are never blocked.
 */
export function isolationToolBlock(
  state: IsolationState,
  toolName: string,
): { block: boolean; reason?: string } {
  if (
    state === "invalid" &&
    ISOLATION_GUARDED_TOOLS.has(toolName.toLowerCase())
  ) {
    return {
      block: true,
      reason:
        "worktree isolation NOT verified (CCT_WORKER_ID is set but the session " +
        "is not running inside its worktree) — refusing edit/write/bash until " +
        "isolation is corrected",
    };
  }
  return { block: false };
}

/**
 * On session_start, when `CCT_WORKER_ID` is set, VALIDATE that the running
 * session actually executes inside its worktree — both `process.cwd()` and
 * `git rev-parse --show-toplevel` must equal the ledger record's worktreePath.
 * Match => attach (audit `worktree.attach`). Mismatch / missing record / not a
 * repo => not-isolated (warn + audit `worktree.not-isolated`); the caller sets
 * the isolation state to `invalid`, and `isolationToolBlock` then blocks writes.
 * No `CCT_WORKER_ID` => no-op (primary session). This never creates anything.
 */
export function attachOnSessionStart(
  ctx: { cwd: string; mode: string },
  env: NodeJS.ProcessEnv,
  deps: LifecycleDeps = {},
): AttachResult {
  const we = readWorkerEnv(env);
  if (!we.workerId) return { status: "no-op" };

  const failClosed = (reason: string): AttachResult => {
    audit({
      mode: ctx.mode,
      actor: "session_start",
      decision: "deny",
      rule: WORKTREE_AUDIT.notIsolated,
      subject: `${we.workerId}:${we.branch || "<none>"}`,
      origin: AUDIT_ORIGIN,
    });
    return {
      status: "not-isolated",
      workerId: we.workerId,
      warning: `worktree isolation NOT verified for worker '${we.workerId}' — ${reason}. Writes are blocked until corrected.`,
    };
  };

  const primaryRoot = primaryRepoRoot(ctx.cwd, deps);
  if (!primaryRoot) return failClosed("not inside a git repository");

  const record = loadLedger(primaryRoot).workers.find(
    (w) => w.workerId === we.workerId,
  );
  if (!record) return failClosed("no ledger record (worker not provisioned)");

  const expected = record.worktreePath; // realpath-normalized at creation
  const actualCwd = resolveWorktreePath(ctx.cwd);
  const topRaw = (deps.gitToplevel ?? gitToplevel)(ctx.cwd);
  if (!topRaw) return failClosed("git rev-parse --show-toplevel failed");
  const toplevel = resolveWorktreePath(topRaw);

  if (actualCwd !== expected || toplevel !== expected) {
    return failClosed(
      `cwd '${actualCwd}' / toplevel '${toplevel}' != record '${expected}'`,
    );
  }

  audit({
    mode: ctx.mode,
    actor: "session_start",
    decision: "attached",
    rule: WORKTREE_AUDIT.attach,
    subject: `${we.workerId}:${record.branch}`,
    origin: AUDIT_ORIGIN,
  });
  return { status: "attached", workerId: we.workerId, worktreePath: expected };
}

// ── fail-closed reconcile (FR-7; review #3/#4) ───────────────────────────────

export interface ReconcileResult {
  status: "skipped" | "reconciled";
  reason?: string;
  stale: string[];
  foreign: string[];
  changed: boolean;
}

type ReconcileOutcome =
  | { kind: "skip"; reason: string }
  | { kind: "done"; stale: string[]; foreign: string[]; changed: boolean };

/**
 * Reconcile the ledger against the live worktrees — the WHOLE transaction
 * (list → prune → load → reconcile → save) runs inside the lock (review #3), so
 * a concurrent create/cleanup cannot be lost. It proceeds only when the git
 * listing is STRUCTURALLY valid (`listWorktreesStrict`, review #4) AND has
 * exactly one primary; otherwise it audits `worktree.reconcile-skipped` and
 * leaves the ledger byte-for-byte unchanged (a git failure never marks live
 * workers stale). The primary and non-existent paths are excluded before
 * `reconcile`; the ledger is saved only when something changed. Never
 * auto-removes live work.
 */
export function reconcileOnStart(
  cwd: string,
  opts: { mode: string },
  deps: LifecycleDeps = {},
): ReconcileResult {
  const primaryRoot = primaryRepoRoot(cwd, deps) ?? cwd;
  const listStrict = deps.listWorktreesStrict ?? listWorktreesStrict;
  const prune = deps.pruneWorktrees ?? pruneWorktrees;

  const outcome: ReconcileOutcome = withLedgerLock(primaryRoot, () => {
    const listed = listStrict(primaryRoot);
    if (!listed.ok) {
      return {
        kind: "skip",
        reason: `git worktree list untrustworthy: ${listed.reason ?? "unknown"}`,
      };
    }
    // Belt-and-suspenders: a valid parse still must have exactly one primary.
    if (listed.worktrees.filter((w) => w.isPrimary).length !== 1) {
      return {
        kind: "skip",
        reason: "git worktree list has no single primary",
      };
    }
    const pruned = prune(primaryRoot);
    if (!pruned.ok) {
      return {
        kind: "skip",
        reason: `git worktree prune failed: ${pruned.reason ?? "unknown"}`,
      };
    }

    const workerPaths = listed.worktrees
      .filter((w) => !w.isPrimary && fs.existsSync(w.path))
      .map((w) => resolveWorktreePath(w.path));
    const ledger = loadLedger(primaryRoot);
    const rec = reconcile(ledger, workerPaths);
    const changed = JSON.stringify(ledger) !== JSON.stringify(rec.ledger);
    if (changed) saveLedger(primaryRoot, rec.ledger);
    return { kind: "done", stale: rec.stale, foreign: rec.foreign, changed };
  });

  if (outcome.kind === "skip") {
    audit({
      mode: opts.mode,
      actor: "session_start",
      decision: "skipped",
      rule: WORKTREE_AUDIT.reconcileSkipped,
      subject: outcome.reason.slice(0, 200),
      origin: AUDIT_ORIGIN,
    });
    return {
      status: "skipped",
      reason: outcome.reason,
      stale: [],
      foreign: [],
      changed: false,
    };
  }

  audit({
    mode: opts.mode,
    actor: "session_start",
    decision: outcome.changed ? "reconciled" : "noop",
    rule: WORKTREE_AUDIT.reconcile,
    subject: `stale:${outcome.stale.length} foreign:${outcome.foreign.length}`,
    origin: AUDIT_ORIGIN,
  });
  return {
    status: "reconciled",
    stale: outcome.stale,
    foreign: outcome.foreign,
    changed: outcome.changed,
  };
}

// ── provisioning (pre-spawn, for `pi-code worktree create`) (FR-1/FR-3/FR-5) ──

export interface ProvisionInput {
  workerId: string;
  branch: string;
  base?: string;
  worktreePath?: string;
  tasks?: string[];
  areas?: string[];
  featureId?: string | null;
}

export interface ProvisionResult {
  ok: boolean;
  path?: string;
  errors?: string[];
  reason?: string;
}

/**
 * Provision a worker worktree + ledger record BEFORE the worker Pi is spawned.
 * Runs the manager's full validated create under the lock; on success returns
 * the resolved worktreePath the driver launches the worker in
 * (`cwd = worktreePath`). Never runs on a protected branch / outside the managed
 * root (the manager refuses).
 */
export function provisionWorktree(
  repoRoot: string,
  input: ProvisionInput,
  opts: { mode: string; now: string },
  _deps: LifecycleDeps = {},
): ProvisionResult {
  const worktreePath = input.worktreePath
    ? resolveWorktreePath(input.worktreePath)
    : defaultWorktreePath(repoRoot, input.workerId);
  const req: CreateRequest = {
    workerId: input.workerId,
    branch: input.branch,
    worktreePath,
    base: input.base,
    featureId: input.featureId ?? null,
    tasks: input.tasks ?? [],
    ownedAreas: input.areas ?? [],
  };

  const res = withLedgerLock(repoRoot, () => {
    const ledger = loadLedger(repoRoot);
    const r = createWorker(repoRoot, ledger, req, opts.now);
    if (r.ok) saveLedger(repoRoot, r.ledger);
    return r;
  });

  audit({
    mode: opts.mode,
    actor: "worktree.create",
    decision: res.ok ? "created" : "deny",
    rule: WORKTREE_AUDIT.create,
    subject: `${input.workerId}:${input.branch}`,
    origin: AUDIT_ORIGIN,
  });

  if (!res.ok) return { ok: false, errors: res.errors, reason: res.reason };
  return { ok: true, path: res.record?.worktreePath };
}

// ── explicit cleanup + list commands (FR-6) ──────────────────────────────────

export interface CleanupResult {
  ok: boolean;
  message: string;
}

/** `/cct:worktree cleanup <workerId> [--force]` — teardown, under the lock. */
export function worktreeCleanup(
  cwd: string,
  workerId: string,
  opts: { force?: boolean; mode: string },
  deps: LifecycleDeps = {},
): CleanupResult {
  const primaryRoot = primaryRepoRoot(cwd, deps) ?? cwd;
  const res = withLedgerLock(primaryRoot, () => {
    const ledger = loadLedger(primaryRoot);
    const r = cleanupWorker(primaryRoot, ledger, workerId, {
      force: opts.force,
    });
    if (r.ok) saveLedger(primaryRoot, r.ledger);
    return r;
  });

  audit({
    mode: opts.mode,
    actor: "cct:worktree",
    decision: res.ok ? (opts.force ? "override" : "cleanup") : "deny",
    rule: WORKTREE_AUDIT.cleanup,
    subject: workerId,
    origin: AUDIT_ORIGIN,
  });

  return {
    ok: res.ok,
    message: res.ok
      ? `cleaned worktree '${workerId}'${opts.force ? " (forced, audited)" : ""}`
      : `refused to clean '${workerId}': ${res.reason}`,
  };
}

/** `/cct:worktree list` — read-only ledger + live/foreign view. */
export function worktreeListReport(
  cwd: string,
  deps: LifecycleDeps = {},
): string {
  const primaryRoot = primaryRepoRoot(cwd, deps) ?? cwd;
  const ledger = loadLedger(primaryRoot);
  const live = (deps.listWorktrees ?? listWorktrees)(primaryRoot);
  const tracked = new Set(ledger.workers.map((w) => w.worktreePath));
  const foreign = live.filter((w) => !w.isPrimary && !tracked.has(w.path));

  const lines = [`=== worktrees (primary: ${primaryRoot}) ===`];
  if (ledger.workers.length === 0) lines.push("ledger: (no workers recorded)");
  for (const w of ledger.workers) {
    const gone = !fs.existsSync(w.worktreePath);
    lines.push(
      `  ${w.workerId}  [${w.cleanupStatus}${gone ? ",missing" : ""}]  ` +
        `${w.branch}  merge:${w.mergeStatus}  ${w.worktreePath}`,
    );
  }
  for (const f of foreign) {
    lines.push(`  (foreign) ${f.branch ?? "<detached>"}  ${f.path}`);
  }
  return lines.join("\n");
}
