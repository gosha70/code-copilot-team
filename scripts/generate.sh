#!/bin/bash
# generate.sh — Build tool-specific adapter configs from shared/ content
#
# Reads from:   shared/rules/always/*.md, shared/rules/on-demand/*.md
# Writes to:    adapters/<tool>/  (generated configs, committed to repo)
#
# Run after modifying shared/ content, then commit the generated outputs.
# CI verifies: git diff --exit-code adapters/ (no drift allowed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$SCRIPT_DIR/.."
SHARED="$REPO_DIR/shared/rules"
ADAPTERS="$REPO_DIR/adapters"

echo "=== Generating adapter configs from shared/ ==="

# ── Claude Code ──────────────────────────────────────────────
# Claude Code uses direct symlinks + file copies from shared/.
# No generation needed — setup.sh reads shared/ at install time.
echo "[claude-code] No generation needed (reads shared/ directly)"

# ── Codex ────────────────────────────────────────────────────
# Generate AGENTS.md by concatenating shared/rules/always/* with on-demand TOC
echo "[codex] Generating AGENTS.md..."
CODEX_DIR="$ADAPTERS/codex"
AGENTS_MD="$CODEX_DIR/AGENTS.md"
mkdir -p "$CODEX_DIR"

{
  echo "# Codex Agent Instructions"
  echo ""
  echo "Auto-generated from shared/rules/always/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""
  echo "---"
  echo ""

  # Concatenate all always-on rules
  for f in "$SHARED/always"/*.md; do
    cat "$f"
    echo ""
    echo "---"
    echo ""
  done

  # Append on-demand rules reference
  echo "## On-Demand Rules Reference"
  echo ""
  echo "The following rules are loaded by skills when relevant. Invoke the"
  echo "corresponding skill to apply them."
  echo ""
  echo "| Rule | Used By |"
  echo "|------|---------|"
  for f in "$SHARED/on-demand"/*.md; do
    name="$(basename "$f" .md)"
    # Map rules to skills
    case "$name" in
      ralph-loop|environment-setup|stack-constraints|phase-workflow)
        skill="build" ;;
      agent-team-protocol|team-lead-efficiency)
        skill="build (optional team mode)" ;;
      clarification-protocol)
        skill="plan" ;;
      integration-testing)
        skill="review" ;;
      spec-workflow)
        skill="plan, build" ;;
      token-efficiency)
        skill="research" ;;
      gcc-protocol)
        skill="all (optional)" ;;
      *)
        skill="—" ;;
    esac
    echo "| \`$name\` | $skill |"
  done
  echo ""
} > "$AGENTS_MD"

# Verify size limit (32 KiB = 32768 bytes)
SIZE=$(wc -c < "$AGENTS_MD" | tr -d ' ')
if [[ "$SIZE" -gt 32768 ]]; then
  echo "[codex] WARNING: AGENTS.md is $SIZE bytes (limit: 32768)"
  exit 1
fi
echo "[codex] AGENTS.md generated ($SIZE bytes)"

# ── Cursor ───────────────────────────────────────────────────
# Generate .mdc files with frontmatter from shared/rules/always/*
echo "[cursor] Generating .mdc rules..."
CURSOR_RULES="$ADAPTERS/cursor/.cursor/rules"
mkdir -p "$CURSOR_RULES"

for f in "$SHARED/always"/*.md; do
  name="$(basename "$f" .md)"
  # Extract first heading as description (strip leading #)
  desc="$(head -1 "$f" | sed 's/^#* *//')"
  {
    echo "---"
    echo "description: \"$desc\""
    echo "alwaysApply: true"
    echo "---"
    echo ""
    cat "$f"
  } > "$CURSOR_RULES/$name.mdc"
done

CURSOR_COUNT=$(ls "$CURSOR_RULES"/*.mdc 2>/dev/null | wc -l | tr -d ' ')
echo "[cursor] Generated $CURSOR_COUNT .mdc files"

# ── GitHub Copilot ───────────────────────────────────────────
# Generate copilot-instructions.md (always-on) + instructions/*.instructions.md (on-demand)
echo "[github-copilot] Generating instructions..."
GH_DIR="$ADAPTERS/github-copilot/.github"
mkdir -p "$GH_DIR/instructions"

# Always-on: concatenate into copilot-instructions.md
{
  echo "# Copilot Instructions"
  echo ""
  echo "Auto-generated from shared/rules/always/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""

  for f in "$SHARED/always"/*.md; do
    cat "$f"
    echo ""
    echo "---"
    echo ""
  done
} > "$GH_DIR/copilot-instructions.md"

echo "[github-copilot] Generated copilot-instructions.md"

# On-demand: each rule becomes an .instructions.md with applyTo frontmatter
for f in "$SHARED/on-demand"/*.md; do
  name="$(basename "$f" .md)"
  # Map rules to reasonable glob patterns
  case "$name" in
    environment-setup)     glob="**/.env*,**/docker-compose*" ;;
    stack-constraints)     glob="**/package.json,**/pyproject.toml,**/go.mod,**/Cargo.toml,**/pom.xml" ;;
    integration-testing)   glob="**/tests/**,**/test/**,**/*test*,**/*spec*" ;;
    phase-workflow)        glob="**" ;;
    ralph-loop)            glob="**" ;;
    spec-workflow)            glob="**" ;;
    gcc-protocol)          glob="**" ;;
    clarification-protocol) glob="**" ;;
    agent-team-protocol)   glob="**" ;;
    team-lead-efficiency)  glob="**" ;;
    token-efficiency)      glob="**" ;;
    *)                     glob="**" ;;
  esac
  {
    echo "---"
    echo "applyTo: \"$glob\""
    echo "---"
    echo ""
    cat "$f"
  } > "$GH_DIR/instructions/$name.instructions.md"
done

ON_DEMAND_COUNT=$(ls "$GH_DIR/instructions"/*.instructions.md 2>/dev/null | wc -l | tr -d ' ')
echo "[github-copilot] Generated $ON_DEMAND_COUNT on-demand instruction files"

# ── Windsurf ─────────────────────────────────────────────────
# Concatenate shared/rules/always/* into .windsurf/rules/rules.md
echo "[windsurf] Generating rules.md..."
WINDSURF_RULES="$ADAPTERS/windsurf/.windsurf/rules"
mkdir -p "$WINDSURF_RULES"

{
  echo "# Windsurf Rules"
  echo ""
  echo "Auto-generated from shared/rules/always/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""

  for f in "$SHARED/always"/*.md; do
    cat "$f"
    echo ""
    echo "---"
    echo ""
  done
} > "$WINDSURF_RULES/rules.md"

echo "[windsurf] Generated rules.md"

# ── Aider ────────────────────────────────────────────────────
# Concatenate shared/rules/always/* into CONVENTIONS.md
echo "[aider] Generating CONVENTIONS.md..."
AIDER_DIR="$ADAPTERS/aider"
mkdir -p "$AIDER_DIR"

{
  echo "# Aider Conventions"
  echo ""
  echo "Auto-generated from shared/rules/always/. Do not edit directly."
  echo "Regenerate with: ./scripts/generate.sh"
  echo ""

  for f in "$SHARED/always"/*.md; do
    cat "$f"
    echo ""
    echo "---"
    echo ""
  done
} > "$AIDER_DIR/CONVENTIONS.md"

echo "[aider] Generated CONVENTIONS.md"

echo "=== Done ==="
