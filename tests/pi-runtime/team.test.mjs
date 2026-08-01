// team.test.mjs — T8.1 team controller coordination state (FR-012). Run via
// tests/test-pi-runtime.sh. Pure state machine + file I/O; no spawn.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  TEAM_MESSAGES_REL,
  activateTeam,
  addTeammate,
  approvePlan,
  assignTask,
  claimTask,
  closeTeam,
  completeTask,
  createTeam,
  failTask,
  loadTeamLedger,
  postMessage,
  postTask,
  requestShutdown,
  saveTeamLedger,
} from "../../adapters/pi/runtime/agents/team.ts";

const NOW = "2026-07-31T00:00:00Z";
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "cct-team-"));

// Build a team with a lead + two teammates, plan approved, active.
function activeTeam(taskInputs = []) {
  let l = createTeam("t1", "lead", NOW).ledger;
  l = addTeammate(l, "alice", NOW).ledger;
  l = addTeammate(l, "bob", NOW).ledger;
  for (const t of taskInputs) l = postTask(l, t).ledger;
  l = approvePlan(l, "lead", NOW).ledger;
  l = activateTeam(l).ledger;
  return l;
}

// ── identities ───────────────────────────────────────────────────────────────

test("createTeam seeds exactly one lead; addTeammate adds peers", () => {
  const l = createTeam("t1", "lead", NOW).ledger;
  assert.equal(l.members.length, 1);
  assert.equal(l.members[0].role, "lead");
  const r = addTeammate(l, "alice", NOW);
  assert.equal(r.ok, true);
  assert.equal(r.ledger.members.find((m) => m.memberId === "alice").role, "teammate");
});

test("createTeam / addTeammate reject bad ids and duplicates", () => {
  assert.equal(createTeam("Bad Id", "lead", NOW).ok, false);
  assert.equal(createTeam("t1", "Bad Lead", NOW).ok, false);
  const l = createTeam("t1", "lead", NOW).ledger;
  assert.equal(addTeammate(l, "lead", NOW).ok, false, "duplicate id refused");
  assert.equal(addTeammate(l, "NOPE", NOW).ok, false, "non-kebab refused");
});

// ── plan approval gates BOTH activation and claims ───────────────────────────

test("activateTeam is blocked until the lead approves (when required)", () => {
  let l = createTeam("t1", "lead", NOW).ledger;
  l = addTeammate(l, "alice", NOW).ledger;
  assert.equal(activateTeam(l).ok, false, "cannot activate before approval");
  l = approvePlan(l, "lead", NOW).ledger;
  const r = activateTeam(l);
  assert.equal(r.ok, true);
  assert.equal(r.ledger.status, "active");
});

test("only the lead may approve the plan", () => {
  let l = createTeam("t1", "lead", NOW).ledger;
  l = addTeammate(l, "alice", NOW).ledger;
  assert.equal(approvePlan(l, "alice", NOW).ok, false);
  assert.equal(approvePlan(l, "lead", NOW).ok, true);
});

test("claimTask is refused before approval even if status were forced", () => {
  // A team with required approval, not approved: claim must refuse on both the
  // status gate and (independently) the approval gate.
  let l = createTeam("t1", "lead", NOW).ledger;
  l = addTeammate(l, "alice", NOW).ledger;
  l = postTask(l, { taskId: "task-a", title: "A" }).ledger;
  // force status active WITHOUT approval to prove the independent approval gate
  l = { ...l, status: "active" };
  const r = claimTask(l, "task-a", "alice", NOW);
  assert.equal(r.ok, false);
  assert.match(r.error, /approval/);
});

// ── claiming: fail-closed, single claimant ───────────────────────────────────

test("claimTask: open + unassigned + active member -> claimed by exactly one", () => {
  const l = activeTeam([{ taskId: "task-a", title: "A" }]);
  const r = claimTask(l, "task-a", "alice", NOW);
  assert.equal(r.ok, true);
  const t = r.ledger.tasks[0];
  assert.equal(t.claimStatus, "claimed");
  assert.equal(t.claimedBy, "alice");
});

