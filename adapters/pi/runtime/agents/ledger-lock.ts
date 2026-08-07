/**
 * Repo-scoped ledger lock with pid/token ownership (extracted from
 * worktree-lifecycle.ts so both the worktree ledger and the team ledger share
 * one proven implementation; issue #185 / Slice A of #174).
 *
 * The lock is an atomic `mkdir` of `.cct/<name>.lock` plus an `owner.json`
 * recording `{pid, token}`. On contention it retries within a bounded timeout
 * and, on timeout, FAILS CLOSED by throwing. A lock is reclaimed only when its
 * owner is provably NOT alive (crashed), or — when liveness cannot be determined
 * — after `staleMs`; a slow-but-live owner's lock is never stolen. On release the
 * lock is removed only if THIS call still owns the recorded token. Every ledger
 * mutation runs its full `load → validate → op → save` inside this critical
 * section.
 *
 * `lockName` is a CONSTRAINED union (not a free string) so a caller can never
 * pass a path-shaped name, and error messages name the right ledger.
 */

import * as fs from "node:fs";
import * as path from "node:path";

/** The ledgers that have a lock. Constrained union — no path-shaped names. */
export type LedgerLockName = "worktrees" | "team";

const LOCK_OWNER_FILE = "owner.json";
const DEFAULT_LOCK_TIMEOUT_MS = 5000;
const DEFAULT_LOCK_STALE_MS = 60_000;
const LOCK_RETRY_MS = 50;

export interface LockOptions {
  /** Which ledger's lock to take. Defaults to "worktrees" (back-compat). */
  lockName?: LedgerLockName;
  timeoutMs?: number;
  staleMs?: number;
}

interface LockOwner {
  pid: number;
  token: string;
  ts: number;
}

/** Block the thread without spinning (legitimate in a CLI / short startup wait). */
function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/**
 * Liveness of a pid: true (alive / exists), false (gone), undefined (unknown /
 * unsupported). Used so a stale lock is reclaimed ONLY when its owner is not
 * alive — a slow but live holder never has its lock stolen.
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

/**
 * Run `fn` while holding the repo-scoped `.cct/<lockName>.lock`. See the module
 * header for the ownership/reclaim contract.
 */
export function withLedgerLock<T>(
  repoRoot: string,
  fn: () => T,
  opts: LockOptions = {},
): T {
  const lockName: LedgerLockName = opts.lockName ?? "worktrees";
  const timeoutMs = opts.timeoutMs ?? DEFAULT_LOCK_TIMEOUT_MS;
  const staleMs = opts.staleMs ?? DEFAULT_LOCK_STALE_MS;
  const lockDir = path.join(repoRoot, ".cct", `${lockName}.lock`);
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
          `could not acquire ${lockName} ledger lock at ${lockDir} within ${timeoutMs}ms`,
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
