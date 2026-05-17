#!/usr/bin/env bash
# scripts/run-compare-anthropic-vs-vllm.sh
#
# Automated 2-LLM benchmark: Claude Code → <anthropic-model> (Anthropic API)
# vs. Claude Code → <vllm-model> (remote vLLM on an NVIDIA DGX Spark),
# on Aider Polyglot.
#
# ARCHITECTURE (the part that differs from the Ollama sibling script):
#
#   claude-code  ──Anthropic shape──▶  LiteLLM proxy        ──OpenAI shape──▶  vLLM
#   (claude -p)   /v1/messages         127.0.0.1:8787                          192.168.1.23:8000
#                                      (this script starts & kills it)         /v1/chat/completions
#
#   Why the proxy: vLLM exposes an OpenAI-compatible API only
#   (/v1/chat/completions, /v1/models). It does NOT serve an
#   Anthropic-shaped /v1/messages. Claude Code speaks Anthropic API,
#   so pointing ANTHROPIC_BASE_URL straight at vLLM 404s on
#   /v1/messages. Ollama 0.14+ ships an Anthropic shim and needs no
#   proxy; vLLM has none, so we front it with LiteLLM's proxy mode
#   (a single pip dep) as the Anthropic→OpenAI translation layer.
#   vLLM is a *provider*, not a backend — the only backend family is
#   still claude-code; routing is purely env-var gateway plumbing.
#
# ENVIRONMENT (no setup step, no flags): every run creates a throwaway
# Python venv, pip-installs its required libs (litellm[proxy]) into it,
# then DELETES the venv on exit — even on failure or Ctrl-C. Nothing is
# installed into your system/Homebrew Python (which is PEP-668
# externally-managed). The venv, the LiteLLM proxy + its config/log,
# and every scratch temp file are removed on exit. Two things are
# deliberately KEPT: the benchmark results under runs/, and the
# compare-config tmp file — its path is printed at the end so the
# compare is re-runnable. Cost: the litellm[proxy] install (~1-3 min)
# is paid fresh on each run.
#
# CAVEATS — read before trusting a green run:
#
#   1. TOOL CALLS. The user's vLLM is (by default) started WITHOUT
#      `--enable-auto-tool-choice --tool-call-parser qwen3_coder
#      --reasoning-parser qwen3_coder`. Without these, OpenAI-shaped
#      tool calls are NOT parsed into structured tool_calls[]: claude-
#      code sends tools=[…], vLLM ignores them, the model answers in
#      plain prose, and claude-code's tool-use loop cannot action the
#      reply — a SILENT capability loss on Polyglot tasks. RECOMMENDED:
#      restart vLLM with those three flags before any compare run. This
#      script only WARNS (does not abort) — raw-completion-only
#      benchmarks don't need tool parsing.
#
#   2. CONTEXT LENGTH. claude-code requests max_output_tokens=32000 per
#      call; vLLM 400s the request outright when that exceeds
#      --max-model-len (e.g. the default 8192), so a too-small window is
#      a HARD failure — every call 400s, the vLLM candidate is a
#      deterministic 0%, not mere prompt truncation. Preflight ABORTS
#      when /v1/models reports max_model_len below the 32000 output
#      request, and warns below the recommended 65536.
#
# Usage:
#   ./scripts/run-compare-anthropic-vs-vllm.sh [ANTHROPIC_MODEL] [VLLM_MODEL]
#
# Examples:
#   ./scripts/run-compare-anthropic-vs-vllm.sh
#       # defaults: sonnet vs RedHatAI/Qwen3-Coder-Next-NVFP4
#   ./scripts/run-compare-anthropic-vs-vllm.sh opus RedHatAI/Qwen3-Coder-Next-NVFP4
#   VLLM_TIMEOUT=3600 ./scripts/run-compare-anthropic-vs-vllm.sh sonnet RedHatAI/Qwen3-Coder-Next-NVFP4
#
# Stages (gated; press Enter to continue, Ctrl-C to abort):
#   1. Preflight checks — ephemeral venv provisioned + litellm
#      installed + remote vLLM reachable +
#      model served + context-length sanity + LiteLLM proxy started &
#      Anthropic-shape translation confirmed end-to-end + claude CLI +
#      Polyglot dataset cached + harness sanity.
#   2. Harness smoke — one Polyglot task against the vLLM model only
#      (~5-10 min, no Anthropic spend). Confirms env-routing reaches
#      vLLM through the proxy and the harness end-to-end.
#   3. Full compare — Anthropic vs vLLM on configured tasks at
#      --runs N (~15-30 min default; the Anthropic-side runs DO bill
#      the Anthropic account).
#
# Positional args:
#   $1  Anthropic model id   default: sonnet
#   $2  vLLM model id         default: RedHatAI/Qwen3-Coder-Next-NVFP4
#
# Env-var knobs (all optional, orthogonal to positional args):
#   VLLM_BASE         default: http://192.168.1.23:8000  (remote vLLM root).
#   VLLM_TIMEOUT      default: 1800  (per-candidate claude-code timeout, s).
#   LITELLM_PROXY_PORT default: 8787  (local Anthropic→OpenAI proxy port).
#   COMPARE_TASKS     default: python/bowling  (comma-separated for multi-task).
#                     Must be task ids the Polyglot adapter actually exposes —
#                     inspect with: ./scripts/benchmark list --benchmark aider-polyglot
#   SMOKE_TASK        default: first task in COMPARE_TASKS.
#   COMPARE_RUNS      default: 3
#   SKIP_SMOKE=1      jump straight from preflight to compare.
#   SKIP_PREFLIGHT=1  dangerous — only set after a prior run already passed.
#   AUTO_CONFIRM=1    skip the inter-stage gates (for unattended re-runs).
#
# Exit codes:
#   0  all stages green.
#   1  preflight failed (litellm/vLLM/proxy/local environment).
#   2  smoke failed (harness or vLLM routing through the proxy).
#   3  compare failed (one or more candidate runs errored).

