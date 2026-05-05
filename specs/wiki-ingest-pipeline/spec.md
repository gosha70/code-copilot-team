---
feature_id: wiki-ingest-pipeline
spec_mode: lightweight
status: draft
issue: TBD
---

# Wiki Ingest Pipeline — Spec

## Problem

The LLM Wiki groundwork (#12) plus v0.2 schema patches (#26) have
proved the wiki schema works at small scale. The v0.1 dogfood
measured the remaining bottleneck: every promotion costs ~24–28
minutes of focused human work, and the most repetitive shape inside
that cost is **applying the four-question gate** (reusable, citable,
non-duplicative, new-contributor-relevant) and **drafting the typed
skeleton** that fills the page-type template.

That repetitive shape is exactly what an LLM agent can do — under
human review, without merging into the canonical wiki on its own.
This spec defines the v1 pipeline that runs the gate and the draft
as a structured prompt, and writes a typed proposal to
`doc_internal/proposals/<date>-<slug>.md` for human curator review.

**Human approval remains gating throughout.** The pipeline never
writes to `knowledge/wiki/`. A curator runs the existing
`/promote-lesson` workflow (or the manual procedure in
`knowledge/wiki/workflows/promote-lesson-to-wiki.md`) to take an
approved proposal across the line.

## Non-goals

- Automatic merging into `knowledge/wiki/`. v1 produces proposals
  only.
- Post-commit / post-merge / file-watcher triggers. v1 is manual
  CLI only.
- Multi-source synthesis (combining N sources into one proposal).
  v1 is one-source-in, one-proposal-out.
- Concrete LLM SDK backends (anthropic, openai, ollama, etc.).
  v1 ships one default backend that subprocess-invokes existing
  copilot CLIs (`claude`, `codex`, `cursor`); SDK backends are a
  v1.x extension contributors can write against the documented
  protocol.
- Rich review UI. Markdown-on-disk plus git is the review surface.

## User scenarios

1. **Curator with a candidate file.** A curator finishes reading a
   merged spec or incident write-up and wants to propose it as a
   wiki page. They run `./scripts/wiki-ingest path/to/source.md`,
   wait <60 seconds, and find a proposal at
   `doc_internal/proposals/<date>-<slug>.md`. They open it,
   sanity-check the gate decision, accept the draft, and run
   `/promote-lesson` to land it.

2. **Curator with a borderline candidate.** Same flow, but the
   pipeline's gate disposition is `reject` with a recorded reason.
   The proposal file contains the reason and no draft. The curator
   either accepts the rejection (file lives in
   `doc_internal/proposals/` as a record) or overrides it manually.

3. **Curator running CI / sanity check.** The test backend is
   selected via `--backend test`. The pipeline runs end-to-end
   against a fixture file with no real LLM call and produces a
   deterministic proposal that the test suite asserts against.

4. **Curator without `claude` installed.** The auto-detect order
   tries `claude`, then `codex`, then `cursor`. If none are on
   `PATH`, the pipeline fails with a clear message naming all
   three and pointing at `--backend test` for fixture-only runs.

## Interface

### `WikiIngestor` protocol (Python)

```python
@dataclass(frozen=True)
class IngestRequest:
    source_path: Path                      # repo-relative or absolute
    source_kind: Literal["file", "issue", "url"]  # v1: only "file"
    backend_name: str                      # "claude" | "codex" | "cursor" | "test" | <plugin>

@dataclass(frozen=True)
class IngestProposal:
    disposition: Literal["accept", "reject"]
    reason: str                            # required for reject; optional rationale for accept
    page_type: str | None                  # one of page-types.md types; None on reject
    slug: str | None                       # kebab-case; None on reject
    title: str | None                      # None on reject
    draft_markdown: str | None             # full page body inc. frontmatter; None on reject
    sources: list[dict]                    # frontmatter sources entries; may be empty on reject

class WikiIngestor(Protocol):
    def ingest(self, request: IngestRequest) -> IngestProposal: ...
```

The default implementation composes a structured prompt from the
schema files (`ingest-rules.md`, `page-types.md`,
`citation-rules.md`), invokes the backend via JSON-over-stdio,
parses the response, and returns the typed `IngestProposal`.

### Backend contract (JSON-over-stdio)

A backend is any executable on `PATH` (or any Python callable
registered as a plugin) that:

1. Accepts a single JSON object on stdin matching the
   `BackendPrompt` schema below.
2. Writes a single JSON object on stdout matching the
   `BackendResponse` schema below.
3. Exits 0 on success, non-zero on backend failure (the pipeline
   surfaces backend stderr in the error message).

```json
// BackendPrompt — what the pipeline sends to the backend
{
  "version": 1,
  "system_instructions": "<schema-derived prelude>",
  "task": "ingest",
  "schema_excerpts": {
    "ingest_rules": "<contents of schema/ingest-rules.md>",
    "page_types":   "<contents of schema/page-types.md>",
    "citation_rules": "<contents of schema/citation-rules.md>"
  },
  "source": {
    "kind": "file",
    "path": "<repo-relative path>",
    "content": "<source file body, UTF-8>"
  },
  "response_schema": "<inline JSON Schema for BackendResponse>"
}
```

```json
// BackendResponse — what the backend must return on stdout
{
  "version": 1,
  "disposition": "accept",
  "reason": "<short prose>",
  "page_type": "incident",
  "slug": "spec-code-coherence-drift",
  "title": "Spec/Code Coherence Drift",
  "draft_markdown": "---\npage_type: incident\n…",
  "sources": [
    {"path": "specs/foo/spec.md", "sha": "abc1234"},
    {"pr": "gosha70/rlmkit#30"}
  ]
}
```

The pipeline validates the response in **two layers**:

1. **Shape (JSON-schema).** `BackendResponse` matches the inline
   schema: required keys present, values of expected types,
   `disposition` ∈ `{accept, reject}`, etc. A shape failure raises
   `ContractViolation` (exit 4).

2. **Semantic cross-consistency.** When `disposition == "accept"`,
   the pipeline must also parse the YAML frontmatter embedded in
   `draft_markdown` and assert that:

   - `draft_markdown` starts with a `---`-fenced YAML frontmatter
     block (per `knowledge/wiki/schema/page-types.md` universal
     frontmatter format).
   - The frontmatter's `page_type` equals the structured-field
     `page_type`.
   - The frontmatter's `slug` equals the structured-field `slug`.
   - The frontmatter's `title` equals the structured-field
     `title`.
   - The frontmatter's `sources:` entries equal the structured-
     field `sources` (set equality; order is not significant).
   - The structured-field `slug` is kebab-case.
   - The structured-field `slug`-and-`page_type` pair satisfies
     the directory-placement rule the wiki linter would later
     enforce (`page_type: incident` ⇒ destined for `incidents/`,
     etc.; the special case for `glossary/index.md` applies if
     `slug == "glossary"`).
   - The structured-field `sources` list is non-empty (the wiki
     linter will reject any non-index/log page without sources;
     a draft proposal that violates this is dead on arrival).

   Any semantic-validation failure raises `ContractViolation`
   (exit 4) with a message naming the specific mismatch (e.g.,
   `draft_markdown.frontmatter.page_type ('concept') ≠ structured
   page_type ('incident')`). The pipeline does **not** attempt to
   silently reconcile mismatches — the curator must see that the
   backend is producing inconsistent output.

The semantic validation is what protects the curator from
proposals that pass JSON-shape checks but would fail the wiki
linter, the schema templates, or basic frontmatter sanity. It is
not optional.

### Default backend: copilot-CLI subprocess

Auto-detect order: `claude` → `codex` → `cursor`. The first one
found on `PATH` is selected unless `--backend <name>` overrides.

The default backend wraps the chosen CLI with a documented prompt
template. The prompt:

- Frames the task as "act as the wiki curator persona; read the
  schema excerpts in this prompt; apply the four-question gate to
  the source; if it passes, draft a typed page; if not, return a
  reject disposition with reason."
- Specifies the JSON response schema inline, with explicit
  instructions to emit exactly one JSON object on stdout and
  nothing else.
- Includes the source file content verbatim.
- Includes the v0.2 schema files inline (read from disk at runtime,
  not embedded in source).

The default backend is the **adapter layer** between the
pipeline's JSON contract and a CLI that returns free-form text.
It is responsible for extracting the JSON object from CLI output
(matching the first balanced top-level `{…}` block).

### Test backend

A deterministic in-process backend used by the test suite:

- Accepts the same `BackendPrompt` shape.
- Returns a fixed `BackendResponse` derived from the source
  content's first H1 (page-type and slug derived deterministically).
- No subprocess, no LLM call.
- Selected via `--backend test`. Must not be selected by
  auto-detect.

## CLI surface

```
./scripts/wiki-ingest <source-path>          # default backend, accept-or-reject, full draft
./scripts/wiki-ingest --dry-run <source>     # gate only; do not request a draft
./scripts/wiki-ingest --backend test <src>   # use test backend (CI / fixture)
./scripts/wiki-ingest --backend claude <src> # explicit backend selection
./scripts/wiki-ingest --output-dir <dir>     # override doc_internal/proposals/
./scripts/wiki-ingest --help
```

The script is `scripts/wiki-ingest` (no extension; matches existing
script convention). Internally it sets
`PYTHONPATH=<repo>/scripts` and `exec`s `python3 -m wiki_ingest
"$@"` — the module-form invocation is required so relative imports
inside the package resolve. (Running the directory or
`__main__.py` as a script would fail with `attempted relative
import with no known parent package` the moment any module does
`from .errors import …`.) Python 3.10+ required; documented in
`knowledge/README.md`.

## Output

One proposal file per invocation, written to
`doc_internal/proposals/<YYYY-MM-DD>-<slug>.md`. The proposal
file contains:

```markdown
---
proposal_kind: <accept | reject>
proposal_date: 2026-05-04
source_path: rlmkit/doc_internal/specs/foo.md
backend: claude
ingestor_version: 1
gate_disposition: <accept | reject>
gate_reason: <short prose>
target_slug: <slug or empty>
target_page_type: <type or empty>
---

<for accept: the full proposed wiki page body, ready to drop into knowledge/wiki/<dir>/<slug>.md>

<for reject: a short prose explanation of which gate question failed and why>
```

For accept proposals, the body is verbatim what would be saved to
the wiki — the curator can `cp` it into place once approved (or run
`/promote-lesson` against the proposal path).

`doc_internal/proposals/` is gitignored in v1.

## Error semantics

The pipeline distinguishes:

1. **Backend not found.** All auto-detect candidates absent; or the
   explicitly-named backend not on `PATH` and not registered as a
   plugin. Exit 2; message names the backends tried and points at
   `--backend test`.
2. **Backend invocation failure.** Backend exits non-zero. Exit 3;
   message includes the backend's stderr (truncated to 2 KiB).
3. **Contract violation.** Backend stdout cannot be parsed as JSON,
   or fails the `BackendResponse` schema validation. Exit 4;
   message names the failing schema field and prints the offending
   stdout (truncated).
4. **Source missing or unreadable.** Exit 5.
5. **Output directory write failure.** Exit 6.
6. **Successful run, gate accept.** Exit 0; print absolute path of
   the proposal file.
7. **Successful run, gate reject.** Exit 0; print absolute path of
   the proposal file (a reject is a successful pipeline outcome —
   the gate did its job).

Exit codes are documented in `--help` and stable across v1.

## Requirements

1. **Python 3.10+ only.** Stdlib only — no `pip install` step. Type
   hints, `dataclasses`, `argparse`, `subprocess`, `json`,
   `pathlib`, `tempfile` are sufficient. The decision to introduce
   Python (the rest of the repo's scripts are Bash) is deliberate
   and justified by the JSON + subprocess + structured-prompt
   shape; documented in `knowledge/README.md`.
2. **`WikiIngestor` protocol** as defined above, with concrete
   types (`IngestRequest`, `IngestProposal`).
3. **JSON-over-stdio backend contract** with version field,
   inline response schema, explicit error semantics, **and the
   two-layer validation specified above (shape + semantic
   cross-consistency between structured fields and the YAML
   frontmatter embedded in `draft_markdown`)**.
4. **One default backend** (copilot-CLI subprocess) with documented
   auto-detect order: `claude` → `codex` → `cursor`.
5. **Test backend** that the test suite uses end-to-end, with a
   committed fixture source file and a deterministic expected
   proposal.
6. **`./scripts/wiki-ingest` CLI wrapper** with the flags listed
   under "CLI surface", `--help` documenting all of them and the
   exit codes.
7. **Output to `doc_internal/proposals/<date>-<slug>.md`**, with
   the documented proposal file frontmatter; ensure
   `doc_internal/proposals/` is gitignored.
8. **Documentation:**
   - Update `knowledge/README.md` with a "Running ingest" section.
   - Add `knowledge/wiki/workflows/run-wiki-ingest.md` (page type
     `workflow`) covering when to use it, how it differs from
     manual promotion, and verification steps. Promote via the
     atomic-cluster recipe (one workflow page → one index entry →
     one log entry → one lint pass).
9. **Tests:**
   - Unit tests for prompt composition and response parsing.
   - End-to-end test using `--backend test` against the fixture
     source; assert exit code 0, assert proposal file exists with
     expected frontmatter and body shape.
   - Negative tests: backend not found, contract violation, source
     missing.
   - Wired into CI via the existing test runner in `tests/`.

## Constraints

1. **No automatic merging into `knowledge/wiki/`.** The pipeline
   only writes under `doc_internal/proposals/`. Human approval
   remains gating.
2. **No new third-party dependencies.** Stdlib Python only.
   Backends remain pluggable so a contributor *can* add an SDK
   adapter without changing the pipeline.
3. **No new top-level directory.** The pipeline lives at
   `scripts/wiki-ingest` (entrypoint) and `scripts/wiki_ingest/`
   (Python package). No `src/` or `pkg/` for one feature.
4. **No bypass of `knowledge/wiki/scripts/lint-wiki.sh`.** This
   issue does not edit any committed wiki page; the linter must
   continue to exit 0 against the wiki at every step. The new
   `workflows/run-wiki-ingest.md` page is the only addition and
   must lint clean before commit.
5. **Backend prompts read schema files at runtime.** The prompt
   loader reads `knowledge/wiki/schema/{ingest-rules,page-types,citation-rules}.md`
   from disk on every invocation. Do not embed schema text in
   Python source — that would drift the moment a v0.3 schema
   patch lands.
6. **`doc_internal/proposals/` is gitignored.** The
   `.gitignore` already covers `doc_internal/`; verify and
   document. Proposals are unfinished work and must not pollute
   the tracked tree.
7. **No telemetry, no network calls from the pipeline itself.**
   The default backend invokes a copilot CLI which may make
   network calls; that is the user's choice. The pipeline layer
   does not.
8. **Manual CLI only in v1.** No hooks, no watchers, no
   schedulers. Future hook integration is a v2 issue.
9. **Validate-spec compliance.**
   `scripts/validate-spec.sh --feature-id wiki-ingest-pipeline`
   must pass.

## Acceptance criteria

- [ ] `./scripts/wiki-ingest scripts/wiki_ingest/tests/fixtures/sample-incident.md --backend test`
      writes a syntactically valid proposal to
      `doc_internal/proposals/<today>-<slug>.md` and exits 0.
- [ ] The proposal frontmatter contains `proposal_kind`,
      `gate_disposition`, `target_slug`, `target_page_type`, and
      the proposal body for an `accept` proposal contains a
      complete wiki-page-shaped frontmatter block compatible with
      `knowledge/wiki/schema/page-types.md`.
- [ ] Negative tests pass for: backend-not-found (exit 2),
      contract-violation (exit 4), source-missing (exit 5).
- [ ] `bash scripts/validate-spec.sh --feature-id wiki-ingest-pipeline` passes.
- [ ] `bash knowledge/wiki/scripts/lint-wiki.sh` continues to
      exit 0 (the new `workflows/run-wiki-ingest.md` page passes).
- [ ] `knowledge/README.md` documents the pipeline in a "Running
      ingest" section.
- [ ] Existing test suites (`tests/test-shared-structure.sh`,
      `tests/test-generate.sh`, etc.) continue to pass with no
      count adjustments — this issue does not change `shared/skills/`
      or generator output.

## Sources

- `path: knowledge/wiki/schema/ingest-rules.md` (v0.2)
- `path: knowledge/wiki/schema/page-types.md` (v0.2)
- `path: knowledge/wiki/schema/citation-rules.md` (v0.2)
- `path: knowledge/wiki/workflows/promote-lesson-to-wiki.md` (v0.2)
- `path: scripts/validate-spec.sh`
- `pr: 26` — v0.2 schema patches PR
- `issue: 12` — wiki groundwork prerequisite
- Local-only `doc_internal/dogfood-learnings.md` — friction findings
  F1/F4/F5 are addressed by the v0.2 schema patches the pipeline
  consumes; the "automated ingest pipeline" recommendation in that
  doc is the direct origin of this spec.
