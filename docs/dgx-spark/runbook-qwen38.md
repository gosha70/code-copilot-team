# Qwen3.8-27B on spark-c2e5 — exact execution sequence

Two machines. Every command is labelled **[SPARK]** or **[MAC]**. Run them in order; the phases are ordered so that a failure is cheap to diagnose.

Assumes the scripts are in your home directory on the Spark (that is where you have been running them from).

```
  Phase 0   optional cleanup                 [SPARK]   ~10 min
  Phase 1   make the address stable          [SPARK]   ~5 min   ← do before any config
  Phase 2   pull + verify the image          [SPARK]   15-30 min
  Phase 3   pre-stage the weights            [SPARK]   20-45 min
  Phase 4   first boot                       [SPARK]   10-15 min JIT
  Phase 5   record the numbers               [SPARK]   ~2 min
  Phase 6   the gate  ← DECISION POINT       [SPARK]   ~5 min
  Phase 7   LiteLLM bridge (only if gate 6 failed)     [SPARK]   ~5 min
  Phase 8   Mac prerequisites                [MAC]     ~5 min
  Phase 9   gate over the real network path  [MAC]     ~5 min
  Phase 10  Codex                            [MAC]     ~5 min
  Phase 11  Claude Code                      [MAC]     ~5 min
  Phase 12  the tests that actually matter   [MAC]     hours
```

**Before you start: plug in Ethernet.** enP7s7 is NO-CARRIER. Phases 2 and 3 move roughly 35 GB, and Wi-Fi is also carrying everything else.

## Phase 0 — [SPARK] Optional cleanup

Skip this entirely if you would rather get the model running. You have 3.3 TB free; none of this makes room for Qwen3.8. It is tidiness.

```
docker container prune -f
docker image prune -f
docker builder prune -f

bash ~/retire-ollama-openwebui.sh              # DRY RUN — read the output
APPLY=1 bash ~/retire-ollama-openwebui.sh      # then for real

rm -rf ~/.cache/pip
rm -rf ~/.cache/huggingface/hub/models--Qwen--Qwen3-32B            # 62G, failed experiment
rm -rf ~/.cache/huggingface/hub/models--Qwen--Qwen2.5-7B-Instruct  # 15G, old smoke test
rm -rf ~/.cache/huggingface/hub/models--Qwen--Qwen2.5-72B-Instruct # 11M stub

df -h /
```

Confirm the fallback survived:

```
source ~/dgx-spark-vllm/vllm_env/bin/activate
python -c "import vllm; print(vllm.__version__)"     # expect 0.18.1rc1.dev245
ls ~/dgx-spark-vllm/models/
deactivate
```

## Phase 1 — [SPARK] Make the address stable

Do this **before** anything writes an address into a config file. The Spark is on a Wi-Fi DHCP lease; when it renews to a different address every hardcoded IP breaks at once, silently.

```
# 1.1 — is mDNS working?
hostname                                        # spark-c2e5
systemctl is-active avahi-daemon                # want: active
sudo apt-get install -y avahi-utils             # if avahi-resolve is missing
avahi-resolve -n spark-c2e5.local               # may answer with IPv6 — see next line
avahi-resolve -4 -n spark-c2e5.local            # THIS is the one that matters: want 192.168.1.23

# 1.2 — after plugging in Ethernet
ip -br addr show enP7s7                         # want: UP with an address
hostname -I                                     # LAN address is the FIRST one
```

**1.3 — set a DHCP reservation on your router** for both interfaces, so the address survives a lease renewal either way:

```
Wi-Fi     wlP9s9    f8:3d:c6:b7:30:4c
Ethernet  enP7s7    4c:bb:47:2c:c2:e5
```

**If avahi-resolve -n answers with an fe80:: address**, that is an IPv6 link-local address, and it is not usable in a config file: link-local requires a zone index (fe80::...%en0) that no base_url field will accept. Re-run with -4. If the -4 form returns 192.168.1.23, mDNS is fine and macOS will pick the IPv4 — nothing to do. If -4 returns nothing, use the /etc/hosts fallback in Phase 8.

If mDNS does not resolve from the Mac in Phase 8, you will fall back to the IP — which is exactly why the reservation matters.

## Phase 2 — [SPARK] Pull and verify the image

