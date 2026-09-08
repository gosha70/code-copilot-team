# DGX Spark Setup & Cookbook

**Revision 2 — 2026-09-07.** Changes from revision 1 are listed in *What changed and why* at the end. The largest one: **vLLM no longer needs to be built from source on this hardware**, and the source build in revision 1 is what produced the `vllm 0.18.1rc1.dev245` install that now blocks Qwen3.8.

## Scope

Working setup and troubleshooting patterns for:

- standalone Ollama on NVIDIA DGX Spark
- Open WebUI on DGX Spark
- vLLM on DGX Spark — **container first**, source build as a last resort
- serving coding agents (Claude Code, Codex, Pi) and RLM Studio from one box
- running two models side by side without them fighting for memory
- practical model usage rules
- troubleshooting and important commands
- external references

Depth beyond this cookbook lives in `rlm-studio/docs/hosts/` — `dgx-spark.md`, `dgx-spark-vllm.md` (Qwen3-Coder-Next, verified), `dgx-spark-qwen38.md` (Qwen3.8-27B).

## Recommended target architecture

### Pick the server by the job

- **Ollama — port 11434** — quantized chat models, fastest to stand up. One-line install, no build, model pull by name.
- **vLLM — ports 8000 / 8001** — coding agents, tool calling, long context. The only one of these with structured `tool_calls[]`, `/v1/responses`, `/v1/messages`, prefix caching and MTP.
- **Open WebUI — port 8080** — browser chat UI. Points at either.
- **LiteLLM — port 8787** — Anthropic-to-OpenAI bridge, for Claude Code while the native Anthropic path is unproven.

Ollama 0.14+ ships an Anthropic-shaped shim and needs no proxy. vLLM serves its own `/v1/messages`, but see *Agent transports* — that path has a live failure mode.

### Current layout on this box

```
8000  ->  vLLM   Qwen3-Coder-Next-NVFP4   host venv, vLLM 0.18.1rc1   VERIFIED, DO NOT DISTURB
8001  ->  vLLM   Qwen3.8-27B-NVFP4        container, vLLM >= 0.26
8080  ->  Open WebUI
8787  ->  LiteLLM bridge
11434 ->  Ollama
```

## DGX Spark sanity checks

```
hostnamectl
cat /etc/os-release
uname -a
nvidia-smi
free -h
df -h
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL
ip addr
hostname -I          # see the warning below — pick the LAN address, not a docker bridge
```

### Pin down <dgx-spark-ip> before anything hardcodes it

`hostname -I` returns every address, docker bridges included:

```
192.168.1.23 172.18.0.1 172.17.0.1
    ^ LAN        ^ docker bridges — never use these
```

Two hazards specific to this machine:

- **The LAN address is on Wi-Fi and is a DHCP lease.** `enP7s7` (Ethernet) is `NO-CARRIER` — unplugged — so traffic runs over `wlP9s9` at `192.168.1.23`, with a lease measured in hours. When it renews to a different address, every hardcoded `<dgx-spark-ip>` breaks at once: the Codex `config.toml`, the LiteLLM `api_base`, `providers.toml`, the RLM Studio provider entry. Nothing warns you; the agents simply stop connecting. **Set a DHCP reservation on the router, or use the mDNS name** `spark-c2e5.local`**, before writing that address into config files.**
- **Plug in Ethernet before pulling weights.** A checkpoint is tens of GB, and Wi-Fi is also carrying every agent request.

### Record what you actually have installed

Revision 1 skipped this, and the cost was real: the vLLM venv turned out to be eight minor versions behind what current models need, and nothing in the cookbook would have told you. Run this in **every** venv, and write the output down.

