// enforcement.test.mjs — Unit tests for the CCT Pi enforcement modules.
// Run via tests/test-pi-runtime.sh (node --experimental-strip-types --test).
//
// Covers specs/pi-harness-adoption: FR-006/007 (SDD classification +
// gating, validate-spec.sh parity), FR-008 (phase state machine +
// persistence + corrupt-state recovery), FR-009 (allow/ask/deny with
// deterministic headless resolution, chained-command scanning), and the
// protected-path canonicalization/symlink defenses.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  checkCommand,
  checkPath,
  checkTool,
  matchGlob,
  splitCommands,
} from "../../adapters/pi/runtime/policy/permissions.ts";
import { matchCandidates, resolveTarget } from "../../adapters/pi/runtime/policy/protected.ts";
import { audit, auditLogPath, resolveAuditMode } from "../../adapters/pi/runtime/policy/audit.ts";
import {
  gateBuild,
  parseFrontmatter,
  validateSpecDir,
  isSpecPath,
} from "../../adapters/pi/runtime/workflow/sdd.ts";
import {
  buildWriteGate,
  loadState,
  resolvePhasePolicy,
  saveState,
  transition,
} from "../../adapters/pi/runtime/workflow/phases.ts";
import { loadLayeredConfig } from "../../adapters/pi/runtime/config/loader.ts";
import {
  classifyRisk,
  loadClassification,
  overrideClassification,
  resolveClassification,
} from "../../adapters/pi/runtime/workflow/classify.ts";

const NOW = "2026-07-21T20:00:00.000Z";

function tempTree(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-enf-test-"));
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return dir;
}

const RULES = {
  toolsAllow: [],
  toolsDeny: [],
  pathsDeny: [".env", ".git/config", "**/*.pem", "secrets/**"],
  pathsAsk: ["infra/**"],
  commandsDeny: ["git push --force", "git reset --hard", "rm -rf /"],
  commandsAsk: ["git push"],
  askResolution: "deny",
  interactive: false,
};

// ── glob + command matching ─────────────────────────────────

test("glob: segment, depth, and bare-name-at-any-depth semantics", () => {
  assert.ok(matchGlob("**/*.pem", "certs/server.pem"));
  assert.ok(matchGlob("**/*.pem", "a/b/c/k.pem"));
  assert.ok(matchGlob(".env", ".env"));
  assert.ok(matchGlob(".env", "packages/api/.env"), "bare name matches at depth");
  assert.ok(!matchGlob(".env", ".envrc"));
  assert.ok(matchGlob("secrets/**", "secrets/prod/key.json"));
  assert.ok(!matchGlob("secrets/**", "not-secrets/key.json"));
});

test("commands: chained, piped, and substituted commands are scanned", () => {
  const cases = [
    "git push --force",
    "git push --force origin main",
    "echo hi && git push --force",
    "true; git reset --hard HEAD~3",
    "ls | xargs -I{} sh -c 'true' && git push   --force",
    "echo $(git reset --hard)",
  ];
  for (const c of cases) {
    assert.equal(checkCommand(RULES, c).effective, "deny", `should deny: ${c}`);
  }
  assert.equal(checkCommand(RULES, "git push --force-with-lease").effective, "deny", "prefix+flag still denied");
  assert.equal(checkCommand(RULES, "git commit -m 'x'").effective, "allow");
  // splitCommands: quotes protect separators
  assert.deepEqual(splitCommands('echo "a && b"'), ['echo "a && b"']);
});

test("commands: backslash-in-quotes cannot hide a separator", () => {
  // POSIX processes backslash escapes in "..." but not in '...'. Each of
  // these really does run the trailing command in a shell, so each must
  // deny — a scanner that keeps the quote open would see one benign command.
  const cases = [
    "echo 'a\\'; git push --force",
    'echo "a\\\\"; git push --force',
    'echo "a\\"b" ; git push --force',
  ];
  for (const c of cases) {
    assert.equal(checkCommand(RULES, c).effective, "deny", `should deny: ${c}`);
  }
  // An escaped quote still keeps a double-quoted string open.
  assert.deepEqual(splitCommands('echo "a\\" && b"'), ['echo "a\\" && b"']);
});

