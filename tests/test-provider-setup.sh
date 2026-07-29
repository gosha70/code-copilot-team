#!/usr/bin/env bash
set -uo pipefail

# test-provider-setup.sh — adapter --provider wiring (T2.2) + backwards
# compatibility (T2.3). Each adapters/<copilot>/setup.sh must, given --provider,
# produce exactly what provider-emit.sh produces (and for codex, append it
# idempotently); and WITHOUT --provider the provider path must be inert.

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
EMIT="$REPO_DIR/shared/scripts/provider-emit.sh"
PROFILE="$REPO_DIR/tests/fixtures/provider-emit/sample-providers.toml"

PASS=0
FAIL=0
assert() { if eval "$2"; then echo "  PASS: $1"; PASS=$((PASS+1)); else echo "  FAIL: $1"; FAIL=$((FAIL+1)); fi; }

echo "=== provider adapter --provider wiring (T2.2) ==="

# stdout copilots: setup.sh --provider == provider-emit output.
for a in claude-code aider cursor github-copilot windsurf pi; do
  got="$(bash "$REPO_DIR/adapters/$a/setup.sh" --provider gdx --providers-file "$PROFILE" 2>/dev/null)"
  want="$(bash "$EMIT" "$a" gdx --profile-file "$PROFILE" 2>/dev/null)"
  assert "$a --provider emits the translator output" "[[ \"\$got\" == \"\$want\" ]]"
done

# codex: appends to CODEX_HOME/config.toml, idempotently.
TCH="$(mktemp -d)"
CODEX_HOME="$TCH" bash "$REPO_DIR/adapters/codex/setup.sh" --provider gdx --providers-file "$PROFILE" >/dev/null 2>&1
assert "codex --provider appends the block to config.toml" "grep -qE '^\[model_providers\.gdx\]' '$TCH/config.toml'"
CODEX_HOME="$TCH" bash "$REPO_DIR/adapters/codex/setup.sh" --provider gdx --providers-file "$PROFILE" >/dev/null 2>&1
COUNT="$(grep -cE '^\[model_providers\.gdx\]' "$TCH/config.toml")"
assert "codex --provider is idempotent (block appears once)" "[[ '$COUNT' -eq 1 ]]"
rm -r "$TCH"

echo "=== backwards compatibility (T2.3) ==="
# Without --provider, the shared handler is inert: returns non-zero, no output.
source "$REPO_DIR/shared/scripts/provider-setup.sh"
OUT="$(cct_handle_provider_flag aider /some/project --sync 2>&1)"; RC=$?
assert "no --provider -> handler returns non-zero (normal setup proceeds)" "[[ $RC -ne 0 ]]"
assert "no --provider -> handler emits nothing" "[[ -z \"\$OUT\" ]]"

echo ""
echo "========================================="
echo "  provider adapter wiring: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
