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
| 3 | | `pi-code worktree create <workerId> --branch <b> [--base][--path][--tasks][--areas]` → under the lock: `loadLedger → validateCreateRequest → createWorker → saveLedger`; print the resolved path. (FR-1, FR-3, FR-5) | `bin/pi-code`, `runtime/cli.ts` or lifecycle module | prints a worktree path; invalid signal (master/main, out-of-root, overlap) refused, no side effect |
| 4 | | `attachOnSessionStart(state, env)` — if `CCT_WORKER_ID`: load record; assert `process.cwd()` **and** `git rev-parse --show-toplevel` == record path; match → attach+audit (state `ok`); mismatch/missing → fail closed (warn + audit `worktree.not-isolated`, state `invalid`). No `CCT_WORKER_ID` → no-op (`not-a-worker`). (FR-1, FR-2, FR-8) | `agents/worktree-lifecycle.ts` | in-worktree launch: attach; wrong cwd: invalid; primary session: no-op |
| 4b | | `isolationToolBlock(state, toolName)` + `isolationStateFromAttach(status)` — while isolation is `invalid`, **block** edit/write/bash (read-only tools pass). This is the operational fail-closed (warn-only is insufficient). (FR-2, review #1) | `agents/worktree-lifecycle.ts` | invalid+edit/write/bash → block; ok/not-a-worker → allow; read tools → allow |
| 5 | | Wire `attachOnSessionStart` into `pi.on("session_start")` (store `state.worktreeIsolation`); wire `isolationToolBlock` into the existing `tool_call` gate. (FR-1/2, review #1) | `index.ts` | worker session validates isolation; on failure the next edit/write/bash is blocked+audited; primary untouched |
| 6 | | Tests: **isolation** (real command → `pwd`/`show-toplevel` == worktree), wrong-cwd → not-isolated audit → **next edit/bash blocked** (review #1 acceptance), no-signal no-op, invalid-signal refusal; **concurrency** (two creates both survive; conflicting areas → one wins); **lock ownership** (live-owner not stolen, dead-owner reclaimed). (AC-1, AC-2, AC-7) | `tests/pi-runtime/worktree-lifecycle.test.mjs` | all green; block asserted; ledger has both concurrent records |

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
| 9b | | `parseWorktreePorcelainStrict(stdout)` + `listWorktreesStrict(repoRoot)` → `{ok,worktrees,reason}` — reject pre-block content, a path-less/relative `worktree` line, unknown keys, and any listing without exactly one primary. Additive: the tolerant `listWorktrees` and its callers are untouched. (FR-7, review #4) | `agents/worktree-lifecycle.ts` | malformed porcelain → `ok:false`; well-formed → `ok:true` + one primary |
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
