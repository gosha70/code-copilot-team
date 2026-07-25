// review.test.mjs — Unit tests for T6.1 peer-review runner integration + the
// mandatory-review gate (FR-015). Run via tests/test-pi-runtime.sh.
//
// Covers: state init, the mandatory-review gate (PASS/bypass/FAIL/INVALID/
// missing), mid-review warning, decision + bypass summary, runner invocation
// through a STUB runner (PASS / FAIL / breaker / INVALID-tamper outcomes),
// config→runner-env override winning over ambient CCT_REVIEW_* (decision C),
// and the generalized profile-key lint guard (condition E).

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  initReviewState,
  loadLoopSummary,
  loadReviewState,
  midReviewWarning,
  resolveReviewRunner,
  reviewGate,
  reviewPasses,
  runReviewRound,
  writeDecision,
} from "../../adapters/pi/runtime/workflow/review.ts";
import { BUILTIN_PROFILES } from "../../adapters/pi/runtime/config/profiles.ts";
import { lintConfig } from "../../adapters/pi/runtime/config/lint.ts";

function tmpProject() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-review-"));
}
function reviewFile(root, name) {
  return path.join(root, ".cct", "review", name);
}
function writeSummary(root, obj) {
  fs.mkdirSync(path.join(root, ".cct", "review"), { recursive: true });
  fs.writeFileSync(reviewFile(root, "loop-summary.json"), JSON.stringify(obj));
}
function stub(dir, name, body) {
  const p = path.join(dir, name);
  fs.writeFileSync(p, `#!/usr/bin/env bash\nset -e\n${body}\n`);
  fs.chmodSync(p, 0o755);
  return p;
}

const SUBMIT = {
  featureId: "042-x",
  phase: "build",
  subjectProvider: "pi",
  peerProvider: "",
  reviewScope: "both",
  targetRef: "HEAD~1",
  loopStart: 1700000000,
};

// ── state init ─────────────────────────────────────────────────────────────

test("initReviewState writes the runner-shaped state.json", () => {
  const root = tmpProject();
  initReviewState(root, SUBMIT);
  const st = loadReviewState(root);
  assert.equal(st.subject_provider, "pi");
  assert.equal(st.feature_id, "042-x");
  assert.equal(st.phase, "build");
  assert.equal(st.current_round, 0);
  assert.deepEqual(st.findings, {});
  assert.equal(st.last_verdict, null);
});

// ── mandatory-review gate (decision A) ─────────────────────────────────────

test("reviewGate: PASS and bypass satisfy it; FAIL/INVALID/missing block", () => {
  const root = tmpProject();
  // Not mandatory → always passes.
  assert.equal(reviewGate(root, false, "build").pass, true);
  // Mandatory, no summary → blocked.
  assert.equal(reviewGate(root, true, "build").pass, false);
  // Non-review phase → gate n/a.
  assert.equal(reviewGate(root, true, "plan").pass, true);

  writeSummary(root, { verdict: "PASS", bypass: false });
  assert.equal(reviewGate(root, true, "build").pass, true);
  assert.equal(reviewPasses(root), true);

  writeSummary(root, { verdict: "FAIL", bypass: false });
  assert.equal(reviewGate(root, true, "review").pass, false);

  // INVALID (tamper downgrade from the runner) must NOT pass.
  writeSummary(root, { verdict: "INVALID", bypass: false });
  assert.equal(reviewGate(root, true, "build").pass, false);

  // Bypass (audited override) satisfies the gate even on a FAIL verdict.
  writeSummary(root, { verdict: "FAIL", bypass: true });
  assert.equal(reviewGate(root, true, "build").pass, true);
});

// ── mid-review warning (decision A mitigation) ─────────────────────────────

test("midReviewWarning fires on an unresolved loop, silent when PASS/none", () => {
  const root = tmpProject();
  assert.equal(midReviewWarning(root), null); // no state
  initReviewState(root, SUBMIT);
  assert.match(midReviewWarning(root), /unresolved peer-review loop/); // in-progress
  writeSummary(root, { verdict: "PASS", bypass: false });
  assert.equal(midReviewWarning(root), null); // resolved
});

// ── decision + bypass summary ──────────────────────────────────────────────

test("writeDecision: approve writes bypass summary; reject/retry do not", () => {
  const root = tmpProject();
  initReviewState(root, { ...SUBMIT });
  writeDecision(root, "approve", "risk accepted", "2026-07-25T00:00:00Z");
  const s = loadLoopSummary(root);
  assert.equal(s.bypass, true);
  assert.equal(s.feature_id, "042-x");
  assert.equal(reviewPasses(root), true);

  const root2 = tmpProject();
  initReviewState(root2, { ...SUBMIT });
  writeDecision(root2, "reject", "no", "2026-07-25T00:00:00Z");
  assert.equal(loadLoopSummary(root2), null); // no bypass summary
  assert.ok(fs.existsSync(reviewFile(root2, "decision.json")));
});

