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
    assert_ok "litellm.proxy.proxy_server imports (proxy can start)" "$?"

    V=$("$VENV/bin/litellm" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    PINNED=$(grep -E '^litellm' "$REQ" | cut -d= -f3)
    assert_eq "the installed litellm matches the pin" "$PINNED" "$V"
    rm -rf "$VENV"
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
