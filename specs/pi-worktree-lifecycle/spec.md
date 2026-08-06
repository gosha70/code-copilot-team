# Spec: Pi worktree lifecycle wiring

Source: GitHub issue **#172**, refined by the PR #183 review (2026-08-06). Wires
the **already-built** T7.3 worktree manager (`adapters/pi/runtime/agents/
worktree.ts`, merged #154/#155) into Pi's *verifiable* session lifecycle. **No**
re-implementation of the manager or its safety model — only the missing live
wiring, corrected so that **the worker actually runs inside its worktree**.

## Context (do NOT rebuild)

The manager already ships `createWorker` / `cleanupWorker` / `reconcile` /
`pruneWorktrees` / `setMergeStatus`, the `.cct/worktrees.json` ledger, and the
enforced safety model (isolation off a base branch, refuse master/main, ownership
conflicts, dirty-refuse, foreign-worktree protection, stale reconcile, no
force/reset/`branch -D`, symlink-escape containment), with temp-repo tests.

**Known library facts the wiring must respect** (verified for this spec):
- `listWorktrees()` returns `[]` on any git failure — indistinguishable from a
  genuinely empty result — and its first entry is always the primary
  (`isPrimary: true`).
- `reconcile()` classifies *every* live path not in the ledger as **foreign**.
- Ledger I/O (`loadLedger`/`saveLedger`) is plain `readFileSync`/`writeFileSync`
  with **no locking or CAS**.

## User Scenarios

- **US1 — Isolation is real.** As a driver/controller orchestrating parallel
  workers, a worker Pi session **runs inside** its own git worktree — its file
  edits, shell commands, and git operations all resolve to the worktree, and the
  user's **primary** worktree is never touched.
- **US2 — Explicit teardown.** As an operator, I explicitly tear down a finished
  worker's worktree with `/cct:worktree cleanup`; a **dirty or unmerged** worktree
  is refused unless I audibly `--force` it.
- **US3 — Honest reconciliation.** On session start (and on demand) stale ledger
  records are marked and foreign worktrees surfaced — but the **primary is never
  flagged foreign**, a **git failure never marks live workers stale**, and **live
  work is never auto-removed**.

## Requirements

- **FR-1 — Worker runs inside its worktree (isolation, not just creation).** A
  worktree the session does not execute inside is not isolation. Pi captures
  `ctx.cwd` at `session_start` and exposes no verified API to change the running
  session's directory afterward. Therefore **creation happens before the worker
  Pi is spawned**: a driver/controller (or `pi-code worktree create`) provisions
  the worktree + ledger record and launches the worker process with
  `cwd = worktreePath`. The `session_start` extension **does not** create-and-hope
  the session relocates.
- **FR-2 — Validate/attach on session_start.** On `session_start`, IF
  `CCT_WORKER_ID` is set, the extension looks up the ledger record and
  **validates** that both `process.cwd()` and `git rev-parse --show-toplevel`
  equal the record's `worktreePath`. Match ⇒ attach (audit `worktree.attach`).
  Mismatch (or missing record) ⇒ **fail closed**: warn + audit
  `worktree.not-isolated`, and do **not** proceed as if isolated. Absent
  `CCT_WORKER_ID` ⇒ no-op (a primary/interactive session is never a worker).
- **FR-3 — Worker signal contract.** The spawning driver sets, at minimum,
  `CCT_WORKER_ID` and `CCT_WORKER_BRANCH`, and optionally `CCT_WORKER_BASE`,
  `CCT_WORKER_TASKS`, `CCT_WORKER_AREAS`, `CCT_WORKER_PATH`, `CCT_FEATURE_ID`.
  These are **untrusted**; every path/branch/area is validated by the existing
  `validateCreateRequest` (managed-root containment, protected-branch refusal,
  overlap) before any git side effect.
- **FR-4 — Namespaced worktree path.** The default worktree path is namespaced by
  repository to avoid cross-repo collisions:
  `<repo-parent>/.cct-worktrees/<repo-name>/<sanitized-worker-id>`. An explicit
  `CCT_WORKER_PATH` override is honored but still passes containment/validation.
- **FR-5 — Serialized ledger mutations (concurrency-safe).** `createWorker`,
  `cleanupWorker`, and reconcile-save each run as a **repo-scoped critical
  section**: acquire a `.cct/worktrees.lock` (atomic create + bounded retry) →
  `loadLedger` → validate → git op → `saveLedger` → release. Two workers starting
  simultaneously must both end up in the ledger, and conflicting owned-area
  requests must not both succeed.
- **FR-6 — Explicit cleanup, NOT a session-end event.** Pi exposes **no**
  session-end/`session.deleted` event. Register `/cct:worktree cleanup <workerId>
  [--force]` → `cleanupWorker` (honor `cleanupEligibility`: clean **and**
  merged/abandoned; `force` audited as override), plus `/cct:worktree list`
  (ledger + live/foreign, read-only) and `/cct:worktree reconcile`.
- **FR-7 — Fail-closed reconcile.** On `session_start` (and via the command) run
  reconcile ONLY when git listing is trustworthy: `listWorktrees()` must contain
  **exactly one `isPrimary` entry** (its absence ⇒ git failed ⇒ audit + **do not
  prune/reconcile/save**; ledger left byte-for-byte unchanged). On a trustworthy
  listing, **exclude the primary** and non-existent paths before `reconcile`, then
  save under the lock. Never auto-remove live work.
- **FR-8 — Audit + honesty.** Every create/attach/cleanup/reconcile action emits
  a `worktree.*` audit record (decision, rule, subject). Docs/diagnostics state
  that cleanup is **explicit-only** because Pi exposes no session-end event —
  degraded by construction, not a bug.

## Constraints

- No re-implementation of `worktree.ts` or any of its safety guarantees.
- Wiring uses **only** `session_start` and `registerCommand` — no invented event.
- Runtime is TypeScript strict; the launcher/env stays bash 3.2 compatible.
- The "**never auto-remove live work**" guarantee is preserved end-to-end.

## Out of scope (separate issues, per #172)

- **Write-time path/ownership enforcement** (pinning every tool write inside the
  worktree at the permission layer) — deferred by the T7.3 design.
- **Auto-remove-on-crash** — conflicts with "never auto-remove live work"; needs
  its own design decision.

## Acceptance criteria

1. **Isolation:** after a worker is provisioned and launched with `cwd`, a real
   worker tool command resolves to the worktree — `pwd == worktreePath` and
   `git rev-parse --show-toplevel == worktreePath`; the primary worktree is
   unchanged. `session_start` with a mismatching cwd **fails closed** (audited).
2. **Concurrency:** two allocations started simultaneously both survive in the
   ledger; two conflicting owned-area requests cannot both succeed.
3. **Cleanup:** a merged/abandoned + clean worker worktree is removed via
   `cleanupWorker`; dirty/unmerged is refused unless audibly `--force`d.
4. **Reconcile — no false positives:** an ordinary repo with only its primary
   checkout produces **no foreign-worktree warning**; a vanished worker path is
   marked `stale`; a foreign worktree is reported (never removed).
5. **Reconcile — fail-closed:** on `git worktree list`/`prune` failure or
   malformed porcelain, the ledger is left **byte-for-byte unchanged** and the
   failure is audited.
6. **No new event source:** wiring uses only `session_start` / `registerCommand`.
