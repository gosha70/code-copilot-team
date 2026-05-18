---
spec_mode: full
feature_id: benchmark-bench-driver
risk_category: integration
justification: "New user-facing wrapper translating a terse CLI into the existing compare-config JSON, touching scripts/ (new scripts/bench shim + benchmark_runner/bench.py + benchmark_runner/proxy.py), benchmarks/presets/ (new), benchmarks/README.md, and threading a timeout signal through run.py + claude_code.py classification. External integrations: Ollama/LM Studio HTTP probes, an ephemeral LiteLLM Anthropic→OpenAI proxy for raw-vLLM endpoints. Multi-deliverable single-PR delivery with regression coverage of the unchanged JSON config flow. The harness verdict/scoring/isolation logic is NOT modified; D5 adds a timeout result value only."
status: draft
date: 2026-05-18
issue: 36
origin:
  issue: gosha70/code-copilot-team#36
  urls:
    - https://github.com/gosha70/code-copilot-team/issues/36
    - https://github.com/gosha70/code-copilot-team/pull/35
    - https://github.com/gosha70/code-copilot-team/issues/32
    - https://github.com/ollama/ollama/releases
    - https://code.claude.com/docs/en/llm-gateway
    - https://code.claude.com/docs/en/headless
  origin_claim: |
    See spec.md `origin:` block. Issue #36 asks for a single
    user-facing scripts/bench wrapper with safe defaults, terse
    provider:model[@endpoint] specs, live progress, per-attempt
    timeout + skip-to-next, a three-preset library, and a README
    quickstart rewrite — without changing harness verdict logic.
    Three planning decisions taken with the user 2026-05-18 refine
    D1's vLLM path (probe-then-decide), the legacy-script fate (keep +
    extract a shared proxy helper), and the D2/D5 basis (build on the
    merged PR #35 Popen+pgkill, not re-introduce it). See spec.md
    § Deviation from origin.
---

# Implementation Plan — Benchmark `bench` Driver

> **Wrapper, not a rewrite.** This plan accompanies
> `specs/benchmark-bench-driver/spec.md`. It changes no verdict,
> scoring, isolation, or run-record logic. Three origin refinements
> are recorded in spec.md § "Deviation from origin"; the
> origin-alignment record dated alongside this plan covers them.

## Approach

One feature branch, **one PR** (issue #36 mandates a single PR; per the
project rule a merged PR fully addresses its issue). Delivered in the
issue's own sequenced order — D3 → D1 → D2 → D5 → D4 — because each
later deliverable references the earlier one and D5 depends on D2's
heartbeat infrastructure. Each deliverable ends with a reviewable
commit and a working slice (the harness is runnable end-to-end after
every commit; the JSON config flow never regresses).

The wrapper is Python (`benchmark_runner/bench.py`) behind a thin
`scripts/bench` bash shim, mirroring `scripts/benchmark`. It resolves
every invocation to a compare-config and calls the **unchanged**
`compare.run_comparison` + `report.render_report`. The only edits to
existing harness modules are: a heartbeat hook in
`run._execute_attempt` (D2), a `result: "timeout"` classification path
in `run.py` + the aggregator (D5), and a one-paragraph header note in
the two legacy scripts plus their adoption of the extracted proxy
helper.

## Phase boundaries

| Deliverable | Working slice | Gate |
|---|---|---|
| D3 presets | 3 JSON presets validate against the compare-config schema | `./scripts/benchmark compare --config benchmarks/presets/anthropic-tour.json` parses (dry validation) |
| D1 wrapper | `scripts/bench` parses, env-fills, gates, smokes, lists | stub×stub smoke green; parser unit tests green; legacy JSON flow regression green |
| D2 progress | heartbeat thread + flush discipline | progress arrives < 1s under `2>&1 \| tee` (automated test) |
| D5 timeout | per-attempt timeout + `result:"timeout"` + skip | forced-hang test: killed, classified, campaign continues |
| D4 README | quickstart promoted, JSON demoted | README links resolve; quickstart is first section |

## D3 — Preset library (~30 min)

**Goal:** Three committed compare-configs under `benchmarks/presets/`.
Lowest risk, useful even if everything else slips.

- `anthropic-tour.json` — sonnet vs opus vs haiku, one Python task,
  3 runs. Anthropic-auth only.
- `local-vs-cloud.json` — sonnet + 2 Ollama candidates, 2 polyglot
  tasks, 3 runs, `attempt_timeout_seconds: 600`.
- `cross-language-mini.json` — sonnet alone on python/bowling,
  go/bowling, rust/bowling, 3 runs (single-candidate bench preset;
  the snapshot has no `*/leap` and no `rust/clock`, so the issue's
  literal task examples are substituted with `bowling`, which exists
  in python/go/java/javascript/rust).
- D3 also adds an optional top-level `attempt_timeout_seconds`
  (integer ≥ 1) to `compare-config.schema.json` so `local-vs-cloud`
  validates; the runtime wiring lands in D5.

**Acceptance:** `anthropic-tour` + `local-vs-cloud` validate against
`benchmarks/schema/compare-config.schema.json`; `cross-language-mini`
validates against the documented single-candidate bench-preset shape
(NOT the compare schema — compare's minItems:2 guard stays untouched);
all task ids exist in the pinned Polyglot snapshot.

## D1 — `scripts/bench` wrapper (~3–3.5h incl. the +30 min vLLM probe)

**Goal:** The terse CLI, safe default, confirmation gate, discovery,
and the shared proxy helper extraction.

- `scripts/bench` bash shim (PYTHONPATH + exec
  `python3 -m benchmark_runner.bench`), copyright header per project
  rule.
- `benchmark_runner/bench.py`: arg parsing, spec-parser (provider
  whitelist + colon-tag invariant), env-fill table, compare-config
  construction to a tempfile, pass-through, stub×stub safe default,
  confirmation gate (TTY-aware), `--list-presets`, `--list-providers`
  (Ollama 3-check incl. ≥ 0.14.0).
- `benchmark_runner/proxy.py`: extract the verified LiteLLM
  Anthropic→OpenAI lifecycle (tempfile config with `hosted_vllm/`
  prefix, background start, healthcheck loop, SIGTERM→SIGKILL teardown)
  out of `run-compare-anthropic-vs-vllm.sh`.
- vLLM probe-then-decide wired into candidate resolution.
- **Single-candidate routing:** when a resolved invocation/preset has
  exactly 1 candidate, the wrapper calls `./scripts/benchmark run`
  (not `compare`); ≥2 → `compare`. (OQ-4.)

**Acceptance:** parser unit tests (all colon-tag + every prefix +
unknown-token-hint); env-fill correctness tests; `--preset`
resolution + `--runs`/`--task` override; `--yes`/non-TTY; stub×stub
smoke green; `./scripts/benchmark compare --config <file>` regression
green.

## D2 — Live progress to stderr (~3h)

**Goal:** A heartbeat-thread + flush discipline so an active run is
never silent for 60s.

- `run._execute_attempt` wraps each attempt in an
  `attempt_in_progress` `threading.Event`; a daemon thread emits
  `[idx/total] cand task attempt running… Ns elapsed` every 30s while
  set, and the start/end lines. Backend untouched.
- Progress logger module: `print(..., file=sys.stderr, flush=True)`;
  wrapper exports `PYTHONUNBUFFERED=1` to spawned subprocesses.

**Acceptance:** automated test asserts a heartbeat line lands in a
`tee`'d file within 1s of emission; no backend regression
(`test_claude_code_backend` green).

## D5 — Per-attempt timeout + skip-to-next (~1h core + 30 min tests)

**Goal:** Configurable per-attempt timeout, correct classification,
campaign continuity — built on the merged Popen+pgkill.

- Wrapper resolves the timeout (300s cloud / 600s non-default
  `ANTHROPIC_BASE_URL` heuristic; `--attempt-timeout` /
  per-preset override) and threads it into the compare-config so the
  existing `RunContext.timeout_seconds` carries it to the backend.
- `run.py`: detect the backend's timeout signal (timeout note +
  `exit_code=None` in `backend_metadata`) → `score.scores.timeout =
  True`, `result: "timeout"`, `tests_output` records the harness-imposed
  timeout. Heartbeat emits the final `timeout after Ns — skipping` line.
- Aggregator (`report.py`/`report_winner.py`): count `timeout` as a
  `pass_rate` failure but surface it as a distinct verdict flag.

**Acceptance:** forced-hang test (`--attempt-timeout 5` + sleeping
stub candidate) → process group killed, `score.json.result ==
"timeout"`, next attempt runs, aggregate flags it separately.

## D4 — README rewrite (~1h, last)

**Goal:** "60-second quickstart" first; JSON/env-var docs demoted.

- New `## 60-second quickstart` (the issue's literal block) becomes
  the first section under the harness heading.
- The current JSON-first "Quick start: compare multiple LLMs" content
  moves under `### Advanced configuration`, alongside the
  four-`ANTHROPIC_*` incantation, the `claude-code:` long form, and
  `attempt_timeout_seconds`.

**Acceptance:** quickstart is first; links resolve; advanced subsection
retains every previously-documented knob.

## Reuse map

Defers to spec.md § "Reuse map". Headline: drive the unchanged
`compare`/`report`; extract (don't duplicate) the proxy lifecycle;
D5 reuses the existing process-group kill.

## Test strategy

Repo convention is stdlib `unittest` under
`scripts/benchmark_runner/tests/`. New test modules:

- `test_bench_parser.py` — spec-parser invariants (every colon-tag
  case, every prefix, `@endpoint`, unknown-token hint).
- `test_bench_envfill.py` — env-fill table correctness incl. vLLM
  probe branches (probes mocked).
- `test_bench_cli.py` — `--yes`/non-TTY, `--preset` + override,
  zero-config smoke (stub×stub), `--list-providers` Ollama 3-check
  (HTTP mocked, incl. < 0.14.0 → "unusable").
- `test_progress_heartbeat.py` — heartbeat fires ≥ once for a >30s
  fake attempt; line reaches a `tee`'d file within 1s.
- `test_timeout_classification.py` — forced-hang → `result:"timeout"`,
  campaign continues, aggregator flags separately.
- `test_proxy_helper.py` — LiteLLM config emits `hosted_vllm/`;
  teardown escalates SIGTERM→SIGKILL (subprocess mocked).
- Regression: extend `test_compare.py` to assert the legacy
  `--config` path is byte-for-byte unaffected.

Per the project's pre-existing-failure memory
(`project_benchmark_preexisting_env_test_failures`): run suites
per-module; `test_polyglot_adapter` ×4 + `test_cli_skeleton` hang are
known host-env failures, not regressions.

## Delegation strategy

Single build agent, phase-scoped per the deliverable order. The build
agent reads spec.md + plan.md + this tasks.md first, implements one
deliverable per scoped invocation, runs that deliverable's tests, and
does not advance until green. No parallel sub-agents — the deliverables
are sequential by construction (D5 ⟶ D2, D4 ⟶ all).

## Files to create

- `scripts/bench` (bash shim)
- `scripts/benchmark_runner/bench.py`
- `scripts/benchmark_runner/proxy.py`
- `scripts/benchmark_runner/progress.py` (stderr heartbeat logger)
- `benchmarks/presets/anthropic-tour.json`
- `benchmarks/presets/local-vs-cloud.json`
- `benchmarks/presets/cross-language-mini.json`
- `scripts/benchmark_runner/tests/test_bench_parser.py`
- `scripts/benchmark_runner/tests/test_bench_envfill.py`
- `scripts/benchmark_runner/tests/test_bench_cli.py`
- `scripts/benchmark_runner/tests/test_progress_heartbeat.py`
- `scripts/benchmark_runner/tests/test_timeout_classification.py`
- `scripts/benchmark_runner/tests/test_proxy_helper.py`
- `specs/benchmark-bench-driver/origin-alignment-2026-05-18-HHMM.md`

## Files to modify

- `scripts/benchmark_runner/run.py` — heartbeat hook in
  `_execute_attempt`; `result:"timeout"` classification + `scores.timeout`.
- `scripts/benchmark_runner/report.py` / `report_winner.py` — count
  `timeout` as failure, flag separately in verdicts.
- `scripts/benchmark_runner/compare.py` — pass the resolved
  per-attempt timeout through to `RunContext.timeout_seconds` (no
  orchestration change beyond threading the value).
- `scripts/run-compare-anthropic-vs-vllm.sh` — consume
  `proxy.py`; add the header note.
- `scripts/run-compare-anthropic-vs-ollama.sh` — header note.
- `benchmarks/README.md` — quickstart promotion / JSON demotion (D4).
- `scripts/benchmark_runner/tests/test_compare.py` — legacy-flow
  regression assertion.

## Rollout

1. One branch `feat/benchmark-bench-driver`, one PR titled
   `feat(benchmark): usable cross-LLM comparison driver (Closes #36)`.
2. Commit chain follows the deliverable order: D3, D1, D2, D5, D4,
   then a final "tests + origin-alignment" commit.
3. PR opened only after all suites green (per-module),
   `scripts/check-origin-alignment.sh benchmark-bench-driver` exits
   ≤ 1, and the executable artifacts (`scripts/bench` zero-config
   smoke, a real `--yes` stub run, the forced-hang test) have been
   run, not just syntax-checked (infra-verification rule).
4. Never push to master; PR via branch (memory
   `feedback_never_push_to_master`). Diff shown + explicit approval
   before every commit.
