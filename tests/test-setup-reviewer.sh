#!/usr/bin/env bash

# test-setup-reviewer.sh — Tests for the copilot reviewer installer
#
# Covers:
#   - fresh-project install (AGENTS.md created, docs/CODE_REVIEW.md installed)
#   - existing AGENTS.md content preserved; loader appended in markers
#   - idempotency (second run byte-identical)
#   - loader refresh when the shared source changes
#   - refusal to overwrite a foreign docs/CODE_REVIEW.md
#   - generated AGENTS.md skipped (loader ships via generate.sh instead)
#   - uninstall removes only managed content
#   - unknown copilot rejected with the supported list
#   - generated adapters/codex/AGENTS.md carries the loader block
#
# Run from the repo root:
#   bash tests/test-setup-reviewer.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SETUP="$REPO_DIR/scripts/setup-reviewer.sh"

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

echo "=== setup-reviewer tests ==="

# ── Fresh project ───────────────────────────────────────────
echo "--- fresh project ---"
P1="$TMP/fresh"
mkdir -p "$P1"
bash "$SETUP" --codex "$P1" > /dev/null
assert "creates docs/CODE_REVIEW.md" "[[ -f '$P1/docs/CODE_REVIEW.md' ]]"
assert "installed doc carries the managed marker" \
  "head -1 '$P1/docs/CODE_REVIEW.md' | grep -q 'CCT-REVIEWER-MANAGED'"
assert "creates project-owned CODE_REVIEW_PROJECT.md" \
  "[[ -f '$P1/docs/CODE_REVIEW_PROJECT.md' ]]"
assert "project config keeps the placeholders" \
  "grep -q '<PROJECT_NAME>' '$P1/docs/CODE_REVIEW_PROJECT.md'"
assert "managed doc points to the project config" \
  "grep -q 'CODE_REVIEW_PROJECT.md' '$P1/docs/CODE_REVIEW.md'"
assert "managed doc requires target-alignment classification" \
  "grep -q 'on-target.*overcomplicated.*off-target' '$P1/docs/CODE_REVIEW.md'"
assert "managed doc requires a simplification pass" \
  "grep -q 'What can be removed without weakening' '$P1/docs/CODE_REVIEW.md'"
assert "creates AGENTS.md when absent" "[[ -f '$P1/AGENTS.md' ]]"
assert "loader block present with markers" \
  "grep -q 'BEGIN CCT-REVIEWER (codex)' '$P1/AGENTS.md' && grep -q 'END CCT-REVIEWER (codex)' '$P1/AGENTS.md'"
assert "loader directs to docs/CODE_REVIEW.md" \
  "grep -q 'docs/CODE_REVIEW.md' '$P1/AGENTS.md'"
assert "loader forbids PASS on unverified claims" \
  "grep -q 'Never return .PASS.' '$P1/AGENTS.md'"

# ── Existing AGENTS.md preserved + idempotency ──────────────
echo "--- existing content + idempotency ---"
P2="$TMP/existing"
mkdir -p "$P2"
printf '# My Project Rules\n\nAlways use tabs.\n' > "$P2/AGENTS.md"
bash "$SETUP" --codex "$P2" > /dev/null
assert "pre-existing content preserved" "grep -q 'Always use tabs.' '$P2/AGENTS.md'"
assert "loader appended after existing content" \
  "grep -q 'BEGIN CCT-REVIEWER (codex)' '$P2/AGENTS.md'"
SUM1=$(cksum "$P2/AGENTS.md")
DOC1=$(cksum "$P2/docs/CODE_REVIEW.md")
bash "$SETUP" --codex "$P2" > /dev/null
assert "second run leaves AGENTS.md byte-identical" "[[ '$SUM1' == \"\$(cksum '$P2/AGENTS.md')\" ]]"
assert "second run leaves CODE_REVIEW.md byte-identical" "[[ '$DOC1' == \"\$(cksum '$P2/docs/CODE_REVIEW.md')\" ]]"
assert "no duplicated marker blocks" \
  "[[ \$(grep -c 'BEGIN CCT-REVIEWER (codex)' '$P2/AGENTS.md') == 1 ]]"

# ── Loader refresh reflects source changes ──────────────────
echo "--- managed-block refresh ---"
# Simulate a stale installed block, then re-run: block must be replaced.
sed -i.bak 's/Never return/NEVER-RETURN-STALE/' "$P2/AGENTS.md" && rm -f "$P2/AGENTS.md.bak"
bash "$SETUP" --codex "$P2" > /dev/null
assert "managed block refreshed from source" \
  "! grep -q 'NEVER-RETURN-STALE' '$P2/AGENTS.md' && grep -q 'Never return' '$P2/AGENTS.md'"
assert "still exactly one block after refresh" \
  "[[ \$(grep -c 'BEGIN CCT-REVIEWER (codex)' '$P2/AGENTS.md') == 1 ]]"

# ── Project configuration survives refresh + uninstall ──────
# Regression (PR #148 review, P1): a re-run must never restore placeholders
# over filled-in values, and uninstall must never delete customized config.
echo "--- project config ownership ---"
sed -i.bak 's/<PROJECT_NAME>/AcmeProject/' "$P2/docs/CODE_REVIEW_PROJECT.md" && rm -f "$P2/docs/CODE_REVIEW_PROJECT.md.bak"
bash "$SETUP" --codex "$P2" > /dev/null
assert "re-run preserves customized project config" \
  "grep -q 'AcmeProject' '$P2/docs/CODE_REVIEW_PROJECT.md'"
assert "re-run does not restore the replaced placeholder" \
  "! grep -q '<PROJECT_NAME>' '$P2/docs/CODE_REVIEW_PROJECT.md'"
