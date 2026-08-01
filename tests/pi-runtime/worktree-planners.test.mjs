// worktree-planners.test.mjs — T7.3 pure planners + ledger I/O (FR-013). Run
// via tests/test-pi-runtime.sh. No git here; the real git-exec is covered by
// worktree-git.test.mjs.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  areasOverlap,
  cleanupEligibility,
  detectOwnershipConflicts,
  emptyLedger,
  isPathContained,
  isProtectedBranch,
  loadLedger,
  normalizeArea,
  reconcile,
  saveLedger,
  validateCreateRequest,
} from "../../adapters/pi/runtime/agents/worktree.ts";

function worker(overrides = {}) {
  return {
    workerId: "w1",
    branch: "feature/w1",
    worktreePath: "/tmp/wt/w1",
    featureId: "F1",
    tasks: ["T1"],
    ownedAreas: ["src/a"],
    verificationStatus: "pending",
    mergeStatus: "unmerged",
    cleanupStatus: "active",
    createdAt: "2026-07-31T00:00:00Z",
    origin: "cct",
    ...overrides,
  };
}

// ── ownership ────────────────────────────────────────────────────────────────

test("areasOverlap: equality, prefix containment, glob/slash normalization", () => {
  assert.equal(areasOverlap("src/a", "src/a"), true);
  assert.equal(areasOverlap("src", "src/a/b"), true);
  assert.equal(areasOverlap("src/a/b", "src"), true);
  assert.equal(areasOverlap("src/a", "src/b"), false);
  assert.equal(areasOverlap("./src/a/", "src/a/**"), true);
  assert.equal(areasOverlap("src/ab", "src/a"), false); // not a path boundary
});

test("normalizeArea strips ./, trailing slash and glob", () => {
  assert.equal(normalizeArea("./src/a/"), "src/a");
  assert.equal(normalizeArea("src/a/**"), "src/a");
  assert.equal(normalizeArea("src/a/*"), "src/a");
});

test("detectOwnershipConflicts finds overlapping active pairs only", () => {
  const ledger = {
    version: 1,
    workers: [
      worker({ workerId: "a", ownedAreas: ["src/x"] }),
      worker({ workerId: "b", branch: "feature/b", worktreePath: "/tmp/wt/b", ownedAreas: ["src/x/y"] }),
      worker({ workerId: "c", branch: "feature/c", worktreePath: "/tmp/wt/c", ownedAreas: ["docs"] }),
    ],
  };
  const conflicts = detectOwnershipConflicts(ledger);
  assert.equal(conflicts.length, 1);
  assert.deepEqual(conflicts[0], { a: "a", b: "b", area: "src/x" });
});

test("cleaned/stale workers do not contribute ownership conflicts", () => {
  const ledger = {
    version: 1,
    workers: [
      worker({ workerId: "a", ownedAreas: ["src/x"] }),
      worker({ workerId: "b", branch: "feature/b", worktreePath: "/tmp/wt/b", ownedAreas: ["src/x"], cleanupStatus: "cleaned" }),
    ],
  };
  assert.equal(detectOwnershipConflicts(ledger).length, 0);
});

// ── create validation ────────────────────────────────────────────────────────

test("validateCreateRequest: happy path", () => {
  const r = validateCreateRequest(
    { workerId: "w2", branch: "feature/w2", worktreePath: "/tmp/wt/w2", ownedAreas: ["docs"] },
    { version: 1, workers: [worker()] },
  );
  assert.equal(r.valid, true, r.errors.join("; "));
});

test("validateCreateRequest refuses protected branches", () => {
  for (const b of ["master", "main", "MAIN"]) {
    const r = validateCreateRequest(
      { workerId: "wx", branch: b, worktreePath: "/tmp/wt/wx" },
      emptyLedger(),
    );
    assert.equal(r.valid, false, b);
    assert.ok(r.errors.some((e) => /protected branch/.test(e)));
  }
});

