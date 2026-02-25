#!/bin/bash
# claude-setup.sh - One-time setup for Claude Code project templates
#
# Creates:
#   ~/.claude/CLAUDE.md                    Global configuration
#   ~/.claude/rules/                       Global rules (auto-loaded, 3 files)
#   ~/.claude/rules-library/               Rules library (on-demand, 10 files)
#   ~/.claude/agents/                      Global agents (5 utility + 4 phase)
#   ~/.claude/hooks/                       Global hook scripts (verify, notify)
#   ~/.claude/settings.json                Global settings with hooks wired
#   ~/.claude/templates/<type>/CLAUDE.md   Project templates (with Agent Team configs)
#   ~/.claude/templates/<type>/commands/   Custom slash commands per type
#   Installs claude-code launcher to ~/.local/bin/
#
# Run once, then use 'claude-code init <type> [path]' to scaffold projects.
# Run with --sync to re-copy rules, rules-library, and agents from repo.
# Run with --gcc to install optional GCC memory support (Aline MCP).

set -e

CLAUDE_DIR="$HOME/.claude"
TEMPLATES_DIR="$CLAUDE_DIR/templates"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
SHARED_DIR="$SCRIPT_DIR/../shared"
LAUNCHER_SOURCE="$SCRIPT_DIR/claude-code"
LAUNCHER_TARGET="$HOME/.local/bin/claude-code"

# ══════════════════════════════════════════════════════════════
# --sync: re-copy rules, rules-library, and agents from repo
# ══════════════════════════════════════════════════════════════

