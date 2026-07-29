// peer-reviewer-enforcement.test.mjs — T3.3/T3.4 (FR-015a). Run via
// tests/test-pi-runtime.sh.
//
// Proves the peer-reviewer reviewer contract is enforced through the REAL
// runtime policy path, not just asserted from profile shape:
//   - write/exec tools denied and a denied command blocked via the permission
//     engine (checkTool/checkCommand) on the resolved peer-reviewer config
//   - the no-recursion guard: a reviewer session is BLOCKED from starting a
//     review (positive), a normal session is NOT blocked (negative) — driven
//     through the runtime's actual /cct:review-submit command handler.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { loadLayeredConfig } from "../../adapters/pi/runtime/config/loader.ts";
import {
  rulesFromConfig,
  checkTool,
  checkCommand,
} from "../../adapters/pi/runtime/policy/permissions.ts";
import activate from "../../adapters/pi/runtime/index.ts";

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-t3-"));
}
function resolved(profile) {
  return loadLayeredConfig({
    globalDir: tmp(),
    projectDir: tmp(),
    trusted: false,
    profile,
  });
}
function rulesFor(profile) {
  const r = resolved(profile);
  return rulesFromConfig((d) => r.resolved.get(d)?.value, false);
}

// ── T3.3 — enforcement through the real permission engine ──────────────────

test("peer-reviewer: write/exec tools are denied by the permission engine", () => {
  const rules = rulesFor("peer-reviewer");
  assert.equal(checkTool(rules, "read").decision, "allow");
  assert.equal(checkTool(rules, "grep").decision, "allow");
  for (const t of ["write", "edit", "bash"]) {
    assert.equal(checkTool(rules, t).decision, "deny", `${t} must be denied`);
  }
});

test("peer-reviewer: a denied command is blocked by the permission engine", () => {
  const rules = rulesFor("peer-reviewer");
  // peer-reviewer imports balanced (T5.2), whose denies include sudo/rm -rf.
  assert.notEqual(checkCommand(rules, "sudo rm -rf /").decision, "allow");
  assert.equal(rules.allowPackageInstall, false, "package install disabled");
});

// ── T3.4 — no-recursion, driven through the real command handler ───────────

async function driveReviewSubmit(profile) {
  const commands = {};
  const handlers = {};
  const captured = [];
  const pi = {
    registerCommand: (name, def) => {
      commands[name] = def;
    },
    on: (event, handler) => {
      handlers[event] = handler;
    },
    call: () => {},
  };
  const cmdCtx = { hasUI: true, ui: { notify: (t) => captured.push(t) } };

  const home = tmp();
  const cwd = tmp();
  // session_start ctx: config is loaded here (not at activation time).
  const sessionCtx = {
    cwd,
    isProjectTrusted: () => false,
    hasUI: false,
    mode: "print",
    addContext: () => {},
    injectContext: () => {},
  };
  const prev = {
    CCT_TEST_BOOTSTRAP: process.env.CCT_TEST_BOOTSTRAP,
    CCT_PROFILE: process.env.CCT_PROFILE,
    CCT_HOME: process.env.CCT_HOME,
  };
  process.env.CCT_TEST_BOOTSTRAP = "1";
  process.env.CCT_PROFILE = profile;
  process.env.CCT_HOME = home;
  try {
    await activate(pi);
    // Fire session_start so the runtime loads config for this profile.
    await handlers["session_start"]?.(null, sessionCtx);
    // Set an active feature so review-submit reaches the recursion guard.
    await commands["cct:phase"].handler(cmdCtx, "research feat-1");
    captured.length = 0; // discard phase output
    await commands["cct:review-submit"].handler(cmdCtx, "");
  } finally {
    for (const [k, v] of Object.entries(prev)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
  return captured.join("\n");
}

test("no-recursion POSITIVE: a peer-reviewer session cannot start a review", async () => {
  const out = await driveReviewSubmit("peer-reviewer");
  assert.match(out, /review blocked/i);
  assert.match(out, /allow_recursive/);
});

test("no-recursion NEGATIVE: a normal session is not blocked by the recursion guard", async () => {
  const out = await driveReviewSubmit("disciplined");
  assert.doesNotMatch(out, /review blocked/i);
  assert.match(out, /review round/i); // proceeds into the review path
});
