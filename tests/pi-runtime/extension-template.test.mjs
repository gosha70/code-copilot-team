// extension-template.test.mjs — #179 (pi-extension-templates) US1: the
// starter guardrails extension is a WORKING artifact. Drives the shipped
// template + shipped validator through BOTH gates with a stub pi, covering
// the cases the phase-1 review proved matter: a fresh `write` of broken
// content is blocked BEFORE disk, a valid->garbage overwrite is blocked, an
// edit that REPAIRS a broken file passes (no legacy deadlock), post-edit
// failures patch the tool result, validator-error vs violation are kept
// distinct, warn-and-allow provably warns, a hung validator times out into
// the validator-error lane, relative post-gate paths resolve against
// ctx.cwd, and the honesty table is checked against the INSTALLED pi
// package (visible skip when pi is absent). Run via tests/test-pi-runtime.sh.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
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

const preGate = (pi, input) =>
  pi.handlers.tool_call({ type: "tool_call", toolCallId: "t1", toolName: "write", input }, {});
const postGate = (pi, toolName, input, isError = false) =>
  pi.handlers.tool_result(
    { type: "tool_result", toolCallId: "t1", toolName, input, content: [], isError },
    {},
  );

function withValidatorEnv(fn, cmd = `python3 ${VALIDATOR}`) {
  const prev = process.env.GUARDRAILS_VALIDATOR_CMD;
  process.env.GUARDRAILS_VALIDATOR_CMD = cmd;
  return Promise.resolve()
    .then(fn)
    .finally(() => {
      if (prev === undefined) delete process.env.GUARDRAILS_VALIDATOR_CMD;
      else process.env.GUARDRAILS_VALIDATOR_CMD = prev;
    });
}

test("registers exactly the surfaces it documents", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  assert.deepEqual(
    Object.keys(pi.handlers).sort(),
    ["session_start", "tool_call", "tool_result"],
  );
  assert.deepEqual(Object.keys(pi.commands), ["guardrails:status"]);
  // The status handler runs (console path) — not just registration shape.
  await pi.commands["guardrails:status"].handler({}, {});
});