test("validateCreateRequest rejects overlap, dup id/branch/path, bad id, relative path", () => {
  const ledger = { version: 1, workers: [worker()] };
  const overlap = validateCreateRequest(
    { workerId: "w2", branch: "feature/w2", worktreePath: "/tmp/wt/w2", ownedAreas: ["src/a/deep"] },
    ledger,
  );
  assert.ok(overlap.errors.some((e) => /overlaps worker 'w1'/.test(e)));

  assert.equal(
    validateCreateRequest({ workerId: "w1", branch: "feature/z", worktreePath: "/tmp/wt/z" }, ledger).valid,
    false,
  );
  assert.equal(
    validateCreateRequest({ workerId: "z", branch: "feature/w1", worktreePath: "/tmp/wt/z" }, ledger).valid,
    false,
  );
  assert.equal(
    validateCreateRequest({ workerId: "Bad_Id", branch: "feature/z", worktreePath: "/tmp/wt/z" }, ledger).valid,
    false,
  );
  assert.equal(
    validateCreateRequest({ workerId: "z", branch: "feature/z", worktreePath: "relative/path" }, ledger).valid,
    false,
  );
});

// ── cleanup eligibility (the safety gate) ────────────────────────────────────

test("cleanupEligibility: origin/primary/clean/merge preconditions", () => {
  const rec = worker({ mergeStatus: "merged" });
  assert.equal(cleanupEligibility(rec, { isClean: true, isPrimary: false }).eligible, true);
  // unmerged blocks
  assert.equal(
    cleanupEligibility(worker(), { isClean: true, isPrimary: false }).eligible,
    false,
  );
  // dirty blocks
  assert.equal(
    cleanupEligibility(rec, { isClean: false, isPrimary: false }).eligible,
    false,
  );
  // primary always refused, even forced
  assert.equal(
    cleanupEligibility(rec, { isClean: true, isPrimary: true, force: true }).eligible,
    false,
  );
  // foreign (non-cct) always refused, even forced
  assert.equal(
    cleanupEligibility(worker({ origin: "user" }), { isClean: true, isPrimary: false, force: true }).eligible,
    false,
  );
  // force waives clean+merge (but not primary/foreign)
  assert.equal(
    cleanupEligibility(worker(), { isClean: false, isPrimary: false, force: true }).eligible,
    true,
  );
  // missing record
  assert.equal(cleanupEligibility(undefined, { isClean: true, isPrimary: false }).eligible, false);
});

// ── reconcile ────────────────────────────────────────────────────────────────

test("reconcile marks vanished records stale and reports foreign worktrees", () => {
  const ledger = {
    version: 1,
    workers: [
      worker({ workerId: "a", worktreePath: "/tmp/wt/a" }),
      worker({ workerId: "b", branch: "feature/b", worktreePath: "/tmp/wt/b" }),
    ],
  };
  const { ledger: next, stale, foreign } = reconcile(ledger, ["/tmp/wt/a", "/tmp/wt/foreign"]);
  assert.deepEqual(stale, ["b"]);
  assert.deepEqual(foreign, ["/tmp/wt/foreign"]);
  assert.equal(next.workers.find((w) => w.workerId === "b").cleanupStatus, "stale");
  assert.equal(next.workers.find((w) => w.workerId === "a").cleanupStatus, "active");
});

// ── ledger I/O (tamper-safe) ─────────────────────────────────────────────────

