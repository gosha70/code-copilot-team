# Install Options

Every install path, for every tool. The shortest one is the
[Quick Start](../README.md#quick-start); this page is the rest: per-adapter
flags, what each writes and where, the plugin and LSP paths, and how to
install more than one adapter.

```bash
# 1. Clone the latest stable release (drop --branch for unreleased master)
git clone --branch v1.1.0 https://github.com/gosha70/code-copilot-team.git
cd code-copilot-team

# 2. Install for your tool(s)
./scripts/setup.sh --claude-code                    # Claude Code → ~/.claude/
./scripts/setup.sh --pi                             # Pi (enforced) → ~/.code-copilot-team/pi/
./scripts/setup.sh --codex                          # OpenAI Codex → ~/.codex/
./scripts/setup.sh --cursor ~/my-project            # Cursor → project/.cursor/
./scripts/setup.sh --github-copilot ~/my-project    # GH Copilot → project/.github/
./scripts/setup.sh --windsurf ~/my-project          # Windsurf → project/.windsurf/
./scripts/setup.sh --aider ~/my-project             # Aider → project/CONVENTIONS.md

# Or install everything at once
./scripts/setup.sh --all ~/my-project

# Re-sync after pulling repo updates
git pull && ./scripts/setup.sh --sync --claude-code
```

## Reading the docs on the web

The same documentation is published as a site from the default branch. Its
address is the repository's homepage link once GitHub Pages is switched on
(Settings → Pages → Source: **GitHub Actions**); until then, read the guides
here in the repository or in the Studio's Learn tab, which serve the same
files.

## What each adapter writes

| Tool | Adapter output | Install location |
|---|---|---|
| **Claude Code** | agents, hooks, commands, settings | `~/.claude/` (global) |
| **Pi** | enforcement runtime extension + skills/prompts | `pi install` (advisory) / `pi-code` (enforced) |
| **OpenAI Codex** | `AGENTS.md` + 5 skills | `~/.codex/` (global) |
| **Cursor** | `.mdc` files with frontmatter | `project/.cursor/rules/` |
| **GitHub Copilot** | `copilot-instructions.md` + per-rule instructions | `project/.github/` |
| **Windsurf** | `rules.md` | `project/.windsurf/rules/` |
| **Aider** | `CONVENTIONS.md` | `project/` |

Which of them can *enforce* the contract rather than merely read it is in the
README's [Choose your tool](../README.md#choose-your-tool) table, generated
from the feature catalog.

The legacy `./claude_code/claude-setup.sh` path still works — it delegates to the adapter.

After `git pull`, run `--sync` to regenerate configs and re-install.

### Alternative: Install as a Claude Code Plugin

For Claude Code users who prefer the plugin system over `setup.sh`:

```bash
# Add the CCT marketplace (one-time)
/plugin marketplace add gosha70/code-copilot-team

# Install the hooks plugin
/plugin install code-copilot-team@code-copilot-team
```

This installs the same hooks (file protection, auto-format, type verification, context re-injection, git safety, notifications) as `setup.sh`, but managed through Claude Code's plugin system. Update installed plugins with `/plugin marketplace update`. The plugin does not include peer-review or memkernel hooks — those are CCT-pipeline-specific and remain in the `setup.sh` path.

Both install paths coexist. Use `setup.sh` for the full install (skills, agents, templates, hooks, peer review) or the plugin for hooks only.

### Recommended: Install LSP Plugins (Claude Code)

For continuous type-error feedback during edits, install the appropriate code-intelligence plugin. Each requires its language-server binary on `$PATH`:

```bash
# Install the language server first, then the plugin:
pip install pyright && /plugin install pyright-lsp@claude-plugins-official           # Python
npm i -g typescript-language-server typescript && /plugin install typescript-lsp@claude-plugins-official  # TypeScript
go install golang.org/x/tools/gopls@latest && /plugin install gopls-lsp@claude-plugins-official  # Go
```

These provide native LSP diagnostics and are preferred over the bundled `verify-after-edit.sh` hook. The hook remains as a fallback for languages without an LSP plugin. See the [official plugin catalog](https://claude.com/plugins) for all available languages.
