# DGX Spark + vLLM: Qwen3.8-27B-NVFP4 operator manual

> **Companion documents.** This manual refers to `dgx-spark.md`, `vllm.md`, `dgx-spark-vllm.md`, an rlm-studio `README.md` and the `scripts/dgx-spark/vllm/*.sh` scripts. Those live in the owner's **rlm-studio** repository, not here; the names are kept as plain references. The *DGX Spark — setup & cookbook* page in this section covers the setup they describe.

**Revised 2026-08-28.** Two different things are being tracked here, and conflating them is the main way to misread this document. **The model is verified on this hardware class.** A published run on a single GB10 with 121.63 GiB usable brought up `unsloth/Qwen3.8-27B-NVFP4` on vLLM `0.26.1rc1` at the native 262,144-token window, with no vLLM modifications, and exercised reasoning, tool calling, MTP speculative decoding, long context and memory. vLLM has since published an official Qwen3.8-27B recipe (updated 2026-08-26) covering the NVFP4 checkpoint, FP8 KV cache, the Qwen reasoning parser, structured tool calling and MTP. A separate 2026-08-14/17 hands-on compared llama.cpp, Ollama, vLLM and SGLang on a real Spark. This is not a hypothesis. **This configuration is not verified on** ***our*** **Spark.** Nothing here has been booted on our box, and the §5 memory arithmetic is derived rather than measured. Replace the derived numbers with measured ones per `dgx-spark-vllm.md` §9.6` before quoting them as facts about our hardware. The default configuration in §3 is now the **262,144-token validation config**, not the 1M one. See §9.

This doc is the Qwen3.8-27B companion to `dgx-spark.md` (general DGX Spark setup), `vllm.md` (general vLLM) and `dgx-spark-vllm.md` (the *verified* Qwen3-Coder-Next-NVFP4 manual). Read `dgx-spark.md` §4 first — it is where vLLM and flashinfer actually get built, and this doc assumes both are already in place.

`dgx-spark-vllm.md` is the reference point for everything below. Where this doc says "carries over" or "delta", the comparison is against that file.

## 1. When to use this doc

You want a **long-context** self-hosted model on the Spark, reachable over an OpenAI-compatible API for RLM Studio and over an Anthropic-compatible API for agent clients, with tool calling on both. The distinguishing property of this checkpoint against the one in `dgx-spark-vllm.md` is not quality — it is **weight footprint**:

|  | `Qwen3-Coder-Next-NVFP4` | `Qwen3.8-27B-NVFP4` |
|---|---|---|
| Architecture | Qwen3-Next hybrid MoE, 80B-A3B, 48 layers (12 full-attention) | **Qwen3.5-family hybrid** — Gated DeltaNet linear attention + full attention, MTP draft head in the weights. Resolves as `Qwen3_5ForConditionalGeneration`; multimodal, so a vision tower is present |
| Weights | ~44 GiB | ~22.5 GiB + 0.81 GiB MTP |
| KV per token | ~24 KB (hybrid attention pays off) | ~37.2 KB |
| Native window | 262,144 | 262,144 |
| Extended window | untested | 1,010,000 via YaRN |
| Speculative decoding | none | MTP, no second model file |
| Our verified ceiling | 131,072 | none yet |

**Corrected 2026-09-07 from a real boot on spark-c2e5.** Earlier revisions described this checkpoint as a plain dense 27B. The boot log disproves that: vLLM resolves it as `Qwen3_5ForConditionalGeneration`, selects the Gated DeltaNet linear-attention kernels (`Using Triton/FLA GDN prefill kernel`, `GDN decode kernel: cuda`), and sets a **Mamba cache mode** — so it is a hybrid, like Coder-Next, not a dense transformer. The measured ~37.2 KB/token in §5 was taken from real GB10 runs of this checkpoint and is unaffected; only the architectural description was wrong. One practical consequence: with prefix caching on, vLLM aligns the attention block size to the mamba page size (1568 tokens on this boot), so block-size tuning is not a free parameter here.

The 21 GiB of weights this model does *not* spend is what makes a million-token request fit alongside a usable KV pool. That is the whole argument for it. If you do not need more than 131,072 tokens, `dgx-spark-vllm.md` describes a configuration that is actually verified here, and you should use that one.

**Do not read the smaller KV-per-token column as a reason to go back.** Qwen3-Coder-Next's hybrid attention genuinely costs less KV per token, and its weights-plus-1M-KV total (~68 GiB) also fits this hardware on paper. §5 of `dgx-spark-vllm.md` stops at 131,072 because that is where testing stopped, not where the hardware stopped. That remains an open experiment, not a closed door.

### 1.1 Considered and excluded: Qwen3.8-Flash-Next (2026-08-26)

Evaluated 2026-08-28 and **rejected for this hardware**. Recorded here so the question does not get re-litigated every time the name comes up.

**First, the naming trap.** `Qwen3.8-Flash-Next` shares a version number with `Qwen3.8-27B` and almost nothing else. It is `model_type: qwen4_exp` — a preview of the Qwen4 architecture — where 3.8-27B is `qwen35`. Different lineage, different loader, different support matrix. "The newer 3.8" is the wrong mental model.

**What it is:** 125B multimodal MoE, 6B active per token, plus a *separate* 51.2B N-gram embedding table (176B total). 48 layers — 36 Gated DeltaNet linear-attention plus 12 Qwen Sparse Attention. 512 experts, top-10 routing. 262,144 native, 1,000,000 via YaRN. vLLM has day-0 support (0.29.0+).

The attractive part is real: 12 full-attention layers × 2 KV heads × 256 head_dim gives **~24 KB/token**, the same as Qwen3-Coder-Next and about 35% cheaper than 3.8-27B. And 6B active parameters ought to decode fast.

**Why it does not work here — four independent blockers, any one of which is sufficient:**

| **#** | **Blocker** | **Detail** |
|---|---|---|
| 1 | **It does not fit.** | vLLM's minimum *validated* configuration is TP2 on GB300 at FP8 — **172.78 GiB**. The day-0 NVFP4 checkpoint (`RadixArk/Qwen3.8-Flash-Next-NVFP4`) is **135 GB ≈ 125.7 GiB**, already past this Spark's ~121.6 GiB *before any KV cache*. It is only "NVFP4" in the routed experts; attention, QSA, GDN, hyperconnection streams, shared experts, routers, embeddings, LM head, vision tower and all 31 MTP tensors stay BF16. |
| 2 | **The offload that rescues it elsewhere does nothing here.** | `VLLM_PLE_CPU_OFFLOAD=1` moves the 51 GB N-gram table to *host* RAM, which on an H200 buys back 23.46 GiB of HBM and +78.5% KV capacity. **GB10 has unified memory: host RAM and GPU memory are the same 128 GB pool.** The bytes do not go anywhere. Every published sizing number for this model assumes a machine where that distinction exists. |
| 3 | **The GGUF path costs the architecture.** | Unsloth's GGUFs fit at `UD-Q2_K_XL` (78.9 GB) or `UD-IQ1_S` (72.5 GB); `UD-Q4_K_XL` is 111.3 GB, inside `dgx-spark.md` §7`'s ">100 GB → needs multi-node" band. But llama.cpp serves no Anthropic Messages surface, so agent clients go back through a LiteLLM bridge and §7 #1 becomes structural rather than a version bug. Support also still rides on an unmerged PR (ggml-org/llama.cpp#27742); stock master dies on unknown-architecture. |
| 4 | **It is not actually faster.** | Measured **22–27 tok/s on 128 GB unified-memory NVIDIA hardware**, f16 KV, no speculative decoding — statistically the same as 3.8-27B's 21–26 tok/s *with* MTP. The 4B MTP head has no spec-decode support in any available GGUF, and **quantized KV caches crash this architecture**, so the fp8 KV halving in §3.2 is unavailable. You would pay 3–5× the weight footprint for the same tokens per second and lose the KV trick that pays for the long window. |

