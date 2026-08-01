// cross-adapter-contract.test.mjs — T11.5 cross-adapter contract (DoD item 12).
//
// SHARED SEMANTICS ONLY. Pi and Claude Code are generated from the same
// `shared/` source and classify the same capability catalog; this asserts the
// Pi runtime CONFORMS to those shared contracts. It deliberately does NOT force
// native-feature parity — where the registry marks a divergence (Pi degraded vs
// Claude native), that is intentional and asserted as such, not "fixed".
//
// Claude's side of the contract is enforced by the shell suite
// (validate-capabilities.sh: every catalog id classified by every adapter;
// sdd-cross-adapter fixtures) — this file consolidates the Pi-runtime side.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { PHASE_ORDER } from "../../adapters/pi/runtime/workflow/phases.ts";
import { checkTool } from "../../adapters/pi/runtime/policy/permissions.ts";
import { seedCapabilities } from "../../adapters/pi/runtime/capabilities.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CAP_DIR = path.resolve(HERE, "../../shared/capabilities");

function idsInYaml(file) {
  return fs
    .readFileSync(path.join(CAP_DIR, file), "utf8")
    .split("\n")
    .map((l) => l.match(/^\s*-\s*id:\s*(\S+)/))
    .filter(Boolean)
    .map((m) => m[1]);
}

// ── shared contract: phase order ─────────────────────────────────────────────
test("CONTRACT — phase order is the shared research→plan→build→review order", () => {
  assert.deepEqual(PHASE_ORDER, ["research", "plan", "build", "review"]);
});

// ── shared contract: permission decision precedence (deny wins, fail-closed) ─
test("CONTRACT — permission semantics: deny precedence is shared/fail-closed", () => {
  const denyAll = {
    toolsAllow: ["read"], toolsDeny: ["*"], pathsDeny: [], pathsAsk: [],
    commandsDeny: [], commandsAsk: [], askResolution: "deny", interactive: false,
  };
  // a tool both allowed and deny-globbed resolves to deny — the same decision
  // contract both adapters follow.
  assert.equal(checkTool(denyAll, "read").effective, "deny");
});

// ── shared contract: Pi and Claude agree on the capability SET ────────────────
test("CONTRACT — capability SET agreement: Pi seed == catalog == claude-code", () => {
  const catalog = new Set(idsInYaml("catalog.yaml"));
  const claude = new Set(idsInYaml("claude-code.yaml"));
  const pi = new Set(seedCapabilities().map((c) => c.id));
  assert.deepEqual([...pi].sort(), [...catalog].sort(), "Pi classifies exactly the catalog");
  assert.deepEqual([...claude].sort(), [...catalog].sort(), "Claude classifies exactly the catalog");
  // (per-adapter STATUS may differ — that is the honest divergence below.)
});

// ── deliberate divergence: NOT forced to native parity ───────────────────────
test("CONTRACT — divergence is intentional: Pi may be degraded where Claude is native", () => {
  const pi = Object.fromEntries(seedCapabilities().map((c) => [c.id, c.runtime_status]));
  // agents.subagents: Claude native (enabled); Pi degraded (out-of-process,
  // documented). The contract is "same capability, honest per-adapter status",
  // NOT "identical status" — so Pi degraded here is conformance, not a failure.
  assert.equal(pi["agents.subagents"], "degraded");
  assert.notEqual(pi["agents.subagents"], "enabled", "Pi does not overclaim native parity");
});
