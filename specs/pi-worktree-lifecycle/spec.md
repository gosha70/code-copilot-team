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
  (`isPrimary: true`). It also **tolerates malformed lines**, so it cannot be
  used as a trust gate; this wiring adds an **additive** strict parser
  (`listWorktreesStrict`, see FR-7) rather than modifying the tolerant one.
- `reconcile()` classifies *every* live path not in the ledger as **foreign**.
- Ledger I/O (`loadLedger`/`saveLedger`) is plain `readFileSync`/`writeFileSync`
  with **no locking or CAS** — hence FR-5's repo-scoped lock.

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
- **FR-2 — Validate/attach on session_start, and BLOCK on failure.** On
  `session_start`, IF `CCT_WORKER_ID` is set, the extension looks up the ledger
  record and **validates** that both `process.cwd()` and `git rev-parse
  --show-toplevel` equal the record's `worktreePath`. Match ⇒ attach (audit
  `worktree.attach`), isolation state `ok`. Mismatch (or missing record) ⇒ **fail
  closed OPERATIONALLY**: warn + audit `worktree.not-isolated` AND set the
  isolation state to `invalid`. While `invalid`, the existing `tool_call` gate
  **blocks every `edit`/`write`/`bash`** call (audited `worktree.not-isolated`)
  so the worker cannot run from the wrong directory — warn-only is not
  sufficient. Read-only tools are unaffected. Absent `CCT_WORKER_ID` ⇒ no-op (a
  primary/interactive session is never a worker; state `not-a-worker`).
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
  `cleanupWorker`, and **reconcile in full** each run as a **repo-scoped critical
  section**: acquire a `.cct/worktrees.lock` (atomic `mkdir` + bounded retry) →
  `loadLedger` → (list/prune/)validate → git op → `saveLedger` → release. The
  **entire** transaction — not just the final write — runs inside the lock, so a
  reconcile that loaded the ledger cannot save a stale copy over a concurrent
  create. The lock records the holder's **pid + a unique token**; a lock is
  reclaimed only when its owner is provably not alive (crashed) or, when liveness
  is unknowable, after a bounded age — a slow-but-live holder is never stolen —
  and is released only by the process that still owns the recorded token. Two
  workers starting simultaneously must both end up in the ledger, and conflicting
  owned-area requests must not both succeed.
- **FR-6 — Explicit cleanup, NOT a session-end event.** Pi exposes **no**
  session-end/`session.deleted` event. Register `/cct:worktree cleanup <workerId>
  [--force]` → `cleanupWorker` (honor `cleanupEligibility`: clean **and**
  merged/abandoned; `force` audited as override), plus `/cct:worktree list`
  (ledger + live/foreign, read-only) and `/cct:worktree reconcile`.
- **FR-7 — Fail-closed reconcile (strict listing).** On `session_start` (and via
  the command) run reconcile ONLY when the git listing is trustworthy. Because
  the manager's tolerant `listWorktrees()` cannot distinguish malformed porcelain
  from a valid result (it ignores bad lines and always calls the first block
  primary), a **strict, result-bearing** listing is used:
  `listWorktreesStrict() → { ok, worktrees, reason }` rejects content before the
  first block, a `worktree` line without an absolute path, unknown structural
  keys, and any listing without exactly one primary. Reconcile proceeds only when
  `ok === true`; otherwise it audits `worktree.reconcile-skipped` and leaves the
  ledger **byte-for-byte unchanged** (a git failure or malformed output never
  marks live workers stale). On a trustworthy listing, **exclude the primary**
  and non-existent paths before `reconcile`, then save under the lock. Never
  auto-remove live work.
- **FR-8 — Audit + honesty.** Every create/attach/cleanup/reconcile action emits
  a `worktree.*` audit record (decision, rule, subject). Docs/diagnostics state
  that cleanup is **explicit-only** because Pi exposes no session-end event —
  degraded by construction, not a bug.

## Constraints

- No re-implementation of `worktree.ts`'s safety guarantees. A **small additive**
  hardening is permitted where wiring alone is insufficient: a new
  `listWorktreesStrict` (result-bearing porcelain parse) is added alongside the
  existing tolerant `listWorktrees` — the existing function and its callers are
  untouched.
- Wiring uses **only** `session_start`, `registerCommand`, and the existing
  `tool_call` gate — no invented event.
- Runtime is TypeScript strict; the launcher/env stays bash 3.2 compatible.
- The "**never auto-remove live work**" guarantee is preserved end-to-end.

## Out of scope (separate issues, per #172)

- **Write-time path/ownership enforcement** (pinning *every* tool write inside the
  worktree at the permission layer, per-path) — deferred by the T7.3 design. Note
  this is distinct from FR-2's coarse fail-closed block: FR-2 blocks *all*
  edit/write/bash when isolation is `invalid`; it does not pin individual writes
  to the worktree path when isolation is `ok`.
- **Auto-remove-on-crash** — conflicts with "never auto-remove live work"; needs
  its own design decision.

## Acceptance criteria

1. **Isolation + fail-closed block:** after a worker is provisioned and launched
   with `cwd`, a real worker tool command resolves to the worktree — `pwd ==
   worktreePath` and `git rev-parse --show-toplevel == worktreePath`; the primary
   worktree is unchanged. `session_start` with a **mismatching** cwd → audits
   `worktree.not-isolated`, sets isolation `invalid`, **and the next
   edit/write/bash tool_call is BLOCKED** (audited); the primary checkout remains
   unchanged. A read-only tool is not blocked.
2. **Concurrency:** two allocations started simultaneously both survive in the
   ledger; two conflicting owned-area requests cannot both succeed.
3. **Cleanup:** a merged/abandoned + clean worker worktree is removed via
   `cleanupWorker`; dirty/unmerged is refused unless audibly `--force`d.
4. **Reconcile — no false positives:** an ordinary repo with only its primary
   checkout produces **no foreign-worktree warning**; a vanished worker path is
   marked `stale`; a foreign worktree is reported (never removed).
5. **Reconcile — fail-closed:** on `git worktree list`/`prune` failure or
   **malformed porcelain** (a truncated/garbled listing the strict parser
   rejects), the ledger is left **byte-for-byte unchanged** and the failure is
   audited `worktree.reconcile-skipped`. The strict parser is unit-tested against
   the malformed cases directly.
6. **No new event source:** wiring uses only `session_start` / `registerCommand`
   / the existing `tool_call` gate.
7. **Concurrency-safe transaction + lock ownership:** the full reconcile
   transaction runs inside the lock; a lock whose owner process is alive is never
   stolen (even when old), while a crashed owner's lock is reclaimed.
