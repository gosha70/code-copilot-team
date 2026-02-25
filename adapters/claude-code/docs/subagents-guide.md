# Custom Agents Guide

How to use and create custom agents for Claude Code.

## What Ships

| Agent | Model | Tools | Purpose |
|-------|-------|-------|---------|
| `code-simplifier` | Sonnet | Read, Grep, Glob, Edit | Post-build cleanup: removes dead code, simplifies conditionals, improves readability |
| `verify-app` | Sonnet | Read, Grep, Glob, Bash | End-to-end verification: type checker, linter, tests, dev server smoke test |
| `security-review` | Sonnet | Read, Grep, Glob | Scans for hardcoded secrets, injection risks, missing validation, exposed debug endpoints |
| `doc-writer` | Sonnet | Read, Grep, Glob, Edit, Write | Updates README, adds docstrings for new functions, maintains CHANGELOG |
| `phase-recap` | Sonnet | Read, Grep, Glob, Bash | Generates phase recap document summarizing what was built, decisions, and next steps |

## How Agents Work

Custom agents are Markdown files in `~/.claude/agents/` (global) or `.claude/agents/` (project-local). Each file has YAML frontmatter and a system prompt body.

### Frontmatter Format

```yaml
---
name: agent-name          # Unique identifier
description: One line.    # Shown in agent selection
tools: Read, Grep, Glob   # Comma-separated tool list
model: sonnet              # Model: sonnet, opus, haiku
---
```

### Available Tools

| Tool | Capability |
|------|-----------|
| `Read` | Read file contents |
| `Grep` | Search file contents with regex |
| `Glob` | Find files by pattern |
| `Edit` | Modify existing files |
| `Write` | Create new files |
| `Bash` | Execute shell commands |

Restrict tools to the minimum needed. A review agent shouldn't have `Edit`/`Write`. A verification agent shouldn't have `Edit`.

### Context

Each agent runs in a forked context — it sees the current project directory and can access any files, but its conversation is isolated from the main session. The agent receives only its system prompt (the Markdown body) plus whatever task description you provide when delegating.

## Using Agents

### Automatic Delegation

When working as Team Lead, delegate to agents via the Task tool:

```
Task: "Run the verify-app agent to check the project"
  → subagent_type: general-purpose (or reference the agent by name in the prompt)
```

### Direct Invocation

Reference agents by name when spawning sub-agents. The agent's system prompt and tool restrictions are applied automatically.

## Creating Custom Agents

### Step 1: Choose the Right Scope

An agent should do **one thing well**. Examples:
- Review code for security issues (read-only)
- Run database migrations (bash-only)
- Generate API client code from OpenAPI spec (read + write)

### Step 2: Create the File

Create `~/.claude/agents/my-agent.md` (global) or `.claude/agents/my-agent.md` (project):

```yaml
---
name: my-agent
description: What this agent does in one sentence.
tools: Read, Grep, Glob
model: haiku
---

# My Agent

You are a [role]. Your job is to [specific task].

## What to Do
1. [Step 1]
2. [Step 2]
3. [Step 3]

## Rules
- [Constraint 1]
- [Constraint 2]
```

### Step 3: Test It

Invoke the agent via Task tool and verify it:
- Follows its system prompt constraints
- Uses only its allowed tools
- Produces the expected output format
- Handles edge cases (empty project, missing config)

## Agents vs Hooks

| | Agents | Hooks |
|---|---|---|
| **When** | On-demand (delegated by lead or user) | Automatic (triggered by events) |
| **Scope** | Complex, multi-step analysis | Simple, single-check operations |
| **Context** | Full conversation fork | Stdin JSON, no conversation |
| **Cost** | API call (model inference) | Shell script (free) |
| **Blocking** | Returns results to caller | Can block tool execution (exit 2) |
| **Examples** | Code review, verification suite, refactoring | Type check after edit, format on save, protect files |

**Rule of thumb:** If it can be a 50-line shell script, make it a hook. If it needs to read multiple files, reason about code, or make decisions, make it an agent.

## Cost Optimization

Choose the right model tier for each agent:

| Model | Best For | Cost |
|-------|----------|------|
| `haiku` | Simple review, formatting checks, status reports | Lowest |
| `sonnet` | Code analysis, implementation tasks, test generation | Medium |
| `opus` | Architecture review, security audit, complex reasoning | Highest |

Most agents should use `sonnet`. Reserve `opus` for agents that need deep reasoning (security review, architecture analysis). Use `haiku` for agents that do simple pattern matching or status aggregation.
