# Tasks — Wiki Ingest Pipeline (Karpathy-pattern Maintainer)

Phased delivery. Each task is bounded and independently verifiable.
Tasks within a phase can be sequential; phases themselves must ship in
order (Phase N+1 starts only after Phase N merges).

The legacy v1 single-source path stays working through every phase —
no task removes or regresses it.

## Phase 0 — Relabel + verb dispatcher + adapter fixes

### T0.1 — `scripts/wiki` shell wrapper
- **Output:** new `scripts/wiki` (executable), invokes the Python
  package's `__main__.py` with the verb argument.
- **Done when:** `./scripts/wiki --help` lists `ingest|promote|query|lint`
  and prints exit codes; `./scripts/wiki` with no verb errors out.

### T0.2 — verb dispatcher in `__main__.py`
- **Output:** `scripts/wiki_ingest/__main__.py` parses a leading verb
  (`ingest`/`promote`/`query`/`lint`); each verb sub-parser is its own
  argparse group; `ingest --legacy-single-source <source>` runs the
  current v1 single-source path unchanged.
- **Done when:** `./scripts/wiki ingest --legacy-single-source <fixture> --backend test`
  produces the same proposal as the existing
  `./scripts/wiki-ingest <fixture> --backend test`. All v1
  Python unit tests still pass (`scripts/wiki_ingest/tests/`).

### T0.3 — backwards-compat alias
- **Output:** `scripts/wiki-ingest` rewired as a thin alias that calls
  `./scripts/wiki ingest --legacy-single-source` with the original
  args.
- **Done when:** every v1 call form (`./scripts/wiki-ingest <src>`,
  `--backend`, `--dry-run`, `--output-dir`) produces byte-identical
  output to pre-rescope behavior on a fixture.

### T0.4 — adapter fixes (cursor, codex, claude)
- **Output:** `scripts/wiki_ingest/backends/copilot_cli.py` updated:
  cursor uses `cursor-agent -p`; codex uses `codex exec`; claude
  unchanged at `claude -p`.
- **Done when:** smoke-test against each backend (with
  `--backend <name>`) shows the expected command line in the error
  output when the backend isn't installed (i.e., the right CLI is
  being looked up, even if not present locally).

### T0.5 — stderr redaction + `--debug-unsafe-output`
- **Output:** error messages no longer include raw backend stdout/stderr;
  truncated to a hash + first 80 chars by default; full text only with
  `--debug-unsafe-output`.
- **Done when:** a deliberately-crashing fixture backend produces an
  error message with no leakage; `--debug-unsafe-output` shows full
  stderr.

### T0.6 — real `--dry-run`
- **Output:** `--dry-run` passes `task: gate-only` through the prompt;
  backend returns disposition + reason without drafting a body; CLI
  renders a body-less proposal.
- **Done when:** comparing `--dry-run` vs. real run on the same source
  shows the dry-run is materially smaller (no drafted body) and
  clearly faster.

### T0.7 — repo-root path confinement + `--allow-out-of-repo`
- **Output:** ingest refuses paths outside the repo root unless
  `--allow-out-of-repo` is passed.
- **Done when:** ingest of `/etc/passwd` (or any out-of-repo path)
  exits with a clear refusal; `--allow-out-of-repo` lets it through.

### T0.8 — relabel docs
- **Output:** `knowledge/README.md` and
  `knowledge/wiki/workflows/run-wiki-ingest.md` updated to label
  current behavior as "Stage 1: single-source proposal generator" and
  link forward to Phases 1–4 (which are tracked in this spec).
- **Done when:** lint-wiki.sh exits 0; both docs explicitly state the
  Stage-1 framing.

### T0.9 — `IMPLEMENTATION_STATUS.md`
- **Output:** new `knowledge/wiki/IMPLEMENTATION_STATUS.md` (or
  `specs/wiki-ingest-pipeline/IMPLEMENTATION_STATUS.md`) listing each
  Karpathy operation and its delivery phase.
- **Done when:** committed; lint-wiki.sh exits 0.

### T0.10 — Phase 0 verification
- **Output:** Phase 0 PR description with the alignment block as the
  first section; all existing tests green; legacy CLI unchanged;
  origin gate exits 0.
- **Done when:** PR reviewed, alignment block re-verified, merged.

## Phase 1 — Multi-page ingest

### T1.1 — `yaml_lite.py` extraction
- **Output:** `scripts/wiki_ingest/yaml_lite.py` containing
  `_parse_frontmatter`, `_parse_simple_yaml`, `_unquote`,
  `_sources_equal` extracted from `prompt.py`.
- **Done when:** existing `prompt.py` re-exports these names for
  back-compat; v1 tests pass.

### T1.2 — `WikiState` + `wiki_state.py`
- **Output:** `scripts/wiki_ingest/wiki_state.py`. Loads `index.md`,
  `log.md`, plus a candidate page set selected by relevance heuristics
  (slug match, page-type hint, source path overlap with cited paths).
- **Done when:** unit tests cover: empty wiki (only seed pages); rich
  wiki (relevance ranking returns a stable subset); candidate cap
  honored.

### T1.3 — `compose_multi_prompt` + `WikiPatchSet`/`PageEdit`
- **Output:** new `compose_multi_prompt` in `prompt.py`; new dataclasses
  `WikiPatchSet`, `PageEdit` in `proposal.py`; `errors.py` extended.
- **Done when:** prompt is composable from a `WikiState` + source pair;
  validation rejects a `WikiPatchSet` with duplicate `create` paths,
  malformed entries, or `update` to non-existent paths.

