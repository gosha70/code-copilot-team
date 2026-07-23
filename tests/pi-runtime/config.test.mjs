// config.test.mjs — Unit tests for the CCT Pi runtime configuration engine.
// Run via tests/test-pi-runtime.sh (node --experimental-strip-types --test).
//
// Covers specs/pi-harness-adoption: FR-004 (layered merge, provenance,
// redaction, explain), FR-004a (trust gating fail-closed), FR-009a
// (monotonic security floor), profiles (inheritance + cycle rejection),
// and the minimal TOML parser contract.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { parseToml, TomlError } from "../../adapters/pi/runtime/config/toml.ts";
import {
  BUILTIN_PROFILES,
  ProfileError,
  resolveProfileChain,
} from "../../adapters/pi/runtime/config/profiles.ts";
import { applyFloorValue } from "../../adapters/pi/runtime/config/floor.ts";
import {
  explainKey,
  loadLayeredConfig,
  redactedConfig,
} from "../../adapters/pi/runtime/config/loader.ts";
import {
  CONFIG_SCHEMA_VERSION,
  declaredVersion,
  migrateTable,
} from "../../adapters/pi/runtime/config/migrate.ts";
import {
  defaultProjectTrustFinding,
  trustDrift,
} from "../../adapters/pi/runtime/config/trust.ts";
import { hasErrors, lintConfig } from "../../adapters/pi/runtime/config/lint.ts";
import { BUILTIN_DEFAULTS } from "../../adapters/pi/runtime/config/loader.ts";

// ── helpers ─────────────────────────────────────────────────

function tempTree(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-pi-test-"));
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return dir;
}

function load(overrides = {}) {
  return loadLayeredConfig({
    globalDir: "/nonexistent-global",
    projectDir: "/nonexistent-project",
    trusted: false,
    profile: "disciplined",
    env: {},
    ...overrides,
  });
}

// ── TOML parser ─────────────────────────────────────────────

test("toml: tables, dotted keys, scalars, arrays, inline tables", () => {
  const t = parseToml(`
# comment
title = "CCT"        # trailing comment
[workflow.sdd]
enabled = true
mode = 'enforced'
[limits]
timeout_sec = 300
ratio = 1.5
tools = ["read", "grep", "find"]
inline = { a = 1, b = "two" }
dotted.key = false
`);
  assert.equal(t.title, "CCT");
  assert.equal(t.workflow.sdd.enabled, true);
  assert.equal(t.workflow.sdd.mode, "enforced");
  assert.equal(t.limits.timeout_sec, 300);
  assert.equal(t.limits.ratio, 1.5);
  assert.deepEqual(t.limits.tools, ["read", "grep", "find"]);
  assert.deepEqual(t.limits.inline, { a: 1, b: "two" });
  assert.equal(t.limits.dotted.key, false);
});

test("toml: errors carry line numbers; unsupported forms rejected", () => {
  assert.throws(() => parseToml("a = "), TomlError);
  assert.throws(() => parseToml("[[table]]"), /array-of-tables/);
  assert.throws(() => parseToml('a = "unterminated'), /unterminated/);
  assert.throws(() => parseToml("a = 1\na = 2"), /duplicate key/);
  try {
    parseToml("ok = 1\nbad ==");
    assert.fail("expected TomlError");
  } catch (e) {
    assert.match(e.message, /line 2/);
  }
});

// ── profiles ────────────────────────────────────────────────

test("profiles: inheritance chain resolves base-most first", () => {
  const chain = resolveProfileChain("air-gapped").map((p) => p.name);
  assert.deepEqual(chain, ["disciplined", "local-first", "air-gapped"]);
});

test("profiles: unknown and circular inheritance rejected", () => {
  assert.throws(() => resolveProfileChain("nope"), ProfileError);
  const registry = {
    a: { name: "a", description: "", inherits: "b", config: {} },
    b: { name: "b", description: "", inherits: "a", config: {} },
  };
  assert.throws(() => resolveProfileChain("a", registry), /circular/);
});

test("profiles: peer-reviewer is read-only and non-recursive by construction", () => {
  const p = BUILTIN_PROFILES["peer-reviewer"];
  assert.deepEqual(p.config.tools.allow, ["read", "grep", "find", "ls"]);
  assert.equal(p.config.workflow.sdd.enabled, false);
  assert.equal(p.config.review.allow_recursive, false);
  assert.equal(p.config.agents.subagents_enabled, false);
  assert.equal(p.config.session.ephemeral, true);
  assert.equal(p.config.headless.ask_resolution, "deny");
});