```
for v in ~/dgx-spark-vllm/vllm_env ~/dgx-spark-vllm/qwen38_env; do
  [ -f "$v/bin/activate" ] || continue
  ( echo "== $v"; source "$v/bin/activate"
    python - <<'PY'
import importlib
for m in ("torch", "vllm", "transformers"):
    try: print(f"  {m:14s} {importlib.import_module(m).__version__}")
    except Exception as e: print(f"  {m:14s} MISSING ({e.__class__.__name__})")
PY
  )
done
docker ps --format '  {{.Names}}\t{{.Image}}\t{{.Ports}}'
```

## Standalone Ollama on DGX Spark

### Install

```
curl -fsSL https://ollama.com/install.sh | sh
```

### Host-owned model directory

```
sudo mkdir -p /var/lib/ollama/models
sudo chown -R ollama:ollama /var/lib/ollama
```

### Listen on the LAN

```
sudo systemctl edit ollama.service
```

Override:

```
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_MODELS=/var/lib/ollama/models"
```

```
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
sudo systemctl restart ollama
sudo systemctl status ollama --no-pager
sudo ss -lntp | grep 11434
```

### Pull models

```
ollama pull qwen3.6:35b-a3b     # current-generation MoE
ollama pull qwen3.5:27b         # current-generation dense
ollama pull llama3.2            # tiny — smoke tests only
ollama list
ollama ps
```

Sizing on Spark is governed by **weight footprint in GB**, not parameter count — quantization changes bytes per parameter by up to 4×. See *Memory bands*.

### Verify

```
curl http://127.0.0.1:11434/api/version
curl http://127.0.0.1:11434/api/tags

curl http://<dgx-spark-ip>:11434/api/version
curl http://<dgx-spark-ip>:11434/api/tags
```

## Open WebUI on DGX Spark

### Recommended: point at host Ollama

```
docker rm -f open-webui 2>/dev/null || true

docker run -d --name open-webui --restart unless-stopped \
  -p 8080:8080 \
  -e OLLAMA_BASE_URL=http://<dgx-spark-ip>:11434 \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main
```

### Against a vLLM server instead

```
docker run -d --name open-webui --restart unless-stopped \
  -p 8080:8080 \
  -e OPENAI_API_BASE_URL=http://<dgx-spark-ip>:8001/v1 \
  -e OPENAI_API_KEY=dummy \
  -v open-webui:/app/backend/data \
  ghcr.io/open-webui/open-webui:main
```

### Integrated mode: Open WebUI + embedded Ollama

```
docker rm -f open-webui 2>/dev/null || true

docker run -d --name open-webui --restart unless-stopped \
  --gpus=all -p 8080:8080 \
  -v open-webui:/app/backend/data \
  -v open-webui-ollama:/root/.ollama \
  ghcr.io/open-webui/open-webui:ollama

docker exec -it open-webui ollama pull qwen3.5:27b
docker exec -it open-webui ollama list
```

Integrated mode keeps its models in a Docker volume, invisible to host Ollama. Pick one mode and stay in it; running both is the usual cause of "the model I pulled has vanished".

## vLLM on DGX Spark — container (recommended)

vLLM's DGX Spark guidance is explicit: *"Spark does not require a bespoke serving interface: it runs through vLLM's standard OpenAI-compatible server."* No source build, no toolchain pins to guess, and an existing venv is never disturbed.

```
docker run -d --name qwen38-27b-8001 --restart unless-stopped \
  --gpus all --ipc=host \
  -p 8001:8001 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -e VLLM_USE_FLASHINFER_MOE_FP4=0 \
  vllm/vllm-openai:cu130-nightly \
    unsloth/Qwen3.8-27B-NVFP4 \
    --served-model-name qwen38-27b unsloth/Qwen3.8-27B-NVFP4 \
    --host 0.0.0.0 --port 8001 \
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
    --reasoning-parser qwen3
```

### Check the image before serving

A nightly tag is a compatibility track, not a reproducible reference. Check the floors, then pin the digest.