if [[ "${1:-}" == "--sync" ]]; then
    echo "Syncing rules, rules-library, and agents from repo..."

    # Global rules (3 files) — from shared/rules/always/
    RULES_SOURCE="$SHARED_DIR/rules/always"
    RULES_TARGET="$CLAUDE_DIR/rules"
    mkdir -p "$RULES_TARGET"
    if [[ -d "$RULES_SOURCE" ]]; then
        cp "$RULES_SOURCE"/*.md "$RULES_TARGET/" 2>/dev/null || true
        echo "[done] Synced rules to $RULES_TARGET"
    fi

    # Rules library (10 files) — from shared/rules/on-demand/
    LIBRARY_SOURCE="$SHARED_DIR/rules/on-demand"
    LIBRARY_TARGET="$CLAUDE_DIR/rules-library"
    mkdir -p "$LIBRARY_TARGET"
    if [[ -d "$LIBRARY_SOURCE" ]]; then
        cp "$LIBRARY_SOURCE"/*.md "$LIBRARY_TARGET/" 2>/dev/null || true
        echo "[done] Synced rules-library to $LIBRARY_TARGET"
    fi

    # Agents (9 files)
    AGENTS_SOURCE="$SCRIPT_DIR/.claude/agents"
    AGENTS_TARGET="$CLAUDE_DIR/agents"
    mkdir -p "$AGENTS_TARGET"
    if [[ -d "$AGENTS_SOURCE" ]]; then
        cp "$AGENTS_SOURCE"/*.md "$AGENTS_TARGET/" 2>/dev/null || true
        echo "[done] Synced agents to $AGENTS_TARGET"
    fi

    echo "Sync complete."
    exit 0
fi

# ══════════════════════════════════════════════════════════════
# --gcc: install Aline MCP + GCC protocol rule (optional)
# ══════════════════════════════════════════════════════════════

if [[ "${1:-}" == "--gcc" ]]; then
    echo "Installing GCC (Git Context Controller) support..."

    # Install Aline MCP server
    if command -v claude &>/dev/null; then
        claude mcp add --scope user --transport stdio aline -- npx -y aline-ai@latest
        echo "[done] Aline MCP server added (scope: user)"
    else
        echo "[WARN] 'claude' CLI not found. Install Aline MCP manually:"
        echo "       claude mcp add --scope user --transport stdio aline -- npx -y aline-ai@latest"
    fi

    # Copy gcc-protocol rule to rules-library
    LIBRARY_TARGET="$CLAUDE_DIR/rules-library"
    GCC_RULE_SOURCE="$SCRIPT_DIR/.claude/rules-library/gcc-protocol.md"
    mkdir -p "$LIBRARY_TARGET"
    if [[ -f "$GCC_RULE_SOURCE" ]]; then
        cp "$GCC_RULE_SOURCE" "$LIBRARY_TARGET/"
        echo "[done] Copied gcc-protocol.md to $LIBRARY_TARGET"
    else
        echo "[WARN] gcc-protocol.md not found at $GCC_RULE_SOURCE"
    fi

    echo ""
    echo "GCC setup complete. Phase agents will use GCC memory when Aline MCP is available."
    echo "To verify: start a Claude session and check that the 'aline' MCP server is listed."
    exit 0
fi

echo "============================================"
echo "  Claude Code Project Template Setup v2"
echo "  (with Agent Team configurations)"
echo "============================================"
echo ""

# ══════════════════════════════════════════════════════════════
# 0. DEPENDENCY CHECK: jq
# ══════════════════════════════════════════════════════════════

if ! command -v jq &>/dev/null; then
    echo "[WARN] jq is not installed."
    echo "       jq is required for all hook scripts (JSON parsing)."
    echo "       Without it, hooks will silently skip — no type checking,"
    echo "       no auto-formatting, no file protection, no test verification."
    echo ""

    INSTALL_CMD=""
    case "$(uname -s)" in
        Darwin)
            if command -v brew &>/dev/null; then
                INSTALL_CMD="brew install jq"
            else
                echo "       Install manually: https://jqlang.github.io/jq/download/"
                echo "       (or install Homebrew first: https://brew.sh)"
            fi
            ;;
        Linux)
            if command -v apt-get &>/dev/null; then
                INSTALL_CMD="sudo apt-get install -y jq"
            elif command -v dnf &>/dev/null; then
                INSTALL_CMD="sudo dnf install -y jq"
            elif command -v pacman &>/dev/null; then
                INSTALL_CMD="sudo pacman -S --noconfirm jq"
            elif command -v apk &>/dev/null; then
                INSTALL_CMD="apk add jq"
            else
                echo "       Install manually: https://jqlang.github.io/jq/download/"
            fi
            ;;
        *)
            echo "       Install manually: https://jqlang.github.io/jq/download/"
            ;;
    esac

    if [[ -n "$INSTALL_CMD" ]]; then
        echo -n "       Install jq now with '$INSTALL_CMD'? [Y/n] "
        read -r REPLY
        if [[ -z "$REPLY" || "$REPLY" =~ ^[Yy]$ ]]; then
            echo ""
            if $INSTALL_CMD; then
                echo "[done] jq installed successfully"
            else
                echo "[FAIL] jq installation failed. Install it manually and re-run setup."
                echo "       Setup will continue, but hooks will not work until jq is installed."
            fi
        else
            echo ""
            echo "[skip] Skipping jq installation."
            echo "       IMPORTANT: All hooks will silently skip until jq is installed."
            echo "       To install later: $INSTALL_CMD"
        fi
    fi
    echo ""
else
    echo "[ok]   jq found: $(jq --version)"
fi

# ══════════════════════════════════════════════════════════════
# 1. GLOBAL CLAUDE.md
# ══════════════════════════════════════════════════════════════

mkdir -p "$CLAUDE_DIR"

if [[ -f "$CLAUDE_DIR/CLAUDE.md" ]]; then
    echo "[skip] ~/.claude/CLAUDE.md already exists (not overwriting)"
else
cat > "$CLAUDE_DIR/CLAUDE.md" << 'GLOBALEOF'
# Global Claude Configuration

## Identity
- Developer: Gosha (i.am.goga@gmail.com)

## General Principles
- Write clean, well-documented, production-quality code
- Follow SOLID principles; prefer composition over inheritance
- Handle errors explicitly; never swallow exceptions
- No magic numbers; use named constants
- Keep functions focused (< 30 lines preferred)
- Log meaningful messages at appropriate levels (DEBUG/INFO/WARN/ERROR)

## Git & Commits
- Use conventional commits: feat:, fix:, refactor:, docs:, test:, chore:
- Write descriptive commit messages explaining WHY, not just WHAT
- Keep commits atomic; one logical change per commit

## Code Review Mindset
- Flag potential security or performance concerns proactively
- Suggest tests for any new logic
- When multiple approaches exist, explain trade-offs before implementing
- When uncertain about requirements, ask before building

## Communication Style
- Be direct and concise
- Lead with the answer, then explain
- Use code examples over prose when possible

## Context Efficiency
- Keep this file and project CLAUDE.md lean; reference docs/* for deep detail
- When working on code, read specific files rather than scanning entire directories
- After completing a logical unit of work, suggest running /compact
- When switching tasks within a session, suggest running /clear first
- Prefer targeted file reads over broad codebase scans

## Model & Effort Strategy
Three phases, three configurations:
- PLANNING (architecture, API design, data modeling, security): use highest-capability
  model + high effort. Do NOT delegate to sub-agents. Plan holistically as Team Lead.
- BUILDING (implementation from an approved plan): use fast model + medium effort.
  Delegate to specialist sub-agents. Switch to highest-capability model only for
  complex/security-sensitive parts (auth, concurrency, state machines).
- REVIEW (verifying output, integration testing): use highest-capability model +
  high effort. Review holistically as Team Lead, do not delegate.
Quick tasks (rename, format, boilerplate): use lightest model + low effort.

## Agent Team Protocol (Global)
When this project defines an Agent Team section, follow these rules:
- Default role: Team Lead. You coordinate, plan, and review.
- PLANNING PHASE: Team Lead works alone. Do NOT delegate planning to sub-agents.
  Planning requires seeing the full architecture; sub-agents only see fragments.
- BUILDING PHASE: Team Lead decomposes the plan into tasks and delegates to
  specialist sub-agents via the Task tool.
- REVIEW PHASE: Team Lead reviews all output holistically. Do NOT delegate review.
- When spawning a sub-agent, include: (1) its role prompt from the team section,
  (2) relevant project context, (3) the specific task.
- Review ALL sub-agent output before presenting to the user.
- Never let two sub-agents modify the same file concurrently.
- If a sub-agent's output violates project conventions, reject and re-delegate.
GLOBALEOF
echo "[done] Created ~/.claude/CLAUDE.md"
fi

# ══════════════════════════════════════════════════════════════
# 2. TEMPLATE: ml-rag
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-rag/commands"
cp "$SHARED_DIR/templates/ml-rag/PROJECT.md" "$TEMPLATES_DIR/ml-rag/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/ml-rag/commands" ]]; then
    cp "$SHARED_DIR/templates/ml-rag/commands/"*.md "$TEMPLATES_DIR/ml-rag/commands/" 2>/dev/null || true
fi
echo "[done] Created template: ml-rag"

# ══════════════════════════════════════════════════════════════
# 3. TEMPLATE: ml-app
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-app/commands"
cp "$SHARED_DIR/templates/ml-app/PROJECT.md" "$TEMPLATES_DIR/ml-app/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/ml-app/commands" ]]; then
    cp "$SHARED_DIR/templates/ml-app/commands/"*.md "$TEMPLATES_DIR/ml-app/commands/" 2>/dev/null || true
fi
echo "[done] Created template: ml-app"

# ══════════════════════════════════════════════════════════════
# 4. TEMPLATE: ml-langchain
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-langchain/commands"
cp "$SHARED_DIR/templates/ml-langchain/PROJECT.md" "$TEMPLATES_DIR/ml-langchain/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/ml-langchain/commands" ]]; then
    cp "$SHARED_DIR/templates/ml-langchain/commands/"*.md "$TEMPLATES_DIR/ml-langchain/commands/" 2>/dev/null || true
fi
echo "[done] Created template: ml-langchain"

# ══════════════════════════════════════════════════════════════
# 5. TEMPLATE: ml-n8n
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-n8n/commands"
cp "$SHARED_DIR/templates/ml-n8n/PROJECT.md" "$TEMPLATES_DIR/ml-n8n/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/ml-n8n/commands" ]]; then
    cp "$SHARED_DIR/templates/ml-n8n/commands/"*.md "$TEMPLATES_DIR/ml-n8n/commands/" 2>/dev/null || true
fi
echo "[done] Created template: ml-n8n"

# ══════════════════════════════════════════════════════════════
# 6. TEMPLATE: java-enterprise
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/java-enterprise/commands"
cp "$SHARED_DIR/templates/java-enterprise/PROJECT.md" "$TEMPLATES_DIR/java-enterprise/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/java-enterprise/commands" ]]; then
    cp "$SHARED_DIR/templates/java-enterprise/commands/"*.md "$TEMPLATES_DIR/java-enterprise/commands/" 2>/dev/null || true
fi
echo "[done] Created template: java-enterprise"

# ══════════════════════════════════════════════════════════════
# 7. TEMPLATE: web-static
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/web-static/commands"
cp "$SHARED_DIR/templates/web-static/PROJECT.md" "$TEMPLATES_DIR/web-static/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/web-static/commands" ]]; then
    cp "$SHARED_DIR/templates/web-static/commands/"*.md "$TEMPLATES_DIR/web-static/commands/" 2>/dev/null || true
fi
echo "[done] Created template: web-static"

# ══════════════════════════════════════════════════════════════
# 8. TEMPLATE: web-dynamic
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/web-dynamic/commands"
cp "$SHARED_DIR/templates/web-dynamic/PROJECT.md" "$TEMPLATES_DIR/web-dynamic/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/web-dynamic/commands" ]]; then
    cp "$SHARED_DIR/templates/web-dynamic/commands/"*.md "$TEMPLATES_DIR/web-dynamic/commands/" 2>/dev/null || true
fi
echo "[done] Created template: web-dynamic"

# ══════════════════════════════════════════════════════════════
# 9. INSTALL LAUNCHER SCRIPT
# ══════════════════════════════════════════════════════════════

mkdir -p "$HOME/.local/bin"

if [[ -f "$LAUNCHER_SOURCE" ]]; then
    # Resolve both paths to avoid "identical file" error when re-running
    RESOLVED_SOURCE=$(cd "$(dirname "$LAUNCHER_SOURCE")" && pwd)/$(basename "$LAUNCHER_SOURCE")
    RESOLVED_TARGET=$(cd "$(dirname "$LAUNCHER_TARGET")" 2>/dev/null && pwd)/$(basename "$LAUNCHER_TARGET") 2>/dev/null || RESOLVED_TARGET=""
    if [[ "$RESOLVED_SOURCE" == "$RESOLVED_TARGET" ]]; then
        echo ""
        echo "[skip] claude-code launcher already up to date at $LAUNCHER_TARGET"
    else
        cp "$LAUNCHER_SOURCE" "$LAUNCHER_TARGET"
        chmod +x "$LAUNCHER_TARGET"
        echo ""
        echo "[done] Installed claude-code launcher to $LAUNCHER_TARGET"
    fi
else
    echo ""
    echo "[skip] claude-code launcher not found at $LAUNCHER_SOURCE"
    echo "       Copy it manually to $LAUNCHER_TARGET"
fi

# ══════════════════════════════════════════════════════════════
# 10. GLOBAL HOOKS
# ══════════════════════════════════════════════════════════════

HOOKS_SOURCE="$SCRIPT_DIR/.claude/hooks"
HOOKS_TARGET="$CLAUDE_DIR/hooks"

mkdir -p "$HOOKS_TARGET"

if [[ -d "$HOOKS_SOURCE" ]]; then
    cp "$HOOKS_SOURCE/notify.sh" "$HOOKS_TARGET/notify.sh"
    cp "$HOOKS_SOURCE/verify-after-edit.sh" "$HOOKS_TARGET/verify-after-edit.sh"
    cp "$HOOKS_SOURCE/verify-on-stop.sh" "$HOOKS_TARGET/verify-on-stop.sh"
    cp "$HOOKS_SOURCE/auto-format.sh" "$HOOKS_TARGET/auto-format.sh"
    cp "$HOOKS_SOURCE/protect-files.sh" "$HOOKS_TARGET/protect-files.sh"
    cp "$HOOKS_SOURCE/reinject-context.sh" "$HOOKS_TARGET/reinject-context.sh"
    chmod +x "$HOOKS_TARGET"/*.sh
    echo "[done] Installed hooks to $HOOKS_TARGET"
else
    echo "[skip] Hook scripts not found at $HOOKS_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 10b. GLOBAL AGENTS
# ══════════════════════════════════════════════════════════════

AGENTS_SOURCE="$SCRIPT_DIR/.claude/agents"
AGENTS_TARGET="$CLAUDE_DIR/agents"

mkdir -p "$AGENTS_TARGET"

if [[ -d "$AGENTS_SOURCE" ]]; then
    cp "$AGENTS_SOURCE"/*.md "$AGENTS_TARGET/" 2>/dev/null || true
    echo "[done] Installed agents to $AGENTS_TARGET"
else
    echo "[skip] Agent definitions not found at $AGENTS_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 10c. GLOBAL RULES (auto-loaded, 3 files) — from shared/rules/always/
# ══════════════════════════════════════════════════════════════

RULES_SOURCE="$SHARED_DIR/rules/always"
RULES_TARGET="$CLAUDE_DIR/rules"

mkdir -p "$RULES_TARGET"

if [[ -d "$RULES_SOURCE" ]]; then
    cp "$RULES_SOURCE"/*.md "$RULES_TARGET/" 2>/dev/null || true
    echo "[done] Installed global rules to $RULES_TARGET"
else
    echo "[skip] Rules not found at $RULES_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 10d. RULES LIBRARY (on-demand, 10 files) — from shared/rules/on-demand/
# ══════════════════════════════════════════════════════════════

LIBRARY_SOURCE="$SHARED_DIR/rules/on-demand"
LIBRARY_TARGET="$CLAUDE_DIR/rules-library"

mkdir -p "$LIBRARY_TARGET"

if [[ -d "$LIBRARY_SOURCE" ]]; then
    cp "$LIBRARY_SOURCE"/*.md "$LIBRARY_TARGET/" 2>/dev/null || true
    echo "[done] Installed rules-library to $LIBRARY_TARGET"
else
    echo "[skip] Rules library not found at $LIBRARY_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 11. GLOBAL SETTINGS (hooks wiring)
# ══════════════════════════════════════════════════════════════

SETTINGS_FILE="$CLAUDE_DIR/settings.json"
HOOKS_CONFIG='{
  "env": {
    "HOOK_EDIT_BLOCK": "true",
    "HOOK_STOP_BLOCK": "false"
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/protect-files.sh",
            "timeout": 5000
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/verify-on-stop.sh",
            "timeout": 180000
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/verify-after-edit.sh",
            "timeout": 30000
          },
          {
            "type": "command",
            "command": "~/.claude/hooks/auto-format.sh",
            "timeout": 15000
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/notify.sh",
            "timeout": 10000
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/reinject-context.sh",
            "timeout": 10000
          }
        ]
      }
    ]
  }
}'

if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo "$HOOKS_CONFIG" > "$SETTINGS_FILE"
    echo "[done] Created $SETTINGS_FILE with hooks"
elif command -v jq &>/dev/null; then
    # Check if hooks key already exists
    HAS_HOOKS=$(jq 'has("hooks")' "$SETTINGS_FILE" 2>/dev/null)
    if [[ "$HAS_HOOKS" == "true" ]]; then
        echo "[skip] $SETTINGS_FILE already has hooks configured (not overwriting)"
    else
        # Add hooks key, preserve everything else (permissions, etc.)
        EXISTING=$(cat "$SETTINGS_FILE")
        MERGED=$(echo "$EXISTING" | jq --argjson hooks "$(echo "$HOOKS_CONFIG" | jq '.hooks')" '. + {hooks: $hooks}')
        echo "$MERGED" > "$SETTINGS_FILE"
        echo "[done] Added hooks to existing $SETTINGS_FILE"
    fi
else
    echo "[WARN] $SETTINGS_FILE already exists and jq is not installed for safe merge."
    echo "       Add the hooks configuration manually. See docs/hooks-guide.md"
fi

# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Templates created (all with Agent Team configs):"
for dir in "$TEMPLATES_DIR"/*/; do
    type_name=$(basename "$dir")
    # Count team roles from CLAUDE.md (roles appear as "| **Role** |" in tables)
    roles=$(grep -c '| \*\*' "$dir/CLAUDE.md" 2>/dev/null || echo "?")
    printf "  %-20s (%s agent roles)\n" "$type_name" "$roles"
