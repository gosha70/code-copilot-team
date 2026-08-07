// team-commands.test.mjs — Slice A of #174 (issue #185). Wiring of the built
// team.ts (T8.1) + team-status.ts (T8.2) into /cct:team, against REAL throwaway
// git repos. Covers the four PR #184 review rounds: fail-closed canonical root,
// declared-identity attribution + team binding, per-mutation live authz, safe
// create, and the coordination contract. Run via tests/test-pi-runtime.sh.

import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  runTeamCommand,
  readReport,
  teamAdvisory,
  TEAM_AUDIT,
} from "../../adapters/pi/runtime/agents/team-commands.ts";
import { loadTeamLedger } from "../../adapters/pi/runtime/agents/team.ts";
import { auditLogPath } from "../../adapters/pi/runtime/policy/audit.ts";

const HAS_GIT = spawnSync("git", ["--version"], { encoding: "utf8" }).status === 0;
const NOW = "2026-08-06T00:00:00Z";

function initRepo() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cct-team-repo-"));
  const g = (a) => spawnSync("git", ["-C", dir, ...a], { encoding: "utf8" });
  g(["init", "-q", "-b", "master"]);
  g(["config", "user.email", "t@example.com"]);
  g(["config", "user.name", "T"]);
  fs.writeFileSync(path.join(dir, "README.md"), "seed\n");
  g(["add", "-A"]);
  g(["commit", "-q", "-m", "seed"]);
  return fs.realpathSync(dir);
}

function ctx(repo, teamId, memberId, o = {}) {
  return {
    cwd: o.cwd ?? repo,
    env: teamId ? { CCT_TEAM_ID: teamId, CCT_TEAM_MEMBER_ID: memberId } : {},
    mode: "print",
    teamsEnabled: o.enabled ?? true,
    maxConcurrency: o.maxConcurrency ?? 4,
    now: o.now ?? NOW,
    deps: o.deps,
  };
}
const run = (c, str) => runTeamCommand(c, str.split(/\s+/).filter(Boolean));
const ledgerOf = (repo) => loadTeamLedger(repo);
const teamFile = (repo) => path.join(repo, ".cct", "team.json");

function withAuditHome(fn) {
  const prev = process.env.CCT_HOME;
  process.env.CCT_HOME = fs.mkdtempSync(path.join(os.tmpdir(), "cct-team-home-"));
  try {
    return fn(() => {
      const f = auditLogPath();
      return fs.existsSync(f)
        ? fs.readFileSync(f, "utf8").trim().split("\n").filter(Boolean).map((l) => JSON.parse(l))
        : [];
    });
  } finally {
    if (prev === undefined) delete process.env.CCT_HOME;
    else process.env.CCT_HOME = prev;
  }
}

// ── gating ───────────────────────────────────────────────────────────────────

test("gated: disabled ⇒ opt-in message, no ledger written", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const out = run(ctx(repo, "t", "lead", { enabled: false }), "create t");
  assert.match(out, /opt-in|agents\.teams_enabled/);
  assert.ok(!fs.existsSync(teamFile(repo)), "no team.json when disabled");
});

// ── full lifecycle ───────────────────────────────────────────────────────────

test("lifecycle: create → join → task → approve → activate → claim → complete → close", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  assert.match(run(lead, "create alpha"), /created team 'alpha'/);
  assert.match(run(lead, "join dev1"), /ok/);
  assert.match(run(lead, "task t1 build the thing"), /ok/);
  assert.match(run(lead, "approve"), /ok/);
  assert.match(run(lead, "activate"), /ok/);
  const dev = ctx(repo, "alpha", "dev1");
  assert.match(run(dev, "claim t1"), /ok/);
  assert.match(run(dev, "complete t1"), /ok/);
  const led = ledgerOf(repo);
  assert.equal(led.tasks.find((t) => t.taskId === "t1").claimStatus, "done");
  // close is lead-only and refused while claimed; here t1 is done, so ok.
  assert.match(run(lead, "close"), /ok/);
  assert.equal(ledgerOf(repo).status, "closed");
});

// ── safe create ──────────────────────────────────────────────────────────────

test("create: refuses duplicate + corrupt, never overwrites; teamId must match identity", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  const before = fs.readFileSync(teamFile(repo));
  assert.match(run(lead, "create alpha"), /already exists|not overwriting/);
  assert.ok(fs.readFileSync(teamFile(repo)).equals(before), "duplicate create left file unchanged");

  // corrupt the ledger, then create must refuse and NOT overwrite.
  fs.writeFileSync(teamFile(repo), "}{ not json");
  const corrupt = fs.readFileSync(teamFile(repo));
  assert.match(run(ctx(repo, "beta", "lead1"), "create beta"), /invalid|not overwriting/);
  assert.ok(fs.readFileSync(teamFile(repo)).equals(corrupt), "corrupt ledger not overwritten");

  // create teamId ≠ identity.teamId
  const repo2 = initRepo();
  assert.match(run(ctx(repo2, "alpha", "lead1"), "create beta"), /must match CCT_TEAM_ID/);
  assert.ok(!fs.existsSync(teamFile(repo2)), "mismatched create wrote nothing");
});