```
docker run --rm -i --entrypoint python3 vllm/vllm-openai:cu130-nightly - <<'PY'
from packaging.version import Version
for mod, floor in (("vllm", "0.26.0"), ("transformers", "5.8.0")):
    v = Version(__import__(mod).__version__.split("+")[0])
    print(f"{'OK ' if v >= Version(floor) else 'LOW'} {mod} {v} (need >= {floor})")
PY

docker image inspect --format '{{index .RepoDigests 0}}' vllm/vllm-openai:cu130-nightly
```

If `cu130-nightly` will not pull, Docker Hub also publishes `cu129-nightly` and `*-aarch64` variants. Community GB10 images exist (`ghcr.io/timothystewart6/vllm-gb10`) but the one checked was pinned to vLLM 0.24 — below the floor for Qwen3.8.

### Flags that are not obvious

- `--served-model-name qwen38-27b <hf-id>` — takes a **list**. The first entry is canonical and must be **slash-free**: Claude Code cannot address an id containing a slash. Keep the HF id as an alias so existing configs resolve.
- `--kv-cache-dtype fp8` — halves KV bytes per token. This is what makes room for several clients at once.
- `--gpu-memory-utilization 0.45` — the value the published GB10 run used. A fraction of **total** memory, not of free memory.
- `--tool-call-parser qwen3_coder` — official recipe. Some reports use `qwen3_xml`; if `tool_calls[]` comes back empty with XML in `content`, switch.
- `--reasoning-parser qwen3` — Qwen3.8 has a thinking mode. Qwen3-Coder-Next does **not**: pass no reasoning parser there.
- `--enable-prefix-caching` — on this hardware, the difference between a working agent loop and a 20-minute one.

### Read the KV cache line

```
docker logs qwen38-27b-8001 2>&1 | grep -iE 'kv.cache|GPU blocks|maximum concurrency'
```

**That number, not** `--max-model-len`**, is what admits a request.** Record it.

## Running two models side by side

`--gpu-memory-utilization` is a per-instance fraction of **total** memory. Summing the fractions tests budget arithmetic, not fit.

```
Coder-Next 0.72 + Qwen3.8 0.45 = 87.6 + 54.7 = 142.3 GiB on 121.6 GiB   IMPOSSIBLE
Coder-Next 0.45 + Qwen3.8 0.45 = 54.7 + 54.7 = 109.5 GiB                 viable, unproven
```

Viable is not the same as fits. On unified memory the same pool carries the OS, page cache, container runtime and every other process, and allocations do not all behave like reserved slices — the published GB10 run at 0.45 reported **55.67 GiB against a 54.73 GiB budget**, about 0.94 GiB outside the model, on one instance.

Keep the aggregate at or under **0.90**, and confirm with measurements after both servers have loaded and served a request:

```
grep -E 'MemTotal|MemAvailable' /proc/meminfo
ps -eo pid,rss,args | grep -E 'vllm' | grep -v grep
nvidia-smi --query-compute-apps=pid,used_memory,name --format=csv
```

`nvidia-smi` **cannot tell you GPU memory on this box.** Confirmed on `spark-c2e5`: the Memory-Usage column reads **Not Supported**, because GB10 has no discrete VRAM to account for — the GPU shares the one pool `/proc/meminfo` already measures, and `--query-gpu=memory.used` returns `[N/A]`. Use `MemAvailable` and per-process RSS. `nvidia-smi` is still worth running for the driver version and to see *which* processes hold the GPU.

**Never blanket-kill vLLM.** `pkill -f vllm` takes down the verified server on 8000 as well. Stop by port or container name:

```
docker rm -f qwen38-27b-8001
ss -lntp | grep 8001            # confirm what is actually holding a port first
```

## Agent transports

One vLLM process serves three protocol surfaces. Different clients speak different ones.

```
Codex        -> /v1/responses           direct
RLM Studio   -> /v1/chat/completions    direct
Pi           -> /v1/chat/completions    direct
Claude Code  -> /v1/messages            see the warning below
```

### Codex

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

```
export VLLM_API_KEY=dummy    # vLLM ignores it; Codex will not start without one
```

### Claude Code — bridge first

