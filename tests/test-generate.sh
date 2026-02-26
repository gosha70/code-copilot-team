#!/usr/bin/env bash

# test-generate.sh — Automated tests for the generation pipeline
#
# Run from the repo root:
#   bash tests/test-generate.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$SCRIPT_DIR/.."
ADAPTERS="$REPO_DIR/adapters"
SHARED="$REPO_DIR/shared/rules"
PASS=0
FAIL=0

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

assert_contains() {
  local name="$1" file="$2" pattern="$3"
  if grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (pattern not found: $pattern)"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local name="$1" file="$2" pattern="$3"
  if ! grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (pattern should not be present: $pattern)"
    FAIL=$((FAIL + 1))
  fi
}

# ── Section 1: Run generator ──────────────────────────────

echo "=== Running generate.sh ==="
bash "$REPO_DIR/scripts/generate.sh" >/dev/null 2>&1
RC=$?
assert "generate.sh exits 0" "[[ $RC -eq 0 ]]"

# ── Section 2: Codex AGENTS.md existence and size ─────────

echo ""
echo "=== Codex AGENTS.md ==="

AGENTS_MD="$ADAPTERS/codex/AGENTS.md"

assert "AGENTS.md exists" "[[ -f '$AGENTS_MD' ]]"

SIZE=$(wc -c < "$AGENTS_MD" | tr -d ' ')
assert "AGENTS.md under 32 KiB ($SIZE bytes)" "[[ $SIZE -lt 32768 ]]"
assert "AGENTS.md is non-empty" "[[ $SIZE -gt 0 ]]"

# ── Section 3: AGENTS.md contains all always-on rules ─────

echo ""
echo "=== AGENTS.md content — always-on rules ==="

assert_contains "contains Coding Standards header" "$AGENTS_MD" "^# Coding Standards"
assert_contains "contains Quality Gates section" "$AGENTS_MD" "## Quality Gates"
assert_contains "contains Prohibited Patterns section" "$AGENTS_MD" "## Prohibited Patterns"

assert_contains "contains Cross-Copilot Conventions header" "$AGENTS_MD" "^# Cross-Copilot Conventions"
assert_contains "contains Core Contract section" "$AGENTS_MD" "## Core Contract"
assert_contains "contains Git Discipline section" "$AGENTS_MD" "## Git Discipline"

assert_contains "contains Agent Safety Rules header" "$AGENTS_MD" "^# Agent Safety Rules"
assert_contains "contains Secrets section" "$AGENTS_MD" "## Secrets & Credentials"
assert_contains "contains Input Validation section" "$AGENTS_MD" "## Input Validation"

# Verify key content from each rule file is present
assert_contains "has lint errors: 0" "$AGENTS_MD" "Lint errors: 0"
assert_contains "has SQL injection rule" "$AGENTS_MD" "parameterized queries"
assert_contains "has read before write" "$AGENTS_MD" "Read before write"
assert_contains "has imperative mood" "$AGENTS_MD" "imperative mood"
assert_contains "has destructive commands" "$AGENTS_MD" "rm -rf"
assert_contains "has password storage" "$AGENTS_MD" "## Password Storage"

# ── Section 4: AGENTS.md on-demand rules reference ────────

echo ""
echo "=== AGENTS.md content — on-demand rules reference ==="

assert_contains "has on-demand reference section" "$AGENTS_MD" "## On-Demand Rules Reference"
assert_contains "has auto-generated notice" "$AGENTS_MD" "Auto-generated from shared/rules/always"

