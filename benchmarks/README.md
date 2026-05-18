# CCT Benchmark Harness

Benchmark-agnostic runner for evaluating AI copilots and LLMs on coding tasks under reproducible isolation, with deterministic scoring and SDD-aware run records.

The harness does **not** author benchmarks — it runs established public benchmarks (Aider Polyglot, SWE-bench Verified, BigCodeBench, LiveCodeBench, …) and one-off custom CCT fixtures through a single adapter contract. CCT's value is the harness, not the fixtures.

See [`specs/benchmark-harness/spec.md`](../specs/benchmark-harness/spec.md) for the full design and [`specs/benchmark-harness/plan.md`](../specs/benchmark-harness/plan.md) for the phased delivery plan.

## Quick start: compare multiple LLMs

You have a benchmark (say, Aider Polyglot) and you want to know which LLM does best on it. The `compare` subcommand takes a JSON config listing N candidate LLMs and runs them sequentially under one shared run-dir, then aggregates a Markdown report with mean ± stdev per metric and the calibrated winner verdict.

### 1. Make sure your backend is authenticated

The harness *records* which provider an LLM run uses; it never *sets* the provider. Configuration happens through the backend's own gateway env vars. For Claude Code (the only copilot backend in the MVP — see issue #33 for Aider/Codex/GH-Copilot CLI):

- **Anthropic API (default)**: `claude login` once, or set `ANTHROPIC_API_KEY` in your shell.
- **Local LLM via vLLM**: spin up vLLM with its Anthropic-compatible endpoint (`vllm serve <model> --enable-anthropic-api`) and use the `env` block in the compare config to point Claude Code at it.
- **Local LLM via Ollama**: same pattern; Ollama exposes an Anthropic-compatible endpoint on `http://localhost:11434`.
- **LM Studio, OpenRouter, etc.**: same pattern; whatever URL the gateway serves goes into `ANTHROPIC_BASE_URL`.

