// env-scrub.test.mjs — #173 (pi-sandbox-hardening) T1/T2: the pure NAME-based
// env scrub policy. Run via tests/test-pi-runtime.sh.
//
// Covers: glob semantics (exact / PREFIX_* / *_SUFFIX, case-insensitive),
// keep-beats-pattern, CCT_*/LC_* prefix keeps, config merging with the
// FR-004a trust asymmetry (project layer may only tighten), sanitization of
// config-supplied globs, and non-mutation of the input.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_SCRUB_KEEP,
  DEFAULT_SCRUB_PATTERNS,
  defaultScrubPolicy,
  resolveScrubPolicy,
  sanitizeGlobs,
  sanitizeKeepGlobs,
  scrubEnv,
} from "../../adapters/pi/runtime/policy/env-scrub.ts";

// ── scrubEnv: pattern + keep semantics ───────────────────────────────────────

test("scrubEnv removes credential-shaped names and keeps baselines", () => {
  const { env, removed } = scrubEnv(
    {
      AWS_SECRET_ACCESS_KEY: "s3cr3t",
      AWS_ACCESS_KEY_ID: "AKIA...",
      GITHUB_TOKEN: "ghp_x",
      MY_SERVICE_TOKEN: "t",
      DB_PASSWORD: "p",
      PATH: "/usr/bin",
      HOME: "/home/u",
      EDITOR: "vim",
    },
    defaultScrubPolicy(),
  );
  assert.deepEqual(removed, [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "DB_PASSWORD",
    "GITHUB_TOKEN",
    "MY_SERVICE_TOKEN",
  ]);
  assert.equal(env.PATH, "/usr/bin");
  assert.equal(env.HOME, "/home/u");
  assert.equal(env.EDITOR, "vim");
  assert.equal("GITHUB_TOKEN" in env, false);
});

test("scrubEnv: keep beats pattern (provider keys/tokens, CCT_*, LC_*, AWS selectors)", () => {
  const { env, removed } = scrubEnv(
    {
      ANTHROPIC_API_KEY: "needed", // *_KEY pattern, kept by exact keep
      ANTHROPIC_AUTH_TOKEN: "needed", // *_TOKEN, kept (gateway/local-LLM setups)
      OPENAI_API_KEY: "needed",
      PI_API_KEY: "needed",
      AWS_REGION: "us-east-1", // AWS_* pattern, kept (non-secret selector)
      AWS_PROFILE: "dev",
      CCT_WORKER_ID: "w1", // CCT_* keep
      CCT_TEAM_MEMBER_ID: "m1",
      LC_ALL: "en_US.UTF-8", // LC_* keep
      SSH_KEY: "gone", // *_KEY, not kept
    },
    defaultScrubPolicy(),
  );
  assert.deepEqual(removed, ["SSH_KEY"]);
  assert.equal(env.ANTHROPIC_API_KEY, "needed");
  assert.equal(env.ANTHROPIC_AUTH_TOKEN, "needed");
  assert.equal(env.AWS_REGION, "us-east-1");
  assert.equal(env.CCT_WORKER_ID, "w1");
  assert.equal(env.LC_ALL, "en_US.UTF-8");
});

test("scrubEnv removes the review-F5 vectors (PGPASSWORD, SSH_AUTH_SOCK, *_PAT)", () => {
  const { removed } = scrubEnv(
    {
      PGPASSWORD: "p",
      SSH_AUTH_SOCK: "/tmp/agent.sock",
      DOCKER_AUTH_CONFIG: "{}",
      MY_GITHUB_PAT: "t",
      KUBECONFIG: "/home/u/.kube/config", // path pointer: deliberately NOT scrubbed
    },
    defaultScrubPolicy(),
  );
  assert.deepEqual(removed, [
    "DOCKER_AUTH_CONFIG",
    "MY_GITHUB_PAT",
    "PGPASSWORD",
    "SSH_AUTH_SOCK",
  ]);
});

test("scrubEnv matches case-insensitively", () => {
  const { removed } = scrubEnv(
    { my_api_token: "x", aws_secret_thing: "s", Path: "/bin" },
    defaultScrubPolicy(),
  );
  assert.deepEqual(removed, ["aws_secret_thing", "my_api_token"]);
});

test("scrubEnv drops undefined values and never mutates its input", () => {
  const input = { A: undefined, PATH: "/bin", X_TOKEN: "t" };
  const before = JSON.stringify(input);
  const { env } = scrubEnv(input, defaultScrubPolicy());
  assert.equal("A" in env, false);
  assert.equal(JSON.stringify(input), before);
  assert.equal(input.X_TOKEN, "t"); // input untouched
});

test("scrubEnv with an empty policy passes everything through", () => {
  const { env, removed } = scrubEnv(
    { GITHUB_TOKEN: "t", PATH: "/bin" },
    { patterns: [], keep: [] },
  );
  assert.deepEqual(removed, []);
  assert.equal(env.GITHUB_TOKEN, "t");
});

// ── glob sanitization ────────────────────────────────────────────────────────

