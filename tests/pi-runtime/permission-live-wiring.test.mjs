// permission-live-wiring.test.mjs — T5.2 live-wiring (FR-009). Run via
// tests/test-pi-runtime.sh.
//
// Covers the Claude permissions importer wired into the layered config:
//   - imported denies union into the monotonic floor (base ∪ imported)
//   - imported tools.allow is a base posture a profile can override (non-floor)
//   - most-derived profile wins the importPermissions selection
//   - warnings/notEnforced surface in LoadResult (read-vs-write gap stays visible)
//   - imported floor additions are recorded as an audited "strengthened" decision
//   - unknown / malformed imports are non-fatal (warned + skipped)

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { loadLayeredConfig } from "../../adapters/pi/runtime/config/loader.ts";
import { buildImportedLayer } from "../../adapters/pi/runtime/policy/permission-profiles.ts";

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-t52-"));
}
function load(profile, extra = {}) {
  return loadLayeredConfig({
    globalDir: tmp(),
    projectDir: tmp(),
    trusted: false,
    profile,
    ...extra,
  });
}

test("disciplined imports balanced: allow set + floor denies union with defaults", () => {
  const c = load("disciplined").config;
  assert.ok(c.tools.allow.includes("bash") && c.tools.allow.includes("write"));
  // protected_paths = defaults ∪ balanced (default kept, imported added).
  assert.ok(c.security.protected_paths.includes(".git/config")); // default kept
  assert.ok(c.security.protected_paths.includes(".env.local")); // imported added
  assert.ok(c.security.protected_paths.includes(".env.production"));
  // denied_commands = defaults ∪ balanced.
  assert.ok(c.security.denied_commands.includes("git push --force")); // default
  assert.ok(c.security.denied_commands.includes("sudo")); // imported
  assert.ok(c.security.denied_commands.includes("rm -rf")); // imported
});

test("read-vs-write gap surfaces as notEnforced warnings, tagged by source", () => {
  const r = load("disciplined");
  const nf = r.warnings.filter((w) => w.includes("notEnforced"));
  assert.ok(nf.length >= 3); // Read(.env), Read(.env.local), Read(.env.production)
  assert.ok(nf.some((w) => w.includes(".env.local")));
  assert.ok(r.warnings.every((w) => w.startsWith("permissions import 'balanced'")));
});

test("peer-reviewer: profile tools.allow wins (non-floor replace); denies still union", () => {
  const c = load("peer-reviewer").config;
  assert.deepEqual(c.tools.allow, ["read", "grep", "find", "ls"]); // profile beats imported
  assert.ok(!c.tools.allow.includes("bash"));
  // Floor denies from balanced still apply regardless of the profile override.
  assert.ok(c.security.denied_commands.includes("sudo"));
  assert.ok(c.security.protected_paths.includes(".env.production"));
});

test("most-derived profile wins: autonomous -> relaxed, not the inherited balanced", () => {
  const r = load("autonomous");
  const c = r.config;
  // relaxed declares NO path denies; balanced does. Their absence proves relaxed
  // was imported (not disciplined's inherited balanced).
  assert.ok(!c.security.protected_paths.includes(".env.local"));
  assert.ok(!c.security.protected_paths.includes(".env.production"));
  assert.ok(c.security.denied_commands.includes("sudo")); // relaxed cmd denies union
  assert.equal(r.warnings.filter((w) => w.includes("notEnforced")).length, 0);
});

test("importPermissions is inherited: review-heavy -> disciplined -> balanced", () => {
  const c = load("review-heavy").config;
  assert.ok(c.security.protected_paths.includes(".env.local")); // balanced inherited
});

test("a profile without importPermissions imports nothing", () => {
  const c = load("minimal").config;
  assert.equal(c.tools?.allow, undefined); // no imported allowlist
  assert.ok(!c.security.protected_paths.includes(".env.local")); // defaults only
});

test("imported floor additions are recorded as an audited 'strengthened' decision", () => {
  const r = load("disciplined");
  const d = r.floorDecisions.find(
    (x) => x.path === "security.denied_commands" && x.layer === "imported",
  );
  assert.ok(d, "expected a floor decision for the imported layer");
  assert.equal(d.action, "strengthened");
});

test("buildImportedLayer unions the base floor arrays so denies compose as strengthening", () => {
  const r = buildImportedLayer(["balanced"], tmp(), {
    protectedPaths: ["BASE_PATH"],
    deniedCommands: ["BASE_CMD"],
  });
  assert.ok(r.table.security.protected_paths.includes("BASE_PATH")); // base kept
  assert.ok(r.table.security.protected_paths.includes(".env.local")); // imported added
  assert.ok(r.table.security.denied_commands.includes("BASE_CMD"));
  assert.ok(r.table.tools.allow.includes("bash")); // non-floor list present
});

test("unknown permission profile: warned, empty table, non-fatal", () => {
  const r = buildImportedLayer(["does-not-exist"], tmp());
  assert.deepEqual(r.table, {});
  assert.equal(r.sources.length, 0);
  assert.ok(
    r.warnings.some((w) => w.includes("does-not-exist") && w.includes("not found")),
  );
});

test("malformed permission JSON: warned, skipped, non-fatal (managed dir read first)", () => {
  const g = tmp();
  fs.mkdirSync(path.join(g, "pi", "permissions"), { recursive: true });
  fs.writeFileSync(path.join(g, "pi", "permissions", "bad.json"), "{ not json");
  const r = buildImportedLayer(["bad"], g);
  assert.deepEqual(r.table, {});
  assert.ok(r.warnings.some((w) => w.includes("bad") && w.includes("not valid JSON")));
});