test("permissions: headless ask resolves deterministically (FR-022)", () => {
  assert.equal(checkCommand(RULES, "git push origin main").effective, "deny");
  const failRules = { ...RULES, askResolution: "fail" };
  assert.equal(checkCommand(failRules, "git push origin main").effective, "fail");
  const allowRules = { ...RULES, askResolution: "allow" };
  assert.equal(checkCommand(allowRules, "git push origin main").effective, "allow");
  assert.equal(checkPath(RULES, "infra/main.tf").effective, "deny");
});

test("permissions: tool allowlist enforces peer-reviewer read-only set", () => {
  const reviewer = { ...RULES, toolsAllow: ["read", "grep", "find", "ls"] };
  assert.equal(checkTool(reviewer, "read").effective, "allow");
  assert.equal(checkTool(reviewer, "write").effective, "deny");
  assert.equal(checkTool(reviewer, "bash").effective, "deny");
  const denyAll = { ...RULES, toolsDeny: ["*"] };
  assert.equal(checkTool(denyAll, "read").effective, "deny");
});

// ── protected paths: canonicalization + symlinks ────────────

test("protected: traversal and symlinks cannot bypass patterns", () => {
  const dir = tempTree({ "secrets/prod/key.json": "{}", "src/app.ts": "//" });
  fs.symlinkSync(path.join(dir, "secrets"), path.join(dir, "innocent"));

  // Traversal: src/../secrets/x resolves into secrets/**
  const t1 = matchCandidates(dir, "src/../secrets/prod/key.json");
  assert.ok(t1.candidates.some((c) => checkPath(RULES, c).effective === "deny"));

  // Symlink: innocent/prod/key.json canonicalizes into secrets/**
  const t2 = matchCandidates(dir, "innocent/prod/key.json");
  assert.ok(t2.resolved.viaSymlink);
  assert.ok(t2.candidates.some((c) => checkPath(RULES, c).effective === "deny"));

  // New file inside a symlinked dir still canonicalizes
  const t3 = matchCandidates(dir, "innocent/new/deploy.pem");
  assert.ok(t3.candidates.some((c) => checkPath(RULES, c).effective === "deny"));

  // Escape outside the project is flagged
  const t4 = resolveTarget(dir, "../../etc/passwd");
  assert.ok(t4.outsideProject);

  // Plain files stay allowed
  const t5 = matchCandidates(dir, "src/app.ts");
  assert.ok(t5.candidates.every((c) => checkPath(RULES, c).effective === "allow"));
});

// ── SDD gate (validate-spec.sh parity) ──────────────────────

const PLAN_FULL = `---
spec_mode: full
feature_id: demo-feature
risk_category: feature
justification: "test"
status: draft
origin:
  user_message: "x"
---
# plan
`;

test("sdd: frontmatter parse + full-mode artifact completeness", () => {
  const fm = parseFrontmatter(PLAN_FULL);
  assert.equal(fm.spec_mode, "full");
  assert.equal(fm.feature_id, "demo-feature");

  const dir = tempTree({ "specs/demo-feature/plan.md": PLAN_FULL });
  let gate = gateBuild(dir, "demo-feature");
  assert.equal(gate.pass, false);
  assert.ok(gate.reasons.some((r) => r.includes("spec.md required")));

  fs.writeFileSync(path.join(dir, "specs/demo-feature/spec.md"), "# spec\n## Requirements\n");
  gate = gateBuild(dir, "demo-feature");
  assert.ok(gate.reasons.some((r) => r.includes("tasks.md required")));

  fs.writeFileSync(path.join(dir, "specs/demo-feature/tasks.md"), "# tasks\n");
  gate = gateBuild(dir, "demo-feature");
  assert.equal(gate.pass, true, gate.reasons.join("; "));
});

