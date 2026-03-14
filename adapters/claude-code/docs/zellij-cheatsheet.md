# Zellij Cheat Sheet for Claude Code

Quick reference for using zellij as the session backend for `claude-code`.

## Setup

```bash
# Install zellij
brew install zellij

# Sync launcher (picks up zellij support)
bash ~/dev/repo/code-copilot-team/adapters/claude-code/setup.sh --sync

# Or run full setup with backend picker
bash ~/dev/repo/code-copilot-team/adapters/claude-code/setup.sh
```

## Launching

```bash
# Auto-detect (zellij preferred if installed)
claude-code ~/projects/my-app

# Explicit zellij
claude-code --shell zellij ~/projects/my-app

# Force tmux/cmux instead
claude-code --shell tmux ~/projects/my-app
claude-code --shell cmux ~/projects/my-app
```

## Key Bindings (Default)

### Session Management

| Action | Keys |
|--------|------|
| Session manager | `Ctrl+O`, `W` |
| Detach | `Ctrl+O`, `D` |
| Rename session | `Ctrl+O`, `,` |

### Pane Management

| Action | Keys |
|--------|------|
| New pane (down) | `Ctrl+P`, `D` |
| New pane (right) | `Ctrl+P`, `R` |
| New floating pane | `Ctrl+P`, `W` |
| Close pane | `Ctrl+P`, `X` |
| Toggle fullscreen | `Ctrl+P`, `F` |
| Move focus | `Ctrl+P`, then arrow keys |
| Resize | `Ctrl+N`, then arrow keys |

### Tab Management

| Action | Keys |
|--------|------|
| New tab | `Ctrl+T`, `N` |
| Close tab | `Ctrl+T`, `X` |
| Rename tab | `Ctrl+T`, `R` |
| Next/prev tab | `Ctrl+T`, then arrow keys |
| Go to tab N | `Ctrl+T`, `1-9` |

### Scrolling & Search

| Action | Keys |
|--------|------|
| Enter scroll mode | `Ctrl+S` |
| Search in scroll | `Ctrl+S`, `S` |
| Page up/down | `PgUp` / `PgDn` (in scroll mode) |
| Exit scroll mode | `Esc` or `Q` |

### Modes

| Action | Keys |
|--------|------|
| Lock mode (passthrough) | `Ctrl+G` |
| Normal mode | `Esc` or `Enter` (from any mode) |

## Session Management from Terminal

```bash
# List sessions
zellij list-sessions

# Attach to existing
zellij attach <session-name>

# Delete session
zellij delete-session <session-name>

# Delete all sessions
zellij delete-all-sessions
```

## Configuration

Zellij config lives at `~/.config/zellij/config.kdl`.

```kdl
// Example: common customizations
theme "catppuccin-mocha"
default_shell "/bin/zsh"
scrollback_lines_to_serialize 10000
copy_on_select true
```

Theme options: `default`, `catppuccin-mocha`, `catppuccin-latte`, `dracula`, `nord`, `gruvbox-dark`, `gruvbox-light`, `tokyo-night`, `tokyo-night-storm`, `one-half-dark`, `solarized-dark`

## How claude-code Uses Zellij

- **First pane**: Runs Claude Code with session logging
- **New panes**: Normal login shell (not Claude)
- **Detach/reattach**: Session persists — `claude-code` reattaches automatically
- **Inside zellij**: Running `claude-code` again launches Claude directly (no nesting)
- **Your config preserved**: Keybindings, theme, plugins all work normally

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Unsupported shell backend 'zellij'` | Run `setup.sh --sync` to update the launcher |
| Zellij not found after install | Ensure `~/.local/bin` or brew's bin is in `$PATH` |
| Claude launches in new panes | Delete `/tmp/claude-zellij-*.sh` and `/tmp/.claude-zellij-*.mark` |
| Layout doesn't resize | Press `Ctrl+L` to force redraw |
| Shift+Enter not working | Works out of the box in zellij (kitty keyboard protocol) |
| Want vim keybindings | Add `keybinds clear-defaults=true { ... }` to config.kdl |
