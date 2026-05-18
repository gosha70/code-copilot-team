---
feature_id: benchmark-bench-driver
spec_mode: full
status: draft
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
    Issue #36: "The harness's underlying machinery is correct but its
    user-facing surface (./scripts/benchmark compare + 50-line JSON
    configs + no live progress + no timeouts + dangerous zero-config
    defaults) is not." Deliver a single user-facing wrapper
    (scripts/bench) with safe defaults, terse provider:model[@endpoint]
    specs, live progress to stderr, a per-attempt timeout with
    skip-to-next, a three-preset library, and a rewritten README
    quickstart. "It does not change the harness's verdict logic — only
    how users invoke it." Five tightly-coupled deliverables D1–D5;
    explicit verbatim out-of-scope list; empirically motivated by the
    2026-05-09 release-day session (colon-parsing, subprocess hang,
    silent-spend). Three planning decisions taken with the user
    (2026-05-18) refine D1's vLLM path and the D2/D5 implementation
    basis — see § Deviation from origin.
---

# Benchmark `bench` Driver — usable cross-LLM comparison wrapper

> **Wrapper, not a rewrite (per issue #36).** This feature adds a
> translation layer over the PR #35 harness. It changes **no**
> verdict, scoring, isolation, or run-record logic. Every behaviour
> here resolves down to a `./scripts/benchmark compare --config
> <tempfile>` invocation the harness already supports. Where issue #36's
> deliverable text (written 2026-05-09) contradicts the code that
> actually merged in PR #35 (2026-05-17), the merged code is treated
> as ground truth and the divergence is recorded in § Deviation from
> origin — confirmed with the user 2026-05-18.

## Problem

PR #35 (closed #32) shipped a credible benchmark *framework*:
reproducible run records, calibrated winner declaration, provider-routing
capture, a benchmark-agnostic adapter contract, and a
`./scripts/benchmark compare --config <json>` driver. It is not yet a
credible *product*. The gaps, verbatim from issue #36:

1. No one-line invocation for the 80% case ("Sonnet vs Ollama-Qwen on
   one Python task" requires hand-authoring a JSON config).
2. Provider env vars require expert knowledge (the four-`ANTHROPIC_*`
   incantation, undiscoverable by a first-time user).
3. No live progress — a 90-minute run is indistinguishable from a hung
   one without a side-terminal monitor.
4. No per-attempt timeout / hang recovery surfaced to the user
   (empirically: `claude -p` hung on truncated Qwen thinking-mode
   responses; the campaign blocked until manually killed).
5. No preset library — every comparison shape is re-derived.
6. No environment auto-detection (is Ollama up? which models?).
7. Dangerous zero-config default — `./scripts/bench` with no args must
   not bill the user's Anthropic account before they read what they
   authorized.

The cumulative effect: a user spent a release-day evening trying to run
one comparison, the run silently hung, and the reflexive response was
"throw the feature out." This feature fixes the UX so the framework's
value becomes accessible without a guide and without surprise bills.

## User Scenarios

1. **First-time check (no spend).** A user clones the repo and types
   `./scripts/bench`. It runs a stub×stub end-to-end smoke (< 30s, no
   auth, no LLM call), prints which LLM endpoints the environment has,
   and exits 0. No Anthropic spend.
2. **The 80% comparison.** `./scripts/bench sonnet
   ollama:qwen2.5-coder:7b` parses the colon-bearing tag correctly,
   auto-fills the four `ANTHROPIC_*` vars for the Ollama candidate,
   shows a confirmation gate (because `sonnet` bills Anthropic),
   and on `y` runs end-to-end with live progress to stderr.
3. **CI / non-interactive.** `./scripts/bench --yes sonnet
   ollama:qwen2.5-coder:7b` skips the gate. A non-TTY stdin is treated
   as `--yes`.
4. **Curated comparison.** `./scripts/bench --preset local-vs-cloud
   --runs 5` runs a hand-curated config with the run count overridden.
5. **A hung attempt.** An attempt that exceeds its per-attempt timeout
   is killed (process-group SIGKILL), recorded `result: "timeout"`, and
   the campaign continues to the next attempt with no human action.
6. **Local vLLM, user's own proxy.** `./scripts/bench sonnet
   vllm:Qwen3-Coder@http://127.0.0.1:8787` — the wrapper probes the
   endpoint, finds it answers the Anthropic Messages API (the user's
   long-lived LiteLLM proxy), and uses it directly without spawning
   anything.
7. **Local vLLM, raw endpoint.** `./scripts/bench sonnet
   vllm:Qwen3-Coder@http://192.168.1.23:8000` — the wrapper probes,
   finds only an OpenAI `/v1/models` surface, spawns an ephemeral
   LiteLLM Anthropic→OpenAI proxy in front of it (reusing the verified
   `run-compare-anthropic-vs-vllm.sh` launch recipe), runs the
   context-length/tool-parser preflight, and tears the proxy down on
   exit.
8. **Discovery.** `./scripts/bench --help`, `--list-presets`,
   `--list-providers` each print useful, example-bearing output.
   `--list-providers` flags an Ollama < 0.14.0 install as "detected but
   unusable" with the version reason, not as a usable backend.

## Interface

### CLI surface — `scripts/bench`

`scripts/bench` is a thin bash shim (mirroring `scripts/benchmark`)
that sets `PYTHONPATH` and execs `python3 -m benchmark_runner.bench`.
Rationale (design decision, user-delegated 2026-05-18): the deliverable
is dominated by testable logic — spec-parsing with the provider
whitelist, env-var construction, endpoint probes, preset resolution —
which is far cheaper to unit-test in Python than in bash, and keeps one
language with the rest of `benchmark_runner/`.

```
./scripts/bench                                   # safe default: stub×stub smoke + env detection
./scripts/bench sonnet opus
./scripts/bench sonnet ollama:qwen2.5-coder:7b
./scripts/bench sonnet vllm:Qwen3-Coder@http://127.0.0.1:8787
./scripts/bench --task python/bowling,go/leap --runs 5 sonnet ollama:qwen2.5-coder:7b
./scripts/bench --preset local-vs-cloud
./scripts/bench --yes sonnet ollama:qwen2.5-coder:7b   # bypass confirmation gate (CI)
./scripts/bench --attempt-timeout 600 sonnet ollama:qwen3.6:27b
./scripts/bench --help | --list-presets | --list-providers
```

Unknown flags pass through verbatim to `./scripts/benchmark compare`.
`--report-only` and other compare flags translate 1:1.

### Spec-parsing contract (provider whitelist — colons in model names are real)

Provider tokens are a **closed set**: `sonnet`, `opus`, `haiku`,
`claude-code:`, `ollama:`, `vllm:`, `lmstudio:`, `openrouter:`.
Anything else fails fast with a `did you mean…` hint. Parser rules:

1. Token ∈ `{sonnet, opus, haiku}` → `claude-code:<token>`, ambient
   Anthropic auth.
2. Token starts `claude-code:` → suffix is the model verbatim.
3. Token starts a known endpoint-bearing prefix (`ollama:`, `vllm:`,
   `lmstudio:`, `openrouter:`) → **strip only that one prefix**;
   everything after is the `model[@endpoint]` blob. The parser does
   **not** split on the second colon.
4. `@endpoint` is recognised only as the final `@`-introduced segment.

Testable invariant: `ollama:qwen2.5-coder:7b` →
`(provider=ollama, model=qwen2.5-coder:7b, endpoint=default)`, **never**
`(model=qwen2.5-coder, endpoint=7b)`.

### Env-var auto-fill contract

| Spec | `ANTHROPIC_BASE_URL` | `ANTHROPIC_AUTH_TOKEN` | `ANTHROPIC_DEFAULT_SONNET_MODEL` / `…_HAIKU_MODEL` |
|---|---|---|---|
| `sonnet`/`opus`/`haiku`/`claude-code:<m>` | unset (ambient) | unset (ambient) | unset |
| `ollama:<m>[@ep]` | `<ep or http://localhost:11434>` | `ollama` | `<m>` |
| `vllm:<m>@<ep>` | **probe-resolved** (see vLLM contract) | `vllm-user-proxy` or `vllm-ephemeral` | `<m>` |
| `lmstudio:<m>[@ep]` | `<ep or http://localhost:1234>` | `lmstudio` | `<m>` |
| `openrouter:<m>` | `https://openrouter.ai/api/v1` | `$OPENROUTER_API_KEY` (error if unset) | `<m>` |

These map onto the existing compare-config `candidates[].env` block;
the wrapper writes the JSON, the harness applies/restores env via the
already-shipped `compare._patched_env`.

### vLLM contract (probe-then-decide)

For each `vllm:<model>@<endpoint>` candidate, at wrapper startup:

1. Probe Anthropic Messages first (cheap, definitive): `POST
   <endpoint>/v1/messages` with `anthropic-version: 2023-06-01` and a
   minimal body. Any 2xx, or any non-404 4xx → endpoint is an
   Anthropic-shape gateway (the user's proxy). Use it directly:
   `ANTHROPIC_BASE_URL=<endpoint>`, `ANTHROPIC_AUTH_TOKEN=vllm-user-proxy`.
2. Else probe OpenAI: `GET <endpoint>/v1/models` → 200 with `data: [...]`
   → raw vLLM. Spawn an **ephemeral LiteLLM** Anthropic→OpenAI proxy
   in front of it (shared helper, see Reuse map), point
   `ANTHROPIC_BASE_URL` at the local proxy,
   `ANTHROPIC_AUTH_TOKEN=vllm-ephemeral`, register a cleanup handler,
   and run the vLLM preflight (context-length abort < 32000, warn <
   131072; tool-call-parser warn).
3. Else fail fast: `endpoint <ep> answers neither /v1/messages nor
   /v1/models; check the URL or start vLLM via
   run-compare-anthropic-vs-vllm.sh`.

The ephemeral proxy uses the verified `hosted_vllm/` provider prefix
(never `openai/` — that misroutes to `/v1/responses` and 400s
mid-conversation; blocker #5 in `benchmarks/backends/vllm.md`). Proxy
lifecycle: SIGTERM on wrapper exit, SIGKILL fallback after 5s — same
escalation shape as D5's per-attempt kill.

### Safe zero-config behaviour

`./scripts/bench` with no candidates and no `--preset`:

1. Run stub×stub end-to-end smoke (proves wrapper + harness + report
   pipeline; free, < 30s, no auth).
2. Print a detected-environments summary (Anthropic key last-4,
   Ollama/LM Studio reachable + model count).
3. If no endpoints detected, print only the wrapper-works message and
   point at `--help` / README. Always exit 0 on a passing smoke; no
   LLM call.

### Confirmation gate

Any invocation resolving to ≥1 Anthropic-API-bearing candidate
(`sonnet`/`opus`/`haiku`/`claude-code:<m>` with **no** env override
redirecting it elsewhere) prints the attempt/candidate/spend summary
and prompts `Continue? [y/N]`. `--yes` / `--no-confirm`, or a non-TTY
stdin, bypass it. Zero-Anthropic (all-local) invocations never prompt.
No token/dollar estimates (cost reporting is permanently out of scope —
the prompt says so and points at `spec.md § cost_reporting`).

### `--list-providers` detection rules

- **Anthropic.** `ANTHROPIC_API_KEY` set → `Anthropic API (key
  sk-ant-…XXXX)` (last 4 chars only; never echo the key).
- **Ollama.** Three checks, all must pass: (a) `which ollama` or
  `OLLAMA_HOST` set; (b) `GET <host>:11434/api/version` ≥ 0.14.0
  (when `/v1/messages` landed); (c) `GET /api/tags` enumerates models.
  Any failure → `Ollama detected but unusable: <reason>`.
- **vLLM.** Opt-in only — not probed. Resolved per-candidate via the
  vLLM contract above.
- **LM Studio.** Probe `GET http://localhost:1234/v1/models`,
  enumerate if reachable.

### Live progress contract (D2)

Progress lines go to **stderr** (stdout stays clean JSON). Shapes:

```
[1/6] claude-code:sonnet  python/bowling  attempt 1  starting...
[1/6] claude-code:sonnet  python/bowling  attempt 1  running... 30s elapsed
[1/6] claude-code:sonnet  python/bowling  attempt 1  pass (87s, 12 tool calls)
```

A daemon **heartbeat thread** owned by the orchestration layer
(`run._execute_attempt`) emits a line every 30s while an
`attempt_in_progress` event is set; the orchestrator clears it on
attempt completion. The backend is **not** modified for D2 (it already
blocks in `proc.communicate(timeout=)` and returns nothing meanwhile —
the heartbeat-thread design from issue #36 option (a) is correct and
the only option compatible with the merged backend). Flush discipline
is mandatory: every progress line uses `print(..., file=sys.stderr,
flush=True)`; the wrapper additionally exports `PYTHONUNBUFFERED=1`
into every subprocess it spawns.

### Per-attempt timeout + skip-to-next contract (D5)

Built **on** the merged backend's existing
`subprocess.Popen(start_new_session=True)` + `os.killpg(SIGKILL)` path
(the "Bug #6" fix) — not by re-introducing kill logic. The wrapper
resolves a per-attempt timeout and threads it through the existing
`RunContext.timeout_seconds` (already consumed by the claude-code
backend; precedence is already `ctx.timeout_seconds →
CCT_CLAUDE_TIMEOUT_SECONDS → 600`). What this feature adds:

- Default: 300s for `claude-code:` cloud candidates; 600s for any
  candidate with a non-default `ANTHROPIC_BASE_URL` (local-LLM
  heuristic). Override: `--attempt-timeout <s>` (CLI) or per-preset
  `attempt_timeout_seconds`.
- On timeout the backend already kills the process group and returns a
  `BackendResult` carrying the timeout note + `exit_code=None`. D5
  plumbs that signal into a new `result: "timeout"` classification in
  `score.json` (today a timed-out attempt is misclassified `fail`
  because `_classify_result` only knows pass/fail/error and
  `scores.timeout` is hardcoded `False`).
- The aggregator counts `timeout` as a failure for `pass_rate` but
  flags it separately in verdicts so reviewers can tell "the LLM
  failed" from "the LLM hung."
- The heartbeat thread emits a final
  `… attempt K  timeout after <s>s — skipping` line.
- Skip-to-next already works (the backend returns rather than raises);
  D5 makes it observable and correctly classified.

## Reuse map

- **Stage 1 — reuse, do not duplicate.** The wrapper resolves every
  invocation to a compare-config and calls the *unchanged*
  `compare.load_config` / `compare.run_comparison` /
  `report.render_report`. No fork of the orchestrator.
- The shared LiteLLM proxy lifecycle is **extracted** from
  `scripts/run-compare-anthropic-vs-vllm.sh` into a single source of
  truth (`scripts/benchmark_runner/proxy.py`), then re-used by both the
  wrapper (ephemeral spawn for raw-vLLM `vllm:` candidates) and the
  legacy script (which sources/imports it instead of carrying its own
  copy). The verified DGX launch recipe and `hosted_vllm/` prefix move
  with it.
- D5 reuses the merged backend's process-group kill; it adds only
  classification, not a second kill path.
- The env-fill writes the existing `candidates[].env` schema;
  `compare._patched_env` applies/restores it unchanged.

## Design Decisions

- **Wrapper language: Python**, entrypoint a bash shim. (User-delegated;
  rationale above.)
- **Legacy scripts kept.** `run-compare-anthropic-vs-ollama.sh` and
  `-vs-vllm.sh` stay runnable and authoritative as a reference path;
  each gains a one-paragraph header note: "this script is one way to
  run a comparison; `scripts/bench` is the daily tool — either is
  supported." Their load-bearing proxy logic is not deleted but
  extracted to the shared helper they then consume. Resolves OQ-1.
- **vLLM: probe-then-decide.** One token (`vllm:m@ep`); the wrapper
  picks user-proxy vs ephemeral-proxy by probing. Resolves the
  contradiction between issue #36 D1's literal env-fill and the merged
  PR #35 reality that Claude Code cannot speak raw vLLM. Resolves OQ-2.
- **D2/D5 built on merged Popen+pgkill**, divergence documented.
  Resolves OQ-3.
- **Single-candidate presets route to `run`, not `compare`**
  (user-confirmed 2026-05-18, build-time conflict OQ-4). issue #36's
  `cross-language-mini` is explicitly one candidate (a liveness sweep),
  but `compare` + `compare-config.schema.json` require ≥2 candidates.
  The wrapper detects a 1-candidate resolved invocation/preset and
  calls `./scripts/benchmark run --task … --runs …` instead of
  `compare`. The compare schema's `minItems: 2` guard and
  `compare.py`'s runtime ≥2 reject are **unchanged**;
  `cross-language-mini.json` validates against the documented bench
  preset shape, not the compare schema.

## Requirements

1. `scripts/bench` (bash shim) + `benchmark_runner/bench.py` implement
   the CLI surface, spec-parser (provider whitelist), env-fill, JSON
   construction, pass-through, safe zero-config smoke, confirmation
   gate, `--list-presets`, `--list-providers` with the Ollama 3-check.
2. The spec-parser satisfies the colon-tag invariant and every
   whitelisted prefix; unknown tokens fail fast with a hint.
3. vLLM probe-then-decide per the vLLM contract; ephemeral proxy via
   the shared helper; preflight aborts on context-length < 32000.
4. `benchmarks/presets/{anthropic-tour,local-vs-cloud,cross-language-mini}.json`
   exist; `local-vs-cloud.json` carries `attempt_timeout_seconds: 600`
   (top-level optional field added to `compare-config.schema.json` in
   D3; made load-bearing in D5). `cross-language-mini.json` is a
   single-candidate bench preset routed to `benchmark run` by the
   wrapper (it is not a compare-config and is not validated against
   that schema). Preset task ids must exist in the pinned Polyglot
   snapshot — note the snapshot has **no `*/leap` and no `rust/clock`**;
   `bowling` exists in python/go/java/javascript/rust.
5. Live progress to stderr: attempt-start, 30s heartbeats,
   attempt-end, for every attempt, with flush discipline; visible
   within 1s under `2>&1 | tee`.
6. Per-attempt timeout with the cloud/local default heuristic and
   `--attempt-timeout` override; timed-out attempts recorded
   `result: "timeout"`, counted as failure but flagged separately;
   campaign continues.
7. README: a "60-second quickstart" becomes the first section under
   the harness heading; the JSON-config docs and the four-`ANTHROPIC_*`
   incantation are demoted to an `### Advanced configuration`
   subsection.
8. The JSON config flow (`./scripts/benchmark compare --config`)
   continues to work unchanged (regression-tested).
9. The shared proxy helper is the single source of truth;
   `run-compare-anthropic-vs-vllm.sh` consumes it (no duplicated
   launch recipe) and still runs end-to-end.

## Constraints / What NOT to Build

Verbatim from issue #36's out-of-scope list (non-negotiable):

1. **No additional copilot backends** (Aider, Codex, GH Copilot CLI) —
   issue #33.
2. **No additional benchmark adapters** (SWE-bench Verified,
   BigCodeBench, LiveCodeBench) — issue #33.
3. **No LLM-judge scoring** — issue #34.
4. **No HTML / CSV / chart reports** — issue #34.
5. **No cost reporting** — deferred permanently (`§ cost_reporting`:
   the confirmation gate states call counts, never tokens/dollars).
6. **No GUI / web UI** for inspecting run-dirs.
7. **No cross-campaign regression mode** (`--baseline … --candidate …`
   over time).
8. **No change to verdict / scoring / isolation / run-record logic.**
   D5 adds a `timeout` result *value*; it does not alter the
   pass/fail/winner calculus beyond counting timeouts as failures.

## Key Entities

- **Candidate spec** — a parsed `provider:model[@endpoint]` token.
- **Resolved candidate** — `{name, backend: "claude-code", model, env}`
  ready to serialize into a compare-config `candidates[]` entry.
- **Preset** — a committed JSON compare-config under
  `benchmarks/presets/`, overridable by `--runs` / `--task` /
  `--attempt-timeout`.
- **Progress event** — a stderr line keyed by
  `[idx/total] candidate task attempt state`.
- **Ephemeral proxy** — a wrapper-owned LiteLLM subprocess for
  raw-vLLM candidates; lifecycle bound to the wrapper process.

## Success Criteria

- [ ] `./scripts/bench` (no args) runs stub×stub, prints detected
      environments, exits 0, makes no LLM call / no Anthropic spend.
- [ ] `./scripts/bench sonnet ollama:qwen2.5-coder:7b` parses the
      colon tag correctly, auto-fills the four `ANTHROPIC_*` vars for
      the Ollama candidate, prompts, and runs end-to-end after `y`.
- [ ] `./scripts/bench --yes …` skips the gate; non-TTY stdin is
      treated as `--yes`.
- [ ] Live progress shows start / 30s+60s heartbeats / end for every
      attempt, with **no 60s silent window even under `2>&1 | tee
      /tmp/log`**.
- [ ] An attempt forced to hang (`--attempt-timeout 5` + a sleeping
      candidate) is killed after the timeout, recorded
      `result: "timeout"`, and the campaign continues.
- [ ] All three presets execute when prerequisites are met
      (`cross-language-mini` via `run`, the other two via `compare`);
      `--preset … --runs N` overrides the preset run count.
- [ ] `--help`, `--list-presets`, `--list-providers` produce useful
      output with inline examples; an Ollama < 0.14.0 is flagged
      "detected but unusable" with the version reason.
- [ ] `vllm:m@<anthropic-proxy>` uses it directly; `vllm:m@<raw-vllm>`
      spawns + tears down an ephemeral LiteLLM proxy and runs the
      context-length preflight.
- [ ] `./scripts/benchmark compare --config <file>` still works
      unchanged (regression test green).
- [ ] `run-compare-anthropic-vs-vllm.sh` still runs end-to-end after
      consuming the extracted shared proxy helper.
- [ ] README's 60-second quickstart is the first section under
      `## Benchmark Harness`; JSON config docs demoted to
      `### Advanced configuration`.
- [ ] `scripts/check-origin-alignment.sh benchmark-bench-driver`
      exits 0 (or 1 with the documented divergence) before the PR.

## Deviation from origin

Three refinements to issue #36's deliverable text, each confirmed with
the user 2026-05-18. Issue #36's body was written 2026-05-09; PR #35
merged 2026-05-17 with code that postdates and partly invalidates the
issue's implementation premises. The issue's *intent* and *acceptance
criteria* are delivered in full; the *implementation basis* is adjusted.

- **D2/D5 implementation basis.** Issue #36 D2/D5 assume backends use
  blocking `subprocess.run(capture_output=True)` and prescribe "pick
  option (a), refactor it." The merged claude-code backend already uses
  `subprocess.Popen(start_new_session=True)` + `os.killpg(SIGKILL)` +
  a per-attempt timeout (the "Bug #6" fix, 2026-05-17). This feature
  builds the heartbeat thread and the `result: "timeout"`
  classification **on** that mechanism rather than re-introducing a
  kill path. All D2/D5 acceptance criteria remain deliverable. (OQ-3.)
- **D1 vLLM env-fill → probe-then-decide.** Issue #36 D1 specifies a
  single `vllm:` env shape. Merged PR #35 + `benchmarks/backends/vllm.md`
  prove Claude Code cannot speak raw vLLM (OpenAI-only); a literal
  env-fill yields a broken candidate. The wrapper instead probes and
  auto-selects user-proxy vs. ephemeral-proxy. +~30 min over the D1
  budget; justified by the user requirement to retain the verified
  `run-compare-*.sh` workflows. (OQ-1, OQ-2.)
- **Legacy-script fate.** Issue #36 says `scripts/bench` "supersedes"
  the two ad-hoc drivers. Decision: keep both runnable and
  authoritative, extract their load-bearing LiteLLM proxy logic into a
  shared helper consumed by both the wrapper and the scripts. No
  capability is discarded. (OQ-1.)

This section, plus a newer `origin-alignment-YYYY-MM-DD-HHMM.md`
record, satisfies the origin-confirmation circuit breaker
(`scripts/check-origin-alignment.sh`): documented divergence → exit ≤ 1.

## Sources

- `issue: gosha70/code-copilot-team#36` — the five deliverables,
  acceptance criteria, verbatim out-of-scope list, implementation
  budget.
- `pr: gosha70/code-copilot-team#35` — the merged harness this wraps;
  the Popen+pgkill "Bug #6" fix that D2/D5 build on.
- `path: scripts/benchmark_runner/{compare,run,cli}.py` — the
  unchanged orchestration the wrapper drives.
- `path: scripts/benchmark_runner/backends/claude_code.py` — the
  merged timeout/process-group mechanism D5 layers on.
- `path: benchmarks/backends/vllm.md` — the four-blocker vLLM map;
  `hosted_vllm/` prefix; the two follow-up preflight gates.
- `path: scripts/run-compare-anthropic-vs-{ollama,vllm}.sh` — the
  load-bearing legacy drivers; source of the extracted proxy helper.
- `url: https://github.com/ollama/ollama/releases` — `/v1/messages`
  added in 0.14.0; the `--list-providers` version-check rationale.
- `decisions: 2026-05-18 user clarifications` — OQ-1 (keep + extract),
  OQ-2 (probe-then-decide), OQ-3 (build on merged Popen+pgkill).
