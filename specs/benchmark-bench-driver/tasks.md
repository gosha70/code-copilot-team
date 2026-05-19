# Tasks — Benchmark `bench` Driver

Single PR on `feat/benchmark-bench-driver`. Each task is bounded and
independently verifiable. Deliverables ship in the issue's sequenced
order (D3 → D1 → D2 → D5 → D4); a deliverable's tasks are sequential,
and a later deliverable starts only after the earlier one's tasks are
green. AC map: spec.md § Success Criteria ←→ tasks below.

Pre-existing-failure note (memory
`project_benchmark_preexisting_env_test_failures`): run test suites
per-module; `test_polyglot_adapter` ×4 and a `test_cli_skeleton` hang
are known host-env failures on this machine, NOT regressions.

## D3 — Preset library

### T3.1 — Three preset configs + schema field
- **Output:** `benchmarks/presets/{anthropic-tour,local-vs-cloud,cross-language-mini}.json`
  per plan.md § D3; `local-vs-cloud.json` carries
  `attempt_timeout_seconds: 600`; optional top-level
  `attempt_timeout_seconds` (integer ≥ 1) added to
  `compare-config.schema.json` (`additionalProperties:false` kept).
  `cross-language-mini.json` is single-candidate (bench-preset shape).
- **Done when:** `anthropic-tour` + `local-vs-cloud` validate against
  the compare-config schema; `cross-language-mini` is documented as a
  single-candidate `run`-routed preset (not validated against the
  compare schema; minItems:2 guard untouched); every `task` id
  resolves in the pinned Polyglot snapshot (no `*/leap`, no
  `rust/clock`; `bowling` exists in python/go/java/javascript/rust).

**D3 commit:** `feat(benchmark): preset compare-configs (D3)`

## D1 — `scripts/bench` wrapper

### T1.1 — Bash shim
- **Output:** `scripts/bench` (exec `python3 -m benchmark_runner.bench`
  with PYTHONPATH set, mirroring `scripts/benchmark`), copyright header.
- **Done when:** `./scripts/bench --help` exits 0 and prints the CLI
  surface with inline examples.

### T1.2 — Spec-parser (provider whitelist)
- **Output:** parser in `benchmark_runner/bench.py`: closed provider
  set, the 4 parse rules, `@endpoint` as final segment, unknown-token
  `did you mean…` hint.
- **Done when:** `test_bench_parser.py` green incl. the invariant
  `ollama:qwen2.5-coder:7b → (ollama, qwen2.5-coder:7b, default)` and
  every whitelisted prefix + an unknown token.

### T1.3 — Env-fill + compare-config construction
- **Output:** env-fill table (spec.md § Env-var auto-fill) →
  `candidates[].env`; resolved JSON written to a tempfile; pass-through
  of `--task`/`--runs`/unknown flags to `./scripts/benchmark compare`.
- **Done when:** `test_bench_envfill.py` green; a constructed config
  loads via the unchanged `compare.load_config`.

### T1.4 — Shared LiteLLM proxy helper
- **Output:** `benchmark_runner/proxy.py` — extract the verified
  lifecycle (tempfile config with `hosted_vllm/` prefix, background
  start, healthcheck loop, SIGTERM→SIGKILL teardown) from
  `run-compare-anthropic-vs-vllm.sh`; that script now consumes it.
- **Done when:** `test_proxy_helper.py` green (config emits
  `hosted_vllm/`, teardown escalates); `run-compare-anthropic-vs-vllm.sh
  --help` still works and the script no longer carries its own copy.

> **Operational gate (user, 2026-05-18).** T1.4 is a refactor of
> load-bearing code disguised as a new file — it moves the verified
> two-day-debugged LiteLLM launch recipe out of
> `run-compare-anthropic-vs-vllm.sh`. After T1.4 lands and **before**
> starting T1.5, run `./scripts/run-compare-anthropic-vs-vllm.sh sonnet
> RedHatAI/Qwen3-Coder-Next-NVFP4` against the DGX Spark once and
> confirm no regression. (Requires the operator's DGX; if unreachable
> from the build environment, surface this as a pre-merge manual check
> the user must run, do not silently skip.)

### T1.5 — vLLM probe-then-decide
- **Output:** per `vllm:` candidate, probe `/v1/messages` then
  `/v1/models`; use-directly vs. ephemeral-proxy vs. fail-fast;
  context-length preflight (< 32000 abort, < 131072 warn).
- **Done when:** unit tests (probes mocked) cover all three branches;
  raw-vLLM branch spawns + tears down via `proxy.py`.

