---
feature_id: benchmark-harness
spec_mode: full
status: draft
issue: 32
origin:
  issue: gosha70/code-copilot-team#32
  urls:
    - https://github.com/Aider-AI/polyglot-benchmark
    - https://github.com/Aider-AI/aider/blob/main/benchmark/README.md
    - https://www.swebench.com/verified.html
    - https://livecodebench.github.io/
    - https://bigcode-bench.github.io/
    - https://docs.vllm.ai/en/latest/serving/openai_compatible_server/
    - https://code.claude.com/docs/en/headless
  origin_claim: |
    Issue #32 originally proposed a custom `python-fastapi-service`
    fixture and a one-off `rlmkit-llm-wiki-backbone` dogfood fixture
    as the MVP. After web research surfaced established public
    benchmarks (SWE-bench Verified/Pro, Aider Polyglot, LiveCodeBench,
    BigCodeBench), the user (2026-05-07) explicitly redirected:
    "CCT should not compete with Aider, SWE-bench, or BigCodeBench as
    a benchmark author. CCT should become the harness that runs those
    benchmarks under real copilot workflows, repo policies, SDD gates,
    isolation tiers, and reproducible reporting." The MVP is therefore
    a benchmark-agnostic harness with one validated public adapter
    (Aider Polyglot), not a custom fixture.
---

# Benchmark Harness — benchmark-agnostic runner with Aider Polyglot adapter

> **Origin rescope (2026-05-07).** This spec replaces the custom-fixture
> framing in the original issue #32 body. The rescoped issue body lives
> at `doc_internal/benchmark-issue-1-v2.md`; the original at
> `doc_internal/benchmark-issue-1.md` is preserved as historical record.
> Cascading issue rewrites for #33 (`-2-v2.md`) and #34 (`-3-v2.md`)
> follow the same pattern.

## Strategic framing

CCT's value is **governance + measurement around copilot workflows**: SDD gates, isolation tiers, deterministic run records, repository policies. The field already has well-maintained coding benchmarks (Aider Polyglot, SWE-bench Verified/Pro, LiveCodeBench, BigCodeBench). CCT does not need to author another one.

The harness is therefore **benchmark-agnostic**: a small adapter contract that any public benchmark (or one-off custom fixture) can implement. The MVP ships exactly one public adapter — Aider Polyglot — because it has a published leaderboard for `claude-code:sonnet` we can use as a sanity reference, the format (per-task two-shot with test feedback) exercises every harness moving part, and the dataset is small enough to iterate on.

