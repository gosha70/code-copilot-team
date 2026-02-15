# Generic AI Copilot Setup (Mac Version)

Reference guide for the global agentic coding environment configured on this machine. Applies to Claude Code, and provides portable conventions for Cursor, GitHub Copilot, and local LLMs.

---

## 1\. What's Installed and Where

### Global Configuration (applies to every project, every session)

\~/.claude/

├── CLAUDE.md                          \# Global agent manifest (auto-loaded)

├── rules/

│   ├── coding-standards.md            \# SOLID, quality gates, prohibited patterns

│   ├── safety.md                      \# Destructive action guards, secrets policy

│   ├── token-efficiency.md            \# Diff-over-rewrite, context economy

│   └── copilot-conventions.md         \# Cross-tool conventions, project structure

├── settings.json                      \# Global permissions (pytest, grep, config)

├── settings.local.json                \# Local overrides (MCP tools, docker)

└── mcp\_settings.json                  \# MCP servers (docker-mcp gateway)

### How Loading Works

| File | Scope | Auto-loaded? | Priority |
| :---- | :---- | :---- | :---- |
| `~/.claude/CLAUDE.md` | All projects | Yes | User-level (base) |
| `~/.claude/rules/*.md` | All projects | Yes | User-level (modular) |
| `.claude/CLAUDE.md` or `./CLAUDE.md` | This project | Yes | Project-level (overrides user) |
| `.claude/rules/*.md` | This project | Yes | Project-level (modular) |
| `./CLAUDE.local.md` | This project, you only | Yes | Personal project (gitignored) |
| `~/.claude/projects/<proj>/memory/` | This project, you only | First 200 lines | Auto-memory |

**Precedence**: project-level rules override global rules. More specific always wins.

---

## 2\. What the Global Rules Enforce

### Agent Behaviour (`~/.claude/CLAUDE.md`)

- Read before writing — understand existing code first.  
- Minimal scope — only change what was requested.  
- Show diffs, not rewrites.  
- Confirm destructive actions (rm, DROP, push \--force, deploy, reset \--hard).  
- No silent changes — explain every modification.  
- Sanitize output — strip secrets, tokens, PII.  
- Ask when uncertain.  
- Do **not** add unsolicited features, refactors, docstrings, comments, or TODOs.

### Coding Standards (`~/.claude/rules/coding-standards.md`)

- SOLID, Clean Architecture, Pragmatic Programmer.  
- Composition over inheritance. One function \= one job.  
- Quality gates: 0 lint errors, \>= 80% coverage, no dead code, no secrets.  
- Style: language-standard indentation, 100 char lines, conventional naming.  
- Prohibited: magic numbers, wildcard imports, bare except, print debugging, SQL concatenation, hardcoded JSON/XML.  
- Tests: deterministic, descriptive names, mocked externals.  
- Errors: specific types, fail fast, log with context, never swallow.

### Safety (`~/.claude/rules/safety.md`)

- Confirm before: rm \-rf, DROP, TRUNCATE, reset \--hard, push \--force, deploy, production data changes.  
- Never hardcode secrets. Never commit .env. Flag secrets found in code.  
- Validate/sanitize all external inputs. Parameterized queries only.  
- Review dependencies before adding (license, security, maintenance).

### Token Efficiency (`~/.claude/rules/token-efficiency.md`)

- Reference files by path — don't re-send large blocks.  
- Use /compact when context grows.  
- Load only relevant file sections.  
- One task per session. Flush context between unrelated tasks.  
- Return diffs, not full rewrites. Concise bullets over paragraphs.

### Cross-Copilot Conventions (`~/.claude/rules/copilot-conventions.md`)

- Read before write. Minimal changes. Show diffs. Test everything. Ask when uncertain.  
- Match existing style. Don't touch untouched code.  
- Git: imperative mood commits, one change per commit, feature/fix/chore/docs branches.  
- APIs: modular, testable, versioned, consistent errors, rate-limited.  
- New project layout: /src, /tests, /doc\_internal (ARCHITECTURE.md, OPERATIONAL\_RULES.md, CONTEXT.md, HISTORY.md).

---

## 3\. Session Management — Cheat Sheet

### Starting a Session

| Situation | Command | Notes |
| :---- | :---- | :---- |
| New task | `claude` | Global rules auto-load. Nothing else needed. |
| Continue last session | `claude --continue` or `claude -c` | Restores full conversation history |
| Resume named session | `claude --resume "name"` or `claude -r "name"` | Pick up by name or ID |
| Interactive resume | `/resume` (inside Claude) | Shows session picker |
| Fork (try alternative) | `claude -c --fork-session` | Branches off, original preserved |

**You do NOT need to run `/init` every time.** `/init` is a one-time command to scaffold a project-level CLAUDE.md for a new repo. Your global rules already cover everything generic.

### During a Long Session

| Action | Command | When |
| :---- | :---- | :---- |
| Check context usage | `/context` | Periodically — shows visual grid of what's consuming space |
| Compress history | `/compact` or `/compact focus on X` | When context is getting heavy |
| Check token spend | `/cost` | When you want to see session spend |
| Name your session | `/rename "descriptive-name"` | Before switching tasks or ending work |
| View loaded memory | `/memory` | To review/edit what Claude has loaded |
| Rewind a mistake | `Esc + Esc` or `/rewind` | To undo file changes or roll back conversation |

