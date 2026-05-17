#!/usr/bin/env bash
# scripts/run-compare-anthropic-vs-ollama.sh
#
# Automated 2-LLM benchmark: Claude Code → <anthropic-model> (Anthropic API)
# vs. Claude Code → <ollama-model> (local Ollama), on Aider Polyglot.
#
# Usage:
#   ./scripts/run-compare-anthropic-vs-ollama.sh [ANTHROPIC_MODEL] [OLLAMA_MODEL]
#
# Examples:
#   ./scripts/run-compare-anthropic-vs-ollama.sh
#       # defaults: sonnet vs qwen3.6:27b
#   ./scripts/run-compare-anthropic-vs-ollama.sh opus qwen3.6:27b
#   ./scripts/run-compare-anthropic-vs-ollama.sh sonnet llama3.1:70b
#   ./scripts/run-compare-anthropic-vs-ollama.sh haiku qwen3-coder:30b
#
# ENVIRONMENT (no setup step, no flags): every run creates a throwaway
# Python venv and DELETES it on exit — even on failure or Ctrl-C —
# isolating python3 from your system/Homebrew Python. The Ollama path
# needs no third-party libs (the harness is pure stdlib), so nothing is
# pip-installed; the venv is purely isolation. The venv plus every
# scratch temp file (preflight dumps, smoke/compare stdout captures)
# are removed on exit. Two things are deliberately KEPT: the benchmark
# results under runs/, and the compare-config tmp file — its path is
# printed at the end so the compare is re-runnable.
#
# Stages (gated; press Enter to continue, Ctrl-C to abort):
#   1. Preflight checks — ephemeral venv provisioned + Ollama running
#      + version + Ollama model pulled + endpoint shape + claude CLI
#      + Polyglot dataset cached + harness sanity.
#   2. Harness smoke — one Polyglot task against the Ollama model
#      only (~5-10 min, no Anthropic spend). Confirms env-routing
#      reaches Ollama end-to-end through the harness.
#   3. Full compare — Anthropic vs Ollama on configured tasks at
#      --runs N (~15-30 min default; the Anthropic-side runs DO bill
#      the Anthropic account).
#
# Positional args:
#   $1  Anthropic model id      default: sonnet
#   $2  Ollama model tag         default: qwen3.6:27b
#
# Env-var knobs (all optional, orthogonal to positional args):
#   COMPARE_TASKS    default: python/bowling  (comma-separated for multi-task).
#                    Must be task ids the Polyglot adapter actually exposes —
#                    inspect with: ./scripts/benchmark list --benchmark aider-polyglot
#   SMOKE_TASK       default: first task in COMPARE_TASKS.
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

set -euo pipefail

# --- Help ---
case "${1:-}" in
    -h|--help)
        sed -n '2,56p' "$0" | sed -E 's/^# ?//'
        exit 0
        ;;
esac

# --- Positional args + env-var defaults ---
ANTHROPIC_MODEL="${1:-sonnet}"
OLLAMA_MODEL="${2:-qwen3.6:27b}"

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
    printf '\n=== Anthropic vs Ollama compare ===\n'
    printf '  Anthropic model: %s\n' "$ANTHROPIC_MODEL"
    printf '  Ollama model:    %s\n' "$OLLAMA_MODEL"
    printf '  Tasks:           %s\n' "$COMPARE_TASKS"
    printf '  Runs/candidate:  %s\n' "$COMPARE_RUNS"
    printf '  Smoke task:      %s\n' "$SMOKE_TASK"
    printf '\n'
}

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

# --- Ephemeral virtualenv (auto-provisioned, auto-removed) ---
# A throwaway venv that isolates python3 from the user's Python
# (Homebrew is PEP-668 externally-managed). rm -rf'd on exit by the
# trap below. No flag, no manual setup. The Ollama path has no
# third-party deps, so no pip install runs.
VENV_DIR=""
cleanup_venv() {
    [[ -n "$VENV_DIR" && -d "$VENV_DIR" ]] && rm -rf "$VENV_DIR" || true
}

# Per-run unique preflight scratch files (mktemp ⇒ no clobber across
# concurrent runs); removed by the trap.
OLLAMA_VERSION_JSON="$(mktemp -t cct-ollama-version.XXXXXX.json)"
BENCH_LIST_JSON="$(mktemp -t cct-bench-list.XXXXXX.json)"
# Per-stage scratch captures, assigned later. Declared empty here so
# cleanup() can reference them under `set -u` even on an early exit,
# and so a signal abort mid-stage does not leak them. COMPARE_CONFIG is
# intentionally NOT tracked — it is kept and printed for re-runs.
TMP_RESP=""
SMOKE_OUTPUT=""
COMPARE_OUTPUT=""

# Idempotent (every step guarded) — safe to run from both the signal
# trap and the EXIT trap.
cleanup() {
    rm -f "$OLLAMA_VERSION_JSON" "$BENCH_LIST_JSON" \
          "$TMP_RESP" "$SMOKE_OUTPUT" "$COMPARE_OUTPUT" 2>/dev/null || true
    cleanup_venv
}
# A bare `trap … EXIT` does NOT run on SIGINT/SIGTERM/SIGHUP in bash —
# only on normal exit or `exit N`. Trap the signals explicitly so an
# aborted run (Ctrl-C at a gate, kill) still tears the env down. cleanup
# is idempotent, so the signal+EXIT double-fire is harmless. SIGKILL
# alone cannot be trapped — the only uncleaned path.
on_signal() { cleanup; exit 130; }
trap cleanup EXIT
trap on_signal INT TERM HUP

