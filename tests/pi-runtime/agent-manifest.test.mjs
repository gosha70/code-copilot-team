// agent-manifest.test.mjs — T7.1 neutral agent-manifest schema validation
// (FR-011). Run via tests/test-pi-runtime.sh.
//
// Pure schema tests: kebab/unique name, required fields, thinking vocabulary,
// array shape, and the "inherit" not-sourced sentinel. No spawn, no disk.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  MANIFEST_SENTINELS,
  THINKING_LEVELS,
  validateManifest,
} from "../../adapters/pi/runtime/agents/manifest.ts";

function base(overrides = {}) {
  return {
    name: "worker",
    description: "does a thing",
    model: "inherit",
    thinking: "inherit",
    tools: ["read"],
    skills: [],
    context: [],
    permissions: "inherit",
    source: "authored",
    declaredNotSourced: [],
    ...overrides,
  };
}

test("a well-formed manifest validates", () => {
  const r = validateManifest(base());
  assert.equal(r.valid, true, r.errors.join("; "));
});

test("name must be present and kebab-case", () => {
  assert.equal(validateManifest(base({ name: "" })).valid, false);
  assert.equal(validateManifest(base({ name: "Not Kebab" })).valid, false);
  assert.equal(validateManifest(base({ name: "UPPER" })).valid, false);
  assert.equal(validateManifest(base({ name: "under_score" })).valid, false);
  assert.equal(validateManifest(base({ name: "good-name-2" })).valid, true);
});

test("name uniqueness is enforced against an existing set", () => {
  const seen = new Set(["taken"]);
  assert.equal(validateManifest(base({ name: "taken" }), seen).valid, false);
  assert.equal(validateManifest(base({ name: "fresh" }), seen).valid, true);
});

test("description is required", () => {
  assert.equal(validateManifest(base({ description: "" })).valid, false);
});

test("thinking must be one of the known levels", () => {
  for (const t of THINKING_LEVELS)
    assert.equal(validateManifest(base({ thinking: t })).valid, true, t);
  assert.equal(validateManifest(base({ thinking: "extreme" })).valid, false);
});

test("tools/skills/context must be arrays", () => {
  assert.equal(validateManifest(base({ tools: "read" })).valid, false);
  assert.equal(validateManifest(base({ skills: null })).valid, false);
  assert.equal(validateManifest(base({ context: {} })).valid, false);
});

test("permissions posture is required (inherit for none)", () => {
  assert.equal(validateManifest(base({ permissions: "" })).valid, false);
  assert.equal(validateManifest(base({ permissions: "inherit" })).valid, true);
});

test("the not-sourced sentinels are neutral (assert no intent)", () => {
  assert.equal(MANIFEST_SENTINELS.model, "inherit");
  assert.equal(MANIFEST_SENTINELS.thinking, "inherit");
  assert.equal(MANIFEST_SENTINELS.permissions, "inherit");
});
