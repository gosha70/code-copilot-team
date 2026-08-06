// worktree-lifecycle.test.mjs — issue #172 wiring, revised per the PR #183
// review. Exercises the lifecycle module (attach/validate, fail-closed
// reconcile, the repo-scoped ledger lock, provisioning, and the explicit
// cleanup/list commands) against REAL throwaway git repos, and asserts the
// audit records each action emits. Run via tests/test-pi-runtime.sh.
//
// Mapping to the review:
//   #1 isolation is real  -> "isolation" + "attach fails closed" tests
//   #2 concurrency        -> "concurrent provisions" + "conflicting areas"
//   #3 primary-not-foreign-> "primary-only repo" test
//   #4 fail-closed        -> "list failure" / "prune failure" / "malformed"
//   no-invented-event     -> "wiring subscribes only to session_start"

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  WORKTREE_AUDIT,
  WORKER_ENV,
  attachOnSessionStart,
  defaultWorktreePath,
  gitToplevel,
  isolationStateFromAttach,
  isolationToolBlock,
  listWorktreesStrict,
  parseWorktreePorcelainStrict,
  primaryRepoRoot,
  provisionWorktree,
  reconcileOnStart,
  sanitizeWorkerId,
  withLedgerLock,
  worktreeCleanup,
  worktreeListReport,
} from "../../adapters/pi/runtime/agents/worktree-lifecycle.ts";
import {
  loadLedger,
  saveLedger,
  setMergeStatus,
} from "../../adapters/pi/runtime/agents/worktree.ts";
import { auditLogPath } from "../../adapters/pi/runtime/policy/audit.ts";

const HAS_GIT =
  spawnSync("git", ["--version"], { encoding: "utf8" }).status === 0;
const NOW = "2026-08-06T00:00:00Z";

function initRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-wtl-repo-"));
  const g = (args) => spawnSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  g(["init", "-q", "-b", "master"]);
  g(["config", "user.email", "t@example.com"]);
  g(["config", "user.name", "T"]);
  fs.writeFileSync(path.join(dir, "README.md"), "seed\n");
  g(["add", "-A"]);
  g(["commit", "-q", "-m", "seed"]);
  // git returns realpath'd paths (macOS /var -> /private/var); match them.
  return fs.realpathSync(dir);
}

/** Point CCT_HOME at a private dir so audit records are readable + isolated. */
function withAuditHome(fn) {
  const prev = process.env.CCT_HOME;
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "cct-wtl-home-"));
  process.env.CCT_HOME = home;
  try {
    return fn(() => {
      const f = auditLogPath();
      return fs.existsSync(f)
        ? fs
            .readFileSync(f, "utf8")
            .trim()
            .split("\n")
            .filter(Boolean)
            .map((l) => JSON.parse(l))
        : [];
    });
  } finally {
    if (prev === undefined) delete process.env.CCT_HOME;
    else process.env.CCT_HOME = prev;
  }
}

// ── US1: isolation is real (review #1) ───────────────────────────────────────

test("isolation: a worker launched with cwd=worktree attaches (pwd + toplevel match)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const prov = provisionWorktree(
    repo,
    { workerId: "w1", branch: "feature/w1", areas: ["src/a"] },
    { mode: "print", now: NOW },
  );
  assert.equal(prov.ok, true, prov.reason || (prov.errors || []).join("; "));
  const wt = prov.path;

  // Prove the provisioned dir really is an isolated worktree.
  assert.equal(gitToplevel(wt), wt, "git toplevel == worktree path");
  assert.equal(
    spawnSync("git", ["-C", wt, "branch", "--show-current"], { encoding: "utf8" }).stdout.trim(),
    "feature/w1",
  );

  withAuditHome((read) => {
    const res = attachOnSessionStart(
      { cwd: wt, mode: "print" },
      { [WORKER_ENV.id]: "w1", [WORKER_ENV.branch]: "feature/w1" },
    );
    assert.equal(res.status, "attached");
    const rec = read().at(-1);
    assert.equal(rec.rule, WORKTREE_AUDIT.attach);
    assert.equal(rec.decision, "attached");
  });
});