set -euo pipefail

# --- Help ---
case "${1:-}" in
    -h|--help)
        sed -n '2,99p' "$0" | sed -E 's/^# ?//'
        exit 0
        ;;
esac

# --- Positional args + env-var defaults ---
ANTHROPIC_MODEL="${1:-sonnet}"
VLLM_MODEL="${2:-RedHatAI/Qwen3-Coder-Next-NVFP4}"

VLLM_BASE="${VLLM_BASE:-http://192.168.1.23:8000}"
VLLM_TIMEOUT="${VLLM_TIMEOUT:-1800}"
LITELLM_PROXY_PORT="${LITELLM_PROXY_PORT:-8787}"
LITELLM_PROXY_BASE="http://127.0.0.1:${LITELLM_PROXY_PORT}"
# Observed from run transcripts: claude-code requests this many output
# tokens per call (max_output_tokens=32000). vLLM returns HTTP 400 when
# this exceeds --max-model-len, so it is the HARD floor below which the
# vLLM candidate is deterministically 0%. The recommended window adds
# room for the multi-file Polyglot prompt on top of that output budget.
CLAUDE_CODE_MAX_OUTPUT_TOKENS=32000
VLLM_CTX_RECOMMENDED=65536
# Per-run unique paths: two concurrent runs with different models/ports
# must not clobber each other's config/log, and both are removed by the
# trap on exit.
LITELLM_CONFIG="$(mktemp -t cct-litellm-vllm.XXXXXX.yaml)"
LITELLM_LOG="$(mktemp -t cct-litellm-vllm.XXXXXX.log)"
# Same rule for the preflight scratch files (vLLM /v1/models dump,
# harness registry dump) — mktemp'd, trap-removed.
VLLM_MODELS_JSON="$(mktemp -t cct-vllm-models.XXXXXX.json)"
BENCH_LIST_JSON="$(mktemp -t cct-bench-list.XXXXXX.json)"
# Per-stage scratch captures, assigned later. Declared empty here so
# cleanup() can reference them under `set -u` even on an early exit,
# and so a signal abort mid-stage does not leak them. COMPARE_CONFIG is
# intentionally NOT tracked — it is kept and printed for re-runs.
TMP_RESP=""
SMOKE_OUTPUT=""
COMPARE_OUTPUT=""

