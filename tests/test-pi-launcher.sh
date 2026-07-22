#!/usr/bin/env bash

# test-pi-launcher.sh — Tests for the pi-code launcher contract
#
# Covers (specs/pi-harness-adoption FR-000/FR-002):
#   - upstream pi resolution + version validation (>= 0.79.0)
#   - argument forwarding (unknown flags and everything after --)
#   - --no-cct starts plain pi (no runtime, no CCT_RUNTIME marker)
#   - enforced launch loads runtime via --extension with CCT_RUNTIME=1
#   - recursion guard (CCT_PI_CODE_ACTIVE)
#   - exit-code preservation
#
# Uses a fake `pi` shim; no real Pi installation required.
#
# Run from the repo root:
#   bash tests/test-pi-launcher.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCHER="$REPO_DIR/adapters/pi/bin/pi-code"

PASS=0
FAIL=0

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"; FAIL=$((FAIL + 1))
  fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# ── Fake pi shim: records argv + relevant env, honors --version ─────
make_shim() {
  local dir="$1" version="$2"
  mkdir -p "$dir"
  cat > "$dir/pi" <<SHIM
#!/usr/bin/env bash
if [[ "\${1:-}" == "--version" ]]; then echo "$version"; exit 0; fi
{
  echo "ARGS:\$*"
  echo "CCT_RUNTIME:\${CCT_RUNTIME:-unset}"
  echo "CCT_PI_CODE_ACTIVE:\${CCT_PI_CODE_ACTIVE:-unset}"
  echo "CCT_PROFILE:\${CCT_PROFILE:-unset}"
} > "$TMP/capture.txt"
exit \${PI_SHIM_EXIT:-0}
SHIM
  chmod +x "$dir/pi"
}

make_shim "$TMP/bin-new" "0.80.2"
make_shim "$TMP/bin-old" "0.50.0"
BASE_PATH="/usr/bin:/bin"

echo "=== pi-code launcher tests ==="

# ── version / doctor without pi ─────────────────────────────
echo "--- diagnostics ---"
OUT=$(PATH="$BASE_PATH" "$LAUNCHER" version)
assert "version works without pi on PATH" "echo \"\$OUT\" | grep -q 'pi-code'"
assert "version reports minimum pi" "echo \"\$OUT\" | grep -q '0.79.0'"
if PATH="$BASE_PATH" "$LAUNCHER" doctor > "$TMP/doctor.txt" 2>&1; then
  assert "doctor fails without pi" "false"
else
  assert "doctor fails without pi" "true"
fi
assert "doctor names the missing pi" "grep -q 'upstream pi not found' '$TMP/doctor.txt'"

# ── enforced launch ─────────────────────────────────────────
echo "--- enforced launch ---"
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --profile review-heavy -- --model test/model > /dev/null 2>&1 || true
assert "runtime loaded via --extension" "grep -q -- '--extension' '$TMP/capture.txt'"
assert "runtime entry is runtime/index.ts" "grep -q 'runtime/index.ts' '$TMP/capture.txt'"
assert "CCT_RUNTIME=1 set on enforced launch" "grep -q 'CCT_RUNTIME:1' '$TMP/capture.txt'"
assert "recursion marker set" "grep -q 'CCT_PI_CODE_ACTIVE:1' '$TMP/capture.txt'"
assert "profile forwarded to runtime env" "grep -q 'CCT_PROFILE:review-heavy' '$TMP/capture.txt'"
assert "native args after -- forwarded unmodified" "grep -q -- '--model test/model' '$TMP/capture.txt'"

# Unknown flags forward to pi
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --thinking high > /dev/null 2>&1 || true
assert "unknown flag forwarded to pi" "grep -q -- '--thinking high' '$TMP/capture.txt'"

# ── --no-cct ────────────────────────────────────────────────
echo "--- --no-cct ---"
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --no-cct -- -p "hello" > /dev/null 2>&1 || true
assert "--no-cct: no runtime extension" "! grep -q -- '--extension' '$TMP/capture.txt'"
assert "--no-cct: CCT_RUNTIME unset" "grep -q 'CCT_RUNTIME:unset' '$TMP/capture.txt'"
assert "--no-cct: args still forwarded" "grep -q -- '-p hello' '$TMP/capture.txt'"
NOCCT_WARN=$(PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --no-cct 2>&1 >/dev/null || true)
assert "--no-cct visibly reported as unenforced" "echo \"\$NOCCT_WARN\" | grep -qi 'UNENFORCED'"

# ── version gate ────────────────────────────────────────────
echo "--- version gate ---"
if PATH="$TMP/bin-old:$BASE_PATH" "$LAUNCHER" > /dev/null 2>&1; then
  assert "pi older than 0.79.0 rejected" "false"
else
  RC=$?
  assert "pi older than 0.79.0 rejected" "true"
fi
PATH="$TMP/bin-old:$BASE_PATH" "$LAUNCHER" > /dev/null 2>&1 || RC=$?
assert "old-pi rejection uses exit 65" "[[ '${RC:-0}' == '65' ]]"

# ── recursion guard ─────────────────────────────────────────
echo "--- recursion guard ---"
if CCT_PI_CODE_ACTIVE=1 PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" > /dev/null 2>&1; then
  assert "recursive invocation blocked" "false"
