#!/bin/bash
# setup.sh — Unified entry point for installing AI copilot configurations
#
# Usage:
#   ./scripts/setup.sh                     # auto-detect installed tools
#   ./scripts/setup.sh --claude-code       # install Claude Code adapter
#   ./scripts/setup.sh --codex             # install Codex adapter
#   ./scripts/setup.sh --cursor <dir>      # install Cursor rules into project
#   ./scripts/setup.sh --github-copilot <dir>  # install GH Copilot instructions
#   ./scripts/setup.sh --windsurf <dir>    # install Windsurf rules into project
#   ./scripts/setup.sh --aider <dir>       # install Aider conventions into project
#   ./scripts/setup.sh --all               # install all adapters (project-level need <dir>)
#   ./scripts/setup.sh --sync              # regenerate + re-install active tools
#
# Claude Code and Codex install to global config dirs (~/.claude/, ~/.codex/).
# Cursor, GitHub Copilot, Windsurf, and Aider install into a target project directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
REPO_DIR="$SCRIPT_DIR/.."
ADAPTERS="$REPO_DIR/adapters"

# ── Parse flags ────────────────────────────────────────────
TOOLS=()
SYNC=false
PROJECT_DIR=""
SHOW_HELP=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude-code)      TOOLS+=("claude-code"); shift ;;
    --codex)            TOOLS+=("codex"); shift ;;
    --cursor)           TOOLS+=("cursor"); shift ;;
    --github-copilot)   TOOLS+=("github-copilot"); shift ;;
    --windsurf)         TOOLS+=("windsurf"); shift ;;
    --aider)            TOOLS+=("aider"); shift ;;
    --all)              TOOLS=("claude-code" "codex" "cursor" "github-copilot" "windsurf" "aider"); shift ;;
    --sync)             SYNC=true; shift ;;
    --help|-h)          SHOW_HELP=true; shift ;;
    *)
      if [[ -z "$PROJECT_DIR" ]]; then
        PROJECT_DIR="$1"
      else
        echo "[ERROR] Unknown argument: $1"
        exit 1
      fi
      shift
      ;;
  esac
done

if $SHOW_HELP; then
  echo "Usage: $0 [--tool ...] [--all] [--sync] [project-dir]"
  echo ""
  echo "Tools (global install — no project dir needed):"
  echo "  --claude-code     Install Claude Code config to ~/.claude/"
  echo "  --codex           Install Codex config to ~/.codex/"
  echo ""
  echo "Tools (project install — requires project dir):"
  echo "  --cursor          Install Cursor .mdc rules"
  echo "  --github-copilot  Install GitHub Copilot instructions"
  echo "  --windsurf        Install Windsurf rules"
  echo "  --aider           Install Aider conventions"
  echo ""
  echo "Flags:"
  echo "  --all             Install all adapters"
  echo "  --sync            Regenerate configs before installing"
  echo "  --help            Show this help"
  echo ""
  echo "Examples:"
  echo "  $0 --claude-code              # Install Claude Code globally"
  echo "  $0 --cursor ~/my-project      # Install Cursor rules into project"
  echo "  $0 --all ~/my-project         # Install everything"
  echo "  $0 --sync --claude-code       # Regenerate then install Claude Code"
  exit 0
fi

# ── Auto-detect if no tools specified ──────────────────────
if [[ ${#TOOLS[@]} -eq 0 ]]; then
  echo "=== Auto-detecting installed tools ==="
  if command -v claude >/dev/null 2>&1 || [[ -d "$HOME/.claude" ]]; then
    TOOLS+=("claude-code")
    echo "  Detected: Claude Code"
  fi
  if command -v codex >/dev/null 2>&1 || [[ -d "$HOME/.codex" ]]; then
    TOOLS+=("codex")
    echo "  Detected: Codex"
  fi
  if [[ ${#TOOLS[@]} -eq 0 ]]; then
    echo "  No tools detected. Use --help for options."
    exit 0
  fi
  echo ""
fi

# ── Regenerate if --sync ──────────────────────────────────
if $SYNC; then
  echo "=== Regenerating adapter configs ==="
  bash "$REPO_DIR/scripts/generate.sh"
  echo ""
fi

# ── Project dir validation for project-level tools ─────────
PROJECT_TOOLS=("cursor" "github-copilot" "windsurf" "aider")
needs_project=false
for tool in "${TOOLS[@]}"; do
  for pt in "${PROJECT_TOOLS[@]}"; do
    if [[ "$tool" == "$pt" ]]; then
      needs_project=true
      break 2
    fi
  done
done

if $needs_project && [[ -z "$PROJECT_DIR" ]]; then
  echo "[ERROR] Project-level tools (cursor, github-copilot, windsurf, aider)"
  echo "        require a target project directory."
  echo ""
  echo "Usage: $0 --cursor <project-dir>"
  exit 1
fi

# ── Install each tool ─────────────────────────────────────
INSTALLED=0
FAILED=0

for tool in "${TOOLS[@]}"; do
  echo "=== Installing: $tool ==="
  case "$tool" in
    claude-code)
      bash "$ADAPTERS/claude-code/setup.sh" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      ;;
    codex)
      bash "$ADAPTERS/codex/setup.sh" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      ;;
    cursor)
      bash "$ADAPTERS/cursor/setup.sh" "$PROJECT_DIR" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      ;;
    github-copilot)
      bash "$ADAPTERS/github-copilot/setup.sh" "$PROJECT_DIR" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      ;;
    windsurf)
      bash "$ADAPTERS/windsurf/setup.sh" "$PROJECT_DIR" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      ;;
    aider)
      bash "$ADAPTERS/aider/setup.sh" "$PROJECT_DIR" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      ;;
    *)
      echo "[WARN] Unknown tool: $tool"
      FAILED=$((FAILED + 1))
      ;;
  esac
  echo ""
done

# ── Summary ────────────────────────────────────────────────
echo "========================================="
echo "  Setup complete: $INSTALLED installed, $FAILED failed"
echo "========================================="

if [[ $FAILED -gt 0 ]]; then
  exit 1
fi
