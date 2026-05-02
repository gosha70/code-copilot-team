#!/bin/bash
# claude-setup.sh - One-time setup for Claude Code project templates
#
# Creates:
#   ~/.claude/CLAUDE.md                    Global configuration
#   ~/.claude/rules/                       Global rules (auto-loaded, 4 files)
#   ~/.claude/skills/*/SKILL.md            On-demand skills (SKILL.md format, 15 skills)
#   ~/.claude/agents/                      Global agents (5 utility + 4 phase)
#   ~/.claude/hooks/                       Global hook scripts (verify, notify)
#   ~/.claude/settings.json                Global settings with hooks wired
#   ~/.claude/templates/<type>/CLAUDE.md   Project templates (with Agent Team configs)
#   ~/.claude/templates/<type>/commands/   Custom slash commands per type
#   Installs claude-code launcher to ~/.local/bin/
#
# Run once, then use 'claude-code init <type> [path]' to scaffold projects.
# Run with --sync to re-copy rules, skills, agents, hooks, templates, and launcher from repo.
# Then use 'claude-code sync [path]' to update individual projects against their template.
set -e

CLAUDE_DIR="$HOME/.claude"
TEMPLATES_DIR="$CLAUDE_DIR/templates"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")" && pwd)"
SHARED_DIR="$SCRIPT_DIR/../../shared"
LAUNCHER_SOURCE="$SCRIPT_DIR/claude-code"
LAUNCHER_TARGET="$HOME/.local/bin/claude-code"
SYNC_MODE=0
PLAYWRIGHT_MODE=0
MEMKERNEL_ENABLED=0
MEMKERNEL_SOURCE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sync)
            SYNC_MODE=1
            shift
            ;;
        --playwright)
            PLAYWRIGHT_MODE=1
            shift
            ;;
        --memkernel)
            MEMKERNEL_ENABLED=1
            if [[ -n "${2:-}" && "${2:0:2}" != "--" ]]; then
                MEMKERNEL_SOURCE="$2"
                shift 2
            else
                shift
            fi
            ;;
        --configure-providers)
            CONFIGURE_PROVIDERS=1
            shift
            ;;
        *)
            echo "[ERROR] Unknown option: $1"
            echo "        Supported options: --sync, --playwright, --memkernel [path], --configure-providers"
            exit 1
            ;;
    esac
done

if [[ "$PLAYWRIGHT_MODE" == "1" && ( "$SYNC_MODE" == "1" || "$MEMKERNEL_ENABLED" == "1" ) ]]; then
    echo "[ERROR] --playwright cannot be combined with --sync or --memkernel"
    exit 1
fi

maybe_install_memkernel() {
    if [[ "$MEMKERNEL_ENABLED" != "1" ]]; then
        return
    fi

    if [[ -n "$MEMKERNEL_SOURCE" ]]; then
        if [[ ! -d "$MEMKERNEL_SOURCE" ]]; then
            echo "[WARN] MemKernel source path not found: $MEMKERNEL_SOURCE"
            return
        fi
        if command -v python3 &>/dev/null; then
            if python3 -m pip install -e "$MEMKERNEL_SOURCE"; then
                echo "[done] Installed MemKernel from $MEMKERNEL_SOURCE"
            else
                echo "[WARN] MemKernel install failed from $MEMKERNEL_SOURCE"
            fi
        else
            echo "[WARN] python3 not found. Install MemKernel manually from: $MEMKERNEL_SOURCE"
        fi
        return
    fi

    if command -v memkernel &>/dev/null; then
        echo "[ok]   memkernel found: $(command -v memkernel)"
    else
        echo "[WARN] --memkernel requested but memkernel is not on PATH and no source path was provided"
    fi
}

