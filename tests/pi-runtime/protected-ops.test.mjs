// protected-ops.test.mjs — Unit tests for T5.3 package-install + network policy
// (FR-009). Run via tests/test-pi-runtime.sh.
//
// Covers the pure classifiers (manager+verb package-install, network-binary /
// git-subcommand, sudo/env prefix stripping), checkExecPolicy enforcement
// (definite deny, ambiguous fail-open/closed, chained commands), the
// default-config no-new-block regression guard, and rulesFromConfig mapping.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  classifyNetwork,
  classifyPackageInstall,
  stripPrivilegePrefix,
} from "../../adapters/pi/runtime/policy/protected-ops.ts";
import {
  checkExecPolicy,
  rulesFromConfig,
} from "../../adapters/pi/runtime/policy/permissions.ts";

function rules(over = {}) {
  return {
    toolsAllow: [],
    toolsDeny: [],
    pathsDeny: [],
    pathsAsk: [],
    commandsDeny: [],
    commandsAsk: [],
    askResolution: "deny",
    interactive: false,
    denyNetwork: false,
    allowPackageInstall: true,
    failClosed: true,
    ...over,
  };
}

// ── classifyPackageInstall ─────────────────────────────────────────────────

test("package-install positives: manager + install verb", () => {
  const yes = [
    "npm install",
    "npm i",
    "npm ci",
    "npm install -g eslint",
    "yarn add left-pad",
    "yarn", // bare yarn == install
    "pnpm install",
    "pip install requests",
    "pip3 install -r requirements.txt",
    "python -m pip install flask",
    "uv pip install ruff",
    "poetry add httpx",
    "cargo install ripgrep",
    "go get github.com/x/y",
    "go install ./cmd/foo",
    "gem install bundler",
    "apt-get install curl",
    "brew install jq",
    "pipx install black",
    "bundle add rails",
    "composer require monolog/monolog",
    "npx create-react-app app",
    "bunx cowsay hi",
    "pnpm dlx prettier",
    "uvx ruff",
  ];
  for (const cmd of yes) {
    assert.equal(classifyPackageInstall(cmd).match, true, `should match: ${cmd}`);
  }
});

test("package-install negatives: not the manager alone", () => {
  const no = [
    "npm run build",
    "npm test",
    "yarn build",
    "cargo build",
    "cargo test",
    "go build ./...",
    "pip --version",
    "python app.py",
    "make",
    "ls -la",
    "git commit -m x",
    "echo npm install", // echo, not npm
  ];
  for (const cmd of no) {
    assert.equal(classifyPackageInstall(cmd).match, false, `should NOT match: ${cmd}`);
  }
});

test("package-install ambiguous: install-ish verb after unknown binary", () => {
  assert.deepEqual(classifyPackageInstall("make install"), {
    match: false,
    ambiguous: true,
    manager: "make",
  });
  assert.equal(classifyPackageInstall("mvn install").ambiguous, true);
  assert.equal(classifyPackageInstall("make build").ambiguous, false);
});

// ── classifyNetwork ────────────────────────────────────────────────────────

test("network positives: known binaries + network git subcommands", () => {
  const yes = [
    "curl https://x",
    "wget http://y",
    "nc -l 8080",
    "ssh host",
    "scp a host:b",
    "sftp host",
    "telnet host",
    "ftp host",
    "rsync a host:b",
    "git clone https://x",
    "git fetch origin",
    "git pull",
    "git push",
    "git -C /repo push", // global value-flag skipped
    "npx foo", // dlx is also network (decision A)
  ];
  for (const cmd of yes) {
    assert.equal(classifyNetwork(cmd).match, true, `should match: ${cmd}`);
  }
});

test("network negatives: local git + ordinary commands", () => {
  const no = [
    "git status",
    "git commit -m x",
    "git add .",
    "git diff",
    "git log",
    "git checkout main",
    "echo hi",
    "cat file",
    "ls",
  ];
  for (const cmd of no) {
    assert.equal(classifyNetwork(cmd).match, false, `should NOT match: ${cmd}`);
  }
});

