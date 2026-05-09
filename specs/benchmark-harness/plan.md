---
spec_mode: full
feature_id: benchmark-harness
risk_category: integration
justification: "New subsystem touching scripts/, benchmarks/, .github/workflows/, and tests/. External integrations: Aider Polyglot dataset (git submodule or pinned download), Claude Code headless CLI (which itself can route to vLLM/Ollama/LM Studio via the Anthropic-Messages gateway). Multi-phase delivery with CI smoke gate and a run-to-completion dogfood gate. v3 (2026-05-08): backends are copilot agents, providers are LLM endpoints; the harness records provider env vars but does not set them."
status: draft
date: 2026-05-07
issue: 32
origin:
  issue: gosha70/code-copilot-team#32
  urls:
    - https://github.com/Aider-AI/polyglot-benchmark
    - https://github.com/Aider-AI/aider/blob/main/benchmark/README.md
    - https://code.claude.com/docs/en/llm-gateway
    - https://docs.vllm.ai/en/stable/serving/integrations/claude_code/
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

Phase 2 ships the Aider Polyglot adapter. Still uses stub backend for the smoke test; integration is verified locally with `claude-code --model sonnet` on one task.

Phase 3 ships the Claude Code backend (`claude -p` headless via the launcher; `CCT_CLAUDE_BARE=1` opts into `--bare`). The harness records `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN_present`, and `claude_code_invocation` in `backend_metadata` so reports distinguish Anthropic-API runs from gateway-routed runs (vLLM/Ollama/LM Studio served via Claude Code's [LLM gateway support](https://code.claude.com/docs/en/llm-gateway)).

Additional copilot backends (Aider, Codex, GitHub Copilot CLI) are scoped into issue #33 as Phase 4 candidates — each requires independent verification of its headless-invocation surface. The earlier "Phase 3 vLLM backend" plan is dropped (v3 correction): vLLM is a *provider*, configured via Claude Code's gateway env vars, not a peer backend.

Phase 4 ships the report generator, the winner-declaration rule (unit-tested), and **both dogfood gates**: (1) liveness — ≥10 Aider Polyglot tasks × `claude-code --model sonnet` running to completion; (2) verdict correctness — `cct-dogfood-rlmkit` fixture (throwaway, replaced by issue #33's adapter suite) with harness verdict compared to the gist's human-rubric verdict on rlmkit#38/#41. Gate 2 is the load-bearing one: a running harness that produces wrong verdicts is worse than no harness.

Each phase is a separate commit (or commit chain) reviewed and approved before the next phase starts. No phase's work begins until the previous phase's commits are reviewed.

## Phase boundaries

| Phase | Working slice                                                              | Gate                                          |
|-------|----------------------------------------------------------------------------|-----------------------------------------------|
| 0     | `./scripts/benchmark list` runs and prints `[]`                            | Code review                                   |
| 1     | `./scripts/benchmark run --benchmark stub --backend stub` produces score    | CI smoke test green                           |
| 2     | Aider Polyglot adapter loads, `list` shows tasks, stub-backend run scores  | Per-language smoke task passes via stub       |
| 3     | Claude Code backend produces real BackendResults; provider env vars logged | One real `claude-code --model sonnet` task scores `pass` locally |
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

## Phase 3 — Claude Code backend with provider-routing recording

- `scripts/benchmark_runner/backends/claude_code.py`:
  - Spawns `claude -p` (no `--bare` by default — measures real product behavior with full autodiscovery + OAuth/keychain auth) with the prompt + working directory; captures transcript JSON; parses final-event usage.
  - Transcript parser is a separate function with a snapshot test against committed transcript fixtures.
  - Model passed via `--model <id>` (separated from `--backend` per the v3 CLI surface): `--backend claude-code --model sonnet`.
  - **Provider routing recorded, not set.** The backend reads `ANTHROPIC_BASE_URL`, presence of `ANTHROPIC_AUTH_TOKEN` (boolean only — never the value), and the chosen invocation mode (`launcher` | `bare`) at run time and writes them into `backend_metadata`. The user is responsible for setting these env vars in their shell (e.g. to point at a local vLLM or Ollama gateway). The harness does NOT have a `--vllm-endpoint`-style flag; provider routing is a shell-environment concern, not a CCT CLI concern.
  - Opt-in to `--bare` via `CCT_CLAUDE_BARE=1` env var (deterministic CI use; skips OAuth/keychain, requires `ANTHROPIC_API_KEY`).
- Tests use recorded transcript fixtures + a fake `claude` CLI shim — no live `claude -p` calls or network in unit tests. A separate, documented manual smoke (T3.4) exercises the real CLI locally.

(Phase 3 originally also included a vLLM backend with raw OpenAI Chat Completions + a fenced-block file-edit format. Both are dropped in v3 — vLLM is a *provider*, configured via Claude Code's gateway env vars; the file-edit format problem doesn't exist when Claude Code does the file editing internally via its Edit tool.)

## Phase 4 — Reports + winner rule + dogfood

- `report.py` aggregates `runs/<ts>/` into:
  - `report.md` — per-task pass rate, per-language aggregate, mean/stdev across runs, A/B comparison if two backends present, winner-declaration verdict per metric.
  - `report.json` — same data, machine-readable.
- Winner-declaration rule is its own pure function with unit tests against synthetic A/B distributions (8 tests minimum: clear winner each direction, tied means, high-variance no-winner, low-variance just-below-threshold, one-sided null variance, etc.).
- Dogfood Gate 1 (liveness):
  1. Subset of 10–15 Aider Polyglot tasks (≥1 per language) defined in `benchmarks/adapters/aider_polyglot/dogfood-subset.txt`.
  2. Run `./scripts/benchmark dogfood --backend claude-code --model sonnet --runs 1`.
  3. Commit the produced run-dir under `specs/benchmark-harness/dogfood/<UTC-ts>-liveness/`.
  4. Cause-classify any task failures (harness bug / backend agent-loop / provider-side / model-side) in the merge commit.

  (Earlier draft compared per-language pass rate against Aider's published Polyglot leaderboard. Dropped in v3 — Aider's leaderboard is Aider-the-agent, not Claude Code; not apples-to-apples.)

- Dogfood Gate 2 (verdict correctness — rlmkit#38/#41 retrospective):
  1. Build a small `cct-dogfood-rlmkit` fixture under `benchmarks/adapters/cct_dogfood_rlmkit/` that approximates rlmkit#37 (deterministic tests + lint + required-files checks).
  2. Run `./scripts/benchmark run --benchmark cct-dogfood-rlmkit --backend claude-code --model sonnet --runs 1`.
  3. Compare harness verdict (`tests_passed`, `result`) to the human-rubric verdict in the gist `https://gist.github.com/gosha70/6fbf6dcf8e84a8110c431331c628d344`.
  4. Pass criteria: verdict-class match on ≥80% of labeled cases. Below 80%, document divergence cause (harness can't model task / human-rubric criteria not deterministically checkable / model regression / harness bug).
  5. Commit the run-dir under `specs/benchmark-harness/dogfood/<UTC-ts>-rlmkit-retrospective/`.
  6. The fixture is throwaway — issue #33 replaces it.

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
- **Gateway provider may not be reachable at dev time.** Tests against the Claude Code backend use a fake `claude` CLI shim and recorded transcripts; live `claude -p` (whether against Anthropic API or a local gateway) is exercised only in the documented manual smoke and the dogfood gate. CI never makes live network calls.

## Phase-end gates (commit policy)

Each phase ends with one or more commits on `feat/benchmark-harness`, reviewed and approved before the next phase starts. No squash merging during development; the final PR may squash. No push to remote until issue-#32 acceptance criteria are met and explicit user approval is given.
