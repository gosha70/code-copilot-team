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
LAYERS="$REPO_DIR/docs/configuration-layers.md"
MATURITY="$REPO_DIR/docs/maturity.md"
LANDING="$REPO_DIR/docs/README.md"
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
# Each block lives in exactly one file (#214 Phase 3.2 moved two of them out
# of the README): the front door carries the short forms, the guides the detail.
assert "README carries the choose-adapter block" "grep -qF '<!-- generated:begin choose-adapter -->' '$README'"
assert "README carries the feature-summary block" "grep -qF '<!-- generated:begin feature-summary -->' '$README'"
assert "the configuration-layers guide carries its block" "grep -qF '<!-- generated:begin config-layers -->' '$LAYERS'"
assert "the maturity guide carries the enforcement tiers" "grep -qF '<!-- generated:begin enforcement-tiers -->' '$MATURITY'"
assert "the landing page carries the docs index" "grep -qF '<!-- generated:begin docs-index -->' '$LANDING'"
for f in "$README" "$LAYERS" "$MATURITY" "$LANDING"; do
  b=$(grep -c '<!-- generated:begin' "$f"); e=$(grep -c '<!-- generated:end' "$f")
  assert "$(basename "$f"): every block is closed" "[[ '$b' == '$e' ]]"
done
assert "no block name appears in two files" \
  "[[ \$(cat '$README' '$LAYERS' '$MATURITY' '$LANDING' | grep -o '<!-- generated:begin [a-z-]*' | sort | uniq -d | wc -l) -eq 0 ]]"

OUT="$(bash "$GEN" --stdout)"