test("loadLedger sanitizes: drops bad records, forces origin cct, clamps enums", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-wt-led-"));
  fs.mkdirSync(path.join(dir, ".cct"), { recursive: true });
  fs.writeFileSync(
    path.join(dir, ".cct", "worktrees.json"),
    JSON.stringify({
      version: 99,
      workers: [
        { workerId: "ok", branch: "feature/ok", worktreePath: "/abs/ok", origin: "user", mergeStatus: "bogus", verificationStatus: "passed" },
        { workerId: "Bad Id", branch: "feature/x", worktreePath: "/abs/x" }, // dropped: bad id
        { workerId: "rel", branch: "feature/y", worktreePath: "relative" }, // dropped: not absolute
        { branch: "feature/z", worktreePath: "/abs/z" }, // dropped: no id
      ],
    }),
  );
  const led = loadLedger(dir);
  assert.equal(led.version, 1);
  assert.equal(led.workers.length, 1);
  // Provenance PRESERVED, not rewritten: an origin:"user" record loads as
  // "foreign" and is never removable — the no-delete-user-worktrees invariant.
  assert.equal(led.workers[0].origin, "foreign");
  assert.equal(
    cleanupEligibility(led.workers[0], { isClean: true, isPrimary: false, force: true }).eligible,
    false,
    "a foreign (non-cct) record must never be removable, even forced",
  );
  assert.equal(led.workers[0].mergeStatus, "unmerged"); // clamped
  assert.equal(led.workers[0].verificationStatus, "passed"); // valid kept
});

test("a missing/unknown origin loads as foreign (never cct)", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-wt-orig-"));
  fs.mkdirSync(path.join(dir, ".cct"), { recursive: true });
  fs.writeFileSync(
    path.join(dir, ".cct", "worktrees.json"),
    JSON.stringify({ version: 1, workers: [{ workerId: "x", branch: "feature/x", worktreePath: "/abs/x" }] }),
  );
  assert.equal(loadLedger(dir).workers[0].origin, "foreign");
});

// ── branch-name + path safety (review fixes) ─────────────────────────────────

test("isProtectedBranch rejects master/main and any full refs/ name", () => {
  for (const b of ["master", "main", "MASTER", "refs/heads/master", "refs/heads/main", "refs/tags/x"])
    assert.equal(isProtectedBranch(b), true, b);
  for (const b of ["feature/x", "fix/master-thing", "heads/x"])
    assert.equal(isProtectedBranch(b), false, b);
});

test("validateCreateRequest rejects a full-ref master bypass", () => {
  const r = validateCreateRequest(
    { workerId: "wref", branch: "refs/heads/master", worktreePath: "/mroot/wref" },
    emptyLedger(),
  );
  assert.equal(r.valid, false);
  assert.ok(r.errors.some((e) => /protected branch/.test(e)));
});

test("isPathContained: strictly-inside only", () => {
  assert.equal(isPathContained("/root/a/b", "/root"), true);
  assert.equal(isPathContained("/root", "/root"), false); // equal is not inside
  assert.equal(isPathContained("/other/x", "/root"), false);
  assert.equal(isPathContained("/root/../evil", "/root"), false);
  assert.equal(isPathContained("relative", "/root"), false);
});

test("validateCreateRequest enforces managedRoot containment when given", () => {
  const inside = validateCreateRequest(
    { workerId: "wi", branch: "feature/wi", worktreePath: "/mroot/repo-wi" },
    emptyLedger(),
    { managedRoot: "/mroot" },
  );
  assert.equal(inside.valid, true, inside.errors.join("; "));
  const outside = validateCreateRequest(
    { workerId: "wo", branch: "feature/wo", worktreePath: "/tmp/arbitrary-cct-wt" },
    emptyLedger(),
    { managedRoot: "/mroot" },
  );
  assert.equal(outside.valid, false);
  assert.ok(outside.errors.some((e) => /managed root/.test(e)));
});

test("saveLedger/loadLedger round-trips and pins the version", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-wt-rt-"));
  const led = { version: 1, workers: [worker()] };
  saveLedger(dir, led);
  const back = loadLedger(dir);
  assert.equal(back.workers.length, 1);
  assert.equal(back.workers[0].workerId, "w1");
});

test("loadLedger on a missing/corrupt file returns an empty ledger", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-wt-empty-"));
  assert.deepEqual(loadLedger(dir), emptyLedger());
  fs.mkdirSync(path.join(dir, ".cct"), { recursive: true });
  fs.writeFileSync(path.join(dir, ".cct", "worktrees.json"), "{ not json");
  assert.deepEqual(loadLedger(dir), emptyLedger());
});
