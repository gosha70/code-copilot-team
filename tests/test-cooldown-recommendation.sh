#!/usr/bin/env bash

# test-cooldown-recommendation.sh — Contract test for issue #25.
#
# Pins the prompt text across every surface that implements the
# "recommend the next bet at cycle transitions" behavior:
#
#   Canonical sources (claude_code/ + shared/):
#     1. claude_code/.claude/agents/cooldown-report.md
#          — three conditional output messages, ranking inputs, discipline rule
#     2. claude_code/.claude/commands/cooldown.md
#          — step 7 surfaces the agent's recommendation verbatim, drops the
#            old passive "convene the next betting table" line
#     3. shared/templates/sdd/cooldown-report-template.md
#          — "Next-bet recommendation" subsection present
#     4. shared/skills/team-lead-efficiency/SKILL.md
#          — "Cycle-Transition Handoff" section present
#     5. shared/skills/agent-team-protocol/SKILL.md
#          — cross-reference to the team-lead section present
#     6. docs/shape-up-workflow.md
#          — "Cycle-transition handoff" subsection present
#
#   Adapter outputs (independently maintained — must mirror the canonical):
#     7. adapters/claude-code/.claude/agents/cooldown-report.md
#     8. adapters/claude-code/.claude/commands/cooldown.md
#
#   Generated downstream adapters (must be regenerated via scripts/generate.sh
#   after editing the relevant shared/skills/):
#     9. adapters/cursor/.cursor/rules/team-lead-efficiency.mdc
#    10. adapters/cursor/.cursor/rules/agent-team-protocol.mdc
#    11. adapters/github-copilot/.github/instructions/team-lead-efficiency.instructions.md
#    12. adapters/github-copilot/.github/instructions/agent-team-protocol.instructions.md
#
# Plus a fixture smoke test that the new template additions don't break
# validate-pitch.sh (a synthetic shaped pitch still passes validation).
#
# This is a CONTRACT TEST — agent prompts run inside the LLM, not bash.
# Bash can only verify that the prompt text contains the load-bearing
# guidance phrases so future drift cannot silently regress the behavior.
# Runtime validation of the LLM's actual output requires manual dogfood
# (see docs/shape-up-workflow.md § "Cycle-transition handoff").
#
# Run from the repo root:
#   bash tests/test-cooldown-recommendation.sh

set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0
FAIL=0

assert_grep() {
  local name="$1" pattern="$2" file="$3"
  if grep -qF -- "$pattern" "$file" 2>/dev/null; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name"
    echo "         pattern: $pattern"
    echo "         file:    $file"
    FAIL=$((FAIL + 1))
  fi
}

assert_no_grep() {
  local name="$1" pattern="$2" file="$3"
  if ! grep -qF -- "$pattern" "$file" 2>/dev/null; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name (pattern unexpectedly present)"
    echo "         pattern: $pattern"
    echo "         file:    $file"
    FAIL=$((FAIL + 1))
  fi
}

assert_ok() {
  local name="$1" rc="$2"
  if [[ "$rc" -eq 0 ]]; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name (rc=$rc)"
    FAIL=$((FAIL + 1))
  fi
}

# ── 1. cooldown-report agent prompt ────────────────────────────
echo "--- 1. cooldown-report.md (agent prompt) ---"
AGENT="$REPO_DIR/claude_code/.claude/agents/cooldown-report.md"

assert_grep "ranking inputs section present" "Ranking inputs (in priority order):" "$AGENT"
assert_grep "ROADMAP.md ranking input documented" "ROADMAP.md" "$AGENT"
assert_grep "single-winner output template present" "Recommend \`/bet" "$AGENT"
assert_grep "single-winner names cycle handoff" "/cycle-start" "$AGENT"
assert_grep "empty-set output template present" "No shaped pitches available" "$AGENT"
assert_grep "ambiguity output template present" "Multiple shaped pitches eligible" "$AGENT"
assert_grep "recommendation-discipline rule present" "Recommendation discipline" "$AGENT"
assert_grep "discipline rule cites issue #25 surface" "recommend, don't ask" "$AGENT"

# ── 2. /cooldown command ───────────────────────────────────────
echo "--- 2. cooldown.md (slash command) ---"
CMD="$REPO_DIR/claude_code/.claude/commands/cooldown.md"

