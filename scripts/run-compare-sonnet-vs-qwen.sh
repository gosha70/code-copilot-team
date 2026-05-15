#!/usr/bin/env bash
# scripts/run-compare-sonnet-vs-qwen.sh
#
# Automated multi-LLM benchmark: Claude Code → sonnet (Anthropic API)
# vs. Claude Code → qwen3.6:27b (local Ollama), on Aider Polyglot.
#
# Stages (gated; press Enter to continue, Ctrl-C to abort):
#   1. Preflight checks — Ollama running + version + model + endpoint
#      shape + claude CLI + Polyglot dataset cached + harness sanity.
#   2. Harness smoke — one Polyglot Python task against qwen3.6:27b
#      only (~5-10 min, no Anthropic spend). Confirms the env-routing
#      reaches Ollama end-to-end through the harness.
#   3. Full compare — sonnet vs qwen on configured tasks at --runs N
#      (~15-30 min default; sonnet runs DO bill the Anthropic account).
#
# Knobs (env vars, all optional):
#   QWEN_MODEL       default: qwen3.6:27b
#   COMPARE_TASKS    default: python/leap   (comma-separated for multi-task)
#   COMPARE_RUNS     default: 3
#   SKIP_SMOKE=1     jump straight from preflight to compare.
#   SKIP_PREFLIGHT=1 dangerous — only set after a prior run already passed.
#   AUTO_CONFIRM=1   skip the inter-stage gates (for unattended re-runs).
#
# Exit codes:
#   0  all stages green.
#   1  preflight failed (state of the local environment).
#   2  smoke failed (harness or Ollama routing).
#   3  compare failed (one or more candidate runs errored).
#
# To compare other models, copy this file and edit the two `cat
# <<EOF` blocks (smoke env vars + compare-config JSON). The
# preflight/smoke skeleton is reusable as-is.

set -euo pipefail

# --- Defaults ---
QWEN_MODEL="${QWEN_MODEL:-qwen3.6:27b}"
COMPARE_TASKS="${COMPARE_TASKS:-python/leap}"
COMPARE_RUNS="${COMPARE_RUNS:-3}"
SKIP_SMOKE="${SKIP_SMOKE:-0}"
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-0}"
AUTO_CONFIRM="${AUTO_CONFIRM:-0}"

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# --- Output helpers ---
ts()   { date +%H:%M:%S; }
note() { printf '[%s] %s\n' "$(ts)" "$*"; }
ok()   { printf '[%s] \033[32mOK\033[0m %s\n' "$(ts)" "$*"; }
err()  { printf '[%s] \033[31mERR\033[0m %s\n' "$(ts)" "$*" >&2; }

gate() {
    [[ "$AUTO_CONFIRM" == "1" || ! -t 0 ]] && return 0
    printf '\n--- %s ---\n' "$1"
    printf '    Press Enter to continue, Ctrl-C to abort: '
    read -r _ || true
}

# --- Stage 1: Preflight ---
if [[ "$SKIP_PREFLIGHT" == "1" ]]; then
    note "Skipping preflight (SKIP_PREFLIGHT=1)"