# Verify all on-demand rules are referenced
for f in "$SHARED/on-demand"/*.md; do
  name="$(basename "$f" .md)"
  assert_contains "references on-demand rule: $name" "$AGENTS_MD" "$name"
done

# Verify skill mappings
assert_contains "ralph-loop mapped to build" "$AGENTS_MD" "ralph-loop.*build"
assert_contains "agent-team-protocol mapped to build optional team mode" "$AGENTS_MD" "agent-team-protocol.*build (optional team mode)"
assert_contains "team-lead-efficiency mapped to build optional team mode" "$AGENTS_MD" "team-lead-efficiency.*build (optional team mode)"
assert_contains "clarification-protocol mapped to plan" "$AGENTS_MD" "clarification-protocol.*plan"
assert_contains "integration-testing mapped to review" "$AGENTS_MD" "integration-testing.*review"
assert_contains "token-efficiency mapped to research" "$AGENTS_MD" "token-efficiency.*research"

# ── Section 5: Codex adapter structure ────────────────────

echo ""
echo "=== Codex adapter structure ==="

assert "config.toml exists" "[[ -f '$ADAPTERS/codex/config.toml' ]]"
assert "setup.sh exists" "[[ -f '$ADAPTERS/codex/setup.sh' ]]"
assert "setup.sh is executable" "[[ -x '$ADAPTERS/codex/setup.sh' ]]"

# Verify all 5 skills exist
for skill in research plan build review verify-app; do
  SKILL_FILE="$ADAPTERS/codex/.agents/skills/$skill/SKILL.md"
  assert "skill $skill exists" "[[ -f '$SKILL_FILE' ]]"
done

SKILL_COUNT=$(ls -d "$ADAPTERS/codex/.agents/skills"/*/ 2>/dev/null | wc -l | tr -d ' ')
assert "exactly 5 skills ($SKILL_COUNT)" "[[ $SKILL_COUNT -eq 5 ]]"

# ── Section 6: Skill content verification ─────────────────

echo ""
echo "=== Codex skill content ==="

# Research skill
RESEARCH="$ADAPTERS/codex/.agents/skills/research/SKILL.md"
assert_contains "research: has YAML frontmatter name" "$RESEARCH" "^name: research"
assert_contains "research: has description" "$RESEARCH" "^description:"
assert_contains "research: mentions no code changes" "$RESEARCH" "[Nn]ever.*write\|[Nn]ever.*create\|[Nn]o code changes"
assert_contains "research: has output format" "$RESEARCH" "## Output Format"

# Plan skill
PLAN="$ADAPTERS/codex/.agents/skills/plan/SKILL.md"
assert_contains "plan: has YAML frontmatter name" "$PLAN" "^name: plan"
assert_contains "plan: mentions no code changes" "$PLAN" "[Nn]ever.*write\|[Nn]ever.*create\|[Nn]o code changes"
assert_contains "plan: has task breakdown" "$PLAN" "Task Breakdown\|Task.*description"
assert_not_contains "plan: no Task tool reference" "$PLAN" "Task tool"

# Build skill
BUILD="$ADAPTERS/codex/.agents/skills/build/SKILL.md"
assert_contains "build: has YAML frontmatter name" "$BUILD" "^name: build"
assert_contains "build: uses Ralph Loop" "$BUILD" "Ralph Loop"
assert_not_contains "build: no Task tool delegation" "$BUILD" "Task tool"
assert_not_contains "build: no sub-agent reference" "$BUILD" "sub-agent"
assert_contains "build: has sequential execution" "$BUILD" "[Ss]equential"
assert_contains "build: has verification section" "$BUILD" "Verification"
assert_contains "build: has team mode section" "$BUILD" "Team Mode"
assert_contains "build: has delegation fallback guidance" "$BUILD" "[Ff]allback\\|delegation is unavailable"

# Review skill
REVIEW="$ADAPTERS/codex/.agents/skills/review/SKILL.md"
assert_contains "review: has YAML frontmatter name" "$REVIEW" "^name: review"
assert_contains "review: mentions no file changes" "$REVIEW" "[Nn]ever.*create\|[Nn]ever.*edit\|[Nn]ever.*write"
assert_contains "review: has verdict format" "$REVIEW" "PASS.*FAIL\|Verdict"

