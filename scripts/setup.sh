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
#   ./scripts/setup.sh --claude-code --memkernel /path/to/memkernel
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
MEMKERNEL_ARGS=()
# #212: --playwright is a claude-code adapter flag. The root parser used to
# fall through to `*)`, which assigns an unknown first argument to
# PROJECT_DIR — so the flag became a phantom project dir and was SILENTLY
# ignored while two docs told users it installs Playwright.
PLAYWRIGHT_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude-code)      TOOLS+=("claude-code"); shift ;;
    --codex)            TOOLS+=("codex"); shift ;;
    --pi)               TOOLS+=("pi"); shift ;;
    --cursor)           TOOLS+=("cursor"); shift ;;
    --github-copilot)   TOOLS+=("github-copilot"); shift ;;
    --windsurf)         TOOLS+=("windsurf"); shift ;;
    --aider)            TOOLS+=("aider"); shift ;;
    --all)              TOOLS=("claude-code" "codex" "pi" "cursor" "github-copilot" "windsurf" "aider"); shift ;;
    --sync)             SYNC=true; shift ;;
    --playwright)       PLAYWRIGHT_ARGS+=("--playwright"); shift ;;
    --memkernel)
      MEMKERNEL_ARGS+=("--memkernel")
      if [[ -n "${2:-}" && "${2:0:2}" != "--" ]]; then
        MEMKERNEL_ARGS+=("$2")
        shift 2
      else
        shift
      fi
      ;;
    --help|-h)          SHOW_HELP=true; shift ;;
    *)
      # #212: the class defect behind the silent --playwright. Anything
      # starting with `-` is a flag, never a project directory: swallowing it
      # as PROJECT_DIR meant an unknown or misspelled flag ran a DIFFERENT
      # installation than the user asked for, without a word. Fail loudly.
      if [[ "$1" == -* ]]; then
        echo "[ERROR] Unknown option: $1"
        echo "        Run '$0 --help' for the supported flags."
        echo "        Adapter-specific flags must go to the adapter, e.g."
        echo "        bash adapters/claude-code/setup.sh $1"
        exit 1
      fi
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
  echo "  --playwright      Also install the Playwright MCP server (Claude Code only)"
  echo "  --codex           Install Codex config to ~/.codex/"
  echo "  --pi              Install Pi adapter (pi-code + runtime) to ~/.code-copilot-team/pi/"
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
  echo "  --memkernel [dir] Install or enable MemKernel support for Claude Code"
  echo "  --help            Show this help"
  echo ""
  echo "Examples:"
  echo "  $0 --claude-code              # Install Claude Code globally"
  echo "  $0 --claude-code --memkernel ~/src/memkernel"
  echo "  $0 --cursor ~/my-project      # Install Cursor rules into project"
  echo "  $0 --all ~/my-project         # Install everything"
  echo "  $0 --sync --claude-code       # Regenerate then install Claude Code"
  exit 0
fi

# #212 (review P2): the claude-code adapter rejects --playwright combined
# with --sync or --memkernel. The wrapper used to forward both happily, so
# `setup.sh --claude-code --sync --playwright` regenerated everything and
# THEN failed in the adapter. Reject it here, before any work, with the
# adapter's own wording.
if [[ ${#PLAYWRIGHT_ARGS[@]} -gt 0 ]]; then
  if $SYNC || [[ ${#MEMKERNEL_ARGS[@]} -gt 0 ]]; then
    echo "[ERROR] --playwright cannot be combined with --sync or --memkernel"
    echo "        Run them as separate invocations."
    exit 1
  fi
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
  if command -v pi >/dev/null 2>&1 || [[ -d "$HOME/.pi" ]]; then
    TOOLS+=("pi")
    echo "  Detected: Pi"
  fi
  if [[ ${#TOOLS[@]} -eq 0 ]]; then
    if [[ ${#PLAYWRIGHT_ARGS[@]} -gt 0 ]]; then
      # #212 (review P1): `setup.sh --playwright` is the command the docs
      # recommend. Exiting 0 here left the issue's own acceptance command
      # silently doing nothing — the exact defect, one branch further along.
      echo "[ERROR] --playwright needs the Claude Code adapter, and no tools were detected."
      echo "        Run: bash $0 --claude-code --playwright"
      echo "        or:  bash adapters/claude-code/setup.sh --playwright"
      exit 1
    fi
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
# #212: --playwright only exists on the claude-code adapter. If the resolved
# tool set cannot carry it, say so — forwarding it nowhere would be the same
# silent no-op this issue is about, just one layer deeper.
if [[ ${#PLAYWRIGHT_ARGS[@]} -gt 0 ]]; then
  _pw_ok=0
  for tool in "${TOOLS[@]}"; do
    [[ "$tool" == "claude-code" ]] && _pw_ok=1
  done
  if [[ $_pw_ok -eq 0 ]]; then
    echo "[ERROR] --playwright applies to the Claude Code adapter, which is not"
    echo "        in this run's tool set (${TOOLS[*]})."
    echo "        Add --claude-code, or run: bash adapters/claude-code/setup.sh --playwright"
    exit 1
  fi
fi

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
      if $SYNC; then
        bash "$ADAPTERS/claude-code/setup.sh" --sync "${MEMKERNEL_ARGS[@]+"${MEMKERNEL_ARGS[@]}"}" "${PLAYWRIGHT_ARGS[@]+"${PLAYWRIGHT_ARGS[@]}"}" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      else
        bash "$ADAPTERS/claude-code/setup.sh" "${MEMKERNEL_ARGS[@]+"${MEMKERNEL_ARGS[@]}"}" "${PLAYWRIGHT_ARGS[@]+"${PLAYWRIGHT_ARGS[@]}"}" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      fi
      ;;
    codex)
      if $SYNC; then
        bash "$ADAPTERS/codex/setup.sh" --sync && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      else
        bash "$ADAPTERS/codex/setup.sh" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      fi
      ;;
    pi)
      if $SYNC; then
        bash "$ADAPTERS/pi/setup.sh" --sync && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      else
        bash "$ADAPTERS/pi/setup.sh" && INSTALLED=$((INSTALLED + 1)) || FAILED=$((FAILED + 1))
      fi
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