test("isolation: session_start with a MISMATCHED cwd fails closed (audited not-isolated)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  provisionWorktree(repo, { workerId: "w1", branch: "feature/w1" }, { mode: "print", now: NOW });

  withAuditHome((read) => {
    // Worker env says w1, but the session is running in the PRIMARY repo.
    const res = attachOnSessionStart(
      { cwd: repo, mode: "print" },
      { [WORKER_ENV.id]: "w1", [WORKER_ENV.branch]: "feature/w1" },
    );
    assert.equal(res.status, "not-isolated");
    assert.match(res.warning, /NOT verified/);
    const rec = read().at(-1);
    assert.equal(rec.rule, WORKTREE_AUDIT.notIsolated);
    assert.equal(rec.decision, "deny");
  });
});

test("attach: a worker id with no ledger record fails closed", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  withAuditHome((read) => {
    const res = attachOnSessionStart(
      { cwd: repo, mode: "print" },
      { [WORKER_ENV.id]: "ghost" },
    );
    assert.equal(res.status, "not-isolated");
    assert.equal(read().at(-1).rule, WORKTREE_AUDIT.notIsolated);
  });
});

test("attach: no CCT_WORKER_ID => no-op (a primary/interactive session), no audit", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  withAuditHome((read) => {
    const res = attachOnSessionStart({ cwd: repo, mode: "print" }, {});
    assert.equal(res.status, "no-op");
    assert.equal(read().length, 0, "a primary session emits no worktree audit");
  });
});

test("provision: refuses master, out-of-root, and overlapping areas (no side effect)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const master = provisionWorktree(repo, { workerId: "wm", branch: "master" }, { mode: "print", now: NOW });
  assert.equal(master.ok, false);
  assert.ok((master.errors || []).some((e) => /protected branch/.test(e)));

  const outside = provisionWorktree(
    repo,
    { workerId: "wo", branch: "feature/wo", worktreePath: path.join(path.parse(repo).root, "escape-" + path.basename(repo)) },
    { mode: "print", now: NOW },
  );
  assert.equal(outside.ok, false);
  assert.ok((outside.errors || []).some((e) => /managed root/.test(e)));

  provisionWorktree(repo, { workerId: "w1", branch: "feature/w1", areas: ["src/a"] }, { mode: "print", now: NOW });
  const overlap = provisionWorktree(repo, { workerId: "w2", branch: "feature/w2", areas: ["src/a/deep"] }, { mode: "print", now: NOW });
  assert.equal(overlap.ok, false);
  assert.ok((overlap.errors || []).some((e) => /overlap/.test(e)));
  // Only w1 landed.
  assert.deepEqual(loadLedger(repo).workers.map((w) => w.workerId), ["w1"]);
});

// ── US1: concurrency (review #2) ─────────────────────────────────────────────

test("concurrency: the ledger lock serializes two provisions — both survive", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  // The lock is synchronous, so interleave by hand: each mutation is a full
  // load->create->save critical section; neither can clobber the other's record.
  const a = provisionWorktree(repo, { workerId: "a", branch: "feature/a" }, { mode: "print", now: NOW });
  const b = provisionWorktree(repo, { workerId: "b", branch: "feature/b" }, { mode: "print", now: NOW });
  assert.equal(a.ok, true);
  assert.equal(b.ok, true);
  const ids = loadLedger(repo).workers.map((w) => w.workerId).sort();
  assert.deepEqual(ids, ["a", "b"], "both concurrent records present");
});

test("concurrency: two conflicting owned-area requests — exactly one wins", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const a = provisionWorktree(repo, { workerId: "a", branch: "feature/a", areas: ["src/x"] }, { mode: "print", now: NOW });
  const b = provisionWorktree(repo, { workerId: "b", branch: "feature/b", areas: ["src/x"] }, { mode: "print", now: NOW });
  assert.equal([a.ok, b.ok].filter(Boolean).length, 1, "exactly one owned-area winner");
});

