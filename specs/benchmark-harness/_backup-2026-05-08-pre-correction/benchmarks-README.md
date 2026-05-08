# CCT Benchmark Harness

Benchmark-agnostic runner for evaluating AI copilots and LLMs on coding tasks under reproducible isolation, with deterministic scoring and SDD-aware run records.

The harness does **not** author benchmarks — it runs established public benchmarks (Aider Polyglot, SWE-bench Verified, BigCodeBench, LiveCodeBench, …) and one-off custom CCT fixtures through a single adapter contract. CCT's value is the harness, not the fixtures.

See [`specs/benchmark-harness/spec.md`](../specs/benchmark-harness/spec.md) for the full design and [`specs/benchmark-harness/plan.md`](../specs/benchmark-harness/plan.md) for the phased delivery plan.

## Status

**Phase 3** is the current phase: real Claude Code (`claude --bare -p`) and vLLM (OpenAI-compatible HTTP) backends are wired up and tested end-to-end against committed fixtures. `./scripts/benchmark list` shows `aider-polyglot` and `stub` as adapters, `stub`, `vllm`, and `claude-code` as backends.

| Phase | Ships                                                                          |
|-------|--------------------------------------------------------------------------------|
| 0     | Contracts, CLI skeleton, schemas, tests — done                                 |
| 1     | Stub adapter, stub backend, CI smoke test, run orchestration, report skeleton — done |
| 2     | Aider Polyglot adapter, `worktree+venv` tier, vLLM backend stub — done         |
| 3     | Claude Code (`claude --bare -p`) backend + real vLLM (OpenAI-compatible HTTP) backend — *current* |
| 4     | Calibrated winner-declaration rule, dogfood gate vs Aider leaderboard          |

## CLI

```bash
./scripts/benchmark list
./scripts/benchmark list --benchmark aider-polyglot           # Phase 1+
./scripts/benchmark run --benchmark aider-polyglot \
    --backend claude-code:sonnet --runs 3                     # Phase 1+
./scripts/benchmark run --benchmark aider-polyglot \
    --backend vllm:<model> --runs 3                           # Phase 3+
./scripts/benchmark report --run-dir runs/<UTC-ts>/           # Phase 1+
./scripts/benchmark dogfood --backend claude-code:sonnet      # Phase 4
```

Exit codes (stable across the MVP):
- `0` — success.
- `2` — usage error (argparse) or unknown adapter / backend.
- `8` — subcommand or feature not yet implemented (Phase N stub).

## Adapter contract

A benchmark adapter is a Python module exposing the `BenchmarkAdapter` protocol from `scripts/benchmark_runner/contracts.py`:

```python
class BenchmarkAdapter(Protocol):
    benchmark_id: str
    isolation_default: Literal["worktree", "worktree+venv", "docker"]

    def list_tasks(self) -> list[TaskSpec]: ...
    def prepare_task(self, task: TaskSpec, worktree: Path) -> None: ...
    def prompt_for(self, task: TaskSpec, attempt: int, prior: VerifyResult | None) -> str: ...
    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult: ...
    def golden_patch(self, task: TaskSpec) -> Path: ...
    def max_attempts(self) -> int: ...
```

The adapter owns "what is a task in this benchmark and how do I check it." The harness owns isolation, run records, scoring, and reports.

`max_attempts()` returns `1` for single-shot adapters (SWE-bench-style) and `2` for Aider-style two-shot retry, where `prompt_for(attempt=2, prior=...)` includes the failed first-attempt test output. Adapters with no golden patch raise `NotImplementedError` from `golden_patch` — the runner refuses to run those tasks under the stub backend.

### How to add a new adapter

1. Create `benchmarks/adapters/<your-id>/adapter.py` implementing `BenchmarkAdapter`.
2. Pin any external dataset by SHA in `benchmarks/adapters/<your-id>/REVISION`.
3. Expose a module-level `register()` function that calls `register_adapter(<id>, AdapterClass)`. Do **not** call `register_adapter` at module import time — Python imports each module only once per process, so an import-time side-effect would break test isolation when the registry is reset between cases. See `benchmarks/adapters/stub/adapter.py` for the worked example.
4. Add the new `register()` call to `scripts/benchmark_runner/_register.py:register_all` — the single place where the production set of adapters is wired up.
5. Add at least one task that the stub backend can satisfy via `golden_patch`.
6. Add adapter-conformance tests under `scripts/benchmark_runner/tests/`.

## Backend contract

