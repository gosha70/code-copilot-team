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
    - https://code.claude.com/docs/en/llm-gateway
    - https://docs.vllm.ai/en/stable/serving/integrations/claude_code/
    - https://ollama.com/blog/claude
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

The harness is therefore **benchmark-agnostic**: a small adapter contract that any public benchmark (or one-off custom fixture) can implement. The MVP ships exactly one public adapter — Aider Polyglot — because the format (per-task two-shot with test feedback) exercises every harness moving part, and the dataset is small enough to iterate on.

**Note on leaderboard comparison.** Earlier drafts of this spec proposed comparing `claude-code` runs against Aider's published Polyglot leaderboard. That comparison is apples-to-oranges: Aider's leaderboard reports *Aider-the-agent driving model X*, while CCT runs *Claude Code-the-agent driving model X*. Different agents, different scores. Apples-to-apples leaderboard comparison requires adding an Aider backend (Phase 4 candidate); for the MVP, the dogfood gate is "harness runs end-to-end on real Polyglot tasks," not "harness reproduces Aider's leaderboard."

Out-of-scope for the MVP, on the explicit fork from issue origin:
- Authoring custom CCT-specific fixtures as the primary deliverable. (Optional dogfood adapter is acceptable but secondary; see issue #33.)
- LLM-judge scoring, charts, HTML reports, dollar-cost reporting (issue #34).
- SWE-bench / LiveCodeBench / BigCodeBench adapters (issue #33).
- **Additional copilot backends** beyond Claude Code — Aider, Codex, GitHub Copilot CLI move to issue #33 as Phase 4 candidates.

## Backends vs providers — load-bearing distinction

Two terms with carefully separated meanings (see [`audit-2026-05-08.md`](audit-2026-05-08.md) for the architectural correction that surfaced this):

- **Backend** = an *agentic copilot CLI* the harness drives. The backend has its own editor loop, tool use, and file-edit semantics. Examples: Claude Code, Aider, Codex, GitHub Copilot CLI.
- **Provider** = an *LLM endpoint* the backend's copilot routes its model calls to. Examples: Anthropic API, vLLM, Ollama, LM Studio, OpenRouter.

Same provider can serve different backends; same backend can route to different providers. They are orthogonal axes.

The harness *records* which provider a run used (by reading the backend's gateway env vars at run time and writing them into `backend_metadata`). It does **not** set them — provider configuration is the user's responsibility (or, eventually, CCT's standalone provider-config feature in [`specs/provider-config/`](../provider-config/spec.md)).

## User Scenarios

1. **Maintainer compares two models on Aider Polyglot via Claude Code.** A maintainer runs
   `./scripts/benchmark run --benchmark aider-polyglot --backend claude-code --model sonnet --runs 3`
   and again with `--model opus --runs 3`. They then run
   `./scripts/benchmark report --run-dir runs/<ts>/`. The Markdown report shows
   per-task pass rates, per-language aggregates, and `mean ± stdev` across the
   three runs per (backend, model) combination. Where the winner-declaration
   rule's threshold is met, the report names a winner; otherwise it prints
   "directional, no winner declared." `backend_metadata` records the provider
   endpoint (Anthropic API by default; or vLLM/Ollama gateway URL if set via
   `ANTHROPIC_BASE_URL`). No dollar-cost figures appear anywhere.

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
   maintainer runs `./scripts/benchmark dogfood --backend claude-code --model sonnet`
   over a 10–15-task subset (≥1 per language). The output is a run-dir
   committed under `specs/benchmark-harness/dogfood/<UTC-ts>/`, with
   `backend_metadata` recording the provider env vars (Anthropic API
   default, or local gateway if `ANTHROPIC_BASE_URL` was set). Any
   task failures are cause-classified (harness bug / backend
   agent-loop / provider-side / model-side) in the merge commit body.

5. **Local-LLM run via Claude Code gateway.** A maintainer launches a vLLM
   server with `vllm serve <model> --enable-auto-tool-choice --tool-call-parser openai`,
   exports `ANTHROPIC_BASE_URL=http://localhost:8000`,
   `ANTHROPIC_AUTH_TOKEN=dummy`, `ANTHROPIC_DEFAULT_SONNET_MODEL=<served-model-name>`,
   and runs `./scripts/benchmark run --benchmark aider-polyglot --backend claude-code --model <served-model-name> --runs 1`.
   Claude Code routes its model calls to the local vLLM; the harness measures
   the full copilot+model stack and records `provider_endpoint=http://localhost:8000`
   in `backend_metadata`. Same flow works for Ollama (`ANTHROPIC_BASE_URL=http://localhost:11434`,
   `AUTH_TOKEN=ollama`) or LM Studio (`http://localhost:1234`).

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
- `claude-code` (with `--model <id>`) — invokes `claude -p` headlessly via the launcher. The harness records `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN_present` (boolean only — never the value), and `claude_code_invocation: "launcher" | "bare"` in `backend_metadata`. Provider routing happens via Claude Code's [LLM gateway support](https://code.claude.com/docs/en/llm-gateway) when the user has set the gateway env vars: Claude Code routes to vLLM ([integration](https://docs.vllm.ai/en/stable/serving/integrations/claude_code/)), Ollama ([blog post](https://ollama.com/blog/claude)), LM Studio, or any Anthropic-Messages-compatible endpoint. The harness captures *where it routed* but does not set the routing itself. Default invocation is launcher mode (full autodiscovery, OAuth/keychain auth); `CCT_CLAUDE_BARE=1` opts into `--bare` for cross-machine reproducibility (skips OAuth/keychain — requires `ANTHROPIC_API_KEY`).
- `stub` — copies the adapter's `golden_patch` into the worktree and exits. Used by CI smoke test only; not a real backend.

**Scoped into issue #33 as Phase 4 candidates:** Aider, Codex, GitHub Copilot CLI agent backends — each requires independent verification of headless-invocation surface and BYOK options before landing.

**Out of scope entirely:** Cursor, Windsurf — GUI-only, no headless agent loop.

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
./scripts/benchmark run --benchmark aider-polyglot --backend claude-code --model sonnet --runs 3 [--task <id> ...]
./scripts/benchmark run --benchmark aider-polyglot --backend claude-code --model opus --runs 3
./scripts/benchmark run --benchmark stub --backend stub --runs 1                       # CI smoke
./scripts/benchmark report --run-dir runs/<timestamp>/
./scripts/benchmark dogfood --backend claude-code --model sonnet                       # see Dogfood gate
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

## Dogfood gate

Two complementary gates with distinct purposes — both must pass before merge.

### Gate 1 — Liveness (T3.4): "harness runs end-to-end against a public benchmark"

> Run the Aider Polyglot adapter against `claude-code --model sonnet` on a small task subset (≥10 tasks, ≥1 per language). The merge commit must (1) link to the run-dir produced (under `specs/benchmark-harness/dogfood/<UTC-ts>/`); (2) state which provider the run used (Anthropic API by default, or `ANTHROPIC_BASE_URL=...` if a gateway was configured); (3) note any task-specific failures with cause classification (harness bug / backend agent-loop issue / provider-side issue / model-side issue). If the harness cannot run the adapter end-to-end at all, the issue does not merge.

**Removed from this gate (v3 correction):** the prior version compared CCT's `claude-code` per-language pass rate against Aider's published Polyglot leaderboard. That comparison is apples-to-oranges — Aider's leaderboard reports *Aider-the-agent driving model X*, not *Claude Code driving model X*. Different agents, different scores. Apples-to-apples comparison requires adding an Aider backend (issue #33's scope).

### Gate 2 — Verdict correctness (memkernel#3 spec-first dogfood)

This is the **load-bearing** merge gate — the one that justifies the harness's existence. Liveness is necessary but not sufficient: a harness that runs to completion but produces wrong verdicts is worse than no harness, because it gives false confidence.

> Build a `cct-dogfood-memkernel` fixture (committed under `benchmarks/adapters/cct_dogfood_memkernel/`) that snapshots the memkernel repo at a pinned SHA and exposes one task — `memory-brain-spec` — whose prompt is the verbatim body of memkernel#3 ("Define MemKernel Memory Brain Architecture"). The deliverable is a single file the agent must author: `specs/memory-brain/spec.md`. The deterministic verifier checks: (1) spec.md exists; (2) the seven section headers from memkernel#3's acceptance criteria are present; (3) `pyproject.toml` is unchanged (memkernel#3 is spec-only — no new deps); (4) `src/memkernel/mcp/` is unchanged (no MCP code lands). Run the harness against this fixture using `claude-code --model sonnet --runs 3`. For each (run, attempt) pair, the maintainer manually reads the produced `specs/memory-brain/spec.md` and records a human verdict (the spec is / is not a faithful answer to memkernel#3). Compare against the harness's `tests_passed` per attempt.
>
> **Pass criteria:** verdict-class match (pass/fail) between harness and human on ≥80% of (run, attempt) pairs. With `--runs 3` and a single task, this is 3 comparisons. Below 80%, document the divergence cause (verify.sh too lenient / verify.sh too strict / human rubric not deterministically checkable / model regression / harness bug) in the merge commit. Material divergence is calibration data, not necessarily a blocker — but the merge commit must explain it. If the harness can't run memkernel#3 to completion at all, the issue does not merge.

memkernel#3 is **forward-looking and unrun** at the time the fixture lands — that is the defining property. Retrospective dogfood (replaying a closed experiment whose verdict is already recorded) is too easy: the harness only has to match a known answer. A fresh task forces the harness to demonstrate that its deterministic-scoring + run-record machinery produces verdicts a maintainer would agree with on a real, never-seen-before copilot task.

> **Privileged fixture status.** This is the *only* custom-CCT fixture the MVP ships. The Constraints section ("No custom application fixtures as the foundation") allows it precisely because it is calibration infrastructure for Gate 2, not a fixture pretending to be a benchmark. It does not appear in any leaderboard, does not contend with Aider Polyglot for "first public adapter" status, and never runs in CI (it requires a memkernel clone + claude-code auth). It runs only at maintainer-driven dogfood time. Whether the fixture is refreshed (newer pinned SHA), archived, or removed after #32 merges is a future-maintainer decision — out of scope for this issue.

The two gates measure orthogonal things:
- Gate 1 confirms the harness *runs* end-to-end. Catches integration bugs.
- Gate 2 confirms the harness's *verdict* tracks human judgment. Catches scoring/rubric correctness bugs.

Both must pass.

## Requirements

1. **Adapter contract.** A benchmark adapter is a Python module exposing the
   `BenchmarkAdapter` protocol exactly as specified above. Adding a new
   adapter MUST NOT require changes to the contract; if a new adapter
   exposes a need the contract can't express, that is a regression to fix
   in this issue, not in the follow-up that introduces the adapter.

2. **Backend contract.** A backend is a Python module exposing the
   `Backend` protocol. The MVP ships exactly two: `claude-code` (with
   `--model <id>`) and `stub`. Provider routing for `claude-code` flows
   through Claude Code's own gateway env vars; the harness reads them
   at run time and records them, never sets them. Additional copilot
   backends (Aider, Codex, GitHub Copilot CLI) are scoped into issue
   #33 as Phase 4 candidates.

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

9. **Dogfood gates (TWO must pass).**
   (9a) **Liveness:** ≥10 Aider Polyglot tasks (≥1 per supported language)
   run end-to-end against `claude-code --model sonnet`. Run-dir committed,
   provider env vars in run-record, failures cause-classified.
   (9b) **Verdict correctness (memkernel#3 spec-first dogfood):** harness's
   `tests_passed` matches the maintainer's human verdict on the produced
   `specs/memory-brain/spec.md` for ≥80% of (run, attempt) pairs from a
   `claude-code --model sonnet --runs 3` invocation. This is the
   load-bearing gate — a running harness that produces wrong verdicts is
   worse than no harness. Below 80%, document the divergence cause in
   the merge commit.

10. **Report output.** Markdown + JSON only. HTML, charts, and CSV are
    deferred to issue #34.

11. **Documentation.** `benchmarks/README.md` MUST document the
    adapter contract, the backend contract, the isolation tier matrix,
    and the path to add a new adapter or backend, with the stub
    adapter as a worked example.

## Constraints

What this issue MUST NOT build, even if convenient:

- **No custom application fixtures as the foundation.** A custom CCT
  fixture is permitted in issue #33 as one adapter among several —
  never as the centerpiece or as a stand-in for a public benchmark.
  The MVP's first public adapter is Aider Polyglot precisely so we
  ride a published leaderboard for sanity. *Carve-out:*
  `cct-dogfood-memkernel` (Gate 2 calibration target) ships in this
  issue because verdict-correctness calibration on a fresh,
  forward-looking copilot task is the harness's load-bearing
  justification. It is never invoked outside maintainer-driven
  dogfood, never runs in CI, and never appears in cross-backend
  leaderboard reports.
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
- **No additional copilot backends.** Aider, Codex, GitHub Copilot CLI
  defer to issue #33 — each requires independent verification of its
  headless-invocation surface and BYOK options before landing.
  Cursor and Windsurf are out of scope entirely (GUI-only, no headless
  agent loop).
- **No raw-LLM backend.** vLLM, Ollama, LM Studio, OpenRouter, etc.
  are *providers*, not backends. They're configured per-backend via
  the backend's own gateway env vars (e.g. `ANTHROPIC_BASE_URL` for
  Claude Code; `OPENAI_API_BASE` for the future Aider backend); the
  harness records what was set, not how to set it. The optional
  per-run `--vllm-endpoint`-style harness flag from earlier drafts
  is dropped — provider routing is a shell-environment concern, not
  a CCT CLI concern. CCT's standalone provider-config feature
  (separate `specs/provider-config/` spec) may eventually emit the
  per-copilot config files, but that's not part of this benchmark.
- **No mutation of `master`.** All work lands on `feat/benchmark-harness`;
  the spec's commit cadence stays per-phase, with each phase reviewed
  before the next begins.

## Success Criteria

- [ ] Adapter contract is defined and documented (`benchmarks/README.md`).
- [ ] Backend contract is defined and documented.
- [ ] `./scripts/benchmark list` prints `aider-polyglot` and `stub` as adapters; `claude-code` and `stub` as backends.
- [ ] `./scripts/benchmark run --benchmark aider-polyglot --backend claude-code --model sonnet --runs 3` completes three isolated runs end-to-end on at least one task per supported language.
- [ ] When `ANTHROPIC_BASE_URL` is set in the environment, the harness records it (and `ANTHROPIC_AUTH_TOKEN_present`, `claude_code_invocation`) into `backend_metadata` — provider routing is recorded, not set by the harness.
- [ ] Stub-backend smoke test runs in CI on every PR matching the path filter, in <90s.
- [ ] Each run records: prompt, backend metadata, seed/temperature, elapsed time, command log, diff, test output, deterministic score.
- [ ] Report shows `mean ± stdev` per metric across runs and obeys the winner-declaration rule (unit-tested over ≥8 cases).
- [ ] Report distinguishes missing stats (`null`) from zero values.
- [ ] No dollar-cost estimate appears in any output.
- [ ] Dogfood Gate 1 (liveness): ≥10 Aider Polyglot tasks across ≥1 language each, against `claude-code --model sonnet`, with run-dir committed under `specs/benchmark-harness/dogfood/<UTC-ts>-liveness/`, provider env vars recorded in run-record, any task failures cause-classified in the merge commit.
- [ ] Dogfood Gate 2 (verdict correctness): memkernel#3 spec-first dogfood — `cct-dogfood-memkernel` fixture committed under `benchmarks/adapters/cct_dogfood_memkernel/` (snapshots memkernel at a pinned SHA; one task `memory-brain-spec` whose prompt is the verbatim memkernel#3 body); harness verdict (`tests_passed`) compared to maintainer's human verdict on the produced `specs/memory-brain/spec.md` for ≥80% of (run, attempt) pairs from `claude-code --model sonnet --runs 3`; run-dir committed under `specs/benchmark-harness/dogfood/<UTC-ts>-memkernel-spec/`; divergence cause documented in merge commit.
- [ ] Documentation explains how to add a new benchmark adapter and a new backend.

## Reuse map

Nothing in `scripts/` is reused; this is a new subsystem. The existing `scripts/wiki_ingest/` Python style (argparse subparsers + dispatcher) is the model for `scripts/benchmark`'s argument layout. No code is moved or duplicated.

## Risks

- **Aider Polyglot dataset shape changes.** The benchmark is maintained externally. Pin to a specific commit SHA in `benchmarks/adapters/aider-polyglot/REVISION` and document the upgrade procedure.
- **Claude Code headless transcript format drifts.** The transcript parser is the most fragile MVP surface. Snapshot a transcript in tests; fail loudly on schema changes rather than silently mis-parsing usage.
- **Gateway transcript variability.** When Claude Code is pointed at a non-Anthropic gateway (vLLM/Ollama/LM Studio), the response shape may differ from the Anthropic API's. Treat all token-usage fields as `Optional`; never crash on absence. Tag `backend_metadata.provider_endpoint` so reports can flag mixed-provider comparisons.
- **Worktree contention.** `--runs 3` in parallel could race over the same worktree path. Worktrees are per-(run, task, attempt) — never shared. Cleanup on success; preserve on failure for postmortem.

## Deviation from origin

The original issue body proposed:
1. A custom `python-fastapi-service` MVP fixture.
2. A `rlmkit-llm-wiki-backbone` dogfood fixture comparing against a hand-graded gist with a strict pass/fail human-rubric match.

This spec instead delivers:
1. A benchmark-agnostic adapter contract + the Aider Polyglot adapter as the only public adapter shipped in the MVP.
2. A run-to-completion dogfood gate (no leaderboard comparison — the v3 correction explains why).

The strategic reasoning is captured in the user message of 2026-05-07 ("CCT should become the harness that runs those benchmarks under real copilot workflows…"). The original `python-fastapi-service` and `rlmkit-llm-wiki-backbone` fixtures are dropped — both can return as adapters under issue #33 if there is value, but they are no longer the foundation.

### v3 correction (2026-05-08)

A second-order error surfaced: v2 framed `claude-code:<model>` and `vllm:<model>` as **peer backends**. They are not. Claude Code is a *copilot agent* (drives an editor loop, tool use, file edits); vLLM is a *provider* (an LLM-serving HTTP runtime). v3 separates the abstractions:

- **Backends** = agentic copilot CLIs (Claude Code, plus Aider/Codex/GH-Copilot CLI under issue #33).
- **Providers** = HTTP endpoints the backends route to via the backend's own gateway env vars.

The CLI surface changes accordingly: `--backend <copilot> --model <id>` (separate flags), not `--backend <copilot>:<model>` (combined). The harness *records* the provider env vars (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN_present`, `claude_code_invocation`) but does not *set* them.

Removed in v3:
- The `vllm:<model>` backend (was a Phase-2c stub + Phase-3b real implementation; the latter draft was uncommitted, the former is removed in a fresh refactor commit).
- The harness-side `--vllm-endpoint` CLI flag.
- The whole-file fenced-block "EDIT_FORMAT_INSTRUCTIONS" that the discarded vLLM backend appended to prompts.
- The Aider-leaderboard comparison from the dogfood gate (apples-to-oranges; Aider's leaderboard is Aider-the-agent, not Claude Code).

Audit + rollback documents:
- [`audit-2026-05-08.md`](audit-2026-05-08.md) — line-pinned analysis of the v2-to-v3 changes.
- [`rollback-2026-05-08.md`](rollback-2026-05-08.md) — concrete per-file revert + new commit description.
- [`_backup-2026-05-08-pre-correction/`](_backup-2026-05-08-pre-correction/) — frozen v2 specs for diff convenience.
- [`doc_internal/copilot-llm-support-matrix.md`](../../doc_internal/copilot-llm-support-matrix.md) — verified-facts fact base for the per-copilot LLM-customization story across all six adapters.

### v4 correction (2026-05-09): Gate 2 retargeted

The v3 spec restored the **rlmkit#38/#41 retrospective** as the load-bearing Gate 2 calibration target. That choice was wrong on a third axis — it was retrospective. The gist verdicts are final and the rlmkit experiment is closed; calibrating against a known-answer keyhole produces optimistic verdict-correctness numbers (the harness can be wrong about *anything* and still match the answer if it happens to copy the cases' pattern). v4 retargets Gate 2 onto **memkernel#3**, a fresh forward-looking spec-first issue from a sister project that is unrun at the time the fixture lands. The harness's first comparison against memkernel#3 generates true calibration data — neither side knows the answer in advance.

What changed in v4:
- New fixture: `benchmarks/adapters/cct_dogfood_memkernel/` snapshots memkernel at a pinned SHA and exposes one task (`memory-brain-spec`) whose prompt is the verbatim memkernel#3 issue body.
- Verifier: hard checks (spec.md exists + 7 section headers + pyproject unchanged + MCP unchanged) plus best-effort checks (ruff/mypy/pytest, skipped if toolchain absent).
- Calibration unit: per (run, attempt) pair, harness `tests_passed` vs. maintainer's read of the produced `specs/memory-brain/spec.md`. With `--runs 3` and a single task, that's 3 comparisons; ≥80% match (i.e. 3/3 in practice) clears the gate.
- Removed: `cct-dogfood-rlmkit` fixture, retrospective gist comparison, `rlmkit-retrospective` run-dir naming.
- Constraints carve-out: the v3 prohibition on custom CCT fixtures gets a single, narrow exception named for `cct-dogfood-memkernel` — calibration infrastructure, never a benchmark, never in CI. Whether the fixture is refreshed (newer pinned SHA), archived, or removed after #32 merges is a future-maintainer decision; v4 takes no position on cadence or longevity.

The "no custom CCT fixture as the foundation" rule (v2 origin redirect) is preserved: Aider Polyglot is still the only public adapter shipped, still the calibration backbone for cross-backend comparison, and still the centerpiece of the MVP. `cct-dogfood-memkernel` is calibration infra, not benchmark content.