```
docker pull eugr/spark-vllm:latest

# record the digest — a nightly tag is a moving target, this is the pin
docker image inspect --format '{{index .RepoDigests 0}}' \
  eugr/spark-vllm:latest | tee ~/qwen38-image-digest.txt
```

**Check the floors before spending 45 minutes on weights:**

```
docker run --rm -i --entrypoint python3 eugr/spark-vllm:latest - <<'PY'
from packaging.version import Version
ok = True
for mod, floor in (("vllm", "0.26.0"), ("transformers", "5.8.0")):
    v = Version(__import__(mod).__version__.split("+")[0])
    good = v >= Version(floor)
    print(f"{'OK ' if good else 'LOW'} {mod} {v} (need >= {floor})")
    ok &= good
raise SystemExit(0 if ok else 1)
PY
```

- **Two OK lines and exit=0** → continue.
- **Either LOW** → try vllm/vllm-openai:cu129-nightly, or a *-aarch64

variant, and re-run. Do not proceed on a LOW; transformers 4.x cannot load the Qwen3.8 config at all.

- **No output at all, exit=0** → the check did not run. docker run does not

attach stdin unless you pass -i, so the heredoc went nowhere, python3 - read an empty program and exited 0. **Silence here is a failure, not a pass.** Confirm the -i is present and re-run — you want to see two verdict lines before you trust the exit code.

## Phase 3 — [SPARK] Pre-stage the weights

Downloading inside the first boot makes a slow start look like a hang. Do it separately, where you can watch it.

```
docker run --rm \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  --entrypoint python3 eugr/spark-vllm:latest -c \
  "from huggingface_hub import snapshot_download; \
   snapshot_download('unsloth/Qwen3.8-27B-NVFP4')"

du -sh ~/.cache/huggingface/hub/models--unsloth--Qwen3.8-27B-NVFP4   # expect ~23G
```

**Check the tokenizer before you trust anything downstream.** Some early quantized releases shipped a truncation cap that silently cuts every prompt to 2048 tokens — requests succeed, numbers look right, answers are wrong:

```
grep -o '"truncation"[^}]*}' \
  ~/.cache/huggingface/hub/models--unsloth--Qwen3.8-27B-NVFP4/snapshots/*/tokenizer_config.json \
  || echo "no truncation entry — good"
```

## Phase 4 — [SPARK] First boot

```
VLLM_DRY_RUN=1 bash ~/start-qwen38-27b-docker.sh    # read the command first
bash ~/start-qwen38-27b-docker.sh
docker logs -f qwen38-27b-8001
```

What you will see, in order:

```
Loading model weights ...                 ← looks stuck for minutes. It is not.
Compiling kernel ...  (many lines)        ← flashinfer JIT for sm_121a, 10-15 min
... GPU KV cache size: N tokens ...       ← RECORD THIS NUMBER
Application startup complete
```

**Do not kill it during the JIT.** If it dies with ninja: build stopped or exit 137, restart with MAX_JOBS=1 NINJA_JOBS=1 in the environment — the partial kernel cache survives and the next attempt resumes.

Confirm it is up (Ctrl-C out of the log follow first):

```
curl -s http://127.0.0.1:8001/v1/models | jq '.data[] | {id, max_model_len}'
```

Expect qwen38-27b first (slash-free) and max_model_len: 262144.

## Phase 5 — [SPARK] Record the numbers

```
docker logs qwen38-27b-8001 > ~/qwen38-boot.log 2>&1
bash ~/record-spark-memory.sh ~/qwen38-boot.log | tee ~/qwen38-memory-record.txt
```

This is the first measurement on your hardware rather than someone else's. Keep the file; it is what promotes the doc's derived numbers to measured ones.

## Phase 6 — [SPARK] The gate — decision point

```
bash ~/verify-qwen38-spark.sh 127.0.0.1 8001 qwen38-27b
```

Seven gates. Two of them decide what you do next:

| **Gate** | **If it fails** |
|---|---|
| 2 — structured tool_calls[] | Restart with VLLM_TOOL_CALL_PARSER=qwen3_xml. If the XML is in .reasoning instead, the reasoning parser is intercepting. |
| 5 — function_call in /v1/responses | Codex cannot use this server. Fix before Phase 10. |
| **6 — trailing system turn** | **Go to Phase 7.** Claude Code needs the LiteLLM bridge on this build. |