assert_grep "step 7 surfaces agent message verbatim" "verbatim" "$CMD"
assert_grep "step 7 references the three forms" "single-winner / no-shaped / multiple-ambiguous" "$CMD"
assert_grep "step 7 cites issue #25" "issue #25" "$CMD"
assert_no_grep "old 'convene the next betting table' line removed" \
  "When ready, \`/shape\` new pitches and convene the next betting table." "$CMD"

# ── 3. cooldown-report template ────────────────────────────────
echo "--- 3. cooldown-report-template.md ---"
TPL="$REPO_DIR/shared/templates/sdd/cooldown-report-template.md"

assert_grep "Next-bet recommendation subsection present" "### Next-bet recommendation" "$TPL"
assert_grep "template carries actionable command pair" "**Next-bet recommendation:**" "$TPL"
assert_grep "template names /bet command" "/bet [pitch_id]" "$TPL"
assert_grep "template names /cycle-start handoff" "/cycle-start [pitch_id]" "$TPL"

# ── 4. team-lead-efficiency skill ──────────────────────────────
echo "--- 4. team-lead-efficiency/SKILL.md ---"
TL="$REPO_DIR/shared/skills/team-lead-efficiency/SKILL.md"

assert_grep "Cycle-Transition Handoff section present" "## Cycle-Transition Handoff (Recommend, Don't Ask)" "$TL"
assert_grep "skill carries Bad/Good example" 'What'\''s next?' "$TL"
assert_grep "skill carries actionable Good example" "Recommend \`/bet 0001-foundation\`" "$TL"
assert_grep "skill cites issue #25" "issue #25" "$TL"
assert_grep "anti-pattern row added" '"What'\''s next?" after a shipped cycle' "$TL"

# ── 5. agent-team-protocol cross-reference ─────────────────────
echo "--- 5. agent-team-protocol/SKILL.md (cross-reference) ---"
ATP="$REPO_DIR/shared/skills/agent-team-protocol/SKILL.md"

assert_grep "cross-reference section present" "## Cycle-Transition Handoff" "$ATP"
assert_grep "cross-reference points to team-lead skill" "team-lead-efficiency.md" "$ATP"
assert_grep "cross-reference cites issue #25" "issue #25" "$ATP"

# ── 6. shape-up-workflow doc ───────────────────────────────────
echo "--- 6. docs/shape-up-workflow.md ---"
DOC="$REPO_DIR/docs/shape-up-workflow.md"

assert_grep "doc subsection present" "## Cycle-transition handoff (recommend, don't ask)" "$DOC"
assert_grep "doc carries Bad example" 'What'\''s next?' "$DOC"
assert_grep "doc carries Good example" "Recommend \`/bet 0001-foundation\`" "$DOC"
assert_grep "doc lists implementation surfaces" "Implementation surface:" "$DOC"
assert_grep "doc references cooldown-report agent" "cooldown-report.md" "$DOC"
assert_grep "doc references team-lead skill" "team-lead-efficiency/SKILL.md" "$DOC"

# ── 7. Adapter copies (claude-code adapter — independently maintained) ──
echo "--- 7. adapters/claude-code/ (must mirror canonical) ---"
ADAPTER_AGENT="$REPO_DIR/adapters/claude-code/.claude/agents/cooldown-report.md"
ADAPTER_CMD="$REPO_DIR/adapters/claude-code/.claude/commands/cooldown.md"

assert_grep "adapter agent: ranking inputs section" "Ranking inputs (in priority order):" "$ADAPTER_AGENT"
assert_grep "adapter agent: single-winner output template" "Recommend \`/bet" "$ADAPTER_AGENT"
assert_grep "adapter agent: empty-set output template" "No shaped pitches available" "$ADAPTER_AGENT"
assert_grep "adapter agent: ambiguity output template" "Multiple shaped pitches eligible" "$ADAPTER_AGENT"
assert_grep "adapter agent: recommendation discipline rule" "Recommendation discipline" "$ADAPTER_AGENT"
assert_grep "adapter cmd: step 7 surfaces verbatim" "verbatim" "$ADAPTER_CMD"
assert_grep "adapter cmd: step 7 cites issue #25" "issue #25" "$ADAPTER_CMD"
assert_no_grep "adapter cmd: old passive line removed" \
  "When ready, \`/shape\` new pitches and convene the next betting table." "$ADAPTER_CMD"

