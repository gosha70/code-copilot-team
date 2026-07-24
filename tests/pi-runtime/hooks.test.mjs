// hooks.test.mjs — Unit tests for the T5.1 lifecycle-event schema, Pi->CCT
// translators, and the shell-hook subprocess adapter (FR-010).
//
// Run via tests/test-pi-runtime.sh (node --experimental-strip-types --test).
//
// Covers: the neutral CctLifecycleEvent schema + mapping matrix (only
// SessionStart/PreToolUse supported, Notification degraded, rest unsupported),
// translators + Claude-Code-shaped stdin serialization, and the subprocess
// adapter's support gate, exit-code veto convention, timeout, retry, and
// fail-open/fail-closed disposition — each audited.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  HOOK_MAPPINGS,
  hookMappingReport,
  supportOf,
  toClaudeStdin,
  translateSessionStart,
  translateToolCall,
} from "../../adapters/pi/runtime/hooks/events.ts";
import {
  dispatchHooks,
  resolveHookScripts,
  resolveHookScriptsDir,
} from "../../adapters/pi/runtime/hooks/adapter.ts";

const SESSION = { interactive: false, mode: "print" };

function tmpdir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-hooks-"));
}

function writeScript(dir, name, body) {
  const p = path.join(dir, name);
  fs.writeFileSync(p, `#!/usr/bin/env bash\n${body}\n`);
  fs.chmodSync(p, 0o755);
  return p;
}

function spyAudit() {
  const records = [];
  return { records, fn: (rec) => records.push(rec) };
}

// ── Schema + mapping matrix ────────────────────────────────────────────────

test("mapping matrix: only SessionStart and PreToolUse are supported", () => {
  const byEvent = Object.fromEntries(HOOK_MAPPINGS.map((m) => [m.event, m]));
  assert.equal(byEvent.SessionStart.support, "supported");
  assert.equal(byEvent.SessionStart.piSource, "session_start");
  assert.equal(byEvent.PreToolUse.support, "supported");
  assert.equal(byEvent.PreToolUse.piSource, "tool_call");
  assert.equal(byEvent.Notification.support, "degraded");
  assert.equal(byEvent.Notification.piSource, null);
  for (const e of ["PostToolUse", "Stop", "PreCompact", "PostCompact"]) {
    assert.equal(byEvent[e].support, "unsupported", `${e} must be unsupported`);
    assert.equal(byEvent[e].piSource, null);
  }
});

test("supportOf resolves per-event and defaults unsupported", () => {
  assert.equal(supportOf("PreToolUse"), "supported");
  assert.equal(supportOf("Notification"), "degraded");
  assert.equal(supportOf("Stop"), "unsupported");
});

test("hookMappingReport lists every neutral event", () => {
  const report = hookMappingReport().join("\n");
  for (const m of HOOK_MAPPINGS) assert.match(report, new RegExp(m.event));
});

// ── Translators + stdin shape ──────────────────────────────────────────────

test("translateSessionStart produces a supported SessionStart event", () => {
  const ev = translateSessionStart("/proj", SESSION);
  assert.equal(ev.event, "SessionStart");
  assert.equal(ev.phase, "session");
  assert.equal(ev.support, "supported");
  assert.equal(ev.origin, "pi");
});

test("translateToolCall maps write/exec tools to PreToolUse + matcher", () => {
  const w = translateToolCall("edit", { path: "/x/.env" }, "/proj", SESSION);
  assert.equal(w.event, "PreToolUse");
  assert.equal(w.tool, "edit");
  assert.equal(w.matcher, "Edit|Write");
  assert.equal(w.support, "supported");

  const b = translateToolCall("bash", { command: "ls" }, "/proj", SESSION);
  assert.equal(b.tool, "bash");
  assert.equal(b.matcher, "Bash");
});

test("toClaudeStdin normalizes Pi input keys to Claude Code fields", () => {
  const w = translateToolCall("write", { file_path: "/a/b" }, "/p", SESSION);
  const jw = JSON.parse(toClaudeStdin(w));
  assert.equal(jw.hook_event_name, "PreToolUse");
  assert.equal(jw.tool_name, "Write");
  assert.equal(jw.tool_input.file_path, "/a/b");
  assert.equal(jw.cwd, "/p");

  // Pi variants: path / cmd normalize to file_path / command.
  const alt = translateToolCall("edit", { path: "/z" }, "/p", SESSION);
  assert.equal(JSON.parse(toClaudeStdin(alt)).tool_input.file_path, "/z");
  const bash = translateToolCall("bash", { cmd: "git push" }, "/p", SESSION);
  const jb = JSON.parse(toClaudeStdin(bash));
  assert.equal(jb.tool_name, "Bash");
  assert.equal(jb.tool_input.command, "git push");
});

// ── Adapter: exit-code veto convention ─────────────────────────────────────

test("adapter: exit 0 allows, outcome + audit recorded", () => {
  const dir = tmpdir();
  const allow = writeScript(dir, "allow.sh", "exit 0");
  const ev = translateToolCall("edit", { path: "/ok" }, "/p", SESSION);
  const spy = spyAudit();
  const res = dispatchHooks(ev, [{ path: allow }], {}, spy.fn);
  assert.equal(res.block, false);
  assert.equal(res.ran, true);
  assert.equal(res.outcomes[0].status, "allow");
  assert.equal(spy.records[0].decision, "allow");
  assert.equal(spy.records[0].origin, "shell-hook");
});

