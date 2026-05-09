# Tasks — Benchmark Harness MVP

Phased delivery on `feat/benchmark-harness`. Each task is bounded and independently verifiable. Tasks within a phase can be sequential; phases themselves must ship in order (Phase N+1 starts only after Phase N's commits are reviewed and approved).

## Phase 0 — Scaffolding + contracts

### T0.1 — Directory tree
- **Output:** `benchmarks/{README.md,adapters/.gitkeep,schema/}` and `scripts/benchmark_runner/{__init__.py,__main__.py,cli.py,contracts.py,isolation.py,run.py,report.py,registry.py,tests/__init__.py}` plus `scripts/benchmark` shell wrapper.
- **Done when:** `tree benchmarks scripts/benchmark*` matches the layout in `plan.md` § "Phase 0".

### T0.2 — Adapter + Backend protocols
- **Output:** `contracts.py` defines `TaskSpec`, `VerifyResult`, `BackendResult`, `RunContext` dataclasses and `BenchmarkAdapter`, `Backend` protocols exactly as in `spec.md` § "Adapter contract" / "Backend contract".
- **Done when:** `PYTHONPATH=scripts python3 -m unittest discover -s scripts/benchmark_runner/tests -v` passes (instantiating the protocols + dataclasses, type-checking attribute presence). Repo convention is stdlib `unittest`, matching `scripts/wiki_ingest/tests/`.

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

## Phase 3 — Claude Code backend with provider-routing recording

### T3.1 — Claude Code backend
- **Output:** `backends/claude_code.py`. Spawns `claude -p <prompt>` in the worktree (no `--bare` by default — measures real product behavior with full autodiscovery + OAuth/keychain auth), captures stdout transcript, parses final-event usage. Model passed via `--model <id>` (separate flag from `--backend`). Transcript parser is its own function with a snapshot test.
- **Done when:** unit test against committed transcript fixtures asserts parsed `tokens_input`, `tokens_output`, `tool_calls` match expected values; the fake-`claude`-shim test asserts the backend invokes the CLI with the right argv, sends the prompt on stdin, sets cwd to the worktree, and writes the transcript + model-output files.

### T3.2 — Provider-routing record (replaces the discarded vLLM backend)
- **Output:** Claude Code backend reads `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN_present` (boolean only — never the value), and the `claude_code_invocation` mode (`"launcher" | "bare"`) at run time and writes them into `BackendResult.backend_metadata`. The harness does NOT have a `--vllm-endpoint`-style flag — provider routing is set by the user in their shell, recorded by the harness.
- **Done when:** with `ANTHROPIC_BASE_URL` set in the env, a run's `run-record.json["backend"]["metadata"]["provider_endpoint"]` reflects the value; with it unset, the field is `null`. With `CCT_CLAUDE_BARE=1`, `claude_code_invocation` is `"bare"` and `--bare` appears in the actual argv; otherwise `"launcher"` and no `--bare` flag.

### T3.3 — Backend registry + selection
- **Output:** `registry.py` exposes `get_backend(family: str, model: str) -> Backend`. The CLI parses `--backend <family> --model <id>` (separate flags). Errors clearly on unknown backend family with the registered-families list in the error.
- **Done when:** `./scripts/benchmark run --backend nope --model sonnet` exits with a registered-families list in the error message.

### T3.4 — Local end-to-end smoke against one Polyglot Python task
- **Output:** documented invocation that runs `claude-code --model sonnet` against one Polyglot Python task, lands a real run record, and produces a real score. README documents a parallel example showing the same command with `ANTHROPIC_BASE_URL` set to a local vLLM/Ollama gateway. Not in CI.
- **Done when:** maintainer can paste the command from the README and observe `result: pass` in `score.json`. With the gateway env var set, `backend_metadata.provider_endpoint` reflects the local URL.

**Phase 3 commit:** `feat(benchmark): Claude Code backend with provider-routing recording`

## Phase 4 — Report + winner rule + dogfood gate

### T4.1 — Winner-declaration rule
- **Output:** `report.py:declare_winner(metric, samples_a, samples_b)` returning `"A" | "B" | "directional"`. Pure function. Lives in its own module if it grows.
- **Done when:** `test_report.py` covers ≥8 cases including: clear A win, clear B win, tied means, high-variance no-winner, low-variance just-below-1pt threshold, low-variance just-above-1pt, continuous metric (elapsed_seconds) at exactly 10%, single-run no-stdev fallback.

### T4.2 — Markdown + JSON report
- **Output:** report aggregates run-dir into per-task table, per-language summary, per-(backend, model) totals, A/B winner verdict (when 2+ (backend, model) tuples are present in the run-dir), and an explicit "directional, no winner declared" line where the rule abstains. Reports surface `backend_metadata.provider_endpoint` so mixed-provider runs are visible. JSON mirrors the markdown structure.
- **Done when:** sample run-dir produces a report that matches a snapshot fixture (allowing whitelisted variance: timestamps).

### T4.3 — `./scripts/benchmark dogfood`
- **Output:** subcommand that runs the Polyglot adapter against the dogfood subset for a chosen backend (`claude-code --model sonnet` for the MVP). Emits a Markdown summary of the run-dir. **No** Aider-leaderboard comparison (apples-to-oranges; see spec.md § Dogfood gate).
- **Done when:** dogfood subcommand runs end-to-end against `claude-code --model sonnet` locally and produces a run-dir + summary.

### T4.4 — Dogfood Gate 1 execution (liveness)
- **Output:** committed run-dir under `specs/benchmark-harness/dogfood/<UTC-ts>-liveness/`. Merge-commit body cause-classifies any task failures (harness bug / backend agent-loop / provider-side / model-side).
- **Done when:** the run is documented and the merge commit links to it.

### T4.5 — Dogfood Gate 2 (memkernel#3 spec-first dogfood — load-bearing)
- **Output:**
  - `benchmarks/adapters/cct_dogfood_memkernel/` — fixture that snapshots memkernel at a pinned SHA (REVISION file) and exposes one task `memory-brain-spec`. Adapter implements `BenchmarkAdapter` with `max_attempts=1`. Calibration infra under the spec.md § Constraints carve-out; whether the fixture is refreshed, archived, or removed after #32 merges is a future-maintainer decision out of scope for this issue.
  - `specs/benchmark-harness/dogfood/<UTC-ts>-memkernel-spec/` — committed run-dir from `./scripts/benchmark run --benchmark cct-dogfood-memkernel --backend claude-code --model sonnet --runs 3`.
  - Comparison record: maintainer's per (run, attempt) human verdict on the produced `specs/memory-brain/spec.md` vs. harness `tests_passed`. Recorded inline in the merge commit body (3 rows for `--runs 3`).
  - Cause classification of any divergences in the merge commit body: verify.sh too lenient / verify.sh too strict / human rubric not deterministically checkable / model regression / harness bug.

- **Required input artifacts (maintainer-supplied; not derivable from this spec):**
  1. **`benchmarks/adapters/cct_dogfood_memkernel/tasks/memory-brain-spec/prompt.md`** — the verbatim memkernel#3 issue body. The adapter's `prompt_for` wraps it with a small framing header (working-directory note + deliverable path + scope guard) so the agent has the operational context without modifying the issue text.
  2. **`benchmarks/adapters/cct_dogfood_memkernel/tasks/memory-brain-spec/acceptance.md`** + **`verify.sh`** — the deterministic checks that map onto `VerifyResult`. Hard checks (must pass): `specs/memory-brain/spec.md` exists; the seven section headers from memkernel#3 §7 are present; `pyproject.toml` byte-for-byte unchanged from baseline; `src/memkernel/mcp/` byte-for-byte unchanged from baseline. Best-effort checks (skipped if toolchain absent, otherwise must pass): `ruff check`, `mypy src/`, `pytest`. Best-effort because memkernel's runtime stack (chromadb, sentence-transformers, tree-sitter) is heavy and slow to install in a fresh per-attempt venv; static spec-correctness is the load-bearing assertion.
  3. **`benchmarks/adapters/cct_dogfood_memkernel/REVISION`** — the pinned memkernel SHA that the adapter snapshots via `git archive`. Updating this file rebases the dogfood gate against a newer memkernel commit.

  These three artifacts plus the host's memkernel clone (default `~/dev/repo/memkernel`, override via `CCT_MEMKERNEL_PATH`) are maintainer knowledge: which memkernel revision is the calibration target, the verbatim issue body, and the deterministic acceptance checks. They are NOT derivable from anything in this spec or the harness code, and the v3 rlmkit-retrospective plan is not directly portable (the rlmkit gist's per-case verdicts have no analogue in a single forward-looking task — see plan.md Phase 4 step 4 on the per-(run, attempt) calibration unit).

