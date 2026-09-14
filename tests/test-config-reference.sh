#!/usr/bin/env bash

# test-config-reference.sh — the provider-profile schema, its validator, and
# the generated configuration reference (#214 Phase 2.3).
#
# Run from the repo root:
#   bash tests/test-config-reference.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VALIDATE="$REPO_DIR/scripts/validate-providers-profile.sh"
GEN="$REPO_DIR/scripts/generate-config-reference.sh"
SCHEMA="$REPO_DIR/shared/schemas/providers.schema.json"
TEMPLATE="$REPO_DIR/shared/templates/provider-profile-template.toml"
BAD="$REPO_DIR/tests/fixtures/providers-invalid/providers.toml"
REFERENCE="$REPO_DIR/docs/configuration-reference.md"
PASS=0
FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"; FAIL=$((FAIL + 1))
  fi
}

if ! python3 -c 'import tomllib' >/dev/null 2>&1; then
  echo "[SKIP] tomllib not available (needs python 3.11+) — config reference tests skipped."
  exit 0
fi

echo "=== provider profile schema + configuration reference ==="

# ── the schema and the shipped template ──────────────────────
assert "schema is valid JSON" "python3 -c 'import json,sys; json.load(open(sys.argv[1]))' '$SCHEMA'"
assert "shipped template validates" "bash '$VALIDATE' '$TEMPLATE' >/dev/null 2>&1"
assert "template declares every provider it names as a peer" \
  "! bash '$VALIDATE' '$TEMPLATE' 2>&1 | grep -q 'not a declared provider'"
assert "a missing profile is a skip, not a failure" "bash '$VALIDATE' '$TMP/absent.toml' >/dev/null 2>&1"
assert "a missing schema is an error" "! bash '$VALIDATE' '$TEMPLATE' '$TMP/absent.json' >/dev/null 2>&1"

# ── every defect in the fixture is named ─────────────────────
RC=0; OUT=$(bash "$VALIDATE" "$BAD" 2>&1) || RC=$?
assert "invalid fixture is rejected (exit 1)" "[[ '$RC' == '1' ]]"
for needle in \
  "has an inline comment" \
  "[providers.spark] unknown key \`modle\`" \
  "api_key_env \`sk-not-a-variable-name\` is not a variable NAME" \
  "\`timeout_sec\` must be integer" \
  "\`temperature\` must be number" \
  "type cli needs a \`command\` template" \
  "conformance_command\` must carry the {review_request} placeholder" \
  "type \`telepathy\` is not one of" \
  "peer_for.claude = \`ghost\` is not a declared provider" \
  "fallback_chain.claude names \`phantom\`"; do
  assert "fixture defect named: ${needle:0:44}" "grep -qF '$needle' <<<\"\$OUT\""
done

# ── the schema covers what the readers read ──────────────────
# A key some script reads but the schema does not declare would be rejected
# as "unknown" in a profile that legitimately sets it.
READ_KEYS=$(grep -rhoE 'toml_get "\$(PROFILE|profile_toml)" "\$?[A-Za-z_.$]*" "[a-z_]+"' \
  "$REPO_DIR/scripts"/*.sh 2>/dev/null | grep -oE '"[a-z_]+"\)?$' | tr -d '")' | sort -u)
missing=0
for k in $READ_KEYS; do
  case "$k" in type|command|timeout_sec|healthcheck|model|base_url|api_key_env|max_tokens|temperature|host|disable_thinking|price_usd_per_mtok_input|price_usd_per_mtok_output|version|conformance_command) ;;
    *) python3 -c "
import json, sys
s = json.load(open('$SCHEMA'))
sys.exit(0 if '$k' in s['\$defs']['provider']['properties'] else 1)
" || { echo "    schema does not declare: $k"; missing=$((missing + 1)); } ;;
  esac
done
assert "every provider key the scripts read is declared" "[[ $missing -eq 0 ]]"

# ── the generated reference ──────────────────────────────────
assert "committed reference is current" "bash '$GEN' --check >/dev/null 2>&1"
REF="$(bash "$GEN" --stdout)"
assert "reference carries the generated marker" "grep -q 'GENERATED — do not edit' <<<\"\$REF\""
for section in "automation.json" "providers.toml" "Session analytics"; do
  assert "reference has a section for $section" "grep -qF '$section' <<<\"\$REF\""
done
assert "reference lists the analytics defaults" "grep -q '| \`judge.default.backend\` |' <<<\"\$REF\""
assert "a block-level variable is listed, not guessed onto a row" \
  "grep -q '^- \`CCT_SA_JUDGE_BACKEND\`' <<<\"\$REF\""
assert "reference pairs a key with its environment variable" "grep -q 'CCT_SA_JUDGE_BACKEND' <<<\"\$REF\""
missing_keys=0
for k in $(python3 -c "
import json
s = json.load(open('$SCHEMA'))
print(' '.join(s['\$defs']['provider']['properties']))"); do
  grep -qF "| \`$k\` |" <<<"$REF" || { echo "    not documented: $k"; missing_keys=$((missing_keys + 1)); }
done
assert "reference documents every provider key" "[[ $missing_keys -eq 0 ]]"
assert "reference is linked from the README" "grep -qF '(docs/configuration-reference.md)' '$REPO_DIR/README.md'"
assert "reference is served in Learn" "grep -qF 'docs/configuration-reference.md' '$REPO_DIR/scripts/session_analytics/config_data/learn-sections.json'"

# ── the reference refuses to render half a page ──────────────
cp "$SCHEMA" "$TMP/schema.bak"
printf '{"$schema":"x","properties":{}}' > "$SCHEMA"
RC=0; bash "$GEN" --stdout >/dev/null 2>&1 || RC=$?
cp "$TMP/schema.bak" "$SCHEMA"
assert "a gutted schema fails the render (exit 1)" "[[ '$RC' == '1' ]]"
assert "the schema was restored" "bash '$VALIDATE' '$TEMPLATE' >/dev/null 2>&1"

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
