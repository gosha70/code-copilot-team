// import-claude-agents.test.mjs — T7.1 Claude-agent frontmatter -> neutral
// manifest importer (FR-011). Run via tests/test-pi-runtime.sh.
//
// Verifies the pure converter against checked-in fixtures + a golden: field
// mapping, verbatim model tier, the four not-sourced fields, the flagged (not
// dropped) Claude `Agent` tool, duplicate/bad-name rejection, and idempotence.
// The golden is a drift guard: if importer output or a fixture changes, the
// diff surfaces it — nothing is auto-absorbed.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { importClaudeAgents } from "../../adapters/pi/runtime/agents/import-claude-agents.ts";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DIR = path.join(HERE, "fixtures", "claude-agents");
const GOLDEN = path.join(HERE, "fixtures", "claude-agents-golden.json");

function loadSources() {
  return fs
    .readdirSync(DIR)
    .filter((f) => f.endsWith(".md"))
    .sort()
    .map((f) => ({
      file: f.replace(/\.md$/, ""),
      frontmatter: fs.readFileSync(path.join(DIR, f), "utf8"),
    }));
}

test("importer output matches the committed golden (drift guard)", () => {
  const result = importClaudeAgents(loadSources());
  const golden = JSON.parse(fs.readFileSync(GOLDEN, "utf8"));
  assert.deepEqual(result, golden);
});

test("re-importing the same sources is idempotent", () => {
  const a = importClaudeAgents(loadSources());
  const b = importClaudeAgents(loadSources());
  assert.deepEqual(a, b);
});

test("model tier is carried verbatim, never remapped", () => {
  const { manifests } = importClaudeAgents(loadSources());
  assert.equal(manifests.find((m) => m.name === "build").model, "sonnet");
  assert.equal(manifests.find((m) => m.name === "plan").model, "opus");
});

test("the four Claude-inexpressible fields are reported not-sourced", () => {
  const { notSourced } = importClaudeAgents(loadSources());
  for (const rec of notSourced)
    assert.deepEqual(rec.fields.sort(), [
      "context",
      "permissions",
      "skills",
      "thinking",
    ]);
});

test("not-sourced fields land on neutral sentinels, not fabricated values", () => {
  const { manifests } = importClaudeAgents(loadSources());
  for (const m of manifests) {
    assert.equal(m.thinking, "inherit");
    assert.equal(m.permissions, "inherit");
    assert.deepEqual(m.skills, []);
    assert.deepEqual(m.context, []);
  }
});

test("the Claude `Agent` delegation tool is flagged, not imported as a Pi tool", () => {
  const { manifests, warnings } = importClaudeAgents(loadSources());
  const build = manifests.find((m) => m.name === "build");
  assert.ok(!build.tools.includes("agent"), "Agent must not become a Pi tool");
  assert.ok(
    warnings.some(
      (w) => w.agent === "build" && w.field === "tools" && /Agent/.test(w.reason),
    ),
    "Agent tool must be reported as a warning",
  );
});

test("a colon inside a quoted description is preserved (frontmatter parse)", () => {
  const { manifests } = importClaudeAgents(loadSources());
  assert.match(
    manifests.find((m) => m.name === "plan").description,
    /implementation plans: files/,
  );
});

test("a duplicate name is rejected with a warning, not a second manifest", () => {
  const { manifests, warnings } = importClaudeAgents(loadSources());
  assert.equal(manifests.filter((m) => m.name === "security-review").length, 1);
  // the canonical (first-seen) wins; the dup's model must not appear
  assert.equal(manifests.find((m) => m.name === "security-review").model, "sonnet");
  assert.ok(warnings.some((w) => /duplicate agent name/.test(w.reason)));
});

test("a non-kebab name is rejected, never silently renamed", () => {
  const { manifests, warnings } = importClaudeAgents(loadSources());
  assert.ok(!manifests.some((m) => /kebab/i.test(m.name)));
  assert.ok(warnings.some((w) => /not kebab-case/.test(w.reason)));
});
