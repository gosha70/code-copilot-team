---
feature_id: wiki-ingest-pipeline
spec_mode: full
status: draft
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

# Wiki Ingest Pipeline — Karpathy-pattern LLM Wiki Maintainer

> **Rescope notice (2026-05-06).** This spec replaces the v1 "single-
> source proposal generator" spec that previously occupied this file.
> The earlier spec was found derailed against the user's origin (issue
> #12 + Karpathy's LLM Wiki gist) by the origin-confirmation circuit
> breaker (`specs/wiki-ingest-pipeline/origin-alignment-2026-05-06-1919.md`,
> verdict: derailed). The user picked resolution **A) Rescope spec to
> match origin**. The Stage-1 substrate built under the v1 spec —
> `scripts/wiki_ingest/` Python package — is preserved and reused as
> the foundation for this rescoped feature; the legacy single-source
> CLI is preserved as a backwards-compat alias.

## Problem

The user's `code-copilot-team` repo accumulates durable project knowledge
(lessons, decisions, incidents, workflows) in scattered locations: SDD
specs, GitHub issues/PRs, ephemeral session memory, and an in-repo wiki
that today is curated only by hand. Issue #12 ("LLM Wiki Groundwork")
shipped the structural foundation for a Karpathy-pattern LLM Wiki —
directory layout, schema files, seed pages, manual `/promote-lesson`
workflow, structural linter. It explicitly deferred the maintainer half
(automated ingest, query, knowledge-health lint) to follow-up issues.
This spec (#28) is that follow-up and delivers the **maintainer**.

The Karpathy-pattern wiki is a persistent, compounding artifact sitting
between raw sources and final agent instructions, maintained by an LLM
via three operations:

1. **Ingest** — reads existing wiki state into the prompt; produces a
   multi-page write plan that updates `index.md`, `log.md`, and every
   relevant existing or new page. One source can touch many pages
   (Karpathy's gist describes 10–15 typical).
2. **Query** — reads the wiki to answer a question, navigating index-
   first; optionally files the answer back into the wiki.
3. **Knowledge-health lint** — semantic checks beyond the existing
   structural linter: contradictions across pages, stale claims whose
   sources have moved, orphans only weakly cited from a hub, missing
   cross-links between pages that name the same entity.

Plus a fourth verb that gates writes:

4. **Promote** — the only operation that writes to `knowledge/wiki/`.
   Applies a patch-set produced by `ingest` (or `query --file-back`),
   atomic, runs the structural linter as a gate, stages the result for
   git review.

## User Scenarios

1. **Curator ingests a real source.** A curator finishes reading a
   merged spec or incident write-up. They run
   `./scripts/wiki ingest path/to/source.md`. Within ~60 seconds they
   get a patch-set under
   `doc_internal/proposals/<date>-<source-slug>/`: a `plan.json` listing
   every (page-path, action) pair, plus a `preview/` directory
   containing one rendered markdown per affected page. The
   patch-set typically touches `index.md`, `log.md`, one or more
   existing concept/decision/incident pages (updates), and zero or
   more new pages (creates). The curator reviews the preview, runs
   `./scripts/wiki promote doc_internal/proposals/<dir>` to apply,
   and `git diff` reflects the multi-page update.

2. **Curator queries the wiki.** A curator wants to know "what does
   our wiki say about origin alignment?" They run
   `./scripts/wiki query "what does our wiki say about origin alignment?"`.
   The pipeline reads `knowledge/wiki/index.md` first, follows links
   to relevant pages, synthesises an answer, and prints the answer plus
   `(page, fragment)` citations to every page consulted. If the answer
   isn't fully in the wiki, the curator re-runs with `--file-back`,
   which generates a small patch-set that adds or updates a page with
   the answer; promote applies it.

3. **CI runs knowledge-health lint.** A CI job runs
   `./scripts/wiki lint --health`. The structural linter
   (`knowledge/wiki/scripts/lint-wiki.sh`) runs first as before. Then
   the health pass runs: it flags contradictions across pages
   (LLM-checked over candidate page pairs sharing slugs, sources, or
   cross-links), stale claims whose cited sources moved or contradict
   the cited file's current state, orphans that are reachable from
   `index.md` but only weakly cited from a single hub, and entities
   mentioned in N pages that aren't cross-linked. Default mode is
   advisory (exit 0 with warnings); `--strict` for CI gating once the
   false-positive rate is calibrated.

4. **Curator on a fresh repo.** A curator running ingest on a repo
   with an empty `knowledge/wiki/` (only seed pages from issue #12)
   gets a patch-set that creates 1–3 pages plus `index.md`/`log.md`
   updates — the pipeline degrades gracefully when there is no
   existing wiki state to integrate with.

5. **Curator using legacy single-source flow.** A curator who liked
   the v1 single-source proposal generator continues to run
   `./scripts/wiki-ingest source.md` (the existing Phase-3 wrapper)
   or `./scripts/wiki ingest --legacy-single-source source.md`. The
   pipeline produces a single proposal at
   `doc_internal/proposals/<date>-<slug>.md` exactly as the v1 spec
   defined. No regressions.

6. **Curator running CI / sanity check.** `--backend test` selects the
   in-process deterministic backend used by the test suite. All four
   verbs (ingest, promote, query, lint) round-trip against fixture
   sources without network calls.

## Interface

### CLI surface

```
# Karpathy-pattern operations (new)
./scripts/wiki ingest <source>                  # multi-page write plan generator
./scripts/wiki promote <proposal-dir>           # apply patch-set to knowledge/wiki/
./scripts/wiki query "<question>"               # index-first synthesis with citations
./scripts/wiki query "<question>" --file-back   # synthesise + generate patch-set
./scripts/wiki lint                              # structural linter (existing)
./scripts/wiki lint --health                    # structural + knowledge-health
./scripts/wiki lint --health --strict           # exit non-zero on health flags

# Backwards-compat aliases (Stage 1, kept)
./scripts/wiki ingest --legacy-single-source <source>   # produces the v1 single proposal
./scripts/wiki-ingest <source>                          # alias for the above
```

### Operation contracts

#### `ingest` (multi-page)

- **Input:** path to a source file (repo-relative or absolute).
- **Reads:** the source content; the existing wiki state — at minimum
  `index.md` and `log.md`, plus a bounded candidate set of relevant
  existing pages selected by slug/title/page-type heuristics against
  the source; the schema files (`ingest-rules.md`, `page-types.md`,
  `citation-rules.md`).
- **Backend prompt:** the wiki-aware prompt is composed by the new
  module `compose_multi_prompt` in `prompt.py`. It includes the
  schema, the source, AND the loaded wiki state, framed as "the
  curator's working memory."
- **Output:** a directory under
  `doc_internal/proposals/<date>-<source-slug>/` containing:
  - `plan.json` — the patch-set: a list of `PageEdit` records, each
    with `path`, `action ∈ {create, update, append-log, append-index}`,
    and `new_content`. Plus `index_update`, `log_append`.
  - `preview/<rel-path-to-wiki-page>.md` — one rendered markdown per
    affected page; the curator can `diff` against the live wiki.
- **Validation:** every per-page entry passes the existing two-layer
  validation (shape + semantic cross-consistency between structured
  fields and YAML frontmatter in the rendered body). The patch-set
  itself passes a new `WikiPatchSet`-level validation: no two
  `create` entries write the same path; no `update` targets a non-
  existent path; the `index_update` and `log_append` are well-formed.
- **Exit codes:** as today (0 success, 2 backend-not-found, 3 backend
  invocation failure, 4 contract violation, 5 source missing, 6 output
  dir write failure).

#### `promote`

- **Input:** path to a `doc_internal/proposals/<dir>/`.
- **Action:** the ONLY writer to `knowledge/wiki/`. Applies the
  patch-set atomically: stages `create` and `update` actions to a
  temp dir, runs `knowledge/wiki/scripts/lint-wiki.sh` against the
  staged tree, and only on lint exit 0 moves the changes into
  `knowledge/wiki/` and stages them via `git add`. On lint failure,
  rolls back and prints the lint output.
- **Output:** the wiki tree is updated; `git status` reflects the
  multi-page change. The proposals dir is moved to
  `doc_internal/proposals/.applied/<date>-<source-slug>/` (kept for
  audit, gitignored).
- **Idempotency:** running `promote` on the same dir twice is a
  no-op (after the first run, it's in `.applied/`).

#### `query`

- **Input:** a free-text question and optional `--file-back` flag.
- **Reads:** `knowledge/wiki/index.md` first; navigates to linked
  pages by lexical matching against the question; reads only the
  selected pages into the prompt (NOT the full wiki — Karpathy's
  efficiency principle).
- **Output:** the answer printed to stdout, plus a list of
  `(page-path, fragment)` citations on stderr.
- **`--file-back`:** in addition to printing, generates a patch-set
  under `doc_internal/proposals/query-<date>-<slug>/` containing a
  page (new or update) that captures the answer. Curator reviews
  and runs `promote` to land it.
- **Logging:** which pages were loaded into context is logged to
  `doc_internal/wiki-query-log.jsonl` (one JSONL line per query) so
  curators can audit the index-first navigation.

#### `lint`

- **Input:** none for `lint` (defaults to structural). Flags:
  `--health` to add the knowledge-health pass; `--strict` to make
  health-pass findings non-zero exit; `--paths <p>...` to scope to
  specific page paths.
- **Structural pass:** runs `knowledge/wiki/scripts/lint-wiki.sh`
  unchanged. Exit 0 if clean.
- **Knowledge-health pass (with `--health`):**
  - **Contradictions** — pairs of pages making conflicting claims
    about the same entity/decision. Detected by sending candidate
    pairs (sharing slugs in title, shared sources, or cross-link
    edges) to the backend with a "do these contradict?" prompt.
    JSON-over-stdio response.
  - **Stale claims** — pages whose cited `sources:` `path:` no
    longer exists, or whose `sha:` is more than N commits behind
    HEAD with the file having changed in a meaningful way (LLM
    judgment), or whose cited URL returns 404.
  - **Weak orphans** — pages reachable from `index.md` but only via
    a single hub page; degrade-resilience signal.
  - **Missing cross-links** — entities (proper nouns, function/file
    names) that appear in N pages but aren't cross-linked.
- **Exit codes:** 0 if all passes clean; 1 if structural fails (same
  as today); 2 if health fails AND `--strict`; 0 with stderr
  warnings if health fails WITHOUT `--strict`.

### Python interface

```python
# Existing (kept as-is, Stage 1)
@dataclass(frozen=True)
class IngestRequest: ...           # source_path, source_kind, backend_name
@dataclass(frozen=True)
class IngestProposal: ...          # disposition, reason, page_type, slug, title, draft_markdown, sources

class WikiIngestor(Protocol):
    def ingest(self, request: IngestRequest) -> IngestProposal: ...

# New (Stage 2+)
@dataclass(frozen=True)
class PageEdit:
    path: str                      # e.g., "concepts/origin-alignment.md"
    action: Literal["create", "update", "append-log", "append-index"]
    new_content: str               # full page markdown (for create/update) or one-line entry (for log/index)

@dataclass(frozen=True)
class WikiPatchSet:
    edits: list[PageEdit]
    source_path: Path
    backend: str
    rationale: str                 # one-paragraph why-this-touches-these-pages

class MultiIngestor(Protocol):
    def ingest_multi(self, request: IngestRequest, wiki_state: WikiState) -> WikiPatchSet: ...

@dataclass(frozen=True)
class WikiState:
    index_md: str
    log_md: str
    candidate_pages: dict[str, str]  # path → content, for the relevant subset

@dataclass(frozen=True)
class QueryAnswer:
    answer: str
    citations: list[tuple[str, str]]  # (page-path, fragment)
    pages_loaded: list[str]           # for index-first navigation auditing

class Querier(Protocol):
    def query(self, question: str) -> QueryAnswer: ...
    def query_with_file_back(self, question: str) -> tuple[QueryAnswer, WikiPatchSet]: ...

@dataclass(frozen=True)
class HealthFinding:
    kind: Literal["contradiction", "stale-claim", "weak-orphan", "missing-cross-link"]
    severity: Literal["warning", "error"]
    pages: list[str]                  # page paths involved
    description: str                  # human-readable

class HealthLinter(Protocol):
    def lint_health(self, paths: list[str] | None) -> list[HealthFinding]: ...
```

## Reuse map (Stage 1 → Stage 2+)

The `scripts/wiki_ingest/` package built under the v1 spec stays. The
new operations grow as siblings, not replacements:

| Existing module | Fate |
|---|---|
| `__main__.py` | grow a verb dispatcher (`ingest|promote|query|lint`); existing single-arg behavior moves behind `--legacy-single-source`. |
| `ingestor.py` | split into `ingestor_single.py` (current `DefaultIngestor` — the legacy path) and `ingestor_multi.py` (new — wiki-aware multi-page generator). |
| `prompt.py::compose_prompt` | kept for the legacy path. New: `compose_multi_prompt` (loads wiki state), `compose_query_prompt`, `compose_health_prompt`. |
| `prompt.py::_parse_frontmatter`, `_parse_simple_yaml`, `_unquote`, `_sources_equal` | extract to new `yaml_lite.py`; all four operations import it. |
| `prompt.py::_validate_shape`, `_validate_semantics` | reused per-page inside the patch-set generator (every page edit goes through the same validation). |
| `backends/json_extract.py` | keep as-is. |
| `backends/copilot_cli.py` | keep, with these required fixes from the external review: cursor backend uses `cursor-agent -p` (not `cursor -p`); codex backend uses `codex exec` (not `codex -p`); claude stays on `claude -p`. Stderr redaction by default; `--debug-unsafe-output` for full text. Real `--dry-run` (passes `task: gate-only` to the backend). |
| `backends/test.py` | extend to dispatch on `prompt["task"]`; return deterministic responses for `ingest`, `ingest-multi`, `query`, `lint-health`. |
| `proposal.py::IngestProposal` | keep for legacy path. New `WikiPatchSet`, `PageEdit`, `WikiState`, `QueryAnswer`, `HealthFinding`. |
| `errors.py` | add `WikiStateError`, `KnowledgeHealthError`. Reuse the existing exit-code taxonomy. |
| `tests/` | keep all existing tests. Add per-operation suites alongside (`test-wiki-ingest-multi.sh`, `test-wiki-promote.sh`, `test-wiki-query.sh`, `test-wiki-health-lint.sh`). |

New modules required:

- `scripts/wiki_ingest/wiki_state.py` — loads `index.md`, `log.md`,
  and a candidate set of relevant pages into `WikiState`.
- `scripts/wiki_ingest/promoter.py` — the only writer to
  `knowledge/wiki/`; atomic patch-set application + structural-lint
  gate.
- `scripts/wiki_ingest/querier.py` — index-first navigation + answer
  synthesis + optional file-back.
- `scripts/wiki_ingest/health_lint.py` — knowledge-health lint
  (contradictions, stale claims, weak orphans, missing cross-links).
- `scripts/wiki` — new shell wrapper alongside the existing
  `scripts/wiki-ingest` (kept as backwards-compat alias).

## Requirements

1. **Four verbs.** `./scripts/wiki ingest|promote|query|lint`, all
   wired through the same Python package
   (`scripts/wiki_ingest/__main__.py`).

2. **Multi-page ingest.** `wiki ingest <source>` produces a
   `WikiPatchSet` with at least one `index_update` and `log_append`
   entry; one source can touch ≥ 1 existing or new page. The
   prompt MUST include the loaded `WikiState`.

3. **Promote = only writer.** `wiki promote` is the ONLY code path
   in the repo that writes to `knowledge/wiki/`. Atomic application;
   structural-lint gate; rollback on lint failure.

4. **Query reads index first.** `wiki query` reads
   `knowledge/wiki/index.md` and follows links to relevant pages;
   it must NOT load the full wiki into context. The pages-loaded
   list is recorded in `doc_internal/wiki-query-log.jsonl` for audit.

5. **Knowledge-health lint.** `wiki lint --health` adds four checks
   on top of the structural linter: contradictions, stale claims,
   weak orphans, missing cross-links. Default advisory; `--strict`
   for CI gating.

6. **Backwards compatibility.** `./scripts/wiki-ingest <source>`
   continues to produce the v1 single-source proposal at
   `doc_internal/proposals/<date>-<slug>.md`. All existing v1 tests
   pass. The legacy path is also available as
   `./scripts/wiki ingest --legacy-single-source <source>`.

7. **Reuse, not rewrite.** All Stage 1 modules are kept; new
   operations grow as siblings. No fork.

8. **Adapter fixes from the external review.** Cursor backend uses
   `cursor-agent -p`; codex backend uses `codex exec`; stderr
   redacted by default; real `--dry-run` skips the body generation
   by passing `task: gate-only` through the prompt.

9. **Test backend dispatches on task.** The deterministic test
   backend handles `ingest`, `ingest-multi`, `query`, `lint-health`
   with fixed responses; all four operations have a CI-safe path
   from day one.

10. **Stdlib-only Python.** No third-party deps. `dataclasses`,
    `argparse`, `subprocess`, `json`, `pathlib`, `tempfile`, `re`.

11. **Bash 3.2 + awk for any new scripts.** Matches the repo
    convention (`lint-wiki.sh`, `check-origin-alignment.sh`).

12. **Origin alignment passes.** `bash scripts/check-origin-alignment.sh
    wiki-ingest-pipeline` exits 0 (`aligned, high`) before this spec
    is approved (status: draft → approved).

## Constraints / What NOT to Build

1. **No automatic merging into `knowledge/wiki/`.** `promote` is
   curator-triggered; never run on commit, never run by a hook.

2. **No file-watcher / scheduler / cron.** All four operations are
   manual CLI only.

3. **No third-party LLM SDK dependencies.** Subprocess invocation of
   existing copilot CLIs (claude, codex, cursor) remains the default.
   SDK adapters are a v1.x extension, written by contributors against
   the documented JSON-over-stdio contract.

4. **No vector store, no embeddings.** Karpathy's gist explicitly
   notes the pattern works at moderate scale without a vector DB.
   Index-first navigation is the retrieval primitive. Adding a vector
   DB is a separate, deferred optimization.

5. **No new top-level directory.** All code lives under the existing
   `scripts/wiki_ingest/` package.

6. **No bypass of the structural linter.**
   `knowledge/wiki/scripts/lint-wiki.sh` continues to gate every
   `promote` invocation. If it's wrong, fix it in a separate change.

7. **No silent overrides for backend mismatches.** If a backend's CLI
   contract is wrong (e.g., the cursor adapter calling `cursor -p`
   instead of `cursor-agent -p`), fix the adapter — never mask the
   error and continue.

8. **No coupling to a single copilot.** All four operations work
   identically across the test backend, claude, codex, and cursor.
   `WIKI_INGEST_BACKEND` env var and `--backend` flag continue to
   override auto-detect.

9. **Origin frontmatter immutability.** The `origin:` block in
   `plan.md` is immutable except via an explicit `origin-amendment:`
   commit. Other commits that touch the block fail validation.

## Key Entities

- **WikiState** — the working memory loaded into the multi-page ingest
  prompt: `index.md`, `log.md`, plus a bounded candidate set of
  existing pages selected by relevance to the source. Without
  `WikiState`, ingest cannot integrate; with it, ingest compounds.
- **WikiPatchSet** — the multi-page output of `ingest`: a list of
  `PageEdit` records plus `index_update`/`log_append`. Atomic unit of
  promotion.
- **PageEdit** — one (path, action, content) record. Action is one of
  `create`, `update`, `append-log`, `append-index`.
- **QueryAnswer** — the structured output of `query`: answer text plus
  citations plus the audit list of pages loaded.
- **HealthFinding** — one finding from the knowledge-health lint pass:
  kind, severity, pages involved, description.
- **IngestProposal** — kept, unchanged, for the legacy single-source
  path. Continues to satisfy the v1 contract documented in this
  spec's earlier revisions (preserved in git history).

## Success Criteria

The spec is approved (status `draft` → `approved`) when:

- `bash scripts/check-origin-alignment.sh wiki-ingest-pipeline` exits
  0 with verdict `aligned, high`. The post-rescope alignment record is
  the gate: until it lands, this spec stays `draft`.
- `bash scripts/validate-spec.sh --feature-id wiki-ingest-pipeline`
  exits 0.
- `plan.md` carries the phased delivery plan (Phase 0 relabel +
  hardening; Phase 1 multi-page ingest; Phase 2 promote; Phase 3 query;
  Phase 4 health-lint).
- `tasks.md` carries bounded, independently-verifiable tasks per phase.

The feature is delivered (PR-by-PR) when, after each phase merges:

- All existing tests continue to pass (1437+ assertions across the
  current suite).
- The new operation's test suite exits 0 against the deterministic
  test backend.
- `bash knowledge/wiki/scripts/lint-wiki.sh` continues to exit 0.
- The legacy `./scripts/wiki-ingest <source>` path continues to work
  identically — zero regressions for v1 callers.

## Sources

- `pr: 27` — the v1 substrate this rescope builds on.
- `issue: gosha70/code-copilot-team#12` — origin: LLM Wiki Groundwork.
- `issue: 28` — this spec.
- `url: https://gist.github.com/karpathy/3ef5df0e1ee5d36d59b29eb91f8d35c1`
  retrieved: 2026-05-06 — origin: the Karpathy LLM Wiki gist.
- `path: specs/wiki-ingest-pipeline/origin-alignment-2026-05-06-1919.md`
  — derailment record that motivated this rescope.
- `path: specs/origin-confirmation-circuit-breaker/origin/external-review.md`
  — independent diagnosis of the v1 derailment.
- `path: knowledge/wiki/schema/WIKI_MAINTAINER.md` — curator persona.
- `path: knowledge/wiki/schema/ingest-rules.md`,
  `path: knowledge/wiki/schema/page-types.md`,
  `path: knowledge/wiki/schema/citation-rules.md`,
  `path: knowledge/wiki/schema/lint-rules.md` — schema files that
  every operation reads.
