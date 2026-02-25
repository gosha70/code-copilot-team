# Session Management — Cheat Sheet

Daily reference for managing Claude Code sessions effectively.

## Starting a Session

| Situation | Command | Notes |
|---|---|---|
| New task | `claude` | Global rules auto-load |
| Continue last session | `claude --continue` or `claude -c` | Restores full history |
| Resume named session | `claude --resume "name"` or `claude -r "name"` | Pick up by name or ID |
| Interactive resume | `/resume` (inside Claude) | Shows session picker |
| Fork (try alternative) | `claude -c --fork-session` | Branches off, original preserved |
| Use the tmux launcher | `claude-code ~/projects/my-app` | Per-project tmux session with git context |

You do **not** need to run `/init` every time. `/init` is a one-time command to scaffold a project-level CLAUDE.md for a new repo. Global rules already cover everything generic.

## During a Long Session

| Action | Command | When |
|---|---|---|
| Check context usage | `/context` | Periodically — shows visual grid |
| Compress history | `/compact` or `/compact focus on X` | When context is getting heavy |
| Check token spend | `/cost` | Monitor session spend |
| Name your session | `/rename "descriptive-name"` | Before switching tasks or ending |
| View loaded memory | `/memory` | Review/edit what Claude has loaded |
| Rewind a mistake | `Esc + Esc` or `/rewind` | Undo file changes or roll back |

## Switching Tasks in Same Terminal

```
/rename "previous-work-name"     ← name what you were doing
/clear                           ← fresh context, global rules reload
(start new task)                 ← clean slate
```

## Ending a Session

```
"save memory about X"            ← tell Claude to remember key decisions
/rename "descriptive-name"       ← name it for later resumption
```

## What's Automatic

| What | Stored where | Automatic? |
|---|---|---|
| Conversation history | Internal session storage | Yes — resume with `--continue` |
| File edit checkpoints | Internal | Yes — rewind with `Esc+Esc` |
| Auto-memory (patterns) | `~/.claude/projects/<project>/memory/` | Yes (if enabled) |
| Global rules loading | `~/.claude/CLAUDE.md` + `~/.claude/rules/` | Yes — every session |

## What's NOT Automatic

- **Project session log** (`doc_internal/HISTORY.md`): Add to your project CLAUDE.md if you want it.
- **Explicit memory requests**: Say `"remember that we use pnpm"` to save to auto-memory.

## All Slash Commands

| Command | Purpose |
|---|---|
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
| `/doctor` | Health check on install |
| `/model` | Switch AI model |
| `/mcp` | Manage MCP server connections |
| `/export [file]` | Export conversation to file or clipboard |
| `/plan` | Enter plan mode (or `Shift+Tab` twice) |
| `/stats` | Daily usage and session history |