ensure_hook_command() {
    local settings_file="$1"
    local event_name="$2"
    local matcher="$3"
    local command_name="$4"
    local timeout_ms="$5"
    local has_hook has_matcher content

    has_hook=$(jq --arg event "$event_name" --arg command "$command_name" \
        '[.hooks[$event][]?.hooks[]? | select(.command == $command)] | length > 0' \
        "$settings_file" 2>/dev/null || echo "false")
    if [[ "$has_hook" == "true" ]]; then
        return 1
    fi

    has_matcher=$(jq --arg event "$event_name" --arg matcher "$matcher" \
        '[.hooks[$event][]? | select(.matcher == $matcher)] | length > 0' \
        "$settings_file" 2>/dev/null || echo "false")

    if [[ "$has_matcher" == "true" ]]; then
        content=$(jq --arg event "$event_name" --arg matcher "$matcher" --arg command "$command_name" --argjson timeout "$timeout_ms" '
            (.hooks[$event][] | select(.matcher == $matcher) | .hooks) += [
              {"type":"command","command":$command,"timeout":$timeout}
            ]
        ' "$settings_file")
    else
        content=$(jq --arg event "$event_name" --arg matcher "$matcher" --arg command "$command_name" --argjson timeout "$timeout_ms" '
            .hooks[$event] //= [] |
            .hooks[$event] += [
              {
                "matcher": $matcher,
                "hooks": [
                  {"type":"command","command":$command,"timeout":$timeout}
                ]
              }
            ]
        ' "$settings_file")
    fi

    echo "$content" > "$settings_file"
    return 0
}

# ══════════════════════════════════════════════════════════════
# --sync: re-copy rules, skills, agents, hooks, and launcher from repo
# ══════════════════════════════════════════════════════════════

if [[ "$SYNC_MODE" == "1" ]]; then
    maybe_install_memkernel
    echo "Syncing rules, skills, agents, hooks, and launcher from repo..."

    # Global rules (always skills) — from shared/skills/
    SKILLS_SOURCE="$SHARED_DIR/skills"
    RULES_TARGET="$CLAUDE_DIR/rules"
    mkdir -p "$RULES_TARGET"
    for name in coding-standards copilot-conventions copyright-headers safety; do
        if [[ -f "$SKILLS_SOURCE/$name/SKILL.md" ]]; then
            # Remove stale symlinks from pre-SKILL.md layout
            [[ -L "$RULES_TARGET/$name.md" ]] && rm -f "$RULES_TARGET/$name.md"
            # Strip frontmatter, install body as plain .md for auto-loading
            awk 'BEGIN{n=0} /^---$/{n++; if(n==2){found=1; next}} found{print}' "$SKILLS_SOURCE/$name/SKILL.md" > "$RULES_TARGET/$name.md"
        fi
    done
    echo "[done] Synced rules to $RULES_TARGET"

    # On-demand skills — from shared/skills/ to ~/.claude/skills/
    SKILLS_TARGET="$CLAUDE_DIR/skills"
    mkdir -p "$SKILLS_TARGET"
    for skill_dir in "$SKILLS_SOURCE"/*/; do
        [[ -d "$skill_dir" ]] || continue
        sname=$(basename "$skill_dir")
        # Skip always skills (they go to rules/)
        case "$sname" in coding-standards|copilot-conventions|copyright-headers|safety) continue ;; esac
        mkdir -p "$SKILLS_TARGET/$sname"
        cp "$skill_dir/SKILL.md" "$SKILLS_TARGET/$sname/SKILL.md"
    done
    echo "[done] Synced skills to $SKILLS_TARGET"

    # Agents (9 files)
    AGENTS_SOURCE="$SCRIPT_DIR/.claude/agents"
    AGENTS_TARGET="$CLAUDE_DIR/agents"
    mkdir -p "$AGENTS_TARGET"
    if [[ -d "$AGENTS_SOURCE" ]]; then
        cp "$AGENTS_SOURCE"/*.md "$AGENTS_TARGET/" 2>/dev/null || true
        echo "[done] Synced agents to $AGENTS_TARGET"
    fi

    # Hooks
    HOOKS_SOURCE="$SCRIPT_DIR/.claude/hooks"
    HOOKS_TARGET="$CLAUDE_DIR/hooks"
    mkdir -p "$HOOKS_TARGET"
    if [[ -d "$HOOKS_SOURCE" ]]; then
        for hook_file in \
            notify.sh \
            verify-after-edit.sh \
            verify-on-stop.sh \
            auto-format.sh \
            protect-files.sh \
            protect-git.sh \
            reinject-context.sh \
            peer-review-on-stop.sh \
            memkernel-recall.sh \
            memkernel-recall.py \
            memkernel-pre-compact.sh \
            memkernel-pre-compact.py \
            memkernel-post-compact.sh \
            memkernel-post-compact.py
        do
            [[ -f "$HOOKS_SOURCE/$hook_file" ]] || continue
            cp "$HOOKS_SOURCE/$hook_file" "$HOOKS_TARGET/$hook_file"
        done
        chmod +x "$HOOKS_TARGET"/*.sh 2>/dev/null || true
        echo "[done] Synced hooks to $HOOKS_TARGET"
    fi

    # Status line script
    STATUSLINE_SOURCE="$SCRIPT_DIR/.claude/statusline.sh"
    STATUSLINE_TARGET="$CLAUDE_DIR/statusline.sh"
    if [[ -f "$STATUSLINE_SOURCE" ]]; then
        cp "$STATUSLINE_SOURCE" "$STATUSLINE_TARGET"
        chmod +x "$STATUSLINE_TARGET"
        echo "[done] Synced statusline.sh to $STATUSLINE_TARGET"
    fi

    # Wire hooks + statusLine into settings.json if missing
    SETTINGS_FILE="$CLAUDE_DIR/settings.json"
    if [[ -f "$SETTINGS_FILE" ]] && command -v jq &>/dev/null; then
        CONTENT=$(jq '.hooks //= {} | .env //= {}' "$SETTINGS_FILE")
        echo "$CONTENT" > "$SETTINGS_FILE"

        HAS_STATUSLINE=$(jq 'has("statusLine")' "$SETTINGS_FILE" 2>/dev/null || echo "false")
        if [[ "$HAS_STATUSLINE" != "true" ]]; then
            CONTENT=$(jq '.statusLine = {"type":"command","command":"~/.claude/statusline.sh"}' "$SETTINGS_FILE")
            echo "$CONTENT" > "$SETTINGS_FILE"
            echo "[done] Added statusLine to $SETTINGS_FILE"
        fi

        for VAR_KEY in CCT_PEER_REVIEW_ENABLED CCT_PEER_PROVIDER CCT_PEER_TRIGGER; do
            HAS_VAR=$(jq --arg key "$VAR_KEY" '.env | has($key)' "$SETTINGS_FILE" 2>/dev/null || echo "false")
            if [[ "$HAS_VAR" != "true" ]]; then
                case "$VAR_KEY" in
                    CCT_PEER_REVIEW_ENABLED) DEFAULT_VAL="false" ;;
                    CCT_PEER_PROVIDER) DEFAULT_VAL="" ;;
                    CCT_PEER_TRIGGER) DEFAULT_VAL="phase-complete" ;;
                esac
                CONTENT=$(jq --arg key "$VAR_KEY" --arg value "$DEFAULT_VAL" '.env[$key] = $value' "$SETTINGS_FILE")
                echo "$CONTENT" > "$SETTINGS_FILE"
            fi
        done

        ensure_hook_command "$SETTINGS_FILE" "PreToolUse" "Bash" "~/.claude/hooks/protect-git.sh" 5000 && \
            echo "[done] Added protect-git hook to $SETTINGS_FILE" || true
        ensure_hook_command "$SETTINGS_FILE" "Stop" "" "~/.claude/hooks/peer-review-on-stop.sh" 300000 && \
            echo "[done] Added peer-review hook to $SETTINGS_FILE" || true
        ensure_hook_command "$SETTINGS_FILE" "SessionStart" "" "~/.claude/hooks/memkernel-recall.sh" 30000 && \
            echo "[done] Added MemKernel SessionStart hook to $SETTINGS_FILE" || true
        ensure_hook_command "$SETTINGS_FILE" "PreCompact" "" "~/.claude/hooks/memkernel-pre-compact.sh" 30000 && \
            echo "[done] Added MemKernel PreCompact hook to $SETTINGS_FILE" || true
        ensure_hook_command "$SETTINGS_FILE" "PostCompact" "" "~/.claude/hooks/memkernel-post-compact.sh" 30000 && \
            echo "[done] Added MemKernel PostCompact hook to $SETTINGS_FILE" || true
    fi

    # Templates — clean redeploy from repo to ~/.claude/templates/
    # First, collect the set of repo template names so we can prune stale ones.
    REPO_TEMPLATES=()
    for tmpl_dir in "$SHARED_DIR"/templates/*/; do
        [[ -f "$tmpl_dir/PROJECT.md" ]] || continue
        REPO_TEMPLATES+=("$(basename "$tmpl_dir")")
    done

    # Prune installed templates that no longer exist in the repo.
    if [[ -d "$TEMPLATES_DIR" ]]; then
        for installed_dir in "$TEMPLATES_DIR"/*/; do
            [[ -d "$installed_dir" ]] || continue
            installed_name=$(basename "$installed_dir")
            found=0
            for repo_name in "${REPO_TEMPLATES[@]}"; do
                if [[ "$repo_name" == "$installed_name" ]]; then
                    found=1
                    break
                fi
            done
            if [[ $found -eq 0 ]]; then
                rm -rf "$installed_dir"
                echo "[prune] Removed retired template: $installed_name"
            fi
        done
    fi

    # Remove and recreate each current template so deleted files don't linger.
    for tmpl_dir in "$SHARED_DIR"/templates/*/; do
        [[ -f "$tmpl_dir/PROJECT.md" ]] || continue
        tmpl_name=$(basename "$tmpl_dir")
        dest="$TEMPLATES_DIR/$tmpl_name"
        rm -rf "$dest"
        mkdir -p "$dest/commands"
        cp "$tmpl_dir/PROJECT.md" "$dest/CLAUDE.md"
        if [[ -d "$tmpl_dir/commands" ]]; then
            cp "$tmpl_dir/commands/"*.md "$dest/commands/" 2>/dev/null || true
        fi
        if [[ -d "$tmpl_dir/.claude" ]]; then
            mkdir -p "$dest/.claude"
            cp -r "$tmpl_dir/.claude/"* "$dest/.claude/" 2>/dev/null || true
        fi
        if [[ -d "$tmpl_dir/.github" ]]; then
            cp -r "$tmpl_dir/.github" "$dest/" 2>/dev/null || true
        fi
    done
    echo "[done] Synced templates to $TEMPLATES_DIR"

    # SDD / Shape-Up template library (flat dir; templates loop above filters by PROJECT.md)
    if [[ -d "$SHARED_DIR/templates/sdd" ]]; then
        SDD_TARGET="$TEMPLATES_DIR/sdd"
        rm -rf "$SDD_TARGET"
        mkdir -p "$SDD_TARGET"
        cp "$SHARED_DIR/templates/sdd/"*.md "$SDD_TARGET/" 2>/dev/null || true
        cp "$SHARED_DIR/templates/sdd/"*.json "$SDD_TARGET/" 2>/dev/null || true
        if [[ -f "$SHARED_DIR/templates/sdd/validate-pitch.sh" ]]; then
            cp "$SHARED_DIR/templates/sdd/validate-pitch.sh" "$SDD_TARGET/validate-pitch.sh"
            chmod +x "$SDD_TARGET/validate-pitch.sh"
        fi
        echo "[done] Synced SDD templates to $SDD_TARGET"
    fi

    # Launcher
    if [[ -f "$LAUNCHER_SOURCE" ]]; then
        mkdir -p "$HOME/.local/bin"
        cp "$LAUNCHER_SOURCE" "$LAUNCHER_TARGET"
        chmod +x "$LAUNCHER_TARGET"
        echo "[done] Synced launcher to $LAUNCHER_TARGET"
    fi

    echo "Sync complete."
    exit 0
fi

# ══════════════════════════════════════════════════════════════
# --playwright: install Playwright CLI for browser automation (optional)
# ══════════════════════════════════════════════════════════════

if [[ "$PLAYWRIGHT_MODE" == "1" ]]; then
    echo "Installing Playwright CLI for browser automation..."

    if command -v npm &>/dev/null; then
        npm install -g @playwright/cli@latest
        echo "[done] Playwright CLI installed globally"
        playwright-cli install --skills 2>/dev/null && echo "[done] Playwright skills installed" \
            || echo "[info] Skills install skipped (run 'playwright-cli install --skills' manually)"
    else
        echo "[WARN] npm not found. Install Playwright CLI manually:"
        echo "       npm install -g @playwright/cli@latest"
        echo "       playwright-cli install --skills"
    fi

    echo ""
    echo "Playwright CLI setup complete."
    echo "Usage: playwright-cli open <url>, playwright-cli click, playwright-cli screenshot"
    exit 0
fi

maybe_install_memkernel

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
  specialist sub-agents via the Agent tool.
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
if [[ -d "$SHARED_DIR/templates/ml-rag/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/ml-rag/.claude"
    cp -r "$SHARED_DIR/templates/ml-rag/.claude/"* "$TEMPLATES_DIR/ml-rag/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/ml-rag/.github" ]]; then
    cp -r "$SHARED_DIR/templates/ml-rag/.github" "$TEMPLATES_DIR/ml-rag/" 2>/dev/null || true
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
if [[ -d "$SHARED_DIR/templates/ml-app/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/ml-app/.claude"
    cp -r "$SHARED_DIR/templates/ml-app/.claude/"* "$TEMPLATES_DIR/ml-app/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/ml-app/.github" ]]; then
    cp -r "$SHARED_DIR/templates/ml-app/.github" "$TEMPLATES_DIR/ml-app/" 2>/dev/null || true
fi
echo "[done] Created template: ml-app"

# ══════════════════════════════════════════════════════════════
# 3b. TEMPLATE: ml-utils
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-utils/commands"
cp "$SHARED_DIR/templates/ml-utils/PROJECT.md" "$TEMPLATES_DIR/ml-utils/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/ml-utils/commands" ]]; then
    cp "$SHARED_DIR/templates/ml-utils/commands/"*.md "$TEMPLATES_DIR/ml-utils/commands/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/ml-utils/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/ml-utils/.claude"
    cp -r "$SHARED_DIR/templates/ml-utils/.claude/"* "$TEMPLATES_DIR/ml-utils/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/ml-utils/.github" ]]; then
    cp -r "$SHARED_DIR/templates/ml-utils/.github" "$TEMPLATES_DIR/ml-utils/" 2>/dev/null || true
