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
# 1. shared/skills/ — 19 skills exist in SKILL.md format
# ══════════════════════════════════════════════════════════════

echo "=== shared/skills/ ==="

SKILLS_DIR_PATH="$SHARED_DIR/skills"
assert_dir_exists "shared/skills/ exists" "$SKILLS_DIR_PATH"

SKILL_NAMES=(
  agent-team-protocol
  clarification-protocol
  coding-standards
  copilot-conventions
  copyright-headers
  environment-setup
  infra-verification
  integration-testing
  memkernel-memory
  opus-4-7-features
  origin-confirmation
  phase-workflow
  provider-collaboration-protocol
  ralph-loop
  review-loop
  safety
  spec-workflow
  stack-constraints
  team-lead-efficiency
  token-efficiency
  wiki-first-query
)

for s in "${SKILL_NAMES[@]}"; do
  assert_dir_exists "$s/ exists" "$SKILLS_DIR_PATH/$s"
  assert_file_exists "$s/SKILL.md exists" "$SKILLS_DIR_PATH/$s/SKILL.md"
  assert_nonempty "$s/SKILL.md non-empty" "$SKILLS_DIR_PATH/$s/SKILL.md"
done

SKILL_COUNT=$(find "$SKILLS_DIR_PATH" -name 'SKILL.md' | wc -l | tr -d ' ')
assert_eq "exactly 24 skills" "24" "$SKILL_COUNT"

# Verify SKILL.md frontmatter has required fields
for s in "${SKILL_NAMES[@]}"; do
  SKILL_FILE="$SKILLS_DIR_PATH/$s/SKILL.md"
  rc=0; grep -q '^name:' "$SKILL_FILE" || rc=1
  assert_ok "$s has name field" "$rc"
  rc=0; grep -q '^description:' "$SKILL_FILE" || rc=1
  assert_ok "$s has description field" "$rc"
  # Verify name matches directory
  SKILL_NAME_VALUE=$(sed -n '/^---$/,/^---$/p' "$SKILL_FILE" | grep '^name:' | sed 's/^name: *//')
  assert_eq "$s name matches directory" "$s" "$SKILL_NAME_VALUE"
done

# ══════════════════════════════════════════════════════════════
# 3. shared/docs/ — tool-agnostic docs exist
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== shared/docs/ ==="

assert_dir_exists "shared/docs/ exists" "$SHARED_DIR/docs"

DOCS_FILES=(
  alignment-maintenance.md
  code-reviewer-assistant-guide.md
  common-pitfalls.md
  delegation-best-practices.md
  error-reporting-template.md
  phase-recap-template.md
  ralph-loop-guide.md
  session-management.md
)
DOCS_EXPECTED_COUNT=8

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

TEMPLATE_TYPES=(ml-rag ml-app ml-utils ml-langchain ml-n8n java-enterprise web-static web-dynamic java-tooling domain-pack gradle-plugin)

for t in "${TEMPLATE_TYPES[@]}"; do
  assert_dir_exists "$t dir exists" "$SHARED_DIR/templates/$t"
  assert_file_exists "$t/PROJECT.md exists" "$SHARED_DIR/templates/$t/PROJECT.md"
  assert_nonempty "$t/PROJECT.md non-empty" "$SHARED_DIR/templates/$t/PROJECT.md"
  assert_dir_exists "$t/commands/ exists" "$SHARED_DIR/templates/$t/commands"
done

