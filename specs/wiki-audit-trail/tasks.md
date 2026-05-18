# Tasks — Wiki Audit Trail

Phased delivery. Each task is bounded and independently verifiable —
one focused change, mappable 1:1 to a commit/PR. Phases ship in order
(Phase N+1 starts only after Phase N merges). **Phase 1 is a hard gate:
no Phase 2+ task may write under `knowledge/wiki/.audit/` until Phase 1
has merged** (schema-first; the lint exemption must exist first or CI
breaks on the first `.audit/` write).

Acceptance-criteria → task mapping (verbatim ACs are in `spec.md`
§ "Acceptance Criteria"):
AC1 → T3.2, T3.3, T3.4, T3.5 · AC2 → T2.2, T2.3 ·
AC3 → T1.2, T1.3 · AC4 → T4.1

## Phase 1 — Schema + lint (schema-first; lands first)

### T1.1 — `.audit/` excluded from all three wiki readers
- **Output:** `.audit/` excluded from every wiki-page enumerator:
  (a) `knowledge/wiki/scripts/lint-wiki.sh` `find` gains
  `-not -path "$WIKI_DIR/.audit/*"`; (b)
  `wiki_state.py::_list_wiki_pages` adds `.audit` to `excluded_dirs
  = {"schema","scripts"}`; (c) `health_lint.py::_list_wiki_pages` adds
  `.audit` to `excluded = {"schema","scripts"}`.
- **Done when:** a hand-placed
  `knowledge/wiki/.audit/proposals/x/foo.md` with no wiki frontmatter
  does **not** make `lint-wiki.sh` fail and is **not** returned by
  either `_list_wiki_pages`; removing any of the three exclusions makes
  the corresponding check observe the file (proves each is load-
  bearing). Must land before any other `.audit/` write.

### T1.2 — `audit-rules.md` schema + `lint-rules.md` reference  *(AC3)*
- **Output:** new `knowledge/wiki/schema/audit-rules.md` specifying the
  `ingest-log.md` NDJSON format (marker line; every field name/type/enum
  from `spec.md` § Interface; `ts` format; 240-codepoint `reason` rule)
  and the `.audit/proposals/<dir>/` structure, with the
  `proposal_hash` canonicalization recipe quoted **verbatim** from
  `spec.md` Design Decision 3. `lint-rules.md` gains a short section:
  `.audit/` is exempt from page/orphan/link rules, governed by
  `audit-rules.md`.
- **Done when:** `audit-rules.md` exists; `lint-rules.md` references it;
  `lint-wiki.sh` exits 0 (schema files are themselves exempt).

### T1.3 — `wiki lint` audit-format pass  *(AC3)*
- **Output:** an always-on lint pass (advisory; non-zero under existing
  `--strict`) that validates `ingest-log.md` (marker present+exact;
  each line parses as JSON; required keys/types/enums; `ts` ISO-8601
  UTC; `len(reason) ≤ 240` codepoints) and each `.audit/proposals/*/`
  (has valid `plan.json` + `proposal.md`; optional `curator-delta.md`;
  no unexpected entries). Consumed directly by the linter — **not**
  via `load_schema_files`/`_SCHEMA_NAMES`.
- **Done when:** `./scripts/wiki lint` passes a valid `.audit/`;
  `--strict` exits non-zero on a malformed one with a specific message;
  format-only (it does not check `source_sha`/`proposal_hash`
  resolution).

### T1.4 — audit fixtures + committed test
- **Output:** `scripts/wiki_ingest/tests/fixtures/wiki_audit/` — one
  valid `.audit/` tree + six invalid: missing marker, malformed JSON
  line, missing required key, bad `disposition` enum, `reason` > 240
  codepoints, malformed `ts`. Plus a committed test
  `scripts/wiki_ingest/tests/test_audit_lint.py` that runs all seven
  fixtures, the nested-constraint edge cases (`v != 1`, non-string
  array items, stray top-level `.audit/` entry, `plan.json`-as-dir),
  and the **Python reader-exclusion arm** (`wiki_state._list_wiki_pages`
  + `health_lint._list_wiki_pages` skip a planted `.audit/` artifact).
  The `lint-wiki.sh` shell arm and the promoter behavioral arm of the
  invariant test remain in Phase 2 (T2.5).
- **Done when:** the committed test is green in `pytest
  scripts/wiki_ingest/tests/`; T1.3's pass classifies the valid fixture
  clean and each invalid fixture as its expected failure; CI discovers
  the test (not a manual-only check).

### T1.5 — Phase 1 verification + PR
- **Done when:** `lint-wiki.sh` exits 0 with a populated `.audit/`
  present; `validate-spec.sh --feature-id wiki-audit-trail` exits 0;
  origin-alignment exits 0; PR reviewed and merged.

## Phase 2 — Ingest-log writer (narrowed-invariant exception)

