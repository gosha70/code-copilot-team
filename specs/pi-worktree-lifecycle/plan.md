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

- **Provision (pre-spawn):** two launcher surfaces. `pi-code worktree create
  <workerId> --branch <b> [--base][--path][--tasks][--areas]` calls `createWorker`
  (under the D3 lock) and prints the resolved `worktreePath`; the driver launches
  the worker with `cwd = worktreePath` (via `cd`, or `--project <wt>` which the
  launcher `cd`s into). The atomic happy path is **`pi-code worktree run
  <workerId> --branch <b> [prov flags] -- <pi args>`**: it provisions, exports the
  `CCT_WORKER_*` env, and re-execs `pi-code --project <worktree> <pi args>` so pi
  starts inside the worktree in one step. The CLI provisioner uses
  `primaryRepoRoot(cwd)` (shared git common dir), NOT `gitToplevel`, so running
  it from inside a linked worktree still targets the primary ledger.
- **Validate/attach (session_start):** when `CCT_WORKER_ID` is set, the extension
  loads the ledger record and asserts `process.cwd()` **and** `git rev-parse
  --show-toplevel` both equal the record's `worktreePath`. Match ⇒ attach +
  audit `worktree.attach`, isolation state `ok`. Mismatch/missing ⇒ **fail
  closed OPERATIONALLY**: warn, audit `worktree.not-isolated`, set isolation
  state `invalid`.
- **Enforce (tool_call):** the existing `tool_call` gate reads the isolation
  state via `isolationToolBlock(state, toolName)`; while `invalid` it **blocks
  every `edit`/`write`/`bash`** (audited) so the worker cannot run from the wrong
  directory. Warn-only would let the agent keep editing the primary checkout —
  the exact failure this feature prevents. Read-only tools pass.

### D2 — Thin lifecycle module (`agents/worktree-lifecycle.ts`)
Holds `attachOnSessionStart(state, env)`, `reconcileOnStart(repoRoot)`, the
`/cct:worktree` subcommand handlers, and the D3 lock helper. It **composes** the
existing library and audits each action. `index.ts` only calls it.

### D3 — Serialized ledger mutations, full transaction + owned lock (FR-5, reviews #2 & #3)
Add `withLedgerLock(repoRoot, fn)`: acquire `.cct/worktrees.lock` via an atomic
`fs.mkdirSync(lockDir)` with bounded retry + timeout; on timeout, fail closed
with a clear message. Every mutation — `create`, `cleanup`, **and reconcile in
full** — runs its **entire** `load → list → prune → validate → git op → save`
inside the lock (not just the final write), so a reconcile that loaded the ledger
cannot save a stale copy over a concurrent create, and parallel startups cannot
both win an owned-area conflict.

