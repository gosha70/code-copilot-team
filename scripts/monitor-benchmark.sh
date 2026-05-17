#!/usr/bin/env bash
# scripts/monitor-benchmark.sh — live progress monitor for an in-flight
# benchmark run. Polls every 5s and shows: latest run-dir + most
# recently modified files (proof of progress), ollama ps state, the
# claude-code subprocess's CPU/elapsed time, and GPU active% if
# powermetrics is available without sudo (rare). Ctrl-C to stop.
#
# Run this in a SECOND terminal while
# scripts/run-compare-anthropic-vs-ollama.sh is running in the first.
#
# Heuristic readouts (what "stuck" looks like):
#   - "Latest file age" climbing past ~60s with no other changes
#     → claude-code is idle (between turns, hung, or finished).
#   - "Ollama UNTIL" counting DOWN past 4 min
#     → no inference happening; harness is doing something else
#       (verify, install, or hung).
#   - "claude CPU time" not increasing across two snapshots ~15s apart
#     → claude-code subprocess is sleeping/blocked.
#
# No args. No state mutation. Read-only.

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INTERVAL="${MONITOR_INTERVAL:-5}"

while true; do
    clear
    echo "=== CCT benchmark monitor (refresh every ${INTERVAL}s; Ctrl-C to stop) ==="
    echo "    $(date '+%Y-%m-%d %H:%M:%S')"
    echo

    # --- Latest run-dir ---
    LATEST=$(ls -t "$ROOT/runs/" 2>/dev/null | head -1)
    if [[ -z "$LATEST" ]]; then
        echo "[run-dir] no runs/ entries yet"
    else
        echo "[run-dir] $LATEST"
        echo
        echo "  Most recently modified files (top 6):"
        find "$ROOT/runs/$LATEST" -type f -not -path '*/.venv/*' \
            -exec stat -f '%m %N' {} \; 2>/dev/null \
            | sort -rn \
            | head -6 \
            | while read -r mtime path; do
                age=$(( $(date +%s) - mtime ))
                short=${path#$ROOT/runs/$LATEST/}
                printf '    %5ds ago  %s\n' "$age" "$short"
            done
        echo
        # Score files — green tick if present (run completed).
        SCORES=$(find "$ROOT/runs/$LATEST" -name "score.json" 2>/dev/null | wc -l | tr -d ' ')
        echo "  score.json files written: $SCORES"
    fi
    echo

    # --- Ollama state ---
    echo "[ollama ps]"
    if ! ollama ps 2>&1 | sed 's/^/    /'; then
        echo "    (ollama not reachable)"
    fi
    echo

    # --- Claude-code subprocess ---
    # Match the CLI (~/.local/bin/claude) specifically; exclude the
    # macOS desktop app at /Applications/Claude.app and any other
    # process whose argv happens to contain "claude".
    echo "[claude-code -p subprocess(es)]"
    PS_OUT=$(ps -o pid,etime,time,%cpu,command -ax 2>/dev/null \
        | grep -v '/Applications/Claude.app' \
        | grep -E '\.local/bin/claude.*(-p|--output-format json|--model )' \
        | head -3)
    if [[ -z "$PS_OUT" ]]; then
        echo "    (no claude -p process running)"
    else
        echo "    PID   ELAPSED      CPU-TIME   %CPU  COMMAND"
        echo "$PS_OUT" | awk '{
            pid=$1; etime=$2; cputime=$3; cpu=$4;
            cmd="";
            for (i=5; i<=NF; i++) cmd = cmd " " $i;
            # Truncate cmd to 60 chars for readability.
            if (length(cmd) > 60) cmd = substr(cmd, 1, 57) "...";
            printf "    %-5s %-12s %-10s %-5s %s\n", pid, etime, cputime, cpu, cmd
        }'
    fi
    echo

    # --- Benchmark runner process ---
    BENCH_PS=$(ps -o pid,etime,%cpu,command -ax 2>/dev/null \
        | grep -E '[p]ython.*benchmark_runner|[s]cripts/benchmark' \
        | grep -v 'monitor-benchmark' \
        | head -3)
    if [[ -n "$BENCH_PS" ]]; then
        echo "[benchmark_runner]"
        echo "$BENCH_PS" | awk '{
            pid=$1; etime=$2; cpu=$3;
            cmd="";
            for (i=4; i<=NF; i++) cmd = cmd " " $i;
            if (length(cmd) > 65) cmd = substr(cmd, 1, 62) "...";
            printf "    PID=%-5s elapsed=%-12s cpu=%s%%  %s\n", pid, etime, cpu, cmd
        }'
        echo
    fi

    sleep "$INTERVAL"
done