else
    note "Stage 1/3 — preflight checks"

    # 1a. Ollama reachable?
    if ! curl -sS --max-time 3 http://localhost:11434/api/version > /tmp/cct-ollama-version.json; then
        err "Ollama not reachable at http://localhost:11434. Start it: ollama serve"
        exit 1
    fi
    OLLAMA_VERSION=$(grep -oE '"version":"[^"]+"' /tmp/cct-ollama-version.json | cut -d'"' -f4)
    ok "Ollama running, version $OLLAMA_VERSION"

    # 1b. Ollama version >= 0.14.0?
    if [[ ! "$OLLAMA_VERSION" =~ ^([0-9]+)\.([0-9]+)\. ]]; then
        err "could not parse Ollama version: $OLLAMA_VERSION"
        exit 1
    fi
    MAJOR="${BASH_REMATCH[1]}"; MINOR="${BASH_REMATCH[2]}"
    if (( MAJOR == 0 && MINOR < 14 )); then
        err "Ollama $OLLAMA_VERSION lacks /v1/messages — need 0.14.0+. brew upgrade ollama"
        exit 1
    fi
    ok "Ollama version supports Anthropic /v1/messages"

    # 1c. Model pulled?
    if ! ollama list | awk 'NR>1 {print $1}' | grep -qxF "$QWEN_MODEL"; then
        err "Ollama model '$QWEN_MODEL' not pulled. Run: ollama pull $QWEN_MODEL"
        exit 1
    fi
    ok "Model $QWEN_MODEL is pulled"

    # 1d. Endpoint serves the model with Anthropic shape?
    TMP_RESP=$(mktemp)
    HTTP=$(curl -sS -o "$TMP_RESP" -w '%{http_code}' --max-time 60 -X POST \
        http://localhost:11434/v1/messages \
        -H "Content-Type: application/json" \
        -H "anthropic-version: 2023-06-01" \
        -d "{\"model\":\"$QWEN_MODEL\",\"max_tokens\":50,
             \"messages\":[{\"role\":\"user\",\"content\":\"Reply: OK\"}]}" || echo "000")
    if [[ "$HTTP" != "200" ]]; then
        err "Ollama /v1/messages returned HTTP $HTTP. Response:"
        cat "$TMP_RESP" >&2 || true
        rm -f "$TMP_RESP"
        exit 1
    fi
    if ! grep -q '"type":"message"' "$TMP_RESP"; then
        err "Ollama response not Anthropic-shaped:"
        cat "$TMP_RESP" >&2
        rm -f "$TMP_RESP"
        exit 1
    fi
    rm -f "$TMP_RESP"
    ok "Ollama serves Anthropic-shaped responses for $QWEN_MODEL"

    # 1e. claude CLI present?
    if ! command -v claude > /dev/null; then
        err "claude CLI not on PATH. Install Claude Code first."
        exit 1
    fi
    ok "Claude Code: $(claude --version)"

    # 1f. Polyglot dataset cached?
    if ! find benchmarks/.cache/polyglot -name "*.md" -print -quit 2>/dev/null | grep -q .; then
        note "Polyglot dataset not cached; fetching (one-time, ~clones upstream)…"
        python3 -m benchmarks.adapters.aider_polyglot.fetch
    fi
    ok "Polyglot dataset cached"

    # 1g. Harness wiring sane?
    if ! ./scripts/benchmark list > /tmp/cct-bench-list.json; then
        err "./scripts/benchmark list failed; harness setup is broken"
        exit 1
    fi
    if ! grep -q '"aider-polyglot"' /tmp/cct-bench-list.json; then
        err "aider-polyglot adapter missing from registry"
        exit 1
    fi
    if ! grep -q '"claude-code"' /tmp/cct-bench-list.json; then
        err "claude-code backend missing from registry"
        exit 1
    fi
    ok "Harness reports adapters/backends correctly"
fi

# --- Stage 2: Smoke ---
if [[ "$SKIP_SMOKE" == "1" ]]; then
    note "Skipping smoke (SKIP_SMOKE=1)"
else
    gate "Stage 2/3 — smoke: 1 Polyglot Python task against $QWEN_MODEL only (~5-10 min, no Anthropic spend)"
    note "Running smoke…"

    SMOKE_OUTPUT=$(mktemp)
    if ANTHROPIC_BASE_URL=http://localhost:11434 \
       ANTHROPIC_AUTH_TOKEN=ollama \
       ANTHROPIC_DEFAULT_SONNET_MODEL="$QWEN_MODEL" \
       ANTHROPIC_DEFAULT_HAIKU_MODEL="$QWEN_MODEL" \
       ./scripts/benchmark run --benchmark aider-polyglot \
           --backend claude-code --model "$QWEN_MODEL" \
           --task python/leap --runs 1 \
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
gate "Stage 3/3 — full compare: sonnet vs $QWEN_MODEL on '$COMPARE_TASKS' at --runs $COMPARE_RUNS (~15-30 min; sonnet WILL bill Anthropic)"

# Render the compare config (comma-separated tasks → JSON array).
TASKS_JSON=$(printf '"%s"' "$COMPARE_TASKS" | sed 's/,/","/g')
COMPARE_CONFIG=$(mktemp -t compare-sonnet-vs-qwen.XXXXXX.json)
cat > "$COMPARE_CONFIG" <<EOF
{
  "benchmark": "aider-polyglot",
  "runs": $COMPARE_RUNS,
  "task": [$TASKS_JSON],
  "candidates": [
    {
      "name": "sonnet-anthropic",
      "backend": "claude-code",
      "model": "sonnet"
    },
    {
      "name": "qwen3.6-ollama",
      "backend": "claude-code",
      "model": "$QWEN_MODEL",
      "env": {
        "ANTHROPIC_BASE_URL": "http://localhost:11434",
        "ANTHROPIC_AUTH_TOKEN": "ollama",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "$QWEN_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "$QWEN_MODEL"
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
