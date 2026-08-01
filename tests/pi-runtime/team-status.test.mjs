// team-status.test.mjs — T8.2 team status view + synthesis + failure recovery
// (FR-012/FR-020). Run via tests/test-pi-runtime.sh. Read-model + pure
// aggregation + local-state recovery over the T8.1 ledger; no spawn.

import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  addTeammate,
  approvePlan,
  assignTask,
  claimTask,
  completeTask,
  createTeam,
  failTask,
  postTask,
  activateTeam,
  TEAM_LEDGER_REL,
} from "../../adapters/pi/runtime/agents/team.ts";
import {
  markMemberLeft,
  renderTeamStatus,
  reopenOrphanedClaims,
  synthesizeTeam,
  teamStatus,
} from "../../adapters/pi/runtime/agents/team-status.ts";

const NOW = "2026-08-01T00:00:00Z";

// A lead + alice + bob, plan approved, active, with the given tasks posted.
function team(taskInputs = []) {
  let l = createTeam("t1", "lead", NOW).ledger;
  l = addTeammate(l, "alice", NOW).ledger;
  l = addTeammate(l, "bob", NOW).ledger;
  for (const t of taskInputs) l = postTask(l, t).ledger;
  l = approvePlan(l, "lead", NOW).ledger;
  l = activateTeam(l).ledger;
  return l;
}

// ── status view ──────────────────────────────────────────────────────────────

