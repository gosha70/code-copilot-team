// mcp.test.mjs — T10.2 MCP provider interface + first audited backend (FR-018).
// Run via tests/test-pi-runtime.sh.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  MEMKERNEL_BACKEND,
  probeBackend,
  mcpReport,
  resolveMcpBackends,
} from "../../adapters/pi/runtime/policy/mcp.ts";

function tmpBinWith(name) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-mcp-"));
  const exe = path.join(dir, name);
  fs.writeFileSync(exe, "#!/bin/sh\nexit 0\n");
  fs.chmodSync(exe, 0o755);
  return dir;
}

test("built-in MemKernel backend is external-package with the memory tools", () => {
  assert.equal(MEMKERNEL_BACKEND.mode, "external-package");
  assert.deepEqual(MEMKERNEL_BACKEND.tools, ["retain", "recall", "get", "forget"]);
  assert.equal(MEMKERNEL_BACKEND.source, "built-in");
});

test("probe: reachable when the command is on PATH (no spawn)", () => {
  const bin = tmpBinWith("memkernel");
  const p = probeBackend(MEMKERNEL_BACKEND, { PATH: bin });
  assert.equal(p.reachable, true);
  assert.match(p.reason, /present on PATH/);
  assert.equal(p.version, null); // version never read (would start the server)
});

test("probe: unreachable when not on PATH", () => {
  const p = probeBackend(MEMKERNEL_BACKEND, { PATH: "/nonexistent" });
  assert.equal(p.reachable, false);
  assert.match(p.reason, /not on PATH/);
});

test("probe: a disabled backend is never reachable", () => {
  const p = probeBackend({ ...MEMKERNEL_BACKEND, mode: "disabled" }, { PATH: tmpBinWith("memkernel") });
  assert.equal(p.reachable, false);
  assert.match(p.reason, /disabled/);
});

test("probe: a remote-gateway is declared, not probed in-process", () => {
  const p = probeBackend({
    name: "gw",
    mode: "remote-gateway",
    command: null,
    args: [],
    endpoint: "https://mcp.example/api",
    tools: [],
    source: "built-in",
    permissions: "",
  });
  assert.equal(p.reachable, false);
  assert.match(p.reason, /declared; not probed/);
});

test("report: a trusted, reachable backend renders the full FR-018 surface", () => {
  const bin = tmpBinWith("memkernel");
  const r = mcpReport(MEMKERNEL_BACKEND, probeBackend(MEMKERNEL_BACKEND, { PATH: bin }), "trusted");
  assert.equal(r.mode, "external-package");
  assert.equal(r.provenance, "built-in");
  assert.equal(r.trust, "trusted");
  assert.deepEqual(r.tools, ["retain", "recall", "get", "forget"]);
  assert.match(r.connectivity, /reachable/);
  assert.match(r.permissions, /memory tools only/);
  assert.match(r.security, /Pi's MCP transport/);
});

test("SECURITY: an untrusted project withholds the backend", () => {
  const bin = tmpBinWith("memkernel");
  const r = mcpReport(MEMKERNEL_BACKEND, probeBackend(MEMKERNEL_BACKEND, { PATH: bin }), "untrusted");
  assert.equal(r.trust, "untrusted");
  assert.match(r.security, /withheld/);
});

test("resolveMcpBackends: OFF by default; the built-in backend appears only when enabled", () => {
  const off = (k) => (k === "integrations.mcp.enabled" ? undefined : undefined);
  assert.deepEqual(resolveMcpBackends(off), []);
  const on = (k) => (k === "integrations.mcp.enabled" ? true : undefined);
  const backends = resolveMcpBackends(on);
  assert.equal(backends.length, 1);
  assert.equal(backends[0].name, "memkernel");
});