**Revisit when** an NVFP4-or-smaller checkpoint lands under ~70 GiB with a vLLM build that targets sm_121a, *and* quantized KV stops crashing. The KV economics would then be genuinely better than 3.8-27B's, and the 6B active-parameter decode is worth re-measuring on this hardware rather than inferred from someone else's. Until then the constraint is not quality — it is that this model was designed for a machine with a separate host memory pool, and this one is not that machine.

## 2. Hardware assumptions

Identical to `dgx-spark-vllm.md` §2`:

- DGX Spark (GB10 Grace-Blackwell, sm_121a), 128 GB unified memory — about 121.6 GiB usable.
- ARM64 Linux.
- NVFP4 quantization requires Blackwell sm_120+; Spark is sm_121a, supported.
- **A vLLM >= 0.26 runtime that is NOT the Coder-Next venv.** Measured on this box 2026-09-07: that venv is `vllm 0.18.1rc1.dev245` / `transformers 4.57.6`, below both floors. See §2.1.

### 2.1 Do not upgrade the Coder-Next venv

The start script's preflight refused on this hardware:

```
LOW transformers 4.57.6 (need >= 5.8.0)
LOW vllm 0.18.1rc1.dev245 (need >= 0.26.0)
```

Both floors are real. transformers 4.x cannot load the Qwen3.8 config at all, and every published GB10 run of this model used vLLM 0.26-0.27.

**The wrong fix is upgrading that venv in place.** It holds the one verified configuration on this machine — `dgx-spark-vllm.md` says every flag in its §3 is load-bearing — and the upgrade crosses a transformers major version and eight vLLM minors on an ARM64 source build, with no way back except rebuilding. The fallback you are constructing would be built by destroying the fallback you have.

**The right fix is a container.** vLLM's DGX Spark guidance is explicit that "Spark does not require a bespoke serving interface: it runs through vLLM's standard OpenAI-compatible server", via the published image. No second source build, no torch pin to guess, and the 0.18 venv is never touched:

```
8000  ->  Qwen3-Coder-Next   host venv, vLLM 0.18.1rc1   (UNTOUCHED)
8001  ->  Qwen3.8-27B        container, vLLM >= 0.26
8787  ->  LiteLLM            Anthropic bridge for Claude Code
```

Use `start-qwen38-27b-docker.sh`. It applies the same version floors *inside the image* before serving, because a nightly tag is a moving target, and prints the resolved digest so you can pin it once the gate passes. `start-qwen38-27b.sh` remains for a second, separate venv if you ever want one — never for an in-place upgrade.

Remaining software requirements:

- `transformers >= 5.8.0`**.** Below that the checkpoint's config and vision processor do not load. The start script preflights this before it touches the GPU, because failing here beats failing twelve minutes into a flashinfer JIT.
- vLLM `0.26.x` or newer is what the third-party GB10 reports used. Older builds will not have the `--speculative-config` MTP path this doc relies on.

## 3. Validation configuration (start here)

**This is the validation config — deliberately conservative, deliberately boring.** It is close to the published GB10 baseline plus the official recipe's parser and KV choices. It runs at the **native 262,144 window with no YaRN**, on **port 8001** so the existing Qwen3-Coder-Next server on 8000 stays up, and with **MTP off**.

A runnable wrapper lives at `scripts/dgx-spark/vllm/start-qwen38-27b.sh` (`start-qwen38-27b.sh`) and takes the same env-var override contract as `start-qwen3-coder-next.sh`.

```
# preflight — see §2
pip install -U 'transformers>=5.8.0'