done
echo ""
echo "Quick start:"
echo "  claude-code list                              # see all templates"
echo "  claude-code init java-enterprise ~/projects/my-app"
echo "  claude-code ~/projects/my-app                 # start Claude session"
echo ""
echo "Global hooks installed (active in all projects):"
echo "  - verify-on-stop.sh    — runs tests when Claude finishes"
echo "  - verify-after-edit.sh — runs type checker after source edits"
echo "  - auto-format.sh       — runs formatter after source edits"
echo "  - protect-files.sh     — blocks edits to .env, *.lock, .git/, credentials"
echo "  - reinject-context.sh  — re-injects project context on session start"
echo "  - notify.sh            — desktop notifications when Claude needs input"
echo ""
echo "Custom agents installed:"
echo "  Utility agents:"
echo "  - code-simplifier      — post-build code cleanup (read + edit)"
echo "  - verify-app           — end-to-end project verification (read + bash)"
echo "  - security-review      — vulnerability scanning (read-only)"
echo "  - doc-writer           — documentation updates (read + edit + write)"
echo "  - phase-recap          — phase recap generation (read + bash)"
echo "  Phase agents:"
echo "  - research             — codebase exploration, no code changes (opus)"
echo "  - plan                 — clarification + implementation plans (opus)"
echo "  - build                — team lead, delegates + integrates (sonnet)"
echo "  - review               — holistic review, tests, integration (opus)"
echo ""
echo "Rules installed:"
echo "  - ~/.claude/rules/          — 3 global rules (auto-loaded every session)"
echo "  - ~/.claude/rules-library/  — 10 library rules (loaded on demand by agents)"
echo ""
echo "Each project now includes:"
echo "  - CLAUDE.md with stack, conventions, and Agent Team config"
echo "  - /project:team-review command for full team review"
echo "  - Role-specific delegation prompts for the Task tool"
echo ""
echo "Remember to customize each project's CLAUDE.md after init!"
echo "Look for ← UPDATE comments for project-specific values."
echo ""
