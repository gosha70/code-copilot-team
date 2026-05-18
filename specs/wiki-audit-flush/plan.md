---
spec_mode: full
feature_id: wiki-audit-flush
risk_category: integration
justification: "Introduces the FIRST git-mutating code path into a wiki-ingest pipeline that deliberately runs no git. New verb wiki audit-flush + new module audit_flush.py + a new errors.py exit code; touches __main__.py dispatcher. Integration risk (git history mutation, focused-commit isolation) despite small size — full SDD. One PR fully closes #37."
status: draft
date: 2026-05-18
issue: 37
origin:
  issue: gosha70/code-copilot-team#37
  origin_claim: |
    Audit-trail follow-up to #31: add `wiki audit-flush` to commit
    pending uncommitted lines in knowledge/wiki/.audit/ingest-log.md
    for reject-only workflows that never promote. --dry-run reports
    count + blob SHA; real run commits "audit: flush N pending
    ingest-log line(s)". No content/schema change, no promote coupling.
    The named successor to OQ2 in specs/wiki-audit-trail/spec.md.
---

# Implementation Plan — Wiki Audit-Flush

> **One PR.** #37 is small and single-purpose. Per the governance rule
> (a merged PR must fully close its issue), the entire feature — spec
> bundle + implementation + tests + docs — ships in **one PR titled
> with `Closes #37`**. The phases below are *commit-ordered units
> within that single PR*, not separate PRs. Dependency ordering
> (detection before CLI before the git-mutating commit before docs) is
> preserved inside the PR's commit sequence.

## Approach

Build inside-out so the git-mutating step lands last and on top of a
fully-tested pure core:

1. **Pure detection core** (`audit_flush.detect_pending`) — no git
   mutation; only `git show HEAD:<path>` + `git hash-object` reads.
   Fully unit-tested against a temp git repo.
2. **CLI verb wiring** — `audit-flush` subparser, `_VERBS`,
   `_do_audit_flush`, `--dry-run`, `AuditFlushError` (exit 11).
   `--dry-run` is end-to-end usable after this step (it never commits).
3. **Commit action** — the single `git commit -m <msg> -- <path>`
   pathspec call (message before `--`), message pluralization, no-op +
   divergence + malformed handling. The only step that mutates git; it
   sits on the verified core.
4. **Tests + docs** — unit + e2e shell, README/IMPLEMENTATION_STATUS.

No phase writes to `ingest-log.md` or the schema. The only new external
behavior is one focused commit, introduced last.

## Phased delivery (commit-ordered units in ONE PR)

### Phase 1 — Pending-detection core

**Goal:** a pure, tested `detect_pending(repo_root) -> PendingState`
with zero git mutation.

- New `scripts/wiki_ingest/audit_flush.py`: `PendingState` dataclass +
  `detect_pending`. Committed blob via
  `git show HEAD:knowledge/wiki/.audit/ingest-log.md` (treat non-zero /
  "exists on disk but not in HEAD" as empty committed). Working bytes
  read directly. Strip the 2-line preamble using
  `audit_lint.INGEST_LOG_MARKER` (no duplicated literal). Prefix check
  (committed bytes must be a prefix of working bytes) → `diverged`.
  `malformed` = working file not newline-terminated OR `audit_lint`
  v1 validation of the working log returns any error. `pending` =
  working data-line count − committed data-line count. `blob_sha` via
  `git hash-object <path>` (None if file absent). `PendingState`
  carries `(path, pending, blob_sha, diverged, malformed)`.
- `errors.AuditFlushError(IngestError)` with `exit_code = 11` (codes
  1–10 are taken: 1–6 errors.py, 7 path-out-of-repo, 8 not-implemented,
  9/10 promote).

**Acceptance:** unit tests cover absent file (pending 0, blob None),
untracked file (all data lines pending), N appended lines (pending N),
identical (pending 0), divergence (diverged True), preamble-only
(pending 0), malformed: torn final line / non-newline-terminated /
schema-invalid record (malformed True). No git writes performed.

**Failure modes considered:** not a git repo (`git show` fails) →
surfaced as `AuditFlushError` at the CLI layer (Phase 2), not inside
the pure function which returns a typed signal; CRLF/encoding — compare
raw bytes, not decoded text; empty file vs missing file distinguished.

**Rollback story:** new file + new error class only; revert is deletion,
no behavior change to any existing verb.

### Phase 2 — CLI verb wiring (`--dry-run` usable)

**Goal:** `./scripts/wiki audit-flush [--dry-run]` dispatches; dry-run
fully works (no commit anywhere yet).

- `__main__.py`: add `audit-flush` to `_VERBS`; `sub.add_parser
  ("audit-flush", ...)` with `--dry-run`; `_do_audit_flush(args)` that
  resolves repo root, calls `detect_pending`, and for `--dry-run` (or
  always, this phase) prints `N pending ingest-log line(s); blob <sha>`
  or `nothing to flush`; maps `AuditFlushError` → exit 11;
  not-a-git-repo → `AuditFlushError`.

**Acceptance:** `./scripts/wiki --help` lists five verbs; `audit-flush
--dry-run` prints the count + blob line and exits 0; divergence OR
malformed → exit 11 + clear message + no commit; the four existing
verbs’ help/behaviour byte-unchanged.

**Failure modes considered:** arg parsing collisions with existing
verbs (none — additive); `_resolve_repo_root` reuse; ensure dry-run
path cannot reach any commit code (guard before Phase 3 lands).

