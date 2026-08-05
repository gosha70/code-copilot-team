#!/usr/bin/env bash
# test-claude-settings-gen.sh — US2 of unattended-cross-harness-execution.
#
# Proves the Claude settings generator (scripts/generate-claude-settings.sh):
#   - projects the SHARED permission profile Pi imports into settings.json
#     (FR-5), idempotently, preserving unrelated user keys;
#   - sets the non-interactive default and never emits bypassPermissions (FR-6);
#   - records managed keys so a switch-away removes only managed content (FR-7);
#   - stays aligned with the Pi imported posture, including residual-ask
#     semantics — the cross-harness drift guard (FR-8).
#
# Run from the repo root:  bash tests/test-claude-settings-gen.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GEN="$REPO_DIR/scripts/generate-claude-settings.sh"
PERM_DIR="$REPO_DIR/adapters/claude-code/permissions"
PROFILES_TS="$REPO_DIR/adapters/pi/runtime/config/profiles.ts"

PASS=0
FAIL=0
assert() {
  local name="$1" cond="$2"
  if eval "$cond"; then echo "  PASS: $name"; PASS=$((PASS + 1))
  else echo "  FAIL: $name"; FAIL=$((FAIL + 1)); fi
}

command -v jq >/dev/null 2>&1 || { echo "[SKIP] jq not found — generator tests skipped."; exit 0; }

TMP="$(mktemp -d)"
trap 'rm -r "$TMP"' EXIT

echo "=== Claude settings generator (US2) ==="

# ── FR-5: generate + preserve unrelated user keys ───────────
echo "--- generate + preservation ---"
cat > "$TMP/settings.json" <<'JSON'
{ "statusLine": {"type":"command","command":"~/x.sh"},
  "hooks": {"Stop":[{"matcher":"","hooks":[]}]},
  "env": {"USER_KEY":"keep-me"} }
JSON
bash "$GEN" relaxed --settings "$TMP/settings.json" >/dev/null
assert "unrelated statusLine preserved" "[[ \"\$(jq -r '.statusLine.command' "$TMP/settings.json")\" == '~/x.sh' ]]"
assert "unrelated hooks preserved"      "[[ \"\$(jq -r '.hooks.Stop|length' "$TMP/settings.json")\" == '1' ]]"
assert "unrelated user env preserved"   "[[ \"\$(jq -r '.env.USER_KEY' "$TMP/settings.json")\" == 'keep-me' ]]"
assert "permissions block written"      "[[ \"\$(jq -r '.permissions.allow|length' "$TMP/settings.json")\" -gt 0 ]]"

# allow/deny come verbatim from the shared source (FR-5 single source of truth).
assert "allow equals shared profile" \
  "jq -e --slurpfile s '$PERM_DIR/relaxed.json' '.permissions.allow == \$s[0].permissions.allow' "$TMP/settings.json" >/dev/null"
assert "deny equals shared profile" \
  "jq -e --slurpfile s '$PERM_DIR/relaxed.json' '.permissions.deny == \$s[0].permissions.deny' "$TMP/settings.json" >/dev/null"

# ── FR-6: non-interactive default, never bypass ─────────────
echo "--- non-interactive default, no bypass ---"
# The shared profile's default must be a non-prompting mode (the Claude analog of
# Pi's headless ask_resolution=allow): dontAsk or acceptEdits, never default/plan.
assert "generated defaultMode is non-interactive" \
  "printf '%s' \"\$(jq -r '.permissions.defaultMode' "$TMP/settings.json")\" | grep -qxE 'dontAsk|acceptEdits'"
assert "no bypassPermissions anywhere in output" "! grep -q bypassPermissions '$TMP/settings.json'"