test("sdd: unresolved [NEEDS CLARIFICATION] markers block; none-mode rules", () => {
  const dir = tempTree({
    "specs/f1/plan.md": PLAN_FULL.replace("demo-feature", "f1"),
    "specs/f1/spec.md": "# spec\n[NEEDS CLARIFICATION]: which auth flow?\n",
    "specs/f1/tasks.md": "# tasks\n",
    "specs/f2/plan.md": `---\nspec_mode: none\nfeature_id: f2\njustification: "docs only"\nstatus: draft\n---\n`,
    "specs/f3/plan.md": `---\nspec_mode: none\nfeature_id: f3\njustification: "x"\nstatus: draft\n---\n`,
    "specs/f3/spec.md": "# should not exist\n",
  });
  const g1 = validateSpecDir(path.join(dir, "specs/f1"));
  assert.ok(g1.reasons.some((r) => r.includes("NEEDS CLARIFICATION")));
  assert.equal(validateSpecDir(path.join(dir, "specs/f2")).pass, true);
  const g3 = validateSpecDir(path.join(dir, "specs/f3"));
  assert.ok(g3.reasons.some((r) => r.includes("must NOT exist")));
});

test("sdd: no active feature fails gate with actionable reason; spec paths exempt", () => {
  const dir = tempTree({});
  const gate = gateBuild(dir, null);
  assert.equal(gate.pass, false);
  assert.match(gate.reasons[0], /cct:phase build/);
  assert.ok(isSpecPath("specs/x/plan.md"));
  assert.ok(isSpecPath(".cct/pi-workflow.json"));
  assert.ok(!isSpecPath("src/app.ts"));
});

// ── phase state machine ─────────────────────────────────────

test("phases: build entry gates on SDD; review requires prior build; state persists", () => {
  const dir = tempTree({ "specs/ok/plan.md": PLAN_FULL.replace("demo-feature", "ok") });
  fs.writeFileSync(path.join(dir, "specs/ok/spec.md"), "# spec\n");
  fs.writeFileSync(path.join(dir, "specs/ok/tasks.md"), "# tasks\n");

  let state = loadState(dir); // fresh
  assert.equal(state.phase, "research");

  // review before build → blocked
  let r = transition(dir, state, "review", "ok", NOW);
  assert.equal(r.ok, false);
  assert.match(r.reasons[0], /requires a prior build/);

  // build on incomplete feature → blocked
  r = transition(dir, state, "build", "missing-feature", NOW);
  assert.equal(r.ok, false);

  // plan → build (complete artifacts) → review
  r = transition(dir, state, "plan", "ok", NOW);
  assert.ok(r.ok);
  r = transition(dir, r.state, "build", null, NOW);
  assert.ok(r.ok, r.reasons.join("; "));
  assert.equal(r.gate.pass, true);
  r = transition(dir, r.state, "review", null, NOW);
  assert.ok(r.ok);

  // persistence across "sessions"
  const reloaded = loadState(dir);
  assert.equal(reloaded.phase, "review");
  assert.equal(reloaded.featureId, "ok");

  // corrupt state file → fresh default, no crash
  fs.writeFileSync(path.join(dir, ".cct/pi-workflow.json"), "{not json");
  assert.equal(loadState(dir).phase, "research");
});

test("phases: buildWriteGate blocks only in gated build phase", () => {
  const dir = tempTree({ "specs/bad/plan.md": PLAN_FULL.replace("demo-feature", "bad") });
  const inBuild = { phase: "build", featureId: "bad", enteredAt: NOW, history: [] };
  assert.ok(buildWriteGate(dir, inBuild, true), "incomplete feature in build → gate object");
  assert.equal(buildWriteGate(dir, inBuild, false), null, "sdd disabled → no gate");
  const inPlan = { ...inBuild, phase: "plan" };
  assert.equal(buildWriteGate(dir, inPlan, true), null, "plan phase → no build gate");

  // saveState/loadState round-trip helper coverage
  saveState(dir, inBuild);
  assert.equal(loadState(dir).phase, "build");
});

// ── SDD risk classifier (FR-006, T4.1) ──────────────────────

