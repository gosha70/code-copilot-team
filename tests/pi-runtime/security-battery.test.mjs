// security-battery.test.mjs — T11.5 consolidating SECURITY BATTERY.
//
// One canonical fail-closed invariant per security category, imported from the
// SAME real functions the deep tests exercise. This is a TRIPWIRE, not a
// parallel implementation: if any category's fail-closed behavior regresses, one
// named battery test here fails, over the whole security surface. Deep coverage
// lives in the per-area suites (see specs/pi-harness-adoption/security-battery.md).

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { loadLayeredConfig } from "../../adapters/pi/runtime/config/loader.ts";
import { matchCandidates } from "../../adapters/pi/runtime/policy/protected.ts";
import { checkPath } from "../../adapters/pi/runtime/policy/permissions.ts";
import { stripPrivilegePrefix, classifyPackageInstall } from "../../adapters/pi/runtime/policy/protected-ops.ts";
import { sandboxGate } from "../../adapters/pi/runtime/policy/sandbox.ts";
import { containsSecret } from "../../adapters/pi/runtime/workflow/memory.ts";
import { supportOf } from "../../adapters/pi/runtime/hooks/events.ts";
import { loadTeamLedger, claimTask, createTeam, postTask } from "../../adapters/pi/runtime/agents/team.ts";
import { cleanupEligibility } from "../../adapters/pi/runtime/agents/worktree.ts";
import { seedCapabilities } from "../../adapters/pi/runtime/capabilities.ts";

function tmpTree(files = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-sec-battery-"));
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return dir;
}

const PATH_RULES = {
  toolsAllow: [], toolsDeny: [], pathsDeny: ["**/*.pem", "secrets/**"],
  pathsAsk: [], commandsDeny: [], commandsAsk: [], askResolution: "deny", interactive: false,
};

// 1 ── trust gating (FR-004a fail-closed) ────────────────────────────────────
test("BATTERY 1 — trust gating: untrusted project config is refused, not applied", () => {
  const dir = tmpTree({ "proj/.code-copilot-team/config.toml": "[limits]\ntimeout_sec = 200\n" });
  const r = loadLayeredConfig({
    globalDir: "/nonexistent-global",
    projectDir: path.join(dir, "proj"),
    trusted: false,
    profile: "disciplined",
    env: {},
  });
  assert.notEqual(r.resolved.get("limits.timeout_sec").value, 200, "project value must NOT apply untrusted");
  assert.ok(r.ignoredFiles.some((f) => /not positively trusted/.test(f.reason)), "fail-closed reason");
});

// 2 ── protected paths (traversal/symlink cannot bypass) ─────────────────────
test("BATTERY 2 — protected paths: a traversal path to a protected file is denied", () => {
  const dir = tmpTree({ "secrets/prod/key.json": "{}", "src/app.ts": "//" });
  const m = matchCandidates(dir, "src/../secrets/prod/key.json");
  assert.ok(
    m.candidates.some((c) => checkPath(PATH_RULES, c).effective === "deny"),
    "traversal into secrets/** must resolve to deny",
  );
});

// 3 ── command denial (shell-wrapper / priv-prefix cannot hide it) ───────────
test("BATTERY 3 — command denial: a privilege prefix cannot hide a package install", () => {
  assert.deepEqual(stripPrivilegePrefix(["sudo", "-u", "root", "npm", "install"]), ["npm", "install"]);
  // classifyPackageInstall strips the prefix internally — the wrapper cannot hide it.
  assert.equal(classifyPackageInstall("sudo -u root npm install evil").match, true, "still matched as install");
});

// 4 ── sandbox fail-closed (autonomous + host-unrestricted, no override) ──────
test("BATTERY 4 — sandbox fail-closed: required sandbox on an unrestricted host is blocked", () => {
  const g = sandboxGate(
    { state: "host-unrestricted", provider: "none", evidence: [] },
    { sandboxRequired: true, rejectUnrestrictedHost: false, override: false },
  );
  assert.equal(g.allowed, false, "must refuse when a sandbox is required but absent");
});