See [Claude Code's LLM gateway docs](https://code.claude.com/docs/en/llm-gateway) for the full env-var set.

### 2. Pick a benchmark and fetch its dataset

```bash
./scripts/benchmark list
# {
#   "adapters": ["aider-polyglot", "cct-dogfood-memkernel", "stub"],
#   "backends": ["claude-code", "stub"]
# }

# Aider Polyglot needs a one-time clone of the upstream dataset (pinned by SHA):
python3 -m benchmarks.adapters.aider_polyglot.fetch

./scripts/benchmark list --benchmark aider-polyglot
# Lists every (language, exercise) the adapter exposes.
```

### 3. Write a compare config

Copy [`benchmarks/compare-config.example.json`](compare-config.example.json) as a starting point. Minimal shape:

```json
{
  "benchmark": "aider-polyglot",
  "runs": 3,
  "task": ["python/leap", "go/leap", "rust/leap"],
  "candidates": [
    { "name": "sonnet",   "backend": "claude-code", "model": "sonnet" },
    { "name": "opus",     "backend": "claude-code", "model": "opus"   },
    {
      "name": "llama3-vllm",
      "backend": "claude-code",
      "model": "meta-llama/Llama-3-70B-Instruct",
      "env": {
        "ANTHROPIC_BASE_URL": "http://localhost:8000",
        "ANTHROPIC_AUTH_TOKEN": "dummy"
      }
    }
  ]
}
```

Field reference (full schema: [`benchmarks/schema/compare-config.schema.json`](schema/compare-config.schema.json)):

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `benchmark` | string | yes | Adapter id from `./scripts/benchmark list`. |
| `runs` | integer ≥1 | no (default 1) | Repetitions per task per candidate. **Use ≥3** for cross-LLM comparisons; the calibrated winner-rule needs stdev to declare a winner over noise. |
| `task` | string[] | no | Task filter (omit to run every task). Same shape as `./scripts/benchmark run --task`. |
| `candidates[]` | array (≥2) | yes | LLMs to compare. Order is preserved in the report. |
| `candidates[].name` | string | no | Human-readable label; defaults to `<backend>:<model>`. Must be unique. |
| `candidates[].backend` | string | yes | Backend family — `claude-code` or `stub`. **Do not** use the combined `claude-code:sonnet` form (rejected). |
| `candidates[].model` | string | no | Model id passed to the backend. |
| `candidates[].env` | string→string map | no | Provider routing env vars, applied only for this candidate's runs and restored after. Values are passed verbatim into `os.environ`; **only key names are persisted** to the compare manifest (no secret leakage). |

Three things the config deliberately does **not** support:
- **Per-candidate `task` overrides** — comparison must be apples-to-apples.
- **Per-candidate `runs` overrides** — same reason.
- **Parallel execution** — candidates run sequentially. Parallel runs would contend on the polyglot cache, the per-attempt worktree provisioning, and most providers' rate limits.

### 4. Run the comparison

```bash
./scripts/benchmark compare --config my-compare.json
# {
#   "run_dir": "runs/20260513T140000Z-compare-aider-polyglot",
#   "report_md": "runs/20260513T140000Z-compare-aider-polyglot/report.md"
# }
```

The harness validates the adapter and every candidate backend *before* doing any work, so a typo in `candidates[5]` does not waste candidates 0–4's wall time. Each candidate's per-attempt artifacts (`run-record.json`, `score.json`, `stats.json`, `diff.patch`, transcripts) land in its own nested run-dir under the parent.

### 5. Read the report

```bash
cat runs/20260513T140000Z-compare-aider-polyglot/report.md
```

The report shows:
- One group per candidate (labelled by the candidate's `name`), with total attempts, pass rate, and `mean ± stdev` for elapsed seconds. When two candidates share `(backend, model)` but differ in `env` routing — e.g. the same Claude Code model through Anthropic API vs. an OpenRouter gateway — the unique candidate names keep them as distinct groups rather than collapsing them.
- A per-task table (which tasks each candidate passed).
- Pairwise winner verdicts using the calibrated rule: `(Δ > 2σ) AND (|Δ| ≥ threshold)` per metric. Below those thresholds the report emits `directional, no winner declared` rather than calling a winner on noise.
- `backend_metadata.provider_endpoint` per candidate, so a comparison that mixes Anthropic API + a local gateway is visibly marked as such.

### 6. (Optional) skip the auto-report

```bash
./scripts/benchmark compare --config my-compare.json --no-report
# Later:
./scripts/benchmark report --run-dir runs/20260513T140000Z-compare-aider-polyglot/
```

Useful when you want to inspect run-dirs first before producing the comparison.

### Common patterns

**Three Anthropic models on Python tasks only:**
```json
{ "benchmark": "aider-polyglot", "runs": 3,
  "task": ["python/leap", "python/anagram", "python/clock"],
  "candidates": [
    { "name": "haiku",  "backend": "claude-code", "model": "haiku"  },
    { "name": "sonnet", "backend": "claude-code", "model": "sonnet" },
    { "name": "opus",   "backend": "claude-code", "model": "opus"   }
  ] }
```

**Anthropic API vs. one local LLM:**
```json
{ "benchmark": "aider-polyglot", "runs": 3,
  "task": ["python/leap"],
  "candidates": [
    { "name": "sonnet-cloud", "backend": "claude-code", "model": "sonnet" },
    { "name": "local-qwen", "backend": "claude-code",
      "model": "qwen2.5-coder:32b",
      "env": { "ANTHROPIC_BASE_URL": "http://localhost:11434",
               "ANTHROPIC_AUTH_TOKEN": "dummy" } }
  ] }
```

**Same model, two different providers** (give each candidate a unique `name` since `(backend, model)` overlaps):
```json
{ "benchmark": "stub", "runs": 1,
  "candidates": [
    { "name": "anthropic-direct",
      "backend": "claude-code", "model": "claude-sonnet-4-6" },
    { "name": "openrouter-proxy",
      "backend": "claude-code", "model": "claude-sonnet-4-6",
      "env": { "ANTHROPIC_BASE_URL": "https://openrouter.ai/api/v1" } }
  ] }
```

## Status

| Phase | Ships | State |
|-------|-------|-------|
| 0 | Contracts, CLI skeleton, schemas, tests | done |
| 1 | Stub adapter + stub backend + run orchestration + CI smoke test + report skeleton | done |
| 2 | Aider Polyglot adapter, `worktree+venv` tier | done |
| 3 | Claude Code (`claude -p`) backend with provider-routing recording | done |
| 4a | Calibrated winner-declaration rule, report verdicts, dogfood subcommand | done |
| 4b | Gate 1 (Polyglot liveness) + Gate 2 (memkernel#3 spec-first verdict-correctness) dogfood execution | pending — maintainer-driven on user's machine |

Comparison driver (`./scripts/benchmark compare`) shipped 2026-05-13.

## CLI

```bash
./scripts/benchmark list                                       # adapters + backends
./scripts/benchmark list --benchmark aider-polyglot            # tasks for an adapter
./scripts/benchmark run --benchmark aider-polyglot \
    --backend claude-code --model sonnet --runs 3              # single (backend, model) run
./scripts/benchmark compare --config my-compare.json           # multi-LLM comparison
./scripts/benchmark report --run-dir runs/<UTC-ts>/            # aggregate any run-dir
./scripts/benchmark dogfood --backend claude-code --model sonnet  # Gate 1 dogfood
```

Backend and model are **separate flags**. The combined `--backend claude-code:sonnet` form is rejected (see spec.md § v3 correction for why the abstractions were split).

Exit codes (stable across the MVP):
- `0` — success.
- `2` — usage error (argparse), unknown adapter / backend, or invalid compare-config.
- `3` — runtime failure during run / report / compare.
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
| `codex`          | #33   | Spawns `codex exec --json --sandbox workspace-write --skip-git-repo-check [--model <m>] -` (prompt on stdin), parses the JSONL transcript. **Provider routing:** the OpenAI Codex CLI selects a provider via `~/.codex/config.toml` `[model_providers.<id>]` blocks (OpenAI cloud, or a local `base_url` for Ollama/vLLM). CCT *records* the resolved config.toml path + selected provider id in `backend_metadata` (never secrets); it does not set them. Pinned & verified: `codex-cli 0.130.0` — see `specs/benchmark-harness/verification/codex.md`. |

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
  image: <prebuilt image ref>     # e.g. swebench/sweb.eval.<arch>.<id>:latest
  container_mount: /testbed       # bind-mount the worktree over the
                                  # image's repo dir (default /workspace)
  dockerfile: <path>              # (build-from-Dockerfile variant)
  build_args: {}
```

The runner provisions one worktree per attempt under
`runs/<ts>-<benchmark>-<backend>-NNN/<task>/<attempt>/worktree/`. For
the `worktree+venv` tier (Phase 2), it also creates a `.venv/` inside
the worktree, runs the configured `install_command` with the venv's
`bin/` at the front of `PATH`, and the verify path looks for
`worktree/.venv/bin/python` and `worktree/.venv/bin/pytest` before
falling back to the host toolchain.

The `docker` tier (issue #33) provisions a long-lived container with
the host worktree **bind-mounted at `IsolationConfig.container_mount`**
(default `/workspace`; the SWE-bench Verified adapter sets `/testbed`,
where its prebuilt image keeps the repo + editable-installed deps).
`prepare_task` + the backend edit the host worktree; those edits are
live in the container; `verify` runs the test sets in-container via
`isolation.run_in_worktree`; teardown (`release_worktree`) is called
by the runner in a `finally`. **docker is local-only — never in CI**
(images are multi-GB); a missing/misconfigured Docker daemon is
reported as an environment prerequisite, never a silent skip. The
SWE-bench Verified adapter (`swe-bench-verified`, `REVISION`-pinned via
the stdlib HF rows-API `fetch.py`; image ref derived at runtime as
`swebench/sweb.eval.<host-arch>.<instance_id with __→_1776_>:latest`;
single-shot) is the first real docker-tier consumer; `verify` applies
the instance `test_patch` then runs `FAIL_TO_PASS`/`PASS_TO_PASS` in
the image's `testbed` conda env. Update procedure: edit `REVISION`,
run `python3 -m benchmarks.adapters.swe_bench_verified.fetch`.

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
- **No custom application fixtures as the foundation.** The MVP's first public adapter is Aider Polyglot precisely so we ride a published leaderboard for sanity. Custom CCT fixtures are one adapter among several in issue #33, never the centerpiece. *Carve-out:* `cct-dogfood-memkernel` ships in this issue as Gate-2 verdict-correctness calibration infra against memkernel#3 (a fresh forward-looking spec-first task) — never invoked outside maintainer-driven dogfood, never in CI, never in cross-backend leaderboard reports. See `specs/benchmark-harness/spec.md` § Constraints.

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