source ~/dgx-spark-vllm/vllm_env/bin/activate
export VLLM_USE_FLASHINFER_MOE_FP4=0
export MAX_JOBS=2 NINJA_JOBS=2

python -m vllm.entrypoints.openai.api_server \
  --model unsloth/Qwen3.8-27B-NVFP4 \
  --served-model-name qwen38-27b unsloth/Qwen3.8-27B-NVFP4 \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --max-model-len 262144 \
  --max-num-seqs 4 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.45 \
  --kv-cache-dtype fp8 \
  --enable-chunked-prefill \
  --enable-prefix-caching \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --host 0.0.0.0 --port 8001
```

**MTP is added second, not first**, once §6 passes:

```
--speculative-config '{"method":"mtp","num_speculative_tokens":3}'
```

That ordering is not caution for its own sake. It separates *"does this model behave as a coding agent?"* from *"does speculative decoding make it faster?"* — two questions whose failure modes look nothing alike and whose evidence gets tangled if you enable both at once. MTP roughly doubles single-stream decode on GB10 into the mid-20s tok/s, with `n=3`–`n=5` the useful range; that is worth having, and worth having *after* the tool loop is proven.

### 3.1 Carries over unchanged from dgx-spark-vllm.md §9.2

Each of these is a property of the toolchain, the host or the transport rather than of the checkpoint, so it transfers without re-derivation:

| **Flag / setting** | **Why it is model-independent** |
|---|---|
| `MAX_JOBS=2 NINJA_JOBS=2` | flashinfer JIT compile concurrency. Weights here are *half* the Coder-Next footprint, so 2 has more headroom than it did there — but leave it at 2 until a first boot proves otherwise. |
| `VLLM_USE_FLASHINFER_MOE_FP4=0` | Disables the experimental FP4 MoE path. Harmless on a dense model; keep it for parity until something needs it off. |
| `pkill` / `drop_caches` preamble | Host-state hygiene before vLLM's memory probe. |
| `--trust-remote-code` | Required whenever a checkpoint ships custom `modeling_*.py`. |
| `--enable-prefix-caching` | The single biggest RLM-loop win on this hardware — see `dgx-spark.md` §4b`. Nothing about it is model-specific. |

### 3.2 Deltas from dgx-spark-vllm.md §3, each with its reason

| **Flag** | **Delta** | **Reason** |
|---|---|---|
| `--served-model-name qwen38-27b unsloth/…` | Was a single HF-style id | **The flag takes a list.** The first entry is the canonical id returned by `/v1/models`; the rest are aliases. The canonical one must be **slash-free**, because Claude Code cannot address a model id containing `/`. Our current `RedHatAI/Qwen3-Coder-Next-NVFP4` served name would fail for that client. Keeping the upstream id as an alias means existing RLM Studio and Pi configs keep resolving. |
| `--enforce-eager` | **Removed** | Spark's older stack needed it for CUDA-graph capture stability. vLLM 0.26 on GB10 is reported to capture graphs cleanly at ~0.15 GiB, and graphs are worth real decode throughput. The wrapper makes it opt-in via `VLLM_ENFORCE_EAGER=1` — flip it at the first sign of a capture-time hang. |
| `--reasoning-parser qwen3` | **Added** | This inverts Blocker #2's guidance. Qwen3-Coder-Next emits no separate thinking output, so §3 there passes no reasoning parser. Qwen3.8 has a thinking mode with materially different token budgets per reasoning level, so the parser belongs here. If §6 Step 2 fails with tool-call XML landing in `reasoning`, change the **tool** parser before you remove this one. |
| `--kv-cache-dtype fp8` | **Added** | Halves KV bytes per token. This is what turns "a 1M request fits" into "a 1M request fits alongside two other clients." The official vLLM recipe for the single-GPU NVFP4 variant uses it. |
| `--speculative-config` MTP | **Added, but not in the first boot** | The draft head is 15 tensors inside the checkpoint; there is no second model to download. `n=3`–`n=5` is the measured GB10 range, roughly doubling single-stream decode. Full CUDA graphs are unavailable with spec decode — vLLM falls back to piecewise. Enable it only after §6 passes without it. |
| `--max-num-seqs 4` | Was `1` | Four clients may share this server (RLM Studio, Pi, Codex, Claude Code). One sequence slot serialises them behind each other. See §5 on why the KV pool, not this flag, is the real concurrency limit. |
| `--max-num-batched-tokens 8192` | unchanged | The published GB10 baseline value. Raise only with a KV-pool number in hand. |
| `--enable-chunked-prefill` | **Added** | Keeps a very long prefill from monopolising the batch. At the context lengths this doc exists for, prefill is the dominant cost. |
| `--hf-overrides` YaRN | **Not in the default config** | Native window is 262,144; factor 4.0 extends it to ~1.05M, and vLLM officially documents the extension. It is off by default because 262K plus prefix caching plus reliable tool calling is a better coding backend than 1M plus longer cold prefills — see §5.4. The wrapper derives the factor and refuses to apply rope scaling at or below the native window. |
| `--gpu-memory-utilization 0.45` | Was `0.72` | The value the published GB10 run actually used. At 262K with fp8 KV it still leaves ~29 GiB of KV — about 6.5× a full-window request — and it leaves room for the Coder-Next server to stay up. Raise it only when you have a reason and a KV-cache line to check it against. |