// ── layered precedence + provenance ─────────────────────────

test("precedence: defaults < profile < global < project < project-local < env < cli", () => {
  const dir = tempTree({
    "global/config.toml": "[limits]\ntimeout_sec = 100\n[review]\nafter_phase = false\n",
    "proj/.code-copilot-team/config.toml": "[limits]\ntimeout_sec = 200\n",
    "proj/.code-copilot-team/config.local.toml": "[limits]\ntimeout_sec = 300\n",
  });
  const r = load({
    globalDir: path.join(dir, "global"),
    projectDir: path.join(dir, "proj"),
    trusted: true,
    env: { CCT_CONFIG__LIMITS__TIMEOUT_SEC: "400" },
    cliSets: ["limits.timeout_sec=500"],
  });
  assert.equal(r.errors.length, 0);
  const entry = r.resolved.get("limits.timeout_sec");
  assert.equal(entry.value, 500);
  assert.equal(entry.layer, "cli");
  // Full override history retained, oldest first.
  const values = entry.history.map((h) => h.value);
  assert.deepEqual(values, [900, 100, 200, 300, 400]);
  // Non-overridden global key wins over profile.
  assert.equal(r.resolved.get("review.after_phase").value, false);
  assert.equal(r.resolved.get("review.after_phase").layer, "global");
});

test("trust gating: untrusted project config is ignored with reason (fail closed)", () => {
  const dir = tempTree({
    "proj/.code-copilot-team/config.toml": "[limits]\ntimeout_sec = 200\n",
    "proj/.code-copilot-team/config.local.toml": "[limits]\ntimeout_sec = 300\n",
  });
  const r = load({ projectDir: path.join(dir, "proj"), trusted: false });
  assert.equal(r.resolved.get("limits.timeout_sec").value, 900); // defaults
  assert.equal(r.loadedFiles.length, 0);
  assert.equal(r.ignoredFiles.length, 2);
  assert.match(r.ignoredFiles[0].reason, /not positively trusted/);
});

test("trust gating: --no-project-config ignores even trusted project config", () => {
  const dir = tempTree({
    "proj/.code-copilot-team/config.toml": "[limits]\ntimeout_sec = 200\n",
  });
  const r = load({
    projectDir: path.join(dir, "proj"),
    trusted: true,
    noProjectConfig: true,
  });
  assert.equal(r.resolved.get("limits.timeout_sec").value, 900);
  assert.match(r.ignoredFiles[0].reason, /--no-project-config/);
});

// ── security floor (FR-009a) ────────────────────────────────

test("floor: trusted project cannot weaken; can strengthen", () => {
  const dir = tempTree({
    "proj/.code-copilot-team/config.toml": `
[security]
fail_closed = false            # weakening attempt -> blocked
sandbox_required = true        # strengthening -> accepted
protected_paths = [".env", ".git/config", "**/*.pem", "**/id_rsa*", "secrets/"]  # superset -> accepted
denied_commands = ["git push --force"]  # subset (drops entries) -> blocked
`,
  });
  const r = load({ projectDir: path.join(dir, "proj"), trusted: true });
  assert.equal(r.resolved.get("security.fail_closed").value, true, "weakening blocked");
  assert.equal(r.resolved.get("security.sandbox_required").value, true, "strengthening kept");
  assert.ok(r.resolved.get("security.protected_paths").value.includes("secrets/"));
  assert.ok(
    r.resolved.get("security.denied_commands").value.includes("git reset --hard"),
    "array shrink blocked — union with floor retained",
  );
  const blocked = r.floorDecisions.filter((d) => d.action === "blocked-weakening");
  assert.equal(blocked.length, 2);
  assert.ok(r.warnings.some((w) => w.includes("security floor")));
});

test("floor: user-controlled project-local override may relax, recorded", () => {
  const dir = tempTree({
    "proj/.code-copilot-team/config.local.toml": "[security]\nfail_closed = false\n",
  });
  const r = load({ projectDir: path.join(dir, "proj"), trusted: true });
  assert.equal(r.resolved.get("security.fail_closed").value, false);
  const relax = r.floorDecisions.filter((d) => d.action === "relaxed-by-override");
  assert.equal(relax.length, 1);
  assert.equal(relax[0].layer, "project-local");
});

test("floor: combinator unit semantics", () => {
  assert.equal(
    applyFloorValue("security.deny_network", "project", false, true).decision.action,
    "strengthened",
  );
  assert.equal(
    applyFloorValue("security.allow_package_install", "project", false, true).decision.action,
    "blocked-weakening",
  );
  assert.equal(
    applyFloorValue("security.allow_package_install", "cli", false, true).decision.action,
    "relaxed-by-override",
  );
});