fi
echo "[done] Created template: ml-utils"

# ══════════════════════════════════════════════════════════════
# 4. TEMPLATE: ml-langchain
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-langchain/commands"
cp "$SHARED_DIR/templates/ml-langchain/PROJECT.md" "$TEMPLATES_DIR/ml-langchain/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/ml-langchain/commands" ]]; then
    cp "$SHARED_DIR/templates/ml-langchain/commands/"*.md "$TEMPLATES_DIR/ml-langchain/commands/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/ml-langchain/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/ml-langchain/.claude"
    cp -r "$SHARED_DIR/templates/ml-langchain/.claude/"* "$TEMPLATES_DIR/ml-langchain/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/ml-langchain/.github" ]]; then
    cp -r "$SHARED_DIR/templates/ml-langchain/.github" "$TEMPLATES_DIR/ml-langchain/" 2>/dev/null || true
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
if [[ -d "$SHARED_DIR/templates/ml-n8n/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/ml-n8n/.claude"
    cp -r "$SHARED_DIR/templates/ml-n8n/.claude/"* "$TEMPLATES_DIR/ml-n8n/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/ml-n8n/.github" ]]; then
    cp -r "$SHARED_DIR/templates/ml-n8n/.github" "$TEMPLATES_DIR/ml-n8n/" 2>/dev/null || true
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
if [[ -d "$SHARED_DIR/templates/java-enterprise/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/java-enterprise/.claude"
    cp -r "$SHARED_DIR/templates/java-enterprise/.claude/"* "$TEMPLATES_DIR/java-enterprise/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/java-enterprise/.github" ]]; then
    cp -r "$SHARED_DIR/templates/java-enterprise/.github" "$TEMPLATES_DIR/java-enterprise/" 2>/dev/null || true
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
if [[ -d "$SHARED_DIR/templates/web-static/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/web-static/.claude"
    cp -r "$SHARED_DIR/templates/web-static/.claude/"* "$TEMPLATES_DIR/web-static/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/web-static/.github" ]]; then
    cp -r "$SHARED_DIR/templates/web-static/.github" "$TEMPLATES_DIR/web-static/" 2>/dev/null || true
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
if [[ -d "$SHARED_DIR/templates/web-dynamic/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/web-dynamic/.claude"
    cp -r "$SHARED_DIR/templates/web-dynamic/.claude/"* "$TEMPLATES_DIR/web-dynamic/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/web-dynamic/.github" ]]; then
    cp -r "$SHARED_DIR/templates/web-dynamic/.github" "$TEMPLATES_DIR/web-dynamic/" 2>/dev/null || true
