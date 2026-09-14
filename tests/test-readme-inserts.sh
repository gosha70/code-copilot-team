#!/usr/bin/env bash

# test-readme-inserts.sh — the README's generated blocks and their generator
# (#214 Phase 2.2).
#
# Run from the repo root:
#   bash tests/test-readme-inserts.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GEN="$REPO_DIR/scripts/generate-readme-inserts.sh"
README="$REPO_DIR/README.md"
SETUP="$REPO_DIR/adapters/claude-code/setup.sh"
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

echo "=== README generated blocks ==="

# ── the committed README ─────────────────────────────────────
assert "generator is executable" "[[ -x '$GEN' ]]"
assert "committed blocks are current" "bash '$GEN' --check >/dev/null 2>&1"
for m in "generated:begin config-layers" "generated:end config-layers" \
         "generated:begin enforcement-tiers" "generated:end enforcement-tiers"; do
  assert "marker present: $m" "grep -qF '<!-- $m -->' '$README'"
done

OUT="$(bash "$GEN" --stdout)"

# ── the tree lists every source file ─────────────────────────
SKILLS=$(find "$REPO_DIR/shared/skills" -name SKILL.md | wc -l | tr -d ' ')
RULES=$(sed -n 's/^ALWAYS_RULES="\([^"]*\)".*/\1/p' "$SETUP" | head -1 | wc -w | tr -d ' ')
ONDEMAND=$((SKILLS - RULES))
AGENTS=$(find "$REPO_DIR/adapters/claude-code/.claude/agents" -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')
HOOKS=$(find "$REPO_DIR/adapters/claude-code/.claude/hooks" -maxdepth 1 -name '*.sh' | wc -l | tr -d ' ')

assert "rules headline counts the ALWAYS_RULES list ($RULES)" "grep -q 'always loaded, $RULES files' <<<\"\$OUT\""
assert "skills headline counts the on-demand skills ($ONDEMAND)" "grep -q 'SKILL.md format, $ONDEMAND skills' <<<\"\$OUT\""
assert "agents headline counts the agent files ($AGENTS)" "grep -q 'utility agents ($AGENTS files)' <<<\"\$OUT\""
assert "hooks headline counts the hook scripts ($HOOKS)" "grep -q 'always active, $HOOKS files' <<<\"\$OUT\""

# The headline used to disagree with the list beneath it: the README claimed
# 20 on-demand skills and named 15. Every source file must now appear.
BLOCK="$(awk '/generated:begin config-layers/,/generated:end config-layers/' <<<"$OUT")"
missing=0
# An always-rule appears as "<name>.md" under rules/, an on-demand skill as
# "<name>/" under skills/ — either form counts as listed.
for d in "$REPO_DIR"/shared/skills/*/; do
  name="$(basename "$d")"
  grep -qE "($name/|$name\.md)" <<<"$BLOCK" || { echo "    missing skill: $name"; missing=$((missing + 1)); }
done
for f in "$REPO_DIR"/adapters/claude-code/.claude/agents/*.md "$REPO_DIR"/adapters/claude-code/.claude/hooks/*.sh; do
  grep -qF "$(basename "$f")" <<<"$BLOCK" || { echo "    missing: $(basename "$f")"; missing=$((missing + 1)); }
done
assert "every rule, skill, agent and hook appears in the tree" "[[ $missing -eq 0 ]]"
assert "every tree entry carries a description" "! grep -qE '^  (├──|└──) [^ ]+ +$' <<<\"\$BLOCK\""

# ── the tiers table comes from the feature catalog ───────────
TIERS="$(awk '/generated:begin enforcement-tiers/,/generated:end enforcement-tiers/' <<<"$OUT")"
for a in $(find "$REPO_DIR/adapters" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort); do
  assert "tiers table has a row for $a" "grep -q '| \`$a\` |' <<<\"\$TIERS\""
done
assert "claude-code is Enforced" "grep -q '| \`claude-code\` | \*\*Enforced\*\* |' <<<\"\$TIERS\""
assert "an adapter with no enforced feature is Advisory" "grep -q '| \`cursor\` | Advisory |' <<<\"\$TIERS\""

# ── drift is detected, not silently absorbed ─────────────────
cp "$README" "$TMP/README.bak"
python3 - "$README" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("always loaded, 4 files", "always loaded, 99 files", 1)
open(p, "w").write(s)
PY
RC=0; bash "$GEN" --check >/dev/null 2>&1 || RC=$?
cp "$TMP/README.bak" "$README"
assert "--check fails on an edited block (exit 1)" "[[ '$RC' == '1' ]]"

# A hook with no description must fail the render, not produce a blank row.
cp -r "$REPO_DIR/adapters/claude-code/.claude/hooks" "$TMP/hooks.bak"
printf '#!/usr/bin/env bash\nexit 0\n' > "$REPO_DIR/adapters/claude-code/.claude/hooks/zz-undocumented.sh"
RC=0; bash "$GEN" --stdout >/dev/null 2>&1 || RC=$?
rm -f "$REPO_DIR/adapters/claude-code/.claude/hooks/zz-undocumented.sh"
assert "an undescribed hook fails the render (exit 1)" "[[ '$RC' == '1' ]]"

# ── one source for the always-rules list ─────────────────────
assert "ALWAYS_RULES is assigned once in setup.sh" "[[ \$(grep -c '^ALWAYS_RULES=' '$SETUP') -eq 1 ]]"
assert "setup.sh iterates the named list, not a literal" "! grep -q 'for name in coding-standards' '$SETUP'"
assert "the doc-accuracy gate reads the same assignment" "grep -q 'ALWAYS_RULES=\"' '$REPO_DIR/scripts/check-doc-accuracy.sh'"

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