// ── runner invocation through a stub (provider-agnostic) ───────────────────

test("runReviewRound maps runner exit codes: PASS/FAIL/breaker/INVALID", () => {
  const bin = tmpProject();
  const pass = stub(bin, "pass.sh", 'mkdir -p "$1/.cct/review"; echo \'{"verdict":"PASS","bypass":false}\' > "$1/.cct/review/loop-summary.json"; exit 0');
  const fail = stub(bin, "fail.sh", "exit 1");
  const breaker = stub(bin, "breaker.sh", 'mkdir -p "$1/.cct/review"; echo \'{"breaker":"max_rounds"}\' > "$1/.cct/review/breaker-tripped.json"; exit 2');
  // Tamper→INVALID: the runner discards findings and exits 1 with no PASS summary.
  const invalid = stub(bin, "invalid.sh", 'mkdir -p "$1/.cct/review"; echo \'{"round":1,"verdict":"INVALID"}\' > "$1/.cct/review/findings-round-1.json"; exit 1');
  const limits = { maxRounds: 5, timeoutSec: 900 };

  const rp = tmpProject();
  const passOut = runReviewRound(rp, pass, limits);
  assert.equal(passOut.status, "pass");
  assert.equal(passOut.verdict, "PASS");
  assert.equal(reviewGate(rp, true, "build").pass, true);

  assert.equal(runReviewRound(tmpProject(), fail, limits).status, "fail");
  assert.equal(runReviewRound(tmpProject(), breaker, limits).status, "breaker");

  // INVALID/tamper: runtime must NOT treat it as passing.
  const inv = tmpProject();
  const invOut = runReviewRound(inv, invalid, limits);
  assert.equal(invOut.status, "fail");
  assert.equal(reviewPasses(inv), false);
  assert.equal(reviewGate(inv, true, "build").pass, false);

  // No runner resolved → reported no-op, never a throw.
  assert.equal(runReviewRound(tmpProject(), null, limits).status, "no-runner");
});

test("runtime config CCT_REVIEW_* wins over ambient env (decision C)", () => {
  const bin = tmpProject();
  const echoenv = stub(bin, "echoenv.sh", 'mkdir -p "$1/.cct/review"; echo "$CCT_REVIEW_MAX_ROUNDS" > "$1/.cct/review/envcheck.txt"; exit 1');
  const prev = process.env.CCT_REVIEW_MAX_ROUNDS;
  try {
    process.env.CCT_REVIEW_MAX_ROUNDS = "999"; // ambient shell value
    const root = tmpProject();
    runReviewRound(root, echoenv, { maxRounds: 3, timeoutSec: 900 });
    const seen = fs.readFileSync(reviewFile(root, "envcheck.txt"), "utf8").trim();
    assert.equal(seen, "3", "runtime config must override ambient CCT_REVIEW_MAX_ROUNDS");
  } finally {
    if (prev === undefined) delete process.env.CCT_REVIEW_MAX_ROUNDS;
    else process.env.CCT_REVIEW_MAX_ROUNDS = prev;
  }
});

test("resolveReviewRunner honors CCT_REVIEW_RUNNER when it exists", () => {
  const bin = tmpProject();
  const runner = stub(bin, "review-round-runner.sh", "exit 0");
  const prev = process.env.CCT_REVIEW_RUNNER;
  try {
    process.env.CCT_REVIEW_RUNNER = runner;
    assert.equal(resolveReviewRunner(null), runner);
    process.env.CCT_REVIEW_RUNNER = path.join(bin, "nope.sh");
    assert.equal(resolveReviewRunner(null), null);
  } finally {
    if (prev === undefined) delete process.env.CCT_REVIEW_RUNNER;
    else process.env.CCT_REVIEW_RUNNER = prev;
  }
});

// ── generalized profile-key lint guard (condition E) ───────────────────────

test("every key set by every BUILTIN_PROFILES entry is lint-known", () => {
  const offenders = [];
  for (const [name, prof] of Object.entries(BUILTIN_PROFILES)) {
    if (!prof.config) continue;
    for (const f of lintConfig(prof.config)) {
      if (f.kind === "unknown") offenders.push(`${f.key} (in ${name})`);
    }
  }
  assert.deepEqual(offenders, [], `profiles ship keys the lint flags unknown: ${offenders.join(", ")}`);
});