```
# ~/.code-copilot-team/litellm-qwen38.yaml
# model_list:
#   - model_name: qwen38-27b
#     litellm_params:
#       model: hosted_vllm/qwen38-27b     # NOT openai/ — see troubleshooting
#       api_base: http://<dgx-spark-ip>:8001/v1
#       api_key: dummy

litellm --config ~/.code-copilot-team/litellm-qwen38.yaml --port 8787

export ANTHROPIC_BASE_URL="http://127.0.0.1:8787"   # bare origin, NO /v1
export ANTHROPIC_AUTH_TOKEN="dummy"
export ANTHROPIC_MODEL="qwen38-27b"
export ANTHROPIC_DEFAULT_OPUS_MODEL="qwen38-27b"
export ANTHROPIC_DEFAULT_SONNET_MODEL="qwen38-27b"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="qwen38-27b"
export ANTHROPIC_SMALL_FAST_MODEL="qwen38-27b"
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=32000
```

All five model variables are required. Claude Code asks for `sonnet`/`haiku`/`opus` by name; an unpinned tier 404s against a server that has never heard of it, and it reads as a network failure rather than a config one.

### The test that decides whether you can drop the bridge

Claude Code ≥ 2.1.207 appends agent-registry context as a `system`-role message *inside* the messages array, after the user turn. On affected vLLM builds the prompt ends on a system block and the model answers *that* instead of the coding task — returning **HTTP 200**, `stop_reason: end_turn`, and the tool call as pseudo-XML in a text block. Roughly 90% of long agent runs die after one turn, and nothing errors.

```
curl -s http://<dgx-spark-ip>:8001/v1/messages \
  -H 'Content-Type: application/json' -H 'anthropic-version: 2023-06-01' \
  -H 'x-api-key: dummy' \
  -d '{"model":"qwen38-27b","max_tokens":400,
       "system":"You are a coding agent. Always use the provided tools.",
       "tools":[{"name":"edit_file","description":"Edit or create a file.",
         "input_schema":{"type":"object","properties":{"path":{"type":"string"},
         "content":{"type":"string"}},"required":["path","content"]}}],
       "messages":[
         {"role":"user","content":"Use the edit_file tool to create foo.py with a function bar() returning 42."},
         {"role":"system","content":"<agent-registry>No additional agents.</agent-registry>"}
       ]}' | jq '{stop_reason, types: [.content[].type]}'
```

- **PASS** — a `tool_use` block is present. The native path is safe on this build; drop the bridge.
- **FAIL** — `end_turn` with only `text`. Keep LiteLLM.

Do not infer the answer from the vLLM version. Recent builds carry inline-system normalization that may already fix it, and the upstream PR is still open — **run the test against the build you actually installed**, and re-run it after every Claude Code update.

## Base model vs chat model rule

Base models (`facebook/opt-125m`) use `/v1/completions`:

```
curl http://<dgx-spark-ip>:8001/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"facebook/opt-125m","prompt":"Say hello in one sentence.","max_tokens":16}'
```

Instruct/chat models use `/v1/chat/completions`:

```
curl http://<dgx-spark-ip>:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen38-27b","messages":[{"role":"user","content":"Say hello in one sentence."}],"max_tokens":32}'
```

Tool calling must produce a structured `tool_calls[]`, not XML inside `content`. A model that answers chat correctly but fails this is useless as a coding backend:

```
curl -s http://<dgx-spark-ip>:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen38-27b","temperature":0,"max_tokens":300,"tool_choice":"auto",
       "messages":[{"role":"user","content":"Use the tool to create foo.py with bar() returning 42."}],
       "tools":[{"type":"function","function":{"name":"edit_file","description":"Edit or create a file.",
         "parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},
         "required":["path","content"]}}}]}' \
  | jq '.choices[0].message | {content, tool_calls, reasoning}'
```

## Memory bands (weights in GB, not parameter count)

