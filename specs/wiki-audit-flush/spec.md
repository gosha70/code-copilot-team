---
feature_id: wiki-audit-flush
spec_mode: full
status: draft
issue: 37
origin:
  issue: gosha70/code-copilot-team#37
  origin_claim: |
    Audit-trail follow-up to #31. After #31, `wiki ingest` writes audit
    lines to knowledge/wiki/.audit/ingest-log.md but does not itself
    commit. Promote-following workflows commit those lines atomically.
    Reject-only workflows (wiki ingest returns reject, no promote
    follows) leave the line uncommitted; a branch switch or
    `git checkout .` loses it. Add `wiki audit-flush` (or a
    `wiki ingest --commit-pending` flag) that creates a focused commit
    of any uncommitted lines in .audit/ingest-log.md. No content
    changes, no atomicity coupling with promote, no new schema.
    Single-purpose plumbing. Acceptance: command exists;
    `wiki audit-flush --dry-run` reports the pending line count and the
    .audit/ingest-log.md blob SHA without committing; a real run
    produces a commit `audit: flush N pending ingest-log line(s)`; no
    changes to ingest-log content or schema; no coupling with
    `wiki promote` atomicity.
---

# Wiki Audit-Flush — commit pending ingest-log lines

> **Boundary notice.** The wiki-ingest pipeline deliberately runs **no
> git commands** (verified: nothing under `scripts/wiki_ingest/`
> invokes git; `wiki promote`'s "commit" is an atomic *filesystem*
> apply). `wiki audit-flush` is the **single, explicit, user-invoked
> exception**: it is the only pipeline code path that runs
> `git commit`, and it does so only for one file. It must not be
> auto-invoked, scheduled, hooked, or coupled to `promote`.

## Problem

#31 made `knowledge/wiki/.audit/ingest-log.md` a tracked, append-only
NDJSON ledger written by `wiki ingest` on every call. The pipeline
itself never commits; durability rides the existing convention that
someone commits `knowledge/wiki/` changes. For a **promote-following**
workflow that holds: the staged log line is carried into `wiki promote`'s
atomic apply and the human/CI commits it with the wiki change. But a
**reject-only** workflow — `wiki ingest` returns `reject`, no promote
follows — leaves the appended line uncommitted in the working tree. A
`git checkout .`, a branch switch, or a `git stash` discards it, and the
"durable" rejection record is lost. This is OQ2 in
`specs/wiki-audit-trail/spec.md`, resolved as "documented limitation +
this named follow-up."

`wiki audit-flush` closes that gap with one focused command: it commits
exactly the pending tail of `ingest-log.md`, nothing else.

## User Scenarios

1. **Reject, then flush.** A curator runs
   `./scripts/wiki ingest spec.md` (or an agent does). The gate
   rejects; one `disposition:"reject"` line is appended to
   `ingest-log.md`, uncommitted. No promote will follow. The curator
   runs `./scripts/wiki audit-flush`. A commit
   `audit: flush 1 pending ingest-log line` is created containing only
   that file. The rejection survives a later `git checkout .`.

2. **Dry-run before flushing.** `./scripts/wiki audit-flush --dry-run`
   prints `2 pending ingest-log line(s); blob <sha>` and exits 0
   without committing, so the curator can see what would be captured.

3. **Nothing to flush.** With no uncommitted ingest-log lines (or no
   `.audit/ingest-log.md` at all), `./scripts/wiki audit-flush` prints
   `nothing to flush` and exits 0. No commit is created.

4. **Batch of rejects.** Several `wiki ingest` rejects accumulate
   across a session; one `./scripts/wiki audit-flush` commits all
   pending lines in a single `audit: flush N pending ingest-log lines`
   commit.

5. **Divergence refusal.** If the committed `ingest-log.md` is *not* a
   prefix of the working copy (the append-only invariant was violated —
   e.g. a manual rewrite), `audit-flush` refuses with a clear error and
   commits nothing. It never edits or "repairs" the file.

## Interface

### CLI surface

```
./scripts/wiki audit-flush             # commit pending ingest-log lines
./scripts/wiki audit-flush --dry-run   # report count + blob SHA, commit nothing
```

