// extension-template.test.mjs — #179 (pi-extension-templates) US1: the
// starter guardrails extension is a WORKING artifact, not prose. Loads the
// shipped template under the same strip-types execution class the runtime
// uses, drives its tool_call gate with a stub pi against the REAL reference
// validator, and enforces the honesty rule (no unverified API tokens in
// template code). Run via tests/test-pi-runtime.sh.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import registerGuardrails from "../../adapters/pi/resources/extension-template/cct-guardrails.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TEMPLATE_DIR = path.join(
  HERE,
  "..",
  "..",
  "adapters",
  "pi",
  "resources",
  "extension-template",
);
const VALIDATOR = path.join(TEMPLATE_DIR, "validators", "check-python-ast.py");

/** Stub pi capturing handlers the way the real runtime registers them. */
function stubPi() {
  const handlers = {};
  const commands = {};
  return {
    handlers,
    commands,
    on(event, fn) {
      handlers[event] = fn;
    },
    registerCommand(name, def) {
      commands[name] = def;
    },
  };
}

async function gate(pi, toolName, filePath) {
  return pi.handlers.tool_call({ toolName, input: { path: filePath } }, {});
}

function withValidatorEnv(fn) {
  const prev = process.env.CCT_VALIDATOR_CMD;
  process.env.CCT_VALIDATOR_CMD = `python3 ${VALIDATOR}`;
  return Promise.resolve()
    .then(fn)
    .finally(() => {
      if (prev === undefined) delete process.env.CCT_VALIDATOR_CMD;
      else process.env.CCT_VALIDATOR_CMD = prev;
    });
}

test("template registers only the verified surfaces", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  assert.deepEqual(Object.keys(pi.handlers).sort(), ["session_start", "tool_call"]);
  assert.deepEqual(Object.keys(pi.commands), ["guardrails:status"]);
});

test("a clean python write passes the gate", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const file = path.join(dir, "ok.py");
    fs.writeFileSync(file, "def fine():\n    return 1\n");
    await withValidatorEnv(async () => {
      const verdict = await gate(pi, "write", file);
      assert.equal(verdict, undefined); // clean -> proceed
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("a syntax error blocks with the validator's report as the reason", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const file = path.join(dir, "bad.py");
    fs.writeFileSync(file, "def broken(:\n");
    await withValidatorEnv(async () => {
      const verdict = await gate(pi, "edit", file);
      assert.equal(verdict.block, true);
      assert.match(verdict.reason, /syntax error/i);
      assert.match(verdict.reason, /bad\.py/); // names the file
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("non-write tools and non-matching extensions are never gated", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  await withValidatorEnv(async () => {
    assert.equal(await gate(pi, "read", "/x/y.py"), undefined);
    assert.equal(await gate(pi, "bash", "/x/y.py"), undefined);
    assert.equal(await gate(pi, "write", "/x/notes.md"), undefined);
  });
});

test("a broken validator fails CLOSED with an actionable reason", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const prev = process.env.CCT_VALIDATOR_CMD;
  process.env.CCT_VALIDATOR_CMD = "/does/not/exist-validator";
  try {
    const verdict = await gate(pi, "write", "/tmp/whatever.py");
    assert.equal(verdict.block, true);
    assert.match(verdict.reason, /failing closed/);
  } finally {
    if (prev === undefined) delete process.env.CCT_VALIDATOR_CMD;
    else process.env.CCT_VALIDATOR_CMD = prev;
  }
});

test("the reference validator honors the contract directly", async () => {
  const { spawnSync } = await import("node:child_process");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const good = path.join(dir, "g.py");
    fs.writeFileSync(good, "x = 1\n");
    const ok = spawnSync("python3", [VALIDATOR, good], { encoding: "utf8" });
    assert.equal(ok.status, 0);
    const bad = path.join(dir, "b.py");
    fs.writeFileSync(bad, "if True\n    pass\n");
    const fail = spawnSync("python3", [VALIDATOR, bad], { encoding: "utf8" });
    assert.notEqual(fail.status, 0);
    assert.ok(fail.stderr.trim().length > 0); // readable report on stderr
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("honesty: no unverified API token appears in template CODE", () => {
  const code = fs.readFileSync(path.join(TEMPLATE_DIR, "cct-guardrails.ts"), "utf8");
  for (const token of ["post_tool_call", "agent_event", "setModel(", "--mode rpc"]) {
    assert.equal(code.includes(token), false, `template code contains '${token}'`);
  }
  // The README's honesty TABLE is the one sanctioned place for those tokens.
  const readme = fs.readFileSync(path.join(TEMPLATE_DIR, "README.md"), "utf8");
  assert.ok(readme.includes("post_tool_call")); // documented, not shipped
});
