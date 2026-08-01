/**
 * Worktree manager for parallel workers (T7.3, FR-013).
 *
 * git worktree is a real, verifiable CLI, so T7.3 enforces the isolation +
 * lifecycle for real (contrast T7.2's mocked pi). Split like T7.2: pure
 * planners + a thin `git worktree` exec layer, over a versioned, sanitized
 * ledger at `.cct/worktrees.json`.
 *
 * T7.3 owns: isolated worktree creation (own branch, never master/main), the
 * tracked state, ownership CONFLICT DETECTION, and safe cleanup / stale
 * recovery. It does NOT run verification (T7.4) or execute merges (T8) — it
 * tracks their status — and it does NOT enforce write-time ownership (that is
 * the permission layer). The `origin:"cct"` marker is the hard deletion
 * boundary: only worktrees CCT created + recorded are ever removable; a foreign
 * worktree is reported, never touched. The manager never issues force/reset/
 * branch-force-delete. See specs/pi-harness-adoption/design-t73-worktree-manager.md.
 */

import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as path from "node:path";

export const WORKTREE_LEDGER_VERSION = 1;
export const WORKTREE_LEDGER_REL = path.join(".cct", "worktrees.json");

/** Branches a worker may never be created on / removed as. */
export const PROTECTED_BRANCHES = new Set(["master", "main"]);

export type VerificationStatus = "pending" | "passed" | "failed";
export type MergeStatus = "unmerged" | "merged" | "abandoned";
export type CleanupStatus = "active" | "cleaned" | "stale";

export interface WorkerRecord {
  workerId: string;
  branch: string;
  worktreePath: string;
  featureId: string | null;
  tasks: string[];
  ownedAreas: string[];
  verificationStatus: VerificationStatus;
  mergeStatus: MergeStatus;
  cleanupStatus: CleanupStatus;
  createdAt: string;
  /** Provenance — only "cct" records are cleanable. Hard deletion boundary. */
  origin: "cct";
}

export interface WorktreeLedger {
  version: number;
  workers: WorkerRecord[];
}

const ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const BRANCH_RE = /^[A-Za-z0-9._][A-Za-z0-9._/-]*$/;
const MAX_ID = 64;
const MAX_BRANCH = 200;
const MAX_FEATURE_ID = 128;
const MAX_AREA = 256;
const MAX_AREAS = 64;
const MAX_TASKS = 128;

const VERIFICATION: VerificationStatus[] = ["pending", "passed", "failed"];
const MERGE: MergeStatus[] = ["unmerged", "merged", "abandoned"];
const CLEANUP: CleanupStatus[] = ["active", "cleaned", "stale"];

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

/** Strip a leading `./` and trailing glob/slash so areas compare as prefixes. */
export function normalizeArea(area: string): string {
  let a = sanitizeText(area, MAX_AREA);
  if (a.startsWith("./")) a = a.slice(2);
  a = a.replace(/\/+$/, "").replace(/\/\*+$/, "");
  return a;
}

/** Two owned areas overlap if either is a path-prefix of (or equal to) the other. */
export function areasOverlap(a: string, b: string): boolean {
  const x = normalizeArea(a);
  const y = normalizeArea(b);
  if (!x || !y) return false;
  if (x === y) return true;
  return y.startsWith(x + "/") || x.startsWith(y + "/");
}

// ── pure planners ────────────────────────────────────────────────────────────

export interface CreateRequest {
  workerId: string;
  branch: string;
  worktreePath: string;
  base?: string;
  featureId?: string | null;
  tasks?: string[];
  ownedAreas?: string[];
}

export interface Validation {
  valid: boolean;
  errors: string[];
}