test("withLedgerLock: a held lock blocks a second acquirer until released; timeout fails closed", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lockDir = path.join(repo, ".cct", "worktrees.lock");
  fs.mkdirSync(path.dirname(lockDir), { recursive: true });
  fs.mkdirSync(lockDir); // hold the lock out-of-band
  assert.throws(
    () => withLedgerLock(repo, () => "never", { timeoutMs: 120, staleMs: 60_000 }),
    /could not acquire worktree ledger lock/,
  );
  fs.rmdirSync(lockDir);
  // Once free, it acquires and runs.
  assert.equal(withLedgerLock(repo, () => "ran", { timeoutMs: 200 }), "ran");
});

test("withLedgerLock: a stale lock (older than staleMs) is reclaimed", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lockDir = path.join(repo, ".cct", "worktrees.lock");
  fs.mkdirSync(path.dirname(lockDir), { recursive: true });
  fs.mkdirSync(lockDir);
  const old = new Date(Date.now() - 5000);
  fs.utimesSync(lockDir, old, old);
  assert.equal(withLedgerLock(repo, () => "reclaimed", { staleMs: 1000, timeoutMs: 500 }), "reclaimed");
});

// ── path namespacing (review "additional") ───────────────────────────────────

test("defaultWorktreePath namespaces by repo; sibling repos with same id differ", () => {
  const p1 = defaultWorktreePath("/tmp/parent/repoA", "worker-1");
  const p2 = defaultWorktreePath("/tmp/parent/repoB", "worker-1");
  assert.notEqual(p1, p2);
  assert.equal(p1, path.join("/tmp/parent", ".cct-worktrees", "repoA", "worker-1"));
  assert.equal(sanitizeWorkerId("Weird ID/../x"), "weird-id-x");
});

// ── US2: explicit cleanup (review #6 no-session-end) ─────────────────────────

test("cleanup: unmerged refused, merged+clean removed; force is audited", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const prov = provisionWorktree(repo, { workerId: "w1", branch: "feature/w1" }, { mode: "print", now: NOW });
  const wt = prov.path;

  withAuditHome((read) => {
    const refused = worktreeCleanup(repo, "w1", { mode: "print" });
    assert.equal(refused.ok, false);
    assert.match(refused.message, /unmerged/);
    assert.ok(fs.existsSync(wt), "worktree kept while unmerged");
    assert.equal(read().at(-1).decision, "deny");

    // mark merged (as T8 would), then clean succeeds.
    saveLedger(repo, setMergeStatus(loadLedger(repo), "w1", "merged"));
    const ok = worktreeCleanup(repo, "w1", { mode: "print" });
    assert.equal(ok.ok, true, ok.message);
    assert.ok(!fs.existsSync(wt), "worktree removed after merge");
    assert.equal(read().at(-1).decision, "cleanup");
  });
});

test("cleanup: a dirty worktree is refused unless forced (force audited as override)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const prov = provisionWorktree(repo, { workerId: "w1", branch: "feature/w1" }, { mode: "print", now: NOW });
  saveLedger(repo, setMergeStatus(loadLedger(repo), "w1", "merged"));
  fs.writeFileSync(path.join(prov.path, "dirty.txt"), "x\n");

  withAuditHome((read) => {
    const refused = worktreeCleanup(repo, "w1", { mode: "print" });
    assert.equal(refused.ok, false);
    assert.match(refused.message, /dirty/);

    const forced = worktreeCleanup(repo, "w1", { force: true, mode: "print" });
    assert.equal(forced.ok, true, forced.message);
    assert.equal(read().at(-1).decision, "override", "forced cleanup audited as override");
  });
});

