// project.test.mjs — where a project's Pi files are read from (#460).
// Run via tests/test-pi-runtime.sh (node --experimental-strip-types --test).

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  LEGACY_PROJECT_DIR,
  PROJECT_FILES,
  projectFile,
  projectFileStates,
  projectWarnings,
} from "../../adapters/pi/runtime/config/project.ts";

function withProject(files, fn, { git = false } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-project-"));
  try {
    if (git) spawnSync("git", ["init", "-q", dir]);
    for (const [rel, body] of Object.entries(files)) {
      fs.mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true });
      fs.writeFileSync(path.join(dir, rel), body);
    }
    fn(dir);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

test("a fresh project resolves every file to its new path", () => {
  withProject({}, (dir) => {
    assert.equal(projectFile(dir, "config"), path.join(dir, ".cct.toml"));
    assert.equal(projectFile(dir, "local"), path.join(dir, ".cct.local.toml"));
    assert.equal(projectFile(dir, "manifest"), path.join(dir, ".cct-init.json"));
    assert.deepEqual(projectWarnings(dir), []);
  });
});

test("a legacy-only file is read from the legacy directory, each file on its own", () => {
  withProject({ [`${LEGACY_PROJECT_DIR}/config.toml`]: "a = 1\n", ".cct.local.toml": "b = 2\n" }, (dir) => {
    assert.equal(projectFile(dir, "config"), path.join(dir, LEGACY_PROJECT_DIR, "config.toml"));
    assert.equal(projectFile(dir, "local"), path.join(dir, PROJECT_FILES.local));
    const states = Object.fromEntries(projectFileStates(dir).map((s) => [s.kind, s.source]));
    assert.deepEqual(states, { config: "legacy", local: "new", manifest: "absent" });
    assert.ok(projectWarnings(dir).some((w) => w.includes("pi-code migrate")));
  });
});

test("the new file wins when both exist, and the legacy one is reported", () => {
  withProject({ ".cct.toml": "a = 2\n", [`${LEGACY_PROJECT_DIR}/config.toml`]: "a = 1\n" }, (dir) => {
    assert.equal(projectFile(dir, "config"), path.join(dir, ".cct.toml"));
    const config = projectFileStates(dir).find((s) => s.kind === "config");
    assert.equal(config.legacyShadowed, true);
    assert.ok(projectWarnings(dir).some((w) => w.includes("is ignored because .cct.toml exists")));
  });
});

test("doctor warns when git ignores .cct.toml, and when .cct.local.toml is not ignored", () => {
  withProject({ ".cct.toml": "a = 1\n", ".cct.local.toml": "b = 2\n", ".gitignore": ".cct*.toml\n!.cct.local.toml\n" }, (dir) => {
    const w = projectWarnings(dir);
    assert.ok(w.some((x) => x.startsWith(".cct.toml is ignored by git")), w.join("\n"));
    assert.ok(w.some((x) => x.startsWith(".cct.local.toml is not ignored by git")), w.join("\n"));
  }, { git: true });
});

test("a migrated project with the right ignores is quiet", () => {
  withProject({ ".cct.toml": "a = 1\n", ".cct-init.json": "{}\n", ".cct.local.toml": "b = 2\n", ".gitignore": ".cct/\n.cct.local.toml\n" }, (dir) => {
    assert.deepEqual(projectWarnings(dir), []);
  }, { git: true });
});
