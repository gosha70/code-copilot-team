// session-recovery.test.mjs — T9.1 recovery wiring (FR-017). Run via
// tests/test-pi-runtime.sh.
//
// Drives the runtime activation + session_start with a mock pi, proving:
//   - a pre-existing checkpoint is re-injected (recovery digest) into context
//     and reported as a warning at session_start;
//   - no checkpoint -> no recovery injection (clean start);
//   - /cct:checkpoint writes a durable checkpoint.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import activate from "../../adapters/pi/runtime/index.ts";
import { loadCheckpoint, writeCheckpoint } from "../../adapters/pi/runtime/workflow/checkpoint.ts";

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-rec-"));
}

async function drive(cwd) {
  const commands = {};
  const handlers = {};
  const injected = [];
  const notified = [];
  const pi = {
    registerCommand: (name, def) => (commands[name] = def),
    on: (event, handler) => (handlers[event] = handler),
    call: () => {},
  };
  const sessionCtx = {
    cwd,
    isProjectTrusted: () => false,
    hasUI: false,
    mode: "print",
    addContext: (t) => injected.push(t),
  };
  const cmdCtx = { hasUI: true, ui: { notify: (t) => notified.push(t) } };

  const prev = {
    CCT_TEST_BOOTSTRAP: process.env.CCT_TEST_BOOTSTRAP,
    CCT_PROFILE: process.env.CCT_PROFILE,
    CCT_HOME: process.env.CCT_HOME,
  };
  process.env.CCT_TEST_BOOTSTRAP = "1";
  process.env.CCT_PROFILE = "disciplined";
  process.env.CCT_HOME = tmp();
  try {
    await activate(pi);
    await handlers["session_start"]?.(null, sessionCtx);
  } finally {
    for (const [k, v] of Object.entries(prev)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
  return { commands, injected, notified, cmdCtx };
}

test("recovery: a pre-existing checkpoint is re-injected + reported at session_start", async () => {
  const cwd = tmp();
  writeCheckpoint(cwd, { phase: "build", featureId: "feat-9" }, "2026-07-29T00:00:00Z");
  const { injected } = await drive(cwd);
  // The recovery digest — with the feature, phase, and the compaction-
  // preservation prompt — must be re-injected into the resumed session's
  // context (the mechanism that lets the model re-learn CCT state).
  const digest = injected.find((t) => t.includes("CCT session recovery"));
  assert.ok(digest, "recovery digest must be injected into context");
  assert.match(digest, /feat-9/);
  assert.match(digest, /build/);
  assert.match(digest, /checkpoint #1/);
  assert.match(digest, /CCT compaction guidance/);
});

test("no checkpoint -> clean start (no recovery injection)", async () => {
  const { injected, notified } = await drive(tmp());
  assert.ok(!injected.some((t) => t.includes("CCT session recovery")));
  assert.ok(!notified.some((t) => t.includes("session recovery")));
});

test("/cct:checkpoint writes a durable checkpoint", async () => {
  const cwd = tmp();
  const { commands, cmdCtx, notified } = await drive(cwd);
  notified.length = 0;
  await commands["cct:checkpoint"].handler(cmdCtx);
  assert.ok(notified.some((t) => /checkpoint #1 saved/.test(t)));
  assert.ok(loadCheckpoint(cwd), "checkpoint file must exist after /cct:checkpoint");
});