# ── the tree lists every source file ─────────────────────────
SKILLS=$(find "$REPO_DIR/shared/skills" -name SKILL.md | wc -l | tr -d ' ')
RULES=$(sed -n 's/^ALWAYS_RULES="\([^"]*\)".*/\1/p' "$SETUP" | head -1 | wc -w | tr -d ' ')
ONDEMAND=$((SKILLS - RULES))
AGENTS=$(find "$REPO_DIR/adapters/claude-code/.claude/agents" -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')
HOOKS=$(find "$REPO_DIR/adapters/claude-code/.claude/hooks" -maxdepth 1 -name '*.sh' | wc -l | tr -d ' ')

assert "rules headline counts the ALWAYS_RULES list ($RULES)" "grep -q 'always loaded, $RULES files' '$LAYERS'"
assert "skills headline counts the on-demand skills ($ONDEMAND)" "grep -q 'SKILL.md format, $ONDEMAND skills' '$LAYERS'"
assert "agents headline counts the agent files ($AGENTS)" "grep -q 'utility agents ($AGENTS files)' '$LAYERS'"
assert "hooks headline counts the hook scripts ($HOOKS)" "grep -q 'always active, $HOOKS files' '$LAYERS'"

# The headline used to disagree with the list beneath it: the README claimed
# 20 on-demand skills and named 15. Every source file must now appear.
BLOCK="$(awk '/generated:begin config-layers/,/generated:end config-layers/' "$LAYERS")"
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
TIERS="$(awk '/generated:begin enforcement-tiers/,/generated:end enforcement-tiers/' "$MATURITY")"
for a in $(find "$REPO_DIR/adapters" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort); do
  assert "tiers table has a row for $a" "grep -q '| \`$a\` |' <<<\"\$TIERS\""
done
assert "claude-code is Enforced" "grep -q '| \`claude-code\` | \*\*Enforced\*\* |' <<<\"\$TIERS\""
assert "an adapter with no enforced feature is Advisory" "grep -q '| \`cursor\` | Advisory |' <<<\"\$TIERS\""

# ── drift is detected, not silently absorbed ─────────────────
cp "$LAYERS" "$TMP/layers.bak"
python3 - "$LAYERS" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("always loaded, 4 files", "always loaded, 99 files", 1)
open(p, "w").write(s)
PY
RC=0; bash "$GEN" --check >/dev/null 2>&1 || RC=$?
cp "$TMP/layers.bak" "$LAYERS"
assert "--check fails on an edited block (exit 1)" "[[ '$RC' == '1' ]]"

# A hook with no description must fail the render, not produce a blank row.
cp -r "$REPO_DIR/adapters/claude-code/.claude/hooks" "$TMP/hooks.bak"
printf '#!/usr/bin/env bash\nexit 0\n' > "$REPO_DIR/adapters/claude-code/.claude/hooks/zz-undocumented.sh"
RC=0; bash "$GEN" --stdout >/dev/null 2>&1 || RC=$?
rm -f "$REPO_DIR/adapters/claude-code/.claude/hooks/zz-undocumented.sh"
assert "an undescribed hook fails the render (exit 1)" "[[ '$RC' == '1' ]]"

# ── the front door's two blocks ──────────────────────────────
CHOOSE="$(awk '/generated:begin choose-adapter/,/generated:end choose-adapter/' "$README")"
SUMMARY="$(awk '/generated:begin feature-summary/,/generated:end feature-summary/' "$README")"
N_FEATURES=$(ruby -ryaml -e 'puts YAML.load_file(ARGV[0])["features"].size' "$REPO_DIR/shared/features/catalog.yaml")
assert "every feature has a summary bullet" "[[ \$(grep -c '^- \*\*' <<<\"\$SUMMARY\") -eq $N_FEATURES ]]"
assert "non-stable features carry their maturity" "grep -q '_(beta)_' <<<\"\$SUMMARY\""
for a in $(find "$REPO_DIR/adapters" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort); do
  assert "choose-adapter row for $a" "grep -q '| \`$a\` |' <<<\"\$CHOOSE\""
  assert "choose-adapter install flag for $a exists in setup.sh" \
    "grep -qE '^[[:space:]]*--$a\)' '$REPO_DIR/scripts/setup.sh'"
done
# A flag the installer does not accept must fail the render, not ship a
# command that errors: the hand-kept map shipped --copilot for --github-copilot.
cp "$REPO_DIR/scripts/setup.sh" "$TMP/setup.bak"
python3 - "$REPO_DIR/scripts/setup.sh" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("    --aider)            TOOLS+=(\"aider\"); shift ;;\n", "", 1)
open(p, "w").write(s)
PY
RC=0; bash "$GEN" --stdout >/dev/null 2>&1 || RC=$?
cp "$TMP/setup.bak" "$REPO_DIR/scripts/setup.sh"
assert "an adapter with no installer flag fails the render" "[[ '$RC' == '1' ]]"

# ── the docs landing page ────────────────────────────────────
INDEX="$(awk '/generated:begin docs-index/,/generated:end docs-index/' "$LANDING")"
REGISTRY="$REPO_DIR/scripts/session_analytics/config_data/learn-sections.json"
missing_docs=0
for rel in $(python3 -c "
import json
d = json.load(open('$REGISTRY'))
print(' '.join(p for s in d['sections'] for p in (s.get('paths') or [])))"); do
  name="${rel#docs/}"
  case "$rel" in docs/README.md) continue ;; esac
  grep -qF "($name)" <<<"$INDEX" || grep -qF "(../$rel)" <<<"$INDEX" \
    || { echo "    not on the landing page: $rel"; missing_docs=$((missing_docs + 1)); }
done
assert "every registry path is on the landing page" "[[ $missing_docs -eq 0 ]]"
assert "the landing page groups by the registry's section titles" \
  "grep -q '^### Feature guides' <<<\"\$INDEX\""
assert "a lead sentence is prose, not markup" "! grep -qE '— (src=|<|\\|)' <<<\"\$INDEX\""
assert "a generated page says so instead of quoting its banner" \
  "grep -q 'generated from its sources' <<<\"\$INDEX\""
# The lead is a sentence, not a source line: markdown wraps prose, so cutting
# at the first physical line ended descriptions on "which" and "in two"
# (#356 review). A dangling conjunction is the symptom to guard.
assert "no lead ends on a dangling word" \
  "! grep -qE '— .*( which| that| and| in two| the| a| of| to| with)\$' <<<\"\$INDEX\""
assert "no lead is a frontmatter key" "! grep -qE '— [a-z_]+: ' <<<\"\$INDEX\""
# A wiki page opens with YAML frontmatter; its lead must be the prose beneath.
assert "a frontmatter page gets its prose" \
  "grep -q 'Short canonical definitions of terms' <<<\"\$INDEX\""
assert "bold at the start of a line is prose, not a list marker" \
  "grep -q 'the way the Studio.s \*\*Learn\*\* tab' <<<\"\$INDEX\""

# A registry entry pointing at a file that does not exist must fail the
# render rather than emit a dead link onto the landing page.
cp "$REGISTRY" "$TMP/registry.bak"
python3 - "$REGISTRY" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
for s in d["sections"]:
    if s.get("paths"):
        s["paths"].append("docs/no-such-guide.md")
        break
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
PY
RC=0; bash "$GEN" --stdout >/dev/null 2>&1 || RC=$?
cp "$TMP/registry.bak" "$REGISTRY"
assert "a registry entry with no file fails the render" "[[ '$RC' == '1' ]]"

# ── one source for the always-rules list ─────────────────────
assert "ALWAYS_RULES is assigned once in setup.sh" "[[ \$(grep -c '^ALWAYS_RULES=' '$SETUP') -eq 1 ]]"
assert "setup.sh iterates the named list, not a literal" "! grep -q 'for name in coding-standards' '$SETUP'"
assert "the doc-accuracy gate reads the same assignment" "grep -q 'ALWAYS_RULES=\"' '$REPO_DIR/scripts/check-doc-accuracy.sh'"

# ── llms.txt (experimental, #214 Phase 6.1) ─────────────────
# The documentation index in the llmstxt.org shape. It must be the same list
# as the landing page, from the same code, or it is a second source.
echo ""
echo "=== llms.txt ==="
LLMS_GEN="$REPO_DIR/scripts/generate-llms-txt.sh"
LLMS="$REPO_DIR/llms.txt"
RAW="https://raw.githubusercontent.com/gosha70/code-copilot-team/master"

RC=0; bash "$LLMS_GEN" --check >/dev/null 2>&1 || RC=$?
assert "llms.txt is current" "[[ '$RC' == '0' ]]"
assert "it opens with the project name as H1" "[[ \"\$(sed -n '1p' '$LLMS')\" == '# Code Copilot Team' ]]"
assert "then a blockquote summary" "sed -n '3p' '$LLMS' | grep -q '^> An enforceable harness'"
assert "it says it is experimental" "grep -q '^Experimental: llms.txt is a proposal' '$LLMS'"
assert "sections are H2, named as the registry names them" "grep -q '^## Feature guides$' '$LLMS'"

wrong_count=0
for rel in $(python3 -c "
import json
d = json.load(open('$REGISTRY'))
print(' '.join(p for s in d['sections'] for p in (s.get('paths') or [])))"); do
  n=$(grep -cF "]($RAW/$rel)" "$LLMS" || true)
  [[ "$n" -eq 1 ]] || { echo "    listed $n times, expected once: $rel"; wrong_count=$((wrong_count + 1)); }
done
assert "every registry path is linked once, as raw Markdown" "[[ $wrong_count -eq 0 ]]"
assert "it lists exactly what the landing page lists" \
  "[[ \$(grep -c '^- \[' '$LLMS') -eq \$(grep -c '^- \[' <<<\"\$INDEX\") ]]"
assert "a description follows a colon, the llms.txt form" "! grep -qE '^- \[[^]]*\]\([^)]*\) — ' '$LLMS'"
assert "both generators render through the one module" \
  "grep -q 'scripts/lib/docs_index.py' '$GEN' && grep -q 'scripts/lib/docs_index.py' '$LLMS_GEN' && ! grep -q 'def lead_of' '$GEN'"

cp "$LLMS" "$TMP/llms.bak"
echo "- [Hand edit](https://example.com): not from the registry" >> "$LLMS"
RC=0; bash "$LLMS_GEN" --check >/dev/null 2>&1 || RC=$?
cp "$TMP/llms.bak" "$LLMS"
assert "a hand-edited llms.txt fails --check" "[[ '$RC' == '1' ]]"

cp "$REGISTRY" "$TMP/registry.bak"
python3 - "$REGISTRY" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
for s in d["sections"]:
    if s.get("paths"):
        s["paths"].append("docs/no-such-guide.md")
        break
json.dump(d, open(p, "w"), indent=2, ensure_ascii=False)
PY
RC=0; bash "$LLMS_GEN" --stdout >/dev/null 2>&1 || RC=$?
cp "$TMP/registry.bak" "$REGISTRY"
assert "a registry entry with no file fails llms.txt too" "[[ '$RC' == '1' ]]"

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