// ── sudo / env prefix stripping ────────────────────────────────────────────

test("stripPrivilegePrefix removes sudo (+flags) and env assignments", () => {
  assert.deepEqual(stripPrivilegePrefix(["sudo", "npm", "install"]), ["npm", "install"]);
  assert.deepEqual(stripPrivilegePrefix(["sudo", "-u", "root", "npm", "i"]), ["npm", "i"]);
  assert.deepEqual(stripPrivilegePrefix(["env", "X=1", "pip", "install"]), ["pip", "install"]);
  assert.deepEqual(stripPrivilegePrefix(["FOO=bar", "npm", "ci"]), ["npm", "ci"]);
  // Stripping composes with classification.
  assert.equal(classifyPackageInstall("sudo npm install").match, true);
  assert.equal(classifyPackageInstall("sudo -u root npm install").match, true);
  assert.equal(classifyPackageInstall("env NODE_ENV=prod npm ci").match, true);
});

// ── checkExecPolicy enforcement ────────────────────────────────────────────

test("default config: nothing new blocks (regression guard)", () => {
  const r = rules(); // allowPackageInstall=true, denyNetwork=false
  for (const cmd of ["npm install", "curl https://x", "pip install foo", "git push"]) {
    assert.equal(checkExecPolicy(r, cmd).effective, "allow", cmd);
  }
});

test("allow_package_install=false: installs deny, scripts allow, chained caught", () => {
  const r = rules({ allowPackageInstall: false });
  const denied = checkExecPolicy(r, "npm install");
  assert.equal(denied.effective, "deny");
  assert.equal(denied.rule, "security.allow_package_install");
  assert.equal(checkExecPolicy(r, "npm run build").effective, "allow");
  assert.equal(checkExecPolicy(r, "echo hi && pip install x").effective, "deny");
});

test("deny_network=true: network denies, local git allowed", () => {
  const r = rules({ denyNetwork: true });
  const denied = checkExecPolicy(r, "curl https://evil");
  assert.equal(denied.effective, "deny");
  assert.equal(denied.rule, "security.deny_network");
  assert.equal(checkExecPolicy(r, "git push").effective, "deny");
  assert.equal(checkExecPolicy(r, "git status").effective, "allow");
});

test("ambiguous command follows fail_closed", () => {
  const closed = rules({ allowPackageInstall: false, failClosed: true });
  assert.equal(checkExecPolicy(closed, "make install").effective, "deny");
  const open = rules({ allowPackageInstall: false, failClosed: false });
  assert.equal(checkExecPolicy(open, "make install").effective, "allow");
});

test("both flags restrictive: npx blocked by package policy first", () => {
  const r = rules({ allowPackageInstall: false, denyNetwork: true });
  const v = checkExecPolicy(r, "npx foo");
  assert.equal(v.effective, "deny");
  assert.equal(v.rule, "security.allow_package_install");
});

// ── rulesFromConfig mapping ────────────────────────────────────────────────

test("rulesFromConfig maps the three security flags with correct defaults", () => {
  const strict = rulesFromConfig((k) => {
    const m = {
      "security.deny_network": true,
      "security.allow_package_install": false,
      "security.fail_closed": false,
    };
    return k in m ? m[k] : undefined;
  }, false);
  assert.equal(strict.denyNetwork, true);
  assert.equal(strict.allowPackageInstall, false);
  assert.equal(strict.failClosed, false);

  // Absent config -> permissive package/network, fail-closed default true.
  const dflt = rulesFromConfig(() => undefined, false);
  assert.equal(dflt.denyNetwork, false);
  assert.equal(dflt.allowPackageInstall, true);
  assert.equal(dflt.failClosed, true);
});
