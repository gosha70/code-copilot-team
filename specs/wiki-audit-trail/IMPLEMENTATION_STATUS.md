# Wiki Audit Trail — Implementation Status

Snapshot taken on 2026-05-17 at the close of Phase 4. Compare against
`spec.md` § "Acceptance Criteria" and `plan.md` § "Phased delivery"
for the full feature contract.

## Overall

The wiki audit trail (`specs/wiki-audit-trail/`) adds a tracked audit
trail to the wiki-ingest pipeline — two narrow, cheap, tracked
artifacts under `knowledge/wiki/.audit/`:

- **(A) Ingest-log** — `wiki ingest` appends one fail-closed NDJSON
  line per call to `knowledge/wiki/.audit/ingest-log.md`, recording
  timestamp, source SHA, backend, disposition, and reason (≤ 240 cp).
- **(B) Accepted-proposal archive** — `wiki promote` stages
  `knowledge/wiki/.audit/proposals/<date>-<slug>/` inside the existing
  atomic staged tree, atomically with the wiki content write.

The `wiki promote` narrowed-invariant: `wiki promote` is the only
writer to the canonical wiki content tree; `wiki ingest` has one
additional permitted write to `.audit/ingest-log.md` (append-only,
fail-closed).

## Phase 1 — Schema + lint (delivered)

| Capability | Status | Where |
|---|---|---|
| `.audit/` excluded from `lint-wiki.sh` | delivered | `knowledge/wiki/scripts/lint-wiki.sh` `-not -path "$WIKI_DIR/.audit/*"` |
| `.audit/` excluded from `wiki_state._list_wiki_pages` | delivered | `scripts/wiki_ingest/wiki_state.py` `excluded_dirs` |
| `.audit/` excluded from `health_lint._list_wiki_pages` | delivered | `scripts/wiki_ingest/health_lint.py` `excluded` |
| `audit-rules.md` schema (incl. `proposal_hash` recipe) | delivered | `knowledge/wiki/schema/audit-rules.md` |
| `lint-rules.md` reference to `audit-rules.md` | delivered | `knowledge/wiki/schema/lint-rules.md` |
| `wiki lint` audit-format pass | delivered | `scripts/wiki_ingest/audit_lint.py` + wired in `__main__.py::_do_lint` |
| Valid + 6 invalid fixtures | delivered | `scripts/wiki_ingest/tests/fixtures/wiki_audit/` |
| `test_audit_lint.py` (fixture tests + reader-exclusion arm) | delivered | `scripts/wiki_ingest/tests/test_audit_lint.py` |

## Phase 2 — Ingest-log writer (delivered)

| Capability | Status | Where |
|---|---|---|
| `IngestLogRecord` frozen dataclass | delivered | `scripts/wiki_ingest/proposal.py` |
| `audit.py` — `source_sha`, `proposal_hash`, `truncate_reason`, `build_log_record` | delivered | `scripts/wiki_ingest/audit.py` |
| `audit.py` — `append_ingest_log` (fail-closed, marker-prefixed) | delivered | `scripts/wiki_ingest/audit.py` |
| CLI-layer audit hook in `_do_ingest` + `_do_ingest_multi` | delivered | `scripts/wiki_ingest/__main__.py` |
| `--check` flag (gate-only, zero side effects) | delivered | `scripts/wiki_ingest/__main__.py` ingest subparser |
| `--dry-run` emits audit line (`proposal_hash: null`) | delivered | `scripts/wiki_ingest/__main__.py` |
| `--check` / `--dry-run` mutual exclusion | delivered | `__main__.py::_do_ingest` guard |
| Narrowed-invariant wording in README + `promote` help | delivered | `README.md` + `__main__.py` promote subparser help |
| `test_audit.py` (unit tests for audit.py + invariant test + shell exclusion) | delivered | `scripts/wiki_ingest/tests/test_audit.py` |

## Phase 3 — Accepted-proposal archive (delivered)

| Capability | Status | Where |
|---|---|---|
| `.ingest-snapshot/` written at CLI layer after `write_patch_set_dir` | delivered | `scripts/wiki_ingest/__main__.py::_write_ingest_snapshot` |
| `.ingest-snapshot/` not written on `--dry-run` or `--check` | delivered | `__main__.py` ingest handlers |
| `promoter.py::_stage_audit_archive` (plan.json + proposal.md) | delivered | `scripts/wiki_ingest/promoter.py` |
| `curator-delta.md` when snapshot differs from live preview | delivered | `_stage_audit_archive` (difflib.unified_diff, 3-line context) |
| `curator-delta.md` absent when no edit and when no snapshot present | delivered | `_stage_audit_archive` |
| Collision suffix (`-2`, `-3`, …) | delivered | `_stage_audit_archive` while-loop |
| `_commit_stage_to_wiki` extended to carry `.audit/**/plan.json` + `.audit/**/*.md` | delivered | `promoter.py::_commit_stage_to_wiki` (`_collect_plan_json`) |
| Archive staged atomically — rollback on validation failure | delivered | archive inside `with tempfile.TemporaryDirectory` scope |
| `_stage_audit_archive` called in `promote()` between apply loop and validation | delivered | `scripts/wiki_ingest/promoter.py::promote` |

## Phase 4 — Docs + status (delivered)

| Capability | Status | Where |
|---|---|---|
| README: `(tracked: #31)` sentence replaced with merged-feature description | delivered | `README.md` "LLM Wiki Maintainer" § |
| `run-wiki-ingest.md` audit-trail subsection | delivered | `knowledge/wiki/workflows/run-wiki-ingest.md` |
| `IMPLEMENTATION_STATUS.md` (this file) | delivered | `specs/wiki-audit-trail/IMPLEMENTATION_STATUS.md` |

## Acceptance criteria mapping

| # | Issue #31 criterion | Tasks | Status |
|---|---|---|---|
| AC1 | `wiki promote` writes proposal archives under tracked audit paths integrated with atomic commit/rollback | T3.2, T3.3, T3.4, T3.5 | delivered |
| AC2 | `wiki ingest` appends to the tracked log regardless of gate outcome | T2.2, T2.3 | delivered |
| AC3 | Ingest log schema defined in `knowledge/wiki/schema/`; `wiki lint` validates format | T1.2, T1.3 | delivered |
| AC4 | README updated to reference the merged feature | T4.1 | delivered |

## CI coverage note

`sync-check.yml` executes `scripts/validate-spec.sh --all` (L117),
which covers `specs/wiki-audit-trail/`. The
`scripts/check-origin-alignment.sh` script is only `bash -n`
syntax-checked in CI (L78) — it is not executed as part of the PR gate.
Execution-gating it would be a cross-cutting change affecting every
spec, and is explicitly out of #31 scope. It is named here as a
cross-cutting follow-up.

## Named follow-ups (out of #31 scope)

- [`gosha70/code-copilot-team#37`](https://github.com/gosha70/code-copilot-team/issues/37)
  — `wiki audit-flush`: commits pending `.audit/ingest-log.md` lines
  for reject-only workflows that never promote.
- Cross-referential audit lint: verifies `source_sha` resolves to a
  real object and `proposal_hash` matches an existing archive. Deferred
  per Design Decisions 3 and 4.
- "Ingested-but-never-promoted" detector: cross-referential lint flag
  for an `accept` ingest-log line with no matching archive directory.
