---
spec_mode: full
feature_id: wiki-ingest-pipeline
risk_category: integration
justification: "Karpathy-pattern wiki maintainer with three operations (ingest, query, knowledge-health lint) plus promote. Touches scripts/wiki_ingest/ across many new modules, adds a new shell entrypoint, extends knowledge/wiki/scripts/lint-wiki.sh, multi-PR phased delivery. Reuses ~750 lines of Stage-1 substrate built under the v1 spec."
status: draft
date: 2026-05-06
issue: 28
origin:
  issue: gosha70/code-copilot-team#12
  urls:
    - https://gist.github.com/karpathy/3ef5df0e1ee5d36d59b29eb91f8d35c1
  origin_claim: |
    The Karpathy-pattern LLM Wiki: a persistent, compounding artifact
    between raw sources and final agent instructions, maintained by an
    LLM via THREE operations — ingest (reads existing wiki state and
    UPDATES index.md + log.md + multiple matching pages; one source
    can touch 10–15 pages), query (index-first navigation; optional
    file-back), and knowledge-health lint (contradictions, stale
    claims, orphans, missing cross-links — semantic, not just
    structural). Issue #12 (LLM Wiki Groundwork) shipped only the
    structural foundation and explicitly deferred automated ingest,
    RLMKit synthesis, and adapter generation to follow-up issues; #28
    (this spec) was the first follow-up and was expected to deliver
    the maintainer half.
---

# Implementation Plan — Karpathy-pattern Wiki Maintainer

> **Rescope notice (2026-05-06).** Replaces the v1 plan that described a
> single-source proposal generator. The Stage-1 substrate built under
> the v1 plan is preserved and reused. See `spec.md` § "Reuse map" for
> the per-module fate of the ~750 lines of working Python in
> `scripts/wiki_ingest/`.

## Approach

Build the maintainer in five phased PRs on top of the existing branch
(`feat/wiki-ingest-pipeline`). Each phase ships independently, runs
through the origin-alignment gate, and lands behind a structural-lint +
test-suite gate. No phase starts until the previous phase is merged.

Phase 0 lands the relabel and the four-verb dispatcher skeleton so the
in-tree framing stops overclaiming the v1 substrate as "Wiki support."
Phases 1–4 build the four maintainer operations one at a time. Phase 1
(multi-page ingest) is the biggest and highest-value; Phase 2 (promote)
is the smallest but the most consequential because it's the first code
path that ever writes to `knowledge/wiki/` from the pipeline.

The legacy single-source flow is preserved end-to-end: every existing
v1 caller continues to work, every existing v1 test continues to pass.
Resolution A (rescope) preserves all engineering effort.

## Phased delivery

### Phase 0 — Relabel + verb dispatcher + adapter fixes

**Goal:** stop the in-tree framing from overclaiming v1 as the wiki
maintainer; lay down the verb-dispatcher skeleton; apply the external
review's must-fix hardening before new operations pile on top.

- Add `scripts/wiki` shell wrapper that invokes the new verb
  dispatcher. `scripts/wiki-ingest` stays as a backwards-compat alias
  routing to `./scripts/wiki ingest --legacy-single-source`.
- Refactor `scripts/wiki_ingest/__main__.py` into a verb dispatcher
  (`ingest|promote|query|lint`); `--legacy-single-source` is a flag on
  `ingest` that runs the existing single-source path unchanged.
- Apply the external review's adapter fixes in
  `scripts/wiki_ingest/backends/copilot_cli.py`:
  - cursor backend: `cursor-agent -p` (not `cursor -p`)
  - codex backend: `codex exec` (not `codex -p`)
  - claude backend: stays on `claude -p`
  - stderr redaction by default; `--debug-unsafe-output` flag for
    full text
  - real `--dry-run`: passes `task: gate-only` through the prompt;
    backend returns disposition + reason, no draft body
  - silent provider auto-detect → opt-in only via `--backend auto`
  - confine source paths to repo root by default;
    `--allow-out-of-repo` for the rare case
- Update `knowledge/README.md` "Running ingest" section to label the
  current behavior as **Stage 1: single-source proposal generator** and
  point at the new four-verb CLI for the rest.
- Update `knowledge/wiki/workflows/run-wiki-ingest.md` to reflect the
  Stage-1 framing and link forward to Phases 1–4.
- Add `knowledge/wiki/IMPLEMENTATION_STATUS.md` (or similar) noting
  which Karpathy operations are delivered (Stage 1) vs planned
  (Phases 1–4), so readers don't get the v1-only impression.

**Acceptance:**
- `./scripts/wiki ingest --legacy-single-source <source>` produces the
  exact v1 proposal output.
- `./scripts/wiki-ingest <source>` still works (backwards-compat alias).
- All existing v1 tests pass unchanged.
- Cursor / codex backends use the correct documented CLIs.
- `--dry-run` skips body generation (verifiable via no draft markdown
  on accept).