else
  RC=$?
  assert "recursive invocation blocked" "true"
fi
assert "recursion block uses exit 64" "[[ '${RC:-0}' == '64' ]]"
OUT=$(CCT_PI_CODE_ACTIVE=1 PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" version)
assert "diagnostic commands allowed under recursion guard" "echo \"\$OUT\" | grep -q 'pi-code'"

# ── no passthrough args ─────────────────────────────────────
# bash 3.2 (macOS /bin/bash) errors on "${a[@]}" for an empty array under
# `set -u`, which broke the default launch path with no extra arguments.
echo "--- no passthrough args ---"
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" > /dev/null 2>&1 || true
assert "enforced launch execs pi with no args" "grep -q 'CCT_RUNTIME:1' '$TMP/capture.txt'"
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --no-cct > /dev/null 2>&1 || true
assert "--no-cct execs pi with no args" "grep -q 'CCT_RUNTIME:unset' '$TMP/capture.txt'"

# ── exit-code preservation ──────────────────────────────────
echo "--- exit codes ---"
if PI_SHIM_EXIT=7 PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --no-cct > /dev/null 2>&1; then
  RC=0
else
  RC=$?
fi
assert "pi exit code preserved through exec" "[[ '$RC' == '7' ]]"

# ── Diagnostic subcommands (T1.6) ───────────────────────────
echo "--- diagnostics ---"
# The diagnostic subcommands shell out to node; BASE_PATH deliberately does
# not contain it, so add its real location for these cases only.
NODE_DIR="$(dirname "$(command -v node 2>/dev/null || echo /usr/bin/node)")"
DIAG_PATH="$TMP/bin-new:$NODE_DIR:$BASE_PATH"

for cmd in features config; do
  OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" "$cmd" 2>&1 || true)
  assert "$cmd produces output" "[[ -n \"\$OUT\" ]]"
done

OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" features 2>&1 || true)
assert "features reports capability status" "echo \"\$OUT\" | grep -q 'enabled'"
assert "features reports implementation kind" "echo \"\$OUT\" | grep -q 'cct-first-party'"

OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" config 2>&1 || true)
assert "config reports resolved keys" "echo \"\$OUT\" | grep -q 'security.fail_closed'"
# Diagnostics must never imply project config was trusted (C-3).
assert "config states the untrusted resolution" "echo \"\$OUT\" | grep -q 'UNTRUSTED'"

OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" config explain security.fail_closed 2>&1 || true)
assert "explain shows the setting layer" "echo \"\$OUT\" | grep -q 'set by:'"

RC=0
PATH="$DIAG_PATH" "$LAUNCHER" config explain no.such.key > /dev/null 2>&1 || RC=$?
assert "explain exits 1 for an unknown key" "[[ '$RC' == '1' ]]"

for cmd in features doctor config; do
  OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" "$cmd" --json 2>&1 || true)
  assert "$cmd --json emits valid JSON" \
    "echo \"\$OUT\" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null"
done

# Diagnostics stay usable inside a session; only launches recurse.
OUT=$(CCT_PI_CODE_ACTIVE=1 PATH="$DIAG_PATH" "$LAUNCHER" features 2>&1 || true)
assert "recursion guard permits diagnostics" "echo \"\$OUT\" | grep -q 'capabilities'"

assert "help documents the diagnostic commands" \
  "PATH=\"\$DIAG_PATH\" '$LAUNCHER' help | grep -q 'config explain'"

# ── Redacted export (T1.8) ──────────────────────────────────
echo "--- export ---"
EXP_HOME="$TMP/exp-home"
mkdir -p "$EXP_HOME"
printf 'config_version = 2\n[security]\nfail_closed = true\n[providers]\napi_key = "sk-export-secret"\n' > "$EXP_HOME/config.toml"

EXP=$(CCT_HOME="$EXP_HOME" PATH="$DIAG_PATH" "$LAUNCHER" export 2>&1 || true)
assert "export marks output as redacted" "echo \"\$EXP\" | grep -q 'redacted'"
assert "export never emits the raw secret" "! echo \"\$EXP\" | grep -q 'sk-export-secret'"
assert "export includes a resolved key" "echo \"\$EXP\" | grep -q 'security.fail_closed'"

# The exported TOML must re-parse — it claims to be a portable artifact.
echo "$EXP" > "$TMP/exported.toml"
assert "exported TOML re-parses through the loader" \
  "CCT_CFG='$TMP/exported.toml' node --experimental-strip-types --input-type=module -e 'import fs from \"node:fs\"; import { parseToml } from \"$REPO_DIR/adapters/pi/runtime/config/toml.ts\"; const t = parseToml(fs.readFileSync(process.env.CCT_CFG, \"utf8\")); process.exit(t.security && t.security.fail_closed === true ? 0 : 1);' 2>/dev/null"

EXPJ=$(CCT_HOME="$EXP_HOME" PATH="$DIAG_PATH" "$LAUNCHER" export --json 2>&1 || true)
assert "export --json never emits the raw secret" "! echo \"\$EXPJ\" | grep -q 'sk-export-secret'"
assert "export --json is valid JSON with redacted flag" \
  "echo \"\$EXPJ\" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get(\"redacted\") is True else 1)'"

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  pi-code launcher tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