test("sanitizeGlobs accepts only exact / PREFIX_* / *_SUFFIX shapes", () => {
  assert.deepEqual(
    sanitizeGlobs([
      "FOO",
      "FOO_*",
      "*_BAR",
      "*", // bare star: rejected
      "A*B", // inner star: rejected
      "**_X", // double star: rejected
      "BAD CHARS",
      "9LEADING", // env names cannot start with a digit
      42,
      null,
    ]),
    ["FOO", "FOO_*", "*_BAR"],
  );
  assert.deepEqual(sanitizeGlobs("not-an-array"), []);
  assert.deepEqual(sanitizeGlobs(undefined), []);
});

test("sanitizeKeepGlobs is narrower: exact / PREFIX_* only (keeps loosen)", () => {
  assert.deepEqual(
    sanitizeKeepGlobs(["FOO", "FOO_*", "*_BAR", "*", 42]),
    ["FOO", "FOO_*"], // *_SUFFIX rejected for keeps
  );
});

// ── resolveScrubPolicy: defaults ─────────────────────────────────────────────

function entry(layer, value, history = []) {
  return { layer, value, history };
}

test("resolveScrubPolicy: absent config resolves default-ON with built-ins", () => {
  const r = resolveScrubPolicy(undefined);
  assert.equal(r.enabled, true);
  assert.deepEqual(r.policy.patterns, [...DEFAULT_SCRUB_PATTERNS]);
  assert.deepEqual(r.policy.keep, [...DEFAULT_SCRUB_KEEP]);
});

test("resolveScrubPolicy: global opt-out disables; env layer re-enables", () => {
  const off = resolveScrubPolicy(
    new Map([
      ["security.env_scrub", entry("global", false, [{ layer: "defaults", value: true }])],
    ]),
  );
  assert.equal(off.enabled, false);

  const reOn = resolveScrubPolicy(
    new Map([
      [
        "security.env_scrub",
        entry("env", true, [
          { layer: "defaults", value: true },
          { layer: "global", value: false },
        ]),
      ],
    ]),
  );
  assert.equal(reOn.enabled, true);
});

// ── resolveScrubPolicy: FR-004a trust asymmetry ──────────────────────────────

test("neither in-repo layer can disable scrubbing (tighten-only)", () => {
  for (const repoLayer of ["project", "project-local"]) {
    const r = resolveScrubPolicy(
      new Map([
        [
          "security.env_scrub",
          entry(repoLayer, false, [{ layer: "defaults", value: true }]),
        ],
      ]),
    );
    assert.equal(r.enabled, true, `${repoLayer} opt-out must be ignored`);
  }
});

test("a LATER trusted opt-out beats an earlier repo enable (ordered walk)", () => {
  // global: false, then repo latches true, then the user's cli --set false.
  const r = resolveScrubPolicy(
    new Map([
      [
        "security.env_scrub",
        entry("cli", false, [
          { layer: "defaults", value: true },
          { layer: "global", value: false },
          { layer: "project", value: true },
        ]),
      ],
    ]),
  );
  assert.equal(r.enabled, false); // the user's later opt-out wins
});

test("project layer CAN enable scrubbing over a global opt-out", () => {
  const r = resolveScrubPolicy(
    new Map([
      [
        "security.env_scrub",
        entry("project", true, [
          { layer: "defaults", value: true },
          { layer: "global", value: false },
        ]),
      ],
    ]),
  );
  assert.equal(r.enabled, true);
});

test("env_scrub_extra unions across every layer including project", () => {
  const r = resolveScrubPolicy(
    new Map([
      [
        "security.env_scrub_extra",
        entry("project", ["INTERNAL_*"], [
          { layer: "global", value: ["CORP_ID"] },
        ]),
      ],
    ]),
  );
  assert.ok(r.policy.patterns.includes("INTERNAL_*"));
  assert.ok(r.policy.patterns.includes("CORP_ID"));
  assert.ok(r.policy.patterns.includes("*_TOKEN")); // defaults still present
});

test("env_scrub_keep from either in-repo layer is ignored (keeps loosen)", () => {
  for (const repoLayer of ["project", "project-local"]) {
    const r = resolveScrubPolicy(
      new Map([
        [
          "security.env_scrub_keep",
          entry(repoLayer, ["EVIL_TOKEN"], [
            { layer: "global", value: ["MY_BUILD_KEY"] },
          ]),
        ],
      ]),
    );
    assert.ok(r.policy.keep.includes("MY_BUILD_KEY")); // trusted global keep
    assert.equal(
      r.policy.keep.includes("EVIL_TOKEN"),
      false,
      `${repoLayer} keep must be ignored`,
    );
  }
});

test("config-supplied malformed globs are dropped, defaults intact", () => {
  const r = resolveScrubPolicy(
    new Map([
      ["security.env_scrub_extra", entry("global", ["**", "A*B", "OK_*"])],
      ["security.env_scrub_keep", entry("global", ["*", "GOOD_NAME"])],
    ]),
  );
  assert.ok(r.policy.patterns.includes("OK_*"));
  assert.equal(r.policy.patterns.includes("**"), false);
  assert.equal(r.policy.patterns.includes("A*B"), false);
  assert.ok(r.policy.keep.includes("GOOD_NAME"));
  assert.equal(r.policy.keep.includes("*"), false);
});

