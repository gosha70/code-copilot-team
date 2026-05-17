---
page_type: playbook
slug: drive-claude-code-with-local-vllm
title: Drive Claude Code With a Local vLLM Model
status: stable
last_reviewed: 2026-05-17
sources:
  - path: scripts/run-compare-anthropic-vs-vllm.sh
    sha: fe9c690
  - path: benchmarks/backends/vllm.md
    sha: a9a3b1e
  - issue: 35
---

# Drive Claude Code With a Local vLLM Model

## Symptom

You are pointing Claude Code at a local/remote vLLM model (to benchmark
it against an Anthropic model, or to run it as a cheaper provider) and
hitting one of these — each appears *only after* the previous is fixed,
and most surface as a bare HTTP 400 with no hint of the real cause:

- vLLM 404s on `/v1/messages` (it serves only the OpenAI API).
- Every call 400s in ~0.5 s, candidate scores a deterministic 0%.
- A 400 a few turns in: "maximum context length is N … prompt contains
  155596 characters".
- The model replies in prose; the agent loop never actions tool calls.
- The agent **solves the task at turn ~9, then the conversation crashes
  at turn ~10** with `212 validation errors: body.input should be a
  valid string`.

Root insight: the failure modes are *sequential and disguised*. The
canonical map (verified vs reported, with detection + fix for each) is
[`benchmarks/backends/vllm.md`](../../../benchmarks/backends/vllm.md).

## Recovery steps

1. **Front vLLM with a translation proxy.** Claude Code speaks the
   Anthropic API; vLLM serves only OpenAI. Use LiteLLM proxy mode. Do
   **not** point `ANTHROPIC_BASE_URL` straight at vLLM.
2. **Use the `hosted_vllm/` LiteLLM provider, never `openai/`.**
   LiteLLM ≥1.50 auto-routes `openai/` to vLLM's `/v1/responses`, whose
   schema rejects LiteLLM's multi-turn input-array shape (the turn-~10
   crash). `hosted_vllm/` pins `/v1/chat/completions`.
3. **Size `--max-model-len` from the envelope, not the task.**
   claude-code sends a ~38K-token request envelope every turn (system
   prompt + tool schemas + skills + CLAUDE.md + plugins), independent of
   task size, plus `max_output_tokens=32000`. Floor ≈ 70K; run at
   `--max-model-len 131072` for headroom.
4. **Start vLLM with tool parsing:** `--enable-auto-tool-choice
   --tool-call-parser qwen3_coder`. Omit `--reasoning-parser` for the
   *Coder* variant (it is wrong there).
5. **On the DGX/host:** `export VLLM_USE_FLASHINFER_MOE_FP4=0` and
   `export MAX_JOBS=2` to survive the FP4 MoE JIT compile.
6. Let `scripts/run-compare-anthropic-vs-vllm.sh` do steps 1–2 and the
   preflight gates automatically; you only own the vLLM launch (3–5).

## Verification

Before spending a multi-minute run, prove the route in ~60 s — a
two-turn (`tool_use → tool_result → continue`) Anthropic `/v1/messages`
call through the proxy:

- LiteLLM's upstream call must be `…/v1/chat/completions` (response id
  `chatcmpl-…`), **not** `…/v1/responses` (response id `resp_…`).
- The script's preflight already aborts when `max_model_len < 32000`
  and warns below the recommended `131072`.
- A clean end-to-end run looks like: zero 400s, zero failed commands,
  full multi-turn loop, scored pass — e.g. the 2026-05-17 baseline of
  Sonnet 3/3 (141±39 s) vs Qwen3-Coder-Next 3/3 (473±449 s) on
  `python/bowling`.

## Prevention

- The `hosted_vllm/` provider and the `max_model_len` preflight gate
  are baked into `scripts/run-compare-anthropic-vs-vllm.sh`
  (commits `7dd1565`, `c407cbd`, `c8b1f97`) — use the script, don't
  hand-roll the proxy config.
- Treat the context threshold as a **rule, not a number**:
  `required_ctx > measured_envelope + max_output + margin`. The ~38K
  envelope will grow as Anthropic adds tools; re-measure rather than
  trusting the constant.
- Add the proposed `multi_turn_continuation_observed` preflight gate
  (a 5-second two-turn dummy) so the Responses-API misroute is caught
  up front, not after a run. Tracked as follow-up in
  [`benchmarks/backends/vllm.md`](../../../benchmarks/backends/vllm.md).
- Read the result honestly: harness/routing validation plus one
  capable-on-`bowling` data point is **not** a general capability
  ranking. Do not cite it as one.

## Related

- [`benchmarks/backends/vllm.md`](../../../benchmarks/backends/vllm.md)
  — the full blocker map and the first comparative dataset.
- [Executable Artifacts Shipped Unexecuted](../incidents/executable-artifacts-shipped-unexecuted.md)
  — sibling lesson: verify the artifact end-to-end, don't trust syntax.