test("PRE-WRITE: broken incoming content for a NEW file is blocked before disk", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const target = path.join(dir, "new_module.py"); // does NOT exist
    await withValidatorEnv(async () => {
      const verdict = await preGate(pi, { path: target, content: "def broken(:\n" });
      assert.equal(verdict.block, true);
      assert.match(verdict.reason, /pre-write validation failed/);
      assert.match(verdict.reason, /syntax error/i);
    });
    assert.equal(fs.existsSync(target), false); // never reached disk
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("PRE-WRITE: overwriting a valid file with garbage is blocked; clean content passes", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const target = path.join(dir, "good.py");
    fs.writeFileSync(target, "x = 1\n"); // valid on disk
    await withValidatorEnv(async () => {
      const bad = await preGate(pi, { path: target, content: "def x(:\n" });
      assert.equal(bad.block, true); // incoming CONTENT is what is judged
      const ok = await preGate(pi, { path: target, content: "def fine():\n    return 1\n" });
      assert.equal(ok, undefined);
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("POST-EDIT: repairing an already-broken file PASSES (no legacy deadlock)", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const target = path.join(dir, "legacy.py");
    // Simulate the post-execution state: the agent's edit REPAIRED the file.
    fs.writeFileSync(target, "def repaired():\n    return 1\n");
    await withValidatorEnv(async () => {
      const verdict = await postGate(pi, "edit", { path: target });
      assert.equal(verdict, undefined); // post-state is valid -> pass
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("POST-EDIT: a still-broken result is patched to an error with the report", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const target = path.join(dir, "still_bad.py");
    fs.writeFileSync(target, "def broken(:\n");
    await withValidatorEnv(async () => {
      const verdict = await postGate(pi, "edit", { path: target });
      assert.equal(verdict.isError, true);
      assert.equal(verdict.content[0].type, "text");
      assert.match(verdict.content[0].text, /post-edit validation failed/);
      assert.match(verdict.content[0].text, /syntax error/i);
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("scoping: non-gated tools, other extensions, and failed tools are untouched", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  await withValidatorEnv(async () => {
    assert.equal(
      await pi.handlers.tool_call(
        { type: "tool_call", toolCallId: "t", toolName: "read", input: { path: "/x.py" } },
        {},
      ),
      undefined,
    );
    assert.equal(await preGate(pi, { path: "/x/notes.md", content: "def broken(:" }), undefined);
    assert.equal(await postGate(pi, "bash", { path: "/x.py" }), undefined);
    // A tool that already errored is left alone.
    assert.equal(await postGate(pi, "edit", { path: "/nonexistent.py" }, true), undefined);
  });
});

test("a broken validator is a VALIDATOR error (fail-closed), never a code violation", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  await withValidatorEnv(async () => {
    const verdict = await preGate(pi, { path: "/tmp/x.py", content: "x = 1\n" });
    assert.equal(verdict.block, true);
    assert.match(verdict.reason, /validator could not run/);
    assert.doesNotMatch(verdict.reason, /Correct the violations/);
  }, "/does/not/exist-validator");
});

test("validator usage error (exit 2) is a validator error, not a violation", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  // No file argument appended twice — force exit 2 by giving a validator
  // command that already carries a bogus extra arg.
  await withValidatorEnv(async () => {
    const verdict = await preGate(pi, { path: "/tmp/x.py", content: "x = 1\n" });
    assert.equal(verdict.block, true);
    assert.match(verdict.reason, /validator could not run/);
  }, `python3 ${VALIDATOR} extra-arg`);
});

test("the reference validator honors the contract directly (incl. --)", async () => {
  const { spawnSync } = await import("node:child_process");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const good = path.join(dir, "g.py");
    fs.writeFileSync(good, "x = 1\n");
    assert.equal(spawnSync("python3", [VALIDATOR, "--", good], { encoding: "utf8" }).status, 0);
    const bad = path.join(dir, "b.py");
    fs.writeFileSync(bad, "if True\n    pass\n");
    const fail = spawnSync("python3", [VALIDATOR, "--", bad], { encoding: "utf8" });
    assert.equal(fail.status, 1); // violation is exactly 1
    assert.ok(fail.stderr.trim().length > 0);
    // The shipped file is executable (shebang usable as a direct command).
    assert.ok(fs.statSync(VALIDATOR).mode & 0o111);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("honesty: template code never uses names pi does not ship", () => {
  const code = fs.readFileSync(path.join(TEMPLATE_DIR, "cct-guardrails.ts"), "utf8");
  assert.equal(code.includes("agent_event"), false);
  assert.equal(code.includes("post_tool_call"), false); // pi's name is tool_result
});

/** Locate the installed pi package: local resolution, then the global npm
 * root (both the execPath-derived layout and `npm root -g`). */
function resolvePiPackage() {
  try {
    const require = createRequire(import.meta.url);
    return require.resolve("@earendil-works/pi-coding-agent/package.json", {
      paths: [process.cwd(), os.homedir()],
    });
  } catch {
    /* fall through to the global roots */
  }
  const candidates = [
    path.join(path.dirname(process.execPath), "..", "lib", "node_modules"),
  ];
  for (const root of candidates) {
    const p = path.join(root, "@earendil-works", "pi-coding-agent", "package.json");
    if (fs.existsSync(p)) return p;
  }
  return null;
}

test("honesty canary: the README table matches the INSTALLED pi package", async (t) => {
  const pkgPath = resolvePiPackage();
  if (!pkgPath) {
    t.skip("pi package not resolvable — honesty-table canary not verified on this host");
    return;
  }
  const pkgDir = path.dirname(pkgPath);
  const installed = JSON.parse(fs.readFileSync(pkgPath, "utf8")).version;
  const types = fs.readFileSync(
    path.join(pkgDir, "dist", "core", "extensions", "types.d.ts"),
    "utf8",
  );
  const readme = fs.readFileSync(path.join(TEMPLATE_DIR, "README.md"), "utf8");

  // The table names the version it was verified against; it must match the
  // installed package (upgrading pi is SUPPOSED to trip this — that is the
  // re-verify-on-upgrade contract).
  assert.ok(
    readme.includes(`pi ${installed}`),
    `README table cites a different pi version than the installed ${installed} — re-verify the table`,
  );
  // Row 1: tool_result is a shipped event.
  assert.ok(types.includes('on(event: "tool_result"'));
  assert.match(readme, /`tool_result` event/);
  // Row 2: setModel exists; agent_event does not.
  assert.ok(types.includes("setModel("));
  assert.equal(types.includes('on(event: "agent_event"'), false);
  assert.match(readme, /no `agent_event` event/);
  // Row 4: auto-discovery documented as supported + trust-gated.
  assert.match(readme, /auto-discovery \| \*\*supported, trust-gated\*\*/);
});

test("warn-and-allow WARNS (never silent) when the validator cannot run", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const warnings = [];
  const origWarn = console.warn;
  console.warn = (msg) => warnings.push(String(msg));
  const prevFC = process.env.GUARDRAILS_FAIL_CLOSED;
  process.env.GUARDRAILS_FAIL_CLOSED = "false";
  try {
    await withValidatorEnv(async () => {
      const verdict = await preGate(pi, { path: "/tmp/x.py", content: "x = 1\n" });
      assert.equal(verdict, undefined); // allowed through...
    }, "/does/not/exist-validator");
    assert.equal(warnings.length, 1); // ...but never silently
    assert.match(warnings[0], /proceeding WITHOUT validation/);
  } finally {
    console.warn = origWarn;
    if (prevFC === undefined) delete process.env.GUARDRAILS_FAIL_CLOSED;
    else process.env.GUARDRAILS_FAIL_CLOSED = prevFC;
  }
});

test("a hung validator times out into a validator-error (fail-closed)", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const prevT = process.env.GUARDRAILS_TIMEOUT_MS;
  process.env.GUARDRAILS_TIMEOUT_MS = "200";
  // A sleeper SCRIPT (the whitespace-split env var cannot express a
  // spaced -c program — the documented limitation).
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  const sleeper = path.join(dir, "sleeper.sh");
  fs.writeFileSync(sleeper, "#!/bin/sh\nsleep 60\n");
  fs.chmodSync(sleeper, 0o755);
  try {
    await withValidatorEnv(async () => {
      const verdict = await preGate(pi, { path: "/tmp/x.py", content: "x = 1\n" });
      assert.equal(verdict.block, true);
      assert.match(verdict.reason, /validator could not run/);
    }, sleeper);
  } finally {
    if (prevT === undefined) delete process.env.GUARDRAILS_TIMEOUT_MS;
    else process.env.GUARDRAILS_TIMEOUT_MS = prevT;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("POST gate resolves relative paths against ctx.cwd (no silent fail-open)", async () => {
  const pi = stubPi();
  await registerGuardrails(pi);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    fs.writeFileSync(path.join(dir, "rel_bad.py"), "def broken(:\n");
    await withValidatorEnv(async () => {
      const verdict = await pi.handlers.tool_result(
        {
          type: "tool_result",
          toolCallId: "t1",
          toolName: "edit",
          input: { path: "rel_bad.py" }, // RELATIVE — pi documents this
          content: [],
          isError: false,
        },
        { cwd: dir },
      );
      assert.equal(verdict.isError, true); // resolved + validated, not skipped
      assert.match(verdict.content[0].text, /syntax error/i);
    });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("non-UTF-8 content is a validator error, not a code violation", async () => {
  const { spawnSync } = await import("node:child_process");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-ext-"));
  try {
    const f = path.join(dir, "latin1.py");
    fs.writeFileSync(f, Buffer.from([0x78, 0x20, 0x3d, 0x20, 0xff, 0x0a]));
    const run = spawnSync("python3", [VALIDATOR, "--", f], { encoding: "utf8" });
    assert.equal(run.status, 2); // validator-error lane, never "fix your code"
    assert.match(run.stderr, /not UTF-8/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
