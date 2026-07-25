// fuzz.test.mjs — Property/fuzz + malformed-input tests (T5.5). Run via
// tests/test-pi-runtime.sh.
//
// Deterministic (seeded PRNG) so any failure is reproducible. Asserts:
//  - never-throw invariants across every command parser / path matcher /
//    lifecycle-event translator on adversarial + malformed input;
//  - the security property that a denied / network / package-install command
//    cannot be smuggled past classification by chaining or quoting;
//  - protected basenames cannot be evaded via ../ traversal or wildcards.
//
// These tests change no enforcement behavior; they exercise existing code.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  checkCommand,
  checkExecPolicy,
  checkPath,
  matchGlob,
  normalizeCommand,
  splitCommands,
} from "../../adapters/pi/runtime/policy/permissions.ts";
import {
  classifyNetwork,
  classifyPackageInstall,
  stripPrivilegePrefix,
} from "../../adapters/pi/runtime/policy/protected-ops.ts";
import {
  matchCandidates,
  resolveTarget,
} from "../../adapters/pi/runtime/policy/protected.ts";
import { dispatchHooks } from "../../adapters/pi/runtime/hooks/adapter.ts";
import {
  toClaudeStdin,
  translateSessionStart,
  translateToolCall,
} from "../../adapters/pi/runtime/hooks/events.ts";

// ── Deterministic PRNG ─────────────────────────────────────────────────────
function mulberry32(seed) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const SEEDS = [1, 7, 42, 1337, 90210];
const ITER = 250;
const pick = (rng, arr) => arr[Math.floor(rng() * arr.length)];
const randInt = (rng, n) => Math.floor(rng() * n);

function rules(over = {}) {
  return {
    toolsAllow: [],
    toolsDeny: [],
    pathsDeny: [".env", ".git/config", "**/*.pem", "**/id_rsa*"],
    pathsAsk: [],
    commandsDeny: ["git push --force", "git reset --hard", "rm -rf /"],
    commandsAsk: [],
    askResolution: "deny",
    interactive: false,
    denyNetwork: false,
    allowPackageInstall: true,
    failClosed: true,
    ...over,
  };
}

// ── Corpora ────────────────────────────────────────────────────────────────
const BENIGN = ["ls", "echo hi", "cat f", "pwd", "npm run build", "git status", "git log", "make"];
const SEPARATORS = [" ; ", " && ", " || ", " | ", " & ", "\n"];
const DENIED = ["git push --force", "git reset --hard", "rm -rf /"];
const NETWORK = ["curl http://x", "wget http://y", "git push", "ssh host", "scp a host:b"];
const INSTALL = ["npm install", "pip install flask", "cargo install ripgrep", "npx foo"];
const PRIV = ["", "sudo ", "sudo -u root ", "env X=1 ", "FOO=bar "];
const PROTECTED_BASENAMES = [".env", "key.pem", "id_rsa", "id_rsa.pub"];
const PATH_SEGMENTS = ["a", "b", "src", "..", ".", "deep*", "x?y", "node_modules"];

function randCommand(rng, inject) {
  const n = 1 + randInt(rng, 3);
  const pieces = [];
  for (let i = 0; i < n; i++) pieces.push(pick(rng, BENIGN));
  if (inject) pieces.splice(randInt(rng, pieces.length + 1), 0, pick(rng, PRIV) + inject);
  // Join with random top-level separators (benign pieces carry no separators).
  let out = pieces[0];
  for (let i = 1; i < pieces.length; i++) out += pick(rng, SEPARATORS) + pieces[i];
  return out;
}

function randPath(rng) {
  const depth = randInt(rng, 5);
  const segs = [];
  for (let i = 0; i < depth; i++) segs.push(pick(rng, PATH_SEGMENTS));
  segs.push(pick(rng, PROTECTED_BASENAMES)); // protected basename is the final segment
  return segs.join("/");
}

// ── Never-throw invariants ─────────────────────────────────────────────────
test("fuzz: command parsers/classifiers never throw on adversarial input", () => {
  const r = rules({ denyNetwork: true, allowPackageInstall: false });
  const NOISE = ['"', "'", "`", "$(", ")", "|", "&", ";", "\\", "\n", "  ", "()", "$()", "``"];
  for (const seed of SEEDS) {
    const rng = mulberry32(seed);
    for (let i = 0; i < ITER; i++) {
      // Mix structured commands with raw noise to stress the parser.
      let cmd = randCommand(rng, pick(rng, [...DENIED, ...NETWORK, ...INSTALL, ""]));
      for (let k = 0; k < randInt(rng, 4); k++) {
        cmd = cmd.slice(0, randInt(rng, cmd.length + 1)) + pick(rng, NOISE) + cmd;
      }
      try {
        splitCommands(cmd);
        normalizeCommand(cmd);
        checkCommand(r, cmd);
        checkExecPolicy(r, cmd);
        classifyPackageInstall(cmd);
        classifyNetwork(cmd);
        stripPrivilegePrefix(cmd.split(/\s+/));
      } catch (e) {
        assert.fail(`threw on command ${JSON.stringify(cmd)}: ${e.message}`);
      }
    }
  }
});