Out-of-scope for the MVP, on the explicit fork from issue origin:
- Authoring custom CCT-specific fixtures as the primary deliverable. (Optional dogfood adapter is acceptable but secondary; see issue #33.)
- LLM-judge scoring, charts, HTML reports, dollar-cost reporting (issue #34).
- SWE-bench / LiveCodeBench / BigCodeBench adapters (issue #33).

## User Scenarios

1. **Maintainer compares two backends on Aider Polyglot.** A maintainer runs
   `./scripts/benchmark run --benchmark aider-polyglot --backend claude-code:sonnet --runs 3`
   and again with `--backend vllm:<model> --runs 3`. They then run
   `./scripts/benchmark report --run-dir runs/<ts>/`. The Markdown report shows
   per-task pass rates, per-language aggregates, and `mean ± stdev` across the
   three runs per backend. Where the winner-declaration rule's threshold is
   met, the report names a winner; otherwise it prints "directional, no winner
   declared." No dollar-cost figures appear anywhere.

2. **CI runs the stub-backend smoke test.** A contributor opens a PR that
   touches `scripts/benchmark_runner/run.py`. The
   `benchmark-smoke.yml` workflow triggers (path filter matches), runs
   `./scripts/benchmark run --benchmark stub --backend stub --runs 1`,
   produces a complete run record, runs `report`, and exits 0 in <90s — no
   LLM is invoked. A PR that breaks the harness plumbing turns this red.

3. **Maintainer adds a new adapter.** A maintainer wants to add an adapter
   for a new public benchmark (anticipating issue #33). They read
   `benchmarks/README.md`, drop a new directory under `benchmarks/adapters/`
   with an `adapter.py` implementing the `BenchmarkAdapter` protocol, register
   it (single import line), and `./scripts/benchmark list` immediately shows
   the new adapter. The contract from this issue does not need to change.

4. **Maintainer runs the dogfood gate.** Before merging this issue, the
   maintainer runs `./scripts/benchmark dogfood --backend claude-code:sonnet`
   over a 10–15-task subset (≥1 per language). The output includes a
   side-by-side comparison against Aider's published leaderboard for the
   same model. The maintainer classifies any divergence (harness bug /
   backend difference / prompt difference / agent-loop difference) and
   captures the classification in the merge commit body.

5. **Local vLLM run for an open-weights model.** A maintainer with a vLLM
   server running locally exports `CCT_VLLM_ENDPOINT=http://localhost:8000/v1`
   and runs `./scripts/benchmark run --benchmark aider-polyglot --backend vllm:<model> --runs 1`.
   The harness produces the same shape of run record as for Claude Code,
   with token usage where the response includes it and `null` where it
   doesn't.

6. **Triaging a flaky comparison.** A run shows a tight backend gap with
   high stdev. The report does not declare a winner. The maintainer reads
   per-run stats (recorded `seed`, `temperature`, transcript paths), spots
   that one backend recorded `seed: null` and the other recorded `seed: 42`,
   and decides to re-run with seeded prompts on both — the harness made the
   variance source visible without the maintainer having to dig into
   transcripts manually.

## Adapter contract

A benchmark adapter is a Python module exposing this interface (loaded by `benchmark-runner.py` via entry-point or import-by-path):

```python
class BenchmarkAdapter(Protocol):
    benchmark_id: str                              # e.g. "aider-polyglot"
    isolation_default: Literal["worktree", "worktree+venv", "docker"]

    def list_tasks(self) -> list[TaskSpec]: ...
    def prepare_task(self, task: TaskSpec, worktree: Path) -> None: ...
    def prompt_for(self, task: TaskSpec, attempt: int, prior_output: VerifyResult | None) -> str: ...
    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult: ...
    def golden_patch(self, task: TaskSpec) -> Path: ...   # used by stub backend only
    def max_attempts(self) -> int: ...                    # 1 for single-shot, 2 for Aider-style retry
```

`TaskSpec` is a frozen dataclass (`task_id`, `language`, `metadata: dict[str, Any]`). `VerifyResult` carries `tests_passed: bool`, `tests_output: str`, `lint_passed: bool | None`, `typecheck_passed: bool | None`, `required_files_present: bool`, `failed_commands: int`.

The contract intentionally stays narrow: the harness owns isolation, run records, and scoring; the adapter owns "what is a task in this benchmark and how do I check it."

## Backend contract

A backend runs one attempt of one task inside a prepared worktree:

```python
class Backend(Protocol):
    backend_id: str
    def run(self, prompt: str, worktree: Path, run_ctx: RunContext) -> BackendResult: ...
```

`BackendResult` records the actual prompt sent, the model output, transcript path, token usage (input/output/cache), tool-call counts, elapsed time, and `failed_commands`.

MVP backends:
- `claude-code:<model>` — invokes `claude -p` headlessly, streams transcript to disk, parses usage from the final transcript event. Reference: https://code.claude.com/docs/en/headless.
- `vllm:<model>` — OpenAI-compatible HTTP client against a configured endpoint. Captures token usage where present in the response. Reference: https://docs.vllm.ai/en/latest/serving/openai_compatible_server/.
- `stub` — copies the adapter's `golden_patch` into the worktree and exits. Used by CI smoke test only; not a real backend.

Out of scope for MVP: Cursor, Codex, Aider, GitHub Copilot agent, LM Studio, Opus, Haiku.

## Isolation tiers

Mandatory in the schema even when only `worktree+venv` is used by the MVP fixture, so issue #33's heavier adapters (SWE-bench is Docker-centric) slot in cleanly:

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

Aider Polyglot uses `worktree+venv` for Python tasks and `worktree` for the others (each language directory ships its own toolchain expectations).

## Determinism control

Backends are non-deterministic by default. `mean ± stdev` across `--runs N` is sampling noise unless the schema controls it:

```yaml
backend_invocation:
  temperature: 0       # default; overridable per-run
  seed: <int | null>   # optional; recorded in stats.json
```

Backends that don't support seeding (most hosted APIs) record `seed: null`. The report annotates such comparisons "higher-variance" and the winner-declaration rule (below) is what protects against false positives.

## Deterministic scoring

Per task, the harness records `score.json`:

```json
{
  "benchmark_id": "aider-polyglot",
  "task_id": "exercism/python/leap",
  "backend_id": "claude-code-sonnet",
  "run_id": "run-001",
  "attempt": 2,
  "scores": {
    "tests_passed": true,
    "lint_passed": null,
    "typecheck_passed": null,
    "required_files_present": true,
    "timeout": false,
    "human_interventions": 0
  },
  "derived": {
    "elapsed_seconds": 312,
    "files_changed": 1,
    "lines_added": 18,
    "lines_removed": 0,
    "failed_commands": 0
  },
  "result": "pass"
}
```

`null` distinguishes "adapter does not produce this signal" from `false`. No LLM-judge score in the MVP — issue #34.

## Run statistics

```json
{
  "elapsed_seconds": 312,
  "tokens_input": 12000,
  "tokens_output": 1800,
  "cache_read_tokens": null,
  "cache_write_tokens": null,
  "tool_calls": { "read": 4, "edit": 1, "bash": 2 },
  "cost_reporting": { "enabled": false, "reason": "billing-correlation pending" }
}
```

`cost_reporting.enabled: false` is permanent for the MVP; no dollar-cost estimate appears in any output.

## Winner-declaration rule

Implemented in `benchmark-report.py`, not left to reviewer judgment:

```
declare_winner(metric, A, B) iff:
  (mean_A − mean_B) > 2 × max(σ_A, σ_B)   AND
  abs(delta) ≥ 1 deterministic point  OR  abs(delta) ≥ 10% on continuous metrics
```

Otherwise the report emits "directional, no winner declared." The threshold rule is unit-tested against synthetic A/B distributions.

## CLI surface

```
./scripts/benchmark list
./scripts/benchmark list --benchmark aider-polyglot
./scripts/benchmark run --benchmark aider-polyglot --backend claude-code:sonnet --runs 3 [--task <id> ...]
./scripts/benchmark run --benchmark aider-polyglot --backend vllm:<model> --runs 3
./scripts/benchmark report --run-dir runs/<timestamp>/
./scripts/benchmark dogfood --backend claude-code:sonnet     # see Dogfood gate
```

Run artifacts land under `runs/<UTC-timestamp>-<benchmark>-<backend>/` with one subdirectory per task per attempt. `report` aggregates a single run-dir into Markdown + JSON. No HTML, no charts (issue #34).

## CI smoke test

`.github/workflows/benchmark-smoke.yml` runs `./scripts/benchmark run --benchmark stub --backend stub --runs 1` on every PR whose changeset matches the path filter:

```yaml
on:
  pull_request:
    paths:
      - 'scripts/benchmark'
      - 'scripts/benchmark_runner/**'
      - 'benchmarks/**'
      - 'specs/benchmark-harness/**'
      - '.github/workflows/benchmark-smoke.yml'
```

The stub backend copies `golden_patch` into the worktree and exits 0 — verifies plumbing (init → run → score → report) without invoking any LLM. Total wall time target: <90s on GitHub free runners. The Aider Polyglot adapter is **not** exercised in CI (cloning the upstream dataset + running language toolchains exceeds the budget); local-only.

## Dogfood gate (softened from origin)

The original issue required reproducing rlmkit#37 within strict bounds, against a single hand-graded gist. The rescoped gate:

> Run the Aider Polyglot adapter against `claude-code:sonnet` on a small task subset (≥10 tasks, ≥1 per language). Compare the harness's per-language pass rate against Aider's published leaderboard for the same model. Material divergence is calibration data, not a blocker — but the merge commit must classify the cause: harness bug, backend difference (Claude Code wraps the model differently from Aider's edit loop), prompt difference, or agent-loop difference. If the harness cannot run the adapter end-to-end at all, the issue does not merge.

The optional `rlmkit-llm-wiki-backbone` adapter from the original gate is deferred to issue #33 as one possible custom-CCT-fixture adapter, on equal footing with SWE-bench and BigCodeBench adapters.

## Requirements

1. **Adapter contract.** A benchmark adapter is a Python module exposing the
   `BenchmarkAdapter` protocol exactly as specified above. Adding a new
   adapter MUST NOT require changes to the contract; if a new adapter
   exposes a need the contract can't express, that is a regression to fix
   in this issue, not in the follow-up that introduces the adapter.

2. **Backend contract.** A backend is a Python module exposing the
   `Backend` protocol. The MVP ships exactly three: `claude-code:<model>`,
   `vllm:<model>`, `stub`. New backends register via `registry.py` without
   contract changes.

3. **Isolation tiers.** The schema MUST define `worktree`,
   `worktree+venv`, and `docker` from day one, even though only the first
   two are exercised by the MVP adapter. Issue #33's SWE-bench adapter
   relies on the `docker` tier slot existing.

4. **Determinism control.** Every run MUST record the actual `seed` and
   `temperature` used in `stats.json`. Backends that do not support
   seeding MUST record `seed: null` (not `seed: 0`).

5. **Deterministic scoring.** `score.json` MUST distinguish `null`
   (signal not produced by this adapter) from `false` (signal produced
   and failed). No LLM-judge scoring in this issue (#34).

6. **Run statistics.** `stats.json` MUST never carry a dollar-cost
   estimate; the `cost_reporting.enabled` field is permanently `false`
   in the MVP. Token usage MUST be `null` rather than `0` when the
   backend does not return it.

7. **Winner-declaration rule.** Implemented as a pure function in
   `report.py`. MUST be unit-tested over ≥8 synthetic A/B distribution
   cases, including: clear-winner each direction, tied means,
   high-variance no-winner, low-variance just-below threshold,
   continuous metric at exactly the 10% boundary, and single-run
   no-stdev fallback.

8. **CI smoke test.** `benchmark-smoke.yml` MUST run `stub × stub`
   on every PR whose changeset matches the path filter listed in the
   "CI smoke test" section. Wall-time budget <90s on GitHub free
   runners. The Aider Polyglot adapter MUST NOT run in CI.

9. **Dogfood gate.** Before merge, the harness MUST run ≥10 Aider
   Polyglot tasks (≥1 per supported language) against
   `claude-code:sonnet`, produce a comparison against Aider's
   published leaderboard, and classify any divergence (harness bug /
   backend difference / prompt difference / agent-loop difference) in
   the merge commit body. A strict numeric reproduction target is
   intentionally not required.

10. **Report output.** Markdown + JSON only. HTML, charts, and CSV are
    deferred to issue #34.

11. **Documentation.** `benchmarks/README.md` MUST document the
    adapter contract, the backend contract, the isolation tier matrix,
    and the path to add a new adapter or backend, with the stub
    adapter as a worked example.

## Constraints

What this issue MUST NOT build, even if convenient:

- **No custom application fixtures as the foundation.** A custom CCT
  fixture (e.g. `cct-dogfood-rlmkit-llm-wiki-backbone`) is permitted
  in issue #33 as one adapter among several — never as the centerpiece
  or the calibration target. The MVP's first public adapter is Aider
  Polyglot precisely so we ride a published leaderboard for sanity.
- **No LLM-judge scoring.** Deferred to issue #34, gated on a 50–100
  sample human-labeled calibration set with per-dimension Spearman ≥
  0.6 before any judge score influences winner declaration.
- **No dollar-cost reporting.** Permanently out of scope until
  billing-correlation is solved across providers; no schema slot for
  cost estimation is added. The `cost_reporting.enabled: false` field
  documents the deliberate omission.
- **No charts, HTML, or CSV exports.** Deferred to issue #34.
- **No additional adapters.** SWE-bench Verified, BigCodeBench,
  LiveCodeBench all defer to issue #33. Adding any of them in this
  issue's PR is scope creep.
- **No additional backends.** Cursor, Codex, Aider, GitHub Copilot
  agent, LM Studio, Opus, Haiku all defer until the harness contract
  is proven against the three MVP backends.
- **No mutation of `master`.** All work lands on `feat/benchmark-harness`;
  the spec's commit cadence stays per-phase, with each phase reviewed
  before the next begins.

## Success Criteria

- [ ] Adapter contract is defined and documented (`benchmarks/README.md`).
- [ ] Backend contract is defined and documented.
- [ ] `./scripts/benchmark list` prints `aider-polyglot` and `stub`.
- [ ] `./scripts/benchmark run --benchmark aider-polyglot --backend claude-code:sonnet --runs 3` completes three isolated runs end-to-end on at least one task per supported language.
- [ ] `./scripts/benchmark run --benchmark aider-polyglot --backend vllm:<model> --runs 3` works against a configured vLLM endpoint.
- [ ] Stub-backend smoke test runs in CI on every PR matching the path filter, in <90s.
- [ ] Each run records: prompt, backend metadata, seed/temperature, elapsed time, command log, diff, test output, deterministic score.
- [ ] Report shows `mean ± stdev` per metric across runs and obeys the winner-declaration rule (unit-tested over ≥8 cases).
- [ ] Report distinguishes missing stats (`null`) from zero values.
- [ ] No dollar-cost estimate appears in any output.
- [ ] Dogfood gate executed: ≥10 Aider Polyglot tasks across ≥1 language each, against `claude-code:sonnet`, with leaderboard comparison + cause classification documented in the merge commit.
- [ ] Documentation explains how to add a new benchmark adapter and a new backend.

## Reuse map

Nothing in `scripts/` is reused; this is a new subsystem. The existing `scripts/wiki_ingest/` Python style (argparse subparsers + dispatcher) is the model for `scripts/benchmark`'s argument layout. No code is moved or duplicated.

## Risks

- **Aider Polyglot dataset shape changes.** The benchmark is maintained externally. Pin to a specific commit SHA in `benchmarks/adapters/aider-polyglot/REVISION` and document the upgrade procedure.
- **Claude Code headless transcript format drifts.** The transcript parser is the most fragile MVP surface. Snapshot a transcript in tests; fail loudly on schema changes rather than silently mis-parsing usage.
- **vLLM endpoint variability.** Different vLLM deployments expose different usage fields. Treat all token-usage fields as `Optional`; never crash on absence.
- **Worktree contention.** `--runs 3` in parallel could race over the same worktree path. Worktrees are per-(run, task, attempt) — never shared. Cleanup on success; preserve on failure for postmortem.

## Deviation from origin

The original issue body proposed:
1. A custom `python-fastapi-service` MVP fixture.
2. A `rlmkit-llm-wiki-backbone` dogfood fixture comparing against a hand-graded gist with a strict pass/fail human-rubric match.

This spec instead delivers:
1. A benchmark-agnostic adapter contract + the Aider Polyglot adapter as the only public adapter shipped in the MVP.
2. A softened dogfood gate that compares against Aider's *published leaderboard* with a cause-classification, not a strict-match requirement.

The strategic reasoning is captured in the user message of 2026-05-07 ("CCT should become the harness that runs those benchmarks under real copilot workflows…"). The original `python-fastapi-service` and `rlmkit-llm-wiki-backbone` fixtures are dropped — both can return as adapters under issue #33 if there is value, but they are no longer the foundation.