# A source demanding bypassPermissions is a hard error.
cat > "$PERM_DIR/_tmp_bypass.json" <<'JSON'
{ "permissions": { "defaultMode": "bypassPermissions", "allow": ["Bash"], "deny": [] } }
JSON
RC=0; bash "$GEN" _tmp_bypass --settings "$TMP/settings.json" >/dev/null 2>&1 || RC=$?
rm -f "$PERM_DIR/_tmp_bypass.json"
assert "bypassPermissions source refused (exit 65)" "[[ '$RC' == '65' ]]"

# ── FR-5: idempotency + FR-7 manifest / managed-key removal ─
echo "--- idempotency + managed-key removal ---"
cp "$TMP/settings.json" "$TMP/first.json"
bash "$GEN" relaxed --settings "$TMP/settings.json" >/dev/null
assert "re-generate is byte-identical (idempotent)" "diff -q '$TMP/first.json' '$TMP/settings.json' >/dev/null"
assert "manifest records the profile" "[[ \"\$(jq -r '.profile' '$TMP/.cct-permissions.json')\" == 'relaxed' ]]"
assert "manifest records permissions as managed" "jq -e '.managedKeys|index(\"permissions\")' '$TMP/.cct-permissions.json' >/dev/null"

# --check is a drift/idempotency guard.
RC=0; bash "$GEN" relaxed --settings "$TMP/settings.json" --check >/dev/null 2>&1 || RC=$?
assert "--check passes when in sync (exit 0)" "[[ '$RC' == '0' ]]"
jq '.permissions.allow += ["Task"]' "$TMP/settings.json" > "$TMP/drift.json" && mv "$TMP/drift.json" "$TMP/settings.json"
RC=0; bash "$GEN" relaxed --settings "$TMP/settings.json" --check >/dev/null 2>&1 || RC=$?
assert "--check fails on a hand-edit drift (exit 1)" "[[ '$RC' == '1' ]]"

# --remove drops only the managed key + manifest; user settings survive.
bash "$GEN" relaxed --settings "$TMP/settings.json" >/dev/null   # re-sync first
bash "$GEN" --remove --settings "$TMP/settings.json" >/dev/null
assert "--remove deletes the managed permissions key" "[[ \"\$(jq -r '.permissions // \"gone\"' "$TMP/settings.json")\" == 'gone' ]]"
assert "--remove preserves unrelated user env"        "[[ \"\$(jq -r '.env.USER_KEY' "$TMP/settings.json")\" == 'keep-me' ]]"
assert "--remove deletes the manifest"                "[[ ! -f '$TMP/.cct-permissions.json' ]]"

# ── FR-8: cross-harness drift guard ─────────────────────────
# The SAME shared file both harnesses consume. Pi's unattended/autonomous
# profiles import it via importPermissions; the Claude generator sources it.
echo "--- cross-harness drift guard ---"
assert "Pi 'autonomous' imports relaxed (shared source)" \
  "grep -A6 'autonomous: {' '$PROFILES_TS' | grep -q 'importPermissions: \\[\"relaxed\"\\]'"
assert "Pi 'unattended' imports relaxed (shared source)" \
  "grep -A14 'unattended: {' '$PROFILES_TS' | grep -q 'importPermissions: \\[\"relaxed\"\\]'"

# Residual-ask parity: Pi unattended resolves asks to allow; the Claude analog
# is a non-prompting defaultMode. The guard fails if Pi would allow a residual
# ask but Claude (its generated default) would still prompt.
bash "$GEN" relaxed --settings "$TMP/parity.json" >/dev/null
CLAUDE_MODE="$(jq -r '.permissions.defaultMode' "$TMP/parity.json")"
assert "Pi unattended sets ask_resolution=allow" \
  "grep -A14 'unattended: {' '$PROFILES_TS' | grep -q 'ask_resolution: \"allow\"'"
assert "Claude default is non-prompting → ask-resolution parity holds" \
  "printf '%s' '$CLAUDE_MODE' | grep -qxE 'dontAsk|acceptEdits'"

echo ""
echo "========================================="
echo "  Claude settings generator: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