**Lock ownership (review #3):** the lock dir holds an `owner.json` with the
holder's `{ pid, token, ts }`. Reclamation does **not** rely on age alone — a
slow but legitimate checkout could outlive the threshold. A lock is reclaimed
only when its owner is provably **not alive** (`process.kill(pid, 0)` ⇒ `ESRCH`),
or — when liveness is unknowable (no owner file / unsupported) — after a bounded
age. Release removes the lock only when THIS call still owns the recorded token
(a reclaimer may have taken over), so a live holder's lock is never stolen.

### D4 — Fail-closed reconcile, strict listing + primary excluded (FR-7, reviews #3 & #4)
The tolerant `listWorktrees()` cannot detect malformed porcelain (it ignores bad
lines and always marks the first block primary), so a truncated listing with one
valid first block would pass a naive `filter(isPrimary).length === 1` gate. D4
therefore adds an **additive strict parser**, `listWorktreesStrict(repoRoot) → {
ok, worktrees, reason }` (using `--porcelain -z`, newline-safe), which validates
each record against git's documented shapes and rejects: content before the first
block; a `worktree` line without an absolute path; a NON-bare record missing HEAD
or with neither/both of branch+detached; a `bare` record carrying
HEAD/branch/detached; an invalid HEAD oid; a duplicate structural attribute; an
unterminated/incomplete final record; an unknown structural key; and any result
without exactly one primary.

`reconcileOnStart` runs the whole transaction inside the D3 lock:
1. `listed = listWorktreesStrict(repoRoot)`; if `!listed.ok` ⇒ audit
   `worktree.reconcile-skipped`, **return without pruning/reconciling/saving**.
2. Belt-and-suspenders: if not exactly one `isPrimary` ⇒ skip likewise.
3. `pruneWorktrees` — if it reports failure, skip save.
4. `workerPaths = listed.worktrees.filter(w => !w.isPrimary &&
     fs.existsSync(w.path)).map(w => resolveWorktreePath(w.path))`.
5. `loadLedger` → `reconcile(ledger, workerPaths)` → mark vanished `stale`,
   collect foreign; `saveLedger` **only** when something changed; audit. All of
   1–5 execute while holding the lock (review #3).

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

1. `agents/worktree-lifecycle.ts` — attach/validate + `isolationToolBlock` /
   `isolationStateFromAttach`, the strict `parseWorktreePorcelainStrict` /
   `listWorktreesStrict`, fail-closed `reconcileOnStart`, the pid/token-owned
   `withLedgerLock`, namespaced-path derivation, provisioning + `/cct:worktree`
   handlers.
2. `index.ts` — call `attachOnSessionStart` + `reconcileOnStart` in the existing
   `session_start` handler (store the isolation state); wire `isolationToolBlock`
   into the existing `tool_call` gate; `registerCommand("cct:worktree", …)`.
3. `bin/pi-code` + `cli.ts` — `worktree create …` provisioning subcommand (routes
   to the runtime), usage help entry.
4. Docs — the `CCT_WORKER_*` contract, the pre-spawn `cwd` handoff, the
   fail-closed block, and the explicit-cleanup boundary.
5. Tests (below).

## Sequencing

1. `withLedgerLock` + namespaced path + `worktree create` subcommand (+ tests).
2. `attachOnSessionStart` validate/fail-closed + `index.ts` wiring (+ tests).
3. Fail-closed `reconcileOnStart` (+ tests).
4. `/cct:worktree cleanup|list|reconcile` command (+ tests).
5. Docs + launcher help + honesty note.

## Test strategy (mapped to the review)

- **Isolation + fail-closed block (review #1):** create a worker, launch a real
  command with `cwd=worktreePath`; assert `pwd`/`show-toplevel == worktreePath`.
  A `session_start` whose `cwd` ≠ record → audits `worktree.not-isolated`, state
  `invalid`, and `isolationToolBlock(invalid, edit/write/bash)` returns **block**
  (read-only tools pass); primary worktree unchanged. Plus the source assertion
  that `index.ts` wires the block into `tool_call`.
- **Concurrency + lock ownership (review #2/#3):** two provisions both survive;
  conflicting owned-area requests → exactly one succeeds; a lock owned by a
  **live** pid is NOT stolen even when old, while a **dead** pid's lock is
  reclaimed.
- **Primary-not-foreign (review #3 orig):** a repo with only its primary →
  reconcile produces **zero** foreign warnings and no ledger change.
- **Fail-closed + strict parse (review #4):** `listWorktreesStrict` failure,
  `prune` failure, and a strict-parser **rejection** each leave the ledger
  **byte-for-byte unchanged** + audit `worktree.reconcile-skipped`;
  `parseWorktreePorcelainStrict` is unit-tested directly against malformed inputs
  (truncated block, relative path, pre-block content, unknown key, empty).
- **Cleanup:** merged/abandoned+clean → removed; dirty/unmerged → refused;
  `--force` → override + audit.
- **No-invented-event:** wiring subscribes only to `session_start` +
  `registerCommand` + the existing `tool_call` gate (asserted).

Home: `tests/pi-runtime/worktree-lifecycle.test.mjs` (unit + temp-repo),
launcher-help assertion in `tests/test-pi-launcher.sh`.

## Resolved decisions (were open questions; settled by the #183 review)

1. **Lifecycle model** → controller/`pi-code worktree create` provisions
   pre-spawn; the extension validates/attaches (not create-and-switch).
2. **Isolation failure** → not warn-only: set state `invalid` and **block**
   edit/write/bash at the existing `tool_call` gate (review #1).
3. **Path** → namespaced `<repo-parent>/.cct-worktrees/<repo-name>/<worker-id>`;
   explicit `CCT_WORKER_PATH` still validated.
4. **Reconcile** → run on every start inside the lock, **fail-closed** on an
   untrustworthy/malformed listing (strict result-bearing parse) and
   **primary-excluded**.
5. **Concurrency** → repo-scoped lock around the **full** mutation transaction,
   with pid/token ownership so a live holder's lock is never stolen (review #3).