- **Done when:** verdict-class match on ≥80% of (run, attempt) pairs (3 pairs at `--runs 3`, so 3/3 in practice) AND the run-dir is committed AND any divergence is cause-classified. This is the load-bearing merge gate — a running harness that produces wrong verdicts fails this gate even if Gate 1 (T4.4) passes.

**Phase 4 commit chain:**
1. `feat(benchmark): winner-declaration rule + report generator`
2. `chore(benchmark): dogfood Gate 1 — Aider Polyglot run-to-completion, claude-code --model sonnet`
3. `chore(benchmark): dogfood Gate 2 — memkernel#3 spec-first verdict-correctness`

## Out of scope (issue #33 / #34)

- Additional benchmark adapters (SWE-bench Verified, BigCodeBench, LiveCodeBench, CCT-custom dogfood) — issue #33.
- **Additional copilot backends** (Aider, Codex, GitHub Copilot CLI) — issue #33 as Phase 4 candidates.
- LLM-judge, charts, HTML/CSV exports — issue #34.

See `doc_internal/benchmark-issue-2-v3.md` and `-3-v3.md` for the v3 issue body drafts.

## Out of scope entirely (not deferred — never)

- vLLM/Ollama/LM Studio as **backends** — they are *providers*, configured per-backend via that backend's gateway env vars (e.g. `ANTHROPIC_BASE_URL` for Claude Code). The harness records the provider env vars; it does not set them.
- Cursor / Windsurf as backends — GUI-only, no headless agent loop.
- Per-run `--vllm-endpoint` / `--provider` CLI flags — provider routing is a shell-environment concern; the harness reads the env, doesn't set it.
- Dollar-cost reporting — permanently deferred until cross-provider billing-correlation is solved.
