// sandbox.test.mjs — T10.1 sandbox detection + the autonomous/ci no-unrestricted-
// host gate (FR-019). Run via tests/test-pi-runtime.sh.
//
// The gate logic is pure/deterministic. Detection is tested via the deterministic
// declaration paths (CCT_SANDBOX / container env) — the FS-sniffing Docker path
// is environment-dependent, so tests drive detection through explicit env.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  detectSandbox,
  dockerProvider,
  envProvider,
  sandboxGate,
} from "../../adapters/pi/runtime/policy/sandbox.ts";
import activate from "../../adapters/pi/runtime/index.ts";

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-sb-"));
}

// Drive activation + session_start + one bash tool_call, returning the
// tool_call verdict (undefined when not blocked). CCT_SANDBOX makes detection
// deterministic regardless of whether the test host is a container.
async function driveTool(profile, extraEnv, home = tmp()) {
  const handlers = {};
  const pi = { registerCommand: () => {}, on: (e, h) => (handlers[e] = h), call: () => {} };
  const sessionCtx = {
    cwd: tmp(),
    isProjectTrusted: () => true,
    hasUI: false,
    mode: "print",
    addContext: () => {},
  };
  const keys = ["CCT_TEST_BOOTSTRAP", "CCT_PROFILE", "CCT_HOME", "CCT_SANDBOX", "CCT_SANDBOX_OVERRIDE"];
  const prev = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  process.env.CCT_TEST_BOOTSTRAP = "1";
  process.env.CCT_PROFILE = profile;
  process.env.CCT_HOME = home;
  delete process.env.CCT_SANDBOX;
  delete process.env.CCT_SANDBOX_OVERRIDE;
  for (const [k, v] of Object.entries(extraEnv)) process.env[k] = v;
  try {
    await activate(pi);
    await handlers["session_start"]?.(null, sessionCtx);
    return await handlers["tool_call"]?.({ toolName: "bash", input: { command: "ls" } }, {});
  } finally {
    for (const k of keys) {
      if (prev[k] === undefined) delete process.env[k];
      else process.env[k] = prev[k];
    }
  }
}

// ── detection ───────────────────────────────────────────────────────────────

test("envProvider maps CCT_SANDBOX declarations to states", () => {
  assert.equal(envProvider.detect({ CCT_SANDBOX: "micro-vm" }).state, "micro-vm");
  assert.equal(envProvider.detect({ CCT_SANDBOX: "remote" }).state, "remote-sandboxed");
  assert.equal(envProvider.detect({ CCT_SANDBOX: "containerized" }).state, "containerized");
  assert.equal(envProvider.detect({}), null);
});

test("dockerProvider detects a container from the env marker", () => {
  const d = dockerProvider.detect({ container: "docker" });
  assert.equal(d.state, "containerized");
  assert.equal(d.provider, "docker");
  assert.ok(d.evidence.length > 0);
});

test("detectSandbox: explicit declaration wins over host sniffing", () => {
  assert.equal(detectSandbox({ CCT_SANDBOX: "remote" }).state, "remote-sandboxed");
});

test("EVAL (T10.4): all 6 FR-019 states are declarable via CCT_SANDBOX and gate-correct", () => {
  // Every FR-019 state (spec.md FR-019) is reachable via declaration. The gate
  // accepts genuine OS sandboxes; host-unrestricted AND permission-gated-only
  // are rejected — permissions are not sandboxing (P5). See
  // specs/pi-harness-adoption/sandbox-backends-eval.md.
  const SANDBOXED = new Set([
    "containerized",
    "micro-vm",
    "remote-sandboxed",
    "external-policy-controlled",
  ]);
  const cases = [
    ["host", "host-unrestricted"],
    ["none", "host-unrestricted"],
    ["permission-gated-only", "permission-gated-only"],
    ["containerized", "containerized"],
    ["micro-vm", "micro-vm"],
    ["remote", "remote-sandboxed"],
    ["remote-sandboxed", "remote-sandboxed"],
    ["external-policy-controlled", "external-policy-controlled"],
  ];
  const seen = new Set();
  for (const [decl, state] of cases) {
    const d = detectSandbox({ CCT_SANDBOX: decl });
    assert.equal(d.state, state, `CCT_SANDBOX=${decl} -> ${state}`);
    seen.add(state);
    const g = sandboxGate(d, {
      sandboxRequired: true,
      rejectUnrestrictedHost: false,
      override: false,
    });
    assert.equal(g.allowed, SANDBOXED.has(state), `gate for ${state}`);
  }
  // All six FR-019 states are exercised.
  for (const st of [
    "host-unrestricted",
    "permission-gated-only",
    "containerized",
    "micro-vm",
    "remote-sandboxed",
    "external-policy-controlled",
  ]) {
    assert.ok(seen.has(st), `FR-019 state ${st} covered`);
  }
});