- **Up to 45 GB of weights** — comfortable alongside a large KV cache. Verified: Qwen3-Coder-Next-NVFP4 (~44 GB) at `--max-model-len 131072`, `--gpu-memory-utilization 0.72`.
- **45 to 90 GB** — possible with tuning and a reduced context. Re-derive per model.
- **90 to 100 GB** — untested. No configuration reported either way.
- **Over 100 GB** — needs multi-node. No single-Spark configuration fits the weights plus a usable KV cache.

MoE sparsity is the trap: `A10B` means 10 B *active* parameters, which reduces **compute** per token but **not** KV cache. KV is sized by total layers and KV heads.

Long context is memory-cheap and time-expensive. Measured prefill on GB10 runs ~1,734 tok/s at a 4.6K prompt and ~853 tok/s at 47.8K, degrading further with length — a cold 1M-token prefill is a 20-minute wait before the first output token. **Start at the native window.** Extend only when you have a reason.

## Troubleshooting cookbook

### Ollama

- `11434` already in use — `sudo ss -lntp | grep 11434`, `ps aux | grep ollama`, `docker ps`. A previous Docker-based Ollama or the integrated Open WebUI image are the usual culprits.
- Reachable locally but not from a laptop — the `OLLAMA_HOST=0.0.0.0:11434` override was not applied.
- Models written to `/var/lib/docker/volumes/...` — an old container is still running. Stop it and use `/var/lib/ollama/models`.

### vLLM — install and build

- `externally-managed-environment` — use a venv, or the container.
- `numa.h: No such file or directory` — `sudo apt-get install -y libnuma-dev numactl`.
- NVFP4 / `.e2m1x2` fails for `sm_121` — rebuild with `TORCH_CUDA_ARCH_LIST="12.1a"`, or use the container.
- Imports fail from some directories — run from the repo root.
- Multiprocessing failures — guard with `if __name__ == "__main__":`.
- `transformers 4.x` **cannot load a Qwen3.8 config.** Floors: `transformers >= 5.8.0`, `vllm >= 0.26.0`. Do not relax them; do not upgrade a working venv in place to satisfy them. Use a container or a second venv.

### vLLM — first boot

- Looks hung for 10–15 minutes on "Loading model weights", then `Compiling kernel ...` — that is flashinfer JIT for sm_121a. Expected. Do not kill it.
- `ninja: build stopped: subcommand failed`, exit 137 mid-JIT — the JIT runs ~8 concurrent `nvcc` processes competing with resident weights for the same unified pool. Set `MAX_JOBS=2 NINJA_JOBS=2`, drop to 1 if needed. The partial cache under `~/.cache/flashinfer/<ver>/121a/` survives — resume, do not wipe.
- Raising `--max-model-len` re-triggers compilation for the new tile sizes. Budget the wait again.

### vLLM — memory

- Startup reservation check fails — lower `--gpu-memory-utilization`. The default (~0.9) is too aggressive on Spark.
- Model loads, then no KV room — raise utilization *and* reduce `--max-model-len`. Compare the boot log's KV token budget against your worst-case `prompt + max_tokens`.
- Real OOM during weight load — the model is too large. See *Memory bands*.

### vLLM — requests

- HTTP 400 with `maximum context length is N tokens` — vLLM enforces `prompt_tokens + max_tokens <= max_model_len` strictly. Agent clients ship a ~30–40K envelope on every call. Raise the window or bound the client.
- `tool_calls: []` with XML in `content` — wrong `--tool-call-parser`; try `qwen3_xml`.
- `tool_calls: []` with XML in `reasoning` — the reasoning parser is intercepting. For Qwen3-Coder-Next, pass no `--reasoning-parser` at all.
- Multi-turn 400 with `212 validation errors` and `input_text` blocks — LiteLLM ≥ 1.50 auto-routing `openai/*` through `/v1/responses`. Use the `hosted_vllm/` prefix instead.
- Requests succeed, model behaves as if it saw nothing — check `tokenizer_config.json` for `"truncation": {"max_length": 2048}` before touching a vLLM flag. Some early quantized releases shipped it.
- Prefix cache hit rate near zero on Claude Code traffic — recent clients inject a per-request hash into the system prompt. Fixed in newer vLLM; on this hardware it matters a lot.

