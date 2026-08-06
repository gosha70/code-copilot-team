---
spec_mode: full
feature_id: pi-worktree-lifecycle
risk_category: security
justification: |
  Wires the T7.3 worktree manager into the live Pi session lifecycle. It touches
  session_start (auto-provisioning) and an explicit teardown command that runs
  git worktree operations. Safety-sensitive: it must never convert the primary
  worktree, never auto-remove live work, and validate untrusted worker-signal env
  before any git side effect. The manager + its safety model already exist and are
  tested; this is wiring only.
status: draft
date: 2026-08-06
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/172
  origin_claim: |
    The T7.3 worktree manager (worktree.ts, .cct/worktrees.json, safety model,
    tests) is already merged (#154/#155). The only gap is live wiring into Pi's
    session lifecycle: create-on-worker-start via session_start, an explicit
    cleanup command (no session-end event exists), and a reconcile pass. Write-time
    enforcement and auto-remove-on-crash are explicitly out of scope.
---

# Plan: Pi worktree lifecycle wiring

## Existing facts (verified)

- `adapters/pi/runtime/agents/worktree.ts` exports the complete library:
  `createWorker(repoRoot, ledger, req: CreateRequest, nowIso)`,
  `cleanupWorker(repoRoot, ledger, workerId, {force?})`,
  `reconcile(ledger, liveWorktreePaths)`, `pruneWorktrees(repoRoot)`,
  `setMergeStatus`, `loadLedger`/`saveLedger`, `validateCreateRequest`
  (managed-root containment + protected-branch refusal + overlap),
  `detectOwnershipConflicts`, `cleanupEligibility`, `listWorktrees`,
  `isWorktreeClean`. `CreateRequest = {workerId, branch, worktreePath, base?,
  featureId?, tasks?, ownedAreas?}`.
- `adapters/pi/runtime/index.ts` already registers `pi.on("session_start", …)`
  (checkpoint recovery wires there) and `pi.registerCommand("cct:doctor", …)` /
  `cct:config` / `cct:explain`. These are the two wiring points — no new event.
- `pi.on("tool_call", …)` exists but is the enforcement path; **write-time**
  containment (pinning tool writes to the worktree) is explicitly out of scope.
- Pi exposes **no** session-end event (`hooks/events.ts`: Stop/turn-end
  `unsupported`) — so cleanup cannot be automatic; it is command/driver-driven.
- Today there is no `CCT_WORKER_*` env contract; only a subagent-depth env var
  exists (`agents/caps.ts`). This feature defines the worker-signal env contract.

## Design

### D1 — A thin lifecycle module, not logic in index.ts
Add `adapters/pi/runtime/agents/worktree-lifecycle.ts` holding the wiring:
`onSessionStartWorktree(state, env)` and the `/cct:worktree` command handlers. It
**composes** the existing library (loadLedger → validateCreateRequest →
createWorker / reconcile / cleanupWorker → saveLedger) and audits each action.
`index.ts` only *calls* it from the existing `session_start` handler and
`registerCommand`, keeping index.ts thin and the logic unit-testable.

### D2 — Worker signal (FR-2)
`session_start` reads env: `CCT_WORKER_ID` gates everything. When present, build a
`CreateRequest { workerId: CCT_WORKER_ID, branch: CCT_WORKER_BRANCH,
worktreePath: <managed-root>/<sanitized workerId>, base: CCT_WORKER_BASE?,
featureId: CCT_FEATURE_ID?, tasks: split(CCT_WORKER_TASKS), ownedAreas:
split(CCT_WORKER_AREAS) }` and run `validateCreateRequest` (which enforces
managed-root containment + protected-branch refusal + overlap) before
`createWorker`. **No `CCT_WORKER_ID` ⇒ the handler returns immediately** — the
primary session provisions nothing. The env is untrusted, so all string fields
are sanitized/validated by the existing validators; a validation failure warns +
audits and does **not** create.

### D3 — Explicit cleanup command (FR-3)
`/cct:worktree`:
- `cleanup <workerId> [--force]` → `cleanupWorker(...)`. Its existing
  `cleanupEligibility` refuses a worktree that is not (clean **and**
  merged/abandoned); `--force` is honored but audited as an override.
- `list` → the ledger records + `listWorktrees` (live/foreign), read-only.
- `reconcile` → the same pass as D4, on demand.
No `session.deleted`/Stop hook is used; teardown is explicit by design.

### D4 — Reconcile-on-start (FR-4)
In `session_start` (after any worker create), run `pruneWorktrees` then
`reconcile(ledger, listWorktrees(...).paths)` → mark vanished `active` records
`stale`, surface foreign worktrees in a warning. **No removal of live work.**

### D5 — Audit + honesty (FR-5/FR-6)
Every create/cleanup/reconcile calls the existing `audit(...)` with a
`worktree.<action>` rule + subject `<workerId>:<branch>`. `pi-code doctor` /
docs state cleanup is explicit-only because Pi exposes no session-end event.

## Deliverables

1. `agents/worktree-lifecycle.ts` — `onSessionStartWorktree` + `/cct:worktree`
   handlers, composing the existing library, with audit.
2. `index.ts` — 3 call sites: the worker-create + reconcile in the existing
   `session_start` handler, and `registerCommand("cct:worktree", …)`.
3. Launcher/docs: the `/cct:worktree` command in the usage help + a short section
   documenting the `CCT_WORKER_*` env contract and the explicit-cleanup boundary.
4. Tests (below).

## Sequencing

1. Lifecycle module + unit tests (pure composition; no index wiring yet).
2. `session_start` create + reconcile wiring + tests (worker vs primary).
3. `/cct:worktree` command + tests (cleanup preconditions, list, reconcile).
4. Docs + honesty note + `pi-code doctor` surfacing.

## Test strategy

- **Worker create:** with `CCT_WORKER_ID` set (temp repo), `session_start`
  provisions a worktree + ledger record; **without it, nothing is created** and
  the primary worktree is untouched.
- **Validation gate:** a worker signal targeting `master`/`main`, an out-of-root
  path, or an overlapping owned area is refused (no side effect) and audited.
- **Cleanup command:** merged/abandoned + clean → removed; dirty or unmerged →
  refused; `--force` overrides and is audited.
- **Reconcile:** a vanished worktree path → its record marked `stale`; a foreign
  worktree → reported, never removed.
- **No-event honesty:** assert wiring subscribes only to `session_start` (and
  registers the command) — no Stop/`session.deleted` subscription.
- **Audit:** each action emits a `worktree.*` audit record.

Home: `tests/pi-runtime/worktree-lifecycle.test.mjs` (unit, temp-repo), extending
the existing worktree test fixtures; launcher help assertion in
`tests/test-pi-launcher.sh`.

## Open questions for approval

1. **Env contract names** — `CCT_WORKER_ID` / `CCT_WORKER_BRANCH` /
   `CCT_WORKER_BASE` / `CCT_WORKER_TASKS` / `CCT_WORKER_AREAS`. Lean: yes (mirrors
   the `CCT_PEER_*` / `CCT_PI_MODE` launcher-env style). Confirm names.
2. **Worktree path derivation** — `<managed-root>/<sanitized workerId>` (managed
   root = repo parent, matching `createWorker`'s containment). Confirm, or take an
   explicit `CCT_WORKER_PATH`.
3. **Reconcile on every start** vs only when a worker signal is present. Lean:
   always (cheap, keeps the ledger honest) — confirm.
