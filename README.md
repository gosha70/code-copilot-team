# Code Copilot Team

Reusable, opinionated configuration for AI-assisted coding with multi-agent team delegation. Ships with templates for ML/AI, Enterprise Java, and Web projects.

Built for **Claude Code** as the reference implementation, with portable conventions for Cursor, GitHub Copilot, Windsurf, Aider, and local LLMs.

> 📖 **Deep dive:** [Stop Fighting AI Agents and Build a Reusable Multi-Agent Dev Environment](https://www.linkedin.com/pulse/stop-fighting-ai-agents-build-reusable-multi-agent-dev-george-ivan-mxwbe) — the full story behind this project, lessons learned from 13+ real build sessions, and why every rule exists.

---

## Why This Exists

Every rule in this repo is failure-driven — it exists because we hit the specific failure it prevents, often more than once. After analyzing 13 sessions of a real project build, we identified six recurring patterns: dependency breaks, agents ignoring conventions, context window exhaustion, schema drift during parallel builds, agents not asking clarifying questions, and commit granularity issues. This setup prevents all of them.

## What You Get

- **Layered rules** — 3 global rules (`~/.claude/rules/`) auto-load every session; 9 on-demand rules (`~/.claude/rules-library/`) loaded by phase agents when needed.
- **Phase agents** (`~/.claude/agents/`) — 4 phase agents (research, plan, build, review) plus 5 utility agents (code-simplifier, doc-writer, phase-recap, security-review, verify-app).
- **Hooks** (`~/.claude/hooks/`) — 6 lifecycle scripts: test verification, type checking, auto-format, file protection, context re-injection, and desktop notifications. Auto-detect your project's stack.
- **7 project templates** — pre-configured `CLAUDE.md` files with stack-specific conventions, slash commands, and agent team roles for each project archetype.
- **Four-phase workflow** — Research → Plan → Build → Review. Plus **Ralph Loop** for single-agent autonomous iteration.
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

# Re-sync after pulling repo updates
git pull && ./claude_code/claude-setup.sh --sync
```

That's it. Every Claude Code session now picks up the global rules and hooks automatically. After `git pull`, run `claude-setup.sh --sync` to update your `~/.claude/` with any new or changed files.

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
| `ml-app` | Python · FastAPI · LiteLLM · Next.js/React | Team Lead, Backend Dev, Frontend Dev, ML/AI Engineer, QA |
| `ml-n8n` | Python · n8n · REST/webhooks | Team Lead, Workflow Designer, Python Developer, QA & DevOps |
| `java-enterprise` | Spring Boot · Kafka · GraphQL · React | Team Lead, Backend Dev, Frontend Dev, Data & Messaging, QA, DevOps |
| `web-static` | Astro/Next.js/Hugo · Tailwind | Team Lead, Frontend Dev, Content & SEO, QA |
| `web-dynamic` | Next.js/Remix · Node/Python · PostgreSQL | Team Lead, Frontend Dev, Backend Dev, QA, DevOps |

## How Configuration Layers Work

```
~/.claude/CLAUDE.md                ← Global agent manifest (base)
~/.claude/rules/*.md               ← Global rules (always loaded, 3 files)
  ├── coding-standards.md          SOLID, quality gates, prohibited patterns
  ├── copilot-conventions.md       Cross-tool portable conventions
  └── safety.md                    Destructive action guards, secrets policy
~/.claude/rules-library/*.md       ← On-demand rules (loaded by phase agents, 9 files)
  ├── agent-team-protocol.md       Three-phase workflow, delegation rules
  ├── clarification-protocol.md    Ask before implementing ambiguous requirements
  ├── environment-setup.md         Environment and config verification
  ├── integration-testing.md       Test integration points early
  ├── phase-workflow.md            Phase transition rules and boundaries
  ├── ralph-loop.md                Single-agent autonomous iteration loop
  ├── stack-constraints.md         Stack version and compatibility guards
  ├── team-lead-efficiency.md      Limit agents, poll frequency, no re-work
  └── token-efficiency.md          Diff-over-rewrite, context economy
~/.claude/agents/*.md              ← Phase + utility agents (9 files)
  ├── research.md                  Research phase agent
  ├── plan.md                      Plan phase agent
  ├── build.md                     Build phase agent
  ├── review.md                    Review phase agent
  ├── code-simplifier.md           Simplify recently changed code
  ├── doc-writer.md                Generate and update documentation
  ├── phase-recap.md               Summarize completed phase
  ├── security-review.md           Scan for security vulnerabilities
  └── verify-app.md                End-to-end project verification
~/.claude/hooks/*.sh               ← Deterministic lifecycle hooks (always active, 6 files)
  ├── verify-on-stop.sh            Run test suite when Claude finishes responding
  ├── verify-after-edit.sh         Run type checker after source file edits
  ├── auto-format.sh               Auto-format edited files
  ├── protect-files.sh             Prevent edits to protected files
  ├── reinject-context.sh          Re-inject session context on prompt submit
  └── notify.sh                    Desktop notifications (macOS + Linux)
~/.claude/settings.json            ← Hooks wiring and global settings
./CLAUDE.md                        ← Project-level (overrides global)
./.claude/commands/*.md            ← Project slash commands
./CLAUDE.local.md                  ← Personal overrides (gitignored)
```

Project-level rules override global rules. More specific always wins.

## Four-Phase Workflow

| Phase | Model | Effort | Delegation | What Happens |
|---|---|---|---|---|
| **Research** | Opus (highest) | High | None | Explore codebase, summarize findings, identify constraints |
| **Plan** | Opus (highest) | High | None | Design approach, get user approval |
| **Build** | Sonnet (fast) | Medium | Yes | Team Lead delegates to specialist sub-agents |
| **Build (loop)** | Sonnet (fast) | Medium | None | Ralph Loop: single agent iterates through stories autonomously |
| **Review** | Opus (highest) | High | None | Holistic review, run tests, verify consistency |

Each phase has a dedicated agent (`~/.claude/agents/`) that loads the relevant rules from the rules library. Planning and research must stay in one mind — sub-agents only see fragments and can't reason about the whole system. Delegation only happens during Build. For smaller features, **Ralph Loop** provides a single-agent alternative: read PRD → implement next failing story → test → commit → repeat.

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
CONTRIBUTING.md                          ← PR guidelines
claude_code/
  claude-code                            ← tmux launcher script
  claude-setup.sh                        ← One-time setup (creates ~/.claude/); --sync to update
  .claude/
    CLAUDE.md                            ← Global agent manifest (reference copy)
    settings.json                        ← Hooks wiring (reference copy)
    rules/                               ← 3 global rules (always loaded)
      coding-standards.md                ← SOLID, quality gates, prohibited patterns
      copilot-conventions.md             ← Cross-tool conventions
      safety.md                          ← Destructive action guards, secrets
    rules-library/                       ← 9 on-demand rules (loaded by phase agents)
      agent-team-protocol.md             ← Three-phase workflow, delegation rules
      clarification-protocol.md          ← Ask before implementing ambiguity
      environment-setup.md               ← Environment verification
      integration-testing.md             ← Test integration points early
      phase-workflow.md                  ← Phase transition boundaries
      ralph-loop.md                      ← Single-agent autonomous iteration loop
      stack-constraints.md               ← Version and compatibility guards
      team-lead-efficiency.md            ← Agent limits, poll frequency
      token-efficiency.md                ← Diff-over-rewrite, context economy
    agents/                              ← 9 agent definitions (4 phase + 5 utility)
      research.md                        ← Research phase agent
      plan.md                            ← Plan phase agent
      build.md                           ← Build phase agent
      review.md                          ← Review phase agent
      code-simplifier.md                 ← Simplify recently changed code
      doc-writer.md                      ← Generate and update documentation
      phase-recap.md                     ← Summarize completed phase
      security-review.md                 ← Scan for security vulnerabilities
      verify-app.md                      ← End-to-end project verification
    commands/                            ← Slash commands
      ralph-start.md                     ← Start a Ralph Loop session
    hooks/                               ← 6 lifecycle hook scripts
      verify-on-stop.sh                  ← Run test suite on Stop event
      verify-after-edit.sh               ← Run type checker on Edit/Write
      auto-format.sh                     ← Auto-format edited files
      protect-files.sh                   ← Prevent edits to protected files
      reinject-context.sh                ← Re-inject session context on prompt submit
      notify.sh                          ← Desktop notifications (macOS + Linux)
  docs/                                  ← 13 reference documents
    agent-traces.md                      ← How to find and archive agent transcripts
    claude-code-setup-cookbook.md         ← Detailed cookbook
    claude-config-guide.md               ← Configuration reference
    common-pitfalls.md                   ← Cross-cutting issues and fixes
    delegation-best-practices.md         ← When and how to delegate to agents
    enhancement-plan.md                  ← Phased enhancement roadmap
    error-reporting-template.md          ← Standardized error report format
    hooks-guide.md                       ← Hook installation and customization guide
    hooks-test-cases.md                  ← Manual test cases for hooks
    phase-recap-template.md              ← End-of-phase handoff template
    ralph-loop-guide.md                  ← Ralph Loop usage guide
    session-management.md                ← Session commands cheat sheet
    subagents-guide.md                   ← Sub-agent configuration and usage
  tests/                                 ← Automated tests
    test-hooks.sh                        ← 27 tests for hook scripts
```

## Documentation

- **[Setup Cookbook](claude_code/docs/claude-code-setup-cookbook.md)** — deep-dive into every configuration option
- **[Config Guide](claude_code/docs/claude-config-guide.md)** — templates, agent teams, and workflow reference
- **[Hooks Guide](claude_code/docs/hooks-guide.md)** — hook installation, customization, and supported stacks
- **[Session Management](claude_code/docs/session-management.md)** — commands cheat sheet for daily use
- **[Delegation Best Practices](claude_code/docs/delegation-best-practices.md)** — when and how to delegate to sub-agents
- **[Common Pitfalls](claude_code/docs/common-pitfalls.md)** — cross-cutting issues and solutions
- **[Enhancement Plan](claude_code/docs/enhancement-plan.md)** — phased roadmap for rules, hooks, and sub-agents
- **[Agent Traces](claude_code/docs/agent-traces.md)** — locating, reading, and archiving agent transcripts
- **[Error Reporting Template](claude_code/docs/error-reporting-template.md)** — standardized format for bug reports
- **[Phase Recap Template](claude_code/docs/phase-recap-template.md)** — end-of-phase handoff checklist
- **[Ralph Loop Guide](claude_code/docs/ralph-loop-guide.md)** — Ralph Loop usage and configuration
- **[Sub-Agents Guide](claude_code/docs/subagents-guide.md)** — sub-agent configuration and usage

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome for new templates, rule improvements, and ports to other tools.

## License

[MIT](LICENSE)