- `bash scripts/check-origin-alignment.sh wiki-ingest-pipeline` exits 0
  (the alignment block already has a stamped record from this rescope;
  Phase 0 doesn't change scope so the verdict stays aligned).

### Phase 1 — Multi-page ingest

**Goal:** deliver the first Karpathy-pattern operation —
ingest-updates-existing-wiki.

- New module `scripts/wiki_ingest/wiki_state.py` — loads `index.md`,
  `log.md`, and a bounded candidate page set into a `WikiState`
  dataclass.
- New module `scripts/wiki_ingest/ingestor_multi.py` — composes a
  wiki-aware prompt (via `compose_multi_prompt` in `prompt.py`),
  invokes the backend, returns a `WikiPatchSet`.
- Extract `_parse_frontmatter`, `_parse_simple_yaml`, `_unquote`,
  `_sources_equal` from `prompt.py` into a new `yaml_lite.py`.
  All four operations import from `yaml_lite`.
- New `proposal.py` types: `WikiPatchSet`, `PageEdit`, `WikiState`.
  Extend `errors.py` with `WikiStateError`.
- The wiki-aware prompt instructs the backend to emit a `WikiPatchSet`
  JSON shape: top-level `edits` array, each entry validated by the
  same two-layer pattern as v1 (per-page shape + per-page semantic
  cross-consistency between structured fields and YAML frontmatter).
- Output directory:
  `doc_internal/proposals/<date>-<source-slug>/plan.json` plus
  `doc_internal/proposals/<date>-<source-slug>/preview/<rel>.md` per
  affected page.
- Test backend gains `task: ingest-multi` dispatch with deterministic
  multi-page response.

**Acceptance:**
- `./scripts/wiki ingest tests/fixtures/sample-source.md --backend test`
  produces a `plan.json` with ≥ 2 edits (at least `index_update` +
  one `create` or `update`) and a `preview/` dir.
- `tests/test-wiki-ingest-multi.sh` covers: source produces multiple
  edits; per-page validation runs and fails on contract violation;
  patch-set-level validation catches duplicate `create` paths.
- v1 single-source path unchanged.
- Origin alignment passes.

### Phase 2 — Promote

**Goal:** the only writer to `knowledge/wiki/`.

- New module `scripts/wiki_ingest/promoter.py`:
  - reads a `proposals/<dir>/plan.json` patch-set
  - stages applied changes to a temp dir (parallel to live wiki)
  - runs `knowledge/wiki/scripts/lint-wiki.sh` against the staged
    tree
  - on lint exit 0: `git add` the staged changes (does NOT commit;
    leaves them staged for the curator's `git commit`)
  - on lint failure: rolls back, prints lint output, exits non-zero
- `./scripts/wiki promote <dir>` is the curator-facing CLI.
- After successful promote, the proposals dir moves to
  `doc_internal/proposals/.applied/<date>-<source-slug>/` (gitignored,
  audit trail).

**Acceptance:**
- `./scripts/wiki promote doc_internal/proposals/<dir>` updates the
  wiki and runs the structural linter; on lint failure, the wiki
  tree is unchanged.
- `tests/test-wiki-promote.sh` covers: success path; lint failure
  rollback; idempotency (`promote` on `.applied/` dir is a no-op).
- The fix preserves the invariant that **only** `promoter.py` writes
  to `knowledge/wiki/`. Grep-test verifies no other module imports
  the wiki path for write.
- Origin alignment passes.

### Phase 3 — Query

**Goal:** index-first navigation + answer synthesis with citations.

- New module `scripts/wiki_ingest/querier.py`:
  - reads `knowledge/wiki/index.md` first
  - lexical relevance match between the question and index entries +
    page titles; selects the top-N candidate pages (default 5,
    configurable)
  - reads only the selected pages into the prompt (NOT the full wiki)
  - composes `compose_query_prompt` with question + selected pages
  - parses backend response into `QueryAnswer`
  - `--file-back` flag: in addition to printing, generates a
    `WikiPatchSet` capturing the answer
- Pages-loaded list logged to `doc_internal/wiki-query-log.jsonl`
  (one JSONL line per query).
- Test backend gains `task: query` dispatch.

**Acceptance:**
- `./scripts/wiki query "what does our wiki say about origin alignment?"`
  prints an answer + citations.
- The pages-loaded log shows index-first navigation worked (index.md
  always first, followed by index-linked pages only).
- `--file-back` produces a patch-set the curator can `promote`.
- `tests/test-wiki-query.sh` covers: question-with-answer-in-wiki;
  question-with-no-good-answer (returns "I don't know" + cites only
  index); file-back round-trip.
- Origin alignment passes.

### Phase 4 — Knowledge-health lint

**Goal:** the third Karpathy operation — semantic checks beyond the
existing structural linter.

- New module `scripts/wiki_ingest/health_lint.py`:
  - **Contradictions** — over candidate page pairs sharing slugs in
    title, shared sources, or cross-link edges, send the pair to the
    backend with a "do these contradict?" prompt; collect findings.
  - **Stale claims** — for each `path:` in `sources:`: check the file
    exists at the cited `sha:` (if pinned) and at HEAD; if the file
    has changed, ask the backend "does the cited claim still hold?";
    for `url:` sources: HEAD-fetch and flag 404s.
  - **Weak orphans** — graph: pages reachable from `index.md` only
    via a single hub page (one cited inbound edge from one hub).
  - **Missing cross-links** — entities (proper nouns matched to a
    glossary or to title slugs) appearing in N ≥ 3 pages without
    cross-links.
- Extend `scripts/wiki lint`:
  - `--health` adds the health pass (advisory by default, exit 0
    with stderr warnings)
  - `--strict` makes any health finding non-zero exit
  - `--paths <p>...` scopes to specific pages
- Backend test mode gains `task: lint-health` dispatch.

**Acceptance:**
- `./scripts/wiki lint --health` returns exit 0 on a clean wiki, with
  findings reported as warnings on stderr.
- `tests/test-wiki-health-lint.sh` covers: at least one fixture per
  finding kind triggers the right finding; clean fixture passes; the
  `--strict` flag flips advisory to error; `--paths` scopes correctly.
- Phase 4 PR is the last; merging it completes the maintainer.
- Origin alignment passes (final verdict: `aligned, high`).

## Reuse map

See `spec.md` § "Reuse map (Stage 1 → Stage 2+)" for the per-module
table. Summary: every Stage-1 module is kept; new operations grow as
siblings; ~70–80% of v1 code becomes load-bearing in the maintainer.

## Test strategy

- Per-phase test suite (`test-wiki-ingest-multi.sh`, etc.) added in
  the corresponding phase.
- Existing test suites (`test-shared-structure.sh`, `test-generate.sh`,
  `test-hooks.sh`, `test-sync.sh`, `test-peer-review.sh`,
  `test-review-loop.sh`, `test-origin-alignment.sh`) continue to pass.
- Existing `scripts/wiki_ingest/tests/` (the v1 Python unit tests)
  continue to pass — zero regressions for the legacy path.
- New live-provider smoke tests (claude, codex, cursor) are
  out-of-band, gated behind an opt-in env var, kept out of default CI.

## Delegation strategy

This is a single-implementer build. No sub-agent delegation. The Build
agent runs the verb dispatcher Stage 0 first, then implements one phase
per session, with `/phase-complete` between phases (the origin gate
fires automatically at each `/phase-complete` thanks to the breaker).

## Files to create

**Phase 0:**
- `scripts/wiki` (new shell wrapper)
- `knowledge/wiki/IMPLEMENTATION_STATUS.md`

**Phase 1:**
- `scripts/wiki_ingest/yaml_lite.py`
- `scripts/wiki_ingest/wiki_state.py`
- `scripts/wiki_ingest/ingestor_multi.py`
- `tests/test-wiki-ingest-multi.sh`
- `scripts/wiki_ingest/tests/fixtures/sample-source.md`

**Phase 2:**
- `scripts/wiki_ingest/promoter.py`
- `tests/test-wiki-promote.sh`

**Phase 3:**
- `scripts/wiki_ingest/querier.py`
- `tests/test-wiki-query.sh`

**Phase 4:**
- `scripts/wiki_ingest/health_lint.py`
- `tests/test-wiki-health-lint.sh`

## Files to modify

**Phase 0:**
- `scripts/wiki_ingest/__main__.py` — verb dispatcher
- `scripts/wiki_ingest/backends/copilot_cli.py` — adapter fixes
- `scripts/wiki-ingest` (shell wrapper) — backwards-compat alias
- `knowledge/README.md` — Stage-1 relabel + forward links
- `knowledge/wiki/workflows/run-wiki-ingest.md` — Stage-1 framing

**Phase 1:**
- `scripts/wiki_ingest/prompt.py` — add `compose_multi_prompt`;
  extract YAML helpers to `yaml_lite.py` and re-export for back-compat
- `scripts/wiki_ingest/proposal.py` — add `WikiPatchSet`, `PageEdit`,
  `WikiState`
- `scripts/wiki_ingest/errors.py` — add `WikiStateError`

**Phase 2 / 3 / 4:** wiring updates to the verb dispatcher only.

## Rollout

Five PRs against `master`, in order:

1. `feat: wiki-ingest pipeline Phase 0 — relabel + verb dispatcher + adapter fixes`
2. `feat: wiki-ingest pipeline Phase 1 — multi-page ingest`
3. `feat: wiki-ingest pipeline Phase 2 — promote`
4. `feat: wiki-ingest pipeline Phase 3 — query`
5. `feat: wiki-ingest pipeline Phase 4 — knowledge-health lint`

Each PR description includes its origin-alignment block as the first
section. The breaker fires at every `/phase-complete` and at every
PR review; the verdict has to remain `aligned, high` for the spec to
stay approved through the multi-PR delivery.