test("--no-plan-approval sets planRequired false; default requires approval", { skip: !HAS_GIT }, () => {
  const a = initRepo();
  run(ctx(a, "alpha", "l"), "create alpha --no-plan-approval");
  assert.equal(ledgerOf(a).planApproval.required, false);
  const b = initRepo();
  run(ctx(b, "beta", "l"), "create beta");
  assert.equal(ledgerOf(b).planApproval.required, true);
});

test("task: --assign/--worker values never leak into the persisted title", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  run(lead, "join dev1");
  // flags after the title
  assert.match(run(lead, "task t1 build the thing --assign dev1 --worker w9"), /ok/);
  // flags interleaved before title words
  assert.match(run(lead, "task t2 --assign dev1 ship it"), /ok/);
  const led = ledgerOf(repo);
  const t1 = led.tasks.find((t) => t.taskId === "t1");
  assert.equal(t1.title, "build the thing", "flag values excluded from the title");
  assert.equal(t1.assignedTo, "dev1");
  assert.equal(t1.workerId, "w9");
  const t2 = led.tasks.find((t) => t.taskId === "t2");
  assert.equal(t2.title, "ship it");
  assert.equal(t2.assignedTo, "dev1");
});

// ── declared identity + team binding ─────────────────────────────────────────

test("identity: missing declared ids ⇒ refused; unknown member ⇒ refused", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  run(ctx(repo, "alpha", "lead1"), "create alpha");
  assert.match(run(ctx(repo, null, null), "task t1 x"), /both required|CCT_TEAM_ID/);
  assert.match(run(ctx(repo, "alpha", "ghost"), "task t1 x"), /not an active member/);
});

test("team binding: declared team A + create B ⇒ refused; A against ledger B ⇒ all mutations refused", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  // declared A, create B → refused (teamId arg must match identity)
  assert.match(run(ctx(repo, "alpha", "lead1"), "create beta"), /must match/);
  assert.ok(!fs.existsSync(teamFile(repo)));
  // ledger is 'beta'; a session declaring teamId 'alpha' is refused on every mutation
  run(ctx(repo, "beta", "lead1"), "create beta");
  const wrongTeam = ctx(repo, "alpha", "lead1");
  for (const cmd of ["task t9 x", "join x", "approve", "leave"]) {
    assert.match(run(wrongTeam, cmd), /does not match this team/, cmd);
  }
});

// ── join/task authz (any active member; not unidentified) ────────────────────

test("join/task: unidentified/inactive refused; an active non-lead member can join & task", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  run(lead, "join dev1");
  const dev = ctx(repo, "alpha", "dev1"); // active non-lead
  assert.match(run(dev, "join dev2"), /ok/, "active member may add a teammate");
  assert.match(run(dev, "task t1 do it"), /ok/, "active member may post a task");
  // unknown identity cannot join/task
  assert.match(run(ctx(repo, "alpha", "nobody"), "task t2 x"), /not an active member/);
});

// ── lead-only + live authz (re-validated, not cached) ────────────────────────

test("lead-only: a non-lead active member is refused on admin commands", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  run(lead, "join dev1");
  run(lead, "task t1 x");
  const dev = ctx(repo, "alpha", "dev1");
  for (const cmd of ["assign t1 dev1", "approve", "activate", "close", "recover"]) {
    assert.match(run(dev, cmd), /lead-only/, cmd);
  }
});

test("live authz: a member that becomes `left` is refused next actor command (not cached)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  run(lead, "join dev1");
  run(lead, "task t1 x");
  run(lead, "approve");
  run(lead, "activate");
  const dev = ctx(repo, "alpha", "dev1");
  assert.match(run(dev, "leave"), /ok/);
  // dev is now `left` in the ledger → its next actor command is refused live.
  assert.match(run(dev, "claim t1"), /not an active member/);
});

test("live authz (lead): an externally-left lead loses authority immediately", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  // External fixture: the normal lifecycle can't make the sole lead `left`, so
  // modify the ledger directly, then a lead-only command must be refused.
  const l = ledgerOf(repo);
  l.members = l.members.map((m) => (m.memberId === "lead1" ? { ...m, status: "left" } : m));
  fs.writeFileSync(teamFile(repo), JSON.stringify(l, null, 2) + "\n");
  assert.match(run(lead, "approve"), /not an active member/);
});

