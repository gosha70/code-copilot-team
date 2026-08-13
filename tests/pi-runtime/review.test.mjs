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
  peerReviewDisabled,
  prepareReviewLoop,
  resolveReviewRunner,
  resolveTargetRef,
  reviewGate,
  reviewPasses,
  runReviewRound,
  sessionPeerProvider,
  sessionReviewScope,
  submitReviewRound,
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
  // #233: writeDecision now enforces a live breaker (file or reconstructable
  // unresolved review_breaker escalation) — the fixtures carry the file.
  const root = tmpProject();
  initReviewState(root, { ...SUBMIT });
  fs.writeFileSync(reviewFile(root, "breaker-tripped.json"), '{"breaker":"max_rounds"}\n');
  writeDecision(root, "approve", "risk accepted", "2026-07-25T00:00:00Z");
  const s = loadLoopSummary(root);
  assert.equal(s.bypass, true);
  assert.equal(s.feature_id, "042-x");
  assert.equal(reviewPasses(root), true);
  // The decision records the breaker type it resolved, and consumes the file.
  const dec = JSON.parse(fs.readFileSync(reviewFile(root, "decision.json"), "utf8"));
  assert.equal(dec.breaker_type, "max_rounds");
  assert.equal(fs.existsSync(reviewFile(root, "breaker-tripped.json")), false);

  const root2 = tmpProject();
  initReviewState(root2, { ...SUBMIT });
  fs.writeFileSync(reviewFile(root2, "breaker-tripped.json"), '{"breaker":"max_rounds"}\n');
  writeDecision(root2, "reject", "no", "2026-07-25T00:00:00Z");
  assert.equal(loadLoopSummary(root2), null); // no bypass summary
  assert.ok(fs.existsSync(reviewFile(root2, "decision.json")));
});

test("writeDecision #233: a typeless breaker artifact reconstructs, never 'unknown'", () => {
  // Parseable {} (and malformed JSON, via readJson->null) is UNAVAILABLE:
  // the decision must come from feature-bound reconstruction with
  // provenance, or not at all — no provenance-less "unknown".
  const root = tmpProject();
  initReviewState(root, { ...SUBMIT });
  fs.writeFileSync(reviewFile(root, "breaker-tripped.json"), "{}\n");
  const escDir = path.join(root, ".cct", "auto-build", "042-x", "escalations");
  fs.mkdirSync(escDir, { recursive: true });
  fs.writeFileSync(
    path.join(escDir, "esc-1.json"),
    JSON.stringify({ id: "esc-1", reason: "review_breaker", detail: "review runner exited 5 (phase 1)", phase: 1, resolved: false }) + "\n",
  );
  writeDecision(root, "retry", "x", "2026-07-25T00:00:00Z");
  const dec = JSON.parse(fs.readFileSync(reviewFile(root, "decision.json"), "utf8"));
  assert.equal(dec.breaker_type, "runner_crash_legacy");
  assert.match(dec.reconstructed_from, /042-x/);

  // Malformed JSON with nothing to reconstruct from -> refusal, no decision.
  const root2 = tmpProject();
  initReviewState(root2, { ...SUBMIT });
  fs.writeFileSync(reviewFile(root2, "breaker-tripped.json"), "not json\n");
  assert.throws(
    () => writeDecision(root2, "retry", "x", "2026-07-25T00:00:00Z"),
    /Nothing to decide/,
  );
  assert.equal(fs.existsSync(reviewFile(root2, "decision.json")), false);
});