bash "$SETUP" --codex --uninstall "$P2" > /dev/null
assert "uninstall keeps customized project config" \
  "[[ -f '$P2/docs/CODE_REVIEW_PROJECT.md' ]] && grep -q 'AcmeProject' '$P2/docs/CODE_REVIEW_PROJECT.md'"
bash "$SETUP" --codex "$P2" > /dev/null
assert "reinstall keeps the customized config (no template reset)" \
  "grep -q 'AcmeProject' '$P2/docs/CODE_REVIEW_PROJECT.md'"
P5="$TMP/pristine-uninstall"
mkdir -p "$P5"
bash "$SETUP" --codex "$P5" > /dev/null
bash "$SETUP" --codex --uninstall "$P5" > /dev/null
assert "uninstall removes a pristine (untouched) project config" \
  "[[ ! -f '$P5/docs/CODE_REVIEW_PROJECT.md' ]]"

# ── Foreign CODE_REVIEW.md refused ──────────────────────────
echo "--- foreign files ---"
P3="$TMP/foreign"
mkdir -p "$P3/docs"
echo "my own review doc" > "$P3/docs/CODE_REVIEW.md"
RC=0
bash "$SETUP" --codex "$P3" > /dev/null 2>&1 || RC=$?
assert "foreign docs/CODE_REVIEW.md refused (exit 1)" "[[ '$RC' == '1' ]]"
assert "foreign doc left untouched" \
  "[[ \"\$(cat '$P3/docs/CODE_REVIEW.md')\" == 'my own review doc' ]]"

# ── Generated AGENTS.md: active vs stale ────────────────────
# Regression (PR #148 review, P2): a generated file WITHOUT the loader must
# fail loudly (setup would be inert), never report success.
echo "--- generated instruction file ---"
P4="$TMP/generated-stale"
mkdir -p "$P4"
printf '# Codex Agent Instructions\n\nAuto-generated from shared/skills/. Do not edit directly.\nRegenerate with: ./scripts/generate.sh\n' > "$P4/AGENTS.md"
RC=0
OUT=$(bash "$SETUP" --codex "$P4" 2>&1) || RC=$?
assert "stale generated AGENTS.md fails (exit 65)" "[[ '$RC' == '65' ]]"
assert "generated AGENTS.md is not hand-edited" \
  "! grep -q 'BEGIN CCT-REVIEWER' '$P4/AGENTS.md'"
assert "failure names the regeneration command" \
  "echo \"\$OUT\" | grep -q 'generate.sh'"
assert "failure states the setup is not active" \
  "echo \"\$OUT\" | grep -qi 'NOT active'"

P4B="$TMP/generated-current"
mkdir -p "$P4B"
{
  printf '# Codex Agent Instructions\n\nAuto-generated from shared/skills/. Do not edit directly.\nRegenerate with: ./scripts/generate.sh\n\n'
  sed -n '/BEGIN CCT-REVIEWER (codex)/,/END CCT-REVIEWER (codex)/p' "$REPO_DIR/adapters/codex/AGENTS.md"
} > "$P4B/AGENTS.md"
RC=0
OUT=$(bash "$SETUP" --codex "$P4B" 2>&1) || RC=$?
assert "generated AGENTS.md with loader succeeds" "[[ '$RC' == '0' ]]"
assert "active loader acknowledged, file untouched" \
  "echo \"\$OUT\" | grep -q 'already carries the loader' && [[ \$(grep -c 'BEGIN CCT-REVIEWER (codex)' '$P4B/AGENTS.md') == 1 ]]"
assert "doc installed alongside the generated file" "[[ -f '$P4B/docs/CODE_REVIEW.md' ]]"

# ── Uninstall ───────────────────────────────────────────────
echo "--- uninstall ---"
bash "$SETUP" --codex --uninstall "$P2" > /dev/null
assert "uninstall removes the loader block" \
  "! grep -q 'BEGIN CCT-REVIEWER' '$P2/AGENTS.md'"
assert "uninstall preserves pre-existing content" "grep -q 'Always use tabs.' '$P2/AGENTS.md'"
assert "uninstall removes the managed doc" "[[ ! -f '$P2/docs/CODE_REVIEW.md' ]]"
bash "$SETUP" --codex --uninstall "$P3" > /dev/null
assert "uninstall leaves a foreign doc in place" "[[ -f '$P3/docs/CODE_REVIEW.md' ]]"

# ── CLI contract ────────────────────────────────────────────
echo "--- CLI contract ---"
RC=0
bash "$SETUP" --cursor "$TMP" > /dev/null 2>&1 || RC=$?
assert "unknown copilot rejected (exit 64)" "[[ '$RC' == '64' ]]"
ERR=$(bash "$SETUP" --cursor "$TMP" 2>&1 || true)
assert "rejection names the supported list" "echo \"\$ERR\" | grep -q 'supported: codex'"
RC=0
bash "$SETUP" > /dev/null 2>&1 || RC=$?
assert "missing copilot selection rejected (exit 64)" "[[ '$RC' == '64' ]]"
assert "--list names codex" "bash '$SETUP' --list | grep -q 'codex'"

# ── Generator integration ───────────────────────────────────
echo "--- generator integration ---"
assert "generated adapters/codex/AGENTS.md carries the loader block" \
  "grep -q 'BEGIN CCT-REVIEWER (codex)' '$REPO_DIR/adapters/codex/AGENTS.md'"
assert "generated block directs to docs/CODE_REVIEW.md" \
  "grep -q 'docs/CODE_REVIEW.md' '$REPO_DIR/adapters/codex/AGENTS.md'"

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  setup-reviewer tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
