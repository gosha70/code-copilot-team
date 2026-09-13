#!/usr/bin/env bash

# test-features-catalog.sh — the feature catalog, its validator and its render
# (#214 Phase 2.1).
#
# Run from the repo root:
#   bash tests/test-features-catalog.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VALIDATE="$REPO_DIR/scripts/validate-features.sh"
GENERATE="$REPO_DIR/scripts/generate-feature-index.sh"
CATALOG="$REPO_DIR/shared/features/catalog.yaml"
SCHEMA="$REPO_DIR/shared/schemas/feature.schema.json"
BAD="$REPO_DIR/tests/fixtures/features-invalid/catalog.yaml"
PASS=0
FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

if ! command -v ruby >/dev/null 2>&1; then
  echo "[SKIP] ruby not found — feature catalog tests skipped."
  exit 0
fi

echo "=== feature catalog ==="

# ── the shipped catalog ──────────────────────────────────────
assert "schema exists and is JSON" "ruby -rjson -e 'JSON.parse(File.read(ARGV[0]))' '$SCHEMA' 2>/dev/null"
assert "shipped catalog validates" "bash '$VALIDATE' >/dev/null 2>&1"
assert "docs/features.md is up to date" "bash '$GENERATE' --check >/dev/null 2>&1"

# ── enums come from the schema ───────────────────────────────
NARROW="$TMP/narrow.schema.json"
ruby -rjson -e '
  s = JSON.parse(File.read(ARGV[0]))
  s["$defs"]["maturity"]["enum"].delete("stable")
  File.write(ARGV[1], JSON.generate(s))
' "$SCHEMA" "$NARROW"
RC=0; bash "$VALIDATE" "$CATALOG" "$NARROW" >/dev/null 2>&1 || RC=$?
assert "validator enums come from the schema (narrowed schema rejects the catalog)" "[[ '$RC' == '1' ]]"
RC=0; bash "$VALIDATE" "$CATALOG" "$TMP/no-such.schema.json" >/dev/null 2>&1 || RC=$?
assert "validator refuses a missing schema (exit 1)" "[[ '$RC' == '1' ]]"
assert "validator restates no enum vocabulary" "! grep -q '%w\\[' '$VALIDATE'"

# ── every defect in the fixture is named ─────────────────────
RC=0; BAD_OUT=$(bash "$VALIDATE" "$BAD" 2>&1) || RC=$?
assert "invalid fixture is rejected (exit 1)" "[[ '$RC' == '1' ]]"
for needle in \
  "duplicate ids dup-id" \
  "bad-maturity: maturity \"alpha\"" \
  "bad-since: since \"soon\"" \
  "missing-adapter: adapters not classified: pi" \
  "unknown-adapter: unknown adapters: emacs" \
  "bad-support: adapters.claude-code \"mandatory\"" \
  "deprecated-orphan: deprecated without replaced_by" \
  "missing-guide: guide docs/no-such-guide.md does not exist" \
  "dangling-refs: command no-such-command" \
  "dangling-refs: skill no-such-skill" \
  "dangling-refs: capability no.such-capability"; do
  assert "fixture defect named: $needle" "grep -qF '$needle' <<<\"\$BAD_OUT\""
done

# ── the render ───────────────────────────────────────────────
OUT=$(bash "$GENERATE" --stdout)
assert "index has a Features section" "grep -q '^## Features' <<<\"\$OUT\""
assert "Features section precedes slash commands" "[[ \$(grep -n '^## Features' <<<\"\$OUT\" | cut -d: -f1) -lt \$(grep -n '^## Slash commands' <<<\"\$OUT\" | cut -d: -f1) ]]"
N=$(ruby -ryaml -e 'puts YAML.load_file(ARGV[0])["features"].size' "$CATALOG")
assert "headline counts the catalog's features ($N)" "grep -q \"^_${N} features · \" <<<\"\$OUT\""
for a in $(find "$REPO_DIR/adapters" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort); do
  assert "adapter column present: $a" "grep -q \"| $a |\" <<<\"\$OUT\""
done
assert "every feature title links to its guide" "[[ \$(grep -c '^| \\[' <<<\"\$OUT\") -eq $N ]]"
assert "index links the maturity definitions" "grep -q '(maturity.md)' <<<\"\$OUT\""

# ── the feature table never degrades silently ────────────────
# A missing catalog must fail the render (and so --check), not print an
# index with the headline table quietly gone.
RC=0; bash -c "FEATURES_OVERRIDE=1; sed 's|^FEATURES=.*|FEATURES=\"$TMP/absent.yaml\"|' '$GENERATE' > '$TMP/gen.sh'; bash '$TMP/gen.sh' --stdout" >/dev/null 2>&1 || RC=$?
assert "render fails when the catalog is missing (no silent degrade)" "[[ '$RC' == '1' ]]"

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