test("claimTask: a second claim of a claimed task is refused (single claimant)", () => {
  let l = activeTeam([{ taskId: "task-a", title: "A" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  const r = claimTask(l, "task-a", "bob", NOW);
  assert.equal(r.ok, false);
  assert.match(r.error, /already claimed/);
});

test("claimTask: a task assigned to another member cannot be claimed", () => {
  let l = activeTeam([{ taskId: "task-a", title: "A" }]);
  l = assignTask(l, "task-a", "alice").ledger;
  assert.equal(claimTask(l, "task-a", "bob", NOW).ok, false, "cross-assignment claim refused");
  assert.equal(claimTask(l, "task-a", "alice", NOW).ok, true, "assignee may claim");
});

test("claimTask: a non-member cannot claim", () => {
  const l = activeTeam([{ taskId: "task-a", title: "A" }]);
  assert.equal(claimTask(l, "task-a", "eve", NOW).ok, false);
});

test("claimTask: refused when the team is not active", () => {
  let l = createTeam("t1", "lead", NOW).ledger;
  l = addTeammate(l, "alice", NOW).ledger;
  l = postTask(l, { taskId: "task-a", title: "A" }).ledger;
  l = approvePlan(l, "lead", NOW).ledger; // approved but still "forming"
  const r = claimTask(l, "task-a", "alice", NOW);
  assert.equal(r.ok, false);
  assert.match(r.error, /not active/);
});

test("claimTask: bounded concurrency cap is enforced", () => {
  const l = activeTeam([
    { taskId: "task-a", title: "A" },
    { taskId: "task-b", title: "B" },
    { taskId: "task-c", title: "C" },
  ]);
  let cur = l;
  cur = claimTask(cur, "task-a", "alice", NOW, { maxConcurrency: 1 }).ledger;
  const r = claimTask(cur, "task-b", "bob", NOW, { maxConcurrency: 1 });
  assert.equal(r.ok, false);
  assert.match(r.error, /concurrency cap/);
});

test("complete/fail only by the claimant, only from claimed", () => {
  let l = activeTeam([{ taskId: "task-a", title: "A" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  assert.equal(completeTask(l, "task-a", "bob").ok, false, "non-claimant cannot complete");
  const done = completeTask(l, "task-a", "alice");
  assert.equal(done.ok, true);
  assert.equal(done.ledger.tasks[0].claimStatus, "done");
  // a done task cannot be failed
  assert.equal(failTask(done.ledger, "task-a", "alice").ok, false);
});

// ── controlled shutdown ──────────────────────────────────────────────────────

test("requestShutdown records who/why; closeTeam blocked while a task is claimed", () => {
  let l = activeTeam([{ taskId: "task-a", title: "A" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  const sd = requestShutdown(l, "lead", "wrapping up", NOW);
  assert.equal(sd.ok, true);
  assert.equal(sd.ledger.status, "shutting-down");
  assert.equal(sd.ledger.shutdown.requestedBy, "lead");
  assert.match(sd.ledger.shutdown.reason, /wrapping up/);
  // still claimed -> cannot close
  assert.equal(closeTeam(sd.ledger).ok, false);
  const resolved = completeTask(sd.ledger, "task-a", "alice").ledger;
  const closed = closeTeam(resolved);
  assert.equal(closed.ok, true);
  assert.equal(closed.ledger.status, "closed");
});

// ── messaging (redacted append) ──────────────────────────────────────────────

test("postMessage appends redacted JSONL", () => {
  const root = tmp();
  postMessage(root, "alice", "bob", "status ok", NOW);
  postMessage(root, "bob", "all", "my token is sk-ABCDEFGHIJKLMNOP1234", NOW);
  const lines = fs
    .readFileSync(path.join(root, TEAM_MESSAGES_REL), "utf8")
    .trim()
    .split("\n")
    .map((l) => JSON.parse(l));
  assert.equal(lines.length, 2);
  assert.equal(lines[0].body, "status ok");
  assert.equal(lines[1].body, "[REDACTED]", "a secret in a message body is redacted");
  assert.equal(lines[1].to, "all");
});

// ── ledger I/O (tamper-safe) ─────────────────────────────────────────────────

test("saveTeamLedger/loadTeamLedger round-trips", () => {
  const root = tmp();
  const l = activeTeam([{ taskId: "task-a", title: "A" }]);
  saveTeamLedger(root, l);
  const back = loadTeamLedger(root);
  assert.equal(back.teamId, "t1");
  assert.equal(back.status, "active");
  assert.equal(back.members.length, 3);
  assert.equal(back.tasks[0].taskId, "task-a");
});

test("loadTeamLedger drops malformed members/tasks and clamps enums", () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, ".cct"), { recursive: true });
  fs.writeFileSync(
    path.join(root, ".cct", "team.json"),
    JSON.stringify({
      version: 99,
      teamId: "t1",
      status: "bogus",
      members: [
        { memberId: "lead", role: "lead", status: "active" },
        { memberId: "Bad Id", role: "teammate" }, // dropped
      ],
      tasks: [
        { taskId: "task-a", claimStatus: "weird" }, // enum clamped to open
        { title: "no id" }, // dropped
      ],
      planApproval: { required: true, approved: true },
    }),
  );
  const l = loadTeamLedger(root);
  assert.equal(l.version, 1);
  assert.equal(l.status, "forming"); // clamped
  assert.equal(l.members.length, 1);
  assert.equal(l.tasks.length, 1);
  assert.equal(l.tasks[0].claimStatus, "open"); // clamped
});

test("loadTeamLedger on missing/corrupt returns null", () => {
  assert.equal(loadTeamLedger(tmp()), null);
});
