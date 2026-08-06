---
spec_mode: full
feature_id: pi-worktree-lifecycle
risk_category: security
justification: |
  Wires the T7.3 worktree manager into the live Pi session so worker sessions
  actually run inside an isolated git worktree. Safety-sensitive: it must never
  convert the primary worktree, must serialize ledger mutations against parallel
  workers, must fail closed on git-listing failures (never mark live workers
  stale), and must validate untrusted CCT_WORKER_* env before any git side effect.
  The manager + safety model already exist and are tested; this is wiring only,
  corrected per the PR #183 review so isolation is real (the worker runs inside
  its worktree), not merely a created directory.
status: draft
date: 2026-08-06
origin:
  issue: https://github.com/gosha70/code-copilot-team/issues/172
  review: https://github.com/gosha70/code-copilot-team/pull/183
  origin_claim: |
    The T7.3 worktree manager is merged (#154/#155). The gap is live wiring into
    Pi's session lifecycle. The #183 review corrected the model: creating a
    worktree at session_start does NOT isolate the already-running session, so
    creation must happen before the worker Pi is spawned (cwd=worktreePath) and
    the extension validates/attaches. It also requires: concurrency-safe ledger
    mutation, primary-excluded + fail-closed reconciliation, and repo-namespaced
    paths. Write-time enforcement and auto-remove-on-crash stay out of scope.
---

# Plan: Pi worktree lifecycle wiring

## Existing facts (verified)

- Library complete: `createWorker(repoRoot, ledger, req, nowIso)`,
  `cleanupWorker(repoRoot, ledger, workerId, {force?})`,
  `reconcile(ledger, liveWorktreePaths)`, `pruneWorktrees(repoRoot)`,
  `validateCreateRequest` (managed-root containment + protected-branch + overlap),
  `cleanupEligibility({isClean,isPrimary,force})`, `listWorktrees`,
  `isWorktreeClean`, `loadLedger`/`saveLedger`. `CreateRequest = {workerId,
  branch, worktreePath, base?, featureId?, tasks?, ownedAreas?}`.
- `listWorktrees()` returns `[]` on git failure and its **first entry is always
  the primary** (`isPrimary`). `reconcile()` marks **every** live path not in the
  ledger as foreign. Ledger I/O has **no lock/CAS**.
- `index.ts` registers `pi.on("session_start", …)` (checkpoint recovery wires
  there; `state.cwd = ctx.cwd ?? process.cwd()`) and `pi.registerCommand(…)`
  (`cct:doctor`/`config`/`explain`). No session-end event exists.

## Design (corrected per the #183 review)

### D1 — Creation is pre-spawn; the extension validates, it does not create (FR-1/FR-2)
**Blocker fix (review #1).** Pi cannot relocate a running session, so creating a
worktree at `session_start` would leave the agent editing the *primary* checkout.
Split the responsibilities:

- **Provision (pre-spawn):** a launcher subcommand
  `pi-code worktree create <workerId> --branch <b> [--base <base>] [--path <p>]
  [--tasks …] [--areas …]` calls `createWorker` (under the D3 lock) and prints the
  resolved `worktreePath`. The driver/controller then launches the worker with
  `cwd = worktreePath` and the `CCT_WORKER_*` env. (Equivalently, a controller
  calls `createWorker` directly and spawns with that cwd.)
- **Validate/attach (session_start):** when `CCT_WORKER_ID` is set, the extension
  loads the ledger record and asserts `process.cwd()` **and** `git rev-parse
  --show-toplevel` both equal the record's `worktreePath`. Match ⇒ attach +
  audit `worktree.attach`. Mismatch/missing ⇒ **fail closed**: push a warning,
  audit `worktree.not-isolated`, and do not treat the session as isolated.

### D2 — Thin lifecycle module (`agents/worktree-lifecycle.ts`)
Holds `attachOnSessionStart(state, env)`, `reconcileOnStart(repoRoot)`, the
`/cct:worktree` subcommand handlers, and the D3 lock helper. It **composes** the
existing library and audits each action. `index.ts` only calls it.

### D3 — Serialized ledger mutations (FR-5, review #2)
Add `withLedgerLock(repoRoot, fn)`: acquire `.cct/worktrees.lock` via an atomic
`fs.mkdirSync(lockDir)` (or `open` with `wx`) with bounded retry + timeout; on
timeout, fail closed with a clear message. Every mutation —
`create`, `cleanup`, reconcile-save — runs its full `load → validate → git op →
save` inside the lock, so parallel worker startups cannot lose each other's
records or both win an owned-area conflict. Stale-lock reclamation uses the
lock's own mtime + a bounded age.

### D4 — Fail-closed reconcile with the primary excluded (FR-7, reviews #3 & #4)
`reconcileOnStart`:
1. `live = listWorktrees(repoRoot)`.
2. **Trust gate:** if `live.filter(isPrimary).length !== 1` ⇒ git listing is
   untrustworthy (failure/malformed) ⇒ audit `worktree.reconcile-skipped` and
   **return without pruning/reconciling/saving** (ledger untouched).
3. `pruneWorktrees` — if it reports failure, likewise skip save.
4. `workerPaths = live.filter(w => !w.isPrimary && fs.existsSync(w.path))
     .map(w => w.path)`.
5. `reconcile(ledger, workerPaths)` → mark vanished `stale`, collect foreign;
   `saveLedger` **only** when something changed, under the D3 lock; audit.

### D5 — Namespaced path default (FR-4, review "additional")
`defaultWorktreePath(repoRoot, workerId) =
<repo-parent>/.cct-worktrees/<basename(repoRoot)>/<sanitize(workerId)>` — avoids
two sibling repos colliding on the same `workerId`. An explicit `CCT_WORKER_PATH`
is honored but still goes through `validateCreateRequest` containment.

### D6 — Cleanup command (FR-6)
`/cct:worktree cleanup <workerId> [--force]` → `cleanupWorker` under the lock;
`list` → ledger + `listWorktrees` (read-only); `reconcile` → D4. No session-end
hook is used — teardown is explicit by design.

### D7 — Audit + honesty (FR-8)
Each action audits `worktree.<create|attach|cleanup|reconcile|not-isolated|
reconcile-skipped>` with subject `<workerId>:<branch>`. Docs + `pi-code doctor`
state cleanup is explicit-only (no Pi session-end event).

## Deliverables

1. `agents/worktree-lifecycle.ts` — attach/validate, fail-closed reconcile, the
   `withLedgerLock` helper, namespaced-path derivation, `/cct:worktree` handlers.
2. `index.ts` — call `attachOnSessionStart` + `reconcileOnStart` in the existing
   `session_start` handler; `registerCommand("cct:worktree", …)`.
3. `bin/pi-code` — `worktree create …` provisioning subcommand (routes to the
   runtime), usage help entry.
4. Docs — the `CCT_WORKER_*` contract, the pre-spawn `cwd` handoff, and the
   explicit-cleanup boundary.
5. Tests (below).

## Sequencing

1. `withLedgerLock` + namespaced path + `worktree create` subcommand (+ tests).
2. `attachOnSessionStart` validate/fail-closed + `index.ts` wiring (+ tests).
3. Fail-closed `reconcileOnStart` (+ tests).
4. `/cct:worktree cleanup|list|reconcile` command (+ tests).
5. Docs + launcher help + honesty note.

## Test strategy (mapped to the review)

- **Isolation (review #1):** create a worker, launch a real command with
  `cwd=worktreePath`; assert `pwd == worktreePath` and `git rev-parse
  --show-toplevel == worktreePath`. A `session_start` whose `cwd` ≠ record fails
  closed (audited `worktree.not-isolated`); primary worktree unchanged.
- **Concurrency (review #2):** start two `createWorker`s simultaneously → both
  records survive; two conflicting owned-area requests → exactly one succeeds.
- **Primary-not-foreign (review #3):** a repo with only its primary → reconcile
  produces **zero** foreign warnings and no ledger change.
- **Fail-closed (review #4):** `git worktree list` failure, `prune` failure, and
  malformed porcelain each leave the ledger **byte-for-byte unchanged** + audit
  `worktree.reconcile-skipped`.
- **Cleanup:** merged/abandoned+clean → removed; dirty/unmerged → refused;
  `--force` → override + audit.
- **No-invented-event:** wiring subscribes only to `session_start` + registers the
  command (asserted).

Home: `tests/pi-runtime/worktree-lifecycle.test.mjs` (unit + temp-repo),
launcher-help assertion in `tests/test-pi-launcher.sh`.

## Resolved decisions (were open questions; settled by the #183 review)

1. **Lifecycle model** → controller/`pi-code worktree create` provisions
   pre-spawn; the extension validates/attaches (not create-and-switch).
2. **Path** → namespaced `<repo-parent>/.cct-worktrees/<repo-name>/<worker-id>`;
   explicit `CCT_WORKER_PATH` still validated.
3. **Reconcile** → run on every start, but **fail-closed** (skip on untrustworthy
   git listing) and **primary-excluded**.
4. **Concurrency** → repo-scoped lockfile around every ledger mutation.