// ── end-to-end: resolved policy drives scrubEnv ──────────────────────────────

test("resolved policy end-to-end: extra tightens, trusted keep survives", () => {
  const r = resolveScrubPolicy(
    new Map([
      ["security.env_scrub_extra", entry("global", ["CORP_*"])],
      ["security.env_scrub_keep", entry("global", ["RELEASE_SIGNING_KEY"])],
    ]),
  );
  const { env, removed } = scrubEnv(
    {
      CORP_SESSION: "x",
      RELEASE_SIGNING_KEY: "keepme",
      GITHUB_TOKEN: "gone",
      PATH: "/bin",
    },
    r.policy,
  );
  assert.deepEqual(removed, ["CORP_SESSION", "GITHUB_TOKEN"]);
  assert.equal(env.RELEASE_SIGNING_KEY, "keepme");
  assert.equal(env.PATH, "/bin");
});

// ── resolveScrubPolicy: disabledBy provenance (phase-2 review F3) ────────────

test("disabledBy names the layer whose explicit false won", () => {
  const g = resolveScrubPolicy(
    new Map([
      ["security.env_scrub", entry("global", false, [{ layer: "defaults", value: true }])],
    ]),
  );
  assert.equal(g.enabled, false);
  assert.equal(g.disabledBy, "global");

  const c = resolveScrubPolicy(
    new Map([
      [
        "security.env_scrub",
        entry("cli", false, [
          { layer: "defaults", value: true },
          { layer: "project", value: true },
        ]),
      ],
    ]),
  );
  assert.equal(c.enabled, false);
  assert.equal(c.disabledBy, "cli");
});

test("disabledBy is null whenever scrubbing is enabled", () => {
  assert.equal(resolveScrubPolicy(undefined).disabledBy, null);
  const repoLatch = resolveScrubPolicy(
    new Map([
      [
        "security.env_scrub",
        entry("project", true, [
          { layer: "defaults", value: true },
          { layer: "global", value: false },
        ]),
      ],
    ]),
  );
  assert.equal(repoLatch.enabled, true);
  assert.equal(repoLatch.disabledBy, null);
});

// ── CCT_CONFIG__* carrier namespace (post-review P1) ─────────────────────────

test("BOTH env config carriers are scrubbed, contract vars survive", () => {
  const { env, removed } = scrubEnv(
    {
      CCT_CONFIG__providers__api_key: "sk-secret", // credential-shaped
      CCT_CONFIG__providers__auth: "also-secret", // NOT credential-shaped — still removed
      CCT_CONFIG__security__env_scrub: "false", // benign config — still removed (namespace rule)
      CCT_CLI_SETS: "providers.api_key=sk-via-cli", // the --set carrier — removed
      cct_cli_sets: "case-trick", // case-insensitive carrier match
      CCT_WORKER_ID: "w1",
      CCT_AGENT_DEPTH: "1",
      CCT_TEAM_MEMBER_ID: "m1",
    },
    defaultScrubPolicy(),
  );
  assert.deepEqual(removed, [
    "CCT_CLI_SETS",
    "CCT_CONFIG__providers__api_key",
    "CCT_CONFIG__providers__auth",
    "CCT_CONFIG__security__env_scrub",
    "cct_cli_sets",
  ]);
  assert.equal(env.CCT_WORKER_ID, "w1");
  assert.equal(env.CCT_AGENT_DEPTH, "1");
  assert.equal(env.CCT_TEAM_MEMBER_ID, "m1");
});

test("only an EXACT keep restores a carrier var; prefix keeps never do", () => {
  const exact = scrubEnv(
    { CCT_CONFIG__autonomy__max_concurrency: "2" },
    {
      patterns: [...DEFAULT_SCRUB_PATTERNS],
      keep: [...DEFAULT_SCRUB_KEEP, "CCT_CONFIG__autonomy__max_concurrency"],
    },
  );
  assert.equal(exact.env.CCT_CONFIG__autonomy__max_concurrency, "2");

  const prefix = scrubEnv(
    { CCT_CONFIG__providers__api_key: "sk", CCT_CLI_SETS: "a=b" },
    { patterns: [], keep: ["CCT_CONFIG__*", "CCT_*"] },
  );
  assert.deepEqual(prefix.removed, [
    "CCT_CLI_SETS",
    "CCT_CONFIG__providers__api_key",
  ]);

  // A *_SUFFIX keep entry (unreachable from config, reachable via a
  // hand-built policy) must not rescue a carrier either (final-review F2).
  const suffix = scrubEnv(
    { CCT_CONFIG__providers__api_key: "sk" },
    { patterns: [], keep: ["*_KEY"] },
  );
  assert.deepEqual(suffix.removed, ["CCT_CONFIG__providers__api_key"]);

  // The exact-name escape works for CCT_CLI_SETS too (trusted scope).
  const cliKept = scrubEnv(
    { CCT_CLI_SETS: "a=b" },
    { patterns: [], keep: ["CCT_CLI_SETS"] },
  );
  assert.deepEqual(cliKept.removed, []);
});