### Switching Tasks in Same Terminal

/rename "previous-work-name"     ← name what you were doing

/clear                           ← fresh context, global rules reload

(start new task)                 ← clean slate

### Ending a Session

"save memory about X"            ← tell Claude to remember key decisions

/rename "descriptive-name"       ← name it for later resumption

### What's Automatic (you don't need to ask)

| What | Stored where | Automatic? |
| :---- | :---- | :---- |
| Conversation history | Internal session storage | Yes — resume with `--continue` |
| File edit checkpoints | Internal | Yes — rewind with `Esc+Esc` |
| Auto-memory (patterns, preferences) | `~/.claude/projects/<project>/memory/` | Yes (if enabled) |
| Global rules loading | `~/.claude/CLAUDE.md` \+ `~/.claude/rules/` | Yes — every session |

### What's NOT Automatic

- **Project-level session log** (`doc_internal/HISTORY.md`): Add to project CLAUDE.md if you want it:  
    
  Before ending a session, append a summary to doc\_internal/HISTORY.md.  
    
- **Explicit "remember this" requests**: Say `"remember that we use pnpm"` if you want Claude to save something to auto-memory.

---

## 4\. Per-Project Setup (When Needed)

When you start a new project that needs its own rules on top of the globals:

### Option A: Quick — Just a CLAUDE.md

Create `./CLAUDE.md` or `./.claude/CLAUDE.md` in the repo root:

\# Project: my-api

\- Language: Python 3.12

\- Framework: FastAPI

\- Test runner: pytest

\- Linter: ruff

\- Package manager: uv

\#\# Commands

\- Run tests: \`uv run pytest\`

\- Lint: \`uv run ruff check .\`

\- Dev server: \`uv run uvicorn src.main:app \--reload\`

\#\# Session Protocol

Before ending a session, append a summary to doc\_internal/HISTORY.md.

### Option B: Full Structure (for larger projects)

/src

/tests

/doc\_internal

  ARCHITECTURE.md        ← system design, ADRs

  OPERATIONAL\_RULES.md   ← project-specific coding rules

  CONTEXT.md             ← session context summaries

  HISTORY.md             ← timestamped session log

.gitignore

CLAUDE.md                ← project manifest

Add to `.gitignore`:

doc\_internal/

.env

### Option C: Personal Project Overrides

Create `./CLAUDE.local.md` (auto-gitignored):

\- My dev database: mysql://localhost:3306/my\_dev\_db

\- Preferred test command: pytest \-x \--tb=short

---

## 5\. Useful Slash Commands Reference

| Command | Purpose |
| :---- | :---- |
| `/init` | One-time: scaffold project CLAUDE.md |
| `/memory` | View/edit loaded memory files |
| `/compact [focus]` | Compress context with optional focus |
| `/context` | Visual context usage grid |
| `/cost` | Token usage for this session |
| `/clear` | Wipe conversation, keep session |
| `/rename "name"` | Name session for later resume |
| `/resume [name]` | Resume a previous session |
| `/rewind` | Undo file changes or conversation |
| `/config` | Open settings UI |
| `/status` | Version, model, account info |
| `/doctor` | Health check on Claude Code install |
| `/model` | Switch AI model |
| `/mcp` | Manage MCP server connections |
| `/export [file]` | Export conversation to file or clipboard |
| `/plan` | Enter plan mode (or use Shift+Tab twice) |
| `/stats` | Daily usage and session history |

---

## 6\. Porting to Other AI Tools

The conventions in `~/.claude/rules/copilot-conventions.md` are tool-agnostic. To reuse them:

| Tool | Where to put shared rules |
| :---- | :---- |
| **Cursor** | `.cursorrules` in repo root (copy relevant sections) |
| **GitHub Copilot** | `.github/copilot-instructions.md` in repo root |
| **Windsurf** | `.windsurfrules` in repo root |
| **Aider** | `.aider.conf.yml` or `CONVENTIONS.md` referenced in config |
| **Local LLMs** | System prompt or prepended context file |

The global `~/.claude/rules/` files serve as the single source of truth. Copy relevant sections to tool-specific files as needed.

---

## 7\. Current Permissions & MCP Servers

### Global Permissions (`~/.claude/settings.json`)

Allow: claude config, python \-m py\_compile, grep, python3 \-m pytest

### Local Permissions (`~/.claude/settings.local.json`)

Allow: claude mcp list/exec, docker mcp tools ls/call

### MCP Servers (`~/.claude/mcp_settings.json`)

docker-mcp: docker mcp gateway run

---

## 8\. Maintenance

- **Review rules quarterly**: Re-read `~/.claude/rules/` and prune anything stale.  
- **Update after major tool upgrades**: Check `/doctor` after Claude Code updates.  
- **Auto-memory cleanup**: Use `/memory` to review and trim auto-saved memories per project.  
- **Check `/cost` and `/stats`**: Monitor token usage trends over time.