**Gate 6 PASS** → skip Phase 7. Claude Code talks to vLLM directly. **Gate 6 FAIL** → do Phase 7. This is the expected case on many builds and is not a fault in your setup.

Gate 6 is the only one whose failure returns HTTP 200. Gates 1–5 and 7 all pass against a server that is silently broken for Claude Code, so do not skip it.

## Phase 7 — [SPARK] LiteLLM bridge (only if gate 6 failed)

Run it on the Spark, not the Mac — then the laptop needs no extra service.

```
mkdir -p ~/litellm
cat > ~/litellm/qwen38.yaml <<'YAML'
model_list:
  - model_name: qwen38-27b
    litellm_params:
      # hosted_vllm/ pins to /v1/chat/completions. The generic openai/ prefix
      # is auto-detected as the Responses API and routed to /v1/responses,
      # which breaks multi-turn.
      model: hosted_vllm/qwen38-27b
      api_base: http://127.0.0.1:8001/v1
      api_key: dummy
YAML

docker run -d --name litellm-8787 --restart unless-stopped \
  --network host \
  -v ~/litellm/qwen38.yaml:/app/config.yaml \
  ghcr.io/berriai/litellm:main-latest \
  --config /app/config.yaml --port 8787 --host 0.0.0.0

sleep 10
curl -s http://127.0.0.1:8787/v1/models | jq '.data[].id'    # expect qwen38-27b
docker logs --tail=30 litellm-8787
```

## Phase 8 — [MAC] Prerequisites

```
brew install jq

ping -c 3 spark-c2e5.local
curl -s http://spark-c2e5.local:8001/v1/models | jq '.data[].id'
```

**If mDNS does not resolve**, do NOT pin a .local name in /etc/hosts. macOS routes every .local lookup to mDNSResponder, so a hosts entry for one is inconsistently honoured. Use a plain name instead — it bypasses mDNS entirely and is stable as long as the DHCP reservation from Phase 1 holds:

```
echo "192.168.1.23  spark" | sudo tee -a /etc/hosts
ping -c 3 spark
curl -s http://spark:8001/v1/models | jq '.data[].id'
```

Then substitute spark for spark-c2e5.local everywhere below — Phases 9, 10 and 11, and SPARK_HOST if you use spark-qwen38.env.sh.

Copy the two client-side scripts over. Both are bash 3.2 clean and use no GNU-only flags, so they run on stock macOS:

```
scp egoge-nvidia@spark-c2e5.local:~/verify-qwen38-spark.sh .
scp egoge-nvidia@spark-c2e5.local:~/check-transport-wiring.sh .
chmod +x verify-qwen38-spark.sh check-transport-wiring.sh
```

## Phase 9 — [MAC] Run the gate over the real network path

Phase 6 tested loopback. This tests what the agents will actually traverse — Wi-Fi, mDNS, and any firewall in between.

```
bash verify-qwen38-spark.sh spark-c2e5.local 8001 qwen38-27b
```

A gate that passed on the Spark and fails here is a **network** problem, not a model one. Check that vLLM is bound to 0.0.0.0 and not 127.0.0.1:

```
# [SPARK]
docker port qwen38-27b-8001
```

## Phase 10 — [MAC] Codex

```
mkdir -p ~/.codex
cat >> ~/.codex/config.toml <<'TOML'

model = "qwen38-27b"
model_provider = "dgx-vllm"

[model_providers.dgx-vllm]
name = "DGX Spark vLLM"
base_url = "http://spark-c2e5.local:8001/v1"
env_key = "VLLM_API_KEY"
wire_api = "responses"
TOML

export VLLM_API_KEY=dummy      # vLLM ignores it; Codex will not start without one
```

Add that export to ~/.zshrc so it survives a new shell.

```
cd ~/some-repo
codex
```

## Phase 11 — [MAC] Claude Code

Pick the block that matches your Phase 6 result. Put it in ~/.zshrc or a sourced file — **not** typed once and forgotten.

**Gate 6 PASSED — direct:**

```
export ANTHROPIC_BASE_URL="http://spark-c2e5.local:8001"   # bare origin, NO /v1
export EXPECT_CC_TRANSPORT=native
```