fi
echo "[done] Created template: web-dynamic"

# ══════════════════════════════════════════════════════════════
# 9. TEMPLATE: java-tooling
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/java-tooling/commands"
cp "$SHARED_DIR/templates/java-tooling/PROJECT.md" "$TEMPLATES_DIR/java-tooling/CLAUDE.md"
if [[ -d "$SHARED_DIR/templates/java-tooling/commands" ]]; then
    cp "$SHARED_DIR/templates/java-tooling/commands/"*.md "$TEMPLATES_DIR/java-tooling/commands/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/java-tooling/.claude" ]]; then
    mkdir -p "$TEMPLATES_DIR/java-tooling/.claude"
    cp -r "$SHARED_DIR/templates/java-tooling/.claude/"* "$TEMPLATES_DIR/java-tooling/.claude/" 2>/dev/null || true
fi
if [[ -d "$SHARED_DIR/templates/java-tooling/.github" ]]; then
    cp -r "$SHARED_DIR/templates/java-tooling/.github" "$TEMPLATES_DIR/java-tooling/" 2>/dev/null || true
fi
echo "[done] Created template: java-tooling"

# ══════════════════════════════════════════════════════════════
# 9b. INSTALL SDD / SHAPE-UP TEMPLATE LIBRARY
# ══════════════════════════════════════════════════════════════
# Flat template dir without PROJECT.md — used by Shape-Up agents
# (pitch-shaper, scope-executor, cycle-retro, cooldown-report) and
# slash commands (/shape, /bet, /cycle-start, /hill, /cooldown).
# Ships pitch-template.md, hill-chart.json, cycle-retro-template.md,
# cooldown-report-template.md, and the validate-pitch.sh validator.

if [[ -d "$SHARED_DIR/templates/sdd" ]]; then
    mkdir -p "$TEMPLATES_DIR/sdd"
    cp "$SHARED_DIR/templates/sdd/"*.md "$TEMPLATES_DIR/sdd/" 2>/dev/null || true
    cp "$SHARED_DIR/templates/sdd/"*.json "$TEMPLATES_DIR/sdd/" 2>/dev/null || true
    if [[ -f "$SHARED_DIR/templates/sdd/validate-pitch.sh" ]]; then
        cp "$SHARED_DIR/templates/sdd/validate-pitch.sh" "$TEMPLATES_DIR/sdd/validate-pitch.sh"
        chmod +x "$TEMPLATES_DIR/sdd/validate-pitch.sh"
    fi
    echo "[done] Created template library: sdd"
fi

# ══════════════════════════════════════════════════════════════
# 10. INSTALL LAUNCHER SCRIPT
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
# 11. GLOBAL HOOKS
# ══════════════════════════════════════════════════════════════

HOOKS_SOURCE="$SCRIPT_DIR/.claude/hooks"
HOOKS_TARGET="$CLAUDE_DIR/hooks"

mkdir -p "$HOOKS_TARGET"

