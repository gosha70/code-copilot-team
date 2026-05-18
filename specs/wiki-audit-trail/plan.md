---
spec_mode: full
feature_id: wiki-audit-trail
risk_category: integration
justification: "Adds a tracked audit trail to the wiki-ingest pipeline: wiki ingest gains an append-only ingest-log writer (a narrowed exception to the documented single-writer invariant), wiki promote gains an accepted-proposal archive staged into its existing atomic apply, wiki lint gains an audit-format pass, and a new schema lands in knowledge/wiki/schema/. Touches scripts/wiki_ingest/ (promoter.py, ingestor*.py, __main__.py, new audit.py), knowledge/wiki/scripts/lint-wiki.sh, knowledge/wiki/schema/, README.md. Multi-PR phased delivery, schema-first. Integration risk: breaks an advertised invariant by design and writes inside the atomic promote boundary."
status: draft
date: 2026-05-17
issue: 31
origin:
  issue: gosha70/code-copilot-team#31
  origin_claim: |
    doc_internal/proposals/ is gitignored, so the proposal workspace is
    local-only. Promoted wiki pages keep full traceability via git
    history + the append-only log, but decision history preceding
    promotion is undocumented: rejected proposals lose reasoning and LLM
    drafts on decline; abandoned proposals disappear without trace;
    accepted-then-edited proposals obscure the difference between
    proposal and final acceptance. Solution (A): wiki promote transfers
    accepted proposals (minimally plan.json) into a TRACKED audit path
    such as knowledge/wiki/.audit/proposals/<date>-<slug>.md as an
    atomic operation. Solution (B): wiki ingest appends single-line
    entries to a tracked knowledge/wiki/.audit/ingest-log.md for each
    call, recording timestamp, source path + SHA, backend, gate
    disposition, reason (truncated), target slug, and proposal hash.
    Acceptance: wiki promote writes proposal archives under tracked
    audit paths integrated with atomic commit/rollback; wiki ingest
    appends to the tracked log regardless of gate outcome; ingest log
    schema defined in knowledge/wiki/schema/ and wiki lint validates
    format; README updated to reference the merged feature. Out of
    scope: provenance UI, multi-curator merging, historical backfill.
---

# Implementation Plan — Wiki Audit Trail

> **Invariant notice.** This plan implements a deliberate, user-approved
> narrowing of the "`wiki promote` is the only writer to
> `knowledge/wiki/`" invariant (README "LLM Wiki Maintainer" §;
> `__main__.py` promote help). After this feature: `wiki promote` is the
> only writer to the *canonical wiki content tree*; `wiki ingest` gets
> one append-only exception scoped to
> `knowledge/wiki/.audit/ingest-log.md`. The narrowing is enforced by a
> test (Phase 2), not just documentation.

## Approach

Four phased PRs on the `feat/benchmark-harness` working line's successor
branch (`feat/wiki-audit-trail`), each shipping independently behind the
structural-lint + test-suite + origin-alignment gates. **Schema-first**:
Phase 1 lands the `.audit/` lint exemption, the `audit-rules.md` schema,
and the `wiki lint` audit pass *before* any code writes under `.audit/`.
This is non-negotiable for two reasons: (a) it matches the
wiki-ingest-pipeline schema-first discipline so the implementation
cannot drift from the format; (b) without the lint exemption landing
first, the very first commit that writes a `.audit/*.md` file breaks
`lint-wiki.sh` in CI (its `find` has no dotdir exclusion today).

Phase 2 adds the ingest-log writer (the narrowed-invariant exception,
fail-closed) and the `--check` escape hatch. Phase 3 adds the
accepted-proposal archive *inside* the promoter's existing atomic staged
tree — the smallest code change but the most consequential, because it
writes within the atomic boundary. Phase 4 is docs: README rewording to
reference the merged feature, wiki workflow page, status + alignment
trail.

No phase starts until the previous phase merges. The legacy and existing
ingest/promote/query/lint behaviors are preserved end-to-end; the only
behavioral changes are additive (a new audit line, a new archive
directory, a new lint pass, a new `--check` flag).

## Phased delivery