### 3.3 The one flag most likely to be wrong

`--tool-call-parser`. `qwen3_coder` is what our verified Coder-Next config uses and what one GB10 operator used for this model; the NVIDIA developer-forum thread used `qwen3_xml` for the same checkpoint. They extract different emission shapes. **Boot with** `qwen3_coder`**, run §6 Step 2, and switch if** `tool_calls[]` **comes back empty with the XML sitting in** `content`**.** Enumerate what your build actually offers with:

```
python -m vllm.entrypoints.openai.api_server --help | grep -A20 'tool-call-parser'
```

## 4. First-boot expectations

Same shape as `dgx-spark-vllm.md` §4`, with one difference in degree.

**Correction (2026-09-07).** This section previously budgeted **10–15 minutes** for first-boot flashinfer JIT. Measured on `eugr/spark-vllm:latest`: **250.4 s total** for engine init, of which torch.compile was 30.4 s and the flashinfer autotuner 118 s. That image ships pre-built sm_121a kernels rather than compiling them on the box, so the long JIT wait applies to a *source* build, not to this container.

Measured first boot, container path, `262144 / 0.45 / fp8`:

| **Stage** | **Time** |
|---|---|
| Model loading (21.34 GiB) | 152.3 s |
| torch.compile | 30.4 s |
| flashinfer autotune (21 profiles, 42 configs saved) | ~118 s |
| CUDA graph capture (4 PIECEWISE + 3 FULL) | 2 s |
| **Engine init total** | **250.4 s** |

The autotune results land at `/root/.cache/vllm/flashinfer_autotune_cache/<ver>/121a/` **inside the container**. `docker restart` keeps them; recreating the container does not, unless `~/.cache/vllm` is bind-mounted — which `start-qwen38-27b-docker.sh` now does via `VLLM_CACHE_HOME`. Without that mount every relaunch re-pays the ~2 minutes.

**Bumping** `--max-model-len` **invalidates the relevant tile-size cache.** Going from 262,144 to 1,010,000 re-triggers compilation for the new sequence-length tiles; budget 5–15 minutes again at that first boot. This is the practical reason §9 tells you to boot at 262,144 first — every debugging cycle at the extended window costs you that recompile.

If a boot is OOM-killed mid-JIT, the partial cache under `~/.cache/flashinfer/<ver>/121a/cached_ops/` survives and the next attempt resumes. Do not wipe it to "start fresh."

## 5. Memory budget (DERIVED — see the banner)

Weights, activations, CUDA graphs and KV cache all draw from one pool that `--gpu-memory-utilization` carves out of ~121.6 GiB. **The number that admits or rejects a request is not** `--max-model-len` — it is the *GPU KV cache size* line vLLM prints at boot. Read it and record it; until you do, this whole section is someone else's arithmetic.

### 5.1 Fixed cost — MEASURED on spark-c2e5, 2026-09-07

| **Component** | **Size** |
|---|---|
| Weights (NVFP4), reported by the loader | 21.34 GiB |
| Weights + non-torch, as vLLM budgets it | 26.46 GiB |
| Peak activation (at `max-num-batched-tokens 8192`) | 3.82 GiB |
| CUDA graphs (actual; vLLM *estimated* 1.93) | 0.04 GiB |
| **Fixed total** | **30.32 GiB** |

**Correction (2026-09-07).** This table previously read ~25.3 GiB, built from a published weight size plus an activation guess. The measured figure is 5 GiB higher, almost all of it in the gap between the 21.34 GiB the loader reports and the 26.46 GiB vLLM actually budgets for weights + non-torch. Budget from 30.3, not from the weight size on the model card. The separate MTP draft-head row is gone: with `VLLM_SPEC_TOKENS=0` it is not loaded, and when it is, re-measure rather than adding a remembered constant.

Activation scales with `--max-num-batched-tokens`, **not** with `--max-model-len`, so the 3.82 GiB does not move when you extend the context window.

### 5.2 KV pool — MEASURED, and the fp8 assumption was wrong

Boot log, `--kv-cache-dtype fp8`, `--gpu-memory-utilization 0.45`:

```
GPU KV cache size: 769,859 tokens
Maximum concurrency for 262,144 tokens per request: 2.94x
Available KV cache memory: 24.49 GiB
```

24.49 GiB / 769,859 tokens = **34,157 bytes/token, with fp8 already on.**

**Correction (2026-09-07).** The row below previously claimed fp8 halved KV to ~18,600 B/token. It does not — measured, fp8 costs 34,157 B/token against a ~37,200 B/token `auto` baseline, a **saving of about 8%, not 50%**. The reason is architectural and was missed because the architecture was described wrongly (see §1): this is a Gated DeltaNet hybrid. Most layers are linear-attention and carry a fixed-size recurrent state that is held in bf16 regardless of `--kv-cache-dtype`; only the minority full-attention layers are quantised. The `align` mamba cache mode and the 1568-token attention block size vLLM pins to the mamba page size add further per-block overhead. **Do not budget any Qwen3.5- family hybrid as though fp8 halves its cache.**

| **KV dtype** | **Bytes/token** | **Basis** |
|---|---|---|
| `auto` | ~37,200 | Forum + GX10 operator, dense-attention models |
| `fp8` | **34,157** | **Measured here, this model, 2026-09-07** |

vLLM computed the ceiling for this box in the same log: `--kv-cache-memory=90779070464` (84.54 GiB) "to fully utilize gpu memory" — about **2.66M KV tokens**.

### 5.3 Cost of one long request — recomputed at 34,157 B/token

| `max-model-len` | **KV needed** | **+ fixed 30.32** | **Implied** `--gpu-memory-utilization` |
|---|---|---|---|
| 131,072 | 4.2 GiB | 34.5 GiB | 0.29 |
| 262,144 | 8.3 GiB | 38.6 GiB | 0.32 — **current config has 2.94x headroom on top** |
| 1,010,000 | 32.1 GiB | 62.4 GiB | **0.52** |
| 1,010,000 at 2x concurrency | 64.3 GiB | 94.6 GiB | 0.78 — single-tenant only |

The 0.52 figure independently reproduces the **0.53 floor** reported for 1M on this model, which is the strongest cross-check in this document: an estimate derived from our own boot log landing within 2% of a number measured by someone else on different hardware of the same family.

**At the current 0.45 the box holds 769,859 KV tokens — so 1M in a single request does not fit today.** Extending to 1M is a utilization change (`0.55` for one sequence with margin), not just a `--max-model-len` change plus YaRN.

### 5.3 Cost of one long request

| `max-model-len` | **KV,** `auto` | **KV,** `fp8` | **Notes** |
|---|---|---|---|
| 131,072 | 4.6 GiB | 2.3 GiB | The claude-code-class envelope floor from `dgx-spark-vllm.md` §5. |
| 262,144 | 9.3 GiB | 4.7 GiB | Native window. **Start here.** |
| 1,010,000 | 34.9 GiB | 17.5 GiB | Requires YaRN. Reported floor is `--gpu-memory-utilization 0.53`, recommended `0.60`; we use `0.90` for concurrency, not for fit. |

### 5.4 Fits is not the same as usable

Measured prefill on GB10 runs **1,734 tok/s at a 4.6K prompt and 853 tok/s at 47.8K**, degrading with length. A cold 1M-token prefill is a **20-minute-plus** wait before the first output token. Decode with MTP lands at **21–26 tok/s**.

The operational consequence, and the reason this matters more to RLM Studio than to any other client:

**A million-token window on this hardware is headroom that accumulates across a prefix-cached session, not a window you fill in one shot.**

This is the same conclusion `dgx-spark.md` §4b` reached from the other direction. RLM mode — which navigates content with `peek()`, `grep()` and `chunk()` instead of prefilling it — remains the right tool at these sizes. A bigger window does not retire RLM mode; it raises what Direct mode can reach *when the prefix is already cached*. See §8.2 for the experiment that would settle where the crossover actually sits on this hardware.