if [[ -d "$HOOKS_SOURCE" ]]; then
    for hook_file in \
        notify.sh \
        verify-after-edit.sh \
        verify-on-stop.sh \
        auto-format.sh \
        protect-files.sh \
        protect-git.sh \
        reinject-context.sh \
        peer-review-on-stop.sh \
        memkernel-recall.sh \
        memkernel-recall.py \
        memkernel-pre-compact.sh \
        memkernel-pre-compact.py \
        memkernel-post-compact.sh \
        memkernel-post-compact.py
    do
        [[ -f "$HOOKS_SOURCE/$hook_file" ]] || continue
        cp "$HOOKS_SOURCE/$hook_file" "$HOOKS_TARGET/$hook_file"
    done
    chmod +x "$HOOKS_TARGET"/*.sh 2>/dev/null || true
    echo "[done] Installed hooks to $HOOKS_TARGET"
else
    echo "[skip] Hook scripts not found at $HOOKS_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 11a. GLOBAL COMMANDS
# ══════════════════════════════════════════════════════════════

COMMANDS_SOURCE="$SCRIPT_DIR/.claude/commands"
COMMANDS_TARGET="$CLAUDE_DIR/commands"

mkdir -p "$COMMANDS_TARGET"

if [[ -d "$COMMANDS_SOURCE" ]]; then
    cp "$COMMANDS_SOURCE"/*.md "$COMMANDS_TARGET/" 2>/dev/null || true
    echo "[done] Installed commands to $COMMANDS_TARGET"
else
    echo "[skip] Command files not found at $COMMANDS_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 11b. GLOBAL AGENTS
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
# 11c. GLOBAL RULES (always skills, 4 files) — from shared/skills/
# ══════════════════════════════════════════════════════════════

SKILLS_SOURCE="$SHARED_DIR/skills"
RULES_TARGET="$CLAUDE_DIR/rules"

mkdir -p "$RULES_TARGET"

if [[ -d "$SKILLS_SOURCE" ]]; then
    for name in coding-standards copilot-conventions copyright-headers safety; do
        if [[ -f "$SKILLS_SOURCE/$name/SKILL.md" ]]; then
            # Remove stale symlinks from pre-SKILL.md layout
            [[ -L "$RULES_TARGET/$name.md" ]] && rm -f "$RULES_TARGET/$name.md"
            # Strip frontmatter, install body as plain .md for auto-loading
            awk 'BEGIN{n=0} /^---$/{n++; if(n==2){found=1; next}} found{print}' "$SKILLS_SOURCE/$name/SKILL.md" > "$RULES_TARGET/$name.md"
        fi
    done
    echo "[done] Installed global rules to $RULES_TARGET"
else
    echo "[skip] Skills not found at $SKILLS_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 11d. ON-DEMAND SKILLS (15 skills) — from shared/skills/ to ~/.claude/skills/
# ══════════════════════════════════════════════════════════════

SKILLS_TARGET="$CLAUDE_DIR/skills"

mkdir -p "$SKILLS_TARGET"

if [[ -d "$SKILLS_SOURCE" ]]; then
    for skill_dir in "$SKILLS_SOURCE"/*/; do
        [[ -d "$skill_dir" ]] || continue
        sname=$(basename "$skill_dir")
        # Skip always skills (they go to rules/)
        case "$sname" in coding-standards|copilot-conventions|copyright-headers|safety) continue ;; esac
        mkdir -p "$SKILLS_TARGET/$sname"
        cp "$skill_dir/SKILL.md" "$SKILLS_TARGET/$sname/SKILL.md"
    done
    echo "[done] Installed skills to $SKILLS_TARGET"
else
    echo "[skip] Skills not found at $SKILLS_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 11e. STATUS LINE SCRIPT
# ══════════════════════════════════════════════════════════════

STATUSLINE_SOURCE="$SCRIPT_DIR/.claude/statusline.sh"
STATUSLINE_TARGET="$CLAUDE_DIR/statusline.sh"

if [[ -f "$STATUSLINE_SOURCE" ]]; then
    cp "$STATUSLINE_SOURCE" "$STATUSLINE_TARGET"
    chmod +x "$STATUSLINE_TARGET"
    echo "[done] Installed statusline.sh to $STATUSLINE_TARGET"
else
    echo "[skip] statusline.sh not found at $STATUSLINE_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 12. GLOBAL SETTINGS (hooks wiring)
# ══════════════════════════════════════════════════════════════

SETTINGS_FILE="$CLAUDE_DIR/settings.json"
HOOKS_CONFIG='{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh"
  },
  "env": {
    "HOOK_EDIT_BLOCK": "true",
    "HOOK_STOP_BLOCK": "false",
    "CCT_PEER_REVIEW_ENABLED": "false",
    "CCT_PEER_PROVIDER": "",
    "CCT_PEER_TRIGGER": "phase-complete"
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
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/protect-git.sh",
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
          },
          {
            "type": "command",
            "command": "~/.claude/hooks/peer-review-on-stop.sh",
            "timeout": 300000
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
          },
          {
            "type": "command",
            "command": "~/.claude/hooks/memkernel-recall.sh",
            "timeout": 30000
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/memkernel-pre-compact.sh",
            "timeout": 30000
          }
        ]
      }
    ],
    "PostCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/memkernel-post-compact.sh",
            "timeout": 30000
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
        # Merge missing env defaults and hook entries into existing settings
        UPDATED="$SETTINGS_FILE"
        CHANGED=0

        # Add missing CCT_* env vars
        for VAR_KEY in CCT_PEER_REVIEW_ENABLED CCT_PEER_PROVIDER CCT_PEER_TRIGGER; do
            HAS_VAR=$(jq --arg k "$VAR_KEY" '.env | has($k)' "$UPDATED" 2>/dev/null || echo "false")
            if [[ "$HAS_VAR" != "true" ]]; then
                DEFAULT_VAL=$(echo "$HOOKS_CONFIG" | jq -r --arg k "$VAR_KEY" '.env[$k]')
                CONTENT=$(jq --arg k "$VAR_KEY" --arg v "$DEFAULT_VAL" '.env[$k] = $v' "$UPDATED")
                echo "$CONTENT" > "$UPDATED"
                CHANGED=1
            fi
        done

        # Add peer-review-on-stop.sh to Stop hooks if missing
        HAS_PEER_HOOK=$(jq '[.hooks.Stop[]?.hooks[]? | select(.command == "~/.claude/hooks/peer-review-on-stop.sh")] | length > 0' "$UPDATED" 2>/dev/null || echo "false")
        if [[ "$HAS_PEER_HOOK" != "true" ]]; then
            CONTENT=$(jq '.hooks.Stop[0].hooks += [{"type":"command","command":"~/.claude/hooks/peer-review-on-stop.sh","timeout":300000}]' "$UPDATED")
            echo "$CONTENT" > "$UPDATED"
            CHANGED=1
        fi

        # Add protect-git.sh to PreToolUse Bash hooks if missing
        HAS_GIT_HOOK=$(jq '[.hooks.PreToolUse[]? | select(.matcher == "Bash") | .hooks[]? | select(.command == "~/.claude/hooks/protect-git.sh")] | length > 0' "$UPDATED" 2>/dev/null || echo "false")
        if [[ "$HAS_GIT_HOOK" != "true" ]]; then
            # Check if a Bash matcher entry already exists
            HAS_BASH_MATCHER=$(jq '[.hooks.PreToolUse[]? | select(.matcher == "Bash")] | length > 0' "$UPDATED" 2>/dev/null || echo "false")
            if [[ "$HAS_BASH_MATCHER" == "true" ]]; then
                CONTENT=$(jq '(.hooks.PreToolUse[] | select(.matcher == "Bash") | .hooks) += [{"type":"command","command":"~/.claude/hooks/protect-git.sh","timeout":5000}]' "$UPDATED")
            else
                CONTENT=$(jq '.hooks.PreToolUse += [{"matcher":"Bash","hooks":[{"type":"command","command":"~/.claude/hooks/protect-git.sh","timeout":5000}]}]' "$UPDATED")
            fi
            echo "$CONTENT" > "$UPDATED"
            CHANGED=1
        fi

        # Add statusLine if missing
        HAS_STATUSLINE=$(jq 'has("statusLine")' "$UPDATED" 2>/dev/null || echo "false")
        if [[ "$HAS_STATUSLINE" != "true" ]]; then
            CONTENT=$(jq '.statusLine = {"type":"command","command":"~/.claude/statusline.sh"}' "$UPDATED")
            echo "$CONTENT" > "$UPDATED"
            CHANGED=1
        fi

        ensure_hook_command "$UPDATED" "SessionStart" "" "~/.claude/hooks/memkernel-recall.sh" 30000 && CHANGED=1 || true
        ensure_hook_command "$UPDATED" "PreCompact" "" "~/.claude/hooks/memkernel-pre-compact.sh" 30000 && CHANGED=1 || true
        ensure_hook_command "$UPDATED" "PostCompact" "" "~/.claude/hooks/memkernel-post-compact.sh" 30000 && CHANGED=1 || true

        if [[ $CHANGED -eq 1 ]]; then
            echo "[done] Updated $SETTINGS_FILE with missing config"
        else
            echo "[skip] $SETTINGS_FILE already up to date"
        fi
    else
        # Add hooks + statusLine keys, preserve everything else (permissions, etc.)
        EXISTING=$(cat "$SETTINGS_FILE")
        MERGED=$(echo "$EXISTING" | jq \
            --argjson hooks "$(echo "$HOOKS_CONFIG" | jq '.hooks')" \
            --argjson sl '{"type":"command","command":"~/.claude/statusline.sh"}' \
            '. + {hooks: $hooks, statusLine: $sl}')
        echo "$MERGED" > "$SETTINGS_FILE"
        echo "[done] Added hooks and statusLine to existing $SETTINGS_FILE"
    fi