# Verify-app skill
VERIFY="$ADAPTERS/codex/.agents/skills/verify-app/SKILL.md"
assert_contains "verify-app: has YAML frontmatter name" "$VERIFY" "^name: verify-app"
assert_contains "verify-app: detects project stack" "$VERIFY" "package.json\|pyproject.toml\|go.mod"
assert_contains "verify-app: has type checker" "$VERIFY" "Type [Cc]hecker"
assert_contains "verify-app: has linter" "$VERIFY" "Linter"
assert_contains "verify-app: has test suite" "$VERIFY" "Test Suite\|test.*suite"
assert_contains "verify-app: has runtime observability section" "$VERIFY" "Runtime Observability"
assert_contains "verify-app: output includes UI smoke row" "$VERIFY" "UI smoke"
assert_contains "verify-app: output includes console row" "$VERIFY" "Console"
assert_contains "verify-app: output includes network row" "$VERIFY" "Network"
assert_contains "verify-app: has visual smoke test section" "$VERIFY" "Visual Smoke Test"
assert_contains "verify-app: output includes visual row" "$VERIFY" "Visual"
assert_contains "verify-app: no file modification" "$VERIFY" "[Nn]ever modify"

# All skills must include machine-checkable completion criteria
for skill in research plan build review verify-app; do
  SKILL_FILE="$ADAPTERS/codex/.agents/skills/$skill/SKILL.md"
  assert_contains "$skill: has Definition of Done section" "$SKILL_FILE" "Definition of Done"
  assert_contains "$skill: has PASS/FAIL checklist markers" "$SKILL_FILE" "PASS/FAIL:"
done

# ── Section 7: No Claude-specific leakage ─────────────────

echo ""
echo "=== No Claude-specific leakage in Codex skills ==="

for skill in research plan build review verify-app; do
  SKILL_FILE="$ADAPTERS/codex/.agents/skills/$skill/SKILL.md"
  assert_not_contains "$skill: no ~/.claude reference" "$SKILL_FILE" "~/.claude"
  assert_not_contains "$skill: no rules-library path" "$SKILL_FILE" "rules-library"
  assert_not_contains "$skill: no CLAUDE.md reference" "$SKILL_FILE" "CLAUDE.md"
done

# ── Section 8: config.toml content ────────────────────────

echo ""
echo "=== Codex config.toml ==="

CONFIG="$ADAPTERS/codex/config.toml"
assert_contains "has project_doc_max_bytes" "$CONFIG" "project_doc_max_bytes"
assert_contains "max bytes is 65536" "$CONFIG" "65536"

# ── Section 9: setup.sh content ───────────────────────────

echo ""
echo "=== Codex setup.sh ==="

SETUP="$ADAPTERS/codex/setup.sh"
assert_contains "setup.sh has shebang" "$SETUP" "^#!/bin/bash"
assert_contains "setup.sh references ~/.codex" "$SETUP" '\.codex'
assert_contains "setup.sh installs AGENTS.md" "$SETUP" "AGENTS.md"
assert_contains "setup.sh installs skills" "$SETUP" "skills"
assert_contains "setup.sh supports --sync" "$SETUP" "\-\-sync"

# ── Section 10: Cursor .mdc files ─────────────────────────

echo ""
echo "=== Cursor .mdc files ==="

CURSOR_RULES="$ADAPTERS/cursor/.cursor/rules"

assert "cursor rules dir exists" "[[ -d '$CURSOR_RULES' ]]"