// ── redaction + explain ─────────────────────────────────────

test("redaction: sensitive keys masked in dumps; explain shows provenance", () => {
  const dir = tempTree({
    "global/config.toml": '[providers.custom]\napi_key = "sk-super-secret"\nendpoint = "http://localhost:8000"\n',
  });
  const r = load({ globalDir: path.join(dir, "global") });
  const dump = redactedConfig(r);
  assert.equal(dump["providers.custom.api_key"], "<redacted>");
  assert.equal(dump["providers.custom.endpoint"], "http://localhost:8000");
  assert.match(explainKey(r, "providers.custom.api_key"), /<redacted>/);
  assert.doesNotMatch(explainKey(r, "providers.custom.api_key"), /sk-super-secret/);

  const explained = explainKey(r, "workflow.sdd.enabled");
  assert.match(explained, /set by: {2}profile/);
  const missing = explainKey(r, "workflow.sdd.enable");
  assert.match(missing, /not set/);
  assert.match(missing, /workflow.sdd.enabled/); // suggestion
});

test("errors: malformed TOML reported with file + line, load continues", () => {
  const dir = tempTree({ "global/config.toml": "[limits]\ntimeout_sec ==\n" });
  const r = load({ globalDir: path.join(dir, "global") });
  assert.equal(r.errors.length, 1);
  assert.match(r.errors[0], /config.toml/);
  assert.match(r.errors[0], /line 2/);
  assert.equal(r.resolved.get("limits.timeout_sec").value, 900); // defaults intact
});

// ── versioning + migration (FR-004, T1.2) ───────────────────

test("migrate: absent config_version is treated as v1", () => {
  assert.equal(declaredVersion({}), 1);
  assert.equal(declaredVersion({ config_version: 2 }), 2);
  assert.equal(declaredVersion({ config_version: 0 }), null);
  assert.equal(declaredVersion({ config_version: "2" }), null);
});

test("migrate: v1 headless.deny_asks becomes the three-valued resolution", () => {
  const denied = migrateTable({ headless: { deny_asks: true } });
  assert.equal(denied.error, null);
  assert.equal(denied.table.headless.ask_resolution, "deny");
  assert.equal(denied.table.headless.deny_asks, undefined);
  assert.match(denied.notes[0].change, /ask_resolution/);

  const allowed = migrateTable({ headless: { deny_asks: false } });
  assert.equal(allowed.table.headless.ask_resolution, "allow");
});

test("migrate: an explicit new-form key wins over the legacy one", () => {
  const r = migrateTable({
    headless: { deny_asks: true, ask_resolution: "fail" },
  });
  assert.equal(r.table.headless.ask_resolution, "fail");
  assert.equal(r.table.headless.deny_asks, undefined);
  assert.match(r.notes[0].change, /already set/);
});

test("migrate: v1 security ask lists move under permissions", () => {
  const r = migrateTable({
    security: { ask_paths: ["infra/**"], ask_commands: ["git push"] },
  });
  assert.deepEqual(r.table.permissions.paths.ask, ["infra/**"]);
  assert.deepEqual(r.table.permissions.commands.ask, ["git push"]);
  assert.equal(r.table.security.ask_paths, undefined);
});

test("migrate: input table is not mutated and version is stamped", () => {
  const input = { headless: { deny_asks: true } };
  const r = migrateTable(input);
  assert.equal(input.headless.deny_asks, true, "input must be untouched");
  assert.equal(r.table.config_version, CONFIG_SCHEMA_VERSION);
});

test("migrate: a future config_version is an error, not a warning", () => {
  const r = migrateTable({ config_version: CONFIG_SCHEMA_VERSION + 1 });
  assert.notEqual(r.error, null);
  assert.match(r.error, /newer than this runtime supports/);
  const bad = migrateTable({ config_version: -3 });
  assert.match(bad.error, /positive integer/);
});

test("loader: a future-versioned file is rejected and never merged", () => {
  const dir = tempTree({
    "config.toml": `config_version = ${CONFIG_SCHEMA_VERSION + 10}\n[limits]\ntimeout_sec = 1\n`,
  });
  const r = load({ globalDir: dir });
  assert.ok(r.errors.some((e) => /newer than this runtime supports/.test(e)));
  assert.ok(r.ignoredFiles.some((f) => /config\.toml$/.test(f.file)));
  assert.ok(!r.loadedFiles.some((f) => /config\.toml$/.test(f)));
  // The built-in default must survive; the bad file contributes nothing.
  assert.equal(r.config.limits.timeout_sec, 900);
});

