# T7.3 Design Read — Worktree manager (FR-013)

Status: **design read — approval needed on the capability status + state schema
+ the enforceable/declared split before implementing.** T7.3 is P0. Unlike T7.1
(schema) and T7.2 (child-session over an unverified-then-verified pi surface),
`git worktree` is a **real, fully verifiable CLI** — so the enforceable line sits
much closer to fully-enforced, and the real design work is the *safety* and
*state* model, not "does the primitive exist."

## FR-013 (verbatim)

> Worktree isolation for parallel workers: worker, branch, worktree, tasks,
> owned areas, verification/merge/cleanup state tracked.

Note the emphasis: **state tracked.** T7.3 owns the isolation primitive + the
tracked state + safe lifecycle. It does **not** run verification (T7.4) or
execute merges (T8) — it tracks their status.

## What exists today (ground truth)

- **No git-worktree management code anywhere.** T7.3 builds it. But git worktree
  is a real CLI, and this repo already runs in worktrees (Agent `isolation:
  "worktree"`, the statusline shows `wt:<name>`).
- **Dirty-check idiom** (`review-round-runner.sh`, `auto-build-loop.sh`):
  `git status --porcelain | grep -Ev '^[?][?] \.cct/'` → clean iff empty
  (untracked `.cct/` is ignored). Reuse verbatim.
- **State-file pattern** (`workflow/checkpoint.ts`, T9.1): `.cct/<name>.json`,
  versioned, strings sanitized (single line, control-chars stripped, bounded)
  because persisted state can become model-visible; trust discipline applies.
  Mirror it.
- **Git safety today is convention, not a runtime gate.** `protect-git.sh` is a
  two-approval gate for commit/push only; **force/reset/branch-delete are not
  mechanically blocked.** So T7.3 must itself *never issue* those and must
  *refuse* to when asked — the safety lives in the manager's own logic.
- **Worktrees share a repo root** (`session_analytics`: project-key = repo
  toplevel). The manager anchors every worker worktree under the primary repo.

## Mechanism (low-risk, recommend without a separate decision)

Shell out to `git worktree add|list|remove|prune` via `spawnSync` (the
`review.ts` pattern), with a pure planning/validation core around it. Because git
is available in CI, the git-exec layer is **tested against a real throwaway git
repo** — the enforcement is genuinely verified, not mocked (contrast T7.2's mock
`pi`).

Split, mirroring T7.2:
- **pure core** (`agents/worktree.ts` planners): validate a create request,
  detect ownership conflicts, decide cleanup eligibility, reconcile ledger vs
  `git worktree list`. No spawn.
- **thin git-exec layer**: `createWorktree` / `removeWorktree` / `listWorktrees`
  / `pruneWorktrees` — each a guarded `git` call.
- **ledger I/O**: `.cct/worktrees.json`, versioned + sanitized.

## State schema — `.cct/worktrees.json` (needs approval)

```ts
export const WORKTREE_LEDGER_VERSION = 1;

export type VerificationStatus = "pending" | "passed" | "failed";
export type MergeStatus = "unmerged" | "merged" | "abandoned";
export type CleanupStatus = "active" | "cleaned" | "stale";

export interface WorkerRecord {
  workerId: string;        // unique, kebab (reuses the manifest name rule)
  branch: string;          // the worker's branch — NEVER master/main
  worktreePath: string;    // absolute path, under the repo's parent
  featureId: string | null;// task/feature id
  tasks: string[];         // task ids assigned to the worker
  ownedAreas: string[];    // path prefixes/globs the worker may touch
  verificationStatus: VerificationStatus; // TRACKED (run by T7.4)
  mergeStatus: MergeStatus;                // TRACKED (executed by T8)
  cleanupStatus: CleanupStatus;
  createdAt: string;       // ISO
  origin: "cct";           // provenance marker — only "cct" records are cleanable
}

export interface WorktreeLedger {
  version: number;
  workers: WorkerRecord[];
}
```
The `origin: "cct"` marker is the linchpin of the no-delete-user-worktrees
guarantee (below): the manager only ever removes worktrees it created and
recorded.

## Enforceable vs declared (T7.3)

| FR-013 element | T7.3 status | How |
|----------------|-------------|-----|
| isolated worktree, own branch off a base | **enforced** | `git worktree add <path> -b <branch> <base>` |
| never on master/main | **enforced** | refuse a create whose branch ∈ {master, main} or whose base would be checked out as the worktree branch |
| worker/branch/path/feature/tasks tracked | **enforced** | the ledger |
| owned areas declared | **enforced** | recorded per worker |
| ownership **conflict detection** (overlap) | **enforced** | pre-assignment overlap check across active workers |
| **write-time** ownership enforcement (a worker only writes its area) | **degraded / tracked** | not T7.3 — belongs to the permission engine / a future write hook; reported, not enforced |
| verification status | **tracked** | field set by the verify runner (T7.4), not run here |
| merge status | **tracked** | field set when the lead merges (T8), not executed here |
| safe cleanup (CCT-created, clean, merged/abandoned) | **enforced** | guarded `git worktree remove` |
| never delete user/foreign worktrees | **enforced** | only `origin:"cct"` ledger records are removable; a path not in the ledger is refused |
| dirty-worktree refusal | **enforced** | the dirty-check idiom before remove |
| stale recovery | **enforced** | `git worktree prune` + ledger↔`worktree list` reconcile |
| force / reset / branch force-delete | **refused** | the manager never issues them; a remove of a dirty/unmerged worktree requires an explicit, audited override |