test("classify: category and file-count map to spec_mode", () => {
  assert.equal(classifyRisk({ category: "security" }).mode, "full");
  assert.equal(classifyRisk({ category: "schema" }).mode, "full");
  assert.equal(classifyRisk({ category: "integration" }).mode, "full");
  assert.equal(classifyRisk({ category: "feature", filesTouched: 5 }).mode, "full");
  assert.equal(classifyRisk({ category: "feature", filesTouched: 2 }).mode, "lightweight");
  assert.equal(classifyRisk({ category: "feature", filesTouched: 1 }).mode, "lightweight");
  assert.equal(classifyRisk({ category: "bug" }).mode, "none");
  assert.equal(classifyRisk({ category: "docs" }).mode, "none");
});

test("classify: a security-relevant change escalates to full", () => {
  // The escalation rule: risk beats size and category.
  const bug = classifyRisk({ category: "bug", securityRelevant: true });
  assert.equal(bug.mode, "full");
  assert.match(bug.justification, /security-relevant/);
  assert.equal(classifyRisk({ category: "docs", securityRelevant: true }).mode, "full");
});

test("classify: every classification carries a justification", () => {
  for (const category of ["security", "schema", "integration", "feature", "bug", "docs"]) {
    const c = classifyRisk({ category });
    assert.ok(c.justification && c.justification.length > 0, `no justification for ${category}`);
    assert.equal(c.source, "auto");
  }
});

test("classify: auto-classification persists and reloads", () => {
  const dir = tempTree({});
  const a = resolveClassification(dir, "f1", { category: "feature", filesTouched: 1 });
  assert.equal(a.mode, "lightweight");
  assert.equal(loadClassification(dir, "f1").mode, "lightweight");
  assert.equal(loadClassification(dir, "f1").source, "auto");
});

test("classify: a user override wins over re-classification (FR-006)", () => {
  const dir = tempTree({});
  resolveClassification(dir, "f2", { category: "feature", filesTouched: 1 });
  const o = overrideClassification(dir, "f2", "full", "auth touched after review");
  assert.equal(o.mode, "full");
  assert.equal(o.source, "user");
  // Re-running the classifier with different input must NOT discard the human decision.
  const again = resolveClassification(dir, "f2", { category: "docs" });
  assert.equal(again.mode, "full");
  assert.equal(again.source, "user");
});

test("classify: a corrupt classification store recovers to null", () => {
  const dir = tempTree({ ".cct/pi-classification.json": "{ not json" });
  assert.equal(loadClassification(dir, "whatever"), null);
});

test("classify: unknown feature is null, not an error", () => {
  const dir = tempTree({});
  assert.equal(loadClassification(dir, "never-classified"), null);
});

// ── per-phase policy: resolve + report (FR-008, T4.3) ───────

function getterFor(env = {}) {
  const r = loadLayeredConfig({
    globalDir: "/nonexistent-g",
    projectDir: "/nonexistent-p",
    trusted: false,
    profile: "disciplined",
    env,
  });
  return (k) => r.resolved.get(k)?.value;
}

test("phase policy: defaults differ per phase and carry the reported fields", () => {
  const get = getterFor();
  const research = resolvePhasePolicy(get, "research");
  const build = resolvePhasePolicy(get, "build");
  // research is read-oriented; build can write/edit/bash.
  assert.deepEqual(research.tools, ["read", "grep", "find", "ls"]);
  assert.ok(build.tools.includes("bash") && build.tools.includes("edit"));
  assert.equal(research.permissions, "read-only");
  assert.equal(build.permissions, "build");
  // model defaults to inherit — actual routing (respawn) is Phase 7.
  assert.equal(build.model, "inherit");
  // every reported field is present and typed.
  for (const p of [research, build]) {
    assert.equal(typeof p.thinking, "string");
    assert.ok(Array.isArray(p.skills));
    assert.ok(Array.isArray(p.context));
  }
});

test("phase policy: config overrides flow through the resolver", () => {
  const get = getterFor({ CCT_CONFIG__PHASES__BUILD__THINKING: "xhigh" });
  assert.equal(resolvePhasePolicy(get, "build").thinking, "xhigh");
  // a phase not overridden keeps its default.
  assert.equal(resolvePhasePolicy(get, "research").thinking, "high");
});