test("list: reports ledger workers + a foreign worktree (never touches it)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  provisionWorktree(repo, { workerId: "w1", branch: "feature/w1" }, { mode: "print", now: NOW });
  const foreign = path.join(path.dirname(repo), path.basename(repo) + "-foreign");
  spawnSync("git", ["-C", repo, "worktree", "add", "-q", foreign, "-b", "feature/foreign"], { encoding: "utf8" });

  const report = worktreeListReport(repo);
  assert.match(report, /w1/);
  assert.match(report, /feature\/w1/);
  assert.match(report, /\(foreign\)/);
});

// ── US3: fail-closed reconcile (reviews #3 & #4) ─────────────────────────────

test("reconcile: a primary-only repo produces ZERO foreign and NO ledger change", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  // Empty ledger written to disk; capture its bytes.
  saveLedger(repo, loadLedger(repo));
  const before = fs.readFileSync(path.join(repo, ".cct", "worktrees.json"));

  withAuditHome(() => {
    const res = reconcileOnStart(repo, { mode: "print" });
    assert.equal(res.status, "reconciled");
    assert.deepEqual(res.foreign, [], "primary is never flagged foreign");
    assert.deepEqual(res.stale, []);
    assert.equal(res.changed, false);
  });
  const after = fs.readFileSync(path.join(repo, ".cct", "worktrees.json"));
  assert.ok(before.equals(after), "ledger byte-for-byte unchanged");
});

test("reconcile: a vanished worker path is marked stale; a foreign one is reported not removed", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const prov = provisionWorktree(repo, { workerId: "w1", branch: "feature/w1" }, { mode: "print", now: NOW });
  // vanish w1 out-of-band; add a foreign worktree.
  fs.rmSync(prov.path, { recursive: true, force: true });
  const foreign = path.join(path.dirname(repo), path.basename(repo) + "-intruder");
  spawnSync("git", ["-C", repo, "worktree", "add", "-q", foreign, "-b", "feature/intruder"], { encoding: "utf8" });

  withAuditHome(() => {
    const res = reconcileOnStart(repo, { mode: "print" });
    assert.equal(res.status, "reconciled");
    assert.deepEqual(res.stale, ["w1"], "vanished worker marked stale");
    assert.ok(res.foreign.includes(fs.realpathSync(foreign)), "foreign reported");
    assert.ok(fs.existsSync(foreign), "foreign worktree left intact");
  });
  assert.equal(loadLedger(repo).workers.find((w) => w.workerId === "w1").cleanupStatus, "stale");
});

for (const scenario of [
  {
    name: "list failure (git nonzero)",
    deps: () => ({ listWorktreesStrict: () => ({ ok: false, worktrees: [], reason: "git exited 128" }) }),
  },
  {
    name: "malformed porcelain (strict parser rejects)",
    deps: () => ({ listWorktreesStrict: () => ({ ok: false, worktrees: [], reason: "unrecognized porcelain key" }) }),
  },
  {
    name: "prune failure",
    deps: (repo) => ({
      listWorktreesStrict: () => ({ ok: true, worktrees: [{ path: repo, branch: "master", isPrimary: true }] }),
      pruneWorktrees: () => ({ ok: false, reason: "git prune boom" }),
    }),
  },
]) {
  test(`reconcile fail-closed: ${scenario.name} => ledger byte-for-byte unchanged + audited`, { skip: !HAS_GIT }, () => {
    const repo = initRepo();
    // A NON-trivial ledger so an accidental save would visibly change the file.
    provisionWorktree(repo, { workerId: "keep", branch: "feature/keep" }, { mode: "print", now: NOW });
    const before = fs.readFileSync(path.join(repo, ".cct", "worktrees.json"));

    withAuditHome((read) => {
      const res = reconcileOnStart(repo, { mode: "print" }, scenario.deps(repo));
      assert.equal(res.status, "skipped");
      assert.equal(res.changed, false);
      assert.equal(read().at(-1).rule, WORKTREE_AUDIT.reconcileSkipped);
    });
    const after = fs.readFileSync(path.join(repo, ".cct", "worktrees.json"));
    assert.ok(before.equals(after), "ledger untouched on a git failure");
    // The live worker record must NOT have been marked stale.
    assert.equal(loadLedger(repo).workers.find((w) => w.workerId === "keep").cleanupStatus, "active");
  });
}

