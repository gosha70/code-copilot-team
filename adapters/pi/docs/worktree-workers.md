# Parallel worker worktrees

How the Pi adapter runs a **worker** session inside its own isolated git
worktree, and why teardown is explicit. This wires the already-built T7.3
worktree manager (`runtime/agents/worktree.ts`) into Pi's session lifecycle
(`runtime/agents/worktree-lifecycle.ts`); the manager owns the safety model
(isolation off a base branch, protected-branch refusal, ownership conflicts,
dirty/foreign/primary protection, symlink-escape containment) and is not
re-implemented here.

The authoritative surfaces never drift:

```sh
pi-code worktree run <workerId> --branch <b> [prov flags] [-- <pi args>]  # provision + launch (one shot)
pi-code worktree create <workerId> --branch <b> [...]   # provision only (prints the path)
/cct:worktree list | cleanup <workerId> [--force] | reconcile   # in a session
```

## Isolation is real — creation is PRE-SPAWN

Pi captures the working directory (`ctx.cwd`) at `session_start` and exposes no
verified API to move a **running** session into a different directory. So a
worktree created *inside* `session_start` would leave the agent still editing the
**primary** checkout — a created directory, not isolation.

The lifecycle therefore splits the responsibility:

1. **Provision, before the worker Pi starts.** A driver/controller runs
   `pi-code worktree create <workerId> --branch <b> …`. It creates the isolated
   worktree + ledger record (under the ledger lock) and **prints the resolved
   worktree path**.
2. **Launch the worker in that path.** The driver spawns the worker Pi with
   `cwd = <that path>` and the `CCT_WORKER_*` env below.
3. **Validate on `session_start`, and BLOCK on failure.** When `CCT_WORKER_ID`
   is set, the extension loads the ledger record and asserts that **both**
   `process.cwd()` **and** `git rev-parse --show-toplevel` equal the record's
   worktree path. Match ⇒ attach (audit `worktree.attach`), isolation `ok`.
   Mismatch, missing record, or "not a repo" ⇒ **fail closed operationally**: it
   warns, audits `worktree.not-isolated`, sets isolation `invalid`, and the
   `tool_call` gate then **blocks every `edit`/`write`/`bash`** (audited) until
   isolation is corrected — a worker that isn't provably inside its worktree
   cannot touch the tree (warn-only would let it keep editing the primary
   checkout). Read-only tools still run. No `CCT_WORKER_ID` ⇒ no-op (a primary or
   interactive session is never a worker).

```sh
# Recommended — one shot: provision AND launch pi inside the worktree.
# Everything before `--` is a `worktree create` flag; everything after `--`
# is passed to the launched pi-code session. It exports the CCT_WORKER_*
# contract and starts pi with cwd = the new worktree.
pi-code worktree run fix-42 --branch fix/issue-42 --areas src/api -- --profile unattended
```

Equivalent manual two-step (provision, then hand off the working directory):

```sh
WT="$(pi-code worktree create fix-42 --branch fix/issue-42 --areas src/api)" || exit 1
(
  cd "$WT" || exit 1
  CCT_WORKER_ID=fix-42 CCT_WORKER_BRANCH=fix/issue-42 \
    pi-code --profile unattended        # pi discovers the project from $PWD
)
```

> The launcher's `--project <dir>` flag also `cd`s into `<dir>` before starting
> pi, so `pi-code --profile unattended --project "$WT"` is equivalent to the
> subshell above — but `worktree run` is preferred because it provisions and
> hands off `cwd` atomically, and sets the `CCT_WORKER_*` env for you.

## The `CCT_WORKER_*` env contract

Set by the spawning driver. **Every value is untrusted** and re-validated by the
manager (`validateCreateRequest`: managed-root containment, protected-branch
refusal, area overlap) before any git side effect.

| Variable | Required | Meaning |
|---|---|---|
| `CCT_WORKER_ID` | yes | Worker id; also the `session_start` isolation gate. Kebab-case, ≤64 chars. |
| `CCT_WORKER_BRANCH` | yes | The worker's branch (never `master`/`main`). |
| `CCT_WORKER_BASE` | no | Branch-off point (branching *off* `master` is fine). |
| `CCT_WORKER_TASKS` | no | Comma/space-separated task ids (recorded). |
| `CCT_WORKER_AREAS` | no | Comma/space-separated owned areas; overlaps between active workers are refused. |
| `CCT_WORKER_PATH` | no | Explicit worktree path; honored but still containment-validated. |
| `CCT_FEATURE_ID` | no | Feature id (recorded). |

**Default path (namespaced by repo)** so two sibling repos with the same
`workerId` never collide:

```
<repo-parent>/.cct-worktrees/<repo-name>/<sanitized-worker-id>
```

## Concurrency — the ledger is lock-serialized

Every ledger mutation (`create`, `cleanup`, and the **entire** `reconcile`
transaction) runs inside a repo-scoped critical section — an atomic
`.cct/worktrees.lock` with bounded retry and a fail-closed timeout. The lock
records its holder's **pid + a unique token**; it is reclaimed only when the
owner is provably not alive (crashed) — a slow-but-live holder's lock is never
stolen — and released only by the process that still owns the token. Two workers
starting at once therefore both land in the ledger, and two conflicting
owned-area requests cannot both win.

## Reconcile is fail-closed and primary-excluded

On `session_start` (and via `/cct:worktree reconcile`) the ledger is reconciled
against live worktrees — but only when the git listing is **trustworthy**. The
manager's tolerant `listWorktrees()` ignores malformed lines, so reconcile uses a
**strict, result-bearing** parse (`listWorktreesStrict`) that rejects truncated
or garbled porcelain:

- The listing must parse cleanly to **exactly one primary** entry. A git failure
  or a malformed/truncated listing ⇒ audit `worktree.reconcile-skipped` and leave
  the ledger **byte-for-byte unchanged** (a git failure never marks live workers
  stale). The whole list→prune→reconcile→save runs inside the lock.
- The **primary is excluded**, so an ordinary repo never produces a false
  "foreign worktree" warning.
- A vanished worker path is marked `stale`; a genuine foreign worktree is
  **reported, never removed**. Live work is never auto-removed.

## Teardown is explicit — Pi has no session-end event (degraded, not a bug)

Pi exposes **no** `session.deleted` / session-end event, so a worktree is torn
down **only** on request:

```sh
/cct:worktree cleanup <workerId>            # requires clean + merged/abandoned
/cct:worktree cleanup <workerId> --force    # waives clean+merge (audited override); never foreign/primary
```

`cleanup` honors the manager's `cleanupEligibility`: it refuses a dirty or
unmerged worktree without `--force`, and **always** refuses a foreign or primary
worktree even with `--force`. This is a deliberate, documented limitation — not a
missing feature. Auto-remove-on-crash is intentionally out of scope (it would
conflict with "never auto-remove live work") and is a separate design decision.

## Audit

Every action emits a `worktree.*` audit record (to `<CCT_HOME>/pi/audit.log`):
`worktree.create`, `worktree.attach`, `worktree.not-isolated`,
`worktree.cleanup`, `worktree.reconcile`, `worktree.reconcile-skipped` — each
with the decision, rule, and `<workerId>:<branch>` subject.