// 5 ── secret redaction ──────────────────────────────────────────────────────
test("BATTERY 5 — secret redaction: a secret value is detected (and ordinary text is not)", () => {
  assert.equal(containsSecret("token=abcdef1234567890"), true);
  assert.equal(containsSecret("sk-ABCDEFGHIJKLMNOP1234"), true);
  assert.equal(containsSecret("the quick brown fox"), false);
});

// 6 ── lifecycle hook honesty (unsupported reported, never a fake pass) ───────
test("BATTERY 6 — lifecycle honesty: an unobservable Pi event reports unsupported", () => {
  assert.equal(supportOf("Stop"), "unsupported", "no observable Stop event");
  assert.equal(supportOf("PreToolUse"), "supported", "but a real one is honestly supported");
});

// 7 ── tamper-safe ledgers (a tampered team ledger loads fail-closed) ─────────
test("BATTERY 7 — tamper-safe ledger: a two-lead / bogus-approval team.json is rejected", () => {
  const dir = tmpTree({});
  fs.mkdirSync(path.join(dir, ".cct"), { recursive: true });
  fs.writeFileSync(
    path.join(dir, ".cct", "team.json"),
    JSON.stringify({
      teamId: "t1", status: "active",
      members: [
        { memberId: "lead", role: "lead", status: "active" },
        { memberId: "eve", role: "lead", status: "active" },
      ],
      tasks: [{ taskId: "task-a", claimStatus: "open" }],
      planApproval: { required: true, approved: true, approvedBy: "eve" },
    }),
  );
  assert.equal(loadTeamLedger(dir), null, "no single lead -> invalid team -> rejected");
});

// 8 ── fail-closed team/worktree behavior ────────────────────────────────────
test("BATTERY 8 — fail-closed team/worktree: unsafe claim + foreign cleanup are refused", () => {
  // team: a claim of a REAL task before the team is active is refused — assert
  // the specific reason so this cannot pass via "no such task" if ordering ever
  // changes.
  let l = createTeam("t1", "lead", "2026-08-01T00:00:00Z").ledger;
  l = postTask(l, { taskId: "task-a", title: "A" }).ledger; // a real, open task
  const claim = claimTask(l, "task-a", "lead", "2026-08-01T00:00:00Z");
  assert.equal(claim.ok, false, "claim on a non-active team is refused");
  assert.match(claim.error, /not active/, "refused specifically because the team is not active");
  // worktree: a foreign (non-cct) worktree is never removable, even forced
  const foreign = {
    workerId: "x", branch: "feature/x", worktreePath: "/abs/x", featureId: null, tasks: [],
    ownedAreas: [], verificationStatus: "pending", mergeStatus: "merged", cleanupStatus: "active",
    createdAt: "", origin: "foreign",
  };
  assert.equal(
    cleanupEligibility(foreign, { isClean: true, isPrimary: false, force: true }).eligible,
    false,
    "a foreign worktree is never removed, even with force",
  );
});

// 9 ── degraded-not-parity: the honesty boundary is reported, not faked ───────
test("BATTERY 9 — degraded surfaces are reported honestly in the registry (not enabled)", () => {
  const caps = seedCapabilities();
  const byId = Object.fromEntries(caps.map((c) => [c.id, c.runtime_status]));
  // Things Pi deliberately does NOT do (no sandbox creation / no live UI / no
  // Stop-compaction event) must never be reported `enabled`.
  for (const id of ["security.sandbox", "agents.teams", "memory.session-state", "verification.enforcement"]) {
    assert.ok(byId[id] !== undefined, `${id} present`);
    assert.notEqual(byId[id], "enabled", `${id} must not overclaim (fork-bomb/live-UI/Stop are degraded)`);
  }
});