test("fuzz: path matchers never throw on adversarial input", () => {
  const r = rules();
  for (const seed of SEEDS) {
    const rng = mulberry32(seed);
    for (let i = 0; i < ITER; i++) {
      const p = randPath(rng) + pick(rng, ["", "/../..", "//", "\\", "*", "?"]);
      try {
        resolveTarget("/proj", p);
        const { candidates } = matchCandidates("/proj", p);
        for (const c of candidates) for (const g of r.pathsDeny) matchGlob(g, c);
      } catch (e) {
        assert.fail(`threw on path ${JSON.stringify(p)}: ${e.message}`);
      }
    }
  }
});

// ── Security property: no smuggling by chaining/quoting ─────────────────────
test("fuzz: a denied command cannot be hidden by chaining", () => {
  const r = rules();
  for (const seed of SEEDS) {
    const rng = mulberry32(seed);
    for (let i = 0; i < ITER; i++) {
      const denied = pick(rng, DENIED);
      const cmd = randCommand(rng, denied);
      const v = checkCommand(r, cmd);
      assert.equal(v.effective, "deny", `denied '${denied}' escaped in: ${JSON.stringify(cmd)}`);
    }
  }
});

test("regression: privilege/env prefixes cannot hide a denied command (T5.5 fuzz finding)", () => {
  const r = rules();
  // Bug the fuzz harness found: sudo / env / assignment prefixes bypassed the
  // denied_commands denylist. checkCommand now strips them before matching.
  const vectors = [
    "FOO=bar git reset --hard",
    "sudo git push --force",
    "env X=1 rm -rf /",
    "sudo -u root git reset --hard",
    "echo ok && FOO=bar git push --force",
  ];
  for (const cmd of vectors) {
    assert.equal(checkCommand(r, cmd).effective, "deny", `should deny: ${cmd}`);
  }
  // Control: an env-assignment on a non-denied command still passes.
  assert.equal(checkCommand(r, "FOO=bar npm run build").effective, "allow");
});

test("fuzz: network + package-install commands cannot be hidden by chaining", () => {
  const rNet = rules({ denyNetwork: true });
  const rPkg = rules({ allowPackageInstall: false });
  for (const seed of SEEDS) {
    const rng = mulberry32(seed);
    for (let i = 0; i < ITER; i++) {
      const net = pick(rng, NETWORK);
      const netCmd = randCommand(rng, net);
      assert.equal(
        checkExecPolicy(rNet, netCmd).effective,
        "deny",
        `network '${net}' escaped in: ${JSON.stringify(netCmd)}`,
      );
      const pkg = pick(rng, INSTALL);
      const pkgCmd = randCommand(rng, pkg);
      assert.equal(
        checkExecPolicy(rPkg, pkgCmd).effective,
        "deny",
        `install '${pkg}' escaped in: ${JSON.stringify(pkgCmd)}`,
      );
    }
  }
});

// ── Security property: traversal/wildcards can't evade protected basenames ──
test("fuzz: protected basenames are caught through traversal + wildcards", () => {
  const r = rules();
  for (const seed of SEEDS) {
    const rng = mulberry32(seed);
    for (let i = 0; i < ITER; i++) {
      const p = randPath(rng);
      const { candidates } = matchCandidates("/proj", p);
      const denied = candidates.some(
        (c) => checkPath(r, c).effective === "deny",
      );
      assert.equal(denied, true, `protected path evaded: ${JSON.stringify(p)}`);
    }
  }
});

// ── Malformed lifecycle events ─────────────────────────────────────────────
test("fuzz: translators + toClaudeStdin never throw on malformed input", () => {
  const JUNK = [null, undefined, 42, "x", true, {}, [], { file_path: 5 }, { path: {} }, { cmd: [] }];
  for (const seed of SEEDS) {
    const rng = mulberry32(seed);
    for (let i = 0; i < ITER; i++) {
      const tool = pick(rng, ["edit", "write", "bash", "", "EDIT", "unknown", null, 7]);
      const input = pick(rng, JUNK);
      const session = { interactive: pick(rng, [true, false, 0, "no"]), mode: pick(rng, ["tui", null]) };
      try {
        const ev = translateToolCall(tool, input, pick(rng, ["/p", "", null]), session);
        toClaudeStdin(ev);
        toClaudeStdin(translateSessionStart(pick(rng, ["/p", null]), session));
      } catch (e) {
        assert.fail(`threw: tool=${JSON.stringify(tool)} input=${JSON.stringify(input)}: ${e.message}`);
      }
    }
  }
});

test("fuzz: dispatchHooks tolerates malformed events; support gate holds", () => {
  const SUPPORTS = ["supported", "degraded", "unsupported", undefined, null, "bogus", 3];
  const EVENTS = ["PreToolUse", "PostToolUse", "Stop", "Notification", "", null, 9];
  for (const seed of SEEDS) {
    const rng = mulberry32(seed);
    for (let i = 0; i < ITER; i++) {
      const ev = {
        event: pick(rng, EVENTS),
        phase: pick(rng, ["pre", "post", null]),
        tool: pick(rng, ["edit", "bash", null, 5]),
        support: pick(rng, SUPPORTS),
        cwd: pick(rng, ["/p", null]),
        session: { interactive: false, mode: "print" },
        origin: "pi",
      };
      let res;
      try {
        res = dispatchHooks(ev, [], {}, () => {});
      } catch (e) {
        assert.fail(`dispatchHooks threw on ${JSON.stringify(ev)}: ${e.message}`);
      }
      // Support gate: anything that is not exactly "supported" must not run.
      if (ev.support !== "supported") assert.equal(res.ran, false);
    }
  }
});
