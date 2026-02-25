# Recommended MCP Servers for Claude Code

MCP (Model Context Protocol) servers extend Claude Code with external capabilities — databases, documentation, file systems, and custom tools.

## Recommended Servers

### Aline (GCC Memory)

**Purpose:** Git Context Controller — persistent memory across sessions via git-aware context tracking.

```bash
# Install (already done if you ran setup.sh --gcc)
claude mcp add --scope user --transport stdio aline -- npx -y aline-ai@latest
```

**When to use:** Every project. Aline provides session continuity by tracking what Claude has learned about your codebase.

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

## When to Use MCP vs Built-in Tools

| Capability | Built-in Tool | MCP Server | Prefer |
|---|---|---|---|
| Read project files | Read, Glob, Grep | Filesystem MCP | **Built-in** (already scoped) |
| Search the web | WebSearch, WebFetch | — | **Built-in** |
| Library docs lookup | WebFetch (manual URL) | Context7 | **MCP** (structured, current) |
| Database schema | Bash(psql ...) | PostgreSQL MCP | **MCP** (safer, structured) |
| Session memory | Auto-memory files | Aline | **MCP** (richer context) |
| Files outside project | Bash(cat ...) | Filesystem MCP | **MCP** (scoped, auditable) |

## Scope Guidance

| Scope | Meaning | Use For |
|---|---|---|
| `--scope user` | Available in all projects | Aline, Context7 (general-purpose tools) |
| `--scope project` | Only available in this project | PostgreSQL MCP, Filesystem MCP (project-specific) |

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