**Gate 6 FAILED — via the bridge:**

```
export ANTHROPIC_BASE_URL="http://spark-c2e5.local:8787"
export LITELLM_ORIGIN="http://spark-c2e5.local:8787"
```

**Both cases, then:**

```
export ANTHROPIC_AUTH_TOKEN="dummy"
export ANTHROPIC_MODEL="qwen38-27b"
export ANTHROPIC_DEFAULT_OPUS_MODEL="qwen38-27b"
export ANTHROPIC_DEFAULT_SONNET_MODEL="qwen38-27b"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="qwen38-27b"
export ANTHROPIC_SMALL_FAST_MODEL="qwen38-27b"
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=32000
export CCT_LOCAL_OPENAI_BASE_URL="http://spark-c2e5.local:8001/v1"

VLLM_ORIGIN="http://spark-c2e5.local:8001" bash check-transport-wiring.sh
```

That last command catches the silent cross-wire — pointing Claude Code at vLLM's own origin when you meant the bridge. It also catches a /v1 suffix on the wrong URL and any unpinned model tier.

Then, in a repo:

```
claude
```

**Switching back to Anthropic:** unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL ANTHROPIC_SMALL_FAST_MODEL. Consider a shell function rather than leaving these exported permanently.

## Phase 12 — [MAC] The tests that actually matter

Everything so far proves the plumbing. None of it proves the model can do the job.

**12.1 — Codex on a real repo task.** Not a prompt: inspect files → edit → run a command or test → fix → finish.

**12.2 — Claude Code for 15–30 tool turns.** A one-prompt smoke test cannot distinguish a working agent from the gate-6 failure, which by construction dies on turn two.

**12.3 — the anchor benchmark**, in code-copilot-team:

```
./scripts/bench --task python/bowling --runs 3 sonnet \
  vllm:qwen38-27b@http://spark-c2e5.local:8001
```

Apply the bench.py probe patch first, or the harness may select a transport gate 6 already failed and score the run against it.

Against the existing anchors: Sonnet 3/3 @ 141 ± 39 s, Qwen3-Coder-Next 3/3 @ 473 ± 449 s.

**Record the ratio, not the throughput:**

```
        tasks completed correctly
   ───────────────────────────────────
    wall-clock time  ×  turns consumed
```

A model that finishes in 8 turns at 22 tok/s beats one that stalls at turn 25 at 50 tok/s, and tokens per second cannot tell them apart.

## Phase 13 — [SPARK] Only after 12 passes

**Add MTP** (roughly doubles decode):

```
VLLM_SPEC_TOKENS=3 bash ~/start-qwen38-27b-docker.sh
bash ~/verify-qwen38-spark.sh 127.0.0.1 8001 qwen38-27b
```

**Then, much later, the 1M window:**

```
VLLM_MAX_MODEL_LEN=1010000 VLLM_YARN=1 VLLM_GPU_UTIL=0.72 \
  bash ~/start-qwen38-27b-docker.sh
```

Expect another 5–15 minute flashinfer recompile at the new tile sizes, and re-run the whole gate. Read §5.4 of dgx-spark-qwen38.md first — a cold 1M-token prefill is a 20-minute wait before the first output token.

## Everyday commands afterwards

```
# [SPARK]
docker logs -f qwen38-27b-8001
docker restart qwen38-27b-8001
docker rm -f qwen38-27b-8001                       # stop
bash ~/start-qwen38-27b-docker.sh                  # start again
bash ~/record-spark-memory.sh ~/qwen38-boot.log

# [MAC]
curl -s http://spark-c2e5.local:8001/v1/models | jq '.data[].id'
bash verify-qwen38-spark.sh spark-c2e5.local 8001 qwen38-27b
bash check-transport-wiring.sh
```

**Re-run gate 6 after every Claude Code update.** The trailing-system failure is version-coupled on both sides, and it returns HTTP 200.

The Coder-Next fallback is untouched throughout. If you need it:

```
# [SPARK]
bash <path-to-rlm-studio>/scripts/dgx-spark/vllm/start-qwen3-coder-next.sh
```

Both servers at once needs the combined --gpu-memory-utilization at or under 0.90 — Coder-Next's verified 0.72 plus this one's 0.45 is 142 GiB on a 121.6 GiB box and will not boot.