```python
class Backend(Protocol):
    backend_id: str
    def run(self, prompt: str, ctx: RunContext) -> BackendResult: ...
```

The MVP ships these backends:

| Backend          | Phase | Description                                                                                         |
|------------------|-------|-----------------------------------------------------------------------------------------------------|
| `stub`           | 1     | Copies `golden_patch` into the worktree; CI smoke test only.                                        |
| `claude-code:<m>`| 3     | Spawns `claude --bare -p` headless in the worktree, parses the JSON transcript, captures usage. File editing is delegated to Claude Code's internal Edit tool — this backend doesn't extract files from text output. Requires the `claude` CLI on `PATH` and `ANTHROPIC_API_KEY` (or another configured auth path; `--bare` skips OAuth/keychain reads). |
| `vllm:<model>`   | 3     | OpenAI-compatible HTTP client (zero-dep stdlib). Sends Chat Completions, parses `usage`, and applies the model's text response to the worktree using whole-file fenced blocks (see "vLLM file-edit format" below). Endpoint via `$CCT_VLLM_ENDPOINT` or `--vllm-endpoint`. Optional bearer token via `$CCT_VLLM_API_KEY`. |

### How to add a new backend

1. Create `scripts/benchmark_runner/backends/<family>.py` implementing `Backend`. Export a `factory(model: str) -> Backend` callable.
2. Add the `register_backend(<family>, factory)` call to `scripts/benchmark_runner/_register.py:register_all`. The `<family>` is what the user types before the colon in `--backend <family>:<model>` (or alone when there is no model variant — see `stub`).
3. Document any required env vars (e.g. `CCT_VLLM_ENDPOINT`) in this README.
4. Add a backend-conformance test that drives `run()` against a recorded transcript or HTTP fixture (no live network calls in the unit tests).

### vLLM file-edit format

Because the vLLM backend speaks plain Chat Completions (it has no edit tool of its own), the model returns text and the harness has to apply that text to the worktree. The format is whole-file fenced blocks:

```
--- BEGIN FILE: <relative-path> ---
```<language>
<full file contents>
```
--- END FILE: <relative-path> ---
```

Rules the backend appends to every adapter prompt:

