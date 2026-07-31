// child-session.test.mjs — T7.2 out-of-process subagent runner (FR-011). Run
// via tests/test-pi-runtime.sh.
//
// Two layers: the pure buildChildArgv translator (manifest -> pi flags +
// notEnforced), and runChildSession end-to-end against a mock `pi` that echoes
// its argv and can sleep/fail — proving the flags are actually passed, the
// timeout/cancel paths kill the child, and the JSON envelope is parsed.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  buildChildArgv,
  mapThinking,
  runChildSession,
} from "../../adapters/pi/runtime/agents/child-session.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MOCK_PI = path.join(HERE, "fixtures", "mock-pi.mjs");

function manifest(overrides = {}) {
  return {
    name: "worker",
    description: "a subagent",
    model: "inherit",
    thinking: "inherit",
    tools: [],
    skills: [],
    context: [],
    permissions: "inherit",
    source: "authored",
    declaredNotSourced: [],
    ...overrides,
  };
}

function opts(m, overrides = {}) {
  return {
    manifest: m,
    prompt: "do the thing",
    cwd: os.tmpdir(),
    correlationId: "corr-1",
    timeoutSec: 5,
    depth: 0,
    maxRecursion: 2,
    ...overrides,
  };
}

// ── pure translator ──────────────────────────────────────────────────────────

test("mapThinking: inherit omits, none->off, rest identity", () => {
  assert.equal(mapThinking("inherit"), null);
  assert.equal(mapThinking("none"), "off");
  assert.equal(mapThinking("low"), "low");
  assert.equal(mapThinking("medium"), "medium");
  assert.equal(mapThinking("high"), "high");
});

test("buildChildArgv: base flags + isolation, no overrides when inherit", () => {
  const { args } = buildChildArgv(opts(manifest()));
  assert.deepEqual(args, ["--mode", "json", "-p", "do the thing", "--no-session"]);
});

test("buildChildArgv: model/thinking/tools become pi flags", () => {
  const { args } = buildChildArgv(
    opts(manifest({ model: "opus", thinking: "high", tools: ["read", "bash"] })),
  );
  assert.ok(args.includes("--model") && args[args.indexOf("--model") + 1] === "opus");
  assert.ok(args.includes("--thinking") && args[args.indexOf("--thinking") + 1] === "high");
  assert.ok(args.includes("--tools") && args[args.indexOf("--tools") + 1] === "read,bash");
});

test("buildChildArgv: none maps to --thinking off", () => {
  const { args } = buildChildArgv(opts(manifest({ thinking: "none" })));
  assert.equal(args[args.indexOf("--thinking") + 1], "off");
});

test("buildChildArgv: permissions/skills/context reported notEnforced, not dropped", () => {
  const { args, notEnforced } = buildChildArgv(
    opts(manifest({ permissions: "build", skills: ["x"], context: ["always"] })),
  );
  assert.deepEqual(notEnforced.sort(), ["context", "permissions", "skills"]);
  // and none of them leaked into the argv
  assert.ok(!args.includes("build") && !args.includes("--permissions"));
});

test("buildChildArgv: inherit/empty fields produce an empty notEnforced", () => {
  assert.deepEqual(buildChildArgv(opts(manifest())).notEnforced, []);
});

test("buildChildArgv: correlation id + incremented depth in child env", () => {
  const { env } = buildChildArgv(opts(manifest(), { depth: 1, correlationId: "abc" }));
  assert.equal(env.CCT_AGENT_CORRELATION_ID, "abc");
  assert.equal(env.CCT_AGENT_DEPTH, "2");
});

// ── runner (mock pi) ─────────────────────────────────────────────────────────

// The mock is an executable .mjs (shebang + chmod +x), so runnerPath: MOCK_PI
// spawns it directly. Behaviour is driven by env vars the mock reads; withMock
// sets them and returns a restore() to unwind process.env.
function withMock(mockEnv = {}) {
  const argvOut = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cct-cs-")), "argv.json");
  const prev = {};
  const env = { MOCK_PI_ARGV_OUT: argvOut, ...mockEnv };
  for (const [k, v] of Object.entries(env)) {
    prev[k] = process.env[k];
    process.env[k] = v;
  }
  return {
    argvOut,
    restore: () => {
      for (const k of Object.keys(env)) {
        if (prev[k] === undefined) delete process.env[k];
        else process.env[k] = prev[k];
      }
    },
  };
}