test("phase policy: an absent phase config resolves to inherit, not a throw", () => {
  // getter that knows nothing → all inherit / empty, no error.
  const get = () => undefined;
  const p = resolvePhasePolicy(get, "review");
  assert.equal(p.model, "inherit");
  assert.equal(p.thinking, "inherit");
  assert.deepEqual(p.tools, []);
  assert.equal(p.permissions, "inherit");
});

// ── audit log (C-9, T5.4 — hardening tests) ─────────────────

// Run `fn` with CCT_HOME pointed at `home`, restoring the prior value after.
function withCctHome(home, fn) {
  const prev = process.env.CCT_HOME;
  process.env.CCT_HOME = home;
  try {
    return fn();
  } finally {
    if (prev === undefined) delete process.env.CCT_HOME;
    else process.env.CCT_HOME = prev;
  }
}

const AUDIT_FIELDS = ["ts", "mode", "actor", "decision", "rule", "subject", "origin"];

test("audit: appends one valid JSONL record per call", () => {
  const home = tempTree({});
  withCctHome(home, () => {
    audit({ mode: "headless", actor: "tool_call:bash", decision: "deny", rule: "commands.deny:rm -rf /", subject: "rm -rf /", origin: "permissions" });
    audit({ mode: "tui", actor: "tool_call:write", decision: "deny", rule: "paths.deny:.env", subject: ".env", origin: "protected-path" });
  });
  const lines = fs.readFileSync(auditLogPathFor(home), "utf8").trim().split("\n");
  assert.equal(lines.length, 2, "each call appends exactly one line");
  for (const line of lines) {
    const rec = JSON.parse(line); // must be valid JSON
    assert.deepEqual(Object.keys(rec).sort(), [...AUDIT_FIELDS].sort());
    assert.ok(typeof rec.ts === "string" && rec.ts.length > 0);
  }
});

test("audit: a record carries only the declared fields (no leak surface)", () => {
  const home = tempTree({});
  withCctHome(home, () => {
    audit({ mode: "json", actor: "tool_call:bash", decision: "ask->deny", rule: "commands.ask:git push", subject: "git push origin main", origin: "permissions" });
  });
  const rec = JSON.parse(fs.readFileSync(auditLogPathFor(home), "utf8").trim());
  // Only the seven declared keys — nothing that could smuggle file contents/credentials.
  assert.deepEqual(Object.keys(rec).sort(), [...AUDIT_FIELDS].sort());
});

test("audit: an over-long subject is truncated (bounded record size)", () => {
  const home = tempTree({});
  const huge = "x".repeat(5000);
  withCctHome(home, () => {
    audit({ mode: "headless", actor: "tool_call:bash", decision: "deny", rule: "r", subject: huge, origin: "permissions" });
  });
  const rec = JSON.parse(fs.readFileSync(auditLogPathFor(home), "utf8").trim());
  assert.ok(rec.subject.length <= 400, `subject should be truncated, was ${rec.subject.length}`);
});

test("audit: the decision field records fail-closed and fail-open outcomes faithfully", () => {
  const home = tempTree({});
  withCctHome(home, () => {
    audit({ mode: "headless", actor: "a", decision: "deny", rule: "r", subject: "s", origin: "permissions" });          // fail-closed
    audit({ mode: "headless", actor: "a", decision: "ask->fail", rule: "r", subject: "s", origin: "permissions" });     // fail-closed (fail)
    audit({ mode: "tui", actor: "a", decision: "relaxed-by-override", rule: "r", subject: "s", origin: "security-floor" }); // fail-open
  });
  const decisions = fs.readFileSync(auditLogPathFor(home), "utf8").trim().split("\n").map((l) => JSON.parse(l).decision);
  assert.deepEqual(decisions, ["deny", "ask->fail", "relaxed-by-override"]);
});