# Verify 3 .mdc files (one per always-on rule)
MDC_COUNT=$(ls "$CURSOR_RULES"/*.mdc 2>/dev/null | wc -l | tr -d ' ')
assert "exactly 3 .mdc files ($MDC_COUNT)" "[[ $MDC_COUNT -eq 3 ]]"

assert "coding-standards.mdc exists" "[[ -f '$CURSOR_RULES/coding-standards.mdc' ]]"
assert "copilot-conventions.mdc exists" "[[ -f '$CURSOR_RULES/copilot-conventions.mdc' ]]"
assert "safety.mdc exists" "[[ -f '$CURSOR_RULES/safety.mdc' ]]"

# Verify frontmatter structure
for mdc in coding-standards copilot-conventions safety; do
  MDC_FILE="$CURSOR_RULES/$mdc.mdc"
  assert_contains "$mdc.mdc: has frontmatter start" "$MDC_FILE" "^---"
  assert_contains "$mdc.mdc: has description field" "$MDC_FILE" "^description:"
  assert_contains "$mdc.mdc: has alwaysApply: true" "$MDC_FILE" "^alwaysApply: true"
done

# Verify content from source rules is present
assert_contains "coding-standards.mdc: has Quality Gates" "$CURSOR_RULES/coding-standards.mdc" "Quality Gates"
assert_contains "copilot-conventions.mdc: has Core Contract" "$CURSOR_RULES/copilot-conventions.mdc" "Core Contract"
assert_contains "safety.mdc: has Secrets & Credentials" "$CURSOR_RULES/safety.mdc" "Secrets & Credentials"

# Verify descriptions match first headings
assert_contains "coding-standards.mdc: description is Coding Standards" "$CURSOR_RULES/coding-standards.mdc" 'description: "Coding Standards"'
assert_contains "copilot-conventions.mdc: description is Cross-Copilot" "$CURSOR_RULES/copilot-conventions.mdc" 'description: "Cross-Copilot Conventions"'
assert_contains "safety.mdc: description is Agent Safety" "$CURSOR_RULES/safety.mdc" 'description: "Agent Safety Rules"'

# ── Section 11: Cursor setup.sh ───────────────────────────

echo ""
echo "=== Cursor setup.sh ==="

CURSOR_SETUP="$ADAPTERS/cursor/setup.sh"
assert "cursor setup.sh exists" "[[ -f '$CURSOR_SETUP' ]]"
assert "cursor setup.sh is executable" "[[ -x '$CURSOR_SETUP' ]]"
assert_contains "cursor setup.sh has shebang" "$CURSOR_SETUP" "^#!/bin/bash"
assert_contains "cursor setup.sh supports --sync" "$CURSOR_SETUP" "\-\-sync"
assert_contains "cursor setup.sh copies .mdc files" "$CURSOR_SETUP" "\.mdc"

# ── Section 12: GitHub Copilot copilot-instructions.md ────

echo ""
echo "=== GitHub Copilot copilot-instructions.md ==="

GH_DIR="$ADAPTERS/github-copilot/.github"
COPILOT_MD="$GH_DIR/copilot-instructions.md"

assert "copilot-instructions.md exists" "[[ -f '$COPILOT_MD' ]]"
assert_contains "has auto-generated notice" "$COPILOT_MD" "Auto-generated from shared/rules/always"
assert_contains "has Copilot Instructions header" "$COPILOT_MD" "^# Copilot Instructions"

# Verify all always-on rules are included
assert_contains "has Coding Standards" "$COPILOT_MD" "^# Coding Standards"
assert_contains "has Cross-Copilot Conventions" "$COPILOT_MD" "^# Cross-Copilot Conventions"
assert_contains "has Agent Safety Rules" "$COPILOT_MD" "^# Agent Safety Rules"

# Verify key content
assert_contains "has lint errors: 0" "$COPILOT_MD" "Lint errors: 0"
assert_contains "has read before write" "$COPILOT_MD" "Read before write"
assert_contains "has destructive commands" "$COPILOT_MD" "rm -rf"

# ── Section 13: GitHub Copilot on-demand instructions ─────

echo ""
echo "=== GitHub Copilot on-demand instructions ==="

INSTRUCTIONS_DIR="$GH_DIR/instructions"
assert "instructions dir exists" "[[ -d '$INSTRUCTIONS_DIR' ]]"

# Verify all 10 on-demand rules become instruction files
ON_DEMAND_COUNT=$(ls "$INSTRUCTIONS_DIR"/*.instructions.md 2>/dev/null | wc -l | tr -d ' ')
assert "exactly 10 instruction files ($ON_DEMAND_COUNT)" "[[ $ON_DEMAND_COUNT -eq 10 ]]"

# Verify each on-demand rule has a corresponding instruction file
for f in "$SHARED/on-demand"/*.md; do
  name="$(basename "$f" .md)"
  INSTR="$INSTRUCTIONS_DIR/$name.instructions.md"
  assert "$name.instructions.md exists" "[[ -f '$INSTR' ]]"
  assert_contains "$name: has applyTo frontmatter" "$INSTR" "^applyTo:"
  assert_contains "$name: has frontmatter delimiters" "$INSTR" "^---"
done

# Verify specific glob patterns for key rules
assert_contains "environment-setup: has env glob" "$INSTRUCTIONS_DIR/environment-setup.instructions.md" '\.env'
assert_contains "stack-constraints: has package.json glob" "$INSTRUCTIONS_DIR/stack-constraints.instructions.md" 'package.json'
assert_contains "integration-testing: has tests glob" "$INSTRUCTIONS_DIR/integration-testing.instructions.md" 'tests'

# ── Section 14: GitHub Copilot setup.sh ───────────────────

echo ""
echo "=== GitHub Copilot setup.sh ==="

GH_SETUP="$ADAPTERS/github-copilot/setup.sh"
assert "gh-copilot setup.sh exists" "[[ -f '$GH_SETUP' ]]"
assert "gh-copilot setup.sh is executable" "[[ -x '$GH_SETUP' ]]"
assert_contains "gh-copilot setup.sh has shebang" "$GH_SETUP" "^#!/bin/bash"
assert_contains "gh-copilot setup.sh supports --sync" "$GH_SETUP" "\-\-sync"
assert_contains "gh-copilot setup.sh copies copilot-instructions" "$GH_SETUP" "copilot-instructions"
assert_contains "gh-copilot setup.sh copies instructions dir" "$GH_SETUP" "instructions"

# ── Section 15: Cursor setup.sh install test ──────────────

echo ""
echo "=== Cursor setup.sh install test ==="

CURSOR_TMP=$(mktemp -d)
bash "$CURSOR_SETUP" "$CURSOR_TMP" >/dev/null 2>&1
CURSOR_INSTALL_RC=$?
assert "cursor install exits 0" "[[ $CURSOR_INSTALL_RC -eq 0 ]]"
INSTALLED_MDC=$(ls "$CURSOR_TMP/.cursor/rules"/*.mdc 2>/dev/null | wc -l | tr -d ' ')
assert "cursor installed 3 .mdc files ($INSTALLED_MDC)" "[[ $INSTALLED_MDC -eq 3 ]]"
rm -rf "$CURSOR_TMP"

# ── Section 16: GitHub Copilot setup.sh install test ──────

echo ""
echo "=== GitHub Copilot setup.sh install test ==="

GH_TMP=$(mktemp -d)
bash "$GH_SETUP" "$GH_TMP" >/dev/null 2>&1
GH_INSTALL_RC=$?
assert "gh-copilot install exits 0" "[[ $GH_INSTALL_RC -eq 0 ]]"
assert "installed copilot-instructions.md" "[[ -f '$GH_TMP/.github/copilot-instructions.md' ]]"
INSTALLED_INSTR=$(ls "$GH_TMP/.github/instructions"/*.instructions.md 2>/dev/null | wc -l | tr -d ' ')
assert "gh-copilot installed 10 instruction files ($INSTALLED_INSTR)" "[[ $INSTALLED_INSTR -eq 10 ]]"
rm -rf "$GH_TMP"

# ── Section 17: Windsurf rules.md ─────────────────────────

echo ""
echo "=== Windsurf rules.md ==="

WINDSURF_RULES="$ADAPTERS/windsurf/.windsurf/rules"
WINDSURF_MD="$WINDSURF_RULES/rules.md"

assert "windsurf rules dir exists" "[[ -d '$WINDSURF_RULES' ]]"
assert "rules.md exists" "[[ -f '$WINDSURF_MD' ]]"
assert_contains "has Windsurf Rules header" "$WINDSURF_MD" "^# Windsurf Rules"
assert_contains "has auto-generated notice" "$WINDSURF_MD" "Auto-generated from shared/rules/always"

# Verify all always-on rules are included
assert_contains "has Coding Standards" "$WINDSURF_MD" "^# Coding Standards"
assert_contains "has Cross-Copilot Conventions" "$WINDSURF_MD" "^# Cross-Copilot Conventions"
assert_contains "has Agent Safety Rules" "$WINDSURF_MD" "^# Agent Safety Rules"

# Verify key content
assert_contains "has lint errors: 0" "$WINDSURF_MD" "Lint errors: 0"
assert_contains "has read before write" "$WINDSURF_MD" "Read before write"
assert_contains "has destructive commands" "$WINDSURF_MD" "rm -rf"
assert_contains "has password storage" "$WINDSURF_MD" "Password Storage"

# ── Section 18: Windsurf setup.sh ─────────────────────────

echo ""
echo "=== Windsurf setup.sh ==="

WINDSURF_SETUP="$ADAPTERS/windsurf/setup.sh"
assert "windsurf setup.sh exists" "[[ -f '$WINDSURF_SETUP' ]]"
assert "windsurf setup.sh is executable" "[[ -x '$WINDSURF_SETUP' ]]"
assert_contains "windsurf setup.sh has shebang" "$WINDSURF_SETUP" "^#!/bin/bash"
assert_contains "windsurf setup.sh supports --sync" "$WINDSURF_SETUP" "\-\-sync"
assert_contains "windsurf setup.sh copies rules.md" "$WINDSURF_SETUP" "rules.md"

# ── Section 19: Aider CONVENTIONS.md ──────────────────────

echo ""
echo "=== Aider CONVENTIONS.md ==="

AIDER_MD="$ADAPTERS/aider/CONVENTIONS.md"

assert "CONVENTIONS.md exists" "[[ -f '$AIDER_MD' ]]"
assert_contains "has Aider Conventions header" "$AIDER_MD" "^# Aider Conventions"
assert_contains "has auto-generated notice" "$AIDER_MD" "Auto-generated from shared/rules/always"

# Verify all always-on rules are included
assert_contains "has Coding Standards" "$AIDER_MD" "^# Coding Standards"
assert_contains "has Cross-Copilot Conventions" "$AIDER_MD" "^# Cross-Copilot Conventions"
assert_contains "has Agent Safety Rules" "$AIDER_MD" "^# Agent Safety Rules"

# Verify key content
assert_contains "has lint errors: 0" "$AIDER_MD" "Lint errors: 0"
assert_contains "has read before write" "$AIDER_MD" "Read before write"
assert_contains "has destructive commands" "$AIDER_MD" "rm -rf"
assert_contains "has password storage" "$AIDER_MD" "Password Storage"

# ── Section 20: Aider setup.sh ────────────────────────────

echo ""
echo "=== Aider setup.sh ==="

AIDER_SETUP="$ADAPTERS/aider/setup.sh"
assert "aider setup.sh exists" "[[ -f '$AIDER_SETUP' ]]"
assert "aider setup.sh is executable" "[[ -x '$AIDER_SETUP' ]]"
assert_contains "aider setup.sh has shebang" "$AIDER_SETUP" "^#!/bin/bash"
assert_contains "aider setup.sh supports --sync" "$AIDER_SETUP" "\-\-sync"
assert_contains "aider setup.sh copies CONVENTIONS.md" "$AIDER_SETUP" "CONVENTIONS.md"

# ── Section 21: Windsurf setup.sh install test ────────────

echo ""
echo "=== Windsurf setup.sh install test ==="

WINDSURF_TMP=$(mktemp -d)
bash "$WINDSURF_SETUP" "$WINDSURF_TMP" >/dev/null 2>&1
WINDSURF_INSTALL_RC=$?
assert "windsurf install exits 0" "[[ $WINDSURF_INSTALL_RC -eq 0 ]]"
assert "installed .windsurf/rules/rules.md" "[[ -f '$WINDSURF_TMP/.windsurf/rules/rules.md' ]]"
rm -rf "$WINDSURF_TMP"

# ── Section 22: Aider setup.sh install test ───────────────

echo ""
echo "=== Aider setup.sh install test ==="

AIDER_TMP=$(mktemp -d)
bash "$AIDER_SETUP" "$AIDER_TMP" >/dev/null 2>&1
AIDER_INSTALL_RC=$?
assert "aider install exits 0" "[[ $AIDER_INSTALL_RC -eq 0 ]]"
assert "installed CONVENTIONS.md" "[[ -f '$AIDER_TMP/CONVENTIONS.md' ]]"
rm -rf "$AIDER_TMP"

# ── Section 23: Content parity across adapters ────────────

echo ""
echo "=== Content parity across adapters ==="

# All concatenated adapters should contain the same always-on rule content.
# Verify by checking that key phrases from each rule appear in all outputs.
for target in "$WINDSURF_MD" "$AIDER_MD" "$COPILOT_MD"; do
  name="$(basename "$target")"
  assert_contains "$name: has Quality Gates" "$target" "Quality Gates"
  assert_contains "$name: has Core Contract" "$target" "Core Contract"
  assert_contains "$name: has Input Validation" "$target" "Input Validation"
done

# ── Section 24: Idempotent generation ─────────────────────

echo ""
echo "=== Idempotent generation ==="

# Run generator twice, verify identical output across all adapters
MD5_BEFORE_AGENTS=$(md5 -q "$AGENTS_MD" 2>/dev/null || md5sum "$AGENTS_MD" | cut -d' ' -f1)
MD5_BEFORE_COPILOT=$(md5 -q "$COPILOT_MD" 2>/dev/null || md5sum "$COPILOT_MD" | cut -d' ' -f1)
MD5_BEFORE_CURSOR=$(md5 -q "$CURSOR_RULES/coding-standards.mdc" 2>/dev/null || md5sum "$CURSOR_RULES/coding-standards.mdc" | cut -d' ' -f1)
MD5_BEFORE_WINDSURF=$(md5 -q "$WINDSURF_MD" 2>/dev/null || md5sum "$WINDSURF_MD" | cut -d' ' -f1)
MD5_BEFORE_AIDER=$(md5 -q "$AIDER_MD" 2>/dev/null || md5sum "$AIDER_MD" | cut -d' ' -f1)
bash "$REPO_DIR/scripts/generate.sh" >/dev/null 2>&1
MD5_AFTER_AGENTS=$(md5 -q "$AGENTS_MD" 2>/dev/null || md5sum "$AGENTS_MD" | cut -d' ' -f1)
MD5_AFTER_COPILOT=$(md5 -q "$COPILOT_MD" 2>/dev/null || md5sum "$COPILOT_MD" | cut -d' ' -f1)
MD5_AFTER_CURSOR=$(md5 -q "$CURSOR_RULES/coding-standards.mdc" 2>/dev/null || md5sum "$CURSOR_RULES/coding-standards.mdc" | cut -d' ' -f1)
MD5_AFTER_WINDSURF=$(md5 -q "$WINDSURF_MD" 2>/dev/null || md5sum "$WINDSURF_MD" | cut -d' ' -f1)
MD5_AFTER_AIDER=$(md5 -q "$AIDER_MD" 2>/dev/null || md5sum "$AIDER_MD" | cut -d' ' -f1)
assert "Codex AGENTS.md is identical after re-generation" "[[ '$MD5_BEFORE_AGENTS' == '$MD5_AFTER_AGENTS' ]]"
assert "GH Copilot copilot-instructions.md is identical" "[[ '$MD5_BEFORE_COPILOT' == '$MD5_AFTER_COPILOT' ]]"
assert "Cursor coding-standards.mdc is identical" "[[ '$MD5_BEFORE_CURSOR' == '$MD5_AFTER_CURSOR' ]]"
assert "Windsurf rules.md is identical" "[[ '$MD5_BEFORE_WINDSURF' == '$MD5_AFTER_WINDSURF' ]]"
assert "Aider CONVENTIONS.md is identical" "[[ '$MD5_BEFORE_AIDER' == '$MD5_AFTER_AIDER' ]]"

# ── Results ───────────────────────────────────────────────

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