test("adapter: exit 2 blocks with stderr as reason", () => {
  const dir = tmpdir();
  const block = writeScript(dir, "block.sh", 'echo "protected file" >&2; exit 2');
  const ev = translateToolCall("edit", { path: "/x/.env" }, "/p", SESSION);
  const spy = spyAudit();
  const res = dispatchHooks(ev, [{ path: block }], {}, spy.fn);
  assert.equal(res.block, true);
  assert.match(res.reason, /protected file/);
  assert.equal(spy.records[0].decision, "block");
});

// ── Adapter: support gate (no approximation) ───────────────────────────────

test("adapter: unsupported/degraded events are skipped, never executed", () => {
  const dir = tmpdir();
  const marker = path.join(dir, "ran.txt");
  const shouldNotRun = writeScript(dir, "mark.sh", `echo ran > "${marker}"; exit 2`);

  for (const support of ["unsupported", "degraded"]) {
    const ev = {
      event: "Stop",
      phase: "post",
      cwd: "/p",
      session: SESSION,
      origin: "pi",
      support,
    };
    const spy = spyAudit();
    const res = dispatchHooks(ev, [{ path: shouldNotRun }], {}, spy.fn);
    assert.equal(res.ran, false);
    assert.equal(res.block, false);
    assert.equal(spy.records[0].decision, `skipped-${support}`);
    assert.equal(spy.records[0].rule, "hook.support-gate");
  }
  assert.equal(fs.existsSync(marker), false, "gated hook must not execute");
});

// ── Adapter: fail-open / fail-closed on error ──────────────────────────────

test("adapter: non-0/2 exit is fail-closed block or fail-open allow", () => {
  const dir = tmpdir();
  const err = writeScript(dir, "err.sh", "exit 1");
  const ev = translateToolCall("edit", { path: "/x" }, "/p", SESSION);

  const closed = dispatchHooks(ev, [{ path: err }], { failMode: "closed" }, () => {});
  assert.equal(closed.block, true);
  assert.match(closed.reason, /fail-closed/);

  const open = dispatchHooks(ev, [{ path: err }], { failMode: "open" }, () => {});
  assert.equal(open.block, false);
  assert.match(open.outcomes[0].reason, /fail-open/);
});

// ── Adapter: timeout ───────────────────────────────────────────────────────

test("adapter: a hook exceeding its timeout is treated per fail mode", () => {
  const dir = tmpdir();
  const slow = writeScript(dir, "slow.sh", "sleep 2; exit 0");
  const ev = translateToolCall("edit", { path: "/x" }, "/p", SESSION);
  const res = dispatchHooks(
    ev,
    [{ path: slow, timeoutMs: 100 }],
    { failMode: "closed" },
    () => {},
  );
  assert.equal(res.block, true);
  assert.match(res.reason, /timed out/);
});

// ── Adapter: bounded retry ─────────────────────────────────────────────────

test("adapter: retries re-run the hook (retries + 1 attempts)", () => {
  const dir = tmpdir();
  const counter = path.join(dir, "count.txt");
  const flaky = writeScript(dir, "flaky.sh", `echo x >> "${counter}"; exit 1`);
  const ev = translateToolCall("edit", { path: "/x" }, "/p", SESSION);
  dispatchHooks(ev, [{ path: flaky }], { retries: 2, failMode: "open" }, () => {});
  const runs = fs.readFileSync(counter, "utf8").trim().split("\n").length;
  assert.equal(runs, 3, "retries:2 => 3 total attempts");
});

// ── Script resolution (reuse existing Claude Code hooks) ───────────────────

test("resolveHookScripts maps PreToolUse tools to existing veto scripts", () => {
  const dir = tmpdir();
  const pf = writeScript(dir, "protect-files.sh", "exit 0");
  writeScript(dir, "protect-git.sh", "exit 0");

  const edit = translateToolCall("edit", { path: "/x" }, "/p", SESSION);
  assert.deepEqual(resolveHookScripts(edit, dir), [{ path: pf }]);

  const bash = translateToolCall("bash", { command: "ls" }, "/p", SESSION);
  assert.equal(resolveHookScripts(bash, dir)[0].path, path.join(dir, "protect-git.sh"));

  // No scripts dir, or a non-veto event, resolves to nothing.
  assert.deepEqual(resolveHookScripts(edit, null), []);
  const ss = translateSessionStart("/p", SESSION);
  assert.deepEqual(resolveHookScripts(ss, dir), []);
});

test("resolveHookScriptsDir honors CCT_HOOK_SCRIPTS_DIR when it exists", () => {
  const dir = tmpdir();
  const prev = process.env.CCT_HOOK_SCRIPTS_DIR;
  try {
    process.env.CCT_HOOK_SCRIPTS_DIR = dir;
    assert.equal(resolveHookScriptsDir(null), dir);
    process.env.CCT_HOOK_SCRIPTS_DIR = path.join(dir, "does-not-exist");
    assert.equal(resolveHookScriptsDir(null), null);
  } finally {
    if (prev === undefined) delete process.env.CCT_HOOK_SCRIPTS_DIR;
    else process.env.CCT_HOOK_SCRIPTS_DIR = prev;
  }
});
