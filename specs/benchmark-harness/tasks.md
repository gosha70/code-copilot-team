# Tasks — Benchmark Harness MVP

Phased delivery on `feat/benchmark-harness`. Each task is bounded and independently verifiable. Tasks within a phase can be sequential; phases themselves must ship in order (Phase N+1 starts only after Phase N's commits are reviewed and approved).

## Phase 0 — Scaffolding + contracts

### T0.1 — Directory tree
- **Output:** `benchmarks/{README.md,adapters/.gitkeep,schema/}` and `scripts/benchmark_runner/{__init__.py,__main__.py,cli.py,contracts.py,isolation.py,run.py,report.py,registry.py,tests/__init__.py}` plus `scripts/benchmark` shell wrapper.
- **Done when:** `tree benchmarks scripts/benchmark*` matches the layout in `plan.md` § "Phase 0".

### T0.2 — Adapter + Backend protocols
- **Output:** `contracts.py` defines `TaskSpec`, `VerifyResult`, `BackendResult`, `RunContext` dataclasses and `BenchmarkAdapter`, `Backend` protocols exactly as in `spec.md` § "Adapter contract" / "Backend contract".
- **Done when:** `pytest scripts/benchmark_runner/tests/test_contracts.py` passes (instantiating the protocols + dataclasses, type-checking attribute presence).

### T0.3 — CLI skeleton
- **Output:** `cli.py` argparse with subcommands `list`, `run`, `report`, `dogfood`. `list` returns `[]` JSON when no adapters registered. `run` errors clearly on unknown adapter/backend.
- **Done when:** `./scripts/benchmark list` exits 0 with `[]`; `./scripts/benchmark run --benchmark unknown --backend unknown` exits non-zero with a readable error.

### T0.4 — Run-record + score JSON schemas
- **Output:** `benchmarks/schema/{run-record,score,stats}.schema.json` capturing the exact shapes from `spec.md`.
- **Done when:** schemas validate one hand-crafted example each (fixture under `scripts/benchmark_runner/tests/fixtures/schema/`).

### T0.5 — `benchmarks/README.md` adapter+backend authoring guide
- **Output:** README with adapter contract, backend contract, isolation tier matrix, "how to add a new adapter" walkthrough referencing the upcoming stub adapter as the worked example.
- **Done when:** README links resolve, contracts in README match `contracts.py`.

**Phase 0 commit:** `feat(benchmark): scaffold harness — contracts, CLI skeleton, schemas`

## Phase 1 — Stub adapter + stub backend + CI smoke

### T1.1 — Stub adapter
- **Output:** `benchmarks/adapters/stub/{adapter.py,tasks/hello-world/{prompt.md,verify.sh,golden/hello.txt}}`. Adapter implements `BenchmarkAdapter`; `verify` runs `verify.sh` and returns `VerifyResult(tests_passed=True)` iff `hello.txt` matches expected content.
- **Done when:** unit test asserts `adapter.list_tasks() == [TaskSpec("hello-world", "text", {})]` and `adapter.verify` returns pass on a tmpdir containing the golden file, fail on an empty tmpdir.

### T1.2 — Stub backend
- **Output:** `scripts/benchmark_runner/backends/stub.py`. `run()` shells out to `cp -r` of `adapter.golden_patch(task)` into the worktree and returns a `BackendResult` with all token fields zero.
- **Done when:** end-to-end run via stub × stub produces a pass score.

### T1.3 — Run orchestration
- **Output:** `run.py` ties together: resolve adapter → resolve backend → for each task × attempt: prepare worktree (per isolation tier), build prompt, invoke backend, verify, write `score.json` + `stats.json` under `runs/<ts>/<task>/<attempt>/`.
- **Done when:** `./scripts/benchmark run --benchmark stub --backend stub --runs 1` writes one complete run-dir; second invocation creates a sibling run-dir with a different timestamp.

### T1.4 — Report skeleton
- **Output:** `report.py` aggregates one run-dir into `report.md` + `report.json`. Winner rule stubbed to "directional, no winner declared" — real implementation lands in Phase 4.
- **Done when:** `./scripts/benchmark report --run-dir runs/<ts>/` writes both files and exits 0.

### T1.5 — CI smoke workflow
- **Output:** `.github/workflows/benchmark-smoke.yml` runs the stub × stub command on PRs whose changeset matches the path filter:
  - `scripts/benchmark`
  - `scripts/benchmark_runner/**`
  - `benchmarks/**`
  - `specs/benchmark-harness/**`
  - `.github/workflows/benchmark-smoke.yml`
- **Done when:** workflow YAML is valid; the path filter exercises a representative changed file under each listed glob (verify by adding a no-op to `scripts/benchmark_runner/run.py` on a throwaway branch and confirming the workflow triggers). Locally-simulated run (`act` or `gh workflow run` after merge) completes <90s.

**Phase 1 commit:** `feat(benchmark): stub adapter, stub backend, CI smoke test`

## Phase 2 — Aider Polyglot adapter

### T2.1 — Pinned upstream + fetch script
- **Output:** `benchmarks/adapters/aider-polyglot/REVISION` with a chosen SHA from `Aider-AI/polyglot-benchmark`. `fetch.py` (or `make polyglot-fetch`) clones at that SHA into `benchmarks/.cache/polyglot/`. Cache dir gitignored.
- **Done when:** `python -m benchmark_runner.adapters.aider_polyglot.fetch` produces a cache populated to the pinned SHA; second invocation is a no-op.

### T2.2 — Adapter implementation
- **Output:** `adapter.py` implements `BenchmarkAdapter` for Polyglot. Walks the upstream tree, classifies tasks by language directory, builds `TaskSpec(task_id="<lang>/<exercise>", language=lang, metadata={...})`. `prepare_task` copies the per-task starter files into the worktree. `prompt_for(attempt=1)` is the Aider-style coding prompt (adapted, not byte-for-byte copied — license check first); `prompt_for(attempt=2, prior=...)` includes the prior failed test output. `verify` runs the per-language test command (Python: `pytest`; Go: `go test`; JS: `npm test`; Rust: `cargo test`; Java: `mvn test` or `gradle test` per upstream layout; C++: per upstream).
- **Done when:** `./scripts/benchmark list --benchmark aider-polyglot` lists ≥200 tasks across 6 languages.

### T2.3 — Per-language verify shells
- **Output:** verify-runner that selects the right language toolchain. Worktree+venv tier handles Python; other languages assume host toolchain present (documented in README).
- **Done when:** stub backend × Polyglot adapter on one Python task produces pass; same on one Go task; same on one JS task. Stub mode uses upstream's reference solutions as `golden_patch`.

### T2.4 — Dogfood subset definition
- **Output:** `benchmarks/adapters/aider-polyglot/dogfood-subset.txt` listing 10–15 task IDs (≥1 per language) chosen for breadth + speed.
- **Done when:** every listed task ID resolves via the adapter.

**Phase 2 commit:** `feat(benchmark): Aider Polyglot adapter (pinned, multi-language)`

## Phase 3 — Real backends

### T3.1 — Claude Code backend
- **Output:** `backends/claude_code.py`. Spawns `claude -p <prompt> --cwd <worktree>` (exact flags per Claude Code headless docs at implementation time), captures stdout transcript, parses final-event usage. Transcript parser is its own function with a snapshot test.
- **Done when:** unit test against recorded transcript fixture asserts parsed `tokens_input`, `tokens_output`, `tool_calls` match expected values; smoke test passes a hand-crafted recorded transcript.

### T3.2 — vLLM backend
- **Output:** `backends/vllm.py`. OpenAI-compatible HTTP client. Reads endpoint URL from `--vllm-endpoint` flag or `CCT_VLLM_ENDPOINT` env. Captures token usage; missing fields stay `null`.
- **Done when:** unit test against recorded HTTP-response fixture asserts a successful round-trip + parse.

### T3.3 — Backend registry + selection
- **Output:** `registry.py` exposes `get_backend(spec: str) -> Backend` parsing `claude-code:<model>`, `vllm:<model>`, `stub`. Errors clearly on unknown backend.
- **Done when:** `./scripts/benchmark run --backend foo:bar` exits with a registered-backends list in the error message.

### T3.4 — Local end-to-end smoke against one Polyglot task
- **Output:** documented invocation that runs `claude-code:sonnet` against one Polyglot Python task, lands a real run record, and produces a real score. Not in CI.
- **Done when:** maintainer can paste the command from the README and observe `result: pass` in `score.json`.

**Phase 3 commit:** `feat(benchmark): Claude Code + vLLM backends`

## Phase 4 — Report + winner rule + dogfood gate

### T4.1 — Winner-declaration rule
- **Output:** `report.py:declare_winner(metric, samples_a, samples_b)` returning `"A" | "B" | "directional"`. Pure function. Lives in its own module if it grows.
- **Done when:** `test_report.py` covers ≥8 cases including: clear A win, clear B win, tied means, high-variance no-winner, low-variance just-below-1pt threshold, low-variance just-above-1pt, continuous metric (elapsed_seconds) at exactly 10%, single-run no-stdev fallback.

### T4.2 — Markdown + JSON report
- **Output:** report aggregates run-dir into per-task table, per-language summary, per-backend totals, A/B winner verdict (when 2 backends are present in the run-dir), and an explicit "directional, no winner declared" line where the rule abstains. JSON mirrors the markdown structure.
- **Done when:** sample run-dir produces a report that matches a snapshot fixture (allowing whitelisted variance: timestamps).

### T4.3 — `./scripts/benchmark dogfood`
- **Output:** subcommand that runs the Polyglot adapter against the dogfood subset for a chosen backend, emits a comparison table against a checked-in `aider-leaderboard-snapshot.json` (manually populated from Aider's published leaderboard at a specific date).
- **Done when:** dogfood subcommand runs end-to-end against `claude-code:sonnet` locally and produces the comparison report.

### T4.4 — Dogfood execution + cause classification
- **Output:** committed run-dir under `specs/benchmark-harness/dogfood/<UTC-ts>/` containing the dogfood report. Merge-commit body classifies any divergence as harness bug / backend difference / prompt difference / agent-loop difference.
- **Done when:** the run is documented and the merge commit links to it.

**Phase 4 commit chain:**
1. `feat(benchmark): winner-declaration rule + report generator`
2. `chore(benchmark): dogfood — Aider Polyglot vs leaderboard, claude-code:sonnet`

## Out of scope (issue #33 / #34)

Tasks for additional adapters, LLM-judge, charts, HTML/CSV exports, optional CCT custom-fixture adapter — see `doc_internal/benchmark-issue-2-v2.md` and `-3-v2.md`.
