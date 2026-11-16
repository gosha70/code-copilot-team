// home.test.mjs — the CCT home resolver in the Pi runtime (#411).
// Run via tests/test-pi-runtime.sh (node --experimental-strip-types --test).

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  ENV_HOME,
  HOME_DEFAULT_REL,
  HOME_LEGACY_REL,
  cctHome,
  cctHomePath,
  legacyHits,
} from "../../adapters/pi/runtime/config/home.ts";

function withHome(fn) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cct-home-"));
  const saved = { HOME: process.env.HOME, [ENV_HOME]: process.env[ENV_HOME] };
  process.env.HOME = tmp;
  delete process.env[ENV_HOME];
  try {
    fn(tmp);
  } finally {
    process.env.HOME = saved.HOME;
    if (saved[ENV_HOME] === undefined) delete process.env[ENV_HOME];
    else process.env[ENV_HOME] = saved[ENV_HOME];
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

test("the default home is ~/.cct and a missing entry is created under it", () => {
  withHome((tmp) => {
    assert.equal(cctHome(), path.join(tmp, HOME_DEFAULT_REL));
    assert.equal(cctHomePath("config.toml"), path.join(tmp, HOME_DEFAULT_REL, "config.toml"));
  });
});

test("a legacy-only entry is read from the legacy home; others still go to the home", () => {
  withHome((tmp) => {
    fs.mkdirSync(path.join(tmp, HOME_LEGACY_REL, "pi"), { recursive: true });
    fs.writeFileSync(path.join(tmp, HOME_LEGACY_REL, "config.toml"), "");
    assert.equal(cctHomePath("config.toml"), path.join(tmp, HOME_LEGACY_REL, "config.toml"));
    assert.equal(cctHomePath("pi"), path.join(tmp, HOME_LEGACY_REL, "pi"));
    assert.equal(cctHomePath("llms.toml"), path.join(tmp, HOME_DEFAULT_REL, "llms.toml"));
  });
});

test("a nested path follows its top-level entry, never splitting a directory", () => {
  withHome((tmp) => {
    // A legacy pi/ and no pi/audit.log anywhere: the audit log goes into the
    // legacy pi/, never into a new ~/.cct/pi that would shadow it.
    fs.mkdirSync(path.join(tmp, HOME_LEGACY_REL, "pi"), { recursive: true });
    assert.equal(cctHomePath(path.join("pi", "audit.log")), path.join(tmp, HOME_LEGACY_REL, "pi", "audit.log"));
    assert.equal(fs.existsSync(path.join(tmp, HOME_DEFAULT_REL, "pi")), false);
    fs.mkdirSync(path.join(tmp, HOME_DEFAULT_REL, "pi"), { recursive: true });
    assert.equal(cctHomePath(path.join("pi", "audit.log")), path.join(tmp, HOME_DEFAULT_REL, "pi", "audit.log"));
  });
});

test("a dangling home entry still selects the home, never the stale legacy copy", () => {
  withHome((tmp) => {
    fs.mkdirSync(path.join(tmp, HOME_DEFAULT_REL), { recursive: true });
    fs.mkdirSync(path.join(tmp, HOME_LEGACY_REL), { recursive: true });
    fs.writeFileSync(path.join(tmp, HOME_LEGACY_REL, "providers.toml"), "stale");
    fs.symlinkSync(path.join(tmp, "nowhere"), path.join(tmp, HOME_DEFAULT_REL, "providers.toml"));
    assert.equal(cctHomePath("providers.toml"), path.join(tmp, HOME_DEFAULT_REL, "providers.toml"));
    assert.deepEqual(legacyHits(), []);
  });
});

test("the home wins when both have the entry", () => {
  withHome((tmp) => {
    for (const d of [HOME_DEFAULT_REL, HOME_LEGACY_REL]) {
      fs.mkdirSync(path.join(tmp, d), { recursive: true });
      fs.writeFileSync(path.join(tmp, d, "config.toml"), "");
    }
    assert.equal(cctHomePath("config.toml"), path.join(tmp, HOME_DEFAULT_REL, "config.toml"));
  });
});

test("CCT_HOME overrides everything with no fallback", () => {
  withHome((tmp) => {
    fs.mkdirSync(path.join(tmp, HOME_LEGACY_REL), { recursive: true });
    fs.writeFileSync(path.join(tmp, HOME_LEGACY_REL, "config.toml"), "");
    process.env[ENV_HOME] = "/srv/cct";
    assert.equal(cctHome(), "/srv/cct");
    assert.equal(cctHomePath("config.toml"), path.join("/srv/cct", "config.toml"));
    assert.deepEqual(legacyHits(), []);
  });
});

test("legacyHits lists what is only in the legacy home", () => {
  withHome((tmp) => {
    assert.deepEqual(legacyHits(), []);
    fs.mkdirSync(path.join(tmp, HOME_LEGACY_REL, "pi"), { recursive: true });
    fs.writeFileSync(path.join(tmp, HOME_LEGACY_REL, "providers.toml"), "");
    fs.mkdirSync(path.join(tmp, HOME_DEFAULT_REL), { recursive: true });
    fs.writeFileSync(path.join(tmp, HOME_DEFAULT_REL, "providers.toml"), "");
    assert.deepEqual(legacyHits(), ["pi"]);
  });
});
