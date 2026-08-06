# Tasks: Pi worktree lifecycle wiring (issue #172)

Wiring only — the T7.3 manager (`agents/worktree.ts`) and its safety model are
already merged and MUST NOT be re-implemented. Keep the gates green
(`test-pi-runtime.sh`, `test-typecheck-gate.sh`, `test-pi-launcher.sh`), audit
every action, and preserve the "never auto-remove live work" guarantee.
`AC` = acceptance criteria.

## US1 — Create on worker start

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 1 | | Add `agents/worktree-lifecycle.ts` with `onSessionStartWorktree(state, env)`: read `CCT_WORKER_ID` (gate); build a `CreateRequest` from `CCT_WORKER_{BRANCH,BASE,TASKS,AREAS}` + `CCT_FEATURE_ID`; run `validateCreateRequest` then `createWorker`; audit `worktree.create`. Absent `CCT_WORKER_ID` ⇒ return without side effect. (FR-1, FR-2, FR-5) | `adapters/pi/runtime/agents/worktree-lifecycle.ts` | worker signal → 1 worktree + ledger record; no signal → nothing; invalid signal (master/main, out-of-root, overlap) → refused + audited, no git op |
| 2 | | Wire the call into the existing `pi.on("session_start")` in `index.ts` (alongside checkpoint recovery); pass the runtime state + `process.env`. (FR-1) | `adapters/pi/runtime/index.ts` | starting a worker session provisions the worktree; the **primary** worktree is unchanged |
| 3 | | Unit tests (temp repo): worker-create happy path; no-signal no-op; validation refusals; audit emitted. (FR-1/2/5) | `tests/pi-runtime/worktree-lifecycle.test.mjs` | all green; primary-worktree-untouched asserted |

**Checkpoint US1** — worker create is gated by `CCT_WORKER_ID`; primary session provisions nothing; untrusted signal is validated before any git side effect.

---

## US2 — Explicit cleanup command

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 4 | | Add the `/cct:worktree` handlers in the lifecycle module: `cleanup <workerId> [--force]` → `cleanupWorker` (honor `cleanupEligibility`; `--force` audited as override); `list` → ledger + `listWorktrees` (live/foreign), read-only; `reconcile` → the US3 pass. (FR-3, FR-5) | `agents/worktree-lifecycle.ts` | cleanup of merged/abandoned+clean removes it; dirty/unmerged refused; `--force` overrides + audits |
| 5 | | Register `pi.registerCommand("cct:worktree", …)` in `index.ts` (mirroring `cct:doctor`); route subcommands to the handlers. (FR-3) | `adapters/pi/runtime/index.ts` | `/cct:worktree …` dispatches; `--help`/usage shown |
| 6 | | Tests: cleanup preconditions (merged/abandoned+clean → removed; dirty/unmerged → refused; force → override+audit); `list` output shape. (FR-3) | `tests/pi-runtime/worktree-lifecycle.test.mjs` | all branches asserted |

**Checkpoint US2** — teardown is explicit-only (no session-end event used); cleanup honors the manager's preconditions; force is audited.

---

## US3 — Reconcile + honesty + docs

| # | [P] | Task | File(s) | AC |
|---|-----|------|---------|----|
| 7 | | In `session_start` (and via `/cct:worktree reconcile`) run `pruneWorktrees` + `reconcile(ledger, listWorktrees().paths)` → mark vanished `active` records `stale`, warn on foreign; save ledger. Never remove live work. (FR-4) | `agents/worktree-lifecycle.ts`, `index.ts` | vanished path → record `stale`; foreign worktree → reported, not removed |
| 8 | | Tests: reconcile marks stale + reports foreign; a subscription assertion proves wiring uses ONLY `session_start` + `registerCommand` (no Stop/`session.deleted`). (FR-4, FR-6, AC-3) | `tests/pi-runtime/worktree-lifecycle.test.mjs` | green; no-invented-event asserted |
| 9 | [P] | Docs + honesty: document the `CCT_WORKER_*` env contract and that cleanup is **explicit-only** because Pi exposes no session-end event; add `/cct:worktree` to the launcher usage help + a launcher-test assertion. (FR-6) | `adapters/pi/docs/*`, `adapters/pi/bin/pi-code`, `tests/test-pi-launcher.sh` | doc states the degraded boundary; help lists `/cct:worktree`; launcher test green |

**Checkpoint US3** — reconcile keeps the ledger honest without removing live work; the no-session-end limitation is documented, not hidden.

---

## Global definition of done (every task)

`build` + `typecheck` (strict) + Pi runtime suite + launcher suite green ·
worktree manager & its safety model unchanged (wiring only) · every worktree
action audited · the "never auto-remove live work" guarantee intact · no new Pi
event source invented (only `session_start` + `registerCommand`).
