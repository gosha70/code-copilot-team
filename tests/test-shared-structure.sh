#!/usr/bin/env bash

# test-shared-structure.sh — Tests for shared/ directory structure and setup.sh integration
#
# Validates:
#   1. shared/ directory has all expected files (rules, docs, templates)
#   2. Symlinks in claude_code/.claude/ resolve to shared/ correctly
#   3. claude-setup.sh installs identical content from shared/ paths
#   4. --sync flag reads from shared/ paths
#   5. Template extraction fidelity (PROJECT.md → CLAUDE.md)
#
# Run from the repo root:
#   bash tests/test-shared-structure.sh

set -u

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHARED_DIR="$REPO_DIR/shared"
CLAUDE_CODE_DIR="$REPO_DIR/claude_code"
ADAPTER_DIR="$REPO_DIR/adapters/claude-code"
SETUP_SCRIPT="$ADAPTER_DIR/setup.sh"
PASS=0
FAIL=0

assert_ok() {
  local name="$1" result="$2"
  if [[ "$result" -eq 0 ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected '$expected', got '$actual')"
    FAIL=$((FAIL + 1))
  fi
}

assert_file_exists() {
  local name="$1" path="$2"
  if [[ -f "$path" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (file not found: $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_dir_exists() {
  local name="$1" path="$2"
  if [[ -d "$path" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (directory not found: $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_symlink() {
  local name="$1" path="$2"
  if [[ -L "$path" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (not a symlink: $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_symlink_resolves() {
  local name="$1" path="$2"
  if [[ -L "$path" && -f "$path" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    if [[ ! -L "$path" ]]; then
      echo "  FAIL: $name (not a symlink: $path)"
    else
      echo "  FAIL: $name (symlink broken: $(readlink "$path"))"
    fi
    FAIL=$((FAIL + 1))
  fi
}

assert_nonempty() {
  local name="$1" path="$2"
  if [[ -s "$path" ]]; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (file is empty: $path)"
    FAIL=$((FAIL + 1))
  fi
}

# ══════════════════════════════════════════════════════════════
# 1. shared/rules/always/ — 3 core rules exist and are non-empty
# ══════════════════════════════════════════════════════════════

echo "=== shared/rules/always/ ==="

assert_dir_exists "shared/rules/always/ exists" "$SHARED_DIR/rules/always"
assert_file_exists "coding-standards.md exists" "$SHARED_DIR/rules/always/coding-standards.md"
assert_file_exists "copilot-conventions.md exists" "$SHARED_DIR/rules/always/copilot-conventions.md"
assert_file_exists "safety.md exists" "$SHARED_DIR/rules/always/safety.md"
assert_nonempty "coding-standards.md non-empty" "$SHARED_DIR/rules/always/coding-standards.md"
assert_nonempty "copilot-conventions.md non-empty" "$SHARED_DIR/rules/always/copilot-conventions.md"
assert_nonempty "safety.md non-empty" "$SHARED_DIR/rules/always/safety.md"

ALWAYS_COUNT=$(find "$SHARED_DIR/rules/always" -name '*.md' | wc -l | tr -d ' ')
assert_eq "exactly 3 always rules" "3" "$ALWAYS_COUNT"

# ══════════════════════════════════════════════════════════════
# 2. shared/rules/on-demand/ — 10 library rules exist
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== shared/rules/on-demand/ ==="

assert_dir_exists "shared/rules/on-demand/ exists" "$SHARED_DIR/rules/on-demand"

ON_DEMAND_FILES=(
  agent-team-protocol.md
  clarification-protocol.md
  environment-setup.md
  gcc-protocol.md
  integration-testing.md
  phase-workflow.md
  ralph-loop.md
  stack-constraints.md
  team-lead-efficiency.md
  token-efficiency.md
)

for f in "${ON_DEMAND_FILES[@]}"; do
  assert_file_exists "$f exists" "$SHARED_DIR/rules/on-demand/$f"
  assert_nonempty "$f non-empty" "$SHARED_DIR/rules/on-demand/$f"
done

ONDEMAND_COUNT=$(find "$SHARED_DIR/rules/on-demand" -name '*.md' | wc -l | tr -d ' ')
assert_eq "exactly 10 on-demand rules" "10" "$ONDEMAND_COUNT"

# ══════════════════════════════════════════════════════════════
# 3. shared/docs/ — tool-agnostic docs exist
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== shared/docs/ ==="

assert_dir_exists "shared/docs/ exists" "$SHARED_DIR/docs"

DOCS_FILES=(
  common-pitfalls.md
  delegation-best-practices.md
  error-reporting-template.md
  phase-recap-template.md
  ralph-loop-guide.md
  session-management.md
)

for f in "${DOCS_FILES[@]}"; do
  assert_file_exists "$f exists" "$SHARED_DIR/docs/$f"
  assert_nonempty "$f non-empty" "$SHARED_DIR/docs/$f"
done

# ══════════════════════════════════════════════════════════════
# 4. shared/templates/ — 7 project templates extracted
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== shared/templates/ ==="

assert_dir_exists "shared/templates/ exists" "$SHARED_DIR/templates"

TEMPLATE_TYPES=(ml-rag ml-app ml-langchain ml-n8n java-enterprise web-static web-dynamic)

for t in "${TEMPLATE_TYPES[@]}"; do
  assert_dir_exists "$t dir exists" "$SHARED_DIR/templates/$t"
  assert_file_exists "$t/PROJECT.md exists" "$SHARED_DIR/templates/$t/PROJECT.md"
  assert_nonempty "$t/PROJECT.md non-empty" "$SHARED_DIR/templates/$t/PROJECT.md"
  assert_dir_exists "$t/commands/ exists" "$SHARED_DIR/templates/$t/commands"
done

TEMPLATE_DIR_COUNT=$(find "$SHARED_DIR/templates" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
assert_eq "exactly 7 template dirs" "7" "$TEMPLATE_DIR_COUNT"

# Verify each template has at least one command file
for t in "${TEMPLATE_TYPES[@]}"; do
  CMD_COUNT=$(find "$SHARED_DIR/templates/$t/commands" -name '*.md' | wc -l | tr -d ' ')
  rc=0; [[ "$CMD_COUNT" -ge 1 ]] || rc=1
  assert_ok "$t has >=1 command file ($CMD_COUNT found)" "$rc"
done

# Verify all templates have a team-review command
for t in "${TEMPLATE_TYPES[@]}"; do
  assert_file_exists "$t has team-review.md" "$SHARED_DIR/templates/$t/commands/team-review.md"
done

# ══════════════════════════════════════════════════════════════
# 5. Template content fidelity — headers match expected stacks
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== template content fidelity ==="

assert_header() {
  local name="$1" file="$2" expected="$3"
  local actual
  actual=$(head -1 "$file")
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS: $name header"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name header (expected '$expected', got '$actual')"
    FAIL=$((FAIL + 1))
  fi
}

assert_header "ml-rag" "$SHARED_DIR/templates/ml-rag/PROJECT.md" "# ML/AI — RAG + Knowledge Graph"
assert_header "ml-app" "$SHARED_DIR/templates/ml-app/PROJECT.md" "# ML/AI — Full-Stack LLM Application"
assert_header "ml-langchain" "$SHARED_DIR/templates/ml-langchain/PROJECT.md" "# ML/AI — LangChain + LangGraph + LangSmith"
assert_header "ml-n8n" "$SHARED_DIR/templates/ml-n8n/PROJECT.md" "# ML/AI — n8n Workflow Automation"
assert_header "java-enterprise" "$SHARED_DIR/templates/java-enterprise/PROJECT.md" "# Enterprise Java Full-Stack Application"
assert_header "web-static" "$SHARED_DIR/templates/web-static/PROJECT.md" "# Static Website"
assert_header "web-dynamic" "$SHARED_DIR/templates/web-dynamic/PROJECT.md" "# Dynamic Web Application"

# Verify templates contain Agent Team section (structural check)
for t in "${TEMPLATE_TYPES[@]}"; do
  rc=0
  grep -q '## Agent Team' "$SHARED_DIR/templates/$t/PROJECT.md" || rc=1
  assert_ok "$t has Agent Team section" "$rc"
done

# ══════════════════════════════════════════════════════════════
# 6. Symlinks — claude_code/.claude/rules/ → shared/
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== symlinks: rules → shared/ ==="

for f in coding-standards.md copilot-conventions.md safety.md; do
  assert_symlink "rules/$f is symlink" "$CLAUDE_CODE_DIR/.claude/rules/$f"
  assert_symlink_resolves "rules/$f resolves" "$CLAUDE_CODE_DIR/.claude/rules/$f"
done

echo ""
echo "=== symlinks: rules-library → shared/ ==="

for f in "${ON_DEMAND_FILES[@]}"; do
  assert_symlink "rules-library/$f is symlink" "$CLAUDE_CODE_DIR/.claude/rules-library/$f"
  assert_symlink_resolves "rules-library/$f resolves" "$CLAUDE_CODE_DIR/.claude/rules-library/$f"
done

# ══════════════════════════════════════════════════════════════
# 7. Symlink content matches shared/ content (no divergence)
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== symlink content matches shared/ ==="

for f in coding-standards.md copilot-conventions.md safety.md; do
  rc=0
  diff -q "$CLAUDE_CODE_DIR/.claude/rules/$f" "$SHARED_DIR/rules/always/$f" >/dev/null 2>&1 || rc=1
  assert_ok "rules/$f content matches" "$rc"
done

for f in "${ON_DEMAND_FILES[@]}"; do
  rc=0
  diff -q "$CLAUDE_CODE_DIR/.claude/rules-library/$f" "$SHARED_DIR/rules/on-demand/$f" >/dev/null 2>&1 || rc=1
  assert_ok "rules-library/$f content matches" "$rc"
done

# ══════════════════════════════════════════════════════════════
# 8. claude-setup.sh — script syntax and SHARED_DIR variable
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== claude-setup.sh structure ==="

# Syntax check
rc=0; bash -n "$SETUP_SCRIPT" >/dev/null 2>&1 || rc=1
assert_ok "setup script syntax valid" "$rc"

# SHARED_DIR variable is defined
rc=0; grep -q 'SHARED_DIR=' "$SETUP_SCRIPT" || rc=1
assert_ok "SHARED_DIR variable defined" "$rc"

# Templates use cp from SHARED_DIR (not inline heredocs)
rc=0; grep -q 'cp "$SHARED_DIR/templates/' "$SETUP_SCRIPT" || rc=1
assert_ok "templates read from SHARED_DIR" "$rc"

# No remaining inline template heredocs (all 7 should be extracted)
HEREDOC_COUNT=$(grep -c "^cat > \"\$TEMPLATES_DIR/.*/CLAUDE.md\" << 'EOF'" "$SETUP_SCRIPT" 2>/dev/null || true)
HEREDOC_COUNT=$(echo "$HEREDOC_COUNT" | tr -d '[:space:]')
HEREDOC_COUNT="${HEREDOC_COUNT:-0}"
assert_eq "no inline template heredocs remain" "0" "$HEREDOC_COUNT"

# Rules section references shared/
rc=0; grep -q 'SHARED_DIR/rules/always' "$SETUP_SCRIPT" || rc=1
assert_ok "rules install uses shared/rules/always" "$rc"

rc=0; grep -q 'SHARED_DIR/rules/on-demand' "$SETUP_SCRIPT" || rc=1
assert_ok "rules-library install uses shared/rules/on-demand" "$rc"

# --sync references shared/
SYNC_SECTION=$(sed -n '/--sync/,/exit 0/p' "$SETUP_SCRIPT")
rc=0; echo "$SYNC_SECTION" | grep -q 'SHARED_DIR/rules/always' || rc=1
assert_ok "--sync uses shared/rules/always" "$rc"

rc=0; echo "$SYNC_SECTION" | grep -q 'SHARED_DIR/rules/on-demand' || rc=1
assert_ok "--sync uses shared/rules/on-demand" "$rc"

# ══════════════════════════════════════════════════════════════
# 9. Regression — Claude-specific files in adapter
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== regression: Claude-specific files in adapter ==="

# CLAUDE.md in adapter
assert_file_exists "adapter CLAUDE.md exists" "$ADAPTER_DIR/.claude/CLAUDE.md"

# settings.json in adapter
assert_file_exists "adapter settings.json exists" "$ADAPTER_DIR/.claude/settings.json"

# Agents in adapter
AGENT_FILES=(research.md plan.md build.md review.md code-simplifier.md doc-writer.md phase-recap.md security-review.md verify-app.md)
for f in "${AGENT_FILES[@]}"; do
  assert_file_exists "adapter agent $f exists" "$ADAPTER_DIR/.claude/agents/$f"
done

# Hooks in adapter
HOOK_FILES=(verify-on-stop.sh verify-after-edit.sh auto-format.sh protect-files.sh reinject-context.sh notify.sh)
for f in "${HOOK_FILES[@]}"; do
  assert_file_exists "adapter hook $f exists" "$ADAPTER_DIR/.claude/hooks/$f"
done

# Claude-specific docs in adapter
CLAUDE_DOCS=(hooks-guide.md subagents-guide.md claude-code-setup-cookbook.md claude-config-guide.md hooks-test-cases.md permissions-guide.md recommended-mcp-servers.md debugging-strategies.md)
for f in "${CLAUDE_DOCS[@]}"; do
  assert_file_exists "adapter doc $f exists" "$ADAPTER_DIR/docs/$f"
done

# Commands in adapter
assert_dir_exists "adapter commands/ exists" "$ADAPTER_DIR/.claude/commands"

# Wrapper still exists
assert_file_exists "wrapper claude-setup.sh exists" "$CLAUDE_CODE_DIR/claude-setup.sh"

# ══════════════════════════════════════════════════════════════
# 10. Regression — setup.sh essential sections intact
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== regression: setup.sh essential sections ==="

# Global CLAUDE.md section exists
rc=0; grep -q '# 1. GLOBAL CLAUDE.md' "$SETUP_SCRIPT" || rc=1
assert_ok "section 1 (GLOBAL CLAUDE.md) present" "$rc"

# Launcher install section exists
rc=0; grep -q '# 9. INSTALL LAUNCHER SCRIPT' "$SETUP_SCRIPT" || rc=1
assert_ok "section 9 (LAUNCHER) present" "$rc"

# Hooks section exists
rc=0; grep -q '# 10. GLOBAL HOOKS' "$SETUP_SCRIPT" || rc=1
assert_ok "section 10 (HOOKS) present" "$rc"

# Agents section exists
rc=0; grep -q '# 10b. GLOBAL AGENTS' "$SETUP_SCRIPT" || rc=1
assert_ok "section 10b (AGENTS) present" "$rc"

# Settings section exists
rc=0; grep -q '# 11. GLOBAL SETTINGS' "$SETUP_SCRIPT" || rc=1
assert_ok "section 11 (SETTINGS) present" "$rc"

# Summary section exists
rc=0; grep -q 'Setup Complete!' "$SETUP_SCRIPT" || rc=1
assert_ok "SUMMARY section present" "$rc"

# --sync handler exists
rc=0; grep -q '\-\-sync' "$SETUP_SCRIPT" || rc=1
assert_ok "--sync handler present" "$rc"

# --gcc handler exists
rc=0; grep -q '\-\-gcc' "$SETUP_SCRIPT" || rc=1
assert_ok "--gcc handler present" "$rc"

# jq dependency check exists
rc=0; grep -q 'command -v jq' "$SETUP_SCRIPT" || rc=1
assert_ok "jq dependency check present" "$rc"

# All 7 template sections exist
for t in "${TEMPLATE_TYPES[@]}"; do
  rc=0; grep -q "TEMPLATE: $t" "$SETUP_SCRIPT" || rc=1
  assert_ok "template section '$t' present in setup.sh" "$rc"
done

# Wrapper delegates to adapter
WRAPPER="$CLAUDE_CODE_DIR/claude-setup.sh"
rc=0; grep -q 'adapters/claude-code/setup.sh' "$WRAPPER" || rc=1
assert_ok "wrapper delegates to adapter setup.sh" "$rc"

# generate.sh exists and is executable
assert_file_exists "scripts/generate.sh exists" "$REPO_DIR/scripts/generate.sh"
rc=0; [[ -x "$REPO_DIR/scripts/generate.sh" ]] || rc=1
assert_ok "generate.sh is executable" "$rc"

# ══════════════════════════════════════════════════════════════
# 11. Install output — installed files match shared/ content
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== install output: ~/.claude/ matches shared/ ==="

INSTALL_DIR="$HOME/.claude"

# Rules match
for f in coding-standards.md copilot-conventions.md safety.md; do
  if [[ -f "$INSTALL_DIR/rules/$f" ]]; then
    rc=0; diff -q "$INSTALL_DIR/rules/$f" "$SHARED_DIR/rules/always/$f" >/dev/null 2>&1 || rc=1
    assert_ok "installed rules/$f matches shared/" "$rc"
  else
    echo "  FAIL: installed rules/$f not found (run setup.sh first)"
    FAIL=$((FAIL + 1))
  fi
done

# Rules library match
for f in "${ON_DEMAND_FILES[@]}"; do
  if [[ -f "$INSTALL_DIR/rules-library/$f" ]]; then
    rc=0; diff -q "$INSTALL_DIR/rules-library/$f" "$SHARED_DIR/rules/on-demand/$f" >/dev/null 2>&1 || rc=1
    assert_ok "installed rules-library/$f matches shared/" "$rc"
  else
    echo "  FAIL: installed rules-library/$f not found (run setup.sh first)"
    FAIL=$((FAIL + 1))
  fi
done

# Templates match (PROJECT.md → CLAUDE.md)
for t in "${TEMPLATE_TYPES[@]}"; do
  if [[ -f "$INSTALL_DIR/templates/$t/CLAUDE.md" ]]; then
    rc=0; diff -q "$INSTALL_DIR/templates/$t/CLAUDE.md" "$SHARED_DIR/templates/$t/PROJECT.md" >/dev/null 2>&1 || rc=1
    assert_ok "installed templates/$t/CLAUDE.md matches PROJECT.md" "$rc"
  else
    echo "  FAIL: installed templates/$t/CLAUDE.md not found (run setup.sh first)"
    FAIL=$((FAIL + 1))
  fi
done

# Template commands match
for t in "${TEMPLATE_TYPES[@]}"; do
  for cmd in "$SHARED_DIR/templates/$t/commands/"*.md; do
    cmd_name=$(basename "$cmd")
    if [[ -f "$INSTALL_DIR/templates/$t/commands/$cmd_name" ]]; then
      rc=0; diff -q "$INSTALL_DIR/templates/$t/commands/$cmd_name" "$cmd" >/dev/null 2>&1 || rc=1
      assert_ok "installed $t/commands/$cmd_name matches shared/" "$rc"
    else
      echo "  FAIL: installed $t/commands/$cmd_name not found"
      FAIL=$((FAIL + 1))
    fi
  done
done

# ══════════════════════════════════════════════════════════════
# 12. Harness Engineering — Architecture Rules + Struggle Diagnosis
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== harness engineering: architecture rules in templates ==="

for t in "${TEMPLATE_TYPES[@]}"; do
  rc=0
  grep -q '## .*Architecture Rules' "$SHARED_DIR/templates/$t/PROJECT.md" || rc=1
  assert_ok "$t has Architecture Rules section" "$rc"
done

echo ""
echo "=== harness engineering: struggle diagnosis in phase-recap ==="

rc=0
grep -q '### Struggle Diagnosis' "$SHARED_DIR/docs/phase-recap-template.md" || rc=1
assert_ok "phase-recap-template has Struggle Diagnosis section" "$rc"

echo ""
echo "=== harness engineering: retro command ==="

assert_file_exists "retro.md command exists" "$ADAPTER_DIR/.claude/commands/retro.md"
assert_nonempty "retro.md command non-empty" "$ADAPTER_DIR/.claude/commands/retro.md"

echo ""
echo "=== harness engineering: remediation hints in verify-after-edit ==="

rc=0
grep -q 'Remediation hints' "$ADAPTER_DIR/.claude/hooks/verify-after-edit.sh" || rc=1
assert_ok "verify-after-edit has remediation hints" "$rc"

rc=0
grep -q 'remediation.json' "$ADAPTER_DIR/.claude/hooks/verify-after-edit.sh" || rc=1
assert_ok "verify-after-edit supports remediation.json config" "$rc"

echo ""
echo "=== harness engineering: visual smoke test in verify-app ==="

rc=0
grep -q 'Visual Smoke Test' "$ADAPTER_DIR/.claude/agents/verify-app.md" || rc=1
assert_ok "verify-app has Visual Smoke Test section" "$rc"

echo ""
echo "=== harness engineering: post-build cleanup in build agent ==="

rc=0
grep -q 'Post-Build Cleanup' "$ADAPTER_DIR/.claude/agents/build.md" || rc=1
assert_ok "build agent has Post-Build Cleanup section" "$rc"

# ══════════════════════════════════════════════════════════════
# 13. Remediation.json — validation per template
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== remediation.json: shared templates ==="

for t in "${TEMPLATE_TYPES[@]}"; do
  RFILE="$SHARED_DIR/templates/$t/.claude/remediation.json"
  assert_file_exists "$t remediation.json exists" "$RFILE"
  assert_nonempty "$t remediation.json non-empty" "$RFILE"

  # Valid JSON
  rc=0; jq empty "$RFILE" >/dev/null 2>&1 || rc=1
  assert_ok "$t remediation.json is valid JSON" "$rc"

  # At least 3 patterns
  PATTERN_COUNT=$(jq '.patterns | length' "$RFILE" 2>/dev/null || echo "0")
  rc=0; [[ "$PATTERN_COUNT" -ge 3 ]] || rc=1
  assert_ok "$t remediation.json has >= 3 patterns ($PATTERN_COUNT found)" "$rc"

  # Each pattern has match + hint
  VALID_PATTERNS=$(jq '[.patterns[] | select(.match and .hint)] | length' "$RFILE" 2>/dev/null || echo "0")
  rc=0; [[ "$VALID_PATTERNS" == "$PATTERN_COUNT" ]] || rc=1
  assert_ok "$t all patterns have match + hint fields" "$rc"
done

# ══════════════════════════════════════════════════════════════
# 14. setup.sh copies .claude/ directories from templates
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== setup.sh: .claude/ directory copy ==="

rc=0; grep -q 'SHARED_DIR/templates/.*/\.claude' "$SETUP_SCRIPT" || rc=1
assert_ok "setup.sh copies .claude/ from templates" "$rc"

# ══════════════════════════════════════════════════════════════
# 15. Installed templates have remediation.json
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== install output: remediation.json matches shared/ ==="

for t in "${TEMPLATE_TYPES[@]}"; do
  INSTALLED="$INSTALL_DIR/templates/$t/.claude/remediation.json"
  SOURCE="$SHARED_DIR/templates/$t/.claude/remediation.json"
  if [[ -f "$INSTALLED" ]]; then
    rc=0; diff -q "$INSTALLED" "$SOURCE" >/dev/null 2>&1 || rc=1
    assert_ok "installed $t remediation.json matches shared/" "$rc"
  else
    echo "  FAIL: installed $t/.claude/remediation.json not found (run setup.sh first)"
    FAIL=$((FAIL + 1))
  fi
done

# ══════════════════════════════════════════════════════════════
# 16. Claude-specific docs — new docs exist
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== new Claude-specific docs ==="

assert_file_exists "permissions-guide.md exists" "$ADAPTER_DIR/docs/permissions-guide.md"
assert_nonempty "permissions-guide.md non-empty" "$ADAPTER_DIR/docs/permissions-guide.md"
assert_file_exists "recommended-mcp-servers.md exists" "$ADAPTER_DIR/docs/recommended-mcp-servers.md"
assert_nonempty "recommended-mcp-servers.md non-empty" "$ADAPTER_DIR/docs/recommended-mcp-servers.md"

# ══════════════════════════════════════════════════════════════
# 17. Remediation.json — architecture-violation patterns
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== remediation.json: architecture-violation patterns ==="

for t in "${TEMPLATE_TYPES[@]}"; do
  RFILE="$SHARED_DIR/templates/$t/.claude/remediation.json"
  ARCH_HINTS=$(jq '[.patterns[] | select(.hint | test("violation|Architecture|architecture|layer|domain|Legacy|Clean|Hexagonal|Provider|inline|credential|docstring|frontmatter|Client Component|endpoint"))] | length' "$RFILE" 2>/dev/null || echo "0")
  rc=0; [[ "$ARCH_HINTS" -ge 1 ]] || rc=1
  assert_ok "$t has architecture-violation patterns ($ARCH_HINTS found)" "$rc"
done

# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