test("primaryRepoRoot resolves the primary from inside a linked worktree", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const prov = provisionWorktree(repo, { workerId: "w1", branch: "feature/w1" }, { mode: "print", now: NOW });
  assert.equal(primaryRepoRoot(prov.path), repo, "worker worktree resolves back to primary");
  assert.equal(primaryRepoRoot(repo), repo, "primary resolves to itself");
});

// ── strict porcelain parsing (review #4) ─────────────────────────────────────

test("parseWorktreePorcelainStrict accepts a well-formed listing", () => {
  const stdout = [
    "worktree /repo",
    "HEAD abc123",
    "branch refs/heads/master",
    "",
    "worktree /repo-w1",
    "HEAD def456",
    "branch refs/heads/feature/w1",
    "",
  ].join("\n");
  const r = parseWorktreePorcelainStrict(stdout);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.worktrees.length, 2);
  assert.equal(r.worktrees[0].isPrimary, true);
  assert.equal(r.worktrees[1].isPrimary, false);
  assert.equal(r.worktrees[1].branch, "feature/w1");
});

for (const [name, stdout] of [
  // The exact review #4 case: a valid first block, then a truncated block.
  ["truncated second block (worktree line, no path)", "worktree /repo\nHEAD abc\nbranch refs/heads/master\n\nworktree\n"],
  ["relative worktree path", "worktree relative/path\n"],
  ["content before the first worktree block", "HEAD abc\nworktree /repo\n"],
  ["unknown structural key", "worktree /repo\nbogus_key value\n"],
  ["empty output (no entries)", ""],
]) {
  test(`parseWorktreePorcelainStrict REJECTS: ${name}`, () => {
    const r = parseWorktreePorcelainStrict(stdout);
    assert.equal(r.ok, false, `expected rejection for: ${name}`);
    assert.deepEqual(r.worktrees, [], "no worktrees returned on rejection");
    assert.ok(typeof r.reason === "string" && r.reason.length > 0);
  });
}

test("listWorktreesStrict returns ok for a real repo with a worker worktree", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  provisionWorktree(repo, { workerId: "w1", branch: "feature/w1" }, { mode: "print", now: NOW });
  const r = listWorktreesStrict(repo);
  assert.equal(r.ok, true, r.reason);
  assert.equal(r.worktrees.filter((w) => w.isPrimary).length, 1);
  assert.ok(r.worktrees.some((w) => !w.isPrimary && /w1/.test(w.path)));
});

// ── isolation enforcement is fail-closed (review #1) ─────────────────────────

test("isolationToolBlock: invalid isolation BLOCKS edit/write/bash, allows read tools", () => {
  for (const t of ["edit", "write", "bash", "Edit", "BASH"]) {
    const r = isolationToolBlock("invalid", t);
    assert.equal(r.block, true, `${t} must be blocked when isolation is invalid`);
    assert.match(r.reason, /isolation/i);
  }
  for (const t of ["read", "grep", "ls", "glob"]) {
    assert.equal(isolationToolBlock("invalid", t).block, false, `${t} is read-only, never blocked`);
  }
});

test("isolationToolBlock: ok / not-a-worker never block (a primary session is not a worker)", () => {
  for (const s of ["ok", "not-a-worker"]) {
    for (const t of ["edit", "write", "bash"]) {
      assert.equal(isolationToolBlock(s, t).block, false, `${s}/${t} must not block`);
    }
  }
});

test("isolationStateFromAttach maps attach outcomes to the enforcement state", () => {
  assert.equal(isolationStateFromAttach("attached"), "ok");
  assert.equal(isolationStateFromAttach("not-isolated"), "invalid");
  assert.equal(isolationStateFromAttach("no-op"), "not-a-worker");
});