**Honesty statement:** T7.3 fully enforces worktree **isolation**, safe
**lifecycle** (create/track/cleanup/stale-recovery), and ownership **conflict
detection** — all against the real `git worktree` CLI. What it does **not**
enforce: **write-time** ownership (a different layer), and it **tracks but does
not execute** verification (T7.4) or merges (T8). It never issues
force/reset/branch-force-delete and never touches a worktree it did not create.

## Safety guarantees (hard rules the manager encodes)

1. **No master/main writes.** Refuse to create a worker branch named master/main;
   never check master/main out into a worker worktree; never remove the primary
   worktree.
2. **No force / no reset.** The manager never runs `git reset --hard`,
   `git worktree remove --force` on a dirty tree, or `git branch -D` on unmerged
   work. A dirty/unmerged removal needs an explicit override flag and is audited.
3. **No deleting user worktrees.** Only `origin:"cct"` ledger records are
   removable. A worktree present on disk but **not** in the ledger is *foreign*
   and never auto-removed — only reported.
4. **Dirty-worktree handling.** Cleanup refuses a worktree with uncommitted
   changes (dirty-check idiom) unless explicitly forced.
5. **Stale recovery.** Reconcile the ledger with `git worktree list`: a ledger
   record whose dir is gone → `stale` (prunable); a live worktree missing from
   the ledger → foreign (reported, never touched).

## Ownership model

- Each worker declares `ownedAreas: string[]` — repo-relative path prefixes (or
  simple globs). Normalized (strip `./`, dedupe) like the T5.2 importer.
- **Conflict = overlap** between two *active* workers: prefix A contains prefix
  B, or vice-versa, or an equal prefix. `detectOwnershipConflicts(ledger)`
  returns the overlapping pairs. Assigning an overlapping area is **refused**
  (or flagged, per approval).
- This is a *pre-assignment* check (enforceable). Enforcing that a worker only
  *wrote* inside its area at commit time is the permission layer's job → degraded
  here, reported not enforced.

## Verification / merge boundary (what T7.3 tracks vs T7.4/T8 executes)

- **T7.3 tracks** `verificationStatus` + `mergeStatus` as ledger fields and
  exposes setters. It provides the isolated worktree the verify runner and the
  lead operate in.
- **T7.4 executes** verification (reusing the FR-016 verify runner) inside a
  worker worktree and sets `verificationStatus`; it also does analytics
  correlation + partial-failure handling.
- **T8 executes** the lead merge/integration and sets `mergeStatus`.
- T7.3 ships no verify run and no merge — only the state + the safe surface.

## Cleanup rules

- **Explicit cleanup is the default** (`cleanupWorker(workerId, {force?})`).
  Preconditions for a non-forced removal, ALL required:
  1. the record exists and is `origin:"cct"`;
  2. its worktree is **clean** (dirty-check idiom);
  3. `mergeStatus` ∈ {`merged`, `abandoned`} (never remove `unmerged` work);
  4. it is **not** the primary worktree.
  On success → `git worktree remove` + mark `cleanupStatus:"cleaned"`.
  `force:true` waives (2)+(3) only, is audited, and still cannot touch a foreign
  or primary worktree.
- **Automatic cleanup is limited to reconciliation**: `git worktree prune` for
  already-gone dirs + marking vanished ledger records `stale`. **No automatic
  removal of a live worktree** — removal of real work is always explicit.

## Scope (in / out)

**In:** `agents/worktree.ts` — ledger schema + pure planners
(`validateCreateRequest`, `detectOwnershipConflicts`, `cleanupEligibility`,
`reconcile`) + thin git-exec (`createWorktree`/`removeWorktree`/`listWorktrees`/
`pruneWorktrees`) + `.cct/worktrees.json` I/O (versioned, sanitized); one
capability entry across the four capability files; tests against a **real temp
git repo** (create → track → conflict → dirty-refuse → cleanup → stale-reconcile
→ foreign-worktree-refused); design doc. `node --test --test-concurrency=1`.

**Out (→ later):** running verification (T7.4); executing merges (T8); write-time
ownership enforcement (permission layer); the team task-ledger / assignment /
claiming (T8.1 — related but distinct); live `/cct:` command wiring (thin
follow-up once the manager + safety are proven).

## Open questions for approval

1. **Capability status for a new `agents.worktrees` id — `enabled` or
   `degraded`?** The case for **enabled**: FR-013 asks for isolation + *state
   tracked*, and T7.3 fully delivers both against a real git CLI — there is no
   *platform* limitation (contrast sandbox/MCP, which are degraded because Pi
   genuinely can't do the thing). The case for **degraded**: write-time
   ownership is not enforced and verification/merge are tracked-not-executed, so
   a reader might over-read "enabled" as "parallel workers are fully
   guard-railed." **My lean: `degraded`**, reason spelling out isolation +
   lifecycle + conflict-detection enforced vs write-time-ownership /
   verification-exec / merge-exec out — the conservative, consistent-with-the-
   project call. Happy to go `enabled` with the same reason if you prefer.
2. **State schema above** — confirm the `WorkerRecord` fields (esp. the
   `origin:"cct"` provenance marker as the no-delete-user-worktrees linchpin).
3. **Ownership overlap on assignment — refuse vs flag?** My lean: **refuse**
   (return a conflict error; the caller must pick non-overlapping areas),
   consistent with fail-closed. Flag-only would let overlapping workers coexist.