**Rollback story:** dispatcher addition is additive; removing the
subparser + `_VERBS` entry fully reverts.

### Phase 3 — Commit action (the only git mutation)

**Goal:** real run creates exactly one focused commit.

- `audit_flush.flush(repo_root, dry_run)`: when `not dry_run` and
  `pending > 0` and not `diverged` and not `malformed`: run
  `git -C <repo_root> commit -m "audit: flush N pending ingest-log
  line(s)" -- knowledge/wiki/.audit/ingest-log.md` (message **before**
  `--`; `-m` after `--` is parsed as a pathspec and fails — verified;
  singular for N==1). Capture failure → `AuditFlushError`.
  `pending == 0` → print `nothing to flush`, exit 0, no commit.
  `diverged` OR `malformed` → `AuditFlushError` (exit 11), no commit,
  file untouched. Never `git add -A`, never `--no-verify`, never edit
  the file.

**Acceptance:** after `wiki ingest` reject(s) leave N uncommitted
lines, `wiki audit-flush` creates one commit whose message is exactly
`audit: flush N pending ingest-log line(s)` (correct plurality) and
whose diff is **only** `knowledge/wiki/.audit/ingest-log.md`; a second
immediate run is a no-op (exit 0); an unrelated dirty file is NOT in
the commit.

**Failure modes considered:** other staged changes (pathspec commit
isolates the file — asserted by a test); detached HEAD (commit still
lands — tested); commit hook/identity failure → `AuditFlushError` exit
11, file untouched; **partial/torn line at EOF or any schema-invalid
record → `malformed` → fail-closed refusal (exit 11), no commit, file
untouched** (a pathspec commit would otherwise persist the invalid tail
since it captures whole-file bytes — Design Decision 7); argv order
(`-m` must precede `--`).

**Rollback story:** the commit step is the last commit in the PR;
reverting that commit restores Phase 1+2 (dry-run-only) behavior with
no data loss (it never edits the ledger).

### Phase 4 — Tests + docs

**Goal:** committed coverage + discoverability.

- `scripts/wiki_ingest/tests/test_audit_flush.py` (unittest, temp git
  repo): detection matrix (Phase 1 acceptance), flush creates the
  exact-message single-file commit, no-op, divergence refusal,
  pathspec isolation (unrelated dirty file excluded), detached HEAD.
- Extend the e2e shell test (`tests/test-wiki-ingest.sh` or a sibling):
  `wiki ingest --backend test` reject → `audit-flush --dry-run` reports
  N + blob → real `audit-flush` → `git log -1 --name-only` shows only
  ingest-log.md with the exact message → second run `nothing to flush`.
- README: one sentence under the LLM Wiki Maintainer section pointing
  at `wiki audit-flush` as the resolution of the reject-only durability
  gap (replaces the "pending follow-up #37" phrasing with "shipped").
- `specs/wiki-audit-flush/IMPLEMENTATION_STATUS.md` (mirror the
  wiki-audit-trail status format).

**Acceptance:** full unittest discovery green; e2e shell green;
`lint-wiki.sh` 0; `wiki lint --strict` clean; `validate-spec.sh
--feature-id wiki-audit-flush` 2 passed; README no longer calls #37
"pending".

**Failure modes considered:** test repo isolation (each test its own
tempdir + `git init`, never the real repo); deterministic (no network,
`--backend test`); clean up any `.audit/` created by e2e.

**Rollback story:** docs/tests-only; revert is isolated.

## Reuse map

See `spec.md` § "Reuse map". Summary: additive verb in the existing
dispatcher; `INGEST_LOG_MARKER` reused (no literal duplication); one
new error code (8); `audit-rules.md` untouched; one new module.

## Test strategy

- Unit (`test_audit_flush.py`): pure detection matrix + flush behavior
  in throwaway `git init` repos; assert commit message, single-file
  diff, no-op idempotency, divergence refusal, pathspec isolation.
- E2E shell: real `./scripts/wiki ingest --backend test` → reject →
  `audit-flush` round-trip, asserting `git log` shape.
- Regression: existing `scripts/wiki_ingest/tests/` +
  `tests/test-wiki-ingest.sh` unchanged-green.
- No live-provider/network tests.

## Delegation strategy

Single-implementer build. The pure core (Phase 1) lands and is tested
before the git-mutating step (Phase 3) is written — the git mutation is
the smallest, last, most-reviewed change.

## Files to create

- `scripts/wiki_ingest/audit_flush.py`
- `scripts/wiki_ingest/tests/test_audit_flush.py`
- `specs/wiki-audit-flush/IMPLEMENTATION_STATUS.md`

## Files to modify

- `scripts/wiki_ingest/__main__.py` — `_VERBS`, `audit-flush`
  subparser, `_do_audit_flush`
- `scripts/wiki_ingest/errors.py` — `AuditFlushError` (exit 11)
- `README.md` — #37 "shipped" sentence
- e2e shell test (extend `tests/test-wiki-ingest.sh` or add a sibling)

## Rollout

**One PR** against `master`, branch `feat/wiki-audit-flush`, title:
`feat(wiki): wiki audit-flush — commit pending ingest-log lines (Closes #37)`.
Commit sequence inside the PR follows Phases 1→4 so the git-mutating
step is the last, smallest, most-isolated commit. PR body maps the four
ACs to the tasks and states the boundary (sole git-mutating verb,
no coupling, no auto-invoke).