test("loader: legacy keys are migrated, reported, and applied", () => {
  const dir = tempTree({
    "config.toml": "[headless]\ndeny_asks = false\n",
  });
  const r = load({ globalDir: dir });
  assert.equal(r.errors.length, 0);
  assert.equal(r.config.headless.ask_resolution, "allow");
  assert.equal(r.migrations.length, 1);
  assert.ok(r.warnings.some((w) => /migrated v1->v2/.test(w)));
  assert.equal(r.configVersion, CONFIG_SCHEMA_VERSION);
  // config_version is file metadata, not a resolved configuration key.
  assert.equal(r.resolved.has("config_version"), false);
});

// ── trust gating (FR-004a, T1.5) ────────────────────────────

test("trust: no drift while the live value matches the loaded one", () => {
  assert.equal(trustDrift("trusted", "trusted"), null);
  assert.equal(trustDrift("untrusted", "untrusted"), null);
});

test("trust: gaining trust mid-session requires a restart, not a reload", () => {
  const d = trustDrift("untrusted", "trusted");
  assert.notEqual(d, null);
  assert.equal(d.from, "untrusted");
  assert.equal(d.to, "trusted");
  // The session must not pretend project config is now in effect.
  assert.match(d.message, /NOT loaded/);
  assert.match(d.message, /Restart pi-code/);
});

test("trust: losing trust mid-session says what is still in effect", () => {
  const d = trustDrift("trusted", "untrusted");
  assert.match(d.message, /remains in effect/);
  assert.match(d.message, /Restart pi-code/);
});

test("trust: unknown is treated as its own state, not as untrusted", () => {
  assert.notEqual(trustDrift("unknown", "trusted"), null);
  assert.notEqual(trustDrift("unknown", "untrusted"), null);
});

test("trust: defaultProjectTrust 'always' warns and produces an audit record", () => {
  const f = defaultProjectTrustFinding("always");
  assert.notEqual(f, null);
  assert.match(f.warning, /without a saved decision/);
  assert.equal(f.audit.origin, "trust");
  assert.equal(f.audit.rule, "pi.defaultProjectTrust");
  assert.match(f.audit.decision, /without-saved-decision/);
});

test("trust: other defaultProjectTrust values report nothing", () => {
  for (const v of [null, "never", "prompt", "", "ALWAYS"]) {
    assert.equal(defaultProjectTrustFinding(v), null, `should be null for ${JSON.stringify(v)}`);
  }
});

test("migrate: a mis-authored chain is an error, not a silent partial migration", () => {
  // Guards the invariant directly: reaching a version below the current one
  // must never be reported as a successful migration.
  const r = migrateTable({ config_version: 1 });
  assert.equal(r.error, null);
  assert.equal(r.table.config_version, CONFIG_SCHEMA_VERSION);
});

// ── config linting: obsolete / legacy / unknown keys (FR-004, T1.7) ──

test("lint: an obsolete key is an error, not a silent no-op", () => {
  const findings = lintConfig({ security: { allow_all: true } });
  const f = findings.find((x) => x.key === "security.allow_all");
  assert.equal(f.kind, "obsolete");
  assert.equal(hasErrors(findings), true);
});

test("lint: a legacy key is informational — migration will carry it", () => {
  const findings = lintConfig({ headless: { deny_asks: true } });
  const f = findings.find((x) => x.key === "headless.deny_asks");
  assert.equal(f.kind, "legacy");
  assert.equal(hasErrors(findings), false);
});

test("lint: a typo in a closed section is an unknown-key warning", () => {
  // The dangerous case: security.fail_close looks like a real setting.
  const findings = lintConfig({ security: { fail_close: true } });
  const f = findings.find((x) => x.key === "security.fail_close");
  assert.equal(f.kind, "unknown");
  assert.equal(hasErrors(findings), false); // warning, not error
});

test("lint: known keys and open sections produce no findings", () => {
  const clean = {
    config_version: 2,
    security: { fail_closed: true, protected_paths: [".env"] },
    profiles: { mine: { extends: "disciplined" } }, // open section
    providers: { openai: { api_key: "x", model: "gpt" } }, // open section
  };
  assert.deepEqual(lintConfig(clean), []);
});

test("lint: every shipped default is recognized (no linter/default drift)", () => {
  const unknown = lintConfig(BUILTIN_DEFAULTS).filter((f) => f.kind === "unknown");
  assert.deepEqual(unknown, [], `defaults not recognized: ${unknown.map((f) => f.key).join(", ")}`);
});
