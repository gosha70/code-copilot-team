#!/usr/bin/env bash
# test-litellm-proxy-deps.sh — the benchmark's LiteLLM proxy dependencies
# must be pinned, and the pinned set must actually start the proxy (#220).
#
# Default run is OFFLINE and fast: it asserts the pins exist, are exact, and
# are wired into the benchmark. CI and the daily suite run this.
#
#   bash tests/test-litellm-proxy-deps.sh            # offline contract checks
#   bash tests/test-litellm-proxy-deps.sh --online   # + provision a real venv
#
# --online is the acceptance test from #220: a clean ephemeral environment
# installs the pins, `pip check` is clean, and the module whose import used to
# crash the proxy imports. It reaches PyPI and takes a few minutes, so it is
# opt-in rather than part of every run.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REQ="$REPO_DIR/scripts/requirements-litellm-proxy.txt"
BENCH="$REPO_DIR/scripts/run-compare-anthropic-vs-vllm.sh"
ONLINE=0
[[ "${1:-}" == "--online" ]] && ONLINE=1

PASS=0; FAIL=0
assert_eq() {
    if [[ "$2" == "$3" ]]; then echo "  PASS: $1"; PASS=$((PASS + 1))
    else echo "  FAIL: $1 (expected '$2', got '$3')"; FAIL=$((FAIL + 1)); fi
}
assert_ok() {
    if [[ "$2" -eq 0 ]]; then echo "  PASS: $1"; PASS=$((PASS + 1))
    else echo "  FAIL: $1"; FAIL=$((FAIL + 1)); fi
}

echo "=== Pinned proxy dependencies (#220) ==="

rc=0; [[ -f "$REQ" ]] || rc=1
assert_ok "requirements-litellm-proxy.txt exists" "$rc"

# Every requirement must be an EXACT pin. A range is what caused the outage:
# litellm's own `fastapi<1.0,>=0.136.3` let pip pick 0.141.1, which dropped a
# symbol litellm imports at module scope.
UNPINNED=$(grep -vE '^[[:space:]]*(#|$)' "$REQ" 2>/dev/null | grep -vcE '==' || true)
assert_eq "every requirement is an exact == pin" "0" "$UNPINNED"

for pkg in litellm fastapi; do
    rc=0; grep -qE "^${pkg}(\[[a-z,]+\])?==" "$REQ" 2>/dev/null || rc=1
    assert_ok "$pkg is pinned" "$rc"
done

# fastapi must be pinned BELOW the release that removed get_flat_dependant.
FA=$(grep -E '^fastapi==' "$REQ" 2>/dev/null | cut -d= -f3)
rc=0; [[ -n "$FA" ]] && [[ "$(printf '%s\n0.141.0\n' "$FA" | sort -V | head -1)" == "$FA" ]] || rc=1
assert_ok "fastapi pin ($FA) predates the get_flat_dependant removal" "$rc"

# The benchmark must USE the pins, and must not carry an unpinned install.
rc=0; grep -q 'requirements-litellm-proxy.txt' "$BENCH" 2>/dev/null || rc=1
assert_ok "the benchmark installs from the pins file" "$rc"
LOOSE=$(grep -cE "setup_venv +'litellm\[proxy\]>=" "$BENCH" 2>/dev/null || true)
assert_eq "no unpinned litellm install remains" "0" "$LOOSE"

# A failure must report what was actually installed.
rc=0; grep -q 'proxy_dep_versions' "$BENCH" 2>/dev/null || rc=1
assert_ok "failures report resolved litellm/fastapi/python versions" "$rc"
for f in 'pip show litellm' 'pip show fastapi' 'import sys; print(sys.version'; do
    rc=0; grep -qF "$f" "$BENCH" 2>/dev/null || rc=1
    assert_ok "diagnostics include: $f" "$rc"
done

# A conflicting resolution must fail at provisioning, where the message names
# the packages — not later as an ImportError inside the proxy.
rc=0; grep -q 'pip check' "$BENCH" 2>/dev/null || rc=1
assert_ok "the venv runs pip check before proceeding" "$rc"

# The ephemeral venv is still removed automatically.
rc=0; grep -q 'cleanup_venv' "$BENCH" 2>/dev/null || rc=1
assert_ok "the ephemeral venv is still auto-removed" "$rc"