### Phase 1 — Schema + lint (schema-first; lands first)

**Goal:** make `knowledge/wiki/.audit/` a first-class, lint-exempt,
format-validated location *before* anything writes there.

Strict intra-phase order — 1.1 MUST precede any `.audit/` write:

- **1.1 — `.audit/` excluded from all three wiki readers.** Not just the
  structural linter — every wiki-page enumerator must skip `.audit/` or
  tooling artifacts leak into ingest prompts / health findings:
  - `knowledge/wiki/scripts/lint-wiki.sh`:
    `find "$WIKI_DIR" -type f -name '*.md' -not -path "$WIKI_DIR/schema/*"
    -not -path "$WIKI_DIR/scripts/*"` (≈L34-37) — add
    `-not -path "$WIKI_DIR/.audit/*"`. Without this the first `.audit/`
    write breaks CI immediately.
  - `wiki_state.py::_list_wiki_pages` — `excluded_dirs =
    {"schema","scripts"}` → add `.audit`.
  - `health_lint.py::_list_wiki_pages` — `excluded =
    {"schema","scripts"}` → add `.audit`.
  All three are covered by the Phase 2 invariant test (reader-exclusion
  arm).
- **1.2 — `audit-rules.md` schema.** New
  `knowledge/wiki/schema/audit-rules.md`: the machine-checkable spec of
  the `ingest-log.md` NDJSON format (marker line, fields/types/enums,
  `ts` format, 240-codepoint `reason` rule) and the
  `.audit/proposals/<dir>/` structure, **including the exact
  `proposal_hash` canonicalization recipe verbatim** (spec.md Design
  Decision 3) so the future cross-referential lint can implement it
  identically. Extend `knowledge/wiki/schema/lint-rules.md` with a short
  section: `.audit/` is exempt from page-type/orphan/link rules and is
  governed by `audit-rules.md`.
- **1.3 — `wiki lint` audit pass.** New always-on pass (advisory; gates
  under existing `--strict`) that validates `ingest-log.md` and every
  `.audit/proposals/*/` against `audit-rules.md`. Consumed directly by
  the linter — **not** routed through `load_schema_files` /
  `_SCHEMA_NAMES` (spec.md Reuse map).
- **1.4 — fixtures.** `scripts/wiki_ingest/tests/fixtures/wiki_audit/`:
  one valid `.audit/` tree + six invalid cases (missing marker,
  malformed JSON line, missing required key, bad `disposition` enum,
  `reason` > 240 codepoints, malformed `ts`).

