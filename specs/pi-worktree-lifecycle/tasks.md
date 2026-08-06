# Tasks: Pi worktree lifecycle wiring (issue #172, revised per PR #183 review)

Wiring only — the T7.3 manager (`agents/worktree.ts`) and its safety model are
already merged and MUST NOT be re-implemented. Keep the gates green
(`test-pi-runtime.sh`, `test-typecheck-gate.sh`, `test-pi-launcher.sh`), audit
every action, and preserve "never auto-remove live work". `AC` = acceptance.

## US1 — Isolation: create pre-spawn, validate on start

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 1 | | `withLedgerLock(repoRoot, fn)` — atomic `.cct/worktrees.lock` (mkdir) + `owner.json` `{pid,token}`; bounded retry/timeout; reclaim ONLY a dead-owner lock (or, liveness-unknown, an aged one) and release only when THIS call still owns the token — never steal a live holder's lock. Fail closed on timeout. (FR-5, review #3) | `agents/worktree-lifecycle.ts` | mutation runs only while holding the lock; live-owner lock not stolen; dead-owner lock reclaimed; timeout errors clearly |
| 2 | | `defaultWorktreePath` = `<repo-parent>/.cct-worktrees/<repo-name>/<sanitize(workerId)>`; honor `CCT_WORKER_PATH` override but still validate. (FR-4) | `agents/worktree-lifecycle.ts` | two sibling repos with the same workerId resolve to different paths |
| 3 | | `pi-code worktree create <workerId> --branch <b> [--base][--path][--tasks][--areas]` → under the lock: `loadLedger → createWorker → saveLedger`; print the resolved path. The CLI resolves the **primary** repo root via `primaryRepoRoot(cwd)` (shared git common dir), NOT `gitToplevel` — invoked from a linked worktree it still targets the primary ledger (review #4). (FR-1, FR-3, FR-5) | `bin/pi-code`, `runtime/cli.ts` | prints a worktree path; invalid signal refused, no side effect; linked-worktree invocation → primary ledger |
| 3b | | `pi-code worktree run <workerId> --branch <b> [prov flags] -- <pi args>` — provision, export `CCT_WORKER_*`, re-exec `pi-code --project <worktree> <pi args>` so pi starts with `cwd = worktree` (atomic provision+spawn happy path). (FR-1) | `bin/pi-code` | one command provisions + launches pi inside the worktree; verified at the process boundary with a pi shim |
| 4 | | `attachOnSessionStart(state, env)` — if `CCT_WORKER_ID`: load record; assert `process.cwd()` **and** `git rev-parse --show-toplevel` == record path; match → attach+audit (state `ok`); mismatch/missing → fail closed (warn + audit `worktree.not-isolated`, state `invalid`). No `CCT_WORKER_ID` → no-op (`not-a-worker`). (FR-1, FR-2, FR-8) | `agents/worktree-lifecycle.ts` | in-worktree launch: attach; wrong cwd: invalid; primary session: no-op |
| 4b | | `isolationToolBlock(state, toolName)` + `isolationStateFromAttach(status)` — while isolation is `invalid`, **block** edit/write/bash (read-only tools pass). This is the operational fail-closed (warn-only is insufficient). (FR-2, review #1) | `agents/worktree-lifecycle.ts` | invalid+edit/write/bash → block; ok/not-a-worker → allow; read tools → allow |
| 5 | | Wire `attachOnSessionStart` into `pi.on("session_start")` (store `state.worktreeIsolation`); wire `isolationToolBlock` into the existing `tool_call` gate. (FR-1/2, review #1) | `index.ts` | worker session validates isolation; on failure the next edit/write/bash is blocked+audited; primary untouched |
| 6 | | Tests: **isolation** (real command → `pwd`/`show-toplevel` == worktree), wrong-cwd → not-isolated audit → **next edit/bash blocked** (review #1 acceptance), no-signal no-op, invalid-signal refusal; **REAL-process concurrency** (barrier-released child processes: two provisions both survive; conflicting areas → one wins; provision-vs-reconcile not lost); **lock ownership** (live-owner not stolen, dead-owner reclaimed); **process boundary** (`worktree run` launches pi in the worktree with `CCT_WORKER_*`; CLI-from-linked-worktree → primary ledger). (AC-1, AC-2, AC-7, AC-8) | `tests/pi-runtime/worktree-lifecycle.test.mjs` (+ `fixtures/provision-worker.mjs`), `tests/test-pi-launcher.sh` | all green; block asserted; real concurrent records survive |

**Checkpoint US1** — the worker provably runs inside its worktree (validated, fail-closed on mismatch); ledger mutations are lock-serialized.

---

## US2 — Explicit cleanup command

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 7 | | `/cct:worktree` handlers: `cleanup <workerId> [--force]` → `cleanupWorker` under the lock (honor `cleanupEligibility`; `--force` audited override); `list` → ledger + `listWorktrees` (read-only). (FR-6, FR-8) | `agents/worktree-lifecycle.ts` | merged/abandoned+clean → removed; dirty/unmerged → refused; force → override+audit |
| 8 | | `registerCommand("cct:worktree", …)` in `index.ts`; route subcommands. (FR-6) | `index.ts` | `/cct:worktree …` dispatches; usage shown |
| 9 | | Tests: cleanup preconditions (all branches), `list` shape, lock held during cleanup. (AC-3) | `tests/pi-runtime/worktree-lifecycle.test.mjs` | branches asserted |

**Checkpoint US2** — teardown is explicit-only (no session-end event); force is audited.

---

## US3 — Fail-closed reconcile + honesty/docs

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 9b | | `parseWorktreePorcelainStrict(raw,{z})` + `listWorktreesStrict(repoRoot)` (via `--porcelain -z`) → `{ok,worktrees,reason}` — validate each record against git's shapes: reject pre-block content, path-less/relative `worktree`, a non-bare record missing HEAD or with neither/both branch+detached, a bare record with HEAD/branch/detached, invalid HEAD oid, duplicate attrs, unterminated final record, unknown keys, and any listing without exactly one primary. Additive: tolerant `listWorktrees` + callers untouched. (FR-7, review #4) | `agents/worktree-lifecycle.ts` | incomplete-but-valid-path records → `ok:false`; well-formed branch/detached/bare → `ok:true` |
| 10 | | `reconcileOnStart(repoRoot)` **inside the lock** (full transaction, review #3): `listed = listWorktreesStrict`; **skip if `!listed.ok`** (git-fail/malformed) → audit `worktree.reconcile-skipped`, no save; skip if not one primary or `pruneWorktrees` fails; else `workerPaths = listed.worktrees.filter(!isPrimary && exists).map(resolve)`; `loadLedger`; `reconcile`; save only on change; audit. (FR-7, FR-8) | `agents/worktree-lifecycle.ts`, `index.ts` | vanished → `stale`; foreign → reported, not removed; primary never foreign |
| 11 | | Tests: primary-only repo → **zero** foreign + no ledger change; `listWorktreesStrict`-failure / `prune`-failure / strict-parser **rejection** → ledger **byte-for-byte unchanged** + audit; strict parser unit-tested against malformed inputs directly; vanished → stale; foreign → reported. (AC-4, AC-5) | `tests/pi-runtime/worktree-lifecycle.test.mjs` | all fail-closed paths asserted (ledger bytes unchanged) |
| 12 | | Assert wiring subscribes ONLY to `session_start` + registers the command (no Stop/`session.deleted`). (AC-6) | `tests/pi-runtime/worktree-lifecycle.test.mjs` | no-invented-event asserted |
| 13 | [P] | Docs + honesty: the `CCT_WORKER_*` contract + the pre-spawn `cwd` handoff + explicit-cleanup boundary; `/cct:worktree` + `worktree create` in launcher usage help + a launcher-test assertion. (FR-8) | `adapters/pi/docs/*`, `bin/pi-code`, `tests/test-pi-launcher.sh` | doc states the degraded boundary; help lists the commands; launcher test green |

**Checkpoint US3** — reconcile never produces a false foreign (primary excluded) and never marks live workers stale on a git failure (fail-closed); the no-session-end limitation is documented.

---

## Global definition of done (every task)

`build` + `typecheck` (strict) + Pi runtime suite + launcher suite green ·
worktree manager & safety model unchanged (only an **additive** strict listing
added) · every action audited · "never auto-remove live work" intact · isolation
failure **blocks** edit/write/bash (not warn-only) · the **full** reconcile
transaction is lock-serialized with pid/token lock ownership · reconcile
fail-closed (strict parse) + primary-excluded · no new Pi event source invented.