if [[ "$ONLINE" -eq 1 ]]; then
    echo ""
    echo "=== --online: clean-environment acceptance test (#220) ==="
    # Cleanup is registered BEFORE anything is created, and covers every exit
    # path — a SIGINT during the multi-minute install, or an assertion that
    # fails midway, must not leave a listener on a port or a venv on disk.
    PROXY_PID=""; PROXY_CFG=""; PROXY_LOG=""; VENV=""
    # Reaping the proxy and removing the venv are separate concerns: the test
    # tears the proxy down mid-run and then keeps using the venv.
    proxy_selftest_kill() {
        if [[ -n "$PROXY_PID" ]] && kill -0 "$PROXY_PID" 2>/dev/null; then
            kill "$PROXY_PID" 2>/dev/null
            for _ in 1 2 3 4 5 6 7 8 9 10; do
                kill -0 "$PROXY_PID" 2>/dev/null || break
                sleep 0.5
            done
            # SIGTERM is a request; a proxy that ignores it still has to go.
            kill -0 "$PROXY_PID" 2>/dev/null && kill -9 "$PROXY_PID" 2>/dev/null
        fi
        [[ -n "$PROXY_CFG" ]] && rm -f "$PROXY_CFG"
        [[ -n "$PROXY_LOG" ]] && rm -f "$PROXY_LOG"
        return 0
    }
    proxy_selftest_cleanup() {
        proxy_selftest_kill
        [[ -n "$VENV" && -d "$VENV" ]] && rm -rf "$VENV"
        return 0
    }
    # Cleanup runs on EXIT; the signal handlers must EXIT, not merely clean.
    # A handler that returns 0 lets bash resume the script after the signal —
    # so a SIGINT could run cleanup and then carry on with a deleted venv, or
    # re-create the very resources it just removed. Exiting with the
    # conventional status also makes the run's disposition honest (130/143),
    # and the EXIT trap still does the reaping.
    trap proxy_selftest_cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    VENV=$(mktemp -d -t cct-proxydeps-XXXXXX)
    python3 -m venv "$VENV" >/dev/null 2>&1
    "$VENV/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1
    echo "  (installing the pinned set — a few minutes)"
    "$VENV/bin/python" -m pip install --quiet --requirement "$REQ" >/dev/null 2>&1
    assert_ok "the pinned set installs in a clean venv" "$?"

    "$VENV/bin/python" -m pip check >/dev/null 2>&1
    assert_ok "pip check reports no conflicts" "$?"

    "$VENV/bin/python" -c 'from fastapi.dependencies.utils import get_flat_dependant' >/dev/null 2>&1
    assert_ok "get_flat_dependant imports (the reported ImportError)" "$?"

    "$VENV/bin/python" -c 'from litellm.proxy import proxy_server' >/dev/null 2>&1
    assert_ok "litellm.proxy.proxy_server imports (the secondary ModuleNotFoundError)" "$?"

    # An import-compatible dependency set can still die during application
    # startup, so the import above is NOT the acceptance test. Start the
    # PRODUCTION helper (benchmark_runner.proxy — the same one the benchmark
    # uses), on an ephemeral port, and require it to become healthy. The
    # helper polls /v1/models itself, which LiteLLM serves from its own
    # config, so no upstream vLLM is needed.
    # Let the OS pick a free port rather than guessing inside a fixed range —
    # a "random" port from a fixed window still collides, and a collision here
    # looks like a proxy failure.
    PROXY_PORT=$("$VENV/bin/python" -c "
import socket
s = socket.socket()
s.bind(('127.0.0.1', 0))
print(s.getsockname()[1])
s.close()
")
    PROXY_OUT=$(PATH="$VENV/bin:$PATH" PYTHONPATH="$REPO_DIR/scripts:$REPO_DIR" \
        "$VENV/bin/python" -m benchmark_runner.proxy start \
        --vllm-base http://127.0.0.1:9 --model cct-selftest-model --port "$PROXY_PORT" 2>&1)
    PROXY_PID=$(printf '%s\n' "$PROXY_OUT" | grep '^pid=' | cut -d= -f2-)
    PROXY_CFG=$(printf '%s\n' "$PROXY_OUT" | grep '^config=' | cut -d= -f2-)
    PROXY_LOG=$(printf '%s\n' "$PROXY_OUT" | grep '^log=' | cut -d= -f2-)
    rc=0; [[ -n "$PROXY_PID" ]] || rc=1
    assert_ok "the production proxy helper starts and reports a pid" "$rc"

    rc=0; kill -0 "$PROXY_PID" 2>/dev/null || rc=1
    assert_ok "the proxy process survives startup" "$rc"

    MODELS=$(curl -s -m 10 "http://127.0.0.1:$PROXY_PORT/v1/models" 2>/dev/null)
    rc=0; printf '%s' "$MODELS" | grep -q 'cct-selftest-model' || rc=1
    assert_ok "the proxy answers /v1/models with its configured model" "$rc"

    # Teardown must actually reap it — a leaked proxy holding the port breaks
    # the next run's preflight. Same escalation the trap uses; the venv stays
    # because the pin assertion below still needs it.
    proxy_selftest_kill
    rc=0; kill -0 "$PROXY_PID" 2>/dev/null && rc=1
    assert_ok "the proxy process is gone after teardown" "$rc"

    # The parent PID disappearing is not the same as the PORT being free: a
    # surviving child or a lingering socket would still break the next run.
    LISTENER=$("$VENV/bin/python" -c "
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('127.0.0.1', $PROXY_PORT))
    print('open')
except OSError:
    print('closed')
finally:
    s.close()
" 2>/dev/null || echo closed)
    assert_eq "the listener is gone (port actually free)" "closed" "$LISTENER"

    rc=0; { [[ -n "$PROXY_CFG" && -e "$PROXY_CFG" ]] || [[ -n "$PROXY_LOG" && -e "$PROXY_LOG" ]]; } && rc=1
    assert_ok "the proxy's config and log tempfiles are removed" "$rc"
    PROXY_PID=""

    V=$("$VENV/bin/litellm" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    PINNED=$(grep -E '^litellm' "$REQ" | cut -d= -f3)
    assert_eq "the installed litellm matches the pin" "$PINNED" "$V"
    # $VENV is removed by proxy_selftest_cleanup on EXIT.
else
    echo ""
    echo "  (skipping the clean-venv acceptance test — rerun with --online)"
fi

echo ""
echo "========================================="
printf "  litellm-proxy-deps tests: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ "$FAIL" -eq 0 ]] || exit 1
exit 0