// ── the gate (pure) ─────────────────────────────────────────────────────────

const HOST = { state: "host-unrestricted", provider: "none", evidence: [] };
const CONTAINER = { state: "containerized", provider: "docker", evidence: ["cgroup"] };

test("REJECT: sandbox required + host-unrestricted + no override -> not allowed", () => {
  const g = sandboxGate(HOST, {
    sandboxRequired: true,
    rejectUnrestrictedHost: false,
    override: false,
  });
  assert.equal(g.allowed, false);
  assert.equal(g.required, true);
  assert.match(g.reason, /host-unrestricted/);
});

test("reject_unrestricted_host alone triggers the rejection", () => {
  const g = sandboxGate(HOST, {
    sandboxRequired: false,
    rejectUnrestrictedHost: true,
    override: false,
  });
  assert.equal(g.allowed, false);
});

test("OVERRIDE: required + host-unrestricted + override -> allowed but recorded", () => {
  const g = sandboxGate(HOST, {
    sandboxRequired: true,
    rejectUnrestrictedHost: false,
    override: true,
  });
  assert.equal(g.allowed, true);
  assert.equal(g.overridden, true);
});

test("a container satisfies the requirement (allowed, not overridden)", () => {
  const g = sandboxGate(CONTAINER, {
    sandboxRequired: true,
    rejectUnrestrictedHost: true,
    override: false,
  });
  assert.equal(g.allowed, true);
  assert.equal(g.overridden, false);
});

test("no sandbox required -> host-unrestricted is allowed", () => {
  const g = sandboxGate(HOST, {
    sandboxRequired: false,
    rejectUnrestrictedHost: false,
    override: false,
  });
  assert.equal(g.allowed, true);
  assert.equal(g.required, false);
});

// ── enforcement through the real runtime tool_call gate ─────────────────────

test("ENFORCE: autonomous profile on an unrestricted host blocks tool execution", async () => {
  const res = await driveTool("autonomous", { CCT_SANDBOX: "host" });
  assert.ok(res && res.block === true, "tool_call must be blocked");
  assert.match(res.reason, /sandbox/i);
});

test("ENFORCE: an explicit override permits execution on an unrestricted host", async () => {
  const res = await driveTool("autonomous", { CCT_SANDBOX: "host", CCT_SANDBOX_OVERRIDE: "1" });
  assert.ok(!res || res.block !== true, "override must not sandbox-block");
});

test("ENFORCE: a container satisfies the requirement (no sandbox block)", async () => {
  const res = await driveTool("autonomous", { CCT_SANDBOX: "containerized" });
  assert.ok(!res || res.block !== true, "containerized must not sandbox-block");
});

test("ENFORCE: a non-sandbox-required profile is not blocked on a host", async () => {
  const res = await driveTool("disciplined", { CCT_SANDBOX: "host" });
  assert.ok(!res || res.block !== true, "no sandbox requirement -> no sandbox block");
});

test("AUDIT: an env-declared sandbox on a required posture is recorded (not invisible)", async () => {
  const home = tmp();
  await driveTool("autonomous", { CCT_SANDBOX: "containerized" }, home);
  const log = fs.readFileSync(path.join(home, "pi", "audit.log"), "utf8");
  assert.match(log, /"decision":"declared"/);
  assert.match(log, /CCT_SANDBOX=containerized/);
  assert.match(log, /"origin":"sandbox"/);
});