- The block markers must appear on their own lines, top of column, no leading or trailing whitespace.
- `<relative-path>` must match a solution file from the prompt and must NOT escape the worktree (`..`, absolute paths are refused with `VllmFileApplyError`).
- The body between the triple-backtick fences is written verbatim — no diff applied, no merge attempted. The file is overwritten in full.
- `<language>` is purely a syntax-highlighting hint; the harness ignores it.
- Mismatched begin/end paths cause that block to be silently skipped (defensive; never write to a path the model didn't really mean).

Aider-style search/replace diffs are a candidate replacement format for a future iteration if SWE-bench (issue #33) needs partial-file edits on large files.

### End-to-end smoke (manual, not CI)

After running the Polyglot fetch script, the harness can be exercised against a real Python task with either backend. These commands are local-only — neither runs in CI (the smoke workflow uses stub × stub).

Pull the upstream Polyglot dataset:

```bash
python3 -m benchmarks.adapters.aider_polyglot.fetch
```

Run one Python task with Claude Code (requires `ANTHROPIC_API_KEY` or a logged-in Claude Code CLI):

```bash
./scripts/benchmark run \
  --benchmark aider-polyglot \
  --backend claude-code:sonnet \
  --runs 1 \
  --task python/leap

./scripts/benchmark report --run-dir runs/<UTC-ts>-aider-polyglot-claude-code-001/
```

Run the same task with a local vLLM endpoint:

```bash
export CCT_VLLM_ENDPOINT=http://localhost:8000          # or pass --vllm-endpoint
export CCT_VLLM_API_KEY=optional-bearer-token-if-needed

./scripts/benchmark run \
  --benchmark aider-polyglot \
  --backend vllm:meta-llama/Meta-Llama-3.1-70B-Instruct \
  --runs 1 \
  --task python/leap
```

Expected outcome (Polyglot's `python/leap` is straightforward enough for a frontier model): `score.json` shows `"result": "pass"`, `tests_passed: true`, and the run-dir contains `prompt.md`, `transcript.json` (Claude Code) or `vllm-request.json` + `vllm-response.json` (vLLM), and a `worktree/leap.py` reflecting the model's edits.

## Isolation tiers

```yaml
isolation:
  tier: worktree                 # cheap; clean per-attempt directory
  # or:
  tier: worktree+venv
  python: "python3"              # interpreter to use for `python -m venv`
  install_command: "pip install -q pytest"
  # or:
  tier: docker
  dockerfile: <path>
  build_args: {}
```

The runner provisions one worktree per attempt under
`runs/<ts>-<benchmark>-<backend>-NNN/<task>/<attempt>/worktree/`. For
the `worktree+venv` tier (Phase 2), it also creates a `.venv/` inside
the worktree, runs the configured `install_command` with the venv's
`bin/` at the front of `PATH`, and the verify path looks for
`worktree/.venv/bin/python` and `worktree/.venv/bin/pytest` before
falling back to the host toolchain. The `docker` tier is reserved
for issue #33's SWE-bench Verified adapter; calling it raises
`NotImplementedError`.

Per-task isolation is declared by the adapter's
`isolation_for(task) -> IsolationConfig`. Adapters that don't vary
per task return `IsolationConfig(tier=self.isolation_default)`. The
Aider Polyglot adapter overrides this to use `worktree+venv` for
Python tasks (so `pytest` lives inside the worktree, not on the
host) and `worktree` for the other five languages (which assume the
host has `go`, `cargo`, `gradle`, `npm`, and `cmake`/`make`/a C++
compiler installed; this is documented as a host-toolchain
requirement).

## Run-record layout

```
runs/<UTC-ts>-<benchmark>-<backend>/
  <task-id-slug>/
    <attempt>/
      run-record.json         # see benchmarks/schema/run-record.schema.json
      score.json              # see benchmarks/schema/score.schema.json
      stats.json              # see benchmarks/schema/stats.schema.json
      prompt.md               # canonical prompt the harness handed the backend
                              #   (output of adapter.prompt_for); sha256 in run-record.json
      effective-prompt.md     # optional: post-wrap prompt the backend actually sent
                              #   (Claude Code's system prompt + user prompt, etc.);
                              #   present only when BackendResult.prompt_path is set
      model-output.txt        # optional: model's raw text response
                              #   (path also recorded in run-record.json)
      transcript.jsonl        # optional, backend-specific structured log
      diff.patch              # post-attempt minus pre-attempt
```

The `prompt.md` artifact is **always** written by the runner before invoking the backend; its path + sha256 are required fields in `run-record.json`. This means every recorded run is audit-traceable — a sha256 mismatch across runs flags prompt drift before it confounds backend comparisons.

Schemas under `benchmarks/schema/` are the single source of truth. Examples live alongside the schema tests at `scripts/benchmark_runner/tests/fixtures/schema/`.

## Determinism

```yaml
backend_invocation:
  temperature: 0       # default
  seed: <int | null>   # optional; recorded in stats.json
```

Backends that don't support seeding record `seed: null`. The report flags such comparisons "higher-variance," and the winner-declaration rule (Phase 4) protects against false positives.

## What this harness deliberately does not do

- **No dollar-cost reporting.** The `cost_reporting.enabled` field in `stats.json` is permanently `false`. Cross-provider billing correlation is not solved; estimates would mislead. See `specs/benchmark-harness/spec.md` § Constraints.
- **No LLM-judge scoring in the MVP.** Issue #34 adds calibrated judge scoring on top of deterministic scoring, gated on a 50–100-sample human-labeled calibration set.
- **No HTML / charts / CSV reports in the MVP.** Markdown + JSON only. Issue #34 adds rich reports.
- **No custom application fixtures as the foundation.** The MVP's first public adapter is Aider Polyglot precisely so we ride a published leaderboard for sanity. Custom CCT fixtures (e.g. `cct-dogfood-rlmkit-llm-wiki-backbone`) are one adapter among several in issue #33, never the centerpiece.

## Running the tests

```bash
PYTHONPATH=scripts:. python3 -m unittest discover -s scripts/benchmark_runner/tests -v
```

CI runs the same discovery on every PR matching the smoke workflow's
path filter (Phase 1+). A handful of tests are skipped by default:

- Tests that require `pytest` to be installed on the host (Phase 2c
  removes the need for a host-installed `pytest` for the Polyglot
  Python verify path; integration coverage there relies on the venv
  tier described above).
- Real-pip integration coverage of the venv tier
  (`test_isolation.py:test_real_pip_install_pytest`). To run it,
  set `CCT_BENCHMARK_INTEGRATION=1`. Otherwise the suite is
  hermetic — no network calls, no per-language toolchains required
  beyond stdlib `python3` for the venv-creation tests.