else
    echo "[WARN] $SETTINGS_FILE already exists and jq is not installed for safe merge."
    echo "       Add the hooks configuration manually. See docs/hooks-guide.md"
fi

# ══════════════════════════════════════════════════════════════
# 13. PROVIDER PROFILE
# ══════════════════════════════════════════════════════════════

PROVIDER_DIR="$HOME/.code-copilot-team"
PROVIDER_FILE="$PROVIDER_DIR/providers.toml"

if [[ ! -f "$PROVIDER_FILE" ]]; then
    mkdir -p "$PROVIDER_DIR"
    cp "$SHARED_DIR/templates/provider-profile-template.toml" "$PROVIDER_FILE"
    echo "[done] Created provider profile at $PROVIDER_FILE"
else
    echo "[skip] Provider profile already exists at $PROVIDER_FILE"
fi

# Prompt for company name if not already set (interactive sessions only)
if [[ -t 0 && -z "${CI:-}" && -f "$PROVIDER_FILE" ]]; then
    _CURRENT_COMPANY=$(grep '^company[[:space:]]*=[[:space:]]*' "$PROVIDER_FILE" \
        | head -1 \
        | sed 's/^company[[:space:]]*=[[:space:]]*"//; s/"[[:space:]]*$//' 2>/dev/null || echo "")
    if [[ -z "$_CURRENT_COMPANY" ]]; then
        echo ""
        read -rp "Company name for copyright headers (e.g. ACME Corp; leave blank to skip): " _INPUT_COMPANY
        if [[ -n "$_INPUT_COMPANY" ]]; then
            python3 - "$PROVIDER_FILE" "$_INPUT_COMPANY" <<'PYEOF'
import sys, re
path, company = sys.argv[1], sys.argv[2]
# Escape backslashes and double quotes for TOML double-quoted string
escaped = company.replace('\\', '\\\\').replace('"', '\\"')
content = open(path).read()
content = re.sub(r'^company\s*=\s*""', f'company = "{escaped}"', content, flags=re.MULTILINE)
open(path, 'w').write(content)
PYEOF
            echo "[done] Set company name to '$_INPUT_COMPANY' in $PROVIDER_FILE"
        fi
    fi
fi

