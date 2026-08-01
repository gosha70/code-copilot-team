// worktree-git.test.mjs — T7.3 thin git-exec + orchestration against a REAL
// throwaway git repo (FR-013). Run via tests/test-pi-runtime.sh. git is
// available in CI, so the isolation/cleanup/reconcile safety is genuinely
// verified, not mocked.

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  cleanupWorker,
  createWorker,
  emptyLedger,
  isWorktreeClean,
  listWorktrees,
  reconcile,
  setMergeStatus,
} from "../../adapters/pi/runtime/agents/worktree.ts";

const HAS_GIT = spawnSync("git", ["--version"], { encoding: "utf8" }).status === 0;
const NOW = "2026-07-31T00:00:00Z";

function initRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-wt-repo-"));
  const g = (args) => spawnSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  g(["init", "-q", "-b", "master"]);
  g(["config", "user.email", "t@example.com"]);
  g(["config", "user.name", "T"]);
  fs.writeFileSync(path.join(dir, "README.md"), "seed\n");
  g(["add", "-A"]);
  g(["commit", "-q", "-m", "seed"]);
  return dir;
}

const wtPath = (repo, name) => path.join(path.dirname(repo), path.basename(repo) + "-" + name);

test("createWorker makes a real isolated worktree on a new branch", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const p = wtPath(repo, "w1");
  const res = createWorker(repo, emptyLedger(), {
    workerId: "w1", branch: "feature/w1", worktreePath: p, ownedAreas: ["src/a"],
  }, NOW);
  assert.equal(res.ok, true, res.reason || (res.errors || []).join("; "));
  assert.ok(fs.existsSync(p), "worktree dir exists");
  const live = listWorktrees(repo);
  // record.worktreePath is realpath-normalized to match git's output.
  const mine = live.find((l) => l.path === res.record.worktreePath);
  assert.ok(mine, "worktree appears in git worktree list");
  assert.equal(mine.branch, "feature/w1");
  assert.equal(mine.isPrimary, false);
  assert.equal(res.record.origin, "cct");
});

test("createWorker refuses a protected branch and never calls git", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const before = listWorktrees(repo).length;
  const res = createWorker(repo, emptyLedger(), {
    workerId: "wm", branch: "master", worktreePath: wtPath(repo, "wm"),
  }, NOW);
  assert.equal(res.ok, false);
  assert.ok(res.errors.some((e) => /protected branch/.test(e)));
  assert.equal(listWorktrees(repo).length, before, "no worktree created");
});

test("cleanupWorker refuses unmerged work, then succeeds once merged", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const p = wtPath(repo, "w2");
  let { ledger } = createWorker(repo, emptyLedger(), {
    workerId: "w2", branch: "feature/w2", worktreePath: p,
  }, NOW);

  const refused = cleanupWorker(repo, ledger, "w2");
  assert.equal(refused.ok, false);
  assert.ok(/unmerged/.test(refused.reason));
  assert.ok(fs.existsSync(p), "worktree not removed while unmerged");

  ledger = setMergeStatus(ledger, "w2", "merged");
  const ok = cleanupWorker(repo, ledger, "w2");
  assert.equal(ok.ok, true, ok.reason);
  assert.ok(!fs.existsSync(p), "worktree removed after merge");
  assert.equal(ok.ledger.workers.find((w) => w.workerId === "w2").cleanupStatus, "cleaned");
});

test("cleanupWorker refuses a dirty worktree unless forced", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const p = wtPath(repo, "w3");
  let { ledger } = createWorker(repo, emptyLedger(), {
    workerId: "w3", branch: "feature/w3", worktreePath: p,
  }, NOW);
  ledger = setMergeStatus(ledger, "w3", "merged");
  fs.writeFileSync(path.join(p, "dirty.txt"), "uncommitted\n");
  assert.equal(isWorktreeClean(p), false);

  const refused = cleanupWorker(repo, ledger, "w3");
  assert.equal(refused.ok, false);
  assert.ok(/dirty/.test(refused.reason));
  assert.ok(fs.existsSync(p), "dirty worktree preserved");

  const forced = cleanupWorker(repo, ledger, "w3", { force: true });
  assert.equal(forced.ok, true, forced.reason);
  assert.ok(!fs.existsSync(p));
});

test("an untracked .cct/ file does not make a worktree dirty", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const p = wtPath(repo, "w4");
  createWorker(repo, emptyLedger(), { workerId: "w4", branch: "feature/w4", worktreePath: p }, NOW);
  fs.mkdirSync(path.join(p, ".cct"), { recursive: true });
  fs.writeFileSync(path.join(p, ".cct", "scratch.json"), "{}\n");
  assert.equal(isWorktreeClean(p), true, ".cct/ untracked is ignored by the clean check");
});

test("cleanupWorker refuses an unknown / foreign worker id", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const res = cleanupWorker(repo, emptyLedger(), "nobody");
  assert.equal(res.ok, false);
  assert.ok(/no such worker/.test(res.reason));
});

test("reconcile marks a vanished worktree stale (real git list)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const p = wtPath(repo, "w5");
  const { ledger } = createWorker(repo, emptyLedger(), {
    workerId: "w5", branch: "feature/w5", worktreePath: p,
  }, NOW);
  // Remove the worktree dir out-of-band (as if a user rm-rf'd it).
  fs.rmSync(p, { recursive: true, force: true });
  // "Live" = non-primary worktrees whose dir still exists (git may still list
  // a removed-but-unpruned worktree; existence is the real signal).
  const livePaths = listWorktrees(repo)
    .filter((l) => !l.isPrimary && fs.existsSync(l.path))
    .map((l) => l.path);
  const { ledger: next, stale } = reconcile(ledger, livePaths);
  assert.deepEqual(stale, ["w5"]);
  assert.equal(next.workers.find((w) => w.workerId === "w5").cleanupStatus, "stale");
});

test("reconcile reports a foreign worktree it did not create (never touches it)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const foreign = wtPath(repo, "foreign");
  // A worktree created directly, outside the manager/ledger.
  spawnSync("git", ["-C", repo, "worktree", "add", "-q", foreign, "-b", "feature/foreign"], { encoding: "utf8" });
  const livePaths = listWorktrees(repo)
    .filter((l) => !l.isPrimary && fs.existsSync(l.path))
    .map((l) => l.path);
  const { foreign: reported } = reconcile(emptyLedger(), livePaths);
  // git reports realpath'd paths (macOS /var -> /private/var).
  assert.ok(reported.includes(fs.realpathSync(foreign)), "foreign worktree reported");
  assert.ok(fs.existsSync(foreign), "foreign worktree left intact");
});
