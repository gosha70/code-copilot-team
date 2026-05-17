# Driving Claude Code with a local vLLM model

> **Why this file exists.** Confirming that a local LLM (Qwen3-Coder-Next
> on a DGX Spark) could stand in for an Anthropic model behind Claude
> Code took ~two days, because the failure modes are sequential: each
> one only surfaces after the previous is fixed, and most produce a
> generic HTTP 400 with no hint about the real cause. This page is the
> map so the next person spends ~two hours, not two days.
>
> Scope: this validates the **harness + routing + multi-turn agentic
> loop**, plus one capable-on-`python/bowling` data point. It is **not**
> a general capability ranking of Qwen vs Sonnet. See *How to read the
> result* at the bottom.

## Architecture

```
claude-code ──Anthropic /v1/messages──▶ LiteLLM proxy ──OpenAI /v1/chat/completions──▶ vLLM
(claude -p)                              127.0.0.1:8787                                 DGX Spark :8000
```

Claude Code speaks the Anthropic API; vLLM serves only the OpenAI API.
The LiteLLM proxy is the translation layer. `vLLM` is a *provider*, not
a backend — the only backend family is still `claude-code`; routing is
pure gateway env-vars (`ANTHROPIC_BASE_URL` etc.). The
`scripts/run-compare-anthropic-vs-vllm.sh` script automates all of it
(ephemeral venv, proxy lifecycle, preflight gates, compare).

## Working config (verified 2026-05-17)

Exact vLLM launch on the DGX Spark that produced a clean run:

Copy-paste safe — no inline comments on the continued lines (a `#`
after a `\` cancels the line continuation and truncates the command):

```bash
pkill -f "vllm.entrypoints.openai.api_server" || true
pkill -f "EngineCore" || true
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null
source ~/dgx-spark-vllm/vllm_env/bin/activate
export VLLM_USE_FLASHINFER_MOE_FP4=0
export MAX_JOBS=2

python -m vllm.entrypoints.openai.api_server \
  --model ~/dgx-spark-vllm/models/Qwen3-Coder-Next-NVFP4 \
  --served-model-name RedHatAI/Qwen3-Coder-Next-NVFP4 \
  --enforce-eager \
  --max-model-len 131072 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.72 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --trust-remote-code \
  --host 0.0.0.0 --port 8000
```

Which flag clears which blocker:

- `VLLM_USE_FLASHINFER_MOE_FP4=0` + `MAX_JOBS=2` → blocker 1 (FP4 MoE
  JIT compile OOM).
- `--max-model-len 131072` → blocker 3 (envelope + output context).
- `--enable-auto-tool-choice` + `--tool-call-parser qwen3_coder` →
  blocker 4 (tool-call parsing). **Do not** add `--reasoning-parser
  qwen3_coder` — wrong for the Coder variant (blocker 2).

Client side (handled automatically by the script — no manual step):
LiteLLM config uses the **`hosted_vllm/`** provider prefix, not
`openai/` (blocker 5).

## The blockers, in the order they bite

Each is invisible until the previous one is cleared. "Verified" =
reproduced from run transcripts and/or a live proxy test this session;
"reported" = observed by the operator on the DGX.

| # | Symptom | Root cause | Fix | Status |
|---|---|---|---|---|
| 1 | vLLM won't start / OOM during FlashInfer JIT compile | FP4 MoE kernel JIT compile exhausts memory on Spark | `export VLLM_USE_FLASHINFER_MOE_FP4=0`, `export MAX_JOBS=2` | reported |
| 2 | reasoning text leaks into content / parser error | `--reasoning-parser qwen3_coder` is wrong for the *Coder* variant | **omit `--reasoning-parser` entirely**; keep `--tool-call-parser qwen3_coder` | reported |
| 3a | every call 400s instantly (~0.5s API), 0% pass | `max_output_tokens=32000` > `--max-model-len 8192` — rejected before generation | raise `--max-model-len` | verified |
| 3b | 400 a few turns in: "maximum context length is 32768 … prompt contains 155596 characters" | claude-code sends a ~38K-token envelope every turn (system + tool schemas + skills + CLAUDE.md + plugins), independent of task size | `--max-model-len 131072` (≈2× the ~70K floor) | verified |
| 4 | tool calls ignored, model replies in prose, agent loop can't act | vLLM not started with tool-call parsing | `--enable-auto-tool-choice --tool-call-parser qwen3_coder` | verified |
| 5 | agent solves task at turn ~9, conversation **crashes at turn ~10** with "212 validation errors: body.input should be a valid string" | LiteLLM ≥1.50 auto-routes the `openai/` provider to vLLM's `/v1/responses`; vLLM's Responses API rejects LiteLLM's multi-turn input-array shape | use the **`hosted_vllm/`** provider prefix (pins `/v1/chat/completions`) | verified (reproduced live: `openai/`→`/v1/responses`, `hosted_vllm/`→`/v1/chat/completions`) |

Blockers 3 and 5 are now caught **before** a run is spent:
preflight aborts when `max_model_len < 32000` and warns below the
recommended `131072` (commit `7dd1565`); the script always emits the
`hosted_vllm/` config (commit `c407cbd`).

## The first clean apples-to-apples result

`aider-polyglot` / `python/bowling`, 3 runs each, 2026-05-17:

| Candidate | Pass | Elapsed (mean ± σ) | Per-attempt |
|---|---|---|---|
| `anthropic-sonnet` | **3/3** | 141 ± 39 s | 186 / 123 / 116 |
| `vllm` Qwen3-Coder-Next-NVFP4 | **3/3** | 473 ± 449 s | 322 / 120 / 978 |

Zero 400s, zero failed commands, zero timeouts, full multi-turn loop.
Winner verdict: *no winner declared* on every axis — pass-rate tied;
elapsed Δ within the 2σ calibrated rule given Qwen's variance. That is
the statistically correct call.

## How to read the result

- **Correctness: tied** on this one task. Qwen3-Coder-Next via vLLM is
  *capable* of driving Claude Code's tool loop end-to-end.
- **Speed: Qwen ~3.3× slower, high variance** (120 s → 978 s). Cause is
  the DGX launch profile, not the model: `--enforce-eager` (no CUDA
  graphs) + `--max-num-batched-tokens 8192` re-prefilling the ~38K
  envelope in 8K chunks every turn + `--max-num-seqs 1`.
- **n=3, single fixture, single task.** This validates the harness,
  routing, and multi-turn loop and yields one comparative data point.
  It is **not** a general "Qwen ≈ Sonnet" ranking. Do not cite it as
  one. A real comparison needs cross-fixture, higher-n runs.

## Follow-up (file post-merge, not in this PR)

- **`multi_turn_continuation_observed` preflight gate** — a ~5-second
  two-turn dummy `tool_use → tool_result → continue` through the proxy.
  This would have caught blocker 5 (the Responses-API misroute) up
  front instead of after a multi-minute run.
- **`tool_calls_observed` preflight gate** — single-turn dummy tool
  call; catches blocker 4 before a run is spent.
- **Cross-fixture validation** — take this from "harness works" to a
  publishable comparative dataset (more tasks, higher n). Separate
  issue; explicitly **out of scope** for the current PR.