# ── Interactive provider configuration (--configure-providers) ─
if [[ "${CONFIGURE_PROVIDERS:-}" == "1" && -t 0 && -z "${CI:-}" ]]; then
    echo ""
    echo "══════════════════════════════════════════════════════"
    echo "  Configure Provider"
    echo "══════════════════════════════════════════════════════"
    echo ""
    echo "Provider types:"
    echo "  1) cli              — local CLI tool (Codex, Aider, etc.)"
    echo "  2) openai-compatible — OpenAI-compatible HTTP API"
    echo "  3) ollama           — Ollama instance (local or remote)"
    echo "  4) custom           — custom command template"
    echo ""
    read -rp "Select type [1-4]: " _TYPE_CHOICE
    case "$_TYPE_CHOICE" in
        1) _PTYPE="cli" ;;
        2) _PTYPE="openai-compatible" ;;
        3) _PTYPE="ollama" ;;
        4) _PTYPE="custom" ;;
        *) echo "[error] Invalid choice"; _PTYPE="" ;;
    esac

    if [[ -n "$_PTYPE" ]]; then
        read -rp "Provider name (e.g. gdx-spark, openai): " _PNAME
        if [[ -z "$_PNAME" ]]; then
            echo "[error] Provider name is required"
        else
            _PBLOCK="\n[providers.$_PNAME]\ntype = \"$_PTYPE\""

            case "$_PTYPE" in
                cli)
                    read -rp "Command template (use {review_request} and {model}): " _PCMD
                    read -rp "Healthcheck command: " _PHC
                    read -rp "Timeout (seconds) [300]: " _PTO
                    _PBLOCK="$_PBLOCK\ncommand = \"$_PCMD\""
                    [[ -n "$_PHC" ]] && _PBLOCK="$_PBLOCK\nhealthcheck = \"$_PHC\""
                    _PBLOCK="$_PBLOCK\ntimeout_sec = ${_PTO:-300}"
                    ;;
                openai-compatible)
                    read -rp "Base URL (e.g. http://192.168.1.50:8000/v1): " _PURL
                    read -rp "Model name: " _PMODEL
                    read -rp "API key env var name (leave blank if none): " _PKEY
                    read -rp "Healthcheck command: " _PHC
                    read -rp "Timeout (seconds) [300]: " _PTO
                    _PBLOCK="$_PBLOCK\nbase_url = \"$_PURL\""
                    [[ -n "$_PKEY" ]] && _PBLOCK="$_PBLOCK\napi_key_env = \"$_PKEY\""
                    _PBLOCK="$_PBLOCK\nmodel = \"$_PMODEL\""
                    _PBLOCK="$_PBLOCK\ntimeout_sec = ${_PTO:-300}"
                    [[ -n "$_PHC" ]] && _PBLOCK="$_PBLOCK\nhealthcheck = \"$_PHC\""
                    ;;
                ollama)
                    read -rp "Model name (e.g. llama3.1:70b): " _PMODEL
                    read -rp "Host:port [localhost:11434]: " _PHOST
                    read -rp "Healthcheck command [ollama list]: " _PHC
                    read -rp "Timeout (seconds) [600]: " _PTO
                    _PBLOCK="$_PBLOCK\nmodel = \"$_PMODEL\""
                    _PBLOCK="$_PBLOCK\nhost = \"${_PHOST:-localhost:11434}\""
                    _PBLOCK="$_PBLOCK\nhealthcheck = \"${_PHC:-ollama list}\""
                    _PBLOCK="$_PBLOCK\ntimeout_sec = ${_PTO:-600}"
                    ;;
                custom)
                    read -rp "Command template (use {review_request} and {model}): " _PCMD
                    read -rp "Healthcheck command: " _PHC
                    read -rp "Timeout (seconds) [300]: " _PTO
                    _PBLOCK="$_PBLOCK\ncommand = \"$_PCMD\""
                    [[ -n "$_PHC" ]] && _PBLOCK="$_PBLOCK\nhealthcheck = \"$_PHC\""
                    _PBLOCK="$_PBLOCK\ntimeout_sec = ${_PTO:-300}"
                    ;;
            esac

            # Append to providers.toml
            printf '\n' >> "$PROVIDER_FILE"
            printf '%b\n' "$_PBLOCK" >> "$PROVIDER_FILE"
            echo "[done] Added provider '$_PNAME' (type: $_PTYPE) to $PROVIDER_FILE"

            # Test connection
            _TEST_HC=$(printf '%b' "$_PBLOCK" | grep '^healthcheck' | sed 's/^healthcheck = "//;s/"$//')
            if [[ -n "$_TEST_HC" ]]; then
                echo "Testing connection..."
                if bash -c "$_TEST_HC" &>/dev/null; then
                    echo "[done] Healthcheck passed: $_TEST_HC"
                else
                    echo "[warn] Healthcheck failed: $_TEST_HC"
                    echo "       The provider was still added. Fix connectivity and re-test with: providers-health.sh"
                fi
            fi

            # Offer to set as default peer
            read -rp "Set '$_PNAME' as default peer for claude? [y/N]: " _SET_DEFAULT
            if [[ "$_SET_DEFAULT" =~ ^[Yy] ]]; then
                if grep -q '^peer_for\.claude' "$PROVIDER_FILE"; then
                    sed -i.bak "s/^peer_for\.claude = .*/peer_for.claude = \"$_PNAME\"/" "$PROVIDER_FILE"
                    rm -f "${PROVIDER_FILE}.bak"
                else
                    sed -i.bak "/^\[defaults\]/a\\
peer_for.claude = \"$_PNAME\"" "$PROVIDER_FILE"
                    rm -f "${PROVIDER_FILE}.bak"
                fi
                echo "[done] Set default peer for claude to '$_PNAME'"
            fi
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════
# 14. LAUNCHER
# ══════════════════════════════════════════════════════════════

LAUNCHER_SOURCE="$SCRIPT_DIR/claude-code"
LAUNCHER_TARGET="$HOME/.local/bin/claude-code"

if [[ -f "$LAUNCHER_SOURCE" ]]; then
    mkdir -p "$HOME/.local/bin"
    cp "$LAUNCHER_SOURCE" "$LAUNCHER_TARGET"
    chmod +x "$LAUNCHER_TARGET"
    echo "[done] Installed launcher to $LAUNCHER_TARGET"
else
    echo "[skip] Launcher not found at $LAUNCHER_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 14b. SESSION BACKEND PREFERENCE
# ══════════════════════════════════════════════════════════════

LAUNCHER_CONFIG="$CLAUDE_DIR/launcher.json"

echo ""
if [[ ! -t 0 || -n "${CI:-}" ]]; then
    # Non-interactive: use OS-appropriate default
    if [[ "$(uname -s)" == "Darwin" ]]; then
        CHOSEN_BACKEND="cmux"
    else
        CHOSEN_BACKEND="tmux"
    fi
    echo "[auto] Session backend set to '$CHOSEN_BACKEND' (non-interactive)"
else
    echo "Choose your preferred session backend for claude-code:"
    echo ""
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "  1) cmux     — macOS native multiplexer (recommended)"
        echo "  2) tmux     — Mature, widest ecosystem support"
        echo ""
        echo -n "Select [1-2] (default: 1): "
        read -r BACKEND_CHOICE
        case "${BACKEND_CHOICE:-1}" in
            1) CHOSEN_BACKEND="cmux" ;;
            2) CHOSEN_BACKEND="tmux" ;;
            *) CHOSEN_BACKEND="cmux" ;;
        esac
    else
        echo "  1) tmux     — Mature, widest ecosystem support (recommended)"
        echo ""
        echo -n "Select [1] (default: 1): "
        read -r BACKEND_CHOICE
        CHOSEN_BACKEND="tmux"
    fi
fi

# Save preference
if command -v jq &>/dev/null; then
    if [[ -f "$LAUNCHER_CONFIG" ]]; then
        CONTENT=$(jq --arg b "$CHOSEN_BACKEND" '.sessionBackend = $b' "$LAUNCHER_CONFIG")
    else
        CONTENT=$(jq -n --arg b "$CHOSEN_BACKEND" '{sessionBackend: $b}')
    fi
    echo "$CONTENT" > "$LAUNCHER_CONFIG"
else
    echo "{\"sessionBackend\": \"$CHOSEN_BACKEND\"}" > "$LAUNCHER_CONFIG"
fi
echo "[done] Set session backend to '$CHOSEN_BACKEND' in $LAUNCHER_CONFIG"

