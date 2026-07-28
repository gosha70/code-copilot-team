// verify.test.mjs — Unit tests for T6.2 verification gates (FR-016).
// Run via tests/test-pi-runtime.sh.
//
// The spine is the LEAK-SHAPED TRIO (the fail-open hole the design must not
// have): (1) no result.json + required list non-empty -> FAIL (fail-closed);
// (2) no result.json + nothing required -> pass (no-op); (3) a required gate
// that is `unsupported` -> FAIL (hard config error, never a silent pass). Plus
// gate pass/fail/degraded/missing, runVerify over a stub runner, and warnings.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  loadVerifyResult,
  resolveVerifyRunner,
  runVerify,
  verifyGate,
  verifyWarning,
} from "../../adapters/pi/runtime/workflow/verify.ts";

function tmpProject() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-verify-"));
}
function writeResult(root, obj) {
  fs.mkdirSync(path.join(root, ".cct", "verify"), { recursive: true });
  fs.writeFileSync(path.join(root, ".cct", "verify", "result.json"), JSON.stringify(obj));
}
// verify.ts invokes the runner via `bash <script>`, so no executable bit needed.
function writeStub(dir, body) {
  const p = path.join(dir, "verify-runner.sh");
  fs.writeFileSync(p, `#!/usr/bin/env bash\nset -e\n${body}\n`);
  return p;
}

// ── The leak-shaped trio (the whole point of this feature's honesty) ────────

test("LEAK TRIO 1: no result + non-empty required -> FAIL (fail-closed, absent runner)", () => {
  const root = tmpProject();
  const g = verifyGate(root, ["drift", "docs"], "build");
  assert.equal(g.pass, false, "a missing result.json with required gates must NOT pass");
  assert.match(g.reason, /has not run/);
});

test("LEAK TRIO 2: no result + nothing required -> pass (no-op)", () => {
  const root = tmpProject();
  assert.equal(verifyGate(root, [], "build").pass, true);
});

test("LEAK TRIO 3: required + unsupported -> FAIL (hard config error, never a silent pass)", () => {
  const root = tmpProject();
  writeResult(root, { "type-check": { status: "unsupported", pass: false } });
  const g = verifyGate(root, ["type-check"], "build");
  assert.equal(g.pass, false);
  assert.match(g.reason, /unsupported/);
  assert.match(g.reason, /config error/);
});

// ── Gate logic ──────────────────────────────────────────────────────────────

test("verifyGate: all required pass -> pass; a required FAIL/missing -> fail", () => {
  const root = tmpProject();
  writeResult(root, {
    drift: { status: "supported", pass: true },
    docs: { status: "supported", pass: true },
  });
  assert.equal(verifyGate(root, ["drift", "docs"], "build").pass, true);

  writeResult(root, { drift: { status: "supported", pass: false, detail: "drift found" } });
  assert.equal(verifyGate(root, ["drift"], "build").pass, false);

  // Required gate absent from the result -> "did not run" -> fail.
  writeResult(root, { docs: { status: "supported", pass: true } });
  assert.equal(verifyGate(root, ["drift"], "build").pass, false);
});

test("verifyGate: a degraded gate that PASSED satisfies the requirement", () => {
  const root = tmpProject();
  writeResult(root, { build: { status: "degraded", pass: true, detail: "docker only" } });
  assert.equal(verifyGate(root, ["build"], "build").pass, true);
});

test("verifyGate: applies to build/review phases only", () => {
  const root = tmpProject();
  // No result, required non-empty, but phase=plan -> gate n/a -> pass.
  assert.equal(verifyGate(root, ["drift"], "plan").pass, true);
  assert.equal(verifyGate(root, ["drift"], "research").pass, true);
});

// ── runVerify over a stub runner (provider-agnostic) ────────────────────────

test("runVerify drives the runner (bash-invoked) and reads its result", () => {
  const bin = tmpProject();
  const root = tmpProject();
  const stub = writeStub(
    bin,
    'mkdir -p "$1/.cct/verify"; echo \'{"drift":{"status":"supported","pass":true}}\' > "$1/.cct/verify/result.json"; exit 0',
  );
  const out = runVerify(root, stub, ["drift"], 900);
  assert.equal(out.ran, true);
  assert.equal(out.exitCode, 0);
  assert.deepEqual(loadVerifyResult(root), { drift: { status: "supported", pass: true } });
  assert.equal(verifyGate(root, ["drift"], "build").pass, true);
});

test("runVerify with no runner reports (does not throw); gate still fails closed", () => {
  const root = tmpProject();
  const out = runVerify(root, null, ["drift"], 900);
  assert.equal(out.ran, false);
  assert.match(out.reason, /not found/);
  // The runtime's gate — NOT runVerify — is the fail-closed authority.
  assert.equal(verifyGate(root, ["drift"], "build").pass, false);
});

test("resolveVerifyRunner honors CCT_VERIFY_RUNNER when it exists", () => {
  const bin = tmpProject();
  const stub = writeStub(bin, "exit 0");
  const prev = process.env.CCT_VERIFY_RUNNER;
  try {
    process.env.CCT_VERIFY_RUNNER = stub;
    assert.equal(resolveVerifyRunner(null), stub);
    process.env.CCT_VERIFY_RUNNER = path.join(bin, "nope.sh");
    assert.equal(resolveVerifyRunner(null), null);
  } finally {
    if (prev === undefined) delete process.env.CCT_VERIFY_RUNNER;
    else process.env.CCT_VERIFY_RUNNER = prev;
  }
});

// ── Session-start warning ───────────────────────────────────────────────────

test("verifyWarning: fires on unresolved required, silent when none/passing", () => {
  const root = tmpProject();
  assert.equal(verifyWarning(root, []), null); // nothing required
  assert.match(verifyWarning(root, ["drift"]), /unresolved verification/); // no result
  writeResult(root, { drift: { status: "supported", pass: true } });
  assert.equal(verifyWarning(root, ["drift"]), null); // resolved
});
