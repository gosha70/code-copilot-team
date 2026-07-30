// memory.test.mjs — T9.2 memory promotion/deletion + wiki-first retrieval +
// sensitive-memory controls (FR-017). Run via tests/test-pi-runtime.sh.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  MEMORY_REL,
  containsSecret,
  promoteMemory,
  deleteMemory,
  listMemories,
  recall,
  memkernelStatus,
} from "../../adapters/pi/runtime/workflow/memory.ts";
import activate from "../../adapters/pi/runtime/index.ts";

// Drive activation + session_start, then run `body(commands, cmdCtx, notified)`
// WHILE the env (incl. CCT_HOME, the audit-log root) is still set — so audits
// written by command handlers land under `home`.
async function withMemorySession(cwd, home, body) {
  const commands = {};
  const handlers = {};
  const notified = [];
  const pi = { registerCommand: (n, d) => (commands[n] = d), on: (e, h) => (handlers[e] = h), call: () => {} };
  const cmdCtx = { hasUI: true, ui: { notify: (t) => notified.push(t) } };
  const keys = ["CCT_TEST_BOOTSTRAP", "CCT_PROFILE", "CCT_HOME"];
  const prev = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  process.env.CCT_TEST_BOOTSTRAP = "1";
  process.env.CCT_PROFILE = "disciplined";
  process.env.CCT_HOME = home;
  try {
    await activate(pi);
    await handlers["session_start"]?.(null, {
      cwd,
      isProjectTrusted: () => true,
      hasUI: false,
      mode: "print",
      addContext: () => {},
    });
    await body(commands, cmdCtx, notified);
  } finally {
    for (const k of keys) {
      if (prev[k] === undefined) delete process.env[k];
      else process.env[k] = prev[k];
    }
  }
}

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-mem-"));
}
const PROV = { phase: "build", featureId: "feat-1", at: "2026-07-30T00:00:00Z" };

test("promote/list/delete roundtrip with provenance", () => {
  const root = tmp();
  const r = promoteMemory(root, { type: "project", fact: "the runner stages before diffing", provenance: PROV });
  assert.equal(r.ok, true);
  assert.equal(r.record.type, "project");
  assert.deepEqual(r.record.provenance, PROV);
  const all = listMemories(root);
  assert.equal(all.length, 1);
  assert.ok(fs.existsSync(path.join(root, MEMORY_REL)));
  assert.equal(deleteMemory(root, r.record.id), true);
  assert.equal(listMemories(root).length, 0);
  assert.equal(deleteMemory(root, "nope"), false);
});

test("SENSITIVE: a fact carrying a secret value is REFUSED (fail-closed)", () => {
  const root = tmp();
  for (const secret of [
    "the key is sk-ABCDEF0123456789ABCD",
    "aws AKIAIOSFODNN7EXAMPLE rotates monthly",
    "token=ghp_0123456789abcdef0123456789abcdef0123",
    "password: hunter2hunter2",
  ]) {
    const r = promoteMemory(root, { type: "reference", fact: secret, provenance: PROV });
    assert.equal(r.ok, false, `must refuse: ${secret}`);
    assert.equal(r.refused, true);
  }
  assert.equal(listMemories(root).length, 0, "no secret was stored");
});

test("containsSecret: values yes, mere key words no", () => {
  assert.equal(containsSecret("password: correct-horse-battery"), true);
  assert.equal(containsSecret("sk-ABCDEF0123456789ABCD"), true);
  // Talking ABOUT secrets without a value is fine.
  assert.equal(containsSecret("the api key lives in an env var, never in code"), false);
  assert.equal(containsSecret("we hash the password with argon2"), false);
});

test("empty fact is rejected (not a refusal)", () => {
  const r = promoteMemory(tmp(), { type: "user", fact: "   ", provenance: PROV });
  assert.equal(r.ok, false);
  assert.ok(!r.refused);
});

test("corrupt store -> empty, never throws", () => {
  const root = tmp();
  const file = path.join(root, MEMORY_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, "{ not json");
  assert.deepEqual(listMemories(root), []);
});

test("wiki-first recall: wiki hits precede memory hits", () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, "knowledge", "wiki"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "knowledge", "wiki", "index.md"),
    "- [Sandbox policy](concepts/sandbox.md) — sandbox rejection rules\n- other line\n",
  );
  promoteMemory(root, { type: "project", fact: "sandbox override is audited", provenance: PROV });
  const hits = recall(root, "sandbox");
  assert.ok(hits.length >= 2);
  assert.equal(hits[0].source, "wiki", "wiki-first: canonical layer ranks before memory");
  assert.ok(hits.some((h) => h.source === "memory"));
});

test("recall with no wiki falls back to memories only", () => {
  const root = tmp();
  promoteMemory(root, { type: "feedback", fact: "always show the diff before commit", provenance: PROV });
  const hits = recall(root, "diff");
  assert.equal(hits.length, 1);
  assert.equal(hits[0].source, "memory");
});

test("memkernel adapter reports pending-MCP (not available yet)", () => {
  const s = memkernelStatus({});
  assert.equal(s.available, false);
  assert.equal(s.transport, "mcp");
  assert.match(s.reason, /MCP provider|T10\.2/);
});

test("BEHAVIORAL: /cct:remember stores through the runtime; a secret is refused + audited", async () => {
  const cwd = tmp();
  const home = tmp();
  await withMemorySession(cwd, home, async (commands, cmdCtx, notified) => {
    await commands["cct:remember"].handler(cmdCtx, "project the runner stages before diffing");
    assert.ok(notified.some((t) => /remembered as/.test(t)));
    const stored = listMemories(cwd);
    assert.equal(stored.length, 1);
    assert.equal(stored[0].provenance.phase, "research"); // provenance from live workflow state

    notified.length = 0;
    await commands["cct:remember"].handler(cmdCtx, "reference token=ghp_0123456789abcdef0123456789abcdef0123");
    assert.ok(notified.some((t) => /not remembered/i.test(t)));
    assert.equal(listMemories(cwd).length, 1, "the secret was not stored");

    const log = fs.readFileSync(path.join(home, "pi", "audit.log"), "utf8");
    assert.match(log, /"decision":"refused"/);
    assert.match(log, /"origin":"memory"/);
  });
});
