---
spec_mode: lightweight
feature_id: wiki-ingest-pipeline
risk_category: tooling
justification: "New Python-package script + CLI wrapper, gitignored output dir, one new wiki workflow page, README update. No runtime behavior change for existing users; no edits to shared/skills, generator outputs, or committed wiki pages."
status: draft
date: 2026-05-04
issue: TBD
---

# Implementation Plan: Wiki Ingest Pipeline (v1)

## Context

The LLM Wiki groundwork (#12, landed) and v0.2 schema patches
(#26, in review) leave the wiki schema substantially correct and
the manual promote-to-wiki workflow validated end-to-end. The v0.1
dogfood measured the remaining bottleneck: ~24–28 minutes of human
work per promotion, dominated by applying the four-question gate
and drafting the typed skeleton.

This plan implements the **v1 ingest pipeline**: a Python CLI that
runs the gate + draft as a structured prompt against an LLM
backend, and writes a typed proposal to `doc_internal/proposals/`
for human curator review. **Human approval remains gating.** No
auto-merge into `knowledge/wiki/`.

The interface is open enough that contributors can plug in concrete
SDK backends (anthropic, openai, ollama) later without changing the
pipeline. v1 ships exactly one default backend that subprocess-
invokes existing copilot CLIs (`claude` → `codex` → `cursor`).

See `specs/wiki-ingest-pipeline/spec.md` for the spec; this plan
breaks the work into phases and assigns it to the build agent.

## Scope (what this plan delivers)

1. `scripts/wiki-ingest` — Bash entrypoint that execs into Python.
2. `scripts/wiki_ingest/` — Python package: `__main__.py`,
   `ingestor.py`, `backends/{copilot_cli,test}.py`,
   `prompt.py`, `proposal.py`, `errors.py`.
3. `scripts/wiki_ingest/tests/` — pytest-free unittest module
   (stdlib only); fixture source under `tests/fixtures/`.
4. `knowledge/wiki/workflows/run-wiki-ingest.md` — new workflow
   page promoted via the v0.2 atomic-cluster recipe.
5. `knowledge/README.md` update — "Running ingest" section.
6. `.gitignore` verification: confirm `doc_internal/proposals/` is
   covered.
7. `tests/test-wiki-ingest.sh` — new test runner that executes the
   Python unittest module and the end-to-end `--backend test` flow,
   wired into the existing test convention.
8. CI: a new GitHub Actions workflow (or an addition to an existing
   one — phase 4 will pick the cheaper option after reading
   `.github/workflows/`) that runs `tests/test-wiki-ingest.sh` on
   PRs touching `scripts/wiki_ingest/**`.

## Out of scope (deferred)

- Concrete SDK backends (anthropic, openai, ollama). The contract
  is open; contributors can add them in a separate PR.
- Hooks (post-commit, post-merge, file-watcher). v2.
- Multi-source synthesis. v2 / RLMKit follow-up.
- Auto-merge. Out of scope by design — human approval is gating.

## Phases

The build agent will execute these phases sequentially. Each phase
ends with a verification step and a stop point for review.

### Phase 1 — Python package skeleton + interface + test backend

**Goal:** All types and the deterministic test backend exist and
are unit-tested. No real-LLM path yet.

Files:

- `scripts/wiki_ingest/__init__.py` (empty)
- `scripts/wiki_ingest/errors.py` — exception hierarchy mapping to
  the spec's exit codes
- `scripts/wiki_ingest/proposal.py` — `IngestRequest`,
  `IngestProposal` dataclasses; helpers to render an
  `IngestProposal` to the proposal-file markdown body
- `scripts/wiki_ingest/prompt.py` — load schema files from disk;
  compose `BackendPrompt` JSON; parse `BackendResponse` JSON with
  **two-layer validation**: (1) shape against the inline JSON
  Schema (using stdlib `json` + hand-written validator; no
  `jsonschema` dependency), then (2) semantic cross-consistency —
  parse the YAML frontmatter inside `draft_markdown` and assert
  it matches the structured `page_type` / `slug` / `title` /
  `sources` fields, that `slug` is kebab-case, that the
  `page_type`/`slug` pair satisfies the directory-placement rule
  the wiki linter enforces, and that `sources` is non-empty for
  accept dispositions. YAML parsing uses a small hand-written
  frontmatter parser (the same `awk`-style trick the wiki linter
  uses, ported to Python) — no `pyyaml` dependency.
- `scripts/wiki_ingest/ingestor.py` — `WikiIngestor` Protocol +
  `DefaultIngestor` class wiring prompt → backend → proposal
- `scripts/wiki_ingest/backends/__init__.py` — registry +
  auto-detect logic
- `scripts/wiki_ingest/backends/test.py` — deterministic test
  backend
- `scripts/wiki_ingest/tests/test_proposal.py`
- `scripts/wiki_ingest/tests/test_prompt.py`
- `scripts/wiki_ingest/tests/test_ingestor_with_test_backend.py`
- `scripts/wiki_ingest/tests/fixtures/sample-incident.md` — small
  realistic incident-shaped source

Verification:

- `python3 -m unittest discover scripts/wiki_ingest/tests` passes.

Stop point: review interface shapes before phase 2.

### Phase 2 — Default backend (copilot-CLI subprocess) + auto-detect

**Goal:** Real backend works against any of `claude`, `codex`,
`cursor`. No CLI wrapper yet.

Files:

- `scripts/wiki_ingest/backends/copilot_cli.py` — subprocess
  invocation, JSON extraction from free-form CLI output, error
  mapping
- `scripts/wiki_ingest/backends/__init__.py` — fill in auto-detect
  order
- `scripts/wiki_ingest/tests/test_copilot_cli.py` — uses a tiny
  shell stub backend (a 5-line shell script that emits a fixed
  JSON object) under `tests/fixtures/stub-backend.sh` to exercise
  the subprocess path without requiring a real copilot CLI in CI

Verification:

- `python3 -m unittest scripts.wiki_ingest.tests.test_copilot_cli`
  passes against the stub.

Stop point: review backend abstraction; confirm the JSON-extraction
strategy handles real `claude` / `codex` output before phase 3.
**This is where I expect the most iteration** — the JSON-extraction
heuristic is the v1 risk.

### Phase 3 — CLI wrapper + bash entrypoint + end-to-end flow

**Goal:** `./scripts/wiki-ingest <path>` works end-to-end with the
test backend; flags and exit codes match the spec.

Files:

- `scripts/wiki_ingest/__main__.py` — argparse, exit-code mapping,
  proposal-file write
- `scripts/wiki-ingest` — bash entrypoint (executable):

      #!/usr/bin/env bash
      set -euo pipefail
      REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
      exec env PYTHONPATH="$REPO_DIR/scripts${PYTHONPATH:+:$PYTHONPATH}" \
        python3 -m wiki_ingest "$@"

  The `python3 -m <pkg>` form (with `PYTHONPATH` pointing at the
  parent of `wiki_ingest/`) is what makes relative imports inside
  the package resolve. Invoking the directory directly
  (`python3 scripts/wiki_ingest`) would fail with `attempted
  relative import with no known parent package` the moment any
  module does `from .errors import …`.

- `scripts/wiki_ingest/tests/test_e2e.py` — invokes the CLI via
  `subprocess.run`, asserts exit code, asserts proposal file
  exists with expected frontmatter

Verification:

- `./scripts/wiki-ingest --backend test scripts/wiki_ingest/tests/fixtures/sample-incident.md`
  exits 0 and writes a proposal file.
- `./scripts/wiki-ingest --backend test --dry-run <fixture>`
  exits 0, no draft, frontmatter `gate_disposition` set.
- Negative paths: missing source (exit 5), missing backend (exit 2),
  contract violation (exit 4) — driven by a stub backend that
  emits invalid JSON.

Stop point: review CLI surface and exit-code semantics.

### Phase 4 — Documentation + tests harness + CI

**Goal:** Pipeline is documented and tested in CI.

Files:

- `tests/test-wiki-ingest.sh` — bash runner that executes the
  Python unittest discovery + the e2e flow; matches the style of
  other `tests/*.sh` files; reports pass/fail count.
- `knowledge/README.md` — new "Running ingest" section explaining
  what the pipeline does, what it doesn't do, the four-question
  gate semantics, and the `--backend test` CI mode.
- `knowledge/wiki/workflows/run-wiki-ingest.md` — new workflow page
  (page_type `workflow`) covering when to use ingest vs. manual,
  and how to take a proposal across the line.
- `knowledge/wiki/index.md` — one bullet under Workflows for the
  new page.
- `knowledge/wiki/log.md` — one entry for the new workflow page.
- `.github/workflows/wiki-ingest-tests.yml` (or addition to
  existing `wiki-lint.yml` if cheaper) — runs
  `tests/test-wiki-ingest.sh`. The `paths:` filter must include
  **every input** the test depends on, otherwise a change to the
  test harness will not trigger CI:

  ```yaml
  on:
    pull_request:
      paths:
        - 'scripts/wiki-ingest'
        - 'scripts/wiki_ingest/**'
        - 'tests/test-wiki-ingest.sh'
        - '.github/workflows/wiki-ingest-tests.yml'
        - 'knowledge/wiki/schema/**'   # prompt.py reads schema at runtime
  ```

  Decision deferred to Phase 4 implementation: pick between
  (a) a standalone workflow with the path filter above, or
  (b) wiring `tests/test-wiki-ingest.sh` into an existing
  always-on test entrypoint (currently `sync-check` runs the
  shared-structure / generate / sync test trio). Option (b)
  removes the path-filter risk entirely but requires updating
  `tests/test-counts.env`, `tests/test-shared-structure.sh`,
  and `README.md` test counts. **Default plan: option (a)** —
  a feature-scoped workflow keeps the change small and avoids
  cross-cutting count drift; revisit (b) only if the path filter
  proves unreliable in practice.

Verification:

- `bash tests/test-wiki-ingest.sh` exits 0 locally.
- `bash knowledge/wiki/scripts/lint-wiki.sh` exits 0 (the new
  workflow page lints clean).
- `bash scripts/validate-spec.sh --feature-id wiki-ingest-pipeline`
  passes.
- All other test suites
  (`tests/test-shared-structure.sh`, `tests/test-generate.sh`,
  `tests/test-sync.sh`, `tests/test-hooks.sh`) still pass — this
  feature does not touch `shared/skills/` or generator outputs.

Stop point: review the new workflow page and README addition before
the PR is opened.

## Test strategy

- **Unit tests** (Python unittest, stdlib only):
  - `proposal.py` rendering (accept + reject shapes).
  - `prompt.py` schema-file loading + JSON composition.
  - `prompt.py` shape validation: malformed JSON, missing keys,
    wrong value types, unknown `disposition`.
  - `prompt.py` semantic validation: structured-vs-frontmatter
    `page_type` mismatch, `slug` mismatch, `title` mismatch,
    `sources` set inequality, non-kebab-case slug, page_type/slug
    placement violation (e.g., a `slug: glossary` page typed as
    `concept`), empty `sources` on accept. Each assertion gets
    its own test so a regression names the specific rule.
  - `backends/test.py` determinism.
  - `backends/copilot_cli.py` against a shell stub.
  - `__main__.py` argparse + exit-code mapping.

- **End-to-end test:** Invokes `./scripts/wiki-ingest --backend
  test <fixture>` and asserts proposal file existence + frontmatter
  shape.

- **Negative tests:** Backend not found, malformed backend JSON,
  source missing.

- **Lint:** New workflow page must pass `lint-wiki.sh`.

- **Spec validation:** `validate-spec.sh --feature-id
  wiki-ingest-pipeline` must pass.

## Files to create / modify

### Create

- `scripts/wiki-ingest`
- `scripts/wiki_ingest/__init__.py`
- `scripts/wiki_ingest/__main__.py`
- `scripts/wiki_ingest/errors.py`
- `scripts/wiki_ingest/proposal.py`
- `scripts/wiki_ingest/prompt.py`
- `scripts/wiki_ingest/ingestor.py`
- `scripts/wiki_ingest/backends/__init__.py`
- `scripts/wiki_ingest/backends/copilot_cli.py`
- `scripts/wiki_ingest/backends/test.py`
- `scripts/wiki_ingest/tests/__init__.py`
- `scripts/wiki_ingest/tests/test_proposal.py`
- `scripts/wiki_ingest/tests/test_prompt.py`
- `scripts/wiki_ingest/tests/test_ingestor_with_test_backend.py`
- `scripts/wiki_ingest/tests/test_copilot_cli.py`
- `scripts/wiki_ingest/tests/test_e2e.py`
- `scripts/wiki_ingest/tests/fixtures/sample-incident.md`
- `scripts/wiki_ingest/tests/fixtures/stub-backend.sh`
- `tests/test-wiki-ingest.sh`
- `knowledge/wiki/workflows/run-wiki-ingest.md`
- `.github/workflows/wiki-ingest-tests.yml` (or merge into existing
  workflow per phase 4 decision)

### Modify

- `knowledge/README.md` — add "Running ingest" section.
- `knowledge/wiki/index.md` — add bullet under Workflows.
- `knowledge/wiki/log.md` — append entry for the new workflow page.
- `.gitignore` — verify `doc_internal/proposals/` is covered;
  add `doc_internal/proposals/` explicitly if `doc_internal/`
  is not already covered as a whole.

### Reuse (no change)

- `knowledge/wiki/schema/{ingest-rules,page-types,citation-rules}.md`
  — read at runtime by `prompt.py`.
- `knowledge/wiki/scripts/lint-wiki.sh` — used in CI.
- `scripts/validate-spec.sh` — used in CI.
- `tests/run-tests.sh` (or equivalent) — wire in
  `test-wiki-ingest.sh`.

## Risks and mitigations

- **JSON extraction from CLI output is fragile.** Real `claude` /
  `codex` output is free-form text with the JSON embedded. The
  backend matches the first balanced top-level `{…}` block. If
  this proves insufficient, phase 2 stop point is the moment to
  iterate (e.g., require the prompt to wrap the JSON in a
  fenced code block and parse that).
- **CI may not have any copilot CLI installed.** Mitigated: CI
  uses `--backend test`. The default backend is exercised only
  via the shell stub fixture.
- **Python introduces a new toolchain to a Bash-dominant repo.**
  Mitigated: stdlib only, Python 3.10+ documented as requirement,
  bash entrypoint isolates the Python detail. The decision is
  deliberate (see spec.md "Requirements" #1) and is the only
  Python script in the repo for this feature.
- **Schema files are read at runtime.** A v0.3 schema patch could
  silently break prompt assembly. Mitigated: phase 1 unit tests
  load the live schema files (not pinned copies), so any breaking
  schema change surfaces in CI.
- **Proposal-file format drift.** v1 documents the proposal
  frontmatter inline; v2 should pull it into the wiki schema so
  proposals can be linted by the same script. Out of scope here.

## Rollout

1. Land this PR with the test backend exercised in CI.
2. Run the pipeline locally against three real candidates (one
   accept, one reject, one borderline) and capture observations
   in `doc_internal/dogfood-ingest-v1.md` (gitignored).
3. If the local dogfood is clean, do not extend immediately —
   wait for the next organic candidate to test the curator flow
   end-to-end.
4. v1.x: SDK backends as contributors need them.
5. v2: hooks, multi-source synthesis (potentially via RLMKit
   follow-up).
