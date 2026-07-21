List the custom subagents installed on this machine and in this project — the replacement for the built-in `/agents` command removed from recent Claude Code versions.

Note: built-in agent types (e.g. `general-purpose`, `Explore`) and plugin-supplied agents have no file in these directories and are not covered by this roster.

Usage: `/list-agents [name]`

## Steps

### 1. Collect agent definitions

Scan both scopes:

- Global: `~/.claude/agents/*.md`
- Project: `.claude/agents/*.md` (relative to the project root)

Read each file's YAML frontmatter: `name`, `description`, `tools`, `model`. If `name` is missing, use the filename without `.md`.

### 2. Detail view (with argument)

If `[name]` is given, show only that agent in full: scope, file path, description, model, tools, and a short excerpt (first ~20 lines) of its system prompt body. If nothing matches, say so and list the available names.

### 3. Roster view (no argument)

Print one table per scope, project scope first:

| Agent | Model | Tools | Description |
|-------|-------|-------|-------------|

- A project-level agent overrides a global agent with the same name — mark the shadowed global entry as `(shadowed)`.
- If a scope's directory is missing or empty, say so on one line; do not treat it as an error.
- If no agents are found in either scope, explain that this machine has no agent setup installed and point to `adapters/claude-code/setup.sh` (fresh install) or `setup.sh --sync` (update) in the code-copilot-team repo, which installs the standard team (research, plan, build, review, and the utility agents).

### 4. Read-only

Do not create, edit, or delete any agent files. This command only reports.
