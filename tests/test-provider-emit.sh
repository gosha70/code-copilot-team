#!/usr/bin/env bash
set -uo pipefail

# test-provider-emit.sh — golden tests for the provider-config translator
# (provider-config Phase 2, T2.1). Runs provider-emit.sh for each (copilot,
# sample-provider) pair and snapshot-asserts the output against a committed
# golden file, plus JSON validity for the GUI copilots and error-path checks.

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EMIT="$REPO_DIR/shared/scripts/provider-emit.sh"
FIX="$REPO_DIR/tests/fixtures/provider-emit"
PROFILE="$FIX/sample-providers.toml"
GOLDEN="$FIX/golden"

COPILOTS="claude-code aider codex github-copilot cursor windsurf pi"
PROVIDERS="gdx local-ollama"

PASS=0
FAIL=0
assert() { if eval "$2"; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi; }

echo "=== provider-emit golden tests (T2.1) ==="

# Golden snapshot for every (copilot, provider) pair.
for cop in $COPILOTS; do
  for prov in $PROVIDERS; do
    out="$(bash "$EMIT" "$cop" "$prov" --profile-file "$PROFILE" 2>/dev/null)"
    g="$GOLDEN/${cop}__${prov}.txt"
    assert "$cop / $prov matches golden" "[[ \"\$out\" == \"\$(cat '$g')\" ]]"
  done
done

# GUI copilots must emit valid JSON.
for cop in cursor windsurf; do
  out="$(bash "$EMIT" "$cop" gdx --profile-file "$PROFILE" 2>/dev/null)"
  assert "$cop output is valid JSON" \
    "echo \"\$out\" | python3 -c 'import json,sys; json.load(sys.stdin)'"
done

# Auth VALUES never appear — only the env-var name / reference.
ALL="$(for c in $COPILOTS; do for p in $PROVIDERS; do bash "$EMIT" "$c" "$p" --profile-file "$PROFILE" 2>/dev/null; done; done)"
assert "no literal auth value leaks (only env-var names)" \
  "! echo \"\$ALL\" | grep -qiE 'sk-|secret-value|password'"

# Error paths.
bash "$EMIT" claude-code no-such-provider --profile-file "$PROFILE" >/dev/null 2>&1
assert "unknown provider -> exit 2" "[[ \$? -eq 2 ]]"
bash "$EMIT" not-a-copilot gdx --profile-file "$PROFILE" >/dev/null 2>&1
assert "unknown copilot -> exit 2" "[[ \$? -eq 2 ]]"
bash "$EMIT" claude-code gdx --profile-file /nonexistent.toml >/dev/null 2>&1
assert "missing profile file -> exit 2" "[[ \$? -eq 2 ]]"

echo ""
echo "========================================="
echo "  provider-emit golden tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
