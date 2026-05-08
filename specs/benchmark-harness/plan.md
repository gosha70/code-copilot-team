---
spec_mode: full
feature_id: benchmark-harness
risk_category: integration
justification: "New subsystem touching scripts/, benchmarks/, .github/workflows/, and tests/. External integrations: Aider Polyglot dataset (git submodule or pinned download), Claude Code headless CLI, vLLM OpenAI-compatible HTTP. Multi-phase delivery with CI smoke gate and dogfood comparison against an external public leaderboard."
status: draft
date: 2026-05-07
issue: 32
origin:
  issue: gosha70/code-copilot-team#32
  urls:
    - https://github.com/Aider-AI/polyglot-benchmark
    - https://github.com/Aider-AI/aider/blob/main/benchmark/README.md
    - https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
    - https://code.claude.com/docs/en/headless
  origin_claim: |
    See spec.md `origin:` block. Issue #32's original framing
    (custom python-fastapi-service fixture + strict rlmkit dogfood)
    was rescoped 2026-05-07 to a benchmark-agnostic harness with
    Aider Polyglot as the first public adapter.
---

# Implementation Plan — Benchmark Harness MVP

> **Origin rescope (2026-05-07).** This plan accompanies the rescoped
> spec at `specs/benchmark-harness/spec.md`. The original-issue
> framing (custom fixture authoring) is replaced; see spec § "Deviation
> from origin."

## Approach

Five phases on `feat/benchmark-harness`. Each phase ends with a reviewable commit and a working slice — the harness must be runnable end-to-end at the end of every phase, even if the only adapter is `stub` and the only backend is `stub`.

Phase 0 lays the directory layout, the adapter and backend contracts as Python protocols, and the `./scripts/benchmark` CLI skeleton. No real benchmarks, no real backends.

Phase 1 ships the stub adapter + stub backend + CI smoke test. From this point forward every PR runs the smoke test.

Phase 2 ships the Aider Polyglot adapter. Still uses stub backend for the smoke test; integration is verified locally with `claude-code:sonnet` on one task.

Phase 3 ships the Claude Code backend (`claude -p` headless) and the vLLM backend (OpenAI-compatible HTTP). Each is independently verifiable against the stub adapter and the Aider Polyglot adapter.

Phase 4 ships the report generator and the winner-declaration rule (unit-tested), then runs the dogfood gate: ≥10 Aider Polyglot tasks × `claude-code:sonnet`, leaderboard comparison + cause classification.

Each phase is a separate commit (or commit chain) reviewed and approved before the next phase starts. No phase's work begins until the previous phase's commits are reviewed.

## Phase boundaries

| Phase | Working slice                                                              | Gate                                          |
|-------|----------------------------------------------------------------------------|-----------------------------------------------|
| 0     | `./scripts/benchmark list` runs and prints `[]`                            | Code review                                   |
| 1     | `./scripts/benchmark run --benchmark stub --backend stub` produces score    | CI smoke test green                           |
| 2     | Aider Polyglot adapter loads, `list` shows tasks, stub-backend run scores  | Per-language smoke task passes via stub       |
| 3     | Claude Code + vLLM backends produce real BackendResults                    | One real `claude-code:sonnet` task scores `pass` locally |
| 4     | Report generator emits Markdown + JSON; winner rule unit-tested; dogfood   | Dogfood comparison + cause classification documented |

## Phase 0 — Scaffolding + contracts

- New tree:
  ```
  benchmarks/
    README.md
    adapters/                      # one subdir per adapter
    schema/run-record.schema.json
    schema/score.schema.json
    schema/stats.schema.json
  scripts/
    benchmark                      # bash dispatcher
    benchmark_runner/              # Python package (snake_case dir)
      __init__.py
      __main__.py                  # CLI entry
      cli.py                       # argparse + subcommands
      contracts.py                 # Adapter, Backend protocols + dataclasses
      isolation.py                 # tier resolver (worktree, worktree+venv, docker)
      run.py                       # orchestration: list/run/report subcommands
      report.py                    # mean/stdev + winner rule (skeleton)
      registry.py                  # adapter + backend discovery
      tests/
        test_contracts.py
        test_cli_skeleton.py
  ```
- `./scripts/benchmark` is a thin shell wrapper around `python -m benchmark_runner` (mirrors `scripts/wiki` style).
- No adapters or backends registered yet — `list` returns `[]`, `run` errors with "no adapter `<id>` registered."
- `benchmarks/README.md` documents the adapter + backend contracts and how to add a new one (≥1 worked example referenced even if not yet implemented).

## Phase 1 — Stub adapter + stub backend + CI smoke

- `benchmarks/adapters/stub/` ships one tiny `hello-world` task with a known-good `golden/` directory.
- Stub backend copies `golden/` into the worktree, exits 0, populates `BackendResult` with placeholder usage (`tokens_input: 0`, etc.).
- `./scripts/benchmark run --benchmark stub --backend stub --runs 1` writes a complete run record under `runs/<ts>/` and `scripts/benchmark report --run-dir runs/<ts>/` emits Markdown + JSON.
- `.github/workflows/benchmark-smoke.yml` runs the smoke command on PRs whose changeset matches the path filter:
  - `scripts/benchmark`
  - `scripts/benchmark_runner/**`
  - `benchmarks/**`
  - `specs/benchmark-harness/**`
  - `.github/workflows/benchmark-smoke.yml`

  Wall-time target <90s.
