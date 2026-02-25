---
applyTo: "**"
---

# GCC Protocol — Git Context Controller

Optional memory persistence layer using the GCC protocol ([arXiv 2508.00031](https://arxiv.org/abs/2508.00031)).

GCC currently relies on **Aline MCP** (`aline-ai`) as its implementation — Aline is the MCP server that provides the CONTEXT, COMMIT, BRANCH, and MERGE tools to Claude Code. Without Aline installed, GCC commands are not available.

## Prerequisites

GCC requires the Aline MCP server registered in your Claude Code configuration.

**Automated setup (recommended):**

```bash
./claude_code/claude-setup.sh --gcc
```

**Manual setup:**

```bash
# 1. Register Aline as an MCP server (user-scoped, available in all projects)
claude mcp add --scope user --transport stdio aline -- npx -y aline-ai@latest

# 2. Verify it's registered
claude mcp list
# Should show: aline  stdio  npx -y aline-ai@latest
```

Once installed, Aline provides four MCP tools: `context`, `commit`, `branch`, and `merge`. Phase agents detect these tools automatically and use them when available.

## When to Use GCC Commands

Use GCC commands **only when Aline MCP is available** (the `aline` MCP server is configured and responsive). If unavailable, skip all GCC operations silently — the workflow functions without them.

## Commands and Their Phase Mapping

### CONTEXT — Load Memory at Session Start

- Run at the **beginning of every phase** (research, plan, build, review).
- Replaces manually re-reading phase recaps when GCC memory is available.
- The `reinject-context.sh` hook still runs as a fallback for non-GCC projects.

### COMMIT — Save Memory Milestone

- Run after **completing a phase milestone**:
  - Plan approved → COMMIT with plan summary
  - Build verified → COMMIT with build summary (files changed, tests passing)
  - Review passed → COMMIT with review verdict
  - Phase recap written → COMMIT with recap summary
- Include: what was done, key decisions, next steps.
- Keep summaries concise (3-5 bullet points).

### BRANCH — Explore Alternatives

- Use during the **Plan phase** when evaluating multiple approaches.
- Create a GCC branch for each alternative being explored.
- Name branches descriptively: `approach-a-redis-cache`, `approach-b-in-memory`.

### MERGE — Conclude Exploration

- Use after selecting an approach during Plan phase.
- Merge the chosen exploration branch back.

## Critical Distinctions

| GCC Operation | Git Operation | Relationship |
|---|---|---|
| GCC COMMIT | `git commit` | **Completely separate.** GCC commits are memory snapshots in `.gcc/`. Git commits are code changes and still require user approval. |
| GCC BRANCH | `git branch` | **Completely separate.** GCC branches are virtual memory branches for exploration. Git branches are code branches. |

**Never conflate GCC operations with git operations.** GCC is a memory layer; git is version control.

## Rules

- GCC is **optional and additive**. All phase workflows, delegation rules, and commit gates remain unchanged.
- GCC COMMIT does **not** replace `git commit`. Users still approve all code commits.
- If Aline MCP is unavailable or errors, continue the workflow normally.
- Do not store secrets, credentials, or PII in GCC memory.