## 6. Verification gate

Extends the three-step smoke test in `dgx-spark-vllm.md` §6` to seven, across the three transports this server has to serve. Scripted at `scripts/dgx-spark/vllm/verify-qwen38-spark.sh` (`verify-qwen38-spark.sh`).

```
bash scripts/dgx-spark/vllm/verify-qwen38-spark.sh <dgx-spark-ip> 8001 qwen38-27b
```

| **Gate** | **Transport** | **Checks** | **FAIL means** |
|---|---|---|---|
| 1 | `/v1/models` | id served, canonical id slash-free, `max_model_len` ≥ 131072 | Wrong `--served-model-name`, or an undersized window (§7 #3) |
| 2 | `/v1/chat/completions` | structured `tool_calls[]` on a tools payload | Parser pairing wrong (§3.3, §7 #4) |
| 3 | `/v1/chat/completions` | two-turn continuation | Multi-turn route problem |
| 4 | `/v1/responses` | endpoint answers | Codex cannot use this server at all (§8.2a) |
| 5 | `/v1/responses` | a `function_call` item in `.output[]` | Codex sees prose where a tool invocation belongs — the Codex equivalent of gate 2 |
| 6 | `/v1/messages` | **trailing system turn** → `tool_use` block | vllm#48874 (§7 #1). Route Claude Code via LiteLLM |
| 7 | `/v1/messages` | structured content blocks accepted | vllm#44000 has regressed; the build predates PR #44283 |

**#48874 is verified against affected released builds. Do not infer susceptibility from the vLLM version alone — gate 6 is authoritative for the installed build.** Current vLLM `main` already carries related inline-system normalization (`_detect_merge_inline_system()` / `merge_inline_system`), which for templates requiring system-first ordering can fold inline system messages into the leading system block. So a build newer than the reported 0.24.0/0.25.1 may already be healthy, and PR #52978 still being open does not by itself mean your server is broken. Equally, a build being new does not mean it is safe: the normalization is conditional on template detection. Run the gate.

**Gate 6 is the reason this file was revised, and the only gate whose failure returns HTTP 200.** Gates 1–5 and 7 all pass against a server that is silently broken for Claude Code — I verified that against stub servers reproducing the #48874 response shape. A green smoke test and a broken agent are indistinguishable without gate 6.

Gate 6 also gives you a clean attribution rule: it runs the *same task* as gate 2, differing only by the trailing system turn. **Gate 2 passing while gate 6 fails means the model is fine and the transport is not.**

## 7. Troubleshooting matrix

Symptom strings are verbatim — operators grep for exact error text.

| **#** | **Symptom (verbatim)** | **Cause** | **Fix** | **Detection** |  |  |
|---|---|---|---|---|---|---|
| 1 | **HTTP 200.** The agent completes one turn and stops. `stop_reason: end_turn`, no `tool_use` block, and the tool call sitting in a text block as pseudo-XML. Roughly 90% of long agent runs die this way | **vllm-project/vllm#48874.** Claude Code ≥ 2.1.207 appends agent-registry context as a `system`-role message *inside* the messages array, after the user turn. Affected builds render it positionally, so the prompt ends on a system block and the model answers *that* instead of the coding task. Reported against vLLM 0.24.0/0.25.1; 0.11.0 rejected it outright instead | Route Claude Code through the LiteLLM bridge (§8.3) until it is fixed on your build. Upstream fix is PR #52978 (hoists trailing system turns into the leading system block), open at the time of writing. Current `main` also carries `_detect_merge_inline_system()` / `merge_inline_system`, so some newer builds may already be healthy — **do not infer from the version, run gate 6** **RLM Studio, Pi and Codex are unaffected** — none of them use `/v1/messages` | §6 Gate 6. This is the only gate whose failure returns HTTP 200 |  |  |
| 1b | `Input should be 'user' or 'assistant'` — HTTP 400 from `/v1/messages` before any inference | vllm#44000, Claude Code ≥ 2.1.154 sending `ctx`/`msg`/`system` roles. **Closed by PR #44283** — this is a regression guard, not a live suspicion | Upgrade vLLM. Seeing this means the build predates #44283 | §6 Gate 7 |  |  |
| 2 | `ninja: build stopped: subcommand failed`, `Engine core initialization failed`, exit 137 on an nvcc/cicc/cc1plus subprocess during first boot | flashinfer JIT concurrency competing with resident weights for the unified pool | `MAX_JOBS=2 NINJA_JOBS=2`; drop to 1 if 2 still OOMs. Partial cache is preserved — resume, do not wipe | `watch -n 2 'pgrep -c -f "nvcc\ | cicc\ | cc1plus"'` during boot — should stay ≤ 2 |
| 3 | HTTP 400 in <1s with `This model's maximum context length is N tokens. However, you requested M output tokens…` | vLLM enforces `prompt_tokens + max_tokens <= max_model_len` strictly. Agent clients ship a ~30–40K envelope on every call and default to a large `max_tokens` | Raise `--max-model-len`, or bound the client (`CLAUDE_CODE_MAX_OUTPUT_TOKENS`). RLM Studio's own budgets do not protect you here — this is enforced server-side | §6 Step 1 |  |  |
| 4 | `tool_calls: []` with the tool-call XML buried in `content` or `reasoning` | Parser pairing wrong for this emission shape | Try `qwen3_xml` in place of `qwen3_coder`. If the XML is specifically in `reasoning`, change the **tool** parser first — unlike Coder-Next, this model does have a thinking mode and wants `--reasoning-parser qwen3` (§3.2) | §6 Step 2 |  |  |
| 5 | The window appears to work, requests succeed, but answers behave as though the model saw almost nothing | Early `unsloth/Qwen3.8-27B-NVFP4` releases shipped `"truncation": {"max_length": 2048}` in the tokenizer config, silently cutting every prompt to 2K. Corrected upstream | Check `tokenizer_config.json` **before** touching a vLLM flag. Re-pull the checkpoint | `grep -n truncation ~/dgx-spark-vllm/models/Qwen3.8-27B-NVFP4/tokenizer_config.json` |  |  |
| 6 | Prefix cache hit rate near zero on agent traffic; every turn re-prefills | Claude Code injects a per-request hash into the system prompt, busting the shared prefix. Handled automatically in vLLM after 0.17.1 | Upgrade vLLM. On this hardware this is not a nicety — it is the difference between a working loop and a 20-minute one | `--kv-cache-metrics` on the serve command |  |  |

