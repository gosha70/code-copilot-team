# Wiki Audit-Flush — Implementation Status

Snapshot taken on 2026-05-17 at the close of Phase 4. Compare against
`spec.md` § "Acceptance Criteria" and `plan.md` § "Phased delivery"
for the full feature contract.

## Overall

`wiki audit-flush` closes the reject-only durability gap identified as
OQ2 in `specs/wiki-audit-trail/spec.md`. After a `wiki ingest` reject
(where no `wiki promote` follows), the appended `ingest-log.md` line
was uncommitted and could be lost on branch switch or `git checkout .`.
`wiki audit-flush` creates a focused `git commit` of exactly
`knowledge/wiki/.audit/ingest-log.md` — nothing else — making the
rejection record durable.

Key design points:
- **Sole git-mutating command** in the pipeline — `ingest`, `promote`,
  `lint`, and `query` remain git-free.
- **Never auto-invoked** — user-driven only; no hook, no scheduler.
- **Fail-closed gates** — divergence (append-only invariant violated)
  or malformed working log (torn final line, non-v1 record) refuse with
  exit 11; the ledger is never edited or truncated.
- **Pathspec isolation** — `git add -- <path>` + `git commit -m <msg>
  -- <path>` commits only `ingest-log.md`, leaving other staged or
  working changes untouched.

## Phase 1 — Pending-detection core (delivered)

| Capability | Status | Where |
|---|---|---|
| `PendingState` frozen dataclass | delivered | `scripts/wiki_ingest/audit_flush.py` |
| `detect_pending(repo_root)` | delivered | `scripts/wiki_ingest/audit_flush.py` |
| Committed blob via `git show HEAD:<path>` (absent ⇒ empty) | delivered | `audit_flush.detect_pending` |
| Byte-prefix divergence check | delivered | `audit_flush.detect_pending` |
| `malformed` = not newline-terminated OR audit_lint v1 errors | delivered | `audit_flush.detect_pending` |
| `pending` = working data lines − committed data lines | delivered | `audit_flush.detect_pending` |
| `blob_sha` via `git hash-object` (None if absent) | delivered | `audit_flush.detect_pending` |
| `AuditFlushError(IngestError)` exit 11 | delivered | `scripts/wiki_ingest/errors.py` |

## Phase 2 — CLI verb wiring (delivered)

| Capability | Status | Where |
|---|---|---|
| `"audit-flush"` in `_VERBS` | delivered | `scripts/wiki_ingest/__main__.py` |
| `audit-flush` subparser with `--dry-run` | delivered | `scripts/wiki_ingest/__main__.py::_build_arg_parser` |
| `_do_audit_flush(args)` handler | delivered | `scripts/wiki_ingest/__main__.py` |
| Not-a-git-repo → `AuditFlushError` exit 11 | delivered | `audit_flush.detect_pending` |
| `--dry-run` prints `N pending ingest-log line(s); blob <sha>` | delivered | `audit_flush.flush` |
| `--dry-run` exits 0, no commit | delivered | `audit_flush.flush` |
| Description + epilog updated (five verbs; exit code 11 documented) | delivered | `scripts/wiki_ingest/__main__.py::_build_arg_parser` |

## Phase 3 — Commit action (delivered)

| Capability | Status | Where |
|---|---|---|
| `flush(repo_root, dry_run)` | delivered | `scripts/wiki_ingest/audit_flush.py` |
| `git add -- <path>` before commit (handles untracked first-flush) | delivered | `audit_flush.flush` |
| `git -C <root> commit -m <msg> -- <path>` (`-m` before `--`) | delivered | `audit_flush.flush` |
| Singular message `audit: flush 1 pending ingest-log line` | delivered | `audit_flush.flush` |
| Plural message `audit: flush N pending ingest-log lines` (N>1) | delivered | `audit_flush.flush` |
| Pending==0 or absent ⇒ `nothing to flush`, exit 0, no commit | delivered | `audit_flush.flush` |
| Diverged ⇒ `AuditFlushError` exit 11, no commit, bytes unchanged | delivered | `audit_flush.flush` |
| Malformed ⇒ `AuditFlushError` exit 11, no commit, bytes unchanged | delivered | `audit_flush.flush` |
| git commit failure ⇒ `AuditFlushError` exit 11 | delivered | `audit_flush.flush` |
| Detached HEAD tolerated | delivered | `audit_flush.flush` (pathspec commit works) |
| Unrelated dirty/staged files excluded from commit | delivered | pathspec `-- <path>` on commit |
| Second run is no-op (exit 0) | delivered | `detect_pending` returns pending=0 after flush |

## Phase 4 — Tests + docs (delivered)

| Capability | Status | Where |
|---|---|---|
| `test_audit_flush.py` (detect_pending matrix, flush behavior) | delivered | `scripts/wiki_ingest/tests/test_audit_flush.py` |
| E2e shell round-trip (Section 5 of test-wiki-ingest.sh) | delivered | `tests/test-wiki-ingest.sh` |
| README "Four operations" → "Five operations" + `audit-flush` CLI | delivered | `README.md` "LLM Wiki Maintainer" § |
| README #37 "pending follow-up" → "shipped" | delivered | `README.md` "LLM Wiki Maintainer" § |
| `IMPLEMENTATION_STATUS.md` (this file) | delivered | `specs/wiki-audit-flush/IMPLEMENTATION_STATUS.md` |

## Acceptance criteria mapping

| # | Issue #37 criterion (verbatim) | Tasks | Status |
|---|---|---|---|
| AC1 | "`wiki audit-flush` command exists." | T2.1, T2.2 | delivered |
| AC2 | "`wiki audit-flush --dry-run` reports the pending line count and the `.audit/ingest-log.md` blob SHA without committing." | T1.1, T2.3 | delivered |
| AC3 | "A real run produces a commit: `audit: flush N pending ingest-log line(s)`." | T3.1, T3.2 | delivered |
| AC4 | "No changes to ingest-log content or schema; no coupling with `wiki promote` atomicity." | T1.1, T3.1, T3.3, T4.2 | delivered |

## Design deviation note

The spec states "No `git add -A`". The implementation uses `git add --
<single-path>` before the pathspec commit to handle the first-flush case
where `ingest-log.md` is untracked. This is explicitly distinct from
`git add -A` (which stages all changes) and does not violate the
isolation guarantee: the subsequent `git commit -m <msg> --
<single-path>` restricts the commit to that one file even if other paths
are staged. This is verified by the `test_unrelated_dirty_file_excluded`
and `test_commit_contains_only_ingest_log` unit tests and the e2e
isolation assertion.
