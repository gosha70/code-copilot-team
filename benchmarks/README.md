# CCT Benchmark Harness

Benchmark-agnostic runner for evaluating AI copilots and LLMs on coding tasks under reproducible isolation, with deterministic scoring and SDD-aware run records.

The harness does **not** author benchmarks — it runs established public benchmarks (Aider Polyglot, SWE-bench Verified, BigCodeBench, LiveCodeBench, …) and one-off custom CCT fixtures through a single adapter contract. CCT's value is the harness, not the fixtures.

See [`specs/benchmark-harness/spec.md`](../specs/benchmark-harness/spec.md) for the full design and [`specs/benchmark-harness/plan.md`](../specs/benchmark-harness/plan.md) for the phased delivery plan.

## Status

**Phase 0** is the current phase: scaffolding, contracts, CLI skeleton, JSON schemas. No real adapters or backends are registered yet. `./scripts/benchmark list` returns empty arrays.

| Phase | Ships                                                                          |
|-------|--------------------------------------------------------------------------------|
| 0     | Contracts, CLI skeleton, schemas, tests — *current*                            |
| 1     | Stub adapter, stub backend, CI smoke test                                      |
| 2     | Aider Polyglot adapter (multi-language)                                        |
| 3     | Claude Code (`claude -p`) and vLLM (OpenAI-compatible HTTP) backends           |
| 4     | Report aggregator, winner-declaration rule, dogfood gate vs Aider leaderboard  |

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
3. Register the adapter via `register_adapter(<id>, factory)` in your module's import side-effects, or via an explicit registration hook (Phase 1 will document the chosen pattern).
4. Add at least one task that the stub backend can satisfy via `golden_patch`.
5. Add adapter-conformance tests under `scripts/benchmark_runner/tests/`.

## Backend contract

```python
class Backend(Protocol):
    backend_id: str
    def run(self, prompt: str, ctx: RunContext) -> BackendResult: ...
```

The MVP ships three backends (Phases 1 + 3):

| Backend          | Phase | Description                                                                  |
|------------------|-------|------------------------------------------------------------------------------|
| `stub`           | 1     | Copies `golden_patch` into the worktree; CI smoke test only.                 |
| `claude-code:<m>`| 3     | Spawns `claude -p` headless; parses transcript usage.                        |
| `vllm:<model>`   | 3     | OpenAI-compatible HTTP against a configured vLLM endpoint.                   |

### How to add a new backend

1. Create `scripts/benchmark_runner/backends/<family>.py` implementing `Backend`.
2. `register_backend(<family>, factory)` — the factory takes the model spec (the part after the colon in `<family>:<model>`).
3. Document any required env vars (e.g. `CCT_VLLM_ENDPOINT`) in this README.
4. Add a backend-conformance test that drives `run()` against a recorded transcript or HTTP fixture (no live network calls in the unit tests).

## Isolation tiers

```yaml
isolation:
  tier: worktree                 # cheap; copies adapter-prepared files into a git worktree
  # or:
  tier: worktree+venv
  python: "3.12"
  install_command: "pip install -e .[dev]"
  # or:
  tier: docker
  dockerfile: <path>
  build_args: {}
```

All three tiers are in the schema from Phase 0. Implementation lands per phase: `worktree` and `worktree+venv` in Phases 1–2; `docker` lands when issue #33's SWE-bench Verified adapter ships.

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
PYTHONPATH=scripts python3 -m unittest discover -s scripts/benchmark_runner/tests -v
```

CI runs the same discovery on every PR matching the smoke workflow's path filter (Phase 1+).
