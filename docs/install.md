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

The same documentation is published as a searchable site at
<https://gosha70.github.io/code-copilot-team/>, built from `master` on every
change to the docs. The guides are equally readable here in the repository and
in the Studio's Learn tab — all three serve the same files.

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

# Install the plugin
/plugin install code-copilot-team@code-copilot-team
```

The plugin is the quick path; `setup.sh` is the full harness. The plugin's contents are generated from the same sources `setup.sh` installs (`scripts/generate.sh`), so the two never drift apart. Update installed plugins with `/plugin marketplace update`.

**What the plugin installs**

- All 24 skills, the 14 agents and the 14 commands, plus the SDD templates and the `review-decide` helper the commands and agents read.
- The same seven hooks as `setup.sh`: file protection, git safety, auto-format, type verification, test-on-stop, context re-injection, notifications.
- Plugin components are namespaced: commands are `/code-copilot-team:shape`, agents are `code-copilot-team:build`. Asking for "the build agent" by its plain name still reaches it.
- Commands that read a template read it from the plugin's own directory, which is outside your project, so Claude Code's usual permission check for reads outside the project applies.

**What only `setup.sh` gives you**

- **Always-loaded rules.** A plugin cannot ship instructions that load into every session. The six skills `setup.sh` installs as always-on rules (coding-standards, copilot-conventions, copyright-headers, origin-confirmation, safety, wiki-first-query) ship in the plugin as ordinary skills: they load when relevant, not always. The two protect hooks enforce file and git safety either way.
- The global `CLAUDE.md` manifest, the `claude-code` launcher, the status line, and the templates for new projects.
- The peer-review and memkernel hooks — those are CCT-pipeline-specific.

**Using both**

Both install paths coexist. Claude Code does not merge same-named components: you will see `/shape` and `/code-copilot-team:shape`, `build` and `code-copilot-team:build`, side by side, and they behave the same. The cost is that every skill and agent is listed twice in context (about 1,500 extra tokens). The plugin's copies of the five non-safety hooks step aside when `setup.sh`'s copies are installed, so formatting, verification and notifications run once. The two protect hooks never step aside: with both installs they run twice, which costs a duplicate block message and nothing else.

### Recommended: Install LSP Plugins (Claude Code)

For continuous type-error feedback during edits, install the appropriate code-intelligence plugin. Each requires its language-server binary on `$PATH`:

```bash
# Install the language server first, then the plugin:
pip install pyright && /plugin install pyright-lsp@claude-plugins-official           # Python
npm i -g typescript-language-server typescript && /plugin install typescript-lsp@claude-plugins-official  # TypeScript
go install golang.org/x/tools/gopls@latest && /plugin install gopls-lsp@claude-plugins-official  # Go
```

These provide native LSP diagnostics and are preferred over the bundled `verify-after-edit.sh` hook. The hook remains as a fallback for languages without an LSP plugin. See the [official plugin catalog](https://claude.com/plugins) for all available languages.