test("writeDecision #233: refusals leave nothing consumable; retry is durable-first", () => {
  // No breaker anywhere -> precise refusal, no decision file.
  const root = tmpProject();
  initReviewState(root, { ...SUBMIT });
  assert.throws(
    () => writeDecision(root, "retry", "x", "2026-07-25T00:00:00Z"),
    /Nothing to decide/,
  );
  assert.equal(fs.existsSync(reviewFile(root, "decision.json")), false);

  // Live breaker but no state.json -> retry refuses, breaker unconsumed.
  const root2 = tmpProject();
  fs.mkdirSync(path.join(root2, ".cct", "review"), { recursive: true });
  fs.writeFileSync(reviewFile(root2, "breaker-tripped.json"), '{"breaker":"timeout"}\n');
  assert.throws(
    () => writeDecision(root2, "retry", "x", "2026-07-25T00:00:00Z"),
    /no decision was recorded/,
  );
  assert.equal(fs.existsSync(reviewFile(root2, "decision.json")), false);
  assert.equal(fs.existsSync(reviewFile(root2, "breaker-tripped.json")), true);

  // Crash-shaped escalation, no breaker file -> feature-bound reconstruction
  // with provenance; retry semantics applied before the decision publishes.
  const root3 = tmpProject();
  initReviewState(root3, { ...SUBMIT });
  const escDir = path.join(root3, ".cct", "auto-build", "042-x", "escalations");
  fs.mkdirSync(escDir, { recursive: true });
  fs.writeFileSync(
    path.join(escDir, "esc-1.json"),
    JSON.stringify({ id: "esc-1", reason: "review_breaker", detail: "review runner exited 5 (phase 1)", phase: 1, resolved: false }) + "\n",
  );
  writeDecision(root3, "retry", "x", "2026-07-25T00:00:00Z");
  const dec3 = JSON.parse(fs.readFileSync(reviewFile(root3, "decision.json"), "utf8"));
  assert.equal(dec3.breaker_type, "runner_crash_legacy");
  assert.match(dec3.reconstructed_from, /042-x/);
  const st3 = JSON.parse(fs.readFileSync(reviewFile(root3, "state.json"), "utf8"));
  assert.equal(st3.attempt, 2);
  assert.ok(Math.abs(Date.now() / 1000 - st3.loop_start) < 60);
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

// ── init-vs-continue: the breaker-preservation regression ──────────────────

test("prepareReviewLoop continues an unresolved same-target loop; resets otherwise", () => {
  const root = tmpProject();
  initReviewState(root, SUBMIT);
  // Simulate the runner having advanced the loop (its breaker inputs).
  const st = loadReviewState(root);
  st.current_round = 3;
  st.loop_start = 111;
  st.last_verdict = "FAIL";
  fs.writeFileSync(reviewFile(root, "state.json"), JSON.stringify(st));

  // Same feature/phase, unresolved → CONTINUE: breaker state preserved.
  assert.equal(prepareReviewLoop(root, SUBMIT), "continue");
  assert.equal(loadReviewState(root).current_round, 3, "must not reset breaker state");
  assert.equal(loadReviewState(root).loop_start, 111);

  // Prior loop resolved → fresh init: breakers reset, stale PASS cleared.
  writeSummary(root, { verdict: "PASS", bypass: false });
  assert.equal(prepareReviewLoop(root, SUBMIT), "init");
  assert.equal(loadReviewState(root).current_round, 0);
  assert.equal(loadLoopSummary(root), null, "stale PASS summary cleared on a new loop");

  // Changed feature → fresh init.
  fs.writeFileSync(
    reviewFile(root, "state.json"),
    JSON.stringify({ ...loadReviewState(root), current_round: 2 }),
  );
  assert.equal(prepareReviewLoop(root, { ...SUBMIT, featureId: "other" }), "init");
  assert.equal(loadReviewState(root).current_round, 0);
});

test("consecutive submits ADVANCE the loop, never reset it (breaker regression)", () => {
  const bin = tmpProject();
  // Stub runner that advances current_round (as the real runner does) and FAILs.
  const incr = stub(
    bin,
    "incr.sh",
    'node -e \'const fs=require("fs");const f=process.argv[1]+"/.cct/review/state.json";' +
      'const s=JSON.parse(fs.readFileSync(f));s.current_round=(s.current_round||0)+1;' +
      "fs.writeFileSync(f,JSON.stringify(s));' \"$1\"; exit 1",
  );
  const root = tmpProject();
  const limits = { maxRounds: 5, timeoutSec: 900 };

  const s1 = submitReviewRound(root, SUBMIT, incr, limits);
  assert.equal(s1.mode, "init");
  assert.equal(loadReviewState(root).current_round, 1);

  const s2 = submitReviewRound(root, SUBMIT, incr, limits);
  assert.equal(s2.mode, "continue", "re-submit must continue, not re-init");
  assert.equal(
    loadReviewState(root).current_round,
    2,
    "current_round must increase monotonically so breakers can trip",
  );
});

test("resolveTargetRef: explicit arg wins; non-git dir falls back to HEAD~1", () => {
  assert.equal(resolveTargetRef("/nonexistent-xyz", "abc123"), "abc123");
  assert.equal(resolveTargetRef(tmpProject()), "HEAD~1"); // tmp dir is not a repo
});

test("runReviewRound kills a hung runner via the belt-and-braces timeout", () => {
  const bin = tmpProject();
  const slow = stub(bin, "slow.sh", "sleep 5; exit 0");
  // timeoutSec + 30s grace; -29 => a 1s wall so the 5s sleep is killed.
  const out = runReviewRound(tmpProject(), slow, { maxRounds: 5, timeoutSec: -29 });
  assert.equal(out.status, "error");
  assert.match(out.reason, /failed to run/);
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

// ── T6.3: peer-review session contract (CCT_PEER_*) ─────────────────────────

function withEnv(vars, fn) {
  const prev = {};
  for (const k of Object.keys(vars)) prev[k] = process.env[k];
  try {
    for (const [k, v] of Object.entries(vars)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
    fn();
  } finally {
    for (const [k, v] of Object.entries(prev)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

test("sessionPeerProvider: ARG > CCT_PEER_PROVIDER > profile-default(empty)", () => {
  withEnv({ CCT_PEER_PROVIDER: "codex" }, () => {
    assert.equal(sessionPeerProvider("gemini"), "gemini"); // explicit arg wins
    assert.equal(sessionPeerProvider(""), "codex"); // env fallback
  });
  withEnv({ CCT_PEER_PROVIDER: undefined }, () => {
    assert.equal(sessionPeerProvider(""), ""); // profile default (runner resolves)
  });
});

test("sessionReviewScope: env value; default both; invalid -> both", () => {
  withEnv({ CCT_PEER_REVIEW_SCOPE: undefined }, () => assert.equal(sessionReviewScope(), "both"));
  withEnv({ CCT_PEER_REVIEW_SCOPE: "code" }, () => assert.equal(sessionReviewScope(), "code"));
  withEnv({ CCT_PEER_REVIEW_SCOPE: "design" }, () => assert.equal(sessionReviewScope(), "design"));
  withEnv({ CCT_PEER_REVIEW_SCOPE: "both" }, () => assert.equal(sessionReviewScope(), "both"));
  withEnv({ CCT_PEER_REVIEW_SCOPE: "bogus" }, () => assert.equal(sessionReviewScope(), "both"));
});

test("peerReviewDisabled: only CCT_PEER_REVIEW_ENABLED=false or CCT_PEER_BYPASS=true", () => {
  withEnv({ CCT_PEER_REVIEW_ENABLED: undefined, CCT_PEER_BYPASS: undefined }, () =>
    assert.equal(peerReviewDisabled(), false),
  );
  withEnv({ CCT_PEER_REVIEW_ENABLED: "false" }, () => assert.equal(peerReviewDisabled(), true));
  withEnv({ CCT_PEER_REVIEW_ENABLED: "true" }, () => assert.equal(peerReviewDisabled(), false));
  withEnv({ CCT_PEER_REVIEW_ENABLED: undefined, CCT_PEER_BYPASS: "true" }, () =>
    assert.equal(peerReviewDisabled(), true),
  );
  // Guardrail A: these are session intent — they never mutate config. A bare
  // "enabled" set to anything but the literal "false" does NOT disable review.
  withEnv({ CCT_PEER_REVIEW_ENABLED: "0" }, () => assert.equal(peerReviewDisabled(), false));
});
