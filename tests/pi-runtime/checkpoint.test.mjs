// checkpoint.test.mjs — T9.1 durable session checkpoint + recovery (FR-017).
// Run via tests/test-pi-runtime.sh.
//
// Covers: write/load roundtrip, monotonic checkpointCount, corrupt/missing ->
// null (never throws), recovery digest content, and the compaction-preservation
// prompt being carried in the digest.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  COMPACTION_PROMPT,
  SESSION_STATE_REL,
  loadCheckpoint,
  writeCheckpoint,
  recoveryDigest,
} from "../../adapters/pi/runtime/workflow/checkpoint.ts";

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "cct-cp-"));
}

test("write/load roundtrip preserves phase + feature", () => {
  const root = tmp();
  const cp = writeCheckpoint(root, { phase: "build", featureId: "feat-42" }, "2026-07-29T00:00:00Z");
  assert.equal(cp.phase, "build");
  assert.equal(cp.featureId, "feat-42");
  assert.equal(cp.checkpointCount, 1);
  const loaded = loadCheckpoint(root);
  assert.deepEqual(loaded, cp);
  assert.ok(fs.existsSync(path.join(root, SESSION_STATE_REL)));
});

test("checkpointCount increments across writes (restart/compaction proxy)", () => {
  const root = tmp();
  writeCheckpoint(root, { phase: "plan", featureId: "f" }, "2026-07-29T00:00:00Z");
  writeCheckpoint(root, { phase: "build", featureId: "f" }, "2026-07-29T00:01:00Z");
  const third = writeCheckpoint(root, { phase: "review", featureId: "f" }, "2026-07-29T00:02:00Z");
  assert.equal(third.checkpointCount, 3);
  assert.equal(loadCheckpoint(root).phase, "review");
});

test("missing checkpoint -> null (recovery is a no-op)", () => {
  assert.equal(loadCheckpoint(tmp()), null);
});

test("corrupt checkpoint -> null, never throws", () => {
  const root = tmp();
  const file = path.join(root, SESSION_STATE_REL);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, "{ not json");
  assert.equal(loadCheckpoint(root), null);
});

test("recovery digest names the feature, phase, count and carries the compaction prompt", () => {
  const cp = writeCheckpoint(tmp(), { phase: "build", featureId: "feat-42" }, "2026-07-29T00:00:00Z");
  const digest = recoveryDigest(cp);
  assert.match(digest, /feat-42/);
  assert.match(digest, /build/);
  assert.match(digest, /checkpoint #1/);
  assert.ok(digest.includes(COMPACTION_PROMPT), "digest must carry the compaction prompt");
});

test("null feature/phase render safely in the digest", () => {
  const cp = writeCheckpoint(tmp(), { phase: null, featureId: null }, "2026-07-29T00:00:00Z");
  const digest = recoveryDigest(cp);
  assert.match(digest, /no active feature/);
  assert.match(digest, /no phase/);
});
