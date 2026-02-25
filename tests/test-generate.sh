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

# Verify Claude-only rules are marked
assert_contains "agent-team-protocol marked Claude-only" "$AGENTS_MD" "agent-team-protocol.*Claude-only"
assert_contains "team-lead-efficiency marked Claude-only" "$AGENTS_MD" "team-lead-efficiency.*Claude-only"

# Verify skill mappings
assert_contains "ralph-loop mapped to build" "$AGENTS_MD" "ralph-loop.*build"
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
assert_contains "verify-app: no file modification" "$VERIFY" "[Nn]ever modify"

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

# ── Section 10: Idempotent generation ─────────────────────

echo ""
echo "=== Idempotent generation ==="

# Run generator twice, verify identical output
MD5_BEFORE=$(md5 -q "$AGENTS_MD" 2>/dev/null || md5sum "$AGENTS_MD" | cut -d' ' -f1)
bash "$REPO_DIR/scripts/generate.sh" >/dev/null 2>&1
MD5_AFTER=$(md5 -q "$AGENTS_MD" 2>/dev/null || md5sum "$AGENTS_MD" | cut -d' ' -f1)
assert "AGENTS.md is identical after re-generation" "[[ '$MD5_BEFORE' == '$MD5_AFTER' ]]"

# ── Results ───────────────────────────────────────────────

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