test("sole active lead cannot `leave` a non-closed team", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  assert.match(run(lead, "leave"), /lead cannot leave/);
  assert.equal(ledgerOf(repo).members.find((m) => m.memberId === "lead1").status, "active");
});

// ── coordination contract ────────────────────────────────────────────────────

test("contract: double-claim refused; close refused while a task is claimed", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  run(lead, "join dev1");
  run(lead, "task t1 x");
  run(lead, "approve");
  run(lead, "activate");
  run(ctx(repo, "alpha", "dev1"), "claim t1");
  // lead tries to claim the same task → refused (already claimed)
  assert.match(run(lead, "claim t1"), /refused/);
  // close while t1 is still claimed → refused
  assert.match(run(lead, "close"), /refused/);
  assert.notEqual(ledgerOf(repo).status, "closed");
});

// ── message ──────────────────────────────────────────────────────────────────

test("message: validates recipient + team-open; appends to team-messages.jsonl (no team.json rewrite)", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  run(lead, "join dev1");
  assert.match(run(lead, "message nobody hi"), /no member 'nobody'/);
  const before = fs.readFileSync(teamFile(repo));
  assert.match(run(lead, "message dev1 hello there"), /message sent to dev1/);
  const msgs = path.join(repo, ".cct", "team-messages.jsonl");
  assert.ok(fs.existsSync(msgs), "message appended");
  assert.ok(fs.readFileSync(teamFile(repo)).equals(before), "team.json not rewritten by message");
});

// ── fail-closed canonical root ───────────────────────────────────────────────

test("fail-closed root: git-common-dir failure ⇒ mutation refused + audit, nothing created", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const deps = { gitCommonDir: () => null }; // force primaryRepoRoot => null
  withAuditHome((read) => {
    const out = run(ctx(repo, "alpha", "lead1", { deps }), "create alpha");
    assert.match(out, /canonical repo root|no canonical/);
    assert.equal(read().at(-1).rule, TEAM_AUDIT.rootUnresolved);
  });
  assert.ok(!fs.existsSync(teamFile(repo)), "nothing created on unresolved root");
});

// ── canonical ledger across linked worktrees ─────────────────────────────────

test("canonical ledger: a command from a LINKED worktree targets the PRIMARY team ledger", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  run(lead, "join dev1");
  run(lead, "task t1 x");
  run(lead, "approve");
  run(lead, "activate");
  // add a real linked worktree and run a claim from inside it
  const wt = path.join(path.dirname(repo), path.basename(repo) + "-wt");
  spawnSync("git", ["-C", repo, "worktree", "add", "-q", wt, "-b", "feature/wt"], { encoding: "utf8" });
  const fromWorktree = ctx(repo, "alpha", "dev1", { cwd: fs.realpathSync(wt) });
  assert.match(run(fromWorktree, "claim t1"), /ok/, "claim from the linked worktree");
  // the claim landed in the PRIMARY ledger, and NO split team.json exists in the worktree
  assert.equal(ledgerOf(repo).tasks.find((t) => t.taskId === "t1").claimStatus, "claimed");
  assert.ok(!fs.existsSync(path.join(fs.realpathSync(wt), ".cct", "team.json")), "no split ledger in the worktree");
});

// ── read reports + advisory ──────────────────────────────────────────────────

test("status/synthesize read a valid ledger; advisory summarizes; missing ⇒ 'no team'", { skip: !HAS_GIT }, () => {
  const repo = initRepo();
  assert.match(readReport({ cwd: repo }, false, false).out, /no team/);
  const lead = ctx(repo, "alpha", "lead1");
  run(lead, "create alpha");
  run(lead, "task t1 x");
  const status = readReport({ cwd: repo }, false, true);
  assert.equal(JSON.parse(status.out).teamId, "alpha");
  assert.match(readReport({ cwd: repo }, true, false).out, /verdict:/);
  withAuditHome(() => {
    const adv = teamAdvisory(repo, { enabled: true, mode: "print" });
    assert.match(adv, /team 'alpha'/);
    assert.equal(teamAdvisory(repo, { enabled: false, mode: "print" }), null, "silent when disabled");
  });
});

// ── audit + no-invented-event wiring ─────────────────────────────────────────

test("wiring: index.ts registers cct:team on session_start only (no invented event)", () => {
  const idx = fs.readFileSync(new URL("../../adapters/pi/runtime/index.ts", import.meta.url), "utf8");
  assert.match(idx, /registerCommand\?\.\("cct:team"/, "cct:team registered");
  assert.match(idx, /runTeamCommand\(/, "team command wired");
  assert.doesNotMatch(idx, /pi\.on\?\(\s*["'](?!session_start)/i, "no non-session_start pi.on");
});