### T1.6 — Safe zero-config + confirmation gate + discovery
- **Output:** single-candidate routing (1 resolved candidate →
  `./scripts/benchmark run`; ≥2 → `compare`);
  no-arg stub×stub smoke + env summary + exit 0;
  TTY-aware confirmation gate (`--yes`/`--no-confirm`/non-TTY bypass;
  zero-Anthropic never prompts); `--list-presets`; `--list-providers`
  with the Ollama 3-check (≥ 0.14.0 → usable; else "detected but
  unusable: <reason>").
- **Done when:** `test_bench_cli.py` green; `./scripts/bench` (no args)
  exits 0 making no LLM call; `./scripts/benchmark compare --config
  <file>` regression assertion in `test_compare.py` green.

**D1 commit:** `feat(benchmark): scripts/bench wrapper + presets resolution + safe defaults (D1)`

## D2 — Live progress to stderr

### T2.1 — Heartbeat thread in orchestration
- **Output:** `benchmark_runner/progress.py` (stderr logger,
  `flush=True`); `run._execute_attempt` wraps each attempt in an
  `attempt_in_progress` Event + daemon thread emitting start / 30s
  heartbeats / end. Backend untouched. Wrapper exports
  `PYTHONUNBUFFERED=1` to subprocesses.
- **Done when:** `test_progress_heartbeat.py` green — a >30s fake
  attempt emits ≥1 heartbeat and a line reaches a `tee`'d file within
  1s; `test_claude_code_backend` still green.

**D2 commit:** `feat(benchmark): live progress heartbeat to stderr (D2)`

## D5 — Per-attempt timeout + skip-to-next

### T5.1 — Timeout resolution + threading
- **Output:** `compare._validate`/`CompareConfig` **parse and retain
  the top-level `attempt_timeout_seconds`** key (D3 added it to the
  schema but the parser ignores it — closes the D3→D5 carry-over P2
  flagged in review 2026-05-18). Wrapper resolves 300s cloud / 600s
  non-default `ANTHROPIC_BASE_URL` heuristic, `--attempt-timeout` +
  per-preset override; value threaded through compare-config →
  `RunContext.timeout_seconds` (backend already consumes it).
  Precedence: explicit `--attempt-timeout` > config
  `attempt_timeout_seconds` > heuristic default.
- **Done when:** unit test asserts the heuristic + override
  precedence AND that `load_config` on `local-vs-cloud.json` retains
  `attempt_timeout_seconds == 600` and it reaches the backend's
  effective timeout.

### T5.2 — `result:"timeout"` classification + skip
- **Output:** `run.py` detects the backend timeout signal (timeout
  note + `exit_code=None`) → `scores.timeout=True`, `result:"timeout"`,
  `tests_output` records it; heartbeat emits final `timeout after Ns —
  skipping`; aggregator counts it as a `pass_rate` failure but flags it
  as a distinct verdict.
- **Done when:** `test_timeout_classification.py` green — forced hang
  (`--attempt-timeout 5` + sleeping stub) is process-group killed,
  `score.json.result == "timeout"`, the next attempt runs, the
  aggregate flags it separately. Verdict/winner calculus otherwise
  unchanged (assert against an existing report fixture).

**D5 commit:** `feat(benchmark): per-attempt timeout + timeout classification (D5)`

## D4 — README rewrite

### T4.1 — Quickstart promotion / JSON demotion
- **Output:** new `## 60-second quickstart` (issue #36's literal
  block) is the first section under the harness heading; the current
  JSON-first content + four-`ANTHROPIC_*` incantation +
  `claude-code:` long form + `attempt_timeout_seconds` move under
  `### Advanced configuration`.
- **Done when:** quickstart is the first section; all README links
  resolve; no previously-documented knob is lost.

**D4 commit:** `docs(benchmark): README 60-second quickstart (D4)`

## Closeout

### TX.1 — Suites + origin-alignment + PR
- **Output:** all new + adjacent suites green (per-module); executable
  artifacts actually run (`./scripts/bench` zero-config smoke, a
  `--yes` stub run, the forced-hang test) per the infra-verification
  rule; a fresh `origin-alignment-2026-05-18-HHMM.md` written newer
  than spec.md/plan.md with a `Verdict:` line.
- **Done when:** `scripts/check-origin-alignment.sh
  benchmark-bench-driver` exits ≤ 1; diff shown and explicitly
  approved; single PR `feat(benchmark): usable cross-LLM comparison
  driver (Closes #36)` opened from `feat/benchmark-bench-driver`
  (never pushed to master).

**PR-description requirements (user operational notes, 2026-05-18):**

1. **Test-mode disclosure.** Name which suites were run, in which mode
   (single pytest call vs. per-module), and which specific files were
   per-module-invoked or skipped because of the known host-env
   failures (`test_polyglot_adapter` ×4, `test_cli_skeleton` hang).
   Reviewers must see this PR is the same shape as PR #38's history,
   not a hidden test regression.
2. **T5.2 metric-discontinuity flag.** State explicitly that
   `result:"timeout"` classification is non-comparable across the T5.2
   boundary: pre-T5.2 runs that recorded `fail` with elapsed near the
   timeout were misclassified timeouts; historical reports are NOT
   rescored. Aggregate pass-rates must not be compared across this
   boundary — the metric definition changed.
3. **Paired-example consistency.** Before merge, open this PR
   side-by-side with PR #38 (wiki-audit-trail) and confirm the two
   spec bundles share consistent conventions (frontmatter shape,
   origin-block style, deviation-section presence). The two land
   within days and will be cited as paired examples of the SDD
   discipline.
