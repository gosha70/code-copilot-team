// worker-analytics.test.mjs — T7.4 worker verification execution + correlation
// + partial-failure aggregation (FR-011/FR-013). Run via tests/test-pi-runtime.sh.
//
// Verification execution uses the real verify.ts over a stub runner (the
// verify.test.mjs pattern); correlation redaction + batch aggregation are pure.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  WORKER_ANALYTICS_REL,
  buildCorrelation,
  emitCorrelation,
  runWorkerVerification,
  summarizeBatch,
  workerPassed,
} from "../../adapters/pi/runtime/agents/worker-analytics.ts";

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-wa-"));
}

// verify.ts invokes the runner via `bash <script>`, so no executable bit needed.
function writeStub(dir, body) {
  const p = path.join(dir, "verify-runner.sh");
  fs.writeFileSync(p, `#!/usr/bin/env bash\nset -e\n${body}\n`);
  return p;
}

const NOW = "2026-07-31T12:00:00Z";

// ── 1. worker verification execution ─────────────────────────────────────────

test("runWorkerVerification: gates pass in the worktree -> passed", () => {
  const worktree = tmp();
  const stub = writeStub(
    tmp(),
    `mkdir -p "$1/.cct/verify"; echo '{"drift":{"status":"supported","pass":true}}' > "$1/.cct/verify/result.json"; exit 0`,
  );
  const r = runWorkerVerification(worktree, ["drift"], 900, { runner: stub });
  assert.equal(r.status, "passed", r.reason);
  assert.equal(r.ran, true);
  // and it wrote INTO the worktree, not elsewhere
  assert.ok(fs.existsSync(path.join(worktree, ".cct", "verify", "result.json")));
});

test("runWorkerVerification: a failing required gate -> failed", () => {
  const worktree = tmp();
  const stub = writeStub(
    tmp(),
    `mkdir -p "$1/.cct/verify"; echo '{"drift":{"status":"supported","pass":false,"detail":"drift found"}}' > "$1/.cct/verify/result.json"; exit 1`,
  );
  const r = runWorkerVerification(worktree, ["drift"], 900, { runner: stub });
  assert.equal(r.status, "failed", r.reason);
  assert.equal(r.ran, true);
});

test("runWorkerVerification: no runner -> pending (did NOT execute, never silent pass)", () => {
  const r = runWorkerVerification(tmp(), ["drift"], 900, { runner: null });
  assert.equal(r.status, "pending");
  assert.equal(r.ran, false);
});

// ── 2. correlation + redaction ───────────────────────────────────────────────

function corrInput(overrides = {}) {
  return {
    at: NOW,
    correlationId: "corr-1",
    workerId: "w1",
    branch: "feature/w1",
    featureId: "F-42",
    parentSessionId: "sess-parent",
    childSessionId: "sess-child",
    depth: 1,
    verification: "passed",
    childStatus: "ok",
    costUsd: 0.02,
    ...overrides,
  };
}

test("buildCorrelation assembles the linkage record", () => {
  const c = buildCorrelation(corrInput());
  assert.equal(c.correlationId, "corr-1");
  assert.equal(c.workerId, "w1");
  assert.equal(c.parentSessionId, "sess-parent");
  assert.equal(c.childSessionId, "sess-child");
  assert.equal(c.verification, "passed");
  assert.equal(c.childStatus, "ok");
  assert.equal(c.costUsd, 0.02);
});

test("buildCorrelation redacts a secret in any string field", () => {
  const c = buildCorrelation(
    corrInput({ featureId: "token=abcdef1234567890", branch: "sk-ABCDEFGHIJKLMNOP1234" }),
  );
  assert.equal(c.featureId, "[REDACTED]");
  assert.equal(c.branch, "[REDACTED]");
});

test("buildCorrelation preserves null fields as null", () => {
  const c = buildCorrelation(corrInput({ featureId: null, childSessionId: null, costUsd: null }));
  assert.equal(c.featureId, null);
  assert.equal(c.childSessionId, null);
  assert.equal(c.costUsd, null);
});

test("emitCorrelation appends redacted JSONL, and re-redacts on write", () => {
  const root = tmp();
  emitCorrelation(root, buildCorrelation(corrInput()));
  // a caller handing emit a record with a secret still gets redaction
  emitCorrelation(root, { ...buildCorrelation(corrInput({ workerId: "w2" })), featureId: "AKIAABCDEFGHIJKLMNOP" });
  const lines = fs
    .readFileSync(path.join(root, WORKER_ANALYTICS_REL), "utf8")
    .trim()
    .split("\n")
    .map((l) => JSON.parse(l));
  assert.equal(lines.length, 2);
  assert.equal(lines[0].workerId, "w1");
  assert.equal(lines[1].featureId, "[REDACTED]", "emit must re-redact, not trust the caller");
});

// ── 3. partial-failure aggregation (fail-closed) ─────────────────────────────

const out = (workerId, verification, childStatus) => ({ workerId, verification, childStatus });

test("workerPassed: only verification passed AND child ok", () => {
  assert.equal(workerPassed(out("a", "passed", "ok")), true);
  assert.equal(workerPassed(out("a", "passed", "timeout")), false);
  assert.equal(workerPassed(out("a", "pending", "ok")), false);
  assert.equal(workerPassed(out("a", "failed", "ok")), false);
});

test("summarizeBatch: all passed -> all-passed", () => {
  const s = summarizeBatch([out("a", "passed", "ok"), out("b", "passed", "ok")]);
  assert.equal(s.verdict, "all-passed");
  assert.equal(s.passed, 2);
  assert.equal(s.failed, 0);
  assert.deepEqual(s.failedWorkers, []);
});

test("summarizeBatch: none passed -> all-failed", () => {
  const s = summarizeBatch([out("a", "failed", "ok"), out("b", "passed", "timeout")]);
  assert.equal(s.verdict, "all-failed");
  assert.equal(s.passed, 0);
});

test("summarizeBatch: mixed -> partial, with failedWorkers + tallies", () => {
  const s = summarizeBatch([
    out("a", "passed", "ok"),
    out("b", "failed", "ok"),
    out("c", "passed", "timeout"),
    out("d", "pending", "no-runner"),
  ]);
  assert.equal(s.verdict, "partial");
  assert.equal(s.passed, 1);
  assert.equal(s.failed, 3);
  assert.deepEqual(s.failedWorkers.sort(), ["b", "c", "d"]);
  assert.equal(s.byChildStatus.ok, 2);
  assert.equal(s.byChildStatus.timeout, 1);
  assert.equal(s.byChildStatus["no-runner"], 1);
  assert.equal(s.byVerification.passed, 2);
  assert.equal(s.byVerification.pending, 1);
});

test("summarizeBatch: a pending/timeout worker prevents all-passed (fail-closed)", () => {
  assert.equal(summarizeBatch([out("a", "passed", "ok"), out("b", "pending", "ok")]).verdict, "partial");
  assert.equal(summarizeBatch([out("a", "passed", "ok"), out("b", "passed", "timeout")]).verdict, "partial");
});

test("summarizeBatch: empty batch is vacuously all-passed", () => {
  const s = summarizeBatch([]);
  assert.equal(s.verdict, "all-passed");
  assert.equal(s.total, 0);
});