# python/bowling is in the pinned Polyglot snapshot (verified
# 2026-05-15). The dogfood-subset.txt's `python/leap` entry is
# stale — that exercise is NOT in the pinned tree; tracked as a
# separate followup. Verify any task id with:
#   ./scripts/benchmark list --benchmark aider-polyglot
COMPARE_TASKS="${COMPARE_TASKS:-python/bowling}"
SMOKE_TASK="${SMOKE_TASK:-${COMPARE_TASKS%%,*}}"
COMPARE_RUNS="${COMPARE_RUNS:-3}"
SKIP_SMOKE="${SKIP_SMOKE:-0}"
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-0}"
AUTO_CONFIRM="${AUTO_CONFIRM:-0}"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

note_intro() {
    printf '\n=== Anthropic vs vLLM compare ===\n'
    printf '  Anthropic model: %s\n' "$ANTHROPIC_MODEL"
    printf '  vLLM model:      %s\n' "$VLLM_MODEL"
    printf '  vLLM endpoint:   %s\n' "$VLLM_BASE"
    printf '  LiteLLM proxy:   %s\n' "$LITELLM_PROXY_BASE"
    printf '  Tasks:           %s\n' "$COMPARE_TASKS"
    printf '  Runs/candidate:  %s\n' "$COMPARE_RUNS"
    printf '  Smoke task:      %s\n' "$SMOKE_TASK"
    printf '\n'
}

# --- Output helpers ---
ts()   { date +%H:%M:%S; }
note() { printf '[%s] %s\n' "$(ts)" "$*"; }
ok()   { printf '[%s] \033[32mOK\033[0m %s\n' "$(ts)" "$*"; }
warn() { printf '[%s] \033[33mWARN\033[0m %s\n' "$(ts)" "$*" >&2; }
err()  { printf '[%s] \033[31mERR\033[0m %s\n' "$(ts)" "$*" >&2; }

gate() {
    [[ "$AUTO_CONFIRM" == "1" || ! -t 0 ]] && return 0
    printf '\n--- %s ---\n' "$1"
    printf '    Press Enter to continue, Ctrl-C to abort: '
    read -r _ || true
}

# --- Ephemeral virtualenv (auto-provisioned, auto-removed) ---
# Required libs are pip-installed into a throwaway venv, never into the
# user's Python (Homebrew is PEP-668 externally-managed). The venv is
# rm -rf'd on exit by the trap below. No flag, no manual setup.
# Combined with the proxy kill in one trap.
VENV_DIR=""
cleanup_venv() {
    [[ -n "$VENV_DIR" && -d "$VENV_DIR" ]] && rm -rf "$VENV_DIR" || true
}