### T2.1 — `audit.py` helpers + patch-set-oriented `IngestLogRecord`
- **Output:** `scripts/wiki_ingest/audit.py` with `source_sha(file)`,
  `proposal_hash(dir)` (the `spec.md` DD3 canonicalization recipe
  exactly), `truncate_reason(s)` (240 codepoints, U+2026, newline
  collapse), and `build_log_record(...)` which derives the
  patch-set-oriented record (Design Decision 9) from either a
  `WikiPatchSet` (`disposition` = accept iff `edits` non-empty;
  `reason` = `rationale`; `target_paths`/`page_types` over all edits) or
  an `IngestProposal` (legacy: direct `disposition`/`reason`, one-element
  `target_paths`), plus `source_repo_relative`; the patch-set-oriented
  `IngestLogRecord` dataclass (fields per `spec.md` § Python interface)
  in `proposal.py`.
- **Done when:** unit tests cover known `source_sha` vectors, a
  `proposal_hash` vector matching `audit-rules.md`'s worked example, the
  240/239+`…` codepoint boundary, `IngestLogRecord` JSON round-trip, and
  `build_log_record` for: multi-page accept (≥2 paths/types), multi-page
  reject (empty `edits` → `disposition:"reject"`, `[]`, hash `null`),
  legacy single-source, and an `--allow-out-of-repo` source
  (`source_repo_relative:false`, path verbatim).

### T2.2 — `append_ingest_log` (fail-closed, marker-prefixed)  *(AC2)*
- **Output:** `audit.append_ingest_log(repo_root, record)` in
  `audit.py` — creates `knowledge/wiki/.audit/ingest-log.md` with the
  `<!-- ingest-log schema v1 -->` marker + blank line on first use,
  then appends exactly one NDJSON line; flushes; fail-closed (raises →
  exit `OutputWriteError`/6 on any write failure).
- **Done when:** first call creates marker + one line; subsequent calls
  append one line each; a simulated write failure exits non-zero and
  leaves no partial line; `audit.py` is the only module containing a
  write to `ingest-log.md`.

### T2.3 — CLI-layer audit hook + `--check` / `--dry-run`  *(AC2)*
- **Output:** the `__main__.py` ingest handlers (`_do_ingest`,
  `_do_ingest_multi`) call `build_log_record` + `append_ingest_log`
  **after** `write_patch_set_dir`/`_write_proposal_file` materializes
  the proposal dir and after dry-run body stripping (Design Decision 8 —
  so `proposal_hash` over the on-disk payload is computable). The
  ingestor modules are **not** modified. New `--check` (gate only; zero
  side effects; mutually exclusive with `--dry-run`); `--dry-run` keeps
  existing semantics and also writes the audit line (`proposal_hash:
  null`, but `disposition`/`target_paths`/`page_types` populated).
- **Done when:** `./scripts/wiki ingest <fixture> --backend test`
  appends one valid line for both accept and reject (multi-page)
  fixtures; the line's `proposal_hash` matches `proposal_hash()` over
  the materialized dir on accept; `--check` writes nothing (no proposal
  dir, no line, no snapshot) and exits accept/reject; `--dry-run` writes
  a line with `proposal_hash: null`; `--check --dry-run` is rejected;
  `git grep` shows no `append_ingest_log` call in `ingestor*.py`.

### T2.4 — narrowed-invariant rewording (wording only)
- **Output:** README "LLM Wiki Maintainer" § single-writer sentence and
  the `__main__.py` `promote` sub-parser help change to "only writer to
  the canonical wiki content tree, excluding `.audit/`". (The
  merged-feature README sentence is T4.1.)
- **Done when:** both strings updated; `lint-wiki.sh` exits 0; no other
  README content changed.

### T2.5 — invariant + reader-exclusion test
- **Output:** in `scripts/wiki_ingest/tests/test-wiki-audit.sh` (+ a
  Python unit): (a) static — no module but `audit.py` writes
  `ingest-log.md`; no module but `promoter.py` writes canonical
  content; (b) behavioral — a crafted promote cannot write outside the
  staged tree; (c) the **`lint-wiki.sh` shell** reader-exclusion arm
  (a planted `.audit/` artifact is skipped). The Python
  reader-exclusion arm (`wiki_state`/`health_lint`) already landed in
  Phase 1 (`test_audit_lint.py`); this task adds the shell arm and the
  write-surface arms (a)/(b).
- **Done when:** test exits 0; deliberately adding a stray
  `knowledge/wiki/` write in another module makes (a)/(b) fail;
  removing the `lint-wiki.sh` `.audit/` clause makes (c) fail.

### T2.6 — Phase 2 verification + PR
- **Done when:** all suites green; interrupted ingest leaves no partial
  line; origin-alignment exits 0; PR reviewed and merged.

## Phase 3 — Accepted-proposal archive (atomic)

### T3.1 — `.ingest-snapshot/` written at the CLI layer
- **Output:** the `__main__.py` ingest handlers write an immutable
  `.ingest-snapshot/` (copy of `plan.json` + `preview/`) inside the
  gitignored proposal dir, **immediately after**
  `write_patch_set_dir`/`_write_proposal_file` materializes it (same
  CLI-layer point as the T2.3 audit append — Design Decision 8). The
  ingestor modules are **not** modified. Not written on `--dry-run`
  (no body) or `--check` (no materialization).