### Ports and processes

- Something unexpected on 8000/8001 — identify it before killing it. `ss -lntp | grep <port>`, `docker ps`, `tr '\0' ' ' < /proc/<pid>/cmdline`.
- A port is an address, not proof of ownership. Never `pkill -f vllm` on a box running two servers.

## Important commands

```
# host
hostnamectl; cat /etc/os-release; uname -a
nvidia-smi; nvcc --version
free -h; df -h; ip addr; hostname -I
ss -lntp

# ollama
systemctl status ollama --no-pager
systemctl cat ollama
journalctl -u ollama -n 100 --no-pager
ollama list; ollama ps

# docker
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}'
docker logs --tail=100 open-webui
docker logs --tail=200 qwen38-27b-8001
docker volume ls | grep open-webui

# vllm venv (legacy / Coder-Next)
cd ~/dgx-spark-vllm/vllm
source ~/dgx-spark-vllm/vllm_env/bin/activate
python -c "import torch, vllm, transformers; print(torch.__version__, vllm.__version__, transformers.__version__)"

# vllm server health
curl -s http://127.0.0.1:8000/v1/models | jq '.data[] | {id, max_model_len}'
curl -s http://<dgx-spark-ip>:8001/v1/models | jq '.data[] | {id, max_model_len}'
curl -s http://<dgx-spark-ip>:8001/v1/responses -H 'Content-Type: application/json' \
  -d '{"model":"qwen38-27b","input":"Reply with just: ok","max_output_tokens":16}' | jq '.output'
```

## What changed and why

- vLLM section is **container-first**; the source build moved to a last resort — vLLM's DGX Spark guidance states no bespoke build is needed. The revision-1 source build is what produced the `0.18.1rc1.dev245` install now blocking Qwen3.8.
- Added *Record what you actually have installed* — Revision 1 built from an unpinned `git clone`, so the installed version was unknowable after the fact. That is exactly how the block above happened.
- Added version floors (`vllm >= 0.26`, `transformers >= 5.8`) and an explicit "do not upgrade a working venv in place" — An in-place upgrade crosses a transformers major and eight vLLM minors on an ARM64 source build, with no way back. It would destroy the one verified configuration on the box to build its replacement.
- Added *Running two models side by side* — Revision 1 assumed a single server. `--gpu-memory-utilization` is a fraction of total memory, so 0.72 + 0.45 is 142 GiB on a 121.6 GiB box — an impossibility, not a boot failure to debug.
- Removed the blanket `pkill -f vllm` habit — It takes down the verified server along with the target.
- Added *Agent transports* with the trailing-system test — The `/v1/messages` failure returns HTTP 200. Every other check passes against a server that is silently broken for Claude Code.
- Added the tool-calling check to the base-vs-chat rule — `facebook/opt-125m` and a chat curl prove the server is up. Neither proves it can drive a coding agent.
- Added *Memory bands* and the prefill note — Sizing on Spark is governed by weight footprint in GB, and long context is cheap in memory but expensive in time.
- Expanded troubleshooting: flashinfer JIT OOM, KV budget, parser pairing, `hosted_vllm/` prefix, tokenizer truncation, prefix-cache hashes — All are Spark- or agent-specific and none were in revision 1.
- Updated the Ollama model list — `qwen2.5:14b` / `gpt-oss:20b` superseded by current-generation Qwen.
- Architecture section now selects a server by job — Revision 1 named host Ollama as the main server. For coding agents that is backwards — vLLM is, because Ollama exposes no structured tool-calling or Responses surface.

**Not changed:** the Ollama install, systemd override, host-owned model directory, and Open WebUI sections were correct and are kept nearly as written.

## External references

