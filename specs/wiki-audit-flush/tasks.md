# Tasks — Wiki Audit-Flush (#37)

One PR (`Closes #37`). Tasks are commit-ordered units **inside that
single PR**, not separate PRs. Each is one focused, independently
verifiable change. The only git-mutating task (T3.1) lands last, on a
fully-tested pure core.

AC → task map (verbatim ACs in `spec.md` § Acceptance Criteria):
AC1 → T2.1, T2.2 · AC2 → T1.1, T2.3 · AC3 → T3.1, T3.2 ·
AC4 → T1.1, T3.1, T4.2

## Phase 1 — Pending-detection core (pure; no git mutation)

### T1.1 — `audit_flush.detect_pending` + `PendingState`
- **Output:** new `scripts/wiki_ingest/audit_flush.py` with frozen
  `PendingState(path, pending, blob_sha, diverged, malformed)` and
  `detect_pending(repo_root)`. Committed blob via
  `git show HEAD:knowledge/wiki/.audit/ingest-log.md` (absent/untracked
  ⇒ empty). Working bytes read raw. Preamble skipped via
  `audit_lint.INGEST_LOG_MARKER` (no duplicated literal). Byte-prefix
  check ⇒ `diverged`; `malformed` = working file not
  newline-terminated OR `audit_lint` v1 validation of the working log
  returns any error; `pending` = working data-line count − committed
  data-line count; `blob_sha` via `git hash-object` (None if absent).
- **Done when:** unit test matrix passes — absent (0, None, not
  diverged, not malformed); untracked (all lines pending); +N appended
  (pending N); identical (0); preamble-only (0); committed-not-a-prefix
  (diverged True); torn final line / non-newline-terminated /
  schema-invalid record (malformed True). No filesystem/git writes
  occur (verified).

### T1.2 — `errors.AuditFlushError` (exit 11)
- **Output:** `AuditFlushError(IngestError)` with `exit_code = 11` in
  `scripts/wiki_ingest/errors.py`. Codes 1–10 are taken (1–6 errors.py;
  7 `EXIT_PATH_OUT_OF_REPO`; 8 `EXIT_NOT_IMPLEMENTED`; 9/10 promote),
  so 11 is the next free code.
- **Done when:** importable; `exit_code == 11`; no existing code maps
  to 11.

## Phase 2 — CLI verb wiring (`--dry-run` end-to-end usable)

### T2.1 — register the `audit-flush` verb
- **Output:** add `"audit-flush"` to `_VERBS`; `sub.add_parser
  ("audit-flush", help=...)`; legacy-prefix shim unaffected.
- **Done when:** `./scripts/wiki --help` lists
  `ingest|promote|query|lint|audit-flush`; the four existing verbs’
  help text is byte-unchanged.

### T2.2 — `_do_audit_flush` handler skeleton
- **Output:** `_do_audit_flush(args)` resolves repo root
  (`_resolve_repo_root`), calls `detect_pending`, maps
  `AuditFlushError` → exit 11, not-a-git-repo → `AuditFlushError`.
- **Done when:** invoking the verb dispatches to the handler; a
  non-git directory yields exit 11 with a clear message; no commit
  path reachable yet.

### T2.3 — `--dry-run` reporting
- **Output:** `--dry-run` flag; prints
  `N pending ingest-log line(s); blob <sha>` (or `nothing to flush`
  when N=0/absent); exit 0; commits nothing.
- **Done when:** with N appended uncommitted lines,
  `./scripts/wiki audit-flush --dry-run` prints the exact line incl.
  the `git hash-object` sha and exits 0; no new commit in `git log`;
  divergence OR malformed ⇒ exit 11, no output of a false count.

## Phase 3 — Commit action (only git mutation; lands last)

### T3.1 — `flush()` pathspec commit
- **Output:** `audit_flush.flush(repo_root, dry_run)`: when
  `not dry_run and pending>0 and not diverged and not malformed`, run
  `git -C <root> commit -m "audit: flush N pending ingest-log line(s)"
  -- knowledge/wiki/.audit/ingest-log.md` — `-m <msg>` **before** `--`
  (after `--` git treats `-m` as a pathspec and fails:
  `pathspec '-m' did not match`, verified); singular at N=1. No
  `git add -A`, no `--no-verify`, no index/GIT_DIR override, never
  edits the file. `pending==0` ⇒ `nothing to flush`, exit 0.
- **Done when:** the commit’s `git show --stat` lists **only**
  `knowledge/wiki/.audit/ingest-log.md`; message exact incl. plurality;
  ledger bytes unchanged by the operation; a `git commit` failure ⇒
  exit 11 with the file uncommitted and untouched.

### T3.2 — idempotency + isolation
- **Output:** behavior guarantees: a second run immediately after a
  successful flush is a no-op (exit 0, no commit); an unrelated
  modified/staged file is excluded from the audit-flush commit.
- **Done when:** tests assert both (second-run no-op; a dirty sibling
  file is absent from the commit diff and remains modified afterward).

### T3.3 — fail-closed on divergence / malformed
- **Output:** `flush` (and `--dry-run`) refuse with `AuditFlushError`
  (exit 11) and commit nothing when `diverged` (committed not a prefix)
  OR `malformed` (torn final line / not newline-terminated / any
  record failing `audit_lint` v1). The ledger is never rewritten,
  truncated, or "repaired".
- **Done when:** tests assert: a divergent log ⇒ exit 11, no commit,
  bytes unchanged; a torn-tail / schema-invalid log ⇒ exit 11, no
  commit, bytes unchanged; a valid log after the bad tail is repaired
  by a correct append flushes normally.

## Phase 4 — Tests + docs

### T4.1 — `test_audit_flush.py`
- **Output:** unittest module using per-test temp `git init` repos:
  full detection matrix (T1.1), flush exact-message single-file commit,
  no-op, divergence refusal, pathspec isolation, detached HEAD.
- **Done when:** `PYTHONPATH=scripts python3 -m unittest discover -s
  scripts/wiki_ingest/tests` is green including the new module; no
  test touches the real repo or network.

### T4.2 — e2e shell round-trip
- **Output:** extend `tests/test-wiki-ingest.sh` (or a sibling): real
  `./scripts/wiki ingest <fixture> --backend test` reject →
  `audit-flush --dry-run` reports N+blob → `audit-flush` →
  `git log -1 --name-only` shows only ingest-log.md + exact message →
  second run `nothing to flush`. Clean up any `.audit/` created.
- **Done when:** the suite passes with the new assertions; tree clean
  afterward (no stray `.audit/`).

### T4.3 — README + IMPLEMENTATION_STATUS
- **Output:** README LLM Wiki Maintainer section: change the
  "pending follow-up #37" phrasing to state `wiki audit-flush` ships
  and resolves the reject-only durability gap. Add
  `specs/wiki-audit-flush/IMPLEMENTATION_STATUS.md` (wiki-audit-trail
  status format).
- **Done when:** README no longer calls #37 "pending";
  `lint-wiki.sh` 0 violations; `validate-spec.sh --feature-id
  wiki-audit-flush` exits 0.

### T4.4 — PR + close #37
- **Output:** single PR `feat(wiki): wiki audit-flush — commit pending
  ingest-log lines (Closes #37)`; body maps AC1–AC4 to tasks, states
  the boundary (sole git-mutating verb, no coupling/auto-invoke).
- **Done when:** all suites green, CI green, PR merged, #37 auto-closed.