TEMPLATE_DIR_COUNT=$(find "$SHARED_DIR/templates" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
assert_eq "exactly 15 template dirs (routing arrived with #248 T1, llm with #479)" "15" "$TEMPLATE_DIR_COUNT"

# Verify SDD templates exist
assert_dir_exists "sdd dir exists" "$SHARED_DIR/templates/sdd"
assert_file_exists "sdd/spec-template.md exists" "$SHARED_DIR/templates/sdd/spec-template.md"
assert_nonempty "sdd/spec-template.md non-empty" "$SHARED_DIR/templates/sdd/spec-template.md"
assert_file_exists "sdd/plan-template.md exists" "$SHARED_DIR/templates/sdd/plan-template.md"
assert_nonempty "sdd/plan-template.md non-empty" "$SHARED_DIR/templates/sdd/plan-template.md"
assert_file_exists "sdd/tasks-template.md exists" "$SHARED_DIR/templates/sdd/tasks-template.md"
assert_nonempty "sdd/tasks-template.md non-empty" "$SHARED_DIR/templates/sdd/tasks-template.md"
assert_file_exists "sdd/lessons-learned-template.md exists" "$SHARED_DIR/templates/sdd/lessons-learned-template.md"
assert_nonempty "sdd/lessons-learned-template.md non-empty" "$SHARED_DIR/templates/sdd/lessons-learned-template.md"

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

# ── Provider profile template (#199) ──────────────────────────
# This template had NO coverage, which is how a codex command built from
# flags that no longer exist shipped and survived. Guard the shipped
# reviewer commands against the two failure modes proven in
# specs/codex-provider-command/verification/codex-reviewer-capture.md.
PROVIDER_TMPL="$SHARED_DIR/templates/provider-profile-template.toml"
assert_file_exists "provider-profile-template.toml exists" "$PROVIDER_TMPL"

CODEX_CMD=$(awk '/^\[providers\.codex\]/{f=1;next} /^\[/{f=0} f && /^command *=/{sub(/^[^=]*= *"/,"");sub(/"$/,"");print;exit}' "$PROVIDER_TMPL")

rc=0; [[ "$CODEX_CMD" != *"--quiet"* && "$CODEX_CMD" != *"--prompt-file"* ]] || rc=1
assert_ok "codex command ships no removed flags (--quiet/--prompt-file)" "$rc"

rc=0; [[ "$CODEX_CMD" == *"codex exec"* ]] || rc=1
assert_ok "codex command uses the non-interactive 'codex exec' entry point" "$rc"

# The runner deletes .git from its snapshot sandbox; codex refuses to start
# outside a git repo, so this flag is required for the command to run at all.
rc=0; [[ "$CODEX_CMD" == *"--skip-git-repo-check"* ]] || rc=1
assert_ok "codex command tolerates the sandbox's missing .git" "$rc"

# A reviewer must not mutate the sandbox it is reviewing.
rc=0; [[ "$CODEX_CMD" == *"read-only"* ]] || rc=1
assert_ok "codex command runs the reviewer read-only" "$rc"

# codex echoes the PROMPT to stderr; the runner captures providers with 2>&1,
# so an unsuppressed stderr made the echoed "State exactly one of: PASS, ..."
# line the first ^### Verdict block — a FAIL parsed as PASS.
rc=0; [[ "$CODEX_CMD" == *"2>/dev/null"* ]] || rc=1
assert_ok "codex command keeps its prompt echo out of the parsed stream" "$rc"

# Every shipped cli command must consume {review_request}, or the reviewer
# is invoked with no request at all.
CLI_CMDS_MISSING=0
while IFS= read -r c; do
  [[ "$c" == *"{review_request}"* ]] || CLI_CMDS_MISSING=$((CLI_CMDS_MISSING + 1))
done < <(awk '/^type *= *"cli"/{cli=1} /^command *=/{if(cli){sub(/^[^=]*= *"/,"");sub(/"$/,"");print;cli=0}} /^\[/{cli=0}' "$PROVIDER_TMPL")
assert_eq "every shipped cli command consumes {review_request}" "0" "$CLI_CMDS_MISSING"

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
assert_header "ml-utils" "$SHARED_DIR/templates/ml-utils/PROJECT.md" "# ML/AI — Headless Utility / MCP Tool Server"
assert_header "ml-langchain" "$SHARED_DIR/templates/ml-langchain/PROJECT.md" "# ML/AI — LangChain + LangGraph + LangSmith"
assert_header "ml-n8n" "$SHARED_DIR/templates/ml-n8n/PROJECT.md" "# ML/AI — n8n Workflow Automation"
assert_header "java-enterprise" "$SHARED_DIR/templates/java-enterprise/PROJECT.md" "# Enterprise Java Full-Stack Application"
assert_header "web-static" "$SHARED_DIR/templates/web-static/PROJECT.md" "# Static Website"
assert_header "web-dynamic" "$SHARED_DIR/templates/web-dynamic/PROJECT.md" "# Dynamic Web Application"
assert_header "java-tooling" "$SHARED_DIR/templates/java-tooling/PROJECT.md" "# Java Developer Tooling — Annotation Processors, Gradle Plugins & Code Generators"
assert_header "domain-pack" "$SHARED_DIR/templates/domain-pack/PROJECT.md" "# Domain Pack — Versioned Content Distribution (JVM + Python)"
assert_header "gradle-plugin" "$SHARED_DIR/templates/gradle-plugin/PROJECT.md" "# Gradle Plugin — Idiomatic \`Plugin<Project>\` with TestKit"

# UI-Enhancement harness add-on bundle (not a project type — no Agent Team section)
UI_HARNESS="$SHARED_DIR/templates/ui-harness"
assert_dir_exists "ui-harness dir exists" "$UI_HARNESS"
assert_header "ui-harness" "$UI_HARNESS/PROJECT.md" "# UI-Enhancement Harness (Add-On)"
assert_file_exists "ui-harness DESIGN.md starter" "$UI_HARNESS/DESIGN.md"
assert_file_exists "ui-harness tokens.json starter" "$UI_HARNESS/design/tokens.json"
assert_file_exists "ui-harness harness/package.json" "$UI_HARNESS/harness/package.json"
assert_file_exists "ui-harness runner.ts" "$UI_HARNESS/harness/src/runner.ts"
assert_file_exists "ui-harness audit.ts" "$UI_HARNESS/harness/src/audit.ts"
assert_file_exists "ui-harness rubric.ts" "$UI_HARNESS/harness/src/rubric.ts"
assert_file_exists "ui-harness team-review command" "$UI_HARNESS/commands/team-review.md"

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
echo "=== skills source structure ==="

# Verify each skill directory has a SKILL.md (already checked above, lightweight re-check)
for s in "${SKILL_NAMES[@]}"; do
  assert_file_exists "skills/$s/SKILL.md present" "$SKILLS_DIR_PATH/$s/SKILL.md"
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
rc=0; grep -q 'SHARED_DIR/skills' "$SETUP_SCRIPT" || rc=1
assert_ok "setup.sh references shared/skills" "$rc"

rc=0; grep -q 'SKILLS_SOURCE' "$SETUP_SCRIPT" || rc=1
assert_ok "setup.sh uses SKILLS_SOURCE variable" "$rc"

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

# Plan agent must have Write and Edit tools for specs/ artifacts
rc=0
grep -q "tools:.*Write" "$ADAPTER_DIR/.claude/agents/plan.md" || rc=1
assert_ok "Plan agent has Write tool for specs/ artifacts" "$rc"

rc=0
grep -q "tools:.*Edit" "$ADAPTER_DIR/.claude/agents/plan.md" || rc=1
assert_ok "Plan agent has Edit tool for specs/ artifacts" "$rc"

# #407: Claude Code removes AskUserQuestion from every subagent even when
# listed, so an agent that lists it is promising a question it cannot ask.
rc=0
grep -l '^tools:.*AskUserQuestion' "$ADAPTER_DIR"/.claude/agents/*.md >/dev/null 2>&1 && rc=1
assert_ok "No agent lists AskUserQuestion in tools (unavailable to subagents, #407)" "$rc"

# Hooks in adapter
HOOK_FILES=(verify-on-stop.sh verify-after-edit.sh auto-format.sh protect-files.sh protect-git.sh peer-review-on-stop.sh reinject-context.sh notify.sh memkernel-recall.sh memkernel-pre-compact.sh memkernel-post-compact.sh)
HOOK_HELPERS=(memkernel-recall.py memkernel-pre-compact.py memkernel-post-compact.py)
for f in "${HOOK_FILES[@]}"; do
  assert_file_exists "adapter hook $f exists" "$ADAPTER_DIR/.claude/hooks/$f"
done
for f in "${HOOK_HELPERS[@]}"; do
  assert_file_exists "adapter hook helper $f exists" "$ADAPTER_DIR/.claude/hooks/$f"
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

# unknown-option guard exists
rc=0; grep -q 'Unknown option:' "$SETUP_SCRIPT" || rc=1
assert_ok "unknown-option guard present" "$rc"

# jq dependency check exists
rc=0; grep -q 'command -v jq' "$SETUP_SCRIPT" || rc=1
assert_ok "jq dependency check present" "$rc"

# One template installer for both paths (#498): every template folder with a
# PROJECT.md is installed by install_project_templates, which the fresh
# install and --sync both call. tests/test-sync.sh checks that the two leave
# the same template tree.
rc=0; grep -q '^install_project_templates() {' "$SETUP_SCRIPT" || rc=1
assert_ok "setup.sh defines install_project_templates" "$rc"
rc=0; [[ "$(grep -c -E '^[[:space:]]*install_project_templates (Installed|Synced)$' "$SETUP_SCRIPT")" == 2 ]] || rc=1
assert_ok "setup.sh calls it from the fresh install and from --sync" "$rc"

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

# Always rules match (installed as plain .md from SKILL.md body)
for f in coding-standards.md copilot-conventions.md safety.md copyright-headers.md; do
  if [[ -f "$INSTALL_DIR/rules/$f" ]]; then
    echo "  PASS: installed rules/$f found"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: installed rules/$f not found (run setup.sh first)"
    FAIL=$((FAIL + 1))
  fi
done

# On-demand skills match (installed as SKILL.md directories)
ON_DEMAND_SKILLS=(
  agent-team-protocol clarification-protocol environment-setup
  infra-verification integration-testing memkernel-memory
  opus-4-7-features phase-workflow provider-collaboration-protocol
  ralph-loop review-loop spec-workflow stack-constraints
  team-lead-efficiency token-efficiency
)
for s in "${ON_DEMAND_SKILLS[@]}"; do
  if [[ -f "$INSTALL_DIR/skills/$s/SKILL.md" ]]; then
    rc=0; diff -q "$INSTALL_DIR/skills/$s/SKILL.md" "$SKILLS_DIR_PATH/$s/SKILL.md" >/dev/null 2>&1 || rc=1
    assert_ok "installed skills/$s/SKILL.md matches shared/" "$rc"
  else
    echo "  FAIL: installed skills/$s/SKILL.md not found (run setup.sh first)"
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

# Hooks match
for f in "${HOOK_FILES[@]}" "${HOOK_HELPERS[@]}"; do
  if [[ -f "$INSTALL_DIR/hooks/$f" ]]; then
    rc=0; diff -q "$INSTALL_DIR/hooks/$f" "$ADAPTER_DIR/.claude/hooks/$f" >/dev/null 2>&1 || rc=1
    assert_ok "installed hooks/$f matches adapter/" "$rc"
  else
    echo "  FAIL: installed hooks/$f not found (run setup.sh first)"
    FAIL=$((FAIL + 1))
  fi
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
grep -Eq 'community standards links.*(complete|sync|synchron)' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance includes community-standards link parity gate" "$rc"

rc=0
grep -q 'docs/github-hardening-playbook.md' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance references hardening playbook" "$rc"

rc=0
grep -Eq 'CI triggers include governance/hardening files' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance includes CI governance/hardening trigger gate" "$rc"

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
grep -Eq '\[ \].*community standards links.*(complete|synchron)' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes community-standards parity item" "$rc"

rc=0
grep -Eq '\[ \].*hardening.*(playbook|scripts/harden-github\.sh)' "$SHARED_DIR/docs/alignment-maintenance.md" || rc=1
assert_ok "alignment-maintenance release checklist includes hardening-docs/scripts item" "$rc"

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
echo "=== harness engineering: list-agents command ==="

assert_file_exists "list-agents.md command exists" "$ADAPTER_DIR/.claude/commands/list-agents.md"
assert_nonempty "list-agents.md command non-empty" "$ADAPTER_DIR/.claude/commands/list-agents.md"

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

rc=0; grep -q 'cp -r "\$tmpl_dir/\.claude/"' "$SETUP_SCRIPT" || rc=1
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
# 15b. Templates that ship extra top-level subdirs (domain-pack,
# gradle-plugin) install with their layout intact — no unwrapping.
# Regression guard for a real bug where `cp -r src/ dest/` (trailing
# slash) flattened nested dirs into the template root.
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== install output: extra subdirs preserved (no unwrapping) ==="

# domain-pack: content/, jvm-wrapper/, python-wrapper/, scripts/
for nested in \
    "domain-pack/content/manifest.yaml" \
    "domain-pack/content/data.tbx" \
    "domain-pack/jvm-wrapper/build.gradle.kts" \
    "domain-pack/jvm-wrapper/src/main/java/com/example/domainpack/PackLoader.java" \
    "domain-pack/python-wrapper/pyproject.toml" \
    "domain-pack/python-wrapper/src/domain_pack/loader.py" \
    "domain-pack/scripts/sync-content.sh"; do
  assert_file_exists "installed $nested preserves nesting" "$INSTALL_DIR/templates/$nested"
done

# gradle-plugin: plugin/, sample-consumer/, gradle/
for nested in \
    "gradle-plugin/plugin/build.gradle.kts" \
    "gradle-plugin/plugin/src/main/kotlin/com/example/gradleplugin/ExamplePlugin.kt" \
    "gradle-plugin/plugin/src/test/kotlin/com/example/gradleplugin/ExamplePluginTest.kt" \
    "gradle-plugin/plugin/src/functionalTest/kotlin/com/example/gradleplugin/ExamplePluginFunctionalTest.kt" \
    "gradle-plugin/sample-consumer/build.gradle.kts" \
    "gradle-plugin/sample-consumer/settings.gradle.kts" \
    "gradle-plugin/gradle/libs.versions.toml" \
    "gradle-plugin/settings.gradle.kts" \
    "gradle-plugin/build.gradle.kts"; do
  assert_file_exists "installed $nested preserves nesting" "$INSTALL_DIR/templates/$nested"
done

# Negative guards: the unwrapping bug would put these at the template root.
for unwrapped in \
    "domain-pack/manifest.yaml" \
    "domain-pack/data.tbx" \
    "domain-pack/loader.py" \
    "domain-pack/PackLoader.java" \
    "gradle-plugin/ExamplePlugin.kt" \
    "gradle-plugin/libs.versions.toml"; do
  rc=0; [[ ! -e "$INSTALL_DIR/templates/$unwrapped" ]] || rc=1
  assert_ok "installed $unwrapped is NOT at template root (no unwrapping)" "$rc"
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
# 18. Repo-structure claims — test-count lines are current
# ══════════════════════════════════════════════════════════════
#
# The repo-layout tree moved out of the README into docs/repo-structure.md
# in #214 Phase 3.1; the claims are pinned wherever the tree lives.
TEST_COUNT_DOC="$REPO_DIR/docs/repo-structure.md"

echo ""
echo "=== repo-structure test-count claims ==="

rc=0
grep -Eq "test-hooks\\.sh[[:space:]]+${TEST_HOOKS_EXPECTED_PASS} hook tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_HOOKS_EXPECTED_PASS} hook tests" "$rc"

rc=0
grep -Eq "test-generate\\.sh[[:space:]]+${TEST_GENERATE_EXPECTED_PASS} generation \\+ adapter tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_GENERATE_EXPECTED_PASS} generation + adapter tests" "$rc"

rc=0
grep -Eq "test-shared-structure\\.sh[[:space:]]+${TEST_SHARED_STRUCTURE_EXPECTED_PASS} structure \\+ content tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_SHARED_STRUCTURE_EXPECTED_PASS} structure + content tests" "$rc"

rc=0
grep -Eq "test-sync\\.sh[[:space:]]+${TEST_SYNC_EXPECTED_PASS} sync \\+ init metadata tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_SYNC_EXPECTED_PASS} sync + init metadata tests" "$rc"

rc=0
grep -Eq "test-peer-review\\.sh[[:space:]]+${TEST_PEER_REVIEW_EXPECTED_PASS} peer-review runner tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_PEER_REVIEW_EXPECTED_PASS} peer-review runner tests" "$rc"

rc=0
grep -Eq "test-review-loop\\.sh[[:space:]]+${TEST_REVIEW_LOOP_EXPECTED_PASS} review loop integration tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_REVIEW_LOOP_EXPECTED_PASS} review loop integration tests" "$rc"

rc=0
grep -Eq "test-auto-build-loop\\.sh[[:space:]]+${TEST_AUTO_BUILD_LOOP_EXPECTED_PASS} auto-build driver tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_AUTO_BUILD_LOOP_EXPECTED_PASS} auto-build driver tests" "$rc"

rc=0
grep -Eq "test-ui-harness\\.sh[[:space:]]+${TEST_UI_HARNESS_EXPECTED_PASS} visual-harness contract tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_UI_HARNESS_EXPECTED_PASS} visual-harness contract tests" "$rc"

rc=0
grep -Eq "test-setup-reviewer\\.sh[[:space:]]+${TEST_SETUP_REVIEWER_EXPECTED_PASS} copilot reviewer installer tests" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${TEST_SETUP_REVIEWER_EXPECTED_PASS} copilot reviewer installer tests" "$rc"

rc=0
grep -Eq "docs/[[:space:]]+${DOCS_EXPECTED_COUNT} tool-agnostic reference docs" "$TEST_COUNT_DOC" || rc=1
assert_ok "repo structure lists ${DOCS_EXPECTED_COUNT} tool-agnostic reference docs" "$rc"

rc=0
grep -Eq "rules/\*\.md[[:space:]]+.*Global rules" "$REPO_DIR/docs/configuration-layers.md" || rc=1
assert_ok "configuration layers lists global rules" "$rc"

rc=0
grep -Eq "skills/[[:space:]]+24 skills" "$TEST_COUNT_DOC" || rc=1
assert_ok "README lists 24 skills" "$rc"

rc=0
grep -Eq "templates/[[:space:]]+11 stacks" "$TEST_COUNT_DOC" || rc=1
assert_ok "README lists 11 template stacks" "$rc"

rc=0
grep -Eq "codex/.*5 skills" "$TEST_COUNT_DOC" || rc=1
assert_ok "README lists 5 codex skills" "$rc"

rc=0
grep -Eq "\\.github/workflows/sync-check\\.yml[[:space:]]+CI: .*drift" "$TEST_COUNT_DOC" || rc=1
assert_ok "README describes sync-check workflow as drift guard" "$rc"

rc=0
grep -Eq "\\.github/workflows/sync-check\\.yml[[:space:]]+CI: .*(full gate|gate verification)" "$TEST_COUNT_DOC" || rc=1
assert_ok "README describes sync-check workflow as full gate verification" "$rc"

rc=0
INSTALL_DOC="$REPO_DIR/docs/install.md"
grep -q '^## What each adapter writes' "$INSTALL_DOC" || rc=1
assert_ok "install guide has the adapter-output table" "$rc"

README_SUPPORTED_TOOLS_SECTION=$(
  awk '
    /^## What each adapter writes/ {in_section=1; next}
    /^## / && in_section {exit}
    in_section {print}
  ' "$INSTALL_DOC"
)

SUPPORTED_TOOLS_ROW_COUNT=$(echo "$README_SUPPORTED_TOOLS_SECTION" | grep -Ec '^\| \*\*[^|]+\*\* \|')
assert_eq "install guide lists 7 adapters" "7" "$SUPPORTED_TOOLS_ROW_COUNT"

rc=0
echo "$README_SUPPORTED_TOOLS_SECTION" | grep -Fq '| **Claude Code** | agents, hooks, commands, settings | `~/.claude/` (global) |' || rc=1
assert_ok "install guide includes Claude Code row" "$rc"

rc=0
echo "$README_SUPPORTED_TOOLS_SECTION" | grep -Fq '| **Pi** | enforcement runtime extension + skills/prompts | `pi install` (advisory) / `pi-code` (enforced) |' || rc=1
assert_ok "install guide includes Pi row" "$rc"

rc=0
echo "$README_SUPPORTED_TOOLS_SECTION" | grep -Fq '| **OpenAI Codex** | `AGENTS.md` + 5 skills | `~/.codex/` (global) |' || rc=1
assert_ok "install guide includes OpenAI Codex row" "$rc"

rc=0
echo "$README_SUPPORTED_TOOLS_SECTION" | grep -Fq '| **Cursor** | `.mdc` files with frontmatter | `project/.cursor/rules/` |' || rc=1
assert_ok "install guide includes Cursor row" "$rc"

rc=0
echo "$README_SUPPORTED_TOOLS_SECTION" | grep -Fq '| **GitHub Copilot** | `copilot-instructions.md` + per-rule instructions | `project/.github/` |' || rc=1
assert_ok "install guide includes GitHub Copilot row" "$rc"

rc=0
echo "$README_SUPPORTED_TOOLS_SECTION" | grep -Fq '| **Windsurf** | `rules.md` | `project/.windsurf/rules/` |' || rc=1
assert_ok "install guide includes Windsurf row" "$rc"

rc=0
echo "$README_SUPPORTED_TOOLS_SECTION" | grep -Fq '| **Aider** | `CONVENTIONS.md` | `project/` |' || rc=1
assert_ok "install guide includes Aider row" "$rc"

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

# The shipped docs directory is the source of which guides exist; a list
# retyped here drifts the moment one is added (agent-teams.md and
# hooks-test-cases.md shipped unlisted until #214 Phase 2.2, and this array
# still named eight). scripts/check-doc-accuracy.sh enforces the same rule
# against the README; this asserts the section's shape.
README_CLAUDE_DOCS=()
while IFS= read -r f; do
  README_CLAUDE_DOCS+=("$(basename "$f")")
done < <(find "$ADAPTER_DIR/docs" -maxdepth 1 -name '*.md' | sort)
README_CLAUDE_DOCS_EXPECTED_COUNT="${#README_CLAUDE_DOCS[@]}"
[[ "$README_CLAUDE_DOCS_EXPECTED_COUNT" -gt 0 ]] || {
  echo "  FAIL: no docs found in $ADAPTER_DIR/docs"; exit 1
}

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

rc=0
grep -Eq '^TEST_SYNC_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_SYNC_EXPECTED_PASS numeric value" "$rc"

rc=0
grep -Eq '^TEST_PEER_REVIEW_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_PEER_REVIEW_EXPECTED_PASS numeric value" "$rc"

rc=0
grep -Eq '^TEST_REVIEW_LOOP_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_REVIEW_LOOP_EXPECTED_PASS numeric value" "$rc"

COUNT_VARS=$(grep -Ec '^TEST_[A-Z_]+_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env")
# 15 as of #239 C3 T4 (test-ui-harness.sh). Bump deliberately when a
# suite is added, so a pin cannot go missing unnoticed.
assert_eq "test-counts has exactly 33 expected-pass variables (the four wiki suites arrived with #384, cct-home with #411, the two llm suites with #479, llm-cli with slice S1 of #400, cct-statefile and llm-compat with slice S2)" "33" "$COUNT_VARS"

# ── #384 FR-10: assistant workflows keep their meaning after the engine swap ──
# /promote-lesson stays a free-text, manual curator procedure that lints
# through the launcher; wiki-first-query stays a direct, model-free read.
# Asserted on the SOURCE and on every generated copy, so a regeneration
# cannot drop either contract.
PL_SRC="$REPO_DIR/adapters/claude-code/.claude/commands/promote-lesson.md"
rc=0; grep -q './scripts/wiki lint' "$PL_SRC" || rc=1
assert_ok "promote-lesson (source) lints through ./scripts/wiki lint" "$rc"
rc=0; grep -q 'lint-wiki.sh' "$PL_SRC" && rc=1
assert_ok "promote-lesson (source) names no Bash linter" "$rc"
rc=0; grep -q 'Free-form prose' "$PL_SRC" || rc=1
assert_ok "promote-lesson (source) keeps its free-text argument" "$rc"
rc=0; grep -q 'never a source path to ingest' "$PL_SRC" || rc=1
assert_ok "promote-lesson (source) never reinterprets the text as an ingest source" "$rc"
rc=0; grep -q 'Without a CCT checkout' "$PL_SRC" || rc=1
assert_ok "promote-lesson (source) states the plugin-only prerequisite and refuses rather than skips" "$rc"
for copy in "$REPO_DIR/adapters/claude-code/plugin/commands/promote-lesson.md" "$REPO_DIR/adapters/pi/resources/prompts/promote-lesson.md"; do
  rc=0; grep -q './scripts/wiki lint' "$copy" || rc=1
  assert_ok "promote-lesson copy lints through the launcher: ${copy#"$REPO_DIR"/}" "$rc"
  rc=0; grep -q 'lint-wiki.sh' "$copy" && rc=1
  assert_ok "promote-lesson copy names no Bash linter: ${copy#"$REPO_DIR"/}" "$rc"
  rc=0; grep -q 'Without a CCT checkout' "$copy" || rc=1
  assert_ok "promote-lesson copy states the plugin-only prerequisite: ${copy#"$REPO_DIR"/}" "$rc"
done
# ── #384 FR-14: the two wiki workflows install what production runs. The
# contract workflow has NO paths filter (its inputs — the live wiki, what
# its pages cite, the doctor — are dynamic; an external review found the
# first hand-written filter incomplete), and the structure test says so.
WIT="$REPO_DIR/.github/workflows/wiki-ingest-tests.yml"
rc=0; grep -q "^    paths:" "$WIT" && rc=1
assert_ok "wiki-ingest-tests.yml runs on every push and pull request (no paths filter)" "$rc"
rc=0; grep -q "No paths filter, on purpose" "$WIT" || rc=1
assert_ok "wiki-ingest-tests.yml says why it has no filter" "$rc"
rc=0; grep -q "^    name: Wiki contract$" "$WIT" && grep -q "needs: test" "$WIT" && grep -q "if: always()" "$WIT" || rc=1
assert_ok "wiki-ingest-tests.yml ends in one check named 'Wiki contract' that fails unless every leg succeeded" "$rc"
rc=0; grep -q "run: bash scripts/setup-wiki.sh --require" "$WIT" || rc=1
assert_ok "wiki-ingest-tests.yml installs the locked wheel with the users' installer" "$rc"
rc=0; grep -q "python-version: \['3.11', '3.12', '3.13'\]" "$WIT" || rc=1
assert_ok "wiki-ingest-tests.yml runs on exactly the package's Python range" "$rc"
for suite in test-wiki-setup.sh test-wiki-launcher.sh test-wiki-schema.sh test-wiki-ingest.sh; do
  rc=0; grep -q "run: bash tests/$suite" "$WIT" || rc=1
  assert_ok "wiki-ingest-tests.yml runs $suite" "$rc"
done
rc=0; grep -q "tests/test-wiki-setup.sh\|tests/test-wiki-launcher.sh" "$REPO_DIR/.github/workflows/sync-check.yml" && rc=1
assert_ok "sync-check does not run the wiki suites (its python3 is outside the package's range)" "$rc"
WL="$REPO_DIR/.github/workflows/wiki-lint.yml"
for input in "knowledge/wiki/\*\*'" "scripts/wiki'" "scripts/lib/wiki_env.sh'" "scripts/setup-wiki.sh'" "scripts/wiki-requirements.txt'"; do
  rc=0; [[ "$(grep -c -- "- '$input" "$WL")" -eq 2 ]] || rc=1
  assert_ok "wiki-lint.yml filters push and pull_request on ${input%\'}" "$rc"
done
rc=0; grep -q "run: bash scripts/setup-wiki.sh --require" "$WL" || rc=1
assert_ok "wiki-lint.yml installs the locked wheel" "$rc"
rc=0; grep -q "run: ./scripts/wiki lint" "$WL" || rc=1
assert_ok "wiki-lint.yml lints through the launcher" "$rc"
rc=0; grep -q "continue-on-error: true" "$WL" || rc=1
assert_ok "wiki-lint.yml stays non-blocking (unchanged merge policy)" "$rc"
rc=0; grep -q "lint-wiki.sh" "$WL" && rc=1
assert_ok "wiki-lint.yml no longer runs the Bash linter" "$rc"

# ── #384 FR-5/FR-6/FR-13: both duplicate engines are gone and nothing
# production-facing names them. Records of the removal (specs, the
# changelog, the schema policy and its delta fixture) are the only
# places the old names may appear.
rc=0; [[ -e "$REPO_DIR/scripts/wiki_ingest" ]] && rc=1
assert_ok "the embedded engine tree scripts/wiki_ingest/ is gone" "$rc"
rc=0; [[ -e "$REPO_DIR/knowledge/wiki/scripts/lint-wiki.sh" ]] && rc=1
assert_ok "the Bash linter knowledge/wiki/scripts/lint-wiki.sh is gone" "$rc"
STALE=$(git -C "$REPO_DIR" grep -lE 'wiki_ingest|python3? -m wiki_ingest' -- . \
  ':!specs' ':!CHANGELOG.md' ':!tests/test-shared-structure.sh' ':!tests/test-wiki-schema.sh' 2>/dev/null || true)
rc=0; [[ -z "$STALE" ]] || rc=1
assert_ok "no file imports or invokes the deleted engine${STALE:+ (found: $(echo "$STALE" | tr '\n' ' '))}" "$rc"
STALE=$(git -C "$REPO_DIR" grep -l 'lint-wiki\.sh' -- . \
  ':!specs' ':!CHANGELOG.md' ':!knowledge/wiki/schema/POLICY.md' ':!tests/fixtures/wiki-schema' \
  ':!tests/test-shared-structure.sh' ':!tests/test-wiki-schema.sh' 2>/dev/null || true)
rc=0; [[ -z "$STALE" ]] || rc=1
assert_ok "no production file names the deleted Bash linter${STALE:+ (found: $(echo "$STALE" | tr '\n' ' '))}" "$rc"

WF_SENTENCE='The convention never runs `wiki query`'
rc=0; grep -qF "$WF_SENTENCE" "$SHARED_DIR/skills/wiki-first-query/SKILL.md" || rc=1
assert_ok "wiki-first-query (source) stays a direct read: never wiki query or find" "$rc"
for copy in \
  "$REPO_DIR/adapters/claude-code/plugin/skills/wiki-first-query/SKILL.md" \
  "$REPO_DIR/adapters/cursor/.cursor/rules/wiki-first-query.mdc" \
  "$REPO_DIR/adapters/codex/AGENTS.md" \
  "$REPO_DIR/adapters/github-copilot/.github/copilot-instructions.md" \
  "$REPO_DIR/adapters/pi/resources/context/always-context.md" \
  "$REPO_DIR/adapters/aider/CONVENTIONS.md" \
  "$REPO_DIR/adapters/windsurf/.windsurf/rules/rules.md"; do
  rc=0; grep -qF "$WF_SENTENCE" "$copy" || rc=1
  assert_ok "wiki-first-query copy keeps the model-free contract: ${copy#"$REPO_DIR"/}" "$rc"
done

rc=0
grep -Eq '^TEST_LITELLM_PROXY_DEPS_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_LITELLM_PROXY_DEPS_EXPECTED_PASS numeric value" "$rc"

rc=0
grep -Eq '^TEST_COVERAGE_PARSE_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_COVERAGE_PARSE_EXPECTED_PASS numeric value" "$rc"

rc=0
grep -Eq '^TEST_VERIFICATION_PRESET_EXPECTED_PASS=[0-9]+$' "$REPO_DIR/tests/test-counts.env" || rc=1
assert_ok "test-counts has TEST_VERIFICATION_PRESET_EXPECTED_PASS numeric value" "$rc"
rc=0
grep -q 'TEST_VERIFICATION_PRESET_EXPECTED_PASS' "$REPO_DIR/tests/test-verification-preset.sh" || rc=1
assert_ok "test-verification-preset enforces its own count pin" "$rc"
# The pin must be ENFORCED by its suite, not merely declared (#225 review P3).
rc=0
grep -q 'TEST_COVERAGE_PARSE_EXPECTED_PASS' "$REPO_DIR/tests/test-coverage-parse.sh" || rc=1
assert_ok "test-coverage-parse enforces its own count pin" "$rc"

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
grep -q 'source "\$COUNTS_FILE"' "$REPO_DIR/tests/test-peer-review.sh" || rc=1
assert_ok "test-peer-review sources count contract" "$rc"

rc=0
grep -q 'source "\$COUNTS_FILE"' "$REPO_DIR/tests/test-review-loop.sh" || rc=1
assert_ok "test-review-loop sources count contract" "$rc"

rc=0
grep -q 'TEST_GENERATE_EXPECTED_PASS' "$REPO_DIR/tests/test-generate.sh" || rc=1
assert_ok "test-generate uses expected-pass variable" "$rc"

rc=0
grep -q 'TEST_HOOKS_EXPECTED_PASS' "$REPO_DIR/tests/test-hooks.sh" || rc=1
assert_ok "test-hooks uses expected-pass variable" "$rc"

rc=0
grep -q 'TEST_SHARED_STRUCTURE_EXPECTED_PASS' "$REPO_DIR/tests/test-shared-structure.sh" || rc=1
assert_ok "test-shared-structure uses expected-pass variable" "$rc"

rc=0
grep -q 'TEST_PEER_REVIEW_EXPECTED_PASS' "$REPO_DIR/tests/test-peer-review.sh" || rc=1
assert_ok "test-peer-review uses expected-pass variable" "$rc"

rc=0
grep -q 'TEST_REVIEW_LOOP_EXPECTED_PASS' "$REPO_DIR/tests/test-review-loop.sh" || rc=1
assert_ok "test-review-loop uses expected-pass variable" "$rc"

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

CONTRIB_HOWTO_SECTION=$(
  awk '
    /^## How to Contribute/ {in_section=1; next}
    /^## / && in_section {exit}
    in_section {print}
  ' "$REPO_DIR/CONTRIBUTING.md"
)

rc=0
echo "$CONTRIB_HOWTO_SECTION" | grep -q 'bash adapters/claude-code/setup.sh' || rc=1
assert_ok "CONTRIBUTING How to Contribute includes setup.sh command" "$rc"

SETUP_HOWTO_LINE=$(echo "$CONTRIB_HOWTO_SECTION" | nl -ba | awk '/bash adapters\/claude-code\/setup\.sh/{print $1; exit}')
STRUCT_HOWTO_LINE=$(echo "$CONTRIB_HOWTO_SECTION" | nl -ba | awk '/bash tests\/test-shared-structure\.sh/{print $1; exit}')
rc=0
[[ -n "$SETUP_HOWTO_LINE" && -n "$STRUCT_HOWTO_LINE" && "$SETUP_HOWTO_LINE" -lt "$STRUCT_HOWTO_LINE" ]] || rc=1
assert_ok "CONTRIBUTING How to Contribute runs setup.sh before structure test" "$rc"

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
grep -q 'bash tests/test-ui-harness.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check runs test-ui-harness.sh" "$rc"

rc=0
grep -q 'bash tests/test-peer-review.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check runs test-peer-review.sh" "$rc"

rc=0
grep -q 'bash tests/test-review-loop.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check runs test-review-loop.sh" "$rc"

rc=0
grep -q 'bash scripts/generate.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check runs scripts/generate.sh" "$rc"

rc=0
grep -q 'name: Validate hardening scripts' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check has hardening script validation step" "$rc"

rc=0
grep -q 'bash -n scripts/apply-branch-protection.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check validates apply-branch-protection syntax" "$rc"

rc=0
grep -q 'bash -n scripts/check-github-hardening.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check validates check-github-hardening syntax" "$rc"

rc=0
grep -q 'bash -n scripts/harden-github.sh' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check validates harden-github syntax" "$rc"

# The review gate runs on pull_request_target with write scopes; it must
# never check out or run PR code, or a fork PR gets the base token.
GATE_FILE="$REPO_DIR/.github/workflows/review-gate.yml"
rc=0
[[ -f "$GATE_FILE" ]] || rc=1
assert_ok "review-gate workflow exists" "$rc"
rc=0
grep -q '^  pull_request_target:' "$GATE_FILE" || rc=1
assert_ok "review-gate runs on pull_request_target (master's copy, never the PR's)" "$rc"
rc=0
grep -qE 'actions/checkout|git clone|git fetch|pip install|npm (ci|install)' "$GATE_FILE" && rc=1
assert_ok "review-gate never checks out or installs PR code" "$rc"
rc=0
grep -q 'context="\$CONTEXT"' "$GATE_FILE" && grep -q 'CONTEXT: External review on record' "$GATE_FILE" || rc=1
assert_ok "review-gate sets the 'External review on record' status" "$rc"

# Staged diff, not plain `git diff`: the latter is blind to untracked
# generator output, which let a missing generated prompt go undetected.
rc=0
grep -q 'git add -A adapters/' "$WORKFLOW_FILE" || rc=1
grep -q 'git diff --cached --exit-code adapters/' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check checks adapter drift via staged diff" "$rc"

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

# Path filters were removed (PR #131) so sync-check runs on EVERY PR and can be a
# required status check without deadlocking PRs that touch unlisted paths. One
# assertion now guards that intent: no `paths:` filter under the triggers.
PATHS_FILTER_COUNT=$(grep -Ec '^[[:space:]]+paths:' "$WORKFLOW_FILE")
assert_eq "sync-check has no paths: filter (runs on every PR)" "0" "$PATHS_FILTER_COUNT"

rc=0; grep -q 'Validate spec conformance' "$WORKFLOW_FILE" || rc=1
assert_ok "sync-check has Validate spec conformance step" "$rc"

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
grep -q '^/scripts/apply-branch-protection\.sh @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes apply-branch-protection ownership" "$rc"

rc=0
grep -q '^/scripts/check-github-hardening\.sh @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes check-github-hardening ownership" "$rc"

rc=0
grep -q '^/scripts/harden-github\.sh @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes harden-github ownership" "$rc"

rc=0
grep -q '^/docs/github-hardening-playbook\.md @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes hardening playbook ownership" "$rc"

rc=0
grep -q '^/\.github/workflows/sync-check\.yml @gosha70$' "$REPO_DIR/.github/CODEOWNERS" || rc=1
assert_ok "CODEOWNERS includes sync-check workflow ownership" "$rc"

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
assert_eq "README community-standards section lists 6 links" "6" "$README_COMMUNITY_LINK_COUNT"

README_COMMUNITY_UNIQUE_LINK_COUNT=$(echo "$README_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | sort -u | wc -l | tr -d ' ')
assert_eq "README community-standards section links are unique" "6" "$README_COMMUNITY_UNIQUE_LINK_COUNT"

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
echo "$README_COMMUNITY_SECTION" | grep -Fq '[GitHub Hardening Playbook](docs/github-hardening-playbook.md)' || rc=1
assert_ok "README community-standards includes hardening playbook link" "$rc"

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
assert_eq "CONTRIBUTING community-standards section lists 6 links" "6" "$CONTRIBUTING_COMMUNITY_LINK_COUNT"

CONTRIBUTING_COMMUNITY_UNIQUE_LINK_COUNT=$(echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | sort -u | wc -l | tr -d ' ')
assert_eq "CONTRIBUTING community-standards section links are unique" "6" "$CONTRIBUTING_COMMUNITY_UNIQUE_LINK_COUNT"

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
echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Fq '[GitHub Hardening Playbook](docs/github-hardening-playbook.md)' || rc=1
assert_ok "CONTRIBUTING community-standards includes hardening playbook link" "$rc"

rc=0
if ! diff -u \
  <(echo "$README_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | sort) \
  <(echo "$CONTRIBUTING_COMMUNITY_SECTION" | grep -Eo '\[[^]]+\]\([^)]+\)' | sort) >/dev/null; then
  rc=1
fi
assert_ok "README and CONTRIBUTING community-standards link sets match" "$rc"

# ══════════════════════════════════════════════════════════════
# 23. GitHub hardening automation scripts/docs
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== github hardening automation ==="

assert_file_exists "scripts/apply-branch-protection.sh exists" "$REPO_DIR/scripts/apply-branch-protection.sh"
assert_nonempty "scripts/apply-branch-protection.sh non-empty" "$REPO_DIR/scripts/apply-branch-protection.sh"

rc=0
[[ -x "$REPO_DIR/scripts/apply-branch-protection.sh" ]] || rc=1
assert_ok "scripts/apply-branch-protection.sh is executable" "$rc"

rc=0
bash -n "$REPO_DIR/scripts/apply-branch-protection.sh" || rc=1
assert_ok "apply-branch-protection.sh syntax valid" "$rc"

rc=0
grep -q -- '--checks' "$REPO_DIR/scripts/apply-branch-protection.sh" || rc=1
assert_ok "apply-branch-protection supports --checks option" "$rc"

rc=0
grep -q '"require_code_owner_reviews": true' "$REPO_DIR/scripts/apply-branch-protection.sh" || rc=1
assert_ok "apply-branch-protection requires code owner reviews" "$rc"

rc=0
grep -q '"required_conversation_resolution": true' "$REPO_DIR/scripts/apply-branch-protection.sh" || rc=1
assert_ok "apply-branch-protection requires conversation resolution" "$rc"

assert_file_exists "scripts/check-github-hardening.sh exists" "$REPO_DIR/scripts/check-github-hardening.sh"
assert_nonempty "scripts/check-github-hardening.sh non-empty" "$REPO_DIR/scripts/check-github-hardening.sh"

rc=0
[[ -x "$REPO_DIR/scripts/check-github-hardening.sh" ]] || rc=1
assert_ok "scripts/check-github-hardening.sh is executable" "$rc"

rc=0
bash -n "$REPO_DIR/scripts/check-github-hardening.sh" || rc=1
assert_ok "check-github-hardening.sh syntax valid" "$rc"

rc=0
grep -q -- '--required-checks' "$REPO_DIR/scripts/check-github-hardening.sh" || rc=1
assert_ok "check-github-hardening supports --required-checks option" "$rc"

rc=0
grep -q 'private vulnerability reporting enabled' "$REPO_DIR/scripts/check-github-hardening.sh" || rc=1
assert_ok "check-github-hardening validates private vulnerability reporting" "$rc"

assert_file_exists "scripts/harden-github.sh exists" "$REPO_DIR/scripts/harden-github.sh"
assert_nonempty "scripts/harden-github.sh non-empty" "$REPO_DIR/scripts/harden-github.sh"

rc=0
[[ -x "$REPO_DIR/scripts/harden-github.sh" ]] || rc=1
assert_ok "scripts/harden-github.sh is executable" "$rc"

rc=0
bash -n "$REPO_DIR/scripts/harden-github.sh" || rc=1
assert_ok "harden-github.sh syntax valid" "$rc"

rc=0
grep -q 'apply-branch-protection.sh' "$REPO_DIR/scripts/harden-github.sh" || rc=1
assert_ok "harden-github invokes apply-branch-protection" "$rc"

rc=0
grep -q 'check-github-hardening.sh' "$REPO_DIR/scripts/harden-github.sh" || rc=1
assert_ok "harden-github invokes check-github-hardening" "$rc"

assert_file_exists "docs/github-hardening-playbook.md exists" "$REPO_DIR/docs/github-hardening-playbook.md"
assert_nonempty "docs/github-hardening-playbook.md non-empty" "$REPO_DIR/docs/github-hardening-playbook.md"

rc=0
grep -q 'scripts/apply-branch-protection.sh' "$REPO_DIR/docs/github-hardening-playbook.md" || rc=1
assert_ok "hardening playbook references apply script" "$rc"

rc=0
grep -q 'scripts/check-github-hardening.sh' "$REPO_DIR/docs/github-hardening-playbook.md" || rc=1
assert_ok "hardening playbook references check script" "$rc"

rc=0
grep -q 'scripts/harden-github.sh' "$REPO_DIR/docs/github-hardening-playbook.md" || rc=1
assert_ok "hardening playbook references harden script" "$rc"

# ══════════════════════════════════════════════════════════════
# 24. GitHub hardening scripts — behavioral dry-run checks
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== github hardening script behavior ==="

FAKE_GH_DIR="$(mktemp -d)"
FAKE_GH="$FAKE_GH_DIR/gh"
cat >"$FAKE_GH" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

cmd="${1:-}"

if [[ "$cmd" == "repo" && "${2:-}" == "view" ]]; then
  if [[ " $* " == *" defaultBranchRef "* ]]; then
    echo "master"
    exit 0
  fi
  if [[ " $* " == *" nameWithOwner "* ]]; then
    echo "gosha70/code-copilot-team"
    exit 0
  fi
fi

if [[ "$cmd" == "api" ]]; then
  shift
  endpoint=""
  jq_filter=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --jq)
        jq_filter="${2:-}"
        shift 2
        ;;
      --method|-H|--input)
        shift 2
        ;;
      -*)
        shift
        ;;
      /repos/*)
        endpoint="$1"
        shift
        ;;
      *)
        shift
        ;;
    esac
  done

  if [[ "$endpoint" == */branches/*/protection ]]; then
    case "$jq_filter" in
      "")
        echo '{}'
        ;;
      ".required_status_checks.strict")
        echo "true"
        ;;
      ".required_status_checks.contexts | join(\",\")")
        echo "sync-check,lint"
        ;;
      ".required_pull_request_reviews.require_code_owner_reviews")
        echo "true"
        ;;
      ".required_pull_request_reviews.required_approving_review_count")
        echo "1"
        ;;
      ".required_conversation_resolution.enabled")
        echo "true"
        ;;
      ".required_linear_history.enabled")
        echo "true"
        ;;
      ".enforce_admins.enabled")
        echo "true"
        ;;
      ".allow_force_pushes.enabled")
        echo "false"
        ;;
      ".allow_deletions.enabled")
        echo "false"
        ;;
      *)
        echo "true"
        ;;
    esac
    exit 0
  fi

  if [[ "$endpoint" == /repos/* ]]; then
    if [[ "$jq_filter" == ".security_and_analysis.private_vulnerability_reporting.status // \"\"" ]]; then
      echo "enabled"
      exit 0
    fi
    echo '{}'
    exit 0
  fi
fi

echo "unsupported gh stub invocation: $cmd $*" >&2
exit 1
EOF
chmod +x "$FAKE_GH"

APPLY_DRY_RUN_OUTPUT="$FAKE_GH_DIR/apply-dry-run.out"
rc=0
PATH="$FAKE_GH_DIR:$PATH" bash "$REPO_DIR/scripts/apply-branch-protection.sh" \
  --repo gosha70/code-copilot-team \
  --branch master \
  --checks "sync-check,lint" \
  --dry-run >"$APPLY_DRY_RUN_OUTPUT" 2>&1 || rc=1
assert_ok "apply-branch-protection dry-run works with fake gh" "$rc"

rc=0
grep -q '"contexts": \["sync-check", "lint"\]' "$APPLY_DRY_RUN_OUTPUT" || rc=1
assert_ok "apply-branch-protection dry-run payload includes required checks list" "$rc"

CHECK_OUTPUT="$FAKE_GH_DIR/check.out"
rc=0
PATH="$FAKE_GH_DIR:$PATH" bash "$REPO_DIR/scripts/check-github-hardening.sh" \
  --repo gosha70/code-copilot-team \
  --branch master \
  --required-checks "sync-check" >"$CHECK_OUTPUT" 2>&1 || rc=1
assert_ok "check-github-hardening passes with fake gh" "$rc"

rc=0
grep -q 'Results: 11 passed, 0 failed' "$CHECK_OUTPUT" || rc=1
assert_ok "check-github-hardening reports clean result summary" "$rc"

HARDEN_DRY_RUN_OUTPUT="$FAKE_GH_DIR/harden-dry-run.out"
rc=0
PATH="$FAKE_GH_DIR:$PATH" bash "$REPO_DIR/scripts/harden-github.sh" \
  --repo gosha70/code-copilot-team \
  --branch master \
  --checks "sync-check,lint" \
  --dry-run >"$HARDEN_DRY_RUN_OUTPUT" 2>&1 || rc=1
assert_ok "harden-github dry-run works with fake gh" "$rc"

rc=0
grep -q '=== Dry run: apply payload ===' "$HARDEN_DRY_RUN_OUTPUT" || rc=1
assert_ok "harden-github dry-run prints apply payload section" "$rc"

rc=0
grep -q 'Dry run completed. No remote settings were changed.' "$HARDEN_DRY_RUN_OUTPUT" || rc=1
assert_ok "harden-github dry-run confirms no remote changes" "$rc"

rm -rf "$FAKE_GH_DIR"

# ══════════════════════════════════════════════════════════════
# SDD Sprint 3 — validate-spec.sh, template frontmatter, spec-workflow, review.md
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== validate-spec.sh existence and syntax ==="

assert_file_exists "validate-spec.sh exists" "$REPO_DIR/scripts/validate-spec.sh"
assert_nonempty "validate-spec.sh non-empty" "$REPO_DIR/scripts/validate-spec.sh"

rc=0; [[ -x "$REPO_DIR/scripts/validate-spec.sh" ]] || rc=1
assert_ok "validate-spec.sh is executable" "$rc"

rc=0; bash -n "$REPO_DIR/scripts/validate-spec.sh" 2>/dev/null || rc=1
assert_ok "validate-spec.sh passes bash -n" "$rc"

echo ""
echo "=== SDD template frontmatter contract ==="

rc=0; grep -q 'spec_mode:' "$SHARED_DIR/templates/sdd/spec-template.md" || rc=1
assert_ok "spec-template.md contains spec_mode: in frontmatter" "$rc"

rc=0; grep -q 'feature_id:' "$SHARED_DIR/templates/sdd/spec-template.md" || rc=1
assert_ok "spec-template.md contains feature_id: in frontmatter" "$rc"

rc=0; grep -q 'status:' "$SHARED_DIR/templates/sdd/spec-template.md" || rc=1
assert_ok "spec-template.md contains status: in frontmatter" "$rc"

rc=0; grep -q 'spec_mode:' "$SHARED_DIR/templates/sdd/plan-template.md" || rc=1
assert_ok "plan-template.md contains spec_mode: in frontmatter" "$rc"

rc=0; grep -q 'justification:' "$SHARED_DIR/templates/sdd/plan-template.md" || rc=1
assert_ok "plan-template.md contains justification: in frontmatter" "$rc"

rc=0; grep -q 'status:' "$SHARED_DIR/templates/sdd/plan-template.md" || rc=1
assert_ok "plan-template.md contains status: in frontmatter" "$rc"

echo ""
echo "=== spec-workflow.md content ==="

SPEC_WORKFLOW="$SHARED_DIR/skills/spec-workflow/SKILL.md"

rc=0; grep -q 'spec_mode' "$SPEC_WORKFLOW" || rc=1
assert_ok "spec-workflow.md contains spec_mode classification" "$rc"

rc=0; grep -q '`full`' "$SPEC_WORKFLOW" || rc=1
assert_ok "spec-workflow.md contains full mode description" "$rc"

rc=0; grep -q '`lightweight`' "$SPEC_WORKFLOW" || rc=1
assert_ok "spec-workflow.md contains lightweight mode description" "$rc"

rc=0; grep -q '`none`' "$SPEC_WORKFLOW" || rc=1
assert_ok "spec-workflow.md contains none mode description" "$rc"

rc=0; grep -q '\[NEEDS CLARIFICATION\]' "$SPEC_WORKFLOW" || rc=1
assert_ok "spec-workflow.md contains [NEEDS CLARIFICATION] resolution rules" "$rc"

rc=0; grep -q 'Plan Approval Gate' "$SPEC_WORKFLOW" || rc=1
assert_ok "spec-workflow.md contains Plan Approval Gate section" "$rc"

rc=0; grep -q 'Build Agent Behavior' "$SPEC_WORKFLOW" || rc=1
assert_ok "spec-workflow.md contains Build Agent Behavior section" "$rc"

rc=0; grep -q 'Spec Artifacts Directory Convention' "$SPEC_WORKFLOW" || rc=1
assert_ok "spec-workflow.md contains Spec Artifacts Directory Convention section" "$rc"

echo ""
echo "=== lessons-learned-template.md content ==="

LESSONS_TEMPLATE="$SHARED_DIR/templates/sdd/lessons-learned-template.md"

rc=0; grep -q 'specs/lessons-learned.md' "$LESSONS_TEMPLATE" || rc=1
assert_ok "lessons-learned-template.md contains specs/lessons-learned.md canonical path" "$rc"

rc=0; grep -q 'Context.*Issue.*Resolution\|Context\|Takeaway' "$LESSONS_TEMPLATE" || rc=1
assert_ok "lessons-learned-template.md contains entry format guidance" "$rc"

rc=0; grep -q 'Plan agent\|Build agent' "$LESSONS_TEMPLATE" || rc=1
assert_ok "lessons-learned-template.md contains Plan and Build agent usage" "$rc"

echo ""
echo "=== review.md spec conformance ==="

REVIEW_MD="$ADAPTER_DIR/.claude/agents/review.md"

rc=0; grep -q 'Spec Conformance' "$REVIEW_MD" || rc=1
assert_ok "review.md contains Spec Conformance in output format" "$rc"

rc=0; grep -q 'spec-workflow' "$REVIEW_MD" || rc=1
assert_ok "review.md references spec-workflow skill" "$rc"

# ══════════════════════════════════════════════════════════════
# Agent contract consistency
# ══════════════════════════════════════════════════════════════

echo ""
echo "=== Agent contract consistency ==="

# No agent has both Write tool AND unscoped "never write files" ban
for agent in "$ADAPTER_DIR"/.claude/agents/*.md; do
  rc=0
  HAS_WRITE=$(grep -c "tools:.*Write" "$agent" 2>/dev/null) || HAS_WRITE=0
  UNSCOPED=$(grep -c "Never create, edit, or write files" "$agent" 2>/dev/null) || UNSCOPED=0
  if [[ "$HAS_WRITE" -gt 0 && "$UNSCOPED" -gt 0 ]]; then
    rc=1
  fi
  assert_ok "agent $(basename "$agent") has no unscoped write contradiction" "$rc"
done

# Every shipped agent sets effort in its frontmatter (#363)
for agent in "$ADAPTER_DIR"/.claude/agents/*.md; do
  rc=0
  awk '/^---[[:space:]]*$/{n++; next} n==1' "$agent" | grep -Eq '^effort: (low|medium|high)$' || rc=1
  assert_ok "agent $(basename "$agent") sets effort: low|medium|high in frontmatter" "$rc"
done

# Shared rules use "writes" not "emits" for Plan agent file creation
rc=0
EMIT_COUNT=$(grep -rl "Plan.*emits\|emits.*plan\|agent emits" "$SHARED_DIR/rules/" 2>/dev/null | wc -l | tr -d ' ')
if [[ "$EMIT_COUNT" -gt 0 ]]; then rc=1; fi
assert_ok "shared rules use 'writes' not 'emits' for Plan agent file creation (found $EMIT_COUNT files)" "$rc"

echo ""
echo "=== peer review enforcement: agent manifests and hook ==="

rc=0
grep -q 'phase-complete' "$ADAPTER_DIR/.claude/agents/build.md" || rc=1
assert_ok "build.md mentions phase-complete" "$rc"

rc=0
grep -q 'phase-complete' "$ADAPTER_DIR/.claude/agents/plan.md" || rc=1
assert_ok "plan.md mentions phase-complete" "$rc"

rc=0
grep -q 'phase-workflow' "$ADAPTER_DIR/.claude/agents/plan.md" || rc=1
assert_ok "plan.md reads phase-workflow skill" "$rc"

rc=0
grep -q 'Peer review gate' "$ADAPTER_DIR/.claude/agents/build.md" || rc=1
assert_ok "build.md has Peer review gate rule" "$rc"

rc=0
grep -q 'Action required.*phase-complete' "$ADAPTER_DIR/.claude/hooks/reinject-context.sh" || rc=1
assert_ok "reinject-context.sh has action-required reminder" "$rc"

# ══════════════════════════════════════════════════════════════
# Codespace tour (#214 Phase 6.2): the container definition is valid and
# every file the tour tells a visitor to run is really in the repository.
# A rename would otherwise leave the tour pointing at nothing.
# ══════════════════════════════════════════════════════════════
echo ""
echo "=== Codespace tour ==="
DEVCONTAINER="$REPO_DIR/.devcontainer/devcontainer.json"
TOUR="$REPO_DIR/docs/codespace-tour.md"

rc=0
jq -e '(.image | type) == "string" and (.postCreateCommand | type) == "string"' "$DEVCONTAINER" >/dev/null 2>&1 || rc=1
assert_ok "devcontainer.json is valid and names an image and a post-create command" "$rc"

rc=0
for f in $(jq -r '.postCreateCommand' "$DEVCONTAINER" | grep -oE '[A-Za-z0-9_./-]+\.sh') \
         $(jq -r '.customizations.codespaces.openFiles[]?' "$DEVCONTAINER"); do
  [[ -f "$REPO_DIR/$f" ]] || { echo "    devcontainer.json names a missing file: $f"; rc=1; }
done
assert_ok "the post-create script and the files it opens exist" "$rc"

rc=0
TOUR_CODE=$(awk '/^```bash$/{f=1; next} /^```$/{f=0} f' "$TOUR")
for f in $(grep -oE '(\./)?(scripts|tests|adapters)/[A-Za-z0-9_./-]+' <<<"$TOUR_CODE" | sed 's#^\./##' | sort -u); do
  [[ -e "$REPO_DIR/$f" ]] || { echo "    the tour runs a file that does not exist: $f"; rc=1; }
done
for h in $(grep -oE '~/\.claude/hooks/[A-Za-z0-9_.-]+' <<<"$TOUR_CODE" | sed 's#.*/##' | sort -u); do
  [[ -f "$ADAPTER_DIR/.claude/hooks/$h" ]] || { echo "    the tour runs a hook the adapter does not ship: $h"; rc=1; }
done
assert_ok "every script, test and hook the tour runs exists" "$rc"

rc=0
grep -q 'cct' <<<"$TOUR_CODE" && ! grep -qE '(^|[^./[:alnum:]_-])cct ' <<<"$TOUR_CODE" || rc=1
assert_ok "the tour calls ./scripts/cct, never a bare cct (setup does not put it on PATH)" "$rc"

# ══════════════════════════════════════════════════════════════
# README demo (#214 Phase 6.3). Rendering needs Docker and runs in its own
# workflow; here, without it: the tape points at real files, the image pin is
# the one that encodes, and the checker that makes the demo an executable test
# really does fail when a command breaks.
# ══════════════════════════════════════════════════════════════
echo ""
echo "=== README demo ==="
DEMO_DIR="$REPO_DIR/docs/demo"
TAPE="$DEMO_DIR/demo.tape"
TAPE_CHECK="$DEMO_DIR/check-tape.py"

rc=0
for f in $(grep -E '^Type ' "$TAPE" | grep -oE '(\./)?(scripts|tests|adapters)/[A-Za-z0-9_./-]+' | sed 's#^\./##' | sort -u); do
  [[ -e "$REPO_DIR/$f" ]] || { echo "    the tape runs a file that does not exist: $f"; rc=1; }
done
for h in $(grep -E '^Type ' "$TAPE" | grep -oE '~/\.claude/hooks/[A-Za-z0-9_.-]+' | sed 's#.*/##' | sort -u); do
  [[ -f "$ADAPTER_DIR/.claude/hooks/$h" ]] || { echo "    the tape runs a hook the adapter does not ship: $h"; rc=1; }
done
assert_ok "every script and hook the demo tape runs exists" "$rc"

rc=0
[[ -x "$DEMO_DIR/render.sh" ]] && grep -q 'check-tape.py' "$DEMO_DIR/render.sh" || rc=1
assert_ok "render.sh is executable and checks the tape before rendering it" "$rc"

rc=0
grep -qE '^FROM ghcr\.io/charmbracelet/vhs:v0\.11\.0$' "$DEMO_DIR/Dockerfile" || rc=1
assert_ok "the demo image stays on the VHS release that encodes (v0.12.0 writes no file)" "$rc"

rc=0
grep -qF '](docs/images/demo.gif)' "$REPO_DIR/README.md" && [[ -s "$REPO_DIR/docs/images/demo.gif" ]] || rc=1
assert_ok "the README shows the demo from docs/images, by a path the site can rewrite" "$rc"

DEMO_TMP=$(mktemp -d)
printf '# expect: hello\nType "clear" Enter\nType "# note" Enter\nType "echo hello | cat" Enter\n' > "$DEMO_TMP/good.tape"
printf '# expect: hello\nType "echo hello" Enter\nType "false | cat" Enter\n' > "$DEMO_TMP/broken.tape"
printf '# expect: goodbye\nType "echo hello" Enter\n' > "$DEMO_TMP/changed.tape"
printf '# expect: hi\nType "echo hi" Enter\nType echo unquoted Enter\n' > "$DEMO_TMP/unparsed.tape"
rc_good=0;    python3 "$TAPE_CHECK" "$DEMO_TMP/good.tape"    >/dev/null 2>&1 || rc_good=$?
rc_broken=0;  python3 "$TAPE_CHECK" "$DEMO_TMP/broken.tape"  >/dev/null 2>&1 || rc_broken=$?
rc_changed=0; python3 "$TAPE_CHECK" "$DEMO_TMP/changed.tape" >/dev/null 2>&1 || rc_changed=$?
rc_unparsed=0; python3 "$TAPE_CHECK" "$DEMO_TMP/unparsed.tape" >/dev/null 2>&1 || rc_unparsed=$?
rm -rf "$DEMO_TMP"
assert_eq "the tape checker passes a tape whose commands work" "0" "$rc_good"
assert_eq "it fails when a command in a pipeline breaks" "1" "$rc_broken"
assert_eq "it fails when the output no longer contains what the tape expects" "1" "$rc_changed"
assert_eq "it refuses a Type line it cannot parse rather than skipping its command" "1" "$rc_unparsed"

# ══════════════════════════════════════════════════════════════
# The CCT home has one resolver per language (#411)
# ══════════════════════════════════════════════════════════════
# ${CCT_HOME:-~/.cct} with ~/.code-copilot-team served as a fallback is
# decided in scripts/lib/cct-home.sh, session_analytics/home.py and
# adapters/pi/runtime/config/home.ts, and nowhere else. Installed scripts
# that run without a checkout carry the bash block verbatim; any other code
# that spells either home as a path would hide the move from the fallback
# and the doctor.
echo "=== CCT home: one resolver, verbatim copies, no stray spelling ==="
HOME_LIB="$REPO_DIR/scripts/lib/cct-home.sh"
home_block() { awk '/^# >>> cct-home resolver/{f=1} f{print} /^# <<< cct-home resolver/{f=0}' "$1"; }
HOME_BLOCK=$(home_block "$HOME_LIB")
rc=0; [[ -n "$HOME_BLOCK" ]] || rc=1
assert_ok "scripts/lib/cct-home.sh has the marked resolver block" "$rc"
for copy in adapters/claude-code/.claude/hooks/harness-stamp.sh adapters/claude-code/claude-code adapters/pi/bin/pi-code; do
  rc=0; [[ "$(home_block "$REPO_DIR/$copy")" == "$HOME_BLOCK" ]] || rc=1
  assert_ok "$copy carries the resolver block verbatim" "$rc"
done
# The guard (FR-9): no code outside the resolvers spells a CCT home. A
# candidate is a non-comment line naming either directory after a tilde
# (~/.cct, ~/.code-copilot-team), or a line that has a home lookup ($HOME,
# ${HOME}, Path.home(), homedir(), os.environ["HOME"], environ.get("HOME"),
# getenv("HOME"), process.env.HOME, env["HOME"], a bare "~" string as in
# expanduser("~")) and EITHER directory token anywhere after it on the same
# line, whatever sits between (joinpath, f-strings, concatenation). No file is exempt: the
# resolvers spell both names through constants (CCT_HOME_DEFAULT_REL,
# HOME_LEGACY_REL, ...), so their code produces no candidates, and any line
# in them that does is compared like every other line. Only a line whose
# FIRST non-blank characters are a comment marker (#, //, *, /*) is skipped;
# a code line with a trailing comment is scanned like any other.
#
# Nothing is exempt by meaning either. Display-only occurrences (help text,
# messages, docstrings, Studio copy) are listed one by one in
# tests/fixtures/home-guard/baseline.txt as "<file><TAB><trimmed line>".
# RULE: an entry there must be text a person reads, never a path the code
# reads, writes, creates or passes on; a real path goes through a resolver.
# Lines starting with # in the baseline are its own header, not entries. The
# comparison is a multiset: a new occurrence anywhere, including a second
# copy of a listed line in a listed file, fails until it is reviewed and
# added; a listed occurrence that no longer exists fails too, so the list
# stays exact.
#
# Best effort, by decision (FR-9): a lookup joined to either directory
# through a variable or constant (home = Path.home() then home / ".cct", or a
# new DOT = ".cct"), or split inside a multi-line string, is not detected;
# review covers those. Do not grow the guard to chase further shapes.
#
# No \b: macOS `git grep -E` treats \b as matching nothing, which made an
# earlier draft scan zero lines and pass. The candidate count proves the scan
# reads something.
HOME_END='([^[:alnum:]_-]|$)'
HOME_ID_END='([^[:alnum:]_]|$)'
HOME_Q='["'"'"'`]'
HOME_SRC="(\\\$HOME$HOME_ID_END|\\\$\\{HOME[}:]|Path[[:space:]]*\\.[[:space:]]*home[[:space:]]*\\([[:space:]]*\\)|homedir[[:space:]]*\\([[:space:]]*\\)|environ[[:space:]]*\\[[[:space:]]*${HOME_Q}HOME${HOME_Q}|environ\\.get\\([[:space:]]*${HOME_Q}HOME${HOME_Q}|getenv\\([[:space:]]*${HOME_Q}HOME${HOME_Q}|env\\.HOME$HOME_ID_END|env\\[[[:space:]]*${HOME_Q}HOME${HOME_Q}|${HOME_Q}~${HOME_Q})"
HOME_SPELLING="(~/\\.(code-copilot-team|cct)$HOME_END)|($HOME_SRC.*\\.(code-copilot-team|cct)$HOME_END)"
HOME_BASELINE="$REPO_DIR/tests/fixtures/home-guard/baseline.txt"
home_baseline() { grep -v '^#' "$HOME_BASELINE" | LC_ALL=C sort; }   # entries only, sorted
home_occurrences() {  # stdin: "<file>:<line>:<text>" → sorted "<file><TAB><trimmed text>", one per occurrence
  grep -E "$HOME_SPELLING" \
    | grep -vE '^[^:]+:[0-9]+:[[:space:]]*(#|//|\*|/\*)' \
    | sed -E 's/^([^:]+):[0-9]+:[[:space:]]*/\1	/; s/[[:space:]]+$//' \
    | LC_ALL=C sort || true
}
home_unreviewed() {  # stdin as above → occurrences not covered by the baseline (multiset)
  LC_ALL=C comm -23 <(home_occurrences) <(home_baseline)
}
# A home construction split across lines (Path.home().joinpath( then ".cct"
# on the next line) has no single line holding both parts. The expression
# scan starts at each home lookup and follows the expression that contains
# it, through balanced brackets or a trailing backslash, so the split form is
# caught while the next independent statement (repo_root / ".cct") is not.
# It needs python3, as the tape checker above does; without it the planted
# split cases below fail loudly rather than passing.
HOME_EXPR_SCAN="$REPO_DIR/tests/fixtures/home-guard/expr_scan.py"
home_expr_occurrences() {  # [<repo dir>] → "<file><TAB><expression>" for split home constructions
  (cd "${1:-$REPO_DIR}" && git grep -lz -E "$HOME_SRC" -- "${HOME_PATHSPEC[@]}" 2>/dev/null \
    | HOME_SRC="$HOME_SRC" HOME_END="$HOME_END" python3 "$HOME_EXPR_SCAN")
}
home_all_occurrences() {  # [<repo dir>] → every occurrence, line scan and expression scan, sorted
  { home_discover "${1:-$REPO_DIR}" | home_occurrences; home_expr_occurrences "${1:-$REPO_DIR}"; } | LC_ALL=C sort
}
# Discovery covers every tracked code and config file: prose (Markdown, the
# generated .mdc rules, specs, the wiki, CHANGELOG, llms.txt, the static pages
# in docs/visual/) and test code are the only exclusions.
HOME_PATHSPEC=(. ':!*.md' ':!*.mdc' ':!specs' ':!knowledge' ':!CHANGELOG.md' ':!llms.txt' ':!*.jsonl' ':!docs/visual/*.html' ':!tests' ':!*/tests/*')
home_discover() {  # [<repo dir>] → "<file>:<line>:<text>" for every tracked line naming either directory
  (cd "${1:-$REPO_DIR}" && git grep -n -E "\.(code-copilot-team|cct)$HOME_END" -- "${HOME_PATHSPEC[@]}" 2>/dev/null)
}
HOME_CANDIDATES=$(home_discover)
rc=0; [[ $(grep -c . <<<"$HOME_CANDIDATES") -ge 20 ]] || rc=1
assert_ok "the home guard's candidate scan reads lines (it is not a silent no-op)" "$rc"
HOME_ALL=$(home_all_occurrences)
STRAY=$(LC_ALL=C comm -23 <(printf '%s\n' "$HOME_ALL" | sed '/^$/d') <(home_baseline))
rc=0; [[ -z "$STRAY" ]] || rc=1
assert_ok "no detected CCT home spelling outside the resolvers is missing from the reviewed baseline${STRAY:+ (unreviewed: $(cut -f1 <<<"$STRAY" | sort -u | tr '\n' ' '))}" "$rc"
GONE=$(LC_ALL=C comm -13 <(printf '%s\n' "$HOME_ALL" | sed '/^$/d') <(home_baseline))
rc=0; [[ -z "$GONE" ]] || rc=1
assert_ok "every baseline entry still occurs (the list is exact)${GONE:+ (stale: $(cut -f1 <<<"$GONE" | sort -u | tr '\n' ' '))}" "$rc"
# The guard bites, through real discovery: each planted file goes into a
# throwaway git repository and is found (or not) by home_discover, the same
# git grep the real scan uses, so scope and matching are both exercised.
# "<path>|<line>": the line is written to <path>; a listed baseline line
# written twice into its own file proves the multiset (a second copy fails).
home_flags_planted() {  # <path> <line>... → 0 if the guard flags the planted file (one line per argument)
  local repo out
  repo=$(mktemp -d)
  mkdir -p "$repo/$(dirname "$1")"
  printf '%s\n' "${@:2}" > "$repo/$1"
  (cd "$repo" && git init -q . && git add -A) >/dev/null 2>&1
  out=$(LC_ALL=C comm -23 <(home_all_occurrences "$repo" | sed '/^$/d') <(home_baseline))
  rm -rf "$repo"
  [[ -n "$out" ]]
}
FIRST_LISTED=$(home_baseline | head -1)
while IFS='|' read -r ppath pline; do
  [[ -n "$ppath" ]] || continue
  rc=0; home_flags_planted "$ppath" "$pline" || rc=1
  assert_ok "the home guard flags a planted spelling in $ppath: $pline" "$rc"
done <<'PLANTED'
scripts/lib/routing-state.sh|RS_FILE="${CCT_ROUTING_STATE:-$HOME/.code-copilot-team/routing-state.json}"
scripts/session_analytics/config.py|_USER_CONFIG = Path.home() / ".cct" / "session-analytics.json"
scripts/x.sh|cat ~/.cct/providers.toml
scripts/x.sh|FILE=~/.cct/providers.toml
scripts/x.py|p = Path(os.environ["HOME"]) / ".cct" / "providers.toml"
scripts/x.py|p = os.environ.get("HOME") + "/.cct/routing.toml"
adapters/pi/runtime/x.ts|const p = path.join(process.env.HOME!, ".cct", "llms.toml");
adapters/pi/runtime/x.ts|const p = path.join(os.homedir(), ".code-copilot-team");
scripts/x.py|REG = os.path.expanduser("~/.cct/routing.toml")
scripts/cct|cat ~/.cct/providers.toml
scripts/lib/cct_doctor.py|p = Path.home() / ".cct" / "secret"
adapters/pi/bin/pi-code|STATE="$HOME/.cct/state"
scripts/lib/cct-home.sh|cat "$HOME/.code-copilot-team/providers.toml"
scripts/session_analytics/home.py|LEGACY = Path.home() / ".code-copilot-team"
scripts/x.sh|cat ~/.cct/providers.toml   # read the profile
scripts/x.py|open(Path.home() / ".cct" / "llms.toml")  # the catalog
scripts/x.py|p = Path.home().joinpath(".cct", "providers.toml")
scripts/x.py|p = Path(os.getenv("HOME")).joinpath(".cct")
scripts/x.py|p = f"{Path.home()}/.cct/providers.toml"
scripts/x.py|p = os.path.join(os.path.expanduser("~"), ".code-copilot-team", "pi")
adapters/pi/runtime/x.ts|const p = `${os.homedir()}/.cct/llms.toml`;
scripts/x.py|p = Path.home( ) / ".cct" / "providers.toml"
benchmarks/presets/x.json|"registry": "~/.cct/other-routing.toml"
.github/workflows/x.yml|run: cat ~/.cct/providers.toml
shared/templates/x.toml|path = "${HOME}/.cct/providers.toml"
PLANTED
rc=0; home_flags_planted "${FIRST_LISTED%%	*}" "${FIRST_LISTED#*	}" "${FIRST_LISTED#*	}" || rc=1
assert_ok "the home guard flags a second copy of a listed line in its listed file" "$rc"
# Split constructions are flagged through the expression scan...
rc=0; home_flags_planted scripts/x.py 'path = Path.home().joinpath(' '    ".cct", "providers.toml"' ')' || rc=1
assert_ok "the home guard flags a Python home construction split across lines" "$rc"
rc=0; home_flags_planted adapters/pi/runtime/x.ts 'const p = path.join(' '  os.homedir(),' '  ".cct",' '  "llms.toml",' ');' || rc=1
assert_ok "the home guard flags a TypeScript home construction split across lines" "$rc"
rc=0; home_flags_planted scripts/x.sh 'dest="${HOME}"\' '"/.cct/providers.toml"' || rc=1
assert_ok "the home guard flags a shell home construction continued with a backslash" "$rc"
rc=0; home_flags_planted .github/workflows/x.yml 'jobs:' '  x:' '    steps:' '      - run: |' '          cp profile.toml \' '            "$HOME"/\' '.cct/providers.toml' || rc=1
assert_ok "the home guard flags a workflow home construction continued with a backslash" "$rc"
# ...while the next independent statement after a home lookup is not part of it.
for neg in py:'home = Path.home()|state = repo_root / ".cct" / "review"' ts:'const home = os.homedir();|const p = path.join(repoRoot, ".cct", "team.json");' sh:'log "$HOME"|STATE="$REPO/.cct/state.json"'; do
  ext="${neg%%:*}"; body="${neg#*:}"
  rc=0; home_flags_planted "scripts/neg.$ext" "${body%%|*}" "${body#*|}" && rc=1
  assert_ok "the home guard does not flag a per-project .cct path in the statement after a home lookup ($ext)" "$rc"
done
# ...and does not flag look-alikes that are not a home: an identifier that
# merely starts with HOME, a non-Path .home() method, a per-project .cct path.
for lookalike in 'p="$HOMELESS/.cct/x"' 'p = account.home() + "/.cct"' 'p = os.path.join(repo_root, ".cct", "review")'; do
  rc=0; home_flags_planted scripts/x.py "$lookalike" && rc=1
  assert_ok "the home guard does not flag a look-alike: $lookalike" "$rc"
done
# The exactness check bites: a baseline entry with no occurrence is reported.
rc=0; [[ -n "$(LC_ALL=C comm -13 <(home_occurrences <<<"$HOME_CANDIDATES") <(printf '%s\n' "$(home_baseline)" "scripts/x.sh	echo ~/.cct/removed" | LC_ALL=C sort))" ]] || rc=1
assert_ok "the home guard reports a baseline entry that no longer occurs" "$rc"
# ...while the resolver's constant (no home construction) and a comment are not candidates.
PLANTED=$(printf '%s\n' 'scripts/lib/cct-home.sh:18:CCT_HOME_LEGACY_REL=".code-copilot-team"' 'scripts/setup.sh:3:# the legacy home is ~/.code-copilot-team' | home_occurrences)
rc=0; [[ -z "$PLANTED" ]] || rc=1
assert_ok "...while the resolver's name constant and a comment are not candidates" "$rc"

# ══════════════════════════════════════════════════════════════
# Simplest Complete Change (#389): the two collision rules ship
# ══════════════════════════════════════════════════════════════
# Text-presence checks (spec FR-008): they prove the rules ship, not that an
# agent follows them. Each fails if its rule is removed from the source.

echo ""
echo "=== Simplest Complete Change (#389) ==="
SCC_CONV="$SKILLS_DIR_PATH/copilot-conventions/SKILL.md"
SCC_STD="$SKILLS_DIR_PATH/coding-standards/SKILL.md"
# Collision 1, "tiny default vs configuration policy": configuration wins.
rc=0; grep -q "A tiny in-code default is not the simpler choice when configuration policy applies" "$SCC_STD" || rc=1
assert_ok "coding-standards keeps the precedence rule (tiny default vs configuration policy)" "$rc"
# Collision 2, "small local fix misses another caller": completeness wins.
rc=0; grep -q "A small local fix that misses another caller is incomplete, not simple" "$SCC_CONV" || rc=1
assert_ok "copilot-conventions keeps the completeness rule (small local fix misses another caller)" "$rc"
rc=0; grep -q "Only then, the simplest complete custom design" "$SCC_CONV" && ! grep -q "simplest complete custom design" "$SCC_STD" || rc=1
assert_ok "the reuse ladder lives only in copilot-conventions (C-002)" "$rc"
rc=0; grep -q "shared/skills/clarification-protocol/SKILL.md" "$SCC_CONV" || rc=1
assert_ok "copilot-conventions points at the clarification protocol, tool-neutral (FR-003)" "$rc"
rc=0; grep -q "retain selective, high-value decisions" "$SKILLS_DIR_PATH/memkernel-memory/SKILL.md" || rc=1
assert_ok "memkernel-memory qualifies decision records as selective and high-value (FR-005)" "$rc"
rc=0; grep -q "must also name the viable" "$SHARED_DIR/review/CODE_REVIEW.md" || rc=1
assert_ok "CODE_REVIEW.md requires a named replacement for removal findings (FR-006)" "$rc"
# The tracked Claude Code rule copies (~/.claude/rules links into them) must
# stay the frontmatter-stripped skill bodies that setup.sh installs.
for name in coding-standards copilot-conventions copyright-headers safety; do
  rc=0
  [[ "$(awk 'BEGIN{n=0} /^---$/{n++; if(n==2){found=1; next}} found{print}' "$SKILLS_DIR_PATH/$name/SKILL.md")" == "$(cat "$REPO_DIR/claude_code/.claude/rules/$name.md")" ]] || rc=1
  assert_ok "claude_code/.claude/rules/$name.md matches its shared skill body" "$rc"
done

# ══════════════════════════════════════════════════════════════
# No test code sends a crash signal (#547)
# ══════════════════════════════════════════════════════════════
# A process ended by a core-dumping signal (SEGV, BUS, ILL, ABRT, FPE, TRAP,
# QUIT, SYS, EMT) makes macOS write a crash report and show a "quit
# unexpectedly" dialog, one per process, so a fixture that simulates a crash
# that way fills the screen on every run, as #547's mock harness did.
# Simulate one with the status a shell reports for it instead (exit 128 + N).
# The scan reads every tracked file under tests/, scripts/ and adapters/ but
# prose and this file, which spells the forms out. It knows these forms:
# kill by name or number, Python's os.kill, signal.raise_signal and os.abort,
# faulthandler's crash helpers, and Node's process.kill and process.abort.

echo ""
echo "=== No test code sends a crash signal (#547) ==="
CRASH_SIGS='(SEGV|BUS|ILL|ABRT|FPE|TRAP|QUIT|SYS|EMT)'
CRASH_SEND="(^|[^[:alnum:]_])kill[[:space:]]+(-s[[:space:]]+)?-?(SIG)?${CRASH_SIGS}([^[:alnum:]_]|$)|(^|[^[:alnum:]_])kill[[:space:]]+-(3|4|5|6|7|8|10|11|12|31)([^[:alnum:]_]|$)|os\\.kill\\(.*SIG${CRASH_SIGS}|raise_signal\\(.*SIG${CRASH_SIGS}|os\\.abort\\(|faulthandler\\._|process\\.kill\\(.*SIG${CRASH_SIGS}|process\\.abort\\("
CRASH_PATHSPEC=(tests scripts adapters ':!*.md' ':!tests/test-shared-structure.sh')
crash_senders() {  # [<repo dir>] → "<file>:<line>:<text>" for each tracked line that sends a crash signal
  (cd "${1:-$REPO_DIR}" && git grep -n -E "$CRASH_SEND" -- "${CRASH_PATHSPEC[@]}" 2>/dev/null)
}
rc=0; [[ $(cd "$REPO_DIR" && git ls-files -- "${CRASH_PATHSPEC[@]}" | grep -c .) -ge 100 ]] || rc=1
assert_ok "the crash-signal scan covers the tracked test and script files (it is not a silent no-op)" "$rc"
CRASH_FOUND=$(crash_senders)
rc=0; [[ -z "$CRASH_FOUND" ]] || rc=1
assert_ok "no tracked test or script code sends a crash signal${CRASH_FOUND:+ (found: $(cut -d: -f1,2 <<<"$CRASH_FOUND" | tr '\n' ' '))}" "$rc"
# The guard bites, through the same git grep, on files planted in a
# throwaway repository; the status a shell reports is not a signal.
crash_flags_planted() {  # <path> <line> → 0 if the guard flags the planted line
  local repo out
  repo=$(mktemp -d)
  mkdir -p "$repo/$(dirname "$1")"
  printf '%s\n' "$2" > "$repo/$1"
  (cd "$repo" && git init -q . && git add -A) >/dev/null 2>&1
  out=$(crash_senders "$repo")
  rm -rf "$repo"
  [[ -n "$out" ]]
}
while IFS='|' read -r ppath pline; do
  [[ -n "$ppath" ]] || continue
  rc=0; crash_flags_planted "$ppath" "$pline" || rc=1
  assert_ok "the crash-signal guard flags $ppath: $pline" "$rc"
done <<'PLANTED'
tests/fixtures/x.py|        os.kill(os.getpid(), signal.SIGSEGV)
tests/x.sh|kill -SEGV $$
scripts/x.py|os.abort()
PLANTED
rc=0; ! crash_flags_planted tests/fixtures/x.py "        os._exit(128 + signal.SIGSEGV)" || rc=1
assert_ok "...and lets a fixture exit with the status a shell reports for one (128 + N)" "$rc"

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