setup_venv() {
    # Args: pip requirement specs to install (may be empty — e.g. the
    # Ollama sibling needs none; the venv still isolates python3).
    local pip_pkgs=("$@")
    VENV_DIR="$(mktemp -d -t cct-venv-XXXXXX)"
    note "Creating ephemeral venv at $VENV_DIR (auto-removed on exit)"
    if ! python3 -m venv "$VENV_DIR"; then
        err "python3 -m venv failed — cannot provision the test env"
        exit 1
    fi
    # Prepend venv bin so python3 / pip / installed console-scripts
    # (litellm) win; claude + git still resolve from the inherited PATH.
    export PATH="$VENV_DIR/bin:$PATH"
    export VIRTUAL_ENV="$VENV_DIR"
    # No PyPI contact unless there is actually something to install
    # (keeps the helper identical to the Ollama sibling's contract).
    if (( ${#pip_pkgs[@]} > 0 )); then
        "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip > /dev/null
        note "Installing into venv: ${pip_pkgs[*]} (fresh each run)"
        if ! "$VENV_DIR/bin/python" -m pip install --quiet "${pip_pkgs[@]}"; then
            err "pip install failed in venv: ${pip_pkgs[*]}"
            exit 1
        fi
    fi
    ok "Ephemeral venv ready"
}

# --- LiteLLM proxy lifecycle ---
# The proxy is the Anthropic→OpenAI translation layer. It must die with
# this script — leaking a backgrounded litellm holding :8787 breaks the
# next run's preflight. Trap installed the moment we have a PID.
LITELLM_PID=""
cleanup_proxy() {
    [[ -n "$LITELLM_PID" ]] && kill "$LITELLM_PID" 2>/dev/null || true
    rm -f "$LITELLM_CONFIG" "$LITELLM_LOG" 2>/dev/null || true
}
# Idempotent (every step is guarded), so running it twice — once from a
# signal trap, once from the EXIT trap — is harmless.
cleanup() {
    cleanup_proxy
    rm -f "$VLLM_MODELS_JSON" "$BENCH_LIST_JSON" \
          "$TMP_RESP" "$SMOKE_OUTPUT" "$COMPARE_OUTPUT" 2>/dev/null || true
    # Reap any child still writing into the venv (e.g. a pip install
    # interrupted by a signal) so the rm -rf is not racing it.
    pkill -P $$ 2>/dev/null || true
    cleanup_venv
}
# A bare `trap … EXIT` does NOT run on SIGINT/SIGTERM/SIGHUP in bash —
# only on normal exit or `exit N`. Trap the signals explicitly so an
# aborted run (Ctrl-C at a gate, kill mid-pip) still tears the env down.
# SIGKILL alone cannot be trapped — that is the only uncleaned path.
on_signal() { cleanup; exit 130; }
trap cleanup EXIT
trap on_signal INT TERM HUP

start_litellm_proxy() {
    # 1. litellm present? It is pip-installed into the ephemeral venv by
    #    setup_venv before any stage; this guards against a silent
    #    install failure (pip succeeded but no console-script on PATH).
    if ! command -v litellm > /dev/null; then
        err "litellm missing after venv provisioning — inspect the pip output above"
        exit 1
    fi
    ok "litellm present in venv: $(litellm --version 2>/dev/null | head -1 || echo 'version unknown')"

    # 2. Write the translation config. One alias that maps Anthropic-
    #    shaped traffic to the remote vLLM's OpenAI API. The hosted_vllm/
    #    prefix routes through LiteLLM's purpose-built vLLM adapter, which
    #    pins to /v1/chat/completions. The generic openai/ provider on
    #    LiteLLM >= 1.50 auto-detects vLLM's advertised /v1/responses
    #    endpoint and routes multi-turn conversations through it; vLLM's
    #    Responses API rejects LiteLLM's input-array shape with a
    #    212-validation-error 400 (agent solves task at turn ~9, dies at
    #    turn ~10 on the next continuation). hosted_vllm/ avoids that
    #    route discovery. api_key is required by the SDK; vLLM ignores it.
    cat > "$LITELLM_CONFIG" <<EOF
model_list:
  - model_name: "$VLLM_MODEL"
    litellm_params:
      model: "hosted_vllm/$VLLM_MODEL"
      api_base: "${VLLM_BASE%/}/v1"
      api_key: "dummy"
litellm_settings:
  drop_params: true
EOF
    ok "LiteLLM config written: $LITELLM_CONFIG"

    # 3. Start the proxy in the background; capture PID for the trap.
    note "Starting LiteLLM proxy on ${LITELLM_PROXY_BASE} → ${VLLM_BASE%/}/v1 …"
    litellm --config "$LITELLM_CONFIG" --port "$LITELLM_PROXY_PORT" --host 127.0.0.1 \
        > "$LITELLM_LOG" 2>&1 &
    LITELLM_PID=$!

    # 4. Wait up to 30s for /v1/models to answer.
    local i
    for i in $(seq 1 30); do
        if ! kill -0 "$LITELLM_PID" 2>/dev/null; then
            err "LiteLLM proxy process died during startup. Log:"
            tail -40 "$LITELLM_LOG" >&2 || true
            exit 1
        fi
        if curl -sS --max-time 2 "${LITELLM_PROXY_BASE}/v1/models" > /dev/null 2>&1; then
            ok "LiteLLM proxy up (PID $LITELLM_PID), /v1/models responding"
            return 0
        fi
        sleep 1
    done
    err "LiteLLM proxy did not answer /v1/models within 30s. Log:"
    tail -40 "$LITELLM_LOG" >&2 || true
    exit 1
}

# --- Print parsed config ---
note_intro

# --- Provision the ephemeral test env (needed by all stages) ---
setup_venv 'litellm[proxy]>=1.50'

# --- Stage 1: Preflight ---
if [[ "$SKIP_PREFLIGHT" == "1" ]]; then
    note "Skipping preflight (SKIP_PREFLIGHT=1)"
else
    note "Stage 1/3 — preflight checks"

    # 1a. Remote vLLM reachable + serves the requested model?
    if ! curl -sS --max-time 5 "${VLLM_BASE%/}/v1/models" > "$VLLM_MODELS_JSON"; then
        err "Remote vLLM not reachable at ${VLLM_BASE}/v1/models."
        err "Ensure the remote vLLM at $VLLM_BASE is up — ssh to the DGX and run:"
        err "    curl http://127.0.0.1:8000/v1/models"
        exit 1
    fi
    if ! grep -qF "\"$VLLM_MODEL\"" "$VLLM_MODELS_JSON"; then
        err "vLLM is up but does not serve model id '$VLLM_MODEL'. /v1/models reports:"
        grep -oE '"id":"[^"]+"' "$VLLM_MODELS_JSON" | cut -d'"' -f4 | sed 's/^/      /' >&2 || true
        err "Pass the exact served id as \$2, or start vLLM with --served-model-name."
        exit 1
    fi
    ok "Remote vLLM reachable and serves $VLLM_MODEL"

    # 1b. Context-length GATE (Caveat 2). claude-code requests
    #     max_output_tokens=$CLAUDE_CODE_MAX_OUTPUT_TOKENS per call; vLLM
    #     rejects the request with HTTP 400 when that exceeds
    #     --max-model-len, before generating a token. A window below that
    #     request is therefore a deterministic 0% for the vLLM candidate
    #     — hard-fail here rather than burn a multi-minute run to find a
    #     400 in every transcript.
    CTX_LEN=$(grep -oE '"max_model_len":[[:space:]]*[0-9]+' "$VLLM_MODELS_JSON" \
        | head -1 | grep -oE '[0-9]+$' || true)
    if [[ -z "$CTX_LEN" ]]; then
        warn "Could not read max_model_len from /v1/models — cannot verify the context"
        warn "  budget. If vLLM is on the default --max-model-len 8192, EVERY claude-code"
        warn "  call will 400 (max_output_tokens=$CLAUDE_CODE_MAX_OUTPUT_TOKENS > 8192)."
        warn "  Strongly recommend restarting vLLM with --max-model-len $VLLM_CTX_RECOMMENDED+."
    elif (( CTX_LEN < CLAUDE_CODE_MAX_OUTPUT_TOKENS )); then
        err "vLLM max_model_len=$CTX_LEN < claude-code's per-call output request"
        err "  ($CLAUDE_CODE_MAX_OUTPUT_TOKENS). vLLM will reject EVERY request with HTTP"
        err "  400 (\"max_output_tokens=$CLAUDE_CODE_MAX_OUTPUT_TOKENS cannot be greater"
        err "  than max_model_len=$CTX_LEN\") before generating a token — the vLLM"
        err "  candidate would be a deterministic 0%. Restart vLLM with"
        err "  --max-model-len $VLLM_CTX_RECOMMENDED plus the tool/reasoning parser"
        err "  flags, then re-run. Aborting before the run is spent."
        exit 1
    elif (( CTX_LEN < VLLM_CTX_RECOMMENDED )); then
        warn "vLLM max_model_len=$CTX_LEN accepts requests but leaves little room for a"
        warn "  multi-file Polyglot prompt on top of the $CLAUDE_CODE_MAX_OUTPUT_TOKENS-token"
        warn "  output budget — long tasks may still truncate. Recommended:"
        warn "  --max-model-len $VLLM_CTX_RECOMMENDED+."
    else
        ok "vLLM max_model_len=$CTX_LEN (>= recommended $VLLM_CTX_RECOMMENDED)"
    fi

    # 1c. Tool-call parser advisory (Caveat 1). We cannot reliably probe
    #     whether vLLM was started with --enable-auto-tool-choice from
    #     /v1/models, so this is an unconditional advisory, not a gate.
    warn "Tool-call parsing is NOT verifiable from /v1/models. If this vLLM was started"
    warn "  WITHOUT --enable-auto-tool-choice --tool-call-parser qwen3_coder"
    warn "  --reasoning-parser qwen3_coder, claude-code's tool-use loop will silently"
    warn "  fail on Polyglot tasks. Restart vLLM with those three flags unless this is a"
    warn "  raw-completion-only benchmark. (Proceeding — advisory only.)"

    # 1d. Start the LiteLLM Anthropic→OpenAI proxy.
    start_litellm_proxy

    # 1e. THE critical preflight: one Anthropic-shaped /v1/messages call
    #     through the proxy. Bugs in the translation layer MUST surface
    #     here, not deep in stage 3. Mirrors the Ollama script's
    #     '"type":"message"' confirmation.
    TMP_RESP=$(mktemp)
    HTTP=$(curl -sS -o "$TMP_RESP" -w '%{http_code}' --max-time 300 -X POST \
        "${LITELLM_PROXY_BASE}/v1/messages" \
        -H "Content-Type: application/json" \
        -H "anthropic-version: 2023-06-01" \
        -H "x-api-key: dummy" \
        -d "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,
             \"messages\":[{\"role\":\"user\",\"content\":\"Reply: OK\"}]}" || echo "000")
    if [[ "$HTTP" != "200" ]]; then
        err "Anthropic /v1/messages through the LiteLLM proxy returned HTTP $HTTP. Response:"
        cat "$TMP_RESP" >&2 || true
        err "Proxy log tail:"
        tail -40 "$LITELLM_LOG" >&2 || true
        rm -f "$TMP_RESP"
        exit 1
    fi
    if ! grep -q '"type":"message"' "$TMP_RESP"; then
        err "Proxy response not Anthropic-shaped — translation layer is broken:"
        cat "$TMP_RESP" >&2
        rm -f "$TMP_RESP"
        exit 1
    fi
    rm -f "$TMP_RESP"
    ok "End-to-end translation confirmed: Anthropic /v1/messages → proxy → vLLM"

    # 1f. claude CLI present?
    if ! command -v claude > /dev/null; then
        err "claude CLI not on PATH. Install Claude Code first."
        exit 1
    fi
    ok "Claude Code: $(claude --version)"

    # 1g. Polyglot dataset cached?
    if ! find benchmarks/.cache/polyglot -name "*.md" -print -quit 2>/dev/null | grep -q .; then
        note "Polyglot dataset not cached; fetching (one-time, ~clones upstream)…"
        python3 -m benchmarks.adapters.aider_polyglot.fetch
    fi
    ok "Polyglot dataset cached"

    # 1h. Harness wiring sane?
    if ! ./scripts/benchmark list > "$BENCH_LIST_JSON"; then
        err "./scripts/benchmark list failed; harness setup is broken"
        exit 1
    fi
    if ! grep -q '"aider-polyglot"' "$BENCH_LIST_JSON"; then
        err "aider-polyglot adapter missing from registry"
        exit 1
    fi
    if ! grep -q '"claude-code"' "$BENCH_LIST_JSON"; then
        err "claude-code backend missing from registry"
        exit 1
    fi
    ok "Harness reports adapters/backends correctly"
fi

# If preflight was skipped, the proxy was never started. Stages 2 & 3
# route through it, so bring it up now (idempotent guard via PID).
if [[ -z "$LITELLM_PID" ]]; then
    note "Bringing up LiteLLM proxy (preflight was skipped)"
    start_litellm_proxy
fi

# --- Stage 2: Smoke ---
if [[ "$SKIP_SMOKE" == "1" ]]; then
    note "Skipping smoke (SKIP_SMOKE=1)"
else
    gate "Stage 2/3 — smoke: Polyglot task '$SMOKE_TASK' against $VLLM_MODEL only (~5-10 min, no Anthropic spend)"
    note "Running smoke against task: $SMOKE_TASK"

    SMOKE_OUTPUT=$(mktemp)
    # Pass the same per-candidate timeout used in stage 3's compare
    # config (default 1800s; VLLM_TIMEOUT override propagates here too).
    # Without this, the smoke uses the harness default 600s — too tight
    # for a remote MoE behind a translation proxy and produces spurious
    # "smoke failed" signals before the real compare can start.
    if ANTHROPIC_BASE_URL="$LITELLM_PROXY_BASE" \
       ANTHROPIC_AUTH_TOKEN=dummy \
       ANTHROPIC_DEFAULT_SONNET_MODEL="$VLLM_MODEL" \
       ANTHROPIC_DEFAULT_HAIKU_MODEL="$VLLM_MODEL" \
       CCT_CLAUDE_TIMEOUT_SECONDS="$VLLM_TIMEOUT" \
       ./scripts/benchmark run --benchmark aider-polyglot \
           --backend claude-code --model "$VLLM_MODEL" \
           --task "$SMOKE_TASK" --runs 1 \
           | tee "$SMOKE_OUTPUT"; then
        SMOKE_RUN_DIR=$(grep -oE '"run_dir":[[:space:]]*"[^"]+"' "$SMOKE_OUTPUT" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
        ok "Smoke completed. Run-dir: $SMOKE_RUN_DIR"

        SCORE_PATH=$(find "$SMOKE_RUN_DIR" -name "score.json" 2>/dev/null | head -1)
        if [[ -n "$SCORE_PATH" ]]; then
            RESULT=$(grep -oE '"result":[[:space:]]*"[^"]+"' "$SCORE_PATH" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
            ELAPSED=$(grep -oE '"elapsed_seconds":[[:space:]]*[0-9.]+' "$SCORE_PATH" | head -1 | grep -oE '[0-9.]+$')
            note "Smoke score: result=$RESULT  elapsed=${ELAPSED}s"
            note "  $SCORE_PATH"
            if [[ "$RESULT" == "error" ]]; then
                err "Smoke result=error — abort before spending Anthropic credits on the compare"
                err "Inspect: $SMOKE_RUN_DIR"
                exit 2
            fi
        fi
    else
        err "Smoke run failed"
        rm -f "$SMOKE_OUTPUT"
        exit 2
    fi
    rm -f "$SMOKE_OUTPUT"
fi

# --- Stage 3: Full compare ---
gate "Stage 3/3 — full compare: $ANTHROPIC_MODEL (Anthropic) vs $VLLM_MODEL (vLLM) on '$COMPARE_TASKS' at --runs $COMPARE_RUNS (~15-30 min; the Anthropic side WILL bill your account)"

# Render the compare config (comma-separated tasks → JSON array).
TASKS_JSON=$(printf '"%s"' "$COMPARE_TASKS" | sed 's/,/","/g')
COMPARE_CONFIG=$(mktemp -t compare-anthropic-vs-vllm.XXXXXX.json)
cat > "$COMPARE_CONFIG" <<EOF
{
  "benchmark": "aider-polyglot",
  "runs": $COMPARE_RUNS,
  "task": [$TASKS_JSON],
  "candidates": [
    {
      "name": "anthropic-$ANTHROPIC_MODEL",
      "backend": "claude-code",
      "model": "$ANTHROPIC_MODEL"
    },
    {
      "name": "vllm-$VLLM_MODEL",
      "backend": "claude-code",
      "model": "$VLLM_MODEL",
      "env": {
        "ANTHROPIC_BASE_URL": "$LITELLM_PROXY_BASE",
        "ANTHROPIC_AUTH_TOKEN": "dummy",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "$VLLM_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "$VLLM_MODEL",
        "CCT_CLAUDE_TIMEOUT_SECONDS": "$VLLM_TIMEOUT"
      }
    }
  ]
}
EOF
note "Compare config written to: $COMPARE_CONFIG"
note "Contents:"
sed 's/^/    /' "$COMPARE_CONFIG"
echo

COMPARE_OUTPUT=$(mktemp)
if ./scripts/benchmark compare --config "$COMPARE_CONFIG" | tee "$COMPARE_OUTPUT"; then
    COMPARE_RUN_DIR=$(grep -oE '"run_dir":[[:space:]]*"[^"]+"' "$COMPARE_OUTPUT" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
    REPORT_MD=$(grep -oE '"report_md":[[:space:]]*"[^"]+"' "$COMPARE_OUTPUT" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
    ok "Compare completed."
    note "Run-dir: $COMPARE_RUN_DIR"
    note "Report:  $REPORT_MD"
    echo
    echo "================ Report preview (first 80 lines) ================"
    head -80 "$REPORT_MD"
    echo "==================================================================="
    echo
    note "Full report:    cat $REPORT_MD"
    note "Full JSON:      cat ${REPORT_MD%.md}.json"
    note "Compare config kept at: $COMPARE_CONFIG (re-runnable with: ./scripts/benchmark compare --config $COMPARE_CONFIG)"
else
    err "Compare failed; inspect run-dir for postmortem"
    rm -f "$COMPARE_OUTPUT"
    exit 3
fi
rm -f "$COMPARE_OUTPUT"

ok "All stages complete."