/** Validate a create request against the current ledger (uniqueness + overlap). */
export function validateCreateRequest(
  req: CreateRequest,
  ledger: WorktreeLedger,
): Validation {
  const errors: string[] = [];
  const active = ledger.workers.filter((w) => w.cleanupStatus === "active");

  if (
    !req.workerId ||
    !ID_RE.test(req.workerId) ||
    req.workerId.length > MAX_ID
  )
    errors.push(
      `workerId '${req.workerId}' must be kebab-case (<=${MAX_ID} chars)`,
    );
  else if (active.some((w) => w.workerId === req.workerId))
    errors.push(`workerId '${req.workerId}' is already active`);

  const branch = (req.branch || "").trim();
  if (!branch || !BRANCH_RE.test(branch) || branch.length > MAX_BRANCH)
    errors.push(`branch '${req.branch}' is not a valid branch name`);
  else if (PROTECTED_BRANCHES.has(branch.toLowerCase()))
    errors.push(`refusing to create a worker on protected branch '${branch}'`);
  else if (active.some((w) => w.branch === branch))
    errors.push(`branch '${branch}' is already in use by an active worker`);

  if (!req.worktreePath || !path.isAbsolute(req.worktreePath))
    errors.push("worktreePath must be an absolute path");
  else if (active.some((w) => w.worktreePath === req.worktreePath))
    errors.push(`worktreePath '${req.worktreePath}' is already in use`);

  if (
    req.base &&
    PROTECTED_BRANCHES.has(req.base.toLowerCase()) === false &&
    !BRANCH_RE.test(req.base)
  )
    errors.push(`base '${req.base}' is not a valid ref`);

  const areas = (req.ownedAreas ?? []).map(normalizeArea).filter(Boolean);
  for (const w of active) {
    for (const mine of areas) {
      for (const theirs of w.ownedAreas) {
        if (areasOverlap(mine, theirs))
          errors.push(
            `owned area '${mine}' overlaps worker '${w.workerId}' area '${theirs}'`,
          );
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

export interface OwnershipConflict {
  a: string;
  b: string;
  area: string;
}

/** All overlapping owned-area pairs among ACTIVE workers. */
export function detectOwnershipConflicts(
  ledger: WorktreeLedger,
): OwnershipConflict[] {
  const active = ledger.workers.filter((w) => w.cleanupStatus === "active");
  const conflicts: OwnershipConflict[] = [];
  for (let i = 0; i < active.length; i++) {
    for (let j = i + 1; j < active.length; j++) {
      for (const x of active[i].ownedAreas) {
        for (const y of active[j].ownedAreas) {
          if (areasOverlap(x, y))
            conflicts.push({
              a: active[i].workerId,
              b: active[j].workerId,
              area: normalizeArea(x),
            });
        }
      }
    }
  }
  return conflicts;
}

export interface CleanupDecision {
  eligible: boolean;
  reason: string;
}

/**
 * Decide whether a worker's worktree may be removed. Non-forced removal
 * requires ALL of: origin cct, clean tree, merged/abandoned, not primary.
 * `force` waives clean + merge ONLY — never origin or primary.
 */
export function cleanupEligibility(
  record: WorkerRecord | undefined,
  ctx: { isClean: boolean; isPrimary: boolean; force?: boolean },
): CleanupDecision {
  if (!record)
    return { eligible: false, reason: "no such worker in the ledger" };
  if (record.origin !== "cct")
    return {
      eligible: false,
      reason: "refusing to remove a non-CCT (foreign) worktree",
    };
  if (ctx.isPrimary)
    return {
      eligible: false,
      reason: "refusing to remove the primary worktree",
    };
  if (ctx.force) return { eligible: true, reason: "forced removal (audited)" };
  if (!ctx.isClean)
    return {
      eligible: false,
      reason: "worktree is dirty — commit/stash or force",
    };
  if (record.mergeStatus === "unmerged")
    return {
      eligible: false,
      reason: "work is unmerged — merge/abandon or force",
    };
  return { eligible: true, reason: "clean and merged/abandoned" };
}

export interface Reconciliation {
  ledger: WorktreeLedger;
  stale: string[]; // workerIds whose worktree dir is gone
  foreign: string[]; // live worktree paths not tracked in the ledger
}

/**
 * Reconcile the ledger against the live worktree paths: a tracked record whose
 * dir is gone -> marked `stale`; a live worktree not in the ledger -> reported
 * `foreign` (NEVER auto-removed).
 */
export function reconcile(
  ledger: WorktreeLedger,
  liveWorktreePaths: string[],
): Reconciliation {
  const live = new Set(liveWorktreePaths);
  const tracked = new Set(ledger.workers.map((w) => w.worktreePath));
  const stale: string[] = [];
  const workers = ledger.workers.map((w) => {
    if (w.cleanupStatus === "active" && !live.has(w.worktreePath)) {
      stale.push(w.workerId);
      return { ...w, cleanupStatus: "stale" as CleanupStatus };
    }
    return w;
  });
  const foreign = liveWorktreePaths.filter((p) => !tracked.has(p));
  return { ledger: { ...ledger, workers }, stale, foreign };
}

// ── ledger I/O (versioned, tamper-safe) ──────────────────────────────────────

export function emptyLedger(): WorktreeLedger {
  return { version: WORKTREE_LEDGER_VERSION, workers: [] };
}

function sanitizeRecord(raw: unknown): WorkerRecord | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  const workerId = sanitizeText(r.workerId, MAX_ID);
  const branch = sanitizeText(r.branch, MAX_BRANCH);
  if (!workerId || !ID_RE.test(workerId)) return null;
  if (!branch || !BRANCH_RE.test(branch)) return null;
  const worktreePath = typeof r.worktreePath === "string" ? r.worktreePath : "";
  if (!path.isAbsolute(worktreePath)) return null;
  const arr = (v: unknown, max: number, cap: number): string[] =>
    Array.isArray(v)
      ? v
          .filter((x) => typeof x === "string")
          .map((x) => sanitizeText(x, max))
          .filter(Boolean)
          .slice(0, cap)
      : [];
  const pick = <T extends string>(v: unknown, allowed: T[], fallback: T): T =>
    typeof v === "string" && (allowed as string[]).includes(v)
      ? (v as T)
      : fallback;
  return {
    workerId,
    branch,
    worktreePath,
    featureId: sanitizeText(r.featureId, MAX_FEATURE_ID) || null,
    tasks: arr(r.tasks, MAX_FEATURE_ID, MAX_TASKS),
    ownedAreas: arr(r.ownedAreas, MAX_AREA, MAX_AREAS).map(normalizeArea),
    verificationStatus: pick(r.verificationStatus, VERIFICATION, "pending"),
    mergeStatus: pick(r.mergeStatus, MERGE, "unmerged"),
    cleanupStatus: pick(r.cleanupStatus, CLEANUP, "active"),
    createdAt: sanitizeText(r.createdAt, 40),
    origin: "cct",
  };
}

export function loadLedger(projectRoot: string): WorktreeLedger {
  const file = path.join(projectRoot, WORKTREE_LEDGER_REL);
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    if (typeof parsed !== "object" || parsed === null) return emptyLedger();
    const rawWorkers: unknown[] = Array.isArray(parsed.workers)
      ? parsed.workers
      : [];
    const workers = rawWorkers
      .map(sanitizeRecord)
      .filter((w: WorkerRecord | null): w is WorkerRecord => !!w);
    return { version: WORKTREE_LEDGER_VERSION, workers };
  } catch {
    return emptyLedger();
  }
}

export function saveLedger(projectRoot: string, ledger: WorktreeLedger): void {
  const file = path.join(projectRoot, WORKTREE_LEDGER_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(
    file,
    JSON.stringify({ ...ledger, version: WORKTREE_LEDGER_VERSION }, null, 2) +
      "\n",
  );
}

// ── thin git-exec layer ──────────────────────────────────────────────────────

/**
 * Canonicalize a worktree path so it compares equal to what `git worktree list`
 * reports (git returns realpath'd paths; on macOS /var is a symlink to
 * /private/var). Resolves the leaf when it exists, else the parent + basename,
 * so it works both before and after creation. Path matching in cleanupWorker /
 * reconcile depends on this.
 */
export function resolveWorktreePath(p: string): string {
  try {
    return fs.realpathSync(p);
  } catch {
    try {
      return path.join(fs.realpathSync(path.dirname(p)), path.basename(p));
    } catch {
      return p;
    }
  }
}

function git(
  repoRoot: string,
  args: string[],
): { code: number; stdout: string; stderr: string } {
  const r = spawnSync("git", ["-C", repoRoot, ...args], { encoding: "utf8" });
  return {
    code: r.status ?? 1,
    stdout: r.stdout ?? "",
    stderr: r.stderr ?? "",
  };
}

export interface LiveWorktree {
  path: string;
  branch: string | null;
  isPrimary: boolean;
}

/** Parse `git worktree list --porcelain`. The first block is the primary. */
export function listWorktrees(repoRoot: string): LiveWorktree[] {
  const { code, stdout } = git(repoRoot, ["worktree", "list", "--porcelain"]);
  if (code !== 0) return [];
  const out: LiveWorktree[] = [];
  let cur: Partial<LiveWorktree> | null = null;
  for (const line of stdout.split("\n")) {
    if (line.startsWith("worktree ")) {
      if (cur?.path)
        out.push({
          path: cur.path,
          branch: cur.branch ?? null,
          isPrimary: out.length === 0,
        });
      cur = { path: line.slice("worktree ".length).trim(), branch: null };
    } else if (line.startsWith("branch ") && cur) {
      cur.branch = line
        .slice("branch ".length)
        .trim()
        .replace(/^refs\/heads\//, "");
    }
  }
  if (cur?.path)
    out.push({
      path: cur.path,
      branch: cur.branch ?? null,
      isPrimary: out.length === 0,
    });
  return out;
}

/** Clean iff `git status --porcelain` is empty ignoring untracked `.cct/`. */
export function isWorktreeClean(worktreePath: string): boolean {
  const r = spawnSync("git", ["-C", worktreePath, "status", "--porcelain"], {
    encoding: "utf8",
  });
  if ((r.status ?? 1) !== 0) return false;
  const dirty = (r.stdout ?? "")
    .split("\n")
    .filter((l) => l.trim() && !/^\?\? \.cct\//.test(l));
  return dirty.length === 0;
}

export interface GitOpResult {
  ok: boolean;
  reason?: string;
}

/** Create an isolated worktree on a NEW branch. Never on a protected branch. */
export function createWorktree(
  repoRoot: string,
  worktreePath: string,
  branch: string,
  base?: string,
): GitOpResult {
  if (PROTECTED_BRANCHES.has(branch.toLowerCase()))
    return {
      ok: false,
      reason: `refusing to create on protected branch '${branch}'`,
    };
  const args = ["worktree", "add", worktreePath, "-b", branch];
  if (base) args.push(base);
  const { code, stderr } = git(repoRoot, args);
  return code === 0 ? { ok: true } : { ok: false, reason: stderr.trim() };
}

/**
 * Remove a worktree. `force` maps to `git worktree remove --force` (used ONLY
 * after cleanupEligibility approved a forced removal). No reset, no branch -D.
 */
export function removeWorktree(
  repoRoot: string,
  worktreePath: string,
  opts: { force?: boolean } = {},
): GitOpResult {
  const args = ["worktree", "remove", worktreePath];
  if (opts.force) args.push("--force");
  const { code, stderr } = git(repoRoot, args);
  return code === 0 ? { ok: true } : { ok: false, reason: stderr.trim() };
}

/** Prune administrative records for worktrees whose directories are gone. */
export function pruneWorktrees(repoRoot: string): GitOpResult {
  const { code, stderr } = git(repoRoot, ["worktree", "prune"]);
  return code === 0 ? { ok: true } : { ok: false, reason: stderr.trim() };
}

// ── orchestration (compose validate + git + ledger) ──────────────────────────

export interface WorkerOpResult {
  ok: boolean;
  ledger: WorktreeLedger;
  record?: WorkerRecord;
  errors?: string[];
  reason?: string;
}

/**
 * Validate a create request, create the isolated worktree, and record it. On
 * any validation or git failure the ledger is returned unchanged (fail-closed).
 * `nowIso` is injected for deterministic, testable timestamps.
 */
export function createWorker(
  repoRoot: string,
  ledger: WorktreeLedger,
  req: CreateRequest,
  nowIso: string,
): WorkerOpResult {
  const v = validateCreateRequest(req, ledger);
  if (!v.valid) return { ok: false, ledger, errors: v.errors };

  const created = createWorktree(
    repoRoot,
    req.worktreePath,
    req.branch,
    req.base,
  );
  if (!created.ok) return { ok: false, ledger, reason: created.reason };

  const record: WorkerRecord = {
    workerId: req.workerId,
    branch: req.branch,
    worktreePath: resolveWorktreePath(req.worktreePath),
    featureId:
      (req.featureId && sanitizeText(req.featureId, MAX_FEATURE_ID)) || null,
    tasks: (req.tasks ?? [])
      .map((t) => sanitizeText(t, MAX_FEATURE_ID))
      .filter(Boolean),
    ownedAreas: (req.ownedAreas ?? []).map(normalizeArea).filter(Boolean),
    verificationStatus: "pending",
    mergeStatus: "unmerged",
    cleanupStatus: "active",
    createdAt: nowIso,
    origin: "cct",
  };
  return {
    ok: true,
    ledger: { ...ledger, workers: [...ledger.workers, record] },
    record,
  };
}

/** Update the tracked verification status of a worker (set by T7.4). */
export function setVerificationStatus(
  ledger: WorktreeLedger,
  workerId: string,
  status: VerificationStatus,
): WorktreeLedger {
  return {
    ...ledger,
    workers: ledger.workers.map((w) =>
      w.workerId === workerId ? { ...w, verificationStatus: status } : w,
    ),
  };
}

/** Update the tracked merge status of a worker (set by T8). */
export function setMergeStatus(
  ledger: WorktreeLedger,
  workerId: string,
  status: MergeStatus,
): WorktreeLedger {
  return {
    ...ledger,
    workers: ledger.workers.map((w) =>
      w.workerId === workerId ? { ...w, mergeStatus: status } : w,
    ),
  };
}

/**
 * Remove a worker's worktree if eligible, then mark it cleaned. Enforces every
 * safety rule via cleanupEligibility (origin/primary/clean/merge). Never issues
 * force/reset unless `force` was explicitly requested AND eligibility approved
 * it (which still refuses foreign/primary worktrees).
 */
export function cleanupWorker(
  repoRoot: string,
  ledger: WorktreeLedger,
  workerId: string,
  opts: { force?: boolean } = {},
): WorkerOpResult {
  const record = ledger.workers.find((w) => w.workerId === workerId);
  const live = listWorktrees(repoRoot);
  const match = record
    ? live.find((l) => l.path === record.worktreePath)
    : undefined;
  const decision = cleanupEligibility(record, {
    isClean: record ? isWorktreeClean(record.worktreePath) : false,
    isPrimary: match?.isPrimary ?? false,
    force: opts.force,
  });
  if (!decision.eligible) return { ok: false, ledger, reason: decision.reason };

  const removed = removeWorktree(repoRoot, record!.worktreePath, {
    force: opts.force,
  });
  if (!removed.ok) return { ok: false, ledger, reason: removed.reason };

  return {
    ok: true,
    ledger: {
      ...ledger,
      workers: ledger.workers.map((w) =>
        w.workerId === workerId ? { ...w, cleanupStatus: "cleaned" } : w,
      ),
    },
    record,
  };
}
