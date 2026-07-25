// import-permissions.test.mjs — Unit tests for the T5.2 Claude permissions
// importer (FR-009). Run via tests/test-pi-runtime.sh.
//
// Verifies the pure Claude permissions/*.json -> Pi rule-list mapping against
// the real balanced/relaxed/web-dynamic profiles, plus adversarial cases for
// path normalization and Bash(...) grammar, and the structured warnings/skips
// and read-vs-write `notEnforced` reporting.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { importClaudePermissions } from "../../adapters/pi/runtime/policy/import-permissions.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PERM_DIR = path.resolve(
  HERE,
  "../../adapters/claude-code/permissions",
);

function loadProfile(rel) {
  return JSON.parse(fs.readFileSync(path.join(PERM_DIR, rel), "utf8"));
}

// ── Real profiles ──────────────────────────────────────────────────────────

test("balanced.json: tools, protected paths, denied commands, read-gap report", () => {
  const { rules, warnings, notEnforced } = importClaudePermissions(
    loadProfile("balanced.json"),
  );
  assert.deepEqual(rules.toolsAllow, [
    "read",
    "glob",
    "grep",
    "edit",
    "write",
    "bash",
    "websearch",
    "webfetch",
  ]);
  // Read(./.env...) -> protected path, ./ stripped, matches at any depth.
  assert.deepEqual(rules.pathsDeny, [".env", ".env.local", ".env.production"]);
  assert.deepEqual(rules.commandsDeny, [
    "rm -rf",
    "sudo",
    "git push --force",
    "git reset --hard",
  ]);
  // The three Read(...) denies enforce on writes only -> reported not-enforced.
  assert.equal(notEnforced.length, 3);
  assert.match(notEnforced[0].reason, /read intent/);
  assert.match(notEnforced[0].target, /pathsDeny:\.env/);
  // Every entry mapped cleanly.
  assert.deepEqual(warnings, []);
});

test("relaxed.json: commands only, no protected paths, env ignored", () => {
  const { rules, warnings, notEnforced } = importClaudePermissions(
    loadProfile("relaxed.json"),
  );
  assert.deepEqual(rules.commandsDeny, [
    "rm -rf",
    "sudo",
    "git push --force",
    "git reset --hard",
  ]);
  assert.deepEqual(rules.pathsDeny, []);
  assert.deepEqual(notEnforced, []);
  assert.deepEqual(warnings, []);
  // `env` is not a permission rule; nothing from it leaks into the lists.
  const flat = JSON.stringify(rules);
  assert.doesNotMatch(flat, /HOOK_GIT_ALLOW|true/);
});

test("deny-extras/web-dynamic.json: Bash(:*) prefixes", () => {
  const { rules } = importClaudePermissions(loadProfile("deny-extras/web-dynamic.json"));
  assert.deepEqual(rules.commandsDeny, [
    "npx prisma migrate reset",
    "npx prisma db push",
    "git push",
  ]);
});

// ── Path normalization ─────────────────────────────────────────────────────

test("path normalization: ./ stripped, internal-slash + absolute kept", () => {
  const { rules } = importClaudePermissions({
    permissions: {
      deny: ["Read(./.env)", "Edit(src/secret.txt)", "Write(/abs/creds)"],
    },
  });
  assert.deepEqual(rules.pathsDeny, [".env", "src/secret.txt", "/abs/creds"]);
});

test("Edit/Write path deny is fully enforced (no notEnforced); Read is not", () => {
  const edit = importClaudePermissions({
    permissions: { deny: ["Edit(./.env)"] },
  });
  assert.deepEqual(edit.rules.pathsDeny, [".env"]);
  assert.deepEqual(edit.notEnforced, []); // writes are enforced

  const read = importClaudePermissions({
    permissions: { deny: ["Read(./.env)"] },
  });
  assert.deepEqual(read.rules.pathsDeny, [".env"]); // still protects writes
  assert.equal(read.notEnforced.length, 1); // read intent not enforced
});

// ── Bash grammar ───────────────────────────────────────────────────────────

test("Bash(:*) strips to prefix; exact and embedded-colon warn", () => {
  const { rules, warnings } = importClaudePermissions({
    permissions: {
      deny: ["Bash(rm -rf:*)", "Bash(npm run test)", "Bash(foo:bar)"],
    },
  });
  assert.ok(rules.commandsDeny.includes("rm -rf"));
  assert.ok(rules.commandsDeny.includes("npm run test")); // exact -> prefix
  assert.ok(rules.commandsDeny.includes("foo:bar")); // embedded colon verbatim
  const reasons = warnings.map((w) => w.reason).join(" | ");
  assert.match(reasons, /exact-match/);
  assert.match(reasons, /non-trailing ':'/);
});

// ── No-Pi-target entries: report, do not fake ──────────────────────────────

test("scoped allow / tool-level ask have no Pi target -> warn + skip", () => {
  const { rules, warnings } = importClaudePermissions({
    permissions: {
      allow: ["Bash(git:*)", "Edit(src/**)"],
      ask: ["Bash", "Read(secret)"],
    },
  });
  // Nothing landed in a rule list for the unmappable allow entries.
  assert.deepEqual(rules.commandsDeny, []);
  assert.deepEqual(rules.pathsDeny, []);
  // Scoped Bash allow, scoped file allow, and bare-tool ask all warn.
  const entries = warnings.map((w) => w.entry);
  assert.ok(entries.includes("Bash(git:*)"));
  assert.ok(entries.includes("Edit(src/**)"));
  assert.ok(entries.includes("Bash"));
  // Read(secret) in ask IS a valid path-ask target.
  assert.deepEqual(rules.pathsAsk, ["secret"]);
});

// ── Malformed input ────────────────────────────────────────────────────────

test("malformed input yields empty rules, never throws", () => {
  for (const bad of [null, undefined, {}, { permissions: {} }, 42, "x", []]) {
    const r = importClaudePermissions(bad);
    assert.deepEqual(r.rules.toolsAllow, []);
    assert.deepEqual(r.rules.commandsDeny, []);
  }
  const junk = importClaudePermissions({ permissions: { deny: ["!!!", 7, "Bash(ok:*)"] } });
  assert.ok(junk.rules.commandsDeny.includes("ok"));
  assert.ok(junk.warnings.some((w) => w.entry === "!!!"));
});