Blocker #4 from `dgx-spark-vllm.md` §7 — LiteLLM auto-routing `openai/*` through `/v1/responses` — **cannot fire on the RLM Studio path**, because the `vllm` backend prepends `hosted_vllm/` in all three prefix tables. It remains live for anything reaching this server through a generic `openai/` LiteLLM prefix, so the bridge config in §8.3 pins `hosted_vllm/` explicitly.

Note the asymmetry that makes this confusing: Blocker #4 is about **LiteLLM's translation into** the Responses API being rejected by vLLM. Codex talking to `/v1/responses` **directly** is a different path and an officially documented integration — see §8.2. "Responses is broken" is the wrong lesson; "LiteLLM's Responses translation is broken, so pin `hosted_vllm/`" is the right one.

## 8. Using this server from RLM Studio

### 8.1 Provider entry

Field shape per `hosts/README.md` §3 (`README.md`):

| **Field** | **Value** |
|---|---|
| Backend | `vllm` |
| Base URL | `http://<dgx-spark-ip>:8001/v1` |
| Model | `qwen38-27b` |

No API key. Secure it per `hosts/README.md` §5 (`README.md`) — VPN, SSH tunnel, or trusted-LAN — rather than `vllm --api-key`.

From the Python API:

```
from rlmstudio import interact

r = interact(
    content, query, mode="rlm",
    provider="vllm", model="qwen38-27b",
    api_base="http://<dgx-spark-ip>:8001/v1",
)
```

