# CCT Benchmark Harness

Benchmark-agnostic runner for evaluating AI copilots and LLMs on coding tasks under reproducible isolation, with deterministic scoring and SDD-aware run records.

The harness does **not** author benchmarks — it runs established public benchmarks (Aider Polyglot, SWE-bench Verified, BigCodeBench, LiveCodeBench, …) and one-off custom CCT fixtures through a single adapter contract. CCT's value is the harness, not the fixtures.

See [`specs/benchmark-harness/spec.md`](../specs/benchmark-harness/spec.md) for the full design and [`specs/benchmark-harness/plan.md`](../specs/benchmark-harness/plan.md) for the phased delivery plan.

## Status

**Phase 2** is the current phase: Aider Polyglot adapter (pinned upstream + per-language tasks), `worktree+venv` isolation tier active. `./scripts/benchmark list` shows `aider-polyglot` and `stub` as adapters, `stub` as the only backend.

| Phase | Ships                                                                          |
|-------|--------------------------------------------------------------------------------|
| 0     | Contracts, CLI skeleton, schemas, tests — done                                 |
| 1     | Stub adapter, stub backend, CI smoke test, run orchestration, report skeleton — done |
| 2     | Aider Polyglot adapter, `worktree+venv` tier — *current*                       |
| 3     | Claude Code (`claude -p`) backend with provider-routing recording              |
| 4     | Calibrated winner-declaration rule, dogfood gate                               |

## CLI

```bash
./scripts/benchmark list
./scripts/benchmark list --benchmark aider-polyglot           # Phase 1+
./scripts/benchmark run --benchmark aider-polyglot \
    --backend claude-code:sonnet --runs 3                     # Phase 1+
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
| `claude-code`    | 3     | Spawns `claude -p` headless; parses transcript usage. Provider routing via `ANTHROPIC_BASE_URL` (vLLM, Ollama, LM Studio). |

**Not a backend:** vLLM, Ollama, LM Studio, OpenRouter — these are *providers* (LLM HTTP endpoints) that backends route to via the backend's own gateway env vars. CCT records which provider a run used; it does not set the routing.

### How to add a new backend

1. Create `scripts/benchmark_runner/backends/<family>.py` implementing `Backend`. Export a `factory(model: str) -> Backend` callable.
2. Add the `register_backend(<family>, factory)` call to `scripts/benchmark_runner/_register.py:register_all`. The `<family>` is what the user types before the colon in `--backend <family>:<model>` (or alone when there is no model variant — see `stub`).
3. Document any required env vars (e.g. `CCT_VLLM_ENDPOINT`) in this README.
4. Add a backend-conformance test that drives `run()` against a recorded transcript or HTTP fixture (no live network calls in the unit tests).

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
path filter (Phase 1+). The hermetic suite stays green on a fresh
checkout with stdlib `python3` only — no network, no per-language
toolchains, no pytest, no Anthropic auth.

### Skipped tests and when to re-run them

Skipped tests cover environment-dependent paths that the hermetic CI
can't validate. They drift toward never-running unless explicitly
exercised on a documented schedule. Each skipped test below has
explicit re-run criteria — run the listed command at the listed
trigger.

| Test | Skip reason | Re-run trigger | Re-run command |
|---|---|---|---|
| `test_polyglot_adapter.py:test_python_verify_passes_with_example_solution` | Requires `pytest` on host | Pre-merge of any PR touching `benchmarks/adapters/aider_polyglot/` or `scripts/benchmark_runner/backends/claude_code.py` | `pip install pytest && PYTHONPATH=scripts:. python3 -m unittest test_polyglot_adapter -v` |
| `test_polyglot_adapter.py:test_python_verify_fails_with_starter` | Requires `pytest` on host | Same as above | Same as above |
| `test_isolation.py:test_real_pip_install_pytest` | Network + pip required | Pre-merge of PR touching `scripts/benchmark_runner/isolation.py` | `CCT_BENCHMARK_INTEGRATION=1 PYTHONPATH=scripts:. python3 -m unittest test_isolation -v` |
| `test_polyglot_dogfood_subset.py:TestDogfoodSubsetResolvesAgainstRealCache` | Requires real upstream cache | Pre-merge of PR touching `benchmarks/adapters/aider_polyglot/` (any file) | `python3 -m benchmarks.adapters.aider_polyglot.fetch && PYTHONPATH=scripts:. python3 -m unittest test_polyglot_dogfood_subset -v` |

Maintainer responsibility: when one of the trigger paths changes, the
PR description must include a paste of the re-run output (pass/fail
summary). If the PR adds a new skipped test, this table is updated in
the same PR — a skipped test without an entry here is a review
finding.

### Local manual smoke

For exercising the real `claude` CLI against the Polyglot fixture
(local-only, not in CI — see spec.md § "Dogfood gate"):

```bash
# Pull the upstream Polyglot dataset (one-time):
python3 -m benchmarks.adapters.aider_polyglot.fetch

# Run one Python task with Claude Code (default = Anthropic API):
./scripts/benchmark run --benchmark aider-polyglot \
    --backend claude-code --model sonnet --runs 1 --task python/leap

# Same task, routed through a local vLLM gateway:
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_AUTH_TOKEN=dummy
export ANTHROPIC_DEFAULT_SONNET_MODEL=<served-model-name>
./scripts/benchmark run --benchmark aider-polyglot \
    --backend claude-code --model <served-model-name> --runs 1 --task python/leap
```

Either run produces a complete record; the second path's
`backend_metadata.provider_endpoint` reflects the local URL.
