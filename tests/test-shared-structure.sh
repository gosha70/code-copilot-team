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
COUNTS_FILE="$REPO_DIR/tests/test-counts.env"
# shellcheck source=/dev/null
source "$COUNTS_FILE"
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
  alignment-maintenance.md
  common-pitfalls.md
  delegation-best-practices.md
  error-reporting-template.md
  phase-recap-template.md
  ralph-loop-guide.md
  session-management.md
)
DOCS_EXPECTED_COUNT=7

for f in "${DOCS_FILES[@]}"; do
  assert_file_exists "$f exists" "$SHARED_DIR/docs/$f"
  assert_nonempty "$f non-empty" "$SHARED_DIR/docs/$f"
done

DOCS_COUNT=$(find "$SHARED_DIR/docs" -maxdepth 1 -type f -name '*.md' | wc -l | tr -d ' ')
assert_eq "exactly ${DOCS_EXPECTED_COUNT} shared docs" "$DOCS_EXPECTED_COUNT" "$DOCS_COUNT"

DOCS_LISTED_COUNT="${#DOCS_FILES[@]}"
assert_eq "DOCS_FILES enumerates all shared docs" "$DOCS_COUNT" "$DOCS_LISTED_COUNT"

# ══════════════════════════════════════════════════════════════
# 4. shared/templates/ — 7 project templates extracted
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== shared/templates/ ==="

assert_dir_exists "shared/templates/ exists" "$SHARED_DIR/templates"

TEMPLATE_TYPES=(ml-rag ml-app ml-langchain ml-n8n java-enterprise web-static web-dynamic java-tooling)

for t in "${TEMPLATE_TYPES[@]}"; do
  assert_dir_exists "$t dir exists" "$SHARED_DIR/templates/$t"
  assert_file_exists "$t/PROJECT.md exists" "$SHARED_DIR/templates/$t/PROJECT.md"
  assert_nonempty "$t/PROJECT.md non-empty" "$SHARED_DIR/templates/$t/PROJECT.md"
  assert_dir_exists "$t/commands/ exists" "$SHARED_DIR/templates/$t/commands"
done