`provider="vllm"` prepends `hosted_vllm/`, which pins to `/v1/chat/completions`. Nothing in the library needs changing for this model. The one stale string is the `model_input_hint` on the `vllm` entry in `src/rlmstudio/ui/data/providers_catalog.py`, which still suggests `Qwen/Qwen2.5-7B-Instruct`.

### 8.2 The experiment worth running once the server is up

RLM Studio's whole reason to exist is deciding whether RLM beats Direct on *your* data. A 1M window changes the inputs to that decision on this hardware, and the Compare matrix is the instrument for measuring it:

Run **Direct vs RLM at 200K and 500K** against this server, on a document you actually care about, and record cost, latency and TTFT for each.

Auto mode currently switches at 8K tokens. That threshold was chosen for a world where Direct meant "pay for a big prefill against a cloud API." On a Spark, Direct at 500K means a multi-minute prefill you cannot pipeline, and the crossover is somewhere very different. **Do not adjust the threshold on intuition** — the matrix produces the number, and the number belongs in this section when you have it.

### 8.2a Codex — direct to /v1/responses

vLLM implements the OpenAI Responses API that current Codex speaks, and the integration is officially documented. There is no bridge on this path.

```
# ~/.codex/config.toml
model = "qwen38-27b"
model_provider = "dgx-vllm"

[model_providers.dgx-vllm]
name = "DGX Spark vLLM"
base_url = "http://<dgx-spark-ip>:8001/v1"
env_key = "VLLM_API_KEY"
wire_api = "responses"
```

`export VLLM_API_KEY=dummy` — vLLM ignores it, Codex refuses to start without one. Gate 5 in §6 is the check that matters: the endpoint answering is necessary but not sufficient, since Codex is useless if the model returns prose where a `function_call` item belongs.

### 8.3 This server also fronts non-RLM-Studio clients

The same vLLM process exposes an Anthropic Messages surface at `/v1/messages` alongside the OpenAI one. Agent clients (Claude Code, Pi) use that path; their configuration lives in the `code-copilot-team` repo, not here. Two consequences for this doc:

- `--max-num-seqs` and the KV pool in §5 are shared with those clients. Budget accordingly — one GPU, one queue.
- §7 #1 and #3 are failures **those** clients hit, not RLM Studio. They are documented here because they are properties of this server, and an operator debugging this server needs them.

## 9. Path to "verified"

In order. Each step removes a variable the next one would otherwise be confounded by.

**Do not touch the running Qwen3-Coder-Next server first**, and specifically do not upgrade its venv (§2.1). Bring Qwen3.8 up beside it in a container:

```
8000  ->  Qwen3-Coder-Next-NVFP4   (existing, verified, untouched)
8001  ->  Qwen3.8-27B-NVFP4        (new)
8787  ->  LiteLLM                  (Anthropic bridge for Claude Code)
```

**Two servers, one memory pool.** `--gpu-memory-utilization` is a per-instance fraction of *total* memory — vLLM's own docs give two instances at 0.5 each as the canonical example. Summing the fractions therefore tests **budget arithmetic, not fit.** What the arithmetic rules out: Coder-Next at its verified `0.72` plus this at `0.45` is 142.3 GiB on a 121.6 GiB box. That is not a boot failure to debug; it is an impossibility. What the arithmetic does *not* establish: that `0.45 + 0.45` works. It shows the aggregate executor budget is **arithmetically viable (0.90)**; actual co-tenancy must still pass the boot and memory gate on the Spark. On unified memory the same pool carries the OS, page cache, container runtime and every other process, and allocations do not all behave like reserved slices — the published GB10 run at `0.45` reported 28.11 GiB fixed + 27.56 GiB KV = **55.67 GiB against a 54.73 GiB budget**, about 0.94 GiB outside the model, on a single instance. So `start-qwen38-27b.sh` §B is an **aggregate-utilization guard**, not a memory-fit check: it warns above 0.90 and refuses above 0.92, and says so in those words. The fit evidence comes from `record-spark-memory.sh`, run once both servers have loaded and served a request — `MemAvailable`, per-process RSS, and each server's KV-cache line. Until that table is filled in, this document does not say the two-model configuration fits. The estimate that Coder-Next at `0.45` retains ~8.7 GiB of KV ≈ **380K tokens** at 24 KB/token is **derived, not measured**. And KV capacity is not context length: a server with room for 380K KV tokens is still bounded by the `--max-model-len` it was started with and by the window that has actually been verified — 131,072 for Coder-Next. **Check the installed versions rather than assuming them.** The known-good Spark reference is vLLM `0.26.1rc1.dev244`; an independent GB10 NVFP4 benchmark used `0.27.1`. A generic "vLLM 0.6+" statement in an older local document is not evidence about your box: ```bash for v in <coder-next-venv> <qwen38-venv>; do ( source "$v/bin/activate" python - <<'PY' import vllm, transformers print(f" vllm={vllm.__version__} transformers={transformers.__version__}") PY ) done` `` This is also the argument for not mutating the working Coder-Next venv to get Qwen3.8 running.

- **Boot at 262,144, YaRN off, MTP off, port 8001, in a container.**

```
   VLLM_DRY_RUN=1 bash scripts/dgx-spark/vllm/start-qwen38-27b-docker.sh   # read it first
   bash scripts/dgx-spark/vllm/start-qwen38-27b-docker.sh
```

The image preflight enforces the same floors that stopped the venv run. Record the digest it prints.