`audit-flush` becomes the fifth verb in the dispatcher
(`ingest|promote|query|lint|audit-flush`).

### Operation contract — `audit-flush`

- **Reads:** `knowledge/wiki/.audit/ingest-log.md` (working tree) and
  its committed blob at `HEAD` (`git show HEAD:<path>`; empty if the
  file is untracked / absent at HEAD).
- **Pending definition:** the file is append-only with a fixed 2-line
  preamble (line 1 = `<!-- ingest-log schema v1 -->`, line 2 empty).
  *Committed content MUST be a byte-exact prefix of the working
  content.* `N` = (count of NDJSON data lines in the working file) −
  (count in the committed file). `N = 0` ⇒ no-op.
- **Well-formedness gate (fail-closed):** before counting/committing,
  the working `ingest-log.md` must be **audit-lint-clean** — it ends
  with a newline (no torn final append) and every data line is a valid
  v1 record per `audit_lint`. If it is malformed (torn final line,
  non-JSON line, schema-invalid record), `audit-flush` **refuses**
  (`AuditFlushError`) and commits nothing. Because the pathspec commit
  captures the whole file's bytes, committing a torn/invalid tail would
  persist an invalid tracked ledger — so a malformed working log is
  never flushed; it is surfaced for repair (e.g. by the next correct
  `wiki ingest` append) instead.
- **Writes (the only git mutation in the pipeline):** when `N > 0`,
  not `--dry-run`, not `diverged`, and not `malformed`, runs
  `git -C <repo_root> commit -m "audit: flush N pending ingest-log
  line(s)" -- knowledge/wiki/.audit/ingest-log.md` — message **before**
  `--`, pathspec **after** (`-m` after `--` is parsed as a pathspec and
  fails); pathspec form commits **only** that file's current content
  and never folds in unrelated staged or working changes. It does
  **not** modify the file, the schema, or any other path. It does
  **not** use `--no-verify` or any index/GIT_DIR override (ordinary
  commit; honors repo hooks).
- **`--dry-run`:** prints `N pending ingest-log line(s); blob <sha>`
  where `<sha>` is `git hash-object <path>` of the working file;
  commits nothing; exit 0.
- **Message grammar:** `audit: flush 1 pending ingest-log line` (N=1)
  / `audit: flush N pending ingest-log lines` (N>1).
- **No coupling:** never invoked by `ingest`/`promote`/`lint`, by a
  hook, or by a scheduler. Independent of promote atomicity.
- **Exit codes:** `0` success or no-op; `11` `AuditFlushError`
  (not a git work tree; append-only invariant violated; working log
  malformed; `git commit` failed). Reuses the existing `errors.py`
  taxonomy — codes 1–6 (`errors.py`), 7 (`EXIT_PATH_OUT_OF_REPO`),
  8 (`EXIT_NOT_IMPLEMENTED`), 9/10 (promote) are taken, so **11** is
  the next free code.

### Python interface

```python
# scripts/wiki_ingest/audit_flush.py — new; the ONLY git-committing module
@dataclass(frozen=True)
class PendingState:
    path: Path            # repo-relative POSIX path to ingest-log.md
    pending: int          # N (>= 0)
    blob_sha: str | None  # git hash-object of the working file (None if absent)
    diverged: bool        # True if committed content is not a prefix of working
    malformed: bool       # True if working log is torn / not audit-lint-clean

def detect_pending(repo_root: Path) -> PendingState: ...
def flush(repo_root: Path, dry_run: bool) -> int:    # returns process exit code

# errors.py — new
class AuditFlushError(IngestError):
    exit_code = 11
```

## Reuse map

| Existing artifact | Use |
|---|---|
| `scripts/wiki_ingest/__main__.py` verb dispatcher (`_VERBS`, `sub.add_parser`, `_do_*`) | add `audit-flush` exactly like the other verbs; add `_do_audit_flush`. |
| `audit_lint.INGEST_LOG_MARKER` + `audit_lint` format validation | reused to skip the 2-line preamble (no duplicated literal) AND to run the fail-closed well-formedness gate on the working log before flushing. |
| `errors.py` exit-code taxonomy | add `AuditFlushError` (exit 11 — next free); reuse `_resolve_repo_root`. |
| `knowledge/wiki/schema/audit-rules.md` | **unchanged** — `audit-flush` adds no schema; it reuses `audit_lint`'s existing v1 validation to gate, never redefines the format. |
| `scripts/wiki_ingest/tests/` (unittest style) | add `test_audit_flush.py`; extend the e2e shell test. |