# ── 8. Generated downstream adapters (cursor + github-copilot) ───────
echo "--- 8. Generated downstream adapter outputs ---"
CURSOR_TL="$REPO_DIR/adapters/cursor/.cursor/rules/team-lead-efficiency.mdc"
CURSOR_ATP="$REPO_DIR/adapters/cursor/.cursor/rules/agent-team-protocol.mdc"
GHCOPILOT_TL="$REPO_DIR/adapters/github-copilot/.github/instructions/team-lead-efficiency.instructions.md"
GHCOPILOT_ATP="$REPO_DIR/adapters/github-copilot/.github/instructions/agent-team-protocol.instructions.md"

assert_grep "cursor team-lead: handoff section regenerated" "Cycle-Transition Handoff" "$CURSOR_TL"
assert_grep "cursor agent-team-protocol: cross-ref regenerated" "Cycle-Transition Handoff" "$CURSOR_ATP"
assert_grep "github-copilot team-lead: handoff section regenerated" "Cycle-Transition Handoff" "$GHCOPILOT_TL"
assert_grep "github-copilot agent-team-protocol: cross-ref regenerated" "Cycle-Transition Handoff" "$GHCOPILOT_ATP"

# ── 9. Fixture smoke: template additions don't break validation ────
echo "--- 9. Fixture smoke (validate-pitch.sh round-trip) ---"
TEST_TMPDIR=$(mktemp -d)
trap 'rm -rf "$TEST_TMPDIR"' EXIT
FAKE="$TEST_TMPDIR/fake-repo"
mkdir -p "$FAKE/specs/pitches/0001-foundation"
mkdir -p "$FAKE/specs/retros"

cat > "$FAKE/specs/pitches/0001-foundation/pitch.md" <<'EOF'
---
pitch_id: 0001-foundation
title: "Foundation pitch (test fixture)"
appetite: 4w
bet_status: shaped
cycle: ""
circuit_breaker: "If foundation scopes don't compile by week 2, ship the schema-only slice and shelve the orchestration layer."
shaped_by: "test-harness"
shaped_date: 2026-05-06
---

# Foundation

Test fixture for issue #25 contract test. Synthetic shaped pitch.
EOF

cat > "$FAKE/specs/retros/cycle-00.md" <<'EOF'
# Cycle 00 retro (test fixture)

Synthetic.
EOF

VALIDATOR="$REPO_DIR/scripts/validate-pitch.sh"
( cd "$FAKE" && VALIDATE_PITCH_REPO="$FAKE" bash "$VALIDATOR" --all >/dev/null 2>&1 )
assert_ok "synthetic shaped pitch validates cleanly" $?

# Render the template into the fixture (substitute placeholders) and
# confirm validate-pitch.sh remains green — a coarse smoke that the
# new template additions don't introduce a syntactic conflict.
TEMPLATE="$REPO_DIR/shared/templates/sdd/cooldown-report-template.md"
RENDERED="$FAKE/specs/retros/cooldown-after-00.md"
sed -e 's/\[NN\]/00/g' \
    -e 's/\[YYYY-MM-DD\]/2026-05-06/g' \
    -e 's/\[1w | 2w\]/1w/g' \
    -e 's/\[pitch_id\]/0001-foundation/g' \
    -e 's/\[NN+1\]/01/g' \
    "$TEMPLATE" > "$RENDERED"

assert_grep "rendered report contains substituted recommendation" \
  "**Next-bet recommendation:** \`/bet 0001-foundation\` → \`/cycle-start 0001-foundation\` (cycle 01)" \
  "$RENDERED"

( cd "$FAKE" && VALIDATE_PITCH_REPO="$FAKE" bash "$VALIDATOR" --all >/dev/null 2>&1 )
assert_ok "validate-pitch.sh still passes after rendering cooldown report" $?

# ── 10. Self syntax check ──────────────────────────────────────
echo "--- 10. This script's syntax ---"
bash -n "$0"
assert_ok "test-cooldown-recommendation.sh has valid bash syntax" $?

echo ""
echo "=========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "=========================================="

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