# Offer to install the chosen backend if missing
install_backend() {
    local backend="$1"
    case "$backend" in
        tmux)
            if command -v tmux &>/dev/null; then
                echo "[ok]   tmux found: $(tmux -V 2>/dev/null || echo 'installed')"
                return
            fi
            echo ""
            echo "       tmux is not installed."
            if command -v brew &>/dev/null; then
                echo -n "       Install tmux now with 'brew install tmux'? [Y/n] "
                read -r REPLY
                if [[ -z "$REPLY" || "$REPLY" =~ ^[Yy]$ ]]; then
                    brew install tmux && echo "[done] tmux installed" \
                        || echo "[FAIL] tmux installation failed. Install manually: brew install tmux"
                else
                    echo "[skip] Install later: brew install tmux"
                fi
            elif command -v apt-get &>/dev/null; then
                echo -n "       Install tmux now with 'sudo apt-get install tmux'? [Y/n] "
                read -r REPLY
                if [[ -z "$REPLY" || "$REPLY" =~ ^[Yy]$ ]]; then
                    sudo apt-get install -y tmux && echo "[done] tmux installed" \
                        || echo "[FAIL] tmux installation failed"
                else
                    echo "[skip] Install later: sudo apt-get install tmux"
                fi
            else
                echo "       Install manually for your platform."
            fi
            ;;
        cmux)
            if command -v cmux &>/dev/null; then
                echo "[ok]   cmux found"
                return
            fi
            # Check if app exists but CLI isn't linked
            for app_path in "/Applications/cmux.app" "$HOME/Applications/cmux.app"; do
                if [[ -d "$app_path" ]]; then
                    cli_path="$app_path/Contents/Resources/bin/cmux"
                    if [[ -x "$cli_path" ]]; then
                        mkdir -p "$HOME/.local/bin"
                        ln -sf "$cli_path" "$HOME/.local/bin/cmux"
                        echo "[done] Linked cmux CLI from $app_path"
                        return
                    fi
                fi
            done
            echo ""
            echo "       cmux is not installed."
            if command -v brew &>/dev/null; then
                echo -n "       Install cmux now with Homebrew? [Y/n] "
                read -r REPLY
                if [[ -z "$REPLY" || "$REPLY" =~ ^[Yy]$ ]]; then
                    brew tap manaflow-ai/cmux && brew install --cask cmux \
                        && echo "[done] cmux installed" \
                        || echo "[FAIL] cmux installation failed"
                else
                    echo "[skip] Install later: brew tap manaflow-ai/cmux && brew install --cask cmux"
                fi
            else
                echo "       Install Homebrew first (https://brew.sh), then: brew install --cask cmux"
            fi
            ;;
    esac
}

install_backend "$CHOSEN_BACKEND"

# ══════════════════════════════════════════════════════════════
# 15. PEER REVIEW SCRIPTS
# ══════════════════════════════════════════════════════════════

REPO_SCRIPTS="$SCRIPT_DIR/../../scripts"
BIN_TARGET="$HOME/.local/bin"

mkdir -p "$BIN_TARGET"

if [[ -f "$REPO_SCRIPTS/peer-review-runner.sh" ]]; then
    cp "$REPO_SCRIPTS/peer-review-runner.sh" "$BIN_TARGET/peer-review-runner.sh"
    chmod +x "$BIN_TARGET/peer-review-runner.sh"
    echo "[done] Installed peer-review-runner.sh to $BIN_TARGET"
else
    echo "[skip] peer-review-runner.sh not found at $REPO_SCRIPTS"
fi

if [[ -f "$REPO_SCRIPTS/providers-health.sh" ]]; then
    cp "$REPO_SCRIPTS/providers-health.sh" "$BIN_TARGET/providers-health.sh"
    chmod +x "$BIN_TARGET/providers-health.sh"
    echo "[done] Installed providers-health.sh to $BIN_TARGET"
else
    echo "[skip] providers-health.sh not found at $REPO_SCRIPTS"
fi

# Install provider adapter scripts
ADAPTER_TARGET="$BIN_TARGET/provider-adapters"
mkdir -p "$ADAPTER_TARGET"
for adapter in "$REPO_SCRIPTS/provider-adapters"/*.sh; do
    if [[ -f "$adapter" ]]; then
        cp "$adapter" "$ADAPTER_TARGET/$(basename "$adapter")"
        chmod +x "$ADAPTER_TARGET/$(basename "$adapter")"
    fi
done
if [[ -d "$REPO_SCRIPTS/provider-adapters" ]] && ls "$REPO_SCRIPTS/provider-adapters"/*.sh &>/dev/null; then
    echo "[done] Installed provider adapters to $ADAPTER_TARGET"
else
    echo "[skip] No provider adapters found at $REPO_SCRIPTS/provider-adapters"
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
echo "Status line installed:"
echo "  - statusline.sh       — model, agent, git, context%, cost, lines, duration"
echo ""
echo "Global hooks installed (active in all projects):"
echo "  - verify-on-stop.sh    — runs tests when Claude finishes"
echo "  - verify-after-edit.sh — runs type checker after source edits"
echo "  - auto-format.sh       — runs formatter after source edits"
echo "  - protect-files.sh     — blocks edits to .env, *.lock, .git/, credentials"
echo "  - protect-git.sh       — blocks git commit/push without explicit user instruction"
echo "  - reinject-context.sh  — re-injects project context on session start"
echo "  - memkernel-recall.sh  — recalls persisted memory on session start"
echo "  - memkernel-pre-compact.sh  — saves a memory checkpoint before compaction"
echo "  - memkernel-post-compact.sh — restores memory context after compaction"
echo "  - peer-review-on-stop.sh — validates review loop completed before session end"
echo "  - notify.sh            — desktop notifications when Claude needs input"
echo ""
echo "Global commands installed:"
echo "  - /review-submit       — start or continue the peer review loop"
echo "  - /review-decide       — resolve a circuit breaker (approve/reject/retry)"
echo "  - /phase-complete      — signal phase completion (validates review passed)"
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
echo "Peer review scripts installed:"
echo "  - peer-review-runner.sh  — executes peer provider and writes artifacts"
echo "  - providers-health.sh    — checks availability of configured providers"
echo ""
echo "Rules installed:"
echo "  - ~/.claude/rules/          — 4 global rules (auto-loaded every session)"
echo "  - ~/.claude/skills/          — 15 on-demand skills (SKILL.md format, loaded by agents)"
echo ""
echo "Each project now includes:"
echo "  - CLAUDE.md with stack, conventions, and Agent Team config"
echo "  - /project:team-review command for full team review"
echo "  - Role-specific delegation prompts for the Agent tool"
echo ""
echo "Remember to customize each project's CLAUDE.md after init!"
echo "Look for ← UPDATE comments for project-specific values."
echo ""