- **Record the** ***GPU KV cache size*** **line** from the boot log. First number in this document that is ours.
- **Run the §6 gate** (7 checks across three transports).

```
   bash scripts/dgx-spark/vllm/verify-qwen38-spark.sh <ip> 8001 qwen38-27b
```

Gate 6 decides whether Claude Code gets the native Anthropic transport or the LiteLLM bridge. Gate 5 decides whether Codex is usable at all.

- **A real Codex repo task**: inspect files → edit → run a command or test → fix → finish. Not a prompt, a task.
- **A real Claude Code task through LiteLLM**, sustained for **15–30 tool turns**. A one-prompt smoke test cannot distinguish a working agent from #48874, which by construction fails on turn two.
- **Add MTP** (`--speculative-config '{"method":"mtp","num_speculative_tokens":3}'`) and re-run §6. Now you are measuring speculative decoding, not tool calling.
- **Run the anchor benchmark** three times in `code-copilot-team`:

```
   ./scripts/bench --task python/bowling --runs 3 sonnet vllm:qwen38-27b@http://<ip>:8001
```

Against Sonnet 3/3 @ 141 ± 39 s and Qwen3-Coder-Next 3/3 @ 473 ± 449 s.

**Record the ratio, not the throughput.** For an emergency coding backend the metric is roughly `tasks completed correctly / (wall-clock × turns consumed)`. A model that finishes in 8 turns at 22 tok/s beats one that stalls at turn 25 at 50 tok/s, and tokens per second cannot tell them apart. SGLang setups on this hardware currently report 30–40+ tok/s, and one SGLang/DFlash2 configuration reports 52–61 tok/s for code generation — but vLLM remains the better common denominator here because it serves Codex Responses, OpenAI-compatible and Anthropic clients from one process, and the throughput gap is not what decides whether a task completes.

- **Only then consider 1M.** `VLLM_MAX_MODEL_LEN=1010000 VLLM_YARN=1 VLLM_GPU_UTIL=0.72`. Expect a 5–15 minute flashinfer recompile at the new tile sizes, and re-run the whole gate. §5.4 is the reason this is step 8 and not step 1.
- **Promote** per `dgx-spark-vllm.md` §9.6`, then delete the banner at the top of this file.

Until step 9, the banner stays.

### 9.1 Optional: register this doc in the Learn panel

Like `dgx-spark-vllm.md`, this file is repo-only and is not served by the in-app docs route. To surface it, add to `_DOCS_ALLOWLIST` in `src/rlmstudio/server/routes/docs.py`:

```
"hosts-dgx-spark-qwen38": "hosts/dgx-spark-qwen38.md",
```

Consider leaving it unregistered while the banner is up — an in-app doc reads as guidance, and unverified guidance is worse than none.

## References

- vLLM tool-calling docs — <https://docs.vllm.ai/en/stable/features/tool_calling/>
- vLLM Claude Code integration — <https://docs.vllm.ai/en/stable/serving/integrations/claude_code/>
- vLLM recipe, Qwen3.8-27B — <https://recipes.vllm.ai/Qwen/Qwen3.8-27B>
- vllm-project/vllm#44000 (Anthropic role validation) — <https://github.com/vllm-project/vllm/issues/44000>
- NVIDIA Developer Forums, Qwen3.8-27B-NVFP4 on a single DGX Spark, 1M context + MTP measurements — <https://forums.developer.nvidia.com/t/qwen3-8-27b-nvfp4-on-a-single-dgx-spark-up-to-1m-context-vllm-mtp-measurements/380244>
- ASUS Ascent GX10 / GB10 deployment notes and KV measurements — <https://github.com/gitcommit90/qwen38-27b-dgx-spark>

§1.1 sources (`Qwen3.8-Flash-Next`, considered and excluded):

- vLLM recipe, Qwen3.8-Flash-Next — <https://recipes.vllm.ai/Qwen/Qwen3.8-Flash-Next> (TP2/GB300 172.78 GiB minimum, `VLLM_PLE_CPU_OFFLOAD=1`, 1M YaRN config)
- LMSYS, day-0 SGLang support — <https://www.lmsys.org/blog/2026-08-26-qwen-flash-next> (GDN + QSA hybrid, PLE host-offload accounting on H200)
- `Qwen/Qwen3.8-Flash-Next` config — <https://huggingface.co/Qwen/Qwen3.8-Flash-Next> (`qwen4_exp`, 48 layers, `full_attention_interval` 4, 2 KV heads, head_dim 256)
- `RadixArk/Qwen3.8-Flash-Next-NVFP4` — <https://huggingface.co/RadixArk/Qwen3.8-Flash-Next-NVFP4> (135 GB; what stays BF16)
- Unsloth GGUF sizes and run guidance — <https://unsloth.ai/docs/models/qwen3.8-next>
- qwen4exp is not qwen3next — <https://www.hospedales.com/notes/qwen4exp-qwen3-8-flash-next-llama-cpp-master> (22–27 tok/s on 128 GB unified memory; quantized KV crashes; no GGUF spec-decode)
- llama.cpp support PR — <https://github.com/ggml-org/llama.cpp/pull/27742>
- Anchor benchmark (separate repo `code-copilot-team`): aider-polyglot `python/bowling`, n=3 each — Sonnet 3/3 pass @ 141 ± 39 s; Qwen3-Coder-Next-NVFP4 (vLLM) 3/3 pass @ 473 ± 449 s. **No Qwen3.8-27B row yet — see §9 step 6.**