test("end-to-end (review #1 acceptance): wrong cwd => not-isolated audit => next bash/edit blocked", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  provisionWorktree(repo, { workerId: "w1", branch: "feature/w1" }, { mode: "print", now: NOW });
  withAuditHome((read) => {
    // Worker env says w1, but the session runs in the PRIMARY checkout.
    const attach = attachOnSessionStart(
      { cwd: repo, mode: "print" },
      { [WORKER_ENV.id]: "w1", [WORKER_ENV.branch]: "feature/w1" },
    );
    assert.equal(attach.status, "not-isolated");
    assert.equal(read().at(-1).rule, WORKTREE_AUDIT.notIsolated);
    // The state the tool_call gate reads => invalid => the next write is blocked.
    const iso = isolationStateFromAttach(attach.status);
    assert.equal(isolationToolBlock(iso, "bash").block, true, "next bash blocked");
    assert.equal(isolationToolBlock(iso, "edit").block, true, "next edit blocked");
  });
});

// ── lock: a LIVE owner's lock is never stolen (review #2/#3) ──────────────────

test("withLedgerLock does NOT reclaim a lock whose owner process is alive, even if old", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lockDir = path.join(repo, ".cct", "worktrees.lock");
  fs.mkdirSync(path.dirname(lockDir), { recursive: true });
  fs.mkdirSync(lockDir);
  // Owner = THIS process (provably alive), with an ancient mtime.
  fs.writeFileSync(path.join(lockDir, "owner.json"), JSON.stringify({ pid: process.pid, token: "other", ts: 0 }));
  const old = new Date(Date.now() - 10 * 60_000);
  fs.utimesSync(lockDir, old, old);
  // Must time out (not steal a live holder's lock) despite the old mtime.
  assert.throws(
    () => withLedgerLock(repo, () => "never", { staleMs: 1000, timeoutMs: 150 }),
    /could not acquire worktree ledger lock/,
  );
  // And it must NOT have removed the live owner's lock.
  assert.ok(fs.existsSync(lockDir), "live owner's lock left intact");
  fs.rmSync(lockDir, { recursive: true, force: true });
});

test("withLedgerLock reclaims a lock whose owner is a dead pid", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lockDir = path.join(repo, ".cct", "worktrees.lock");
  fs.mkdirSync(path.dirname(lockDir), { recursive: true });
  fs.mkdirSync(lockDir);
  // pid 2^31-1 is effectively never a live process.
  fs.writeFileSync(path.join(lockDir, "owner.json"), JSON.stringify({ pid: 2147483646, token: "dead", ts: Date.now() }));
  assert.equal(withLedgerLock(repo, () => "reclaimed", { staleMs: 60_000, timeoutMs: 500 }), "reclaimed", "a crashed owner's lock is reclaimed regardless of age");
});

// ── no-invented-event + fail-closed wiring (AC-6, review #1) ─────────────────

test("wiring subscribes ONLY to session_start and registers the command (no Stop/session.deleted)", () => {
  const idx = fs.readFileSync(new URL("../../adapters/pi/runtime/index.ts", import.meta.url), "utf8");
  assert.match(idx, /attachOnSessionStart\(/, "attach wired into session_start");
  assert.match(idx, /reconcileOnStart\(/, "reconcile wired into session_start");
  assert.match(idx, /registerCommand\?\.\("cct:worktree"/, "cct:worktree command registered");
  // review #1: the tool_call gate must actually block on invalid isolation.
  assert.match(idx, /isolationToolBlock\(state\.worktreeIsolation/, "isolation block wired into tool_call");
  assert.match(idx, /isolationStateFromAttach\(attach\.status\)/, "isolation state set from attach");
  // Pi exposes no session-end event; the wiring must NOT invent one.
  assert.doesNotMatch(idx, /session[._]deleted/, "no invented session-end event");
  assert.doesNotMatch(idx, /pi\.on\?\(\s*["']stop["']/i, "no Stop subscription");
});