New: `scripts/wiki_ingest/audit_flush.py` only.

## Design Decisions

**1 — Verb, not a flag.** The issue offers `wiki audit-flush` *or*
`wiki ingest --commit-pending`. Decision: a dedicated **verb**. A flag
on `ingest` would re-enter the ingest argument surface, imply coupling
to an ingest run, and be undiscoverable for "I just want to flush." A
verb is one obvious surface, matches the issue title, and slots into
the existing dispatcher with no behavior change to other verbs.

**2 — Prefix-based pending detection (not a diff parser).** Because
`ingest-log.md` is strictly append-only with a fixed preamble, "pending"
is unambiguous: the committed blob must be a byte prefix of the working
file; pending count = extra NDJSON lines after the preamble. This needs
no diff library and is robust to content (JSON with commas/newlines is
never an issue — we count physical lines after the preamble). If the
prefix check fails, the append-only contract was violated and the tool
**refuses** rather than guessing — it never edits the ledger.

**3 — Pathspec commit, never `git add -A`.**
`git -C <repo_root> commit -m "audit: flush N pending ingest-log
line(s)" -- knowledge/wiki/.audit/ingest-log.md` commits exactly that
file's working state and leaves the user's index and every other file
untouched. **Argument order is load-bearing: `-m <msg>` MUST come
before `--`; anything after `--` is a pathspec, so `git commit --
<path> -m <msg>` fails with `pathspec '-m' did not match` (verified).**
This guarantees a "focused commit" and avoids the classic footgun of
sweeping unrelated changes. No `--no-verify`, no `GIT_INDEX_FILE`/
`GIT_DIR` overrides (explicitly forbidden by repo safety rules) — it is
an ordinary commit.

**4 — No-op is success.** Absent file or `N = 0` prints `nothing to
flush` and exits 0. Flushing is idempotent: a second run immediately
after a successful flush is a no-op. This makes it safe to call
unconditionally at end of a session.

**5 — Independent of promote; still git-free elsewhere.** This is the
sole pipeline command that runs git, by design and in one place
(`audit_flush.py`). `ingest`/`promote`/`lint` remain git-free. No hook,
no scheduler, no auto-invoke — the boundary the pipeline maintains is
preserved; `audit-flush` is the explicit, user-driven exception.

**6 — Detached HEAD / dirty tree tolerated.** A pathspec commit works
on detached HEAD and does not require a clean tree (it ignores other
changes by construction). `audit-flush` proceeds and the commit lands
on the current HEAD; no special-casing, no refusal for unrelated dirty
state.

**7 — Fail-closed on a malformed working log.** The pathspec commit
captures the *entire* file's bytes, so if the working `ingest-log.md`
has a torn final line (a crashed mid-append) or any non-v1 / non-JSON
record, committing would persist an invalid tracked ledger. So before
counting or committing, `detect_pending` runs the existing `audit_lint`
v1 validation over the working log (and checks it ends with a newline);
any failure sets `malformed=True` and `flush` **refuses**
(`AuditFlushError`, exit 11) and commits nothing. The malformed tail is
left in the working tree to be completed/repaired by the next correct
append — `audit-flush` never edits or truncates the ledger to "fix" it.
Rationale: an audit trail that commits known-invalid bytes is worse
than one that loudly refuses.

## Requirements

1. `./scripts/wiki audit-flush` exists as the fifth verb; `--help`
   lists it; the four existing verbs are unchanged.
2. Pending detection is prefix-based; divergence ⇒ `AuditFlushError`
   (exit 11), no commit, file untouched.
3. Malformed working log (torn final line / non-newline-terminated /
   any record failing `audit_lint` v1) ⇒ `AuditFlushError` (exit 11),
   no commit, file untouched (fail-closed — Design Decision 7).
4. `--dry-run` prints `N pending ingest-log line(s); blob <sha>`,
   commits nothing, exit 0 (after the divergence + malformed gates).