**Acceptance:**
- A populated `knowledge/wiki/.audit/` tree present →
  `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0 (exemption works).
- `./scripts/wiki lint` passes the valid fixture; `--strict` fails each
  of the six invalid fixtures with a specific message.
- `audit-rules.md` contains the `proposal_hash` recipe verbatim.
- Origin alignment exits 0.

**Failure modes considered:** linter `find` portability (BSD vs GNU
`find` `-not -path` — already used in the file, so safe); a future wiki
page legitimately named `.audit*` (none exist; `.audit/` is reserved by
this spec and documented in `lint-rules.md`).

**Rollback story:** Phase 1 is additive and inert (no writer exists
yet). Revert is a clean `git revert` of the PR with zero data
implications — nothing has written to `.audit/`.

### Phase 2 — Ingest-log writer (the narrowed-invariant exception)

**Goal:** `wiki ingest` appends one fail-closed NDJSON line per call;
the single-writer invariant is narrowed and machine-enforced.

- New `scripts/wiki_ingest/audit.py` — the **only** module that writes
  `ingest-log.md`. Contains `append_ingest_log`, `source_sha`,
  `proposal_hash` (the spec.md DD3 recipe), `truncate_reason`
  (240-codepoint, U+2026), `build_log_record` (derives
  `disposition`/`target_paths`/`page_types` from a `WikiPatchSet` or
  `IngestProposal` — Design Decision 9), and the patch-set-oriented
  `IngestLogRecord` dataclass (added to `proposal.py`, imported by
  `audit.py`).
- Hook **`__main__.py` ingest handlers** (`_do_ingest`,
  `_do_ingest_multi`), **not** the ingestor modules: call
  `build_log_record` + `append_ingest_log` **after**
  `write_patch_set_dir`/`_write_proposal_file` has materialized the
  proposal dir and after dry-run body stripping (Design Decision 8 —
  this is what makes `proposal_hash` over the on-disk payload
  computable). Fail-closed — append failure raises and exits non-zero
  (`OutputWriteError`, code 6) before the run can be treated as audited.
  `--check` returns before materialization → never logs.
- `__main__.py`: add `--check` (zero side effects; mutually exclusive
  with `--dry-run`); `--dry-run` keeps existing semantics and now also
  emits the audit line (`proposal_hash: null`, but `disposition`/
  `target_paths`/`page_types` populated from the patch-set).
- Reword README "LLM Wiki Maintainer" § and the `promote` sub-parser
  help: "only writer to the canonical wiki content tree, excluding
  `.audit/`". (The "reference the merged feature" README change is
  Phase 4 / AC4; this is only the invariant wording.)
- Invariant test (`tests/test-wiki-audit.sh` + a Python unit):
  (a) static — no module other than `audit.py` contains a write to
  `ingest-log.md`; no module other than `promoter.py` writes canonical
  content; (b) behavioral — a crafted promote cannot write outside the
  staged tree; (c) reader-exclusion — a planted `.audit/` artifact is
  skipped by `lint-wiki.sh`, `wiki_state._list_wiki_pages`, and
  `health_lint._list_wiki_pages`.

**Acceptance:**
- `./scripts/wiki ingest <fixture> --backend test` appends exactly one
  valid NDJSON line; a second call appends a second; the marker preamble
  is written once on file creation.
- Interrupting ingest mid-append leaves **no** partial line.
- `--check` produces zero filesystem side effects (no proposal dir, no
  audit line, no `.ingest-snapshot/`); exit code reflects accept/reject.
- `--dry-run` writes the line with `proposal_hash: null`.
- The invariant test exits 0; intentionally adding a stray
  `knowledge/wiki/` write elsewhere makes it fail.
- Origin alignment exits 0.

**Failure modes considered:** concurrent `wiki ingest` runs racing on
the append (documented as out of scope — the pipeline is curator-driven,
single-process; a follow-up could add `O_APPEND`+lock if needed);
fail-closed leaving a created-but-empty `ingest-log.md` (mitigated:
marker preamble is written and flushed atomically before the first
record, or not at all).

**Rollback story:** revert the PR. The narrowed-invariant wording
reverts with it. Any `ingest-log.md` already written is harmless tracked
text; no migration needed to roll back (it simply stops growing).

### Phase 3 — Accepted-proposal archive (inside the atomic apply)

**Goal:** `wiki promote` writes the tracked archive atomically with the
wiki content write.

- `wiki ingest` writes an immutable `.ingest-snapshot/` (copy of
  `plan.json` + `preview/`) *inside the gitignored proposal dir* (spec.md
  Design Decision 2). Written from the **`__main__.py` ingest handlers
  immediately after `write_patch_set_dir`/`_write_proposal_file`
  materializes the proposal dir** (same CLI-layer point as the audit
  append — Design Decision 8 — since it copies the just-written
  `plan.json` + `preview/`), not inside the ingestor modules. Not
  written on `--dry-run` (no body) or `--check` (no materialization).
  Gitignored; never tracked.
- New `promoter.py::_stage_audit_archive(stage_dir, proposals_dir,
  patch)` — runs between the `_apply_edit` loop and
  `_validate_staged_tree`; writes `<stage>/.audit/proposals/<name>/`
  with `plan.json` (verbatim) + `proposal.md` (rendered). Deterministic
  `-2`/`-3` suffix on live-tree name collision.
- Extend `_commit_stage_to_wiki`'s planned-write set: it currently
  `rglob`s `*.md` only; extend to also carry `.audit/**/plan.json`,
  `.audit/**/*.md`, and `.audit/ingest-log.md` (so the atomic apply +
  rollback covers them).
- `curator-delta.md`: in `_stage_audit_archive`, diff live proposal
  content vs `.ingest-snapshot/` (`difflib.unified_diff`, 3 lines
  context, repo-relative headers); write the file only when they differ.
- `--dry-run` stages + validates the archive in the temp tree, applies
  nothing.
- New `scripts/wiki_ingest/tests/test-wiki-audit.sh` cases (extends the
  Phase 2 file): archive contents on accept; rollback leaves `.audit/`
  untouched on validation failure; `curator-delta.md` present iff
  hand-edited; collision suffix; idempotency vs `.applied/`.

**Acceptance:**
- A real promote produces `.audit/proposals/<name>/` with `plan.json` +
  `proposal.md`, applied atomically with the page changes.
- A validation failure after staging leaves `knowledge/wiki/` **and**
  `.audit/` byte-for-byte unchanged (no archive for a non-accepted
  proposal).
- Hand-editing a `preview/` file between ingest and promote yields
  `curator-delta.md`; no edit → no `curator-delta.md`.
- Promoting into an existing same-name archive produces `<name>-2`.
- `bash knowledge/wiki/scripts/lint-wiki.sh` still exits 0 with the new
  archive present.
- Origin alignment exits 0.

**Failure modes considered:** `_commit_stage_to_wiki` planned-write
extension accidentally dropping non-`.md` files outside `.audit/`
(mitigated: extension is additive and scoped to `.audit/` globs, with a
test asserting canonical `*.md` writes are unchanged); a proposal dir
lacking `.ingest-snapshot/` (older proposal generated before Phase 2 —
treated as "no delta computable", `curator-delta.md` omitted, logged;
not an error, consistent with backfill-out-of-scope).

**Rollback story:** revert the PR. Already-written archive directories
are inert tracked text; reverting stops new ones from being written. No
schema or invariant change in this phase, so revert is isolated.

### Phase 4 — Docs + status

**Goal:** make the merged feature discoverable and close the README
"(tracked: #31)" loop (AC4).

- README "LLM Wiki Maintainer" §: replace "rejected or abandoned ingest
  attempts are intentionally ephemeral (tracked: #31)" with a sentence
  referencing the merged audit trail (`knowledge/wiki/.audit/`,
  `ingest-log.md`, the accepted-proposal archive).
- Update `knowledge/wiki/workflows/run-wiki-ingest.md` (and add a short
  audit-trail subsection) to describe `.audit/`, `--check`, and the
  curator-delta behavior.
- Add `specs/wiki-audit-trail/IMPLEMENTATION_STATUS.md` (mirror the
  wiki-ingest-pipeline status format) + an origin-alignment trail.
- Confirm `scripts/validate-spec.sh --all` (CI-executed,
  `sync-check.yml` L117) covers `specs/wiki-audit-trail/`; document in
  the status file that `check-origin-alignment.sh` is only `bash -n`
  syntax-checked in CI (L78), not executed — name *execution*-gating it
  a cross-cutting follow-up, explicitly out of #31 scope (it would touch
  every spec, not just this one).

**Acceptance:**
- README no longer contains "(tracked: #31)"; it references the merged
  feature (AC4).
- `lint-wiki.sh` exits 0; `validate-spec.sh --feature-id
  wiki-audit-trail` exits 0; origin alignment exits 0.
- Spec `status` flips `draft` → `approved` after the final alignment
  re-verify.

**Failure modes considered:** wiki workflow page link integrity
(structural lint enforces it); README rewording drifting from actual
behavior (acceptance ties the wording to the shipped `.audit/` paths).

**Rollback story:** docs-only; `git revert` with no functional impact.

## Reuse map

See `spec.md` § "Reuse map" for the per-artifact table. Summary: the
promoter's atomic substrate is reused unmodified except for an additive
planned-write-set extension; the `_archive_proposals_dir` idempotency
pattern is mirrored for collisions; `load_schema_files` is deliberately
**not** touched; `.audit/` is excluded from all three wiki readers
(`lint-wiki.sh` `find` clause + `wiki_state`/`health_lint`
`_list_wiki_pages` exclusion sets); the audit append + `.ingest-snapshot/`
write live in the `__main__.py` CLI layer (post-materialization), not in
the ingestor modules.

## Test strategy

- One new suite, `scripts/wiki_ingest/tests/test-wiki-audit.sh`, grown
  across Phases 1→3 (lint/fixtures → ingest-log/invariant →
  archive/delta/rollback). Fully deterministic under `--backend test`,
  no network.
- Python unit tests for `audit.py` (`source_sha`, `proposal_hash`
  canonicalization vectors, `truncate_reason` codepoint boundary,
  `IngestLogRecord` JSON round-trip).
- All existing `scripts/wiki_ingest/tests/` and repo-level test suites
  continue to pass — zero regressions to ingest/promote/query/lint.
- The single-writer invariant test is part of the suite and is the
  guard for Requirement 5/7.

## Delegation strategy

Single-implementer build. No sub-agent delegation. Build agent
implements one phase per session with `/phase-complete` between phases
(the origin-confirmation breaker fires at each `/phase-complete`).
Phase 1 (schema + lint) is the hard prerequisite and must be merged
before Phase 2 work begins.

## Files to create

**Phase 1:**
- `knowledge/wiki/schema/audit-rules.md`
- `scripts/wiki_ingest/tests/fixtures/wiki_audit/` (valid + 6 invalid)

**Phase 2:**
- `scripts/wiki_ingest/audit.py`
- `scripts/wiki_ingest/tests/test-wiki-audit.sh`

**Phase 3:**
- (no new files; `.ingest-snapshot/` and the archive are runtime
  artifacts, not source)

**Phase 4:**
- `specs/wiki-audit-trail/IMPLEMENTATION_STATUS.md`

## Files to modify

**Phase 1:**
- `knowledge/wiki/scripts/lint-wiki.sh` — `.audit/` `find` exemption
- `scripts/wiki_ingest/wiki_state.py` — add `.audit` to
  `_list_wiki_pages` `excluded_dirs`
- `scripts/wiki_ingest/health_lint.py` — add `.audit` to
  `_list_wiki_pages` `excluded`
- `knowledge/wiki/schema/lint-rules.md` — reference `audit-rules.md`
- `scripts/wiki_ingest/__main__.py` — wire the `wiki lint` audit pass
  (placement kept lint-side; decided at build time)

**Phase 2:**
- `scripts/wiki_ingest/proposal.py` — add `IngestLogRecord`
- `scripts/wiki_ingest/__main__.py` — `build_log_record` +
  fail-closed `append_ingest_log` call in `_do_ingest`/`_do_ingest_multi`
  after proposal-dir materialization; `--check`; `--dry-run` audit line
  (the ingestor modules are **not** modified in Phase 2)
- `README.md` — narrowed-invariant wording (single-writer claim only)

**Phase 3:**
- `scripts/wiki_ingest/promoter.py` — `_stage_audit_archive`; extend
  `_commit_stage_to_wiki` planned-write set; call site in `promote()`
- `scripts/wiki_ingest/__main__.py` — write `.ingest-snapshot/` in the
  ingest handlers right after proposal-dir materialization (same
  CLI-layer point as the Phase 2 audit append; the ingestor modules are
  not modified)

**Phase 4:**
- `README.md` — reference the merged feature (replace "(tracked: #31)")
- `knowledge/wiki/workflows/run-wiki-ingest.md` — audit-trail subsection

## Rollout

Four PRs against `master`, in order:

1. `feat: wiki audit trail Phase 1 — schema + .audit/ lint exemption + lint audit pass`
2. `feat: wiki audit trail Phase 2 — ingest-log writer + --check + narrowed invariant`
3. `feat: wiki audit trail Phase 3 — accepted-proposal archive (atomic)`
4. `docs: wiki audit trail Phase 4 — README/wiki/status + alignment trail`

Each PR description carries its origin-alignment block as the first
section; the breaker fires at every `/phase-complete` and PR review and
must remain aligned for the spec to stay approved through the multi-PR
delivery. Phase 1 is a hard gate: no Phase 2+ commit may write under
`.audit/` until Phase 1 merges.