- **Done when:** a normal ingest produces `.ingest-snapshot/` matching
  the just-materialized `plan.json` + `preview/`; it stays gitignored
  (under `/doc_internal`); `git grep` shows no snapshot write in
  `ingestor*.py`.

### T3.2 — `_stage_audit_archive` (plan.json + proposal.md)  *(AC1)*
- **Output:** `promoter.py::_stage_audit_archive(stage_dir,
  proposals_dir, patch)` writing
  `<stage>/.audit/proposals/<proposals_dir.name>/` with `plan.json`
  (verbatim copy) + `proposal.md` (rendered: patch-set rationale, then
  per `PageEdit` path/action/rationale, then proposed body); called in
  `promote()` between the `_apply_edit` loop and
  `_validate_staged_tree`.
- **Done when:** a real promote yields the archive dir with both files;
  `_validate_staged_tree` passes with it present (proves T1.1
  exemption); `--dry-run` stages it in temp and applies nothing.

### T3.3 — extend `_commit_stage_to_wiki` planned-write set  *(AC1)*
- **Output:** `_commit_stage_to_wiki` (currently `rglob("*.md")` only)
  also carries `.audit/**/plan.json`, `.audit/**/*.md`, and
  `.audit/ingest-log.md` into the atomic plan-then-apply-with-rollback.
- **Done when:** the archive lands iff the promote lands; a forced
  validation failure after staging leaves `knowledge/wiki/` **and**
  `.audit/` byte-for-byte unchanged; a test asserts canonical `*.md`
  writes are unchanged by the extension.

### T3.4 — `curator-delta.md` (diff iff edited)  *(AC1)*
- **Output:** in `_stage_audit_archive`, diff live proposal content vs
  `.ingest-snapshot/` (`difflib.unified_diff`, 3 lines context,
  repo-relative headers); write
  `.audit/proposals/<name>/curator-delta.md` only when they differ.
  A proposal dir lacking `.ingest-snapshot/` → omit (logged, not an
  error).
- **Done when:** hand-editing a `preview/` file between ingest and
  promote yields `curator-delta.md`; no edit → file absent.

### T3.5 — collision suffix + idempotency  *(AC1)*
- **Output:** if `knowledge/wiki/.audit/proposals/<name>/` already
  exists in the live tree, the new archive dir is `<name>-2`, `-3`, …
  (mirrors `_archive_proposals_dir`); promoting an already-applied
  `.applied/` dir stays a no-op.
- **Done when:** two promotes of same-date-same-slug proposals yield
  `<name>` and `<name>-2`; re-promote of an `.applied/` dir is a no-op.

### T3.6 — Phase 3 tests
- **Output:** `test-wiki-audit.sh` cases for T3.2–T3.5 (archive
  contents, rollback untouched, delta present/absent, collision,
  idempotency).
- **Done when:** all assertions pass under `--backend test`;
  `lint-wiki.sh` still exits 0 with the archive present.

### T3.7 — Phase 3 verification + PR
- **Done when:** all suites green; origin-alignment exits 0; PR
  reviewed and merged.

## Phase 4 — Docs + status

### T4.1 — README references the merged feature  *(AC4)*
- **Output:** README "LLM Wiki Maintainer" § — replace "rejected or
  abandoned ingest attempts are intentionally ephemeral (tracked: #31)"
  with a sentence describing the merged audit trail
  (`knowledge/wiki/.audit/`, `ingest-log.md`, the accepted-proposal
  archive, the abandon-detection follow-up).
- **Done when:** README contains no "(tracked: #31)"; it references the
  shipped `.audit/` paths; `lint-wiki.sh` exits 0.

### T4.2 — wiki workflow page audit subsection
- **Output:** `knowledge/wiki/workflows/run-wiki-ingest.md` gains an
  audit-trail subsection: `.audit/` layout, `--check` vs `--dry-run`,
  curator-delta behavior, the format-only-lint note.
- **Done when:** structural lint (incl. link integrity) exits 0; the
  subsection states the `--check`/`--dry-run` distinction explicitly.

### T4.3 — `IMPLEMENTATION_STATUS.md` + origin-alignment trail
- **Output:** `specs/wiki-audit-trail/IMPLEMENTATION_STATUS.md`
  (wiki-ingest-pipeline status format: per-phase capability/status/where
  table + alignment trail). Documents that CI executes
  `validate-spec.sh --all` (covers this spec) but only `bash -n`
  syntax-checks `check-origin-alignment.sh`; names execution-gating it a
  cross-cutting follow-up out of #31 scope.
- **Done when:** file exists in the status format; `validate-spec.sh
  --feature-id wiki-audit-trail` exits 0.

### T4.4 — Phase 4 verification + final PR
- **Output:** final PR with the alignment block first; spec `status`
  `draft` → `approved` after the final alignment re-verify.
- **Done when:** all suites green; origin-alignment exits 0 with the
  final verdict; PR reviewed and merged; all four ACs satisfied and
  mapped tasks complete.