TEMPLATE_DIR_COUNT=$(find "$SHARED_DIR/templates" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
assert_eq "exactly 8 template dirs" "8" "$TEMPLATE_DIR_COUNT"

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
assert_header "java-tooling" "$SHARED_DIR/templates/java-tooling/PROJECT.md" "# Java Developer Tooling — Annotation Processors, Gradle Plugins & Code Generators"

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
rc=0; grep -q '# 10. INSTALL LAUNCHER SCRIPT' "$SETUP_SCRIPT" || rc=1
assert_ok "section 10 (LAUNCHER) present" "$rc"

# Hooks section exists
rc=0; grep -q '# 11. GLOBAL HOOKS' "$SETUP_SCRIPT" || rc=1
assert_ok "section 11 (HOOKS) present" "$rc"

# Agents section exists
rc=0; grep -q '# 11b. GLOBAL AGENTS' "$SETUP_SCRIPT" || rc=1
assert_ok "section 11b (AGENTS) present" "$rc"

# Settings section exists
rc=0; grep -q '# 12. GLOBAL SETTINGS' "$SETUP_SCRIPT" || rc=1
assert_ok "section 12 (SETTINGS) present" "$rc"

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
echo "=== alignment maintenance docs ==="

assert_file_exists "alignment-maintenance.md exists" "$SHARED_DIR/docs/alignment-maintenance.md"
assert_nonempty "alignment-maintenance.md non-empty" "$SHARED_DIR/docs/alignment-maintenance.md"

rc=0
grep -q 'bash tests/test-generate.sh' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance includes test-generate command" "$rc"

rc=0
grep -q 'bash tests/test-hooks.sh' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance includes test-hooks command" "$rc"

rc=0
grep -q 'bash tests/test-shared-structure.sh' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance includes test-shared-structure command" "$rc"

rc=0
grep -q 'bash adapters/claude-code/setup.sh' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance includes setup.sh command" "$rc"

SETUP_DOC_LINE=$(grep -n 'bash adapters/claude-code/setup.sh' "$SHARED_DIR/docs/alignment-maintenance.md" | head -n 1 | cut -d: -f1)
STRUCT_DOC_LINE=$(grep -n 'bash tests/test-shared-structure.sh' "$SHARED_DIR/docs/alignment-maintenance.md" | head -n 1 | cut -d: -f1)
rc=0
[[ -n "$SETUP_DOC_LINE" && -n "$STRUCT_DOC_LINE" && "$SETUP_DOC_LINE" -lt "$STRUCT_DOC_LINE" ]] || rc=1
assert_ok "alignment-maintenance runs setup.sh before structure test" "$rc"

rc=0
grep -q 'tests/test-counts.env' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance references test-counts source of truth" "$rc"

rc=0
grep -q '.github/workflows/sync-check.yml' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance references sync-check workflow contract" "$rc"

rc=0
grep -Eq '\[ \].*tests/test-counts\.env.*expected totals.*suite outputs' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes test-counts parity item" "$rc"

rc=0
grep -Eq '\[ \].*sync-check\.yml.*full gate coverage.*all suites.*setup.*structure test' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes sync-check coverage item" "$rc"

rc=0
grep -Eq '\[ \].*All three test suites pass.*zero failures' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes all-suites-pass item" "$rc"

rc=0
grep -Eq '\[ \].*README test counts.*accurate' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes README parity item" "$rc"

rc=0
grep -Eq '\[ \].*CONTRIBUTING.*current contributor workflow' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes CONTRIBUTING workflow item" "$rc"

rc=0
grep -Eq '\[ \].*No adapter drift.*scripts/generate\.sh' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes adapter-drift item" "$rc"

rc=0
grep -Eq '\[ \].*manual verification run.*changed behavior' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes manual-verification item" "$rc"

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

rc=0
grep -q 'Runtime Observability' "$ADAPTER_DIR/.claude/agents/verify-app.md" || rc=1
assert_ok "verify-app has Runtime Observability section" "$rc"

for field in "UI smoke" "Console" "Network" "Visual"; do
  rc=0
  grep -q "$field" "$ADAPTER_DIR/.claude/agents/verify-app.md" || rc=1
  assert_ok "verify-app report includes $field field" "$rc"
done

echo ""
echo "=== web template team-review observability fields ==="

for cmd in \
  "$SHARED_DIR/templates/web-dynamic/commands/team-review.md" \
  "$SHARED_DIR/templates/web-static/commands/team-review.md"; do
  for field in "ui-smoke" "console" "network" "visual"; do
    rc=0
    grep -q "$field" "$cmd" || rc=1
    assert_ok "$(basename "$(dirname "$(dirname "$cmd")")") team-review includes $field" "$rc"
  done
done

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
# 18. README claims — test-count lines are current
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== README test-count claims ==="

rc=0
grep -Eq "test-hooks\\.sh[[:space:]]+${TEST_HOOKS_EXPECTED_PASS} hook tests" "$REPO_DIR/README.md" || rc=1
assert_ok "README lists ${TEST_HOOKS_EXPECTED_PASS} hook tests" "$rc"

rc=0
grep -Eq "test-generate\\.sh[[:space:]]+${TEST_GENERATE_EXPECTED_PASS} generation \\+ adapter tests" "$REPO_DIR/README.md" || rc=1
assert_ok "README lists ${TEST_GENERATE_EXPECTED_PASS} generation + adapter tests" "$rc"

rc=0
grep -Eq "test-shared-structure\\.sh[[:space:]]+${TEST_SHARED_STRUCTURE_EXPECTED_PASS} structure \\+ content tests" "$REPO_DIR/README.md" || rc=1
assert_ok "README lists ${TEST_SHARED_STRUCTURE_EXPECTED_PASS} structure + content tests" "$rc"

rc=0
grep -Eq "docs/[[:space:]]+${DOCS_EXPECTED_COUNT} tool-agnostic reference docs" "$REPO_DIR/README.md" || rc=1
assert_ok "README lists ${DOCS_EXPECTED_COUNT} tool-agnostic reference docs" "$rc"

rc=0
grep -Eq "rules/always/[[:space:]]+3 global rules" "$REPO_DIR/README.md" || rc=1
assert_ok "README lists 3 global always rules" "$rc"

rc=0
grep -Eq "rules/on-demand/[[:space:]]+10 rules loaded by phase agents" "$REPO_DIR/README.md" || rc=1
assert_ok "README lists 10 on-demand rules" "$rc"

rc=0
grep -Eq "templates/[[:space:]]+8 stacks" "$REPO_DIR/README.md" || rc=1
assert_ok "README lists 8 template stacks" "$rc"

rc=0
grep -Eq "codex/.*5 skills" "$REPO_DIR/README.md" || rc=1
assert_ok "README lists 5 codex skills" "$rc"

README_SHARED_DOC_UNIQUE_COUNT=$(grep -Eo 'shared/docs/[A-Za-z0-9._-]+\.md' "$REPO_DIR/README.md" | sort -u | wc -l | tr -d ' ')
assert_eq "README has ${DOCS_EXPECTED_COUNT} unique shared docs links" "$DOCS_EXPECTED_COUNT" "$README_SHARED_DOC_UNIQUE_COUNT"

rc=0
for f in "${DOCS_FILES[@]}"; do
  grep -q "shared/docs/$f" "$REPO_DIR/README.md" || rc=1
done
assert_ok "README references every shared docs file" "$rc"

README_SHARED_DOCS_SECTION=$(
  awk '
    /^\*\*Shared \(all tools\):\*\*/ {in_section=1; next}
    /^## / && in_section {exit}
    in_section {print}
  ' "$REPO_DIR/README.md"
)

README_SHARED_SECTION_LINK_COUNT=$(echo "$README_SHARED_DOCS_SECTION" | grep -Eo 'shared/docs/[A-Za-z0-9._-]+\.md' | sort -u | wc -l | tr -d ' ')
assert_eq "README shared-docs section lists ${DOCS_EXPECTED_COUNT} unique links" "$DOCS_EXPECTED_COUNT" "$README_SHARED_SECTION_LINK_COUNT"

rc=0
for f in "${DOCS_FILES[@]}"; do
  echo "$README_SHARED_DOCS_SECTION" | grep -q "shared/docs/$f" || rc=1
done
assert_ok "README shared-docs section references every shared docs file" "$rc"

README_CLAUDE_DOCS=(
  claude-code-setup-cookbook.md
  claude-config-guide.md
  hooks-guide.md
  subagents-guide.md
  agent-traces.md
  debugging-strategies.md
  permissions-guide.md
  recommended-mcp-servers.md
)
README_CLAUDE_DOCS_EXPECTED_COUNT="${#README_CLAUDE_DOCS[@]}"

README_CLAUDE_DOCS_SECTION=$(
  awk '
    /^\*\*Claude Code specific:\*\*/ {in_section=1; next}
    /^\*\*Shared \(all tools\):\*\*/ && in_section {exit}
    in_section {print}
  ' "$REPO_DIR/README.md"
)

README_CLAUDE_SECTION_LINK_COUNT=$(echo "$README_CLAUDE_DOCS_SECTION" | grep -Eo 'adapters/claude-code/docs/[A-Za-z0-9._-]+\.md' | sort -u | wc -l | tr -d ' ')
assert_eq "README Claude-docs section lists ${README_CLAUDE_DOCS_EXPECTED_COUNT} unique links" "$README_CLAUDE_DOCS_EXPECTED_COUNT" "$README_CLAUDE_SECTION_LINK_COUNT"

rc=0
for f in "${README_CLAUDE_DOCS[@]}"; do
  echo "$README_CLAUDE_DOCS_SECTION" | grep -q "adapters/claude-code/docs/$f" || rc=1
done
assert_ok "README Claude-docs section references expected curated docs" "$rc"

# ══════════════════════════════════════════════════════════════
# 19. test-counts contract
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== test-counts contract ==="

assert_file_exists "test-counts.env exists" "$REPO_DIR/tests/test-counts.env"
assert_nonempty "test-counts.env non-empty" "$REPO_DIR/tests/test-counts.env"

rc=0
grep -Eq '^TEST_GENERATE_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_GENERATE_EXPECTED_PASS numeric value" "$rc"

rc=0
grep -Eq '^TEST_HOOKS_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_HOOKS_EXPECTED_PASS numeric value" "$rc"

rc=0
grep -Eq '^TEST_SHARED_STRUCTURE_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_SHARED_STRUCTURE_EXPECTED_PASS numeric value" "$rc"

COUNT_VARS=$(grep -Ec '^TEST_[A-Z_]+_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env")
assert_eq "test-counts has exactly 3 expected-pass variables" "3" "$COUNT_VARS"

rc=0
grep -q 'source "\$COUNTS_FILE"' "$REPO_DIR/tests/test-generate.sh" || rc=1
assert_ok "test-generate sources count contract" "$rc"

rc=0
grep -q 'source "\$COUNTS_FILE"' "$REPO_DIR/tests/test-hooks.sh" || rc=1
assert_ok "test-hooks sources count contract" "$rc"

rc=0
grep -q 'source "\$COUNTS_FILE"' "$REPO_DIR/tests/test-shared-structure.sh" || rc=1
assert_ok "test-shared-structure sources count contract" "$rc"

rc=0
grep -q 'TEST_GENERATE_EXPECTED_PASS' "$REPO_DIR/tests/test-generate.sh" || rc=1
assert_ok "test-generate uses expected-pass variable" "$rc"

rc=0
grep -q 'TEST_HOOKS_EXPECTED_PASS' "$REPO_DIR/tests/test-hooks.sh" || rc=1
assert_ok "test-hooks uses expected-pass variable" "$rc"

rc=0
grep -q 'TEST_SHARED_STRUCTURE_EXPECTED_PASS' "$REPO_DIR/tests/test-shared-structure.sh" || rc=1
assert_ok "test-shared-structure uses expected-pass variable" "$rc"

# ══════════════════════════════════════════════════════════════
# 20. CONTRIBUTING governance references
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== CONTRIBUTING governance references ==="

rc=0
grep -q 'tests/test-counts.env' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING references test-counts source of truth" "$rc"

rc=0
grep -q '.github/workflows/sync-check.yml' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING references sync-check workflow contract" "$rc"

rc=0
grep -q 'Do not open public issues for security vulnerabilities' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING states no public issues for vulnerabilities" "$rc"

rc=0
grep -q '\[SECURITY.md\](SECURITY.md)' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING links SECURITY.md reporting policy" "$rc"

rc=0
grep -q 'bash tests/test-generate.sh' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING includes test-generate command" "$rc"

rc=0
grep -q 'bash tests/test-hooks.sh' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING includes test-hooks command" "$rc"

rc=0
grep -q 'bash tests/test-shared-structure.sh' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING includes test-shared-structure command" "$rc"

rc=0
grep -q 'bash adapters/claude-code/setup.sh' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING includes setup.sh command" "$rc"

CONTRIB_ALIGNMENT_SECTION=$(
  awk '
    /^## Ongoing Alignment Checks/ {in_section=1; next}
    /^## / && in_section {exit}
    in_section {print}
  ' "$REPO_DIR/CONTRIBUTING.md"
)
SETUP_CONTRIB_LINE=$(echo "$CONTRIB_ALIGNMENT_SECTION" | nl -ba | awk '/bash adapters\/claude-code\/setup\.sh/{print $1; exit}')
STRUCT_CONTRIB_LINE=$(echo "$CONTRIB_ALIGNMENT_SECTION" | nl -ba | awk '/bash tests\/test-shared-structure\.sh/{print $1; exit}')
rc=0
[[ -n "$SETUP_CONTRIB_LINE" && -n "$STRUCT_CONTRIB_LINE" && "$SETUP_CONTRIB_LINE" -lt "$STRUCT_CONTRIB_LINE" ]] || rc=1
assert_ok "CONTRIBUTING runs setup.sh before structure test" "$rc"

rc=0
grep -q 'shared/docs/alignment-maintenance.md' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING references alignment-maintenance checklist" "$rc"

rc=0
grep -q '\./scripts/generate.sh' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING references scripts/generate.sh regeneration flow" "$rc"

# ══════════════════════════════════════════════════════════════
# 21. CI workflow coverage — sync-check enforces full gates
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== CI workflow coverage ==="

WORKFLOW_FILE="$REPO_DIR/.github/workflows/sync-check.yml"
assert_file_exists "sync-check workflow exists" "$WORKFLOW_FILE"
assert_nonempty "sync-check workflow non-empty" "$WORKFLOW_FILE"

rc=0
grep -q 'bash tests/test-generate.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check runs test-generate.sh" "$rc"

rc=0
grep -q 'bash tests/test-hooks.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check runs test-hooks.sh" "$rc"

rc=0
grep -q 'bash tests/test-shared-structure.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check runs test-shared-structure.sh" "$rc"

rc=0
grep -q 'bash scripts/generate.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check runs scripts/generate.sh" "$rc"

rc=0
grep -q 'git diff --exit-code adapters/' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check checks adapter drift via git diff" "$rc"

# Ensure setup.sh appears in the shared-structure step before test execution.
SHARED_STEP=$(
  awk '
    /- name: Run shared structure tests/ {in_step=1; next}
    /^      - name:/ && in_step {exit}
    in_step {print}
  ' "$WORKFLOW_FILE"
)
SETUP_LINE=$(echo "$SHARED_STEP" | nl -ba | awk '/bash adapters\/claude-code\/setup\.sh/{print $1; exit}')
STRUCT_LINE=$(echo "$SHARED_STEP" | nl -ba | awk '/bash tests\/test-shared-structure\.sh/{print $1; exit}')
rc=0
[[ -n "$SETUP_LINE" && -n "$STRUCT_LINE" && "$SETUP_LINE" -lt "$STRUCT_LINE" ]] || rc=1
assert_ok "sync-check runs setup.sh before structure tests" "$rc"

rc=0
grep -Eq 'HOME:[[:space:]]+\$\{\{ runner\.temp \}\}/cct-home' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check uses isolated HOME for structure tests" "$rc"

TESTS_PATH_COUNT=$(grep -Fc "'tests/**'" "$WORKFLOW_FILE")
assert_eq "sync-check triggers on tests/** changes" "2" "$TESTS_PATH_COUNT"

SHARED_PATH_COUNT=$(grep -Fc "'shared/**'" "$WORKFLOW_FILE")
assert_eq "sync-check triggers on shared/** changes" "2" "$SHARED_PATH_COUNT"

SCRIPTS_PATH_COUNT=$(grep -Fc "'scripts/generate.sh'" "$WORKFLOW_FILE")
assert_eq "sync-check triggers on scripts/generate.sh changes" "2" "$SCRIPTS_PATH_COUNT"

ADAPTERS_PATH_COUNT=$(grep -Fc "'adapters/**'" "$WORKFLOW_FILE")
assert_eq "sync-check triggers on adapters/** changes" "2" "$ADAPTERS_PATH_COUNT"

README_PATH_COUNT=$(grep -Fc "'README.md'" "$WORKFLOW_FILE")
assert_eq "sync-check triggers on README.md changes" "2" "$README_PATH_COUNT"

CONTRIB_PATH_COUNT=$(grep -Fc "'CONTRIBUTING.md'" "$WORKFLOW_FILE")
assert_eq "sync-check triggers on CONTRIBUTING.md changes" "2" "$CONTRIB_PATH_COUNT"

WORKFLOW_PATH_COUNT=$(grep -Fc "'.github/workflows/sync-check.yml'" "$WORKFLOW_FILE")
assert_eq "sync-check triggers on workflow file changes" "2" "$WORKFLOW_PATH_COUNT"

# ══════════════════════════════════════════════════════════════
# 22. GitHub community standards files
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== community standards files ==="

assert_file_exists "CODE_OF_CONDUCT.md exists" "$REPO_DIR/CODE_OF_CONDUCT.md"
assert_nonempty "CODE_OF_CONDUCT.md non-empty" "$REPO_DIR/CODE_OF_CONDUCT.md"

assert_file_exists ".github/CODEOWNERS exists" "$REPO_DIR/.github/CODEOWNERS"
assert_nonempty ".github/CODEOWNERS non-empty" "$REPO_DIR/.github/CODEOWNERS"

rc=0
grep -q '^\* @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS has default owner" "$rc"

rc=0
grep -q '^/CODE_OF_CONDUCT.md @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes CODE_OF_CONDUCT ownership" "$rc"

rc=0
grep -q '^/SECURITY.md @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes SECURITY ownership" "$rc"

rc=0
grep -q '^/CONTRIBUTING.md @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes CONTRIBUTING ownership" "$rc"

rc=0
grep -q '^/README.md @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes README ownership" "$rc"

rc=0
grep -q '^/\.github/ISSUE_TEMPLATE/ @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes issue templates ownership" "$rc"

rc=0
grep -q '^/\.github/pull_request_template\.md @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes pull request template ownership" "$rc"

rc=0
grep -q '^## Our Standards' "$REPO_DIR/CODE_OF_CONDUCT.md" || rc=1
assert_ok "CODE_OF_CONDUCT has Our Standards section" "$rc"

rc=0
grep -q '^## Enforcement' "$REPO_DIR/CODE_OF_CONDUCT.md" || rc=1
assert_ok "CODE_OF_CONDUCT has Enforcement section" "$rc"

rc=0
grep -q 'https://github.com/gosha70' "$REPO_DIR/CODE_OF_CONDUCT.md" || rc=1
assert_ok "CODE_OF_CONDUCT includes owner profile contact link" "$rc"

rc=0
grep -q 'avoid opening public issues' "$REPO_DIR/CODE_OF_CONDUCT.md" || rc=1
assert_ok "CODE_OF_CONDUCT discourages public conduct reports" "$rc"

rc=0
if grep -q '\[CoC\]' "$REPO_DIR/CODE_OF_CONDUCT.md"; then
  rc=1
fi
assert_ok "CODE_OF_CONDUCT omits legacy public [CoC] issue flow" "$rc"

assert_file_exists "SECURITY.md exists" "$REPO_DIR/SECURITY.md"
assert_nonempty "SECURITY.md non-empty" "$REPO_DIR/SECURITY.md"

rc=0
grep -q '^## Supported Versions' "$REPO_DIR/SECURITY.md" || rc=1
assert_ok "SECURITY has Supported Versions section" "$rc"

rc=0
grep -q '^## Reporting a Vulnerability' "$REPO_DIR/SECURITY.md" || rc=1
assert_ok "SECURITY has Reporting a Vulnerability section" "$rc"

rc=0
grep -qE '^\| `master`[[:space:]]*\| :white_check_mark: \|$' "$REPO_DIR/SECURITY.md" || rc=1
assert_ok "SECURITY supported version row matches default branch (master)" "$rc"

assert_dir_exists ".github/ISSUE_TEMPLATE exists" "$REPO_DIR/.github/ISSUE_TEMPLATE"
assert_file_exists "issue template config.yml exists" "$REPO_DIR/.github/ISSUE_TEMPLATE/config.yml"
assert_nonempty "issue template config.yml non-empty" "$REPO_DIR/.github/ISSUE_TEMPLATE/config.yml"

rc=0
grep -q '^blank_issues_enabled:[[:space:]]*false' "$REPO_DIR/.github/ISSUE_TEMPLATE/config.yml" || rc=1
assert_ok "issue template config disables blank issues" "$rc"

rc=0
grep -q '/security/policy' "$REPO_DIR/.github/ISSUE_TEMPLATE/config.yml" || rc=1
assert_ok "issue template config references security policy" "$rc"

rc=0
grep -q '/CODE_OF_CONDUCT.md' "$REPO_DIR/.github/ISSUE_TEMPLATE/config.yml" || rc=1
assert_ok "issue template config references Code of Conduct" "$rc"

rc=0
grep -q '^    url: https://github.com/gosha70$' "$REPO_DIR/.github/ISSUE_TEMPLATE/config.yml" || rc=1
assert_ok "issue template config references private conduct contact URL" "$rc"

rc=0
grep -q '/security/advisories/new' "$REPO_DIR/.github/ISSUE_TEMPLATE/config.yml" || rc=1
assert_ok "issue template config references advisories submission URL" "$rc"

assert_file_exists "bug_report.md template exists" "$REPO_DIR/.github/ISSUE_TEMPLATE/bug_report.md"
assert_nonempty "bug_report.md template non-empty" "$REPO_DIR/.github/ISSUE_TEMPLATE/bug_report.md"

rc=0
grep -q '^name: Bug report' "$REPO_DIR/.github/ISSUE_TEMPLATE/bug_report.md" || rc=1
assert_ok "bug_report template has name field" "$rc"

rc=0
grep -q 'SECURITY.md' "$REPO_DIR/.github/ISSUE_TEMPLATE/bug_report.md" || rc=1
assert_ok "bug_report template references SECURITY.md for vulnerabilities" "$rc"

rc=0
grep -q '/security/advisories/new' "$REPO_DIR/.github/ISSUE_TEMPLATE/bug_report.md" || rc=1
assert_ok "bug_report template references advisories submission URL" "$rc"

rc=0
grep -q '/security/advisories/new' "$REPO_DIR/SECURITY.md" || rc=1
assert_ok "SECURITY.md includes direct advisories submission URL" "$rc"

assert_file_exists "feature_request.md template exists" "$REPO_DIR/.github/ISSUE_TEMPLATE/feature_request.md"
assert_nonempty "feature_request.md template non-empty" "$REPO_DIR/.github/ISSUE_TEMPLATE/feature_request.md"

rc=0
grep -q '^name: Feature request' "$REPO_DIR/.github/ISSUE_TEMPLATE/feature_request.md" || rc=1
assert_ok "feature_request template has name field" "$rc"

assert_file_exists "pull_request_template.md exists" "$REPO_DIR/.github/pull_request_template.md"
assert_nonempty "pull_request_template.md non-empty" "$REPO_DIR/.github/pull_request_template.md"

rc=0
grep -q '^## Validation' "$REPO_DIR/.github/pull_request_template.md" || rc=1
assert_ok "pull_request_template has Validation section" "$rc"

rc=0
grep -q 'Security-sensitive findings were handled privately per `SECURITY.md`' "$REPO_DIR/.github/pull_request_template.md" || rc=1
assert_ok "pull_request_template has SECURITY.md handling checklist item" "$rc"

rc=0
grep -q '^## Community Standards' "$REPO_DIR/README.md" || rc=1
assert_ok "README has Community Standards section" "$rc"

README_COMMUNITY_SECTION=$(
  awk '
    /^## Community Standards/ {in_section=1; next}
    /^## / && in_section {exit}
    in_section {print}
  ' "$REPO_DIR/README.md"
)

README_COMMUNITY_LINK_COUNT=$(echo "$README_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | wc -l | tr -d ' ')
assert_eq "README community-standards section lists 5 links" "5" "$README_COMMUNITY_LINK_COUNT"

README_COMMUNITY_UNIQUE_LINK_COUNT=$(echo "$README_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | sort -u | wc -l | tr -d ' ')
assert_eq "README community-standards section links are unique" "5" "$README_COMMUNITY_UNIQUE_LINK_COUNT"

rc=0
echo "$README_COMMUNITY_SECTION" | grep -Fq '[Code of Conduct](CODE_OF_CONDUCT.md)' || rc=1
assert_ok "README community-standards includes Code of Conduct link" "$rc"

rc=0
echo "$README_COMMUNITY_SECTION" | grep -Fq '[Code Owners](.github/CODEOWNERS)' || rc=1
assert_ok "README community-standards includes Code Owners link" "$rc"

rc=0
echo "$README_COMMUNITY_SECTION" | grep -Fq '[Security Policy](SECURITY.md)' || rc=1
assert_ok "README community-standards includes Security Policy link" "$rc"

rc=0
echo "$README_COMMUNITY_SECTION" | grep -Fq '[Issue Templates](.github/ISSUE_TEMPLATE/)' || rc=1
assert_ok "README community-standards includes Issue Templates link" "$rc"

rc=0
echo "$README_COMMUNITY_SECTION" | grep -Fq '[Pull Request Template](.github/pull_request_template.md)' || rc=1
assert_ok "README community-standards includes Pull Request Template link" "$rc"

rc=0
grep -q '^## Community Standards' "$REPO_DIR/CONTRIBUTING.md" || rc=1
assert_ok "CONTRIBUTING has Community Standards section" "$rc"

CONTRIBUTING_COMMUNITY_SECTION=$(
  awk '
    /^## Community Standards/ {in_section=1; next}
    /^## / && in_section {exit}
    in_section {print}
  ' "$REPO_DIR/CONTRIBUTING.md"
)

CONTRIBUTING_COMMUNITY_LINK_COUNT=$(echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | wc -l | tr -d ' ')
assert_eq "CONTRIBUTING community-standards section lists 5 links" "5" "$CONTRIBUTING_COMMUNITY_LINK_COUNT"

CONTRIBUTING_COMMUNITY_UNIQUE_LINK_COUNT=$(echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | sort -u | wc -l | tr -d ' ')
assert_eq "CONTRIBUTING community-standards section links are unique" "5" "$CONTRIBUTING_COMMUNITY_UNIQUE_LINK_COUNT"

rc=0
echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Fq '[Code of Conduct](CODE_OF_CONDUCT.md)' || rc=1
assert_ok "CONTRIBUTING community-standards includes Code of Conduct link" "$rc"

rc=0
echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Fq '[Code Owners](.github/CODEOWNERS)' || rc=1
assert_ok "CONTRIBUTING community-standards includes Code Owners link" "$rc"

rc=0
echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Fq '[Security Policy](SECURITY.md)' || rc=1
assert_ok "CONTRIBUTING community-standards includes Security Policy link" "$rc"

rc=0
echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Fq '[Issue Templates](.github/ISSUE_TEMPLATE/)' || rc=1
assert_ok "CONTRIBUTING community-standards includes Issue Templates link" "$rc"

rc=0
echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Fq '[Pull Request Template](.github/pull_request_template.md)' || rc=1
assert_ok "CONTRIBUTING community-standards includes Pull Request Template link" "$rc"

rc=0
if ! diff -u \
  <(echo "$README_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | sort) \
  <(echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | sort) >/dev/null; then
  rc=1
fi
assert_ok "README and CONTRIBUTING community-standards link sets match" "$rc"

if [[ "$PASS" -ne "$TEST_SHARED_STRUCTURE_EXPECTED_PASS" ]]; then
  echo "  FAIL: assertion-count drift (expected $TEST_SHARED_STRUCTURE_EXPECTED_PASS, got $PASS)"
  FAIL=$((FAIL + 1))
fi

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
