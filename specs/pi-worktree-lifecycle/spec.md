# Spec: Pi worktree lifecycle wiring

Source: GitHub issue **#172**. Wires the **already-built** T7.3 worktree manager
(`adapters/pi/runtime/agents/worktree.ts`, merged in #154/#155) into Pi's
*verifiable* session lifecycle. This spec adds **no** re-implementation of the
manager or its safety model — only the missing live wiring.

## Context (do NOT rebuild)

The manager already ships: `createWorker` / `cleanupWorker` / `reconcile` /
`pruneWorktrees` / `setMergeStatus`, the `.cct/worktrees.json` ledger, and the
full enforced safety model (isolation off a base branch, refuse master/main,
ownership-conflict detection, dirty-refuse, foreign-worktree protection, stale
reconcile, no force/reset/`branch -D`, symlink-escape containment), with tests
against a real temp repo (`worktree-git.test.mjs`, `worktree-planners.test.mjs`).
The one gap: it is a library with **no live wiring into a running Pi session.**

## User scenarios

- **US1** — As a driver/team-controller orchestrating parallel workers, when a
  *worker* Pi session starts it is automatically given an isolated git worktree +
  ledger record; the user's **primary** worktree is never touched.
- **US2** — As an operator, I can explicitly tear down a finished worker's
  worktree with a `/cct:worktree cleanup` command; a **dirty or unmerged**
  worktree is refused unless I audibly `--force` it.
- **US3** — As an operator, on session start (and on demand) stale ledger records
  are marked and foreign worktrees are surfaced — but **live work is never
  auto-removed.**

## Requirements

- **FR-1 — Create on worker start.** On Pi's `session_start` event, IF the session
  is a *worker* session (FR-2), call `createWorker` to provision the worktree +
  ledger record. A non-worker (primary) session provisions nothing.
- **FR-2 — Explicit worker signal.** Worker sessions are identified by an explicit
  env contract set by the spawning driver/team controller — at minimum
  `CCT_WORKER_ID`, plus `CCT_WORKER_BRANCH`, and optionally `CCT_WORKER_BASE`,
  `CCT_WORKER_TASKS`, `CCT_WORKER_AREAS`. `session_start` reads it and builds the
  `CreateRequest`; **absent `CCT_WORKER_ID` ⇒ no-op** (the primary session is
  never converted to a worktree). No new event is invented — only `session_start`.
- **FR-3 — Explicit cleanup, NOT a session-end event.** Pi exposes **no**
  session-end / `session.deleted` event (`Stop`/turn-end is `unsupported`). Cleanup
  is driven explicitly by a registered command `/cct:worktree cleanup <workerId>
  [--force]` that calls `cleanupWorker`, honoring its existing preconditions (clean
  **and** merged/abandoned; `force` audited). Also register `/cct:worktree list`
  (ledger + live/foreign) and `/cct:worktree reconcile`.
- **FR-4 — Reconcile pass.** On `session_start` (and via `/cct:worktree
  reconcile`) run `reconcile` + `pruneWorktrees` to mark vanished records `stale`
  and surface foreign worktrees. **Report only — never auto-remove live work.**
- **FR-5 — Audit.** Every wired action (create / cleanup / reconcile) is
  audit-logged with the existing C-9 discipline (decision, rule, subject).
- **FR-6 — Honesty.** Diagnostics/docs state that cleanup is **explicit-only**
  because Pi exposes no session-end event — degraded by construction, not a bug.

## Constraints

- No re-implementation of `worktree.ts` or any of its safety guarantees.
- Wiring uses **only** `session_start` and `registerCommand` — no invented event.
- Runtime is TypeScript strict; the launcher/env stays bash 3.2 compatible.
- The "**never auto-remove live work**" guarantee is preserved end-to-end.
- Worker signal + env are UNTRUSTED input: `workerId`/`branch`/paths are validated
  by the existing `validateCreateRequest` (managed-root containment, protected
  branch refusal, overlap detection) before any git side effect.

## Out of scope (separate issues, per #172)

- **Write-time path/ownership enforcement** (pinning every tool write inside the
  worktree) — permission-layer work, deferred by the T7.3 design.
- **Auto-remove-on-crash** — conflicts with the "never auto-remove live work"
  guarantee; needs its own design decision before it can be accepted.

## Acceptance criteria (from #172)

1. Starting a Pi **worker** session provisions an isolated worktree + ledger record
   via `createWorker`, with **no change to the user's primary worktree**.
2. An explicit teardown command cleanly removes a **merged/abandoned** worker
   worktree via `cleanupWorker`; **dirty or unmerged** worktrees are refused unless
   explicitly (and audibly) `--force`d.
3. **No new event source** is invented: wiring uses only
   `session_start` / `registerCommand`.
4. `reconcile` correctly marks **stale** records and reports **foreign** worktrees.
