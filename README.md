# Code Copilot Team

Reusable, opinionated configuration for AI-assisted coding with multi-agent team delegation. Ships with templates for ML/AI, Enterprise Java, and Web projects.

Built for **Claude Code** as the reference implementation, with portable conventions for Cursor, GitHub Copilot, Windsurf, Aider, and local LLMs.

---

## What You Get

- **Global rules** (`~/.claude/rules/`) — coding standards, safety guards, token efficiency, agent team protocol, and cross-tool conventions that load automatically in every session.
- **6 project templates** — pre-configured `CLAUDE.md` files with stack-specific conventions, slash commands, and agent team roles for each project archetype.
- **Three-phase workflow** — Plan (single agent, high-capability model) → Build (team delegation, fast model) → Review (single agent, high-capability model).
- **tmux launcher** (`claude-code`) — per-project sessions with git context display.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/gosha70/code-copilot-team.git
cd code-copilot-team

# 2. Run the one-time setup (creates ~/.claude/ config + templates)
chmod +x claude_code/claude-setup.sh
./claude_code/claude-setup.sh

# 3. (Optional) Install the tmux launcher
cp claude_code/claude-code /usr/local/bin/
chmod +x /usr/local/bin/claude-code
```

That's it. Every Claude Code session now picks up the global rules automatically.

## Start a New Project

```bash
# Initialize from a template
claude-code init ml-rag ~/projects/my-rag-app

# Start a Claude session in the project
claude-code ~/projects/my-rag-app
```

## Start in an Existing Project

```bash
# Just point the launcher at it — global rules load automatically
claude-code ~/projects/existing-api
```

## Available Templates

| Template | Stack | Agent Team |
|---|---|---|
| `ml-rag` | Python · FAISS/Chroma · Neo4j/NetworkX | Team Lead, RAG Engineer, KG Engineer, Data Analyst, QA |
| `ml-langchain` | Python · LangChain/LangGraph/LangSmith | Team Lead, Agent Developer, Integration Engineer, QA & Eval |
| `ml-n8n` | Python · n8n · REST/webhooks | Team Lead, Workflow Designer, Python Developer, QA & DevOps |
| `java-enterprise` | Spring Boot · Kafka · GraphQL · React | Team Lead, Backend Dev, Frontend Dev, Data & Messaging, QA, DevOps |
| `web-static` | Astro/Next.js/Hugo · Tailwind | Team Lead, Frontend Dev, Content & SEO, QA |
| `web-dynamic` | Next.js/Remix · Node/Python · PostgreSQL | Team Lead, Frontend Dev, Backend Dev, QA, DevOps |

## How Configuration Layers Work

```
~/.claude/CLAUDE.md              ← Global agent manifest (base)
~/.claude/rules/*.md             ← Global modular rules (always loaded)
  ├── coding-standards.md
  ├── safety.md
  ├── token-efficiency.md
  ├── copilot-conventions.md
  └── agent-team-protocol.md
./CLAUDE.md                      ← Project-level (overrides global)
./.claude/commands/*.md          ← Project slash commands
./CLAUDE.local.md                ← Personal overrides (gitignored)
```

Project-level rules override global rules. More specific always wins.

## Three-Phase Workflow

| Phase | Model | Effort | Delegation | What Happens |
|---|---|---|---|---|
| **Plan** | Opus (highest) | High | None | Read codebase, design approach, get user approval |
| **Build** | Sonnet (fast) | Medium | Yes | Team Lead delegates to specialist sub-agents |
| **Review** | Opus (highest) | High | None | Holistic review, run tests, verify consistency |

Planning must stay in one mind — sub-agents only see fragments and can't reason about the whole system. Delegation only happens during Build.

## Porting to Other Tools

The conventions in `~/.claude/rules/copilot-conventions.md` are tool-agnostic:

| Tool | Config file |
|---|---|
| **Cursor** | `.cursorrules` |
| **GitHub Copilot** | `.github/copilot-instructions.md` |
| **Windsurf** | `.windsurfrules` |
| **Aider** | `.aider.conf.yml` or `CONVENTIONS.md` |
| **Local LLMs** | System prompt or context file |

## Repo Structure

```
README.md                                ← You are here
LICENSE                                  ← MIT
claude_code/
  claude-code                            ← tmux launcher script
  claude-setup.sh                        ← One-time setup (creates ~/.claude/)
  .claude/
    CLAUDE.md                            ← Global agent manifest (reference copy)
    rules/
      coding-standards.md                ← SOLID, quality gates, prohibited patterns
      safety.md                          ← Destructive action guards, secrets policy
      token-efficiency.md                ← Diff-over-rewrite, context economy
      copilot-conventions.md             ← Cross-tool conventions
      agent-team-protocol.md             ← Three-phase workflow, delegation rules
  docs/
    claude-code-setup-cookbook.md         ← Detailed cookbook
    claude-config-guide.md               ← Configuration reference
    session-management.md                ← Session commands cheat sheet
```

## Documentation

- **[Setup Cookbook](claude_code/docs/claude-code-setup-cookbook.md)** — deep-dive into every configuration option
- **[Config Guide](claude_code/docs/claude-config-guide.md)** — templates, agent teams, and workflow reference
- **[Session Management](claude_code/docs/session-management.md)** — commands cheat sheet for daily use

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome for new templates, rule improvements, and ports to other tools.

## License

[MIT](LICENSE)