setup_venv() {
    # Args: pip requirement specs (none for the Ollama path).
    local pip_pkgs=("$@")
    VENV_DIR="$(mktemp -d -t cct-venv-XXXXXX)"
    note "Creating ephemeral venv at $VENV_DIR (auto-removed on exit)"
    if ! python3 -m venv "$VENV_DIR"; then
        err "python3 -m venv failed — cannot provision the test env"
        exit 1
    fi
    export PATH="$VENV_DIR/bin:$PATH"
    export VIRTUAL_ENV="$VENV_DIR"
    # No PyPI contact unless there is actually something to install —
    # the Ollama path is pure stdlib and must not gain a network
    # failure mode ahead of its own preflight.
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

# --- Print parsed config ---
note_intro

# --- Provision the ephemeral test env (needed by all stages) ---
setup_venv

# --- Stage 1: Preflight ---
if [[ "$SKIP_PREFLIGHT" == "1" ]]; then
    note "Skipping preflight (SKIP_PREFLIGHT=1)"
else
    note "Stage 1/3 — preflight checks"

    # 1a. Ollama reachable?
    if ! curl -sS --max-time 3 http://localhost:11434/api/version > "$OLLAMA_VERSION_JSON"; then
        err "Ollama not reachable at http://localhost:11434. Start it: ollama serve"
        exit 1
    fi
    OLLAMA_VERSION=$(grep -oE '"version":"[^"]+"' "$OLLAMA_VERSION_JSON" | cut -d'"' -f4)
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
    if ! ollama list | awk 'NR>1 {print $1}' | grep -qxF "$OLLAMA_MODEL"; then
        err "Ollama model '$OLLAMA_MODEL' not pulled. Run: ollama pull $OLLAMA_MODEL"
        exit 1
    fi
    ok "Model $OLLAMA_MODEL is pulled"

    # 1d. Endpoint serves the model with Anthropic shape?
    # --max-time 300: a cold-load of a 17–24 GB model from disk to GPU
    # can take 30–90s on Apple Silicon; longer on slower storage. 60s
    # was too aggressive — bumped 2026-05-15 after a real run hit it.
    # If the model has been recently unloaded (`ollama ps` UNTIL ticked
    # down to "Stopping..."), the first /v1/messages call has to pay
    # the load latency.
    TMP_RESP=$(mktemp)
    HTTP=$(curl -sS -o "$TMP_RESP" -w '%{http_code}' --max-time 300 -X POST \
        http://localhost:11434/v1/messages \
        -H "Content-Type: application/json" \
        -H "anthropic-version: 2023-06-01" \
        -d "{\"model\":\"$OLLAMA_MODEL\",\"max_tokens\":50,
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
    ok "Ollama serves Anthropic-shaped responses for $OLLAMA_MODEL"

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

# --- Stage 2: Smoke ---
if [[ "$SKIP_SMOKE" == "1" ]]; then
    note "Skipping smoke (SKIP_SMOKE=1)"
else
    gate "Stage 2/3 — smoke: Polyglot task '$SMOKE_TASK' against $OLLAMA_MODEL only (~5-10 min, no Anthropic spend)"
    note "Running smoke against task: $SMOKE_TASK"

    SMOKE_OUTPUT=$(mktemp)
    # Pass the same per-candidate timeout used in stage 3's compare
    # config (default 1800s; OLLAMA_TIMEOUT override propagates here too).
    # Without this, the smoke uses the harness default 600s — which is
    # too tight for slow local models like qwen3.6:27b and produces
    # spurious "smoke failed" signals before the real compare can start.
    # Bug discovered 2026-05-16 after the OLLAMA_TIMEOUT knob was added
    # to the compare-config JSON but not surfaced to the smoke stage.
    if ANTHROPIC_BASE_URL=http://localhost:11434 \
       ANTHROPIC_AUTH_TOKEN=ollama \
       ANTHROPIC_DEFAULT_SONNET_MODEL="$OLLAMA_MODEL" \
       ANTHROPIC_DEFAULT_HAIKU_MODEL="$OLLAMA_MODEL" \
       CCT_CLAUDE_TIMEOUT_SECONDS="${OLLAMA_TIMEOUT:-1800}" \
       ./scripts/benchmark run --benchmark aider-polyglot \
           --backend claude-code --model "$OLLAMA_MODEL" \
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
gate "Stage 3/3 — full compare: $ANTHROPIC_MODEL (Anthropic) vs $OLLAMA_MODEL (Ollama) on '$COMPARE_TASKS' at --runs $COMPARE_RUNS (~15-30 min; the Anthropic side WILL bill your account)"

# Render the compare config (comma-separated tasks → JSON array).
TASKS_JSON=$(printf '"%s"' "$COMPARE_TASKS" | sed 's/,/","/g')
COMPARE_CONFIG=$(mktemp -t compare-anthropic-vs-ollama.XXXXXX.json)
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
      "name": "ollama-$OLLAMA_MODEL",
      "backend": "claude-code",
      "model": "$OLLAMA_MODEL",
      "env": {
        "ANTHROPIC_BASE_URL": "http://localhost:11434",
        "ANTHROPIC_AUTH_TOKEN": "ollama",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "$OLLAMA_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "$OLLAMA_MODEL",
        "CCT_CLAUDE_TIMEOUT_SECONDS": "${OLLAMA_TIMEOUT:-1800}"
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