5. Real run with `N>0` produces exactly one commit via
   `git commit -m <msg> -- <path>` (message before `--`), message
   `audit: flush N pending ingest-log line(s)` (correct singular/
   plural), containing **only** `knowledge/wiki/.audit/ingest-log.md`.
6. No-op (absent file or `N=0`) prints `nothing to flush`, exit 0,
   no commit.
7. The command never edits `ingest-log.md`, never touches the schema,
   never stages or commits any other path, never uses `--no-verify`
   or index/dir env overrides.
8. Not a git work tree ⇒ `AuditFlushError` (exit 11) with a clear
   message.
9. Stdlib + `git` subprocess only; Bash 3.2 for any shell test.
10. Zero regressions to existing verbs/tests.
11. `bash scripts/validate-spec.sh --feature-id wiki-audit-flush`
    exits 0; one PR fully closes #37 (spec + impl + tests + docs).

## Constraints / What NOT to Build

1. **No `--commit-pending` flag** on `ingest` (Design Decision 1).
2. **No auto-flush** — not from `ingest`, not on session end, not via
   a git hook, not via a scheduler/daemon.
3. **No content mutation / repair** of `ingest-log.md`. On divergence
   *or* a malformed/torn working log, refuse; never rewrite, truncate,
   or "fix" the ledger.
4. **No coupling with `wiki promote`** atomicity or staging.
5. **No new schema; no change to `audit-rules.md`.**
6. **No multi-file scope** — only `knowledge/wiki/.audit/ingest-log.md`.
   The `.audit/proposals/` archive is already committed atomically by
   `promote`; `audit-flush` does not touch it.
7. **No `git push`, no branch creation, no merge** — commit only.
8. **No index/GIT_DIR/`--no-verify` tricks** (repo safety rule).

## Key Entities

- **Pending line** — an NDJSON data line in the working
  `ingest-log.md` after the 2-line preamble that is absent from the
  committed (`HEAD`) blob.
- **`PendingState`** — `(path, pending, blob_sha, diverged,
  malformed)` returned by `detect_pending`.
- **Malformed log** — a working `ingest-log.md` that is not
  newline-terminated or has any record failing `audit_lint` v1; a
  fail-closed refusal condition (Design Decision 7).
- **`AuditFlushError`** — exit 11; raised for non-git-repo,
  append-only divergence, malformed working log, or a failed
  `git commit`.

## Acceptance Criteria

Quoted verbatim from issue #37, mapped 1:1 to tasks in `tasks.md`.

| # | #37 criterion (verbatim) | Tasks |
|---|---|---|
| AC1 | "`wiki audit-flush` command exists." | T2.1, T2.2 |
| AC2 | "`wiki audit-flush --dry-run` reports the pending line count and the `.audit/ingest-log.md` blob SHA without committing." | T1.1, T2.3 |
| AC3 | "A real run produces a commit: `audit: flush N pending ingest-log line(s)`." | T3.1, T3.2 |
| AC4 | "No changes to ingest-log content or schema; no coupling with `wiki promote` atomicity." | T1.1, T3.1, T3.3, T4.2 |

Spec approved when `validate-spec.sh --feature-id wiki-audit-flush`
exits 0 and every AC maps to a concrete task. Feature delivered when,
in one PR (`Closes #37`): all existing tests pass; the new
`test_audit_flush.py` + e2e shell test pass; `lint-wiki.sh` and
`wiki lint --strict` stay clean; the four ACs are demonstrably met.

## Sources

- `issue: gosha70/code-copilot-team#37` — origin.
- `path: specs/wiki-audit-trail/spec.md` — OQ2 (the documented
  limitation this resolves) and the `.audit/ingest-log.md` format.
- `path: scripts/wiki_ingest/audit.py` — `append_ingest_log`, the
  producer of pending lines; `INGEST_LOG_MARKER` preamble shape.
- `path: scripts/wiki_ingest/__main__.py` — verb dispatcher
  (`_VERBS`, subparsers, `_do_*`, `_resolve_repo_root`).
- `path: scripts/wiki_ingest/errors.py` — exit-code taxonomy (8 free).
- `path: knowledge/wiki/schema/audit-rules.md` — append-only +
  preamble contract `audit-flush` relies on (read-only).