test("runChildSession: happy path parses the JSON envelope + passes flags", async () => {
  const { argvOut, restore } = withMock();
  try {
    const r = await runChildSession(opts(manifest({ model: "opus", thinking: "high", tools: ["read"] })), {
      runnerPath: MOCK_PI,
    });
    assert.equal(r.status, "ok", r.reason);
    assert.equal(r.ran, true);
    assert.equal(r.exitCode, 0);
    assert.equal(r.sessionId, "sess-mock");
    assert.equal(r.subtype, "success");
    assert.equal(r.costUsd, 0.01);
    const passed = JSON.parse(fs.readFileSync(argvOut, "utf8"));
    assert.ok(passed.includes("--model") && passed[passed.indexOf("--model") + 1] === "opus");
    assert.ok(passed.includes("--thinking") && passed[passed.indexOf("--thinking") + 1] === "high");
    assert.ok(passed.includes("--no-session"));
  } finally {
    restore();
  }
});

test("runChildSession: recursion cap short-circuits before any spawn", async () => {
  const { argvOut, restore } = withMock();
  try {
    const r = await runChildSession(opts(manifest(), { depth: 2, maxRecursion: 2 }), {
      runnerPath: MOCK_PI,
    });
    assert.equal(r.status, "cap-exceeded");
    assert.equal(r.ran, false);
    assert.ok(!fs.existsSync(argvOut), "no child should have been spawned");
  } finally {
    restore();
  }
});

test("runChildSession: a wall-clock timeout kills the child -> status timeout", async () => {
  const { restore } = withMock({ MOCK_PI_SLEEP_MS: "10000" });
  try {
    const r = await runChildSession(opts(manifest(), { timeoutSec: 1 }), {
      runnerPath: MOCK_PI,
    });
    assert.equal(r.status, "timeout", r.reason);
  } finally {
    restore();
  }
});

test("runChildSession: AbortSignal cancels the child -> status cancelled", async () => {
  const { restore } = withMock({ MOCK_PI_SLEEP_MS: "10000" });
  try {
    const ac = new AbortController();
    const p = runChildSession(opts(manifest(), { timeoutSec: 30 }), {
      runnerPath: MOCK_PI,
      signal: ac.signal,
    });
    setTimeout(() => ac.abort(), 100);
    const r = await p;
    assert.equal(r.status, "cancelled", r.reason);
  } finally {
    restore();
  }
});

test("runChildSession: a missing runner reports no-runner (not a crash)", async () => {
  const r = await runChildSession(opts(manifest()), {
    runnerPath: "/nonexistent/pi-binary-xyz",
  });
  assert.equal(r.status, "no-runner");
  assert.equal(r.ran, false);
});

test("runChildSession: nonzero exit with no envelope -> status error", async () => {
  const { restore } = withMock({ MOCK_PI_EXIT: "3", MOCK_PI_NO_ENVELOPE: "1" });
  try {
    const r = await runChildSession(opts(manifest()), { runnerPath: MOCK_PI });
    assert.equal(r.status, "error", r.reason);
    assert.equal(r.exitCode, 3);
  } finally {
    restore();
  }
});

test("runChildSession: nonzero exit WITH an envelope is still error (not ok)", async () => {
  // A failed child that nonetheless printed a result envelope must not be
  // reported ok; the envelope fields survive as diagnostics.
  const { restore } = withMock({ MOCK_PI_EXIT: "3" });
  try {
    const r = await runChildSession(opts(manifest()), { runnerPath: MOCK_PI });
    assert.equal(r.status, "error", r.reason);
    assert.equal(r.exitCode, 3);
    assert.equal(r.subtype, "success"); // preserved as diagnostic
    assert.equal(r.sessionId, "sess-mock");
    assert.equal(r.costUsd, 0.01);
  } finally {
    restore();
  }
});
