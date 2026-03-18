# Recommended MCP Servers for Claude Code

MCP (Model Context Protocol) servers extend Claude Code with external capabilities — databases, documentation, file systems, and custom tools.

## Recommended Servers

### Context7

**Purpose:** Live library documentation lookup. Fetches current docs for any library, bypassing Claude's knowledge cutoff.

```bash
claude mcp add --scope user --transport stdio context7 -- npx -y @context7/mcp@latest
```

**When to use:** When working with rapidly-evolving libraries (LangChain, Next.js, etc.) where API changes frequently.

### PostgreSQL MCP

**Purpose:** Direct database introspection — schema browsing, query execution, migration validation.

```bash
claude mcp add --scope project --transport stdio postgres -- \
  npx -y @anthropic/mcp-postgres "$DATABASE_URL"
```

**When to use:** Projects with PostgreSQL databases. Enables Claude to inspect schemas, validate migrations, and write accurate queries.

### Filesystem MCP

**Purpose:** Scoped file access outside the working directory — read config files, logs, or shared resources.

```bash
claude mcp add --scope project --transport stdio filesystem -- \
  npx -y @anthropic/mcp-filesystem /path/to/allowed/directory
```

**When to use:** When Claude needs access to files outside the project root (e.g., shared config, monorepo siblings).

### Playwright (Browser Automation)

**Purpose:** Browser automation for debugging, visual testing, and e2e validation in web projects.

**Recommended: Playwright CLI** (token-efficient, designed for coding agents with shell access):

```bash
# Install (or use setup.sh --playwright)
npm install -g @playwright/cli@latest
playwright-cli install --skills

# Usage
playwright-cli open http://localhost:<port>
playwright-cli click "Login button"
playwright-cli screenshot
```

**Alternative: Playwright MCP** (for Docker/CI environments without shell access):

```bash
claude mcp add --scope project --transport stdio playwright -- \
  npx -y @playwright/mcp@latest --headless
```

Or via Docker:

```bash
claude mcp add --scope project --transport stdio playwright -- \
  docker run -i --rm --init mcr.microsoft.com/playwright/mcp
```

**When to use:** Web projects (`web-static`, `web-dynamic`, any project with a browser UI). Use CLI for local development, MCP for containerized environments.

## When to Use MCP vs Built-in Tools

| Capability | Built-in Tool | MCP Server | Prefer |
|---|---|---|---|
| Read project files | Read, Glob, Grep | Filesystem MCP | **Built-in** (already scoped) |
| Search the web | WebSearch, WebFetch | — | **Built-in** |
| Library docs lookup | WebFetch (manual URL) | Context7 | **MCP** (structured, current) |
| Database schema | Bash(psql ...) | PostgreSQL MCP | **MCP** (safer, structured) |
| Session continuity | `CLAUDE.md`, specs, phase recaps | — | **Built-in** |
| Files outside project | Bash(cat ...) | Filesystem MCP | **MCP** (scoped, auditable) |
| Browser automation | Bash(npx playwright test) | Playwright CLI / MCP | **CLI** (token-efficient) |

## Scope Guidance

| Scope | Meaning | Use For |
|---|---|---|
| `--scope user` | Available in all projects | Context7 (general-purpose tools) |
| `--scope project` | Only available in this project | PostgreSQL MCP, Filesystem MCP, Playwright MCP (project-specific) |

## Managing MCP Servers

```bash
claude mcp list                    # list installed servers
claude mcp remove <name>           # remove a server
/mcp                               # manage from inside a session
```

## Tips

- Keep the number of MCP servers small — each adds startup latency and context overhead.
- Use `--scope project` for databases and sensitive resources to avoid leaking access across projects.
- Test MCP servers in a fresh session after installing to verify they connect.
- If an MCP server is slow to start, check that the underlying service (database, API) is running.