test("audit: a write failure is best-effort and never throws (enforcement must not crash)", () => {
  // Point CCT_HOME at a FILE, so mkdir of <home>/pi fails (ENOTDIR).
  const dir = tempTree({ blocker: "i am a file, not a directory" });
  const asFile = path.join(dir, "blocker");
  assert.doesNotThrow(() =>
    withCctHome(asFile, () => {
      audit({ mode: "headless", actor: "a", decision: "deny", rule: "r", subject: "s", origin: "permissions" });
    }),
  );
  // And nothing was written under the blocking file.
  assert.ok(!fs.existsSync(path.join(asFile, "pi", "audit.log")));
});

test("audit: auditLogPath honors CCT_HOME", () => {
  const home = tempTree({});
  const p = withCctHome(home, () => auditLogPath());
  assert.equal(p, path.join(home, "pi", "audit.log"));
});

// auditLogPath() reads process.env at call time; helper mirrors its layout.
function auditLogPathFor(home) {
  return path.join(home, "pi", "audit.log");
}

// ── audit mode label (T5.4 part 2) ──────────────────────────

function withPiMode(value, fn) {
  const prev = process.env.CCT_PI_MODE;
  if (value === undefined) delete process.env.CCT_PI_MODE;
  else process.env.CCT_PI_MODE = value;
  try {
    return fn();
  } finally {
    if (prev === undefined) delete process.env.CCT_PI_MODE;
    else process.env.CCT_PI_MODE = prev;
  }
}

test("audit mode: CCT_PI_MODE is authoritative for the four modes", () => {
  for (const m of ["tui", "print", "json", "rpc"]) {
    withPiMode(m, () => {
      // The label follows CCT_PI_MODE regardless of the interactive flag.
      assert.equal(resolveAuditMode(false), m);
      assert.equal(resolveAuditMode(true), m);
    });
  }
});

test("audit mode: absent/invalid CCT_PI_MODE falls back to the two-value label", () => {
  for (const bad of [undefined, "", "bogus", "TUI", "headless"]) {
    withPiMode(bad, () => {
      assert.equal(resolveAuditMode(true), "tui");
      assert.equal(resolveAuditMode(false), "headless");
    });
  }
});

test("audit mode: the resolved label is what lands in the audit record", () => {
  const home = tempTree({});
  withPiMode("json", () =>
    withCctHome(home, () => {
      audit({ mode: resolveAuditMode(false), actor: "tool_call:bash", decision: "deny", rule: "r", subject: "s", origin: "permissions" });
    }),
  );
  const rec = JSON.parse(fs.readFileSync(auditLogPathFor(home), "utf8").trim());
  assert.equal(rec.mode, "json");
});

// ── decision invariance across modes (T5.4 part 2) ──────────
// The permission ENGINE takes no mode — only an `interactive` flag driving
// ask behavior. So a deny is invariant across all four labels, and an ask
// resolves deterministically in the three headless modes; only interactive
// TUI keeps `ask` open for a ui.confirm prompt. The mode LABEL never changes a
// verdict.

test("decision invariance: deny is identical across all four mode labels", () => {
  // The label does not enter the verdict; the same rule denies regardless.
  for (const m of ["tui", "print", "json", "rpc"]) {
    withPiMode(m, () => {
      assert.equal(checkCommand(RULES, "git push --force").effective, "deny");
      assert.equal(checkPath(RULES, ".env").effective, "deny");
    });
  }
});

test("decision invariance: headless ask resolves deterministically; only TUI stays ask", () => {
  const askCmd = "git push origin main"; // matches commandsAsk
  // Headless (print/json/rpc): interactive=false → ask resolves per policy (deny here).
  const headless = { ...RULES, interactive: false };
  const v = checkCommand(headless, askCmd);
  assert.equal(v.decision, "ask");
  assert.equal(v.effective, "deny"); // deterministic resolution, no prompt
  // Interactive TUI: interactive=true → decision stays ask (a prompt would run).
  const interactive = { ...RULES, interactive: true };
  const vi = checkCommand(interactive, askCmd);
  assert.equal(vi.decision, "ask");
  assert.equal(vi.effective, "allow"); // escalated to the user via ui.confirm
  // The resolution difference is driven by `interactive`, never by the mode label.
});