- NVIDIA Spark portal — https://build.nvidia.com/spark
- DGX Spark User Guide PDF — https://docs.nvidia.com/dgx/dgx-spark/dgx-spark.pdf
- DGX Spark first boot guide — https://docs.nvidia.com/dgx/dgx-spark/first-boot.html
- NVIDIA DGX Spark playbooks repo — https://github.com/NVIDIA/dgx-spark-playbooks
- NVIDIA DGX Spark vLLM instructions — https://build.nvidia.com/spark/vllm/instructions
- **vLLM on the DGX Spark (container guidance)** — https://vllm.ai/blog/2026-06-01-vllm-dgx-spark
- **vLLM Qwen3.8-27B recipe** — https://recipes.vllm.ai/Qwen/Qwen3.8-27B
- **vLLM Claude Code integration** — https://docs.vllm.ai/en/stable/serving/integrations/claude_code/
- **vLLM Codex integration** — https://docs.vllm.ai/en/stable/serving/integrations/codex/
- **Measured Qwen3.8-27B on a single DGX Spark** — https://forums.developer.nvidia.com/t/qwen3-8-27b-nvfp4-on-a-single-dgx-spark-up-to-1m-context-vllm-mtp-measurements/380244
- vLLM GPU installation docs — https://docs.vllm.ai/en/stable/getting_started/installation/gpu/
- vLLM GitHub repo — https://github.com/vllm-project/vllm
- Ollama FAQ — https://docs.ollama.com/faq
- Open WebUI quick start — https://docs.openwebui.com/getting-started/quick-start/
- Open WebUI env config — https://docs.openwebui.com/reference/env-configuration/
- Open WebUI API docs — https://docs.openwebui.com/reference/api-endpoints/

## Appendix — vLLM source build (last resort)

Use only when no suitable image exists. This is how the `0.18.1rc1` install happened; if you do it, **pin a release tag and record the version**.

```
sudo apt-get update
sudo apt-get install -y gcc-12 g++-12 build-essential cmake ninja-build git \
  python3.12-dev python3-dev python3-venv python3-full libnuma-dev numactl

mkdir -p ~/dgx-spark-vllm && cd ~/dgx-spark-vllm
python3 -m venv qwen38_env          # a NEW venv — never the Coder-Next one
source qwen38_env/bin/activate
pip install --upgrade pip setuptools wheel

pip install --no-cache-dir 'torch==2.10.0+cu130' 'torchvision==0.25.0+cu130' \
  'torchaudio==2.10.0+cu130' --index-url https://download.pytorch.org/whl/cu130

git clone https://github.com/vllm-project/vllm.git && cd vllm
git checkout v0.27.1                # PIN. Revision 1 omitted this step.

export CUDA_HOME=/usr/local/cuda-13.0
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:$LD_LIBRARY_PATH"
export CC=/usr/bin/gcc-12 CXX=/usr/bin/g++-12 CUDAHOSTCXX=/usr/bin/g++-12
export TORCH_CUDA_ARCH_LIST="12.1a"
export MAX_JOBS=8                   # drop to 2 if the JIT OOMs later

pip install -r requirements/build.txt
pip install --no-build-isolation -e .

python -c "import vllm, transformers; print(vllm.__version__, transformers.__version__)"
```

The torch pins above are the revision-1 values and are **not** known to be correct for vLLM 0.27. Check the tag's own `requirements/` before trusting them.

### Smoke test

```
# test_vllm_install.py — run from the repo root
from vllm import LLM, SamplingParams
import torch

def main():
    print("CUDA available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
        print("CUDA version:", torch.version.cuda)
    llm = LLM(model="facebook/opt-125m", enforce_eager=True)
    params = SamplingParams(temperature=0.0, max_tokens=16)
    print(llm.generate(["Hello from DGX Spark"], params)[0].outputs[0].text)

if __name__ == "__main__":
    main()
```

This proves the build works. It does **not** prove the server can drive a coding agent — for that, see *Agent transports*.