- Score schema is locked at end of Phase 1; later phases can extend `null`-safe fields but cannot rename or remove existing ones without a schema-version bump.

## Phase 2 — Aider Polyglot adapter

- `benchmarks/adapters/aider-polyglot/` contains:
  - `REVISION` — the upstream `Aider-AI/polyglot-benchmark` commit SHA the adapter is pinned to.
  - `adapter.py` — implements `BenchmarkAdapter`. Tasks are discovered by walking the upstream tree at the pinned revision.
  - `fetch.py` (or Makefile target) — clones/updates the polyglot dataset into a gitignored cache (`benchmarks/.cache/polyglot/`).
  - Per-language test commands documented in `adapter.py` constants (Python: `pytest`, Go: `go test`, JS: `npm test`, etc.).
- The two-attempt protocol is implemented in the runner, not the adapter: runner calls `prompt_for(task, attempt=1, prior=None)`, runs backend, calls `verify`, and if failed and `max_attempts() == 2`, calls `prompt_for(task, attempt=2, prior=verify_result)` and runs backend again.
- Smoke target: one Python Polyglot task verified end-to-end against the stub backend (golden patch ships from upstream's reference solutions).

## Phase 3 — Real backends

- `scripts/benchmark_runner/backends/claude_code.py`:
  - Spawns `claude -p` with the prompt + working directory; captures transcript JSON; parses final-event usage.
  - Transcript parser is a separate function with a snapshot test against a known transcript fixture.
  - Configurable model via `--backend claude-code:<model>`; defaults to `sonnet`.
- `scripts/benchmark_runner/backends/vllm.py`:
  - OpenAI-compatible HTTP client (uses stdlib `http.client` or `requests` if already in deps; will pick after auditing repo deps).
  - Endpoint URL + model from env or `--backend vllm:<model>` plus `--vllm-endpoint <url>`.
  - Token usage parsed from response `usage` block; missing fields → `null`.
- Both backends register via `registry.py`; tests use a recorded HTTP fixture (vLLM) and a recorded transcript (claude-code) — no live network calls in unit tests.

## Phase 4 — Reports + winner rule + dogfood

- `report.py` aggregates `runs/<ts>/` into:
  - `report.md` — per-task pass rate, per-language aggregate, mean/stdev across runs, A/B comparison if two backends present, winner-declaration verdict per metric.
  - `report.json` — same data, machine-readable.
- Winner-declaration rule is its own pure function with unit tests against synthetic A/B distributions (8 tests minimum: clear winner each direction, tied means, high-variance no-winner, low-variance just-below-threshold, one-sided null variance, etc.).
- Dogfood gate execution:
  1. Subset of 10–15 Aider Polyglot tasks (≥1 per language) defined in `benchmarks/adapters/aider-polyglot/dogfood-subset.txt`.
  2. Run `./scripts/benchmark dogfood --backend claude-code:sonnet --runs 1`.
  3. Compare per-language pass rate against Aider's published leaderboard for `claude-3-5-sonnet` (or current `claude-code:sonnet` equivalent).
  4. Document cause classification (harness bug / backend difference / prompt difference / agent-loop difference) in the merge commit body.

## Test strategy

- Unit tests live alongside the package (`scripts/benchmark_runner/tests/`).
- Adapter contract conformance test: any registered adapter must satisfy a stdlib `unittest` parametrized test that lists tasks, prepares one task in a tmpdir, calls verify on the prepared+golden state, and asserts pass. (Repo convention is stdlib `unittest`, mirroring `scripts/wiki_ingest/tests/`. The `pytest` mention earlier in this plan is the Polyglot adapter's *per-language verify command* — Polyglot Python tasks ship pytest test files — not the harness's own test framework.)
- Backend contract conformance test: same shape, against a recorded fixture.
- CI smoke test (live): stub × stub on GH free runner.
- The repo's existing `tests/` shell tests are not modified.

## Out of scope

Per spec § "Out of scope" — SWE-bench / LiveCodeBench / BigCodeBench / custom CCT adapters (#33), LLM-judge (#34), charts/HTML/CSV (#34), dollar-cost (deferred indefinitely).

## Risks (operational)

- **Aider Polyglot dataset is large.** Cloning the full upstream repo is fine locally but bad for CI. The CI smoke test uses the stub adapter only; the Polyglot adapter never runs in CI in this MVP.
- **Headless `claude -p` requires API auth.** The dogfood gate is run locally by the maintainer, not in CI. Document this clearly in `benchmarks/README.md`.
- **vLLM endpoint may not be reachable at dev time.** vLLM backend tests use recorded HTTP fixtures; the live integration test is documented but not gated on by CI.

## Phase-end gates (commit policy)

Each phase ends with one or more commits on `feat/benchmark-harness`, reviewed and approved before the next phase starts. No squash merging during development; the final PR may squash. No push to remote until issue-#32 acceptance criteria are met and explicit user approval is given.