test("teamStatus snapshots members/roles/approval/task-counts/workerCount", () => {
  let l = team([
    { taskId: "task-a", title: "A", workerId: "w1" },
    { taskId: "task-b", title: "B", workerId: "w2" },
    { taskId: "task-c", title: "C" }, // no worker link
  ]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  l = completeTask(l, "task-a", "alice").ledger;
  const v = teamStatus(l);
  assert.equal(v.teamId, "t1");
  assert.equal(v.status, "active");
  assert.equal(v.members.lead, "lead");
  assert.equal(v.members.total, 3);
  assert.equal(v.members.active, 3);
  assert.equal(v.planApproved, true);
  assert.equal(v.tasks.done, 1);
  assert.equal(v.tasks.open, 2);
  assert.equal(v.workerCount, 2, "distinct non-null workerId links");
});

test("renderTeamStatus: text + JSON", () => {
  const v = teamStatus(team([{ taskId: "task-a", title: "A" }]));
  const text = renderTeamStatus(v, false);
  assert.match(text, /=== team t1 ===/);
  assert.match(text, /lead:\s+lead/);
  assert.match(text, /open 1/);
  const parsed = JSON.parse(renderTeamStatus(v, true));
  assert.equal(parsed.teamId, "t1");
});

// ── synthesis (fail-closed) ──────────────────────────────────────────────────

test("synthesizeTeam: empty team -> empty", () => {
  assert.equal(synthesizeTeam(team([])).verdict, "empty");
});

test("synthesizeTeam: all done -> complete", () => {
  let l = team([{ taskId: "task-a", title: "A" }, { taskId: "task-b", title: "B" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  l = completeTask(l, "task-a", "alice").ledger;
  l = claimTask(l, "task-b", "bob", NOW).ledger;
  l = completeTask(l, "task-b", "bob").ledger;
  const s = synthesizeTeam(l);
  assert.equal(s.verdict, "complete");
  assert.equal(s.done, 2);
});

test("synthesizeTeam: all terminal, none done -> failed", () => {
  let l = team([{ taskId: "task-a", title: "A" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  l = failTask(l, "task-a", "alice").ledger;
  const s = synthesizeTeam(l);
  assert.equal(s.verdict, "failed");
  assert.deepEqual(s.failedTasks, ["task-a"]);
});

test("synthesizeTeam: an in-flight or mixed team is partial, never complete", () => {
  let l = team([{ taskId: "task-a", title: "A" }, { taskId: "task-b", title: "B" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  l = completeTask(l, "task-a", "alice").ledger;
  // task-b still open -> partial (fail-closed: not complete)
  assert.equal(synthesizeTeam(l).verdict, "partial");
  l = claimTask(l, "task-b", "bob", NOW).ledger; // now claimed (in flight)
  assert.equal(synthesizeTeam(l).verdict, "partial");
});

// ── failure recovery (reopen only) ───────────────────────────────────────────

test("markMemberLeft reopens the member's claimed tasks for reclaim", () => {
  let l = team([{ taskId: "task-a", title: "A" }, { taskId: "task-b", title: "B" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  l = claimTask(l, "task-b", "bob", NOW).ledger;
  const r = markMemberLeft(l, "alice", NOW);
  assert.equal(r.ok, true);
  assert.equal(r.ledger.members.find((m) => m.memberId === "alice").status, "left");
  const a = r.ledger.tasks.find((t) => t.taskId === "task-a");
  assert.equal(a.claimStatus, "open", "alice's claim reopened");
  assert.equal(a.claimedBy, null);
  // bob's claim is untouched
  assert.equal(r.ledger.tasks.find((t) => t.taskId === "task-b").claimStatus, "claimed");
  // a peer can now reclaim task-a
  assert.equal(claimTask(r.ledger, "task-a", "bob", NOW, { maxConcurrency: 4 }).ok, true);
});

test("markMemberLeft never auto-succeeds/fails; unknown member refused", () => {
  let l = team([{ taskId: "task-a", title: "A" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  l = completeTask(l, "task-a", "alice").ledger; // already done
  const r = markMemberLeft(l, "alice", NOW);
  assert.equal(r.ledger.tasks[0].claimStatus, "done", "a done task is NOT reopened");
  assert.equal(markMemberLeft(l, "ghost", NOW).ok, false);
});

test("reopenOrphanedClaims sweeps claims held by left/inactive members", () => {
  let l = team([{ taskId: "task-a", title: "A" }]);
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  // simulate alice already flipped to left without the reopen (e.g. external edit)
  l = { ...l, members: l.members.map((m) => (m.memberId === "alice" ? { ...m, status: "left" } : m)) };
  const r = reopenOrphanedClaims(l);
  assert.equal(r.ok, true);
  assert.equal(r.ledger.tasks[0].claimStatus, "open");
  assert.equal(r.ledger.tasks[0].claimedBy, null);
});

test("markMemberLeft clears assignedTo of the departed member so a peer CAN reclaim", () => {
  let l = team([{ taskId: "task-a", title: "A" }]);
  l = assignTask(l, "task-a", "alice").ledger;
  l = claimTask(l, "task-a", "alice", NOW).ledger; // assigned to + claimed by alice
  const r = markMemberLeft(l, "alice", NOW);
  assert.equal(r.ledger.tasks[0].claimStatus, "open");
  assert.equal(r.ledger.tasks[0].assignedTo, null, "assignment to the departed member is cleared");
  // a peer can now actually reclaim it (would fail if still assigned to alice)
  assert.equal(claimTask(r.ledger, "task-a", "bob", NOW).ok, true);
});

test("reopenOrphanedClaims clears assignedTo of an inactive member so a peer CAN reclaim", () => {
  let l = team([{ taskId: "task-a", title: "A" }]);
  l = assignTask(l, "task-a", "alice").ledger;
  l = claimTask(l, "task-a", "alice", NOW).ledger;
  l = { ...l, members: l.members.map((m) => (m.memberId === "alice" ? { ...m, status: "left" } : m)) };
  const r = reopenOrphanedClaims(l);
  assert.equal(r.ledger.tasks[0].claimStatus, "open");
  assert.equal(r.ledger.tasks[0].assignedTo, null);
  assert.equal(claimTask(r.ledger, "task-a", "bob", NOW).ok, true);
});

test("recovery leaves a task assigned to a STILL-ACTIVE member intact", () => {
  let l = team([{ taskId: "task-a", title: "A" }]);
  l = assignTask(l, "task-a", "alice").ledger; // assigned to alice (active), unclaimed
  // bob leaves — must not disturb alice's assignment
  const r = markMemberLeft(l, "bob", NOW);
  assert.equal(r.ledger.tasks[0].assignedTo, "alice", "an active member's assignment is preserved");
});

// ── distinct-from-subagents (an explicit T8.2 deliverable) ───────────────────

test("DISTINCT: team ledger file differs from the worktree ledger file", async () => {
  const wt = await import("../../adapters/pi/runtime/agents/worktree.ts");
  assert.notEqual(TEAM_LEDGER_REL, wt.WORKTREE_LEDGER_REL, "separate state files");
});

test("DISTINCT: a team task advances by a PEER CLAIM with no spawn / no worker", () => {
  // A task can be resolved with workerId:null — no child session, no worktree.
  let l = team([{ taskId: "task-a", title: "A" }]);
  assert.equal(l.tasks[0].workerId, null, "workerId is an optional link, not required");
  l = claimTask(l, "task-a", "alice", NOW).ledger; // a peer claims (not a parent spawning)
  l = completeTask(l, "task-a", "alice").ledger;
  assert.equal(l.tasks[0].claimStatus, "done");
});

test("DISTINCT: teams are peers (one lead + teammates), not parent->child", () => {
  const l = team([]);
  assert.equal(l.members.filter((m) => m.role === "lead").length, 1);
  assert.equal(l.members.filter((m) => m.role === "teammate").length, 2);
  // assignment is lead intent over peers, not a spawn edge
  const a = assignTask(team([{ taskId: "task-a", title: "A" }]), "task-a", "alice");
  assert.equal(a.ok, true);
});

test("team-status.ts imports no spawn/child-session surface (state-only)", () => {
  const HERE = path.dirname(fileURLToPath(import.meta.url));
  const src = fs.readFileSync(
    path.resolve(HERE, "../../adapters/pi/runtime/agents/team-status.ts"),
    "utf8",
  );
  assert.doesNotMatch(src, /child-session|child_process|spawn/, "no execution surface in the read-model layer");
});