### T1.4 — `ingestor_multi.py`
- **Output:** `scripts/wiki_ingest/ingestor_multi.py` orchestrates
  source read → wiki state load → prompt compose → backend invoke →
  per-page two-layer validation → patch-set assembly.
- **Done when:** end-to-end run against `--backend test` produces a
  patch-set; per-page validation runs and surfaces errors with the
  same shape as v1.

### T1.5 — output directory structure
- **Output:** patch-sets land at
  `doc_internal/proposals/<date>-<source-slug>/plan.json` plus
  `preview/<rel-path>.md` per affected page.
- **Done when:** reading `plan.json` round-trips through
  `WikiPatchSet`; `preview/*.md` files match the would-be wiki state
  after a hypothetical apply.

### T1.6 — test backend dispatches on `task`
- **Output:** `backends/test.py` extended to handle
  `task: ingest-multi` with deterministic multi-page response.
- **Done when:** `tests/test-wiki-ingest-multi.sh` is fully
  deterministic, no network calls.

### T1.7 — `tests/test-wiki-ingest-multi.sh`
- **Output:** fixture-driven tests for happy path, contract violation,
  patch-set validation failures.
- **Done when:** all assertions pass; counts wired into
  `tests/test-counts.env`.

### T1.8 — Phase 1 verification + PR
- **Done when:** all suites green, alignment gate exits 0, PR merged.

## Phase 2 — Promote

### T2.1 — `promoter.py`
- **Output:** atomic patch-set application; staged-temp-dir +
  structural-lint gate + `git add` on success / rollback on failure.
- **Done when:** unit tests cover success path, lint failure rollback,
  idempotency.

### T2.2 — `wiki promote` verb
- **Output:** verb dispatcher routes `promote <dir>` to `promoter.py`;
  `--dry-run` flag stages but doesn't apply.
- **Done when:** `./scripts/wiki promote <dir>` works end-to-end on a
  fixture; `--dry-run` produces a preview without changes.

### T2.3 — `.applied/` audit trail
- **Output:** post-promote, the proposals dir is moved to
  `doc_internal/proposals/.applied/<date>-<source-slug>/`; gitignored.
- **Done when:** running `promote` on a `.applied/` dir is a no-op
  with a clear message.

### T2.4 — single-writer invariant test
- **Output:** grep-based test asserting no module other than
  `promoter.py` writes to `knowledge/wiki/`.
- **Done when:** test exits 0; documented in
  `tests/test-wiki-promote.sh`.

### T2.5 — Phase 2 verification + PR
- **Done when:** all suites green, alignment gate exits 0, PR merged.

## Phase 3 — Query

### T3.1 — `querier.py` index-first navigation
- **Output:** read `index.md` first; lexical relevance match;
  candidate-page selection.
- **Done when:** unit tests verify only index-linked pages are
  selected.

### T3.2 — `compose_query_prompt` + answer parsing
- **Output:** new prompt composer; `QueryAnswer` dataclass;
  `parse_query_response`.
- **Done when:** answer + citations + pages-loaded round-trip through
  the structured response.

### T3.3 — `--file-back` flag
- **Output:** `query --file-back` produces a `WikiPatchSet` with the
  answer captured as a new or updated page.
- **Done when:** end-to-end test query → file-back → promote →
  re-query shows the captured answer is now cited.

### T3.4 — query log
- **Output:** `doc_internal/wiki-query-log.jsonl` (gitignored).
- **Done when:** every query appends one JSONL line with question,
  pages-loaded, citations.

### T3.5 — `tests/test-wiki-query.sh`
- **Done when:** covers question-with-answer, question-with-no-answer
  (returns "I don't know"), file-back round-trip.

### T3.6 — Phase 3 verification + PR
- **Done when:** all suites green, alignment gate exits 0, PR merged.

## Phase 4 — Knowledge-health lint

### T4.1 — `health_lint.py` skeleton + `HealthFinding`
- **Output:** module + dataclass; verb dispatcher routes
  `lint --health` to it.
- **Done when:** runs end-to-end on a fixture, emits zero findings.

### T4.2 — Contradictions check
- **Output:** candidate-pair selection (slug overlap / shared sources
  / cross-link edges) → backend prompt → finding.
- **Done when:** seeded contradiction fixture produces one finding;
  clean fixture produces zero.

### T4.3 — Stale-claims check
- **Output:** for each `path:` source: existence + sha drift check;
  for each `url:` source: HEAD-fetch check.
- **Done when:** seeded fixture with a 404 URL and a renamed file
  triggers two findings.

### T4.4 — Weak-orphan check
- **Output:** graph traversal from `index.md`; flag pages reachable
  via a single hub.
- **Done when:** seeded fixture produces the expected weak-orphan
  list.

### T4.5 — Missing-cross-link check
- **Output:** entity-mention indexing; flag entities mentioned in
  N ≥ 3 pages without cross-links.
- **Done when:** seeded fixture produces the expected
  missing-cross-link list.

### T4.6 — `--strict` and `--paths`
- **Output:** strict mode promotes any finding to non-zero exit;
  paths flag scopes the pass.
- **Done when:** unit tests cover both flags.

### T4.7 — `tests/test-wiki-health-lint.sh`
- **Done when:** one fixture per finding kind passes; clean fixture
  passes; --strict / --paths covered.

### T4.8 — Phase 4 verification + final PR
- **Output:** Phase 4 PR description carries the FINAL alignment
  block; all maintainer operations now delivered.
- **Done when:** all suites green, alignment gate exits 0, PR merged,
  status of this spec moves `draft` → `approved`.
