# Claude Code Project Configuration Guide

## Overview

This system gives you templated `CLAUDE.md` configurations for different project types, each with a built-in **Agent Team** — specialized roles that Claude uses to delegate work via sub-agents. The enhanced launcher script manages tmux sessions per project.

**Files included:**

| File | Purpose |
|---|---|
| `claude-setup.sh` | One-time setup — creates `~/.claude/templates/` with Agent Team configs |
| `claude-code` | Enhanced launcher — replaces your existing tmux script |

---

## Installation (One-Time)

```bash
# 1. Make both scripts executable
chmod +x claude-setup.sh claude-code

# 2. Run setup (creates all templates in ~/.claude/templates/)
./claude-setup.sh

# 3. Verify
claude-code list
```

After setup, your `~/.claude/` directory looks like:

```
~/.claude/
├── CLAUDE.md                     # Global config + Agent Team Protocol
├── templates/
│   ├── ml-rag/                   # 5 agents: Lead, RAG Eng, Graph Eng, Data Analyst, QA
│   │   ├── CLAUDE.md
│   │   └── commands/
│   │       ├── eval.md
│   │       ├── ingest.md
│   │       └── team-review.md
│   ├── ml-langchain/             # 4 agents: Lead, Agent Dev, Integration Eng, QA
│   │   ├── CLAUDE.md
│   │   └── commands/
│   │       ├── trace.md
│   │       └── team-review.md
│   ├── ml-n8n/                   # 4 agents: Lead, Workflow Designer, Python Dev, QA/DevOps
│   │   ├── CLAUDE.md
│   │   └── commands/
│   │       ├── export-workflows.md
│   │       └── team-review.md
│   ├── java-enterprise/          # 6 agents: Lead, Java Dev, Frontend Dev, Data/Msg Eng, QA, DevOps
│   │   ├── CLAUDE.md
│   │   └── commands/
│   │       ├── build.md
│   │       ├── new-module.md
│   │       ├── db-migrate.md
│   │       ├── team-review.md
│   │       └── new-feature.md
│   ├── web-static/               # 4 agents: Lead, Frontend Dev, Content/SEO, QA
│   │   ├── CLAUDE.md
│   │   └── commands/
│   │       └── team-review.md
│   └── web-dynamic/              # 5 agents: Lead, Frontend Dev, Backend Dev, QA, DevOps
│       ├── CLAUDE.md
│       └── commands/
│           ├── db-migrate.md
│           ├── team-review.md
│           └── new-feature.md
└── settings.json                 # Your global Claude settings (if any)
```

---

## Workflow 1: New Terminal + New Project

When starting a brand-new project from scratch.

### Example: New ML RAG project

```bash
# Step 1: Initialize project with template
claude-code init ml-rag ~/projects/medical-rag

# What this does:
#   - Creates ~/projects/medical-rag/ (if it doesn't exist)
#   - Copies ml-rag template CLAUDE.md → ~/projects/medical-rag/CLAUDE.md
#   - Copies commands → ~/projects/medical-rag/.claude/commands/

# Step 2: Customize the CLAUDE.md for this specific project
#   Open ~/projects/medical-rag/CLAUDE.md
#   Look for ← UPDATE comments and fill in your choices:
#     - Vector store: Qdrant
#     - Embeddings: OpenAI text-embedding-3-large
#     - LLM: Claude 3.5 Sonnet via Anthropic API
#     - etc.

# Step 3: Start Claude session
claude-code ~/projects/medical-rag

# This creates tmux session "claude-medical-rag" in that directory.
# Claude reads: ~/.claude/CLAUDE.md (global) + ./CLAUDE.md (project)
```

### Example: New Java Enterprise project

```bash
# Initialize
claude-code init java-enterprise ~/projects/order-service

# Customize CLAUDE.md:
#   - Databases: PostgreSQL + Redis (no MongoDB for this one)
#   - Messaging: Kafka only (no RabbitMQ)
#   - Frontend: React + MUI
#   - etc.

# Start
claude-code ~/projects/order-service

# Now inside Claude, you also get custom slash commands:
#   /project:build        → full build + test
#   /project:new-module   → scaffold new bounded context
#   /project:db-migrate   → create + apply DB migration
```

### Example: New dynamic web app

```bash
claude-code init web-dynamic ~/projects/saas-dashboard
# Customize, then:
claude-code ~/projects/saas-dashboard
```

---

## Workflow 2: New Terminal + Existing Project

When returning to a project that already has `CLAUDE.md` configured.

```bash
# Option A: Start new session (if tmux session doesn't exist)
claude-code ~/projects/order-service
# Creates tmux session "claude-order-service" and starts Claude

# Option B: Resume existing session (if already running)
claude-code ~/projects/order-service
# Detects existing tmux session and attaches to it

# Option C: From project directory
cd ~/projects/order-service
claude-code
# Uses current directory; creates/attaches session "claude-order-service"
```

### What Claude sees when it starts:

Claude Code automatically reads these files (in this order):

1. **`~/.claude/CLAUDE.md`** — your global preferences (coding style, git conventions, communication style)
2. **`./CLAUDE.md`** — project-specific rules (stack, architecture, conventions, commands)
3. **`./.claude/commands/*.md`** — custom slash commands available via `/project:name`

The global file provides your universal baseline. The project file provides specifics. They combine — you don't repeat yourself.

---

## Template Reference

### Available Templates

| Template | Use When | Key Features |
|---|---|---|
| `ml-rag` | Building RAG pipelines with knowledge graphs | Vector + graph hybrid search, eval harnesses, chunking rules |
| `ml-langchain` | LangChain/LangGraph agent workflows | LangGraph state machines, LangSmith tracing, agent patterns |
| `ml-n8n` | n8n-based workflow automation | Workflow JSON versioning, Python microservice integration |
| `java-enterprise` | Full-stack Java with messaging + caching | Hexagonal architecture, Kafka/RabbitMQ, GraphQL schema-first |
| `web-static` | Static marketing/blog sites | Content-first, SEO, performance budgets |
| `web-dynamic` | Full-stack web apps | Next.js App Router, Prisma, auth, mobile-responsive |

### Customization Points

Every template has `← UPDATE` comments marking values you should change per project. Common ones:

- Database choice (PostgreSQL vs MySQL vs MongoDB)
- LLM provider and model
- Frontend component library
- Deployment target
- Serialization format (Avro vs Protobuf vs JSON)

---

## Model & Effort Strategy

The agent team is NOT used for every phase. Planning, building, and reviewing each require a different configuration:

```
┌─────────────────────────────────────────────────────────────────┐
│  PLAN          │  BUILD                    │  REVIEW            │
│                │                           │                    │
│  Opus / High   │  Sonnet / Medium          │  Opus / High       │
│  Team Lead     │  Team Lead delegates to   │  Team Lead alone   │
│  works ALONE   │  specialist sub-agents    │  reviews all output│
│                │                           │                    │
│  Architecture, │  Implementation from      │  Integration check,│
│  API design,   │  the approved plan.       │  convention audit, │
│  data models,  │  Upgrade to Opus for      │  final sign-off    │
│  trade-offs    │  auth/security/complex    │                    │
└─────────────────────────────────────────────────────────────────┘
                         │
       Quick tasks (rename, format, boilerplate):
              Haiku / Low effort
```

**Why no delegation during planning?** Sub-agents only see what the Team Lead passes them. Planning requires seeing the *full* architecture — trade-offs across frontend, backend, data, and infra simultaneously. Fragmenting that into specialist perspectives produces plans that don't cohere.

**Why delegation during building?** Once the plan is locked, each task is well-scoped to a single domain. A Backend Developer sub-agent implementing Prisma models from a clear spec doesn't need to see the React component tree.

---

## Agent Teams — How They Work

Every template includes an **Agent Team** section in its CLAUDE.md. This tells Claude to operate as a team lead who delegates specialized work to sub-agents during the **build phase**.

### The Full Workflow

```
PLANNING PHASE (Team Lead alone, Opus, high effort)
    │
    │  "Design the order management feature"
    │   → Thinks holistically about architecture
    │   → Produces: API contracts, data model, component tree, test plan
    │
    ▼
BUILDING PHASE (Team delegates, Sonnet, medium effort)
    │
    │  Team Lead decomposes the plan into domain-specific tasks:
    │
    ├──→ Backend Dev: Prisma schema + tRPC routes
    ├──→ Frontend Dev: React pages + components
    ├──→ QA Engineer: tests at every layer
    │
    │  Each sub-agent gets: role prompt + plan context + specific task
    │  Team Lead reviews each output before continuing
    │
    ▼
REVIEW PHASE (Team Lead alone, Opus, high effort)
    │
    │  Reviews all combined output holistically
    │  Checks cross-domain consistency, conventions, integration
```

### When Does Delegation Happen?

Only during the build phase. The Team Lead uses these rules:

- **Handle directly**: planning, review, single-file changes, simple tasks, general questions
- **Delegate**: multi-file specialist work (>50 lines), cross-domain features, evaluations
- **Coordinate**: features that touch multiple domains (e.g., new DB table + API + UI)

### Team Compositions Per Template

| Template | Team Lead (default) | Specialists |
|---|---|---|
| **ml-rag** | Team Lead | RAG Engineer, Knowledge Graph Engineer, Data Analyst, QA Engineer |
| **ml-langchain** | Team Lead | Agent Developer, Integration Engineer, QA & Eval Engineer |
| **ml-n8n** | Team Lead | Workflow Designer, Python Developer, QA & DevOps Engineer |
| **java-enterprise** | Team Lead / Architect | Java Backend Dev, Frontend Dev, Data & Messaging Eng, QA, DevOps |
| **web-static** | Team Lead | Frontend Developer, Content & SEO Specialist, QA Engineer |
| **web-dynamic** | Team Lead / Architect | Frontend Dev, Backend Dev, QA Engineer, DevOps |

### Team Slash Commands

Every template includes `/project:team-review` — triggers all team roles to review recent changes in sequence. The java-enterprise and web-dynamic templates also include `/project:new-feature` for end-to-end feature implementation with coordinated delegation.

### Customizing Your Team

After `claude-code init`, you can edit the Agent Team section in your project's CLAUDE.md:

- **Add a role**: copy an existing role block and modify expertise/constraints
- **Remove a role**: delete the block (Team Lead will handle those tasks directly)
- **Adjust triggers**: change when delegation happens (e.g., raise/lower the 50-line threshold)
- **Refine constraints**: add project-specific rules to any role

---

## How Configuration Layers Work

```
┌─────────────────────────────────────────────────────┐
│               Claude's Behavior                     │
├─────────────────────────────────────────────────────┤
│  4. Custom Commands (.claude/commands/)              │  ← "recipes" for tasks
│  3. Agent Team (in ./CLAUDE.md)                      │  ← "who does what?"
│  2. Project CLAUDE.md (./CLAUDE.md)                  │  ← "how does THIS project work?"
│  1. Global CLAUDE.md (~/.claude/CLAUDE.md)           │  ← "how do I generally code?"
└─────────────────────────────────────────────────────┘
```

**Layer 1 — Global:** Your universal coding standards, git conventions, communication preferences, and the Agent Team Protocol (how delegation works). Written once, applies everywhere.

**Layer 2 — Project:** Stack-specific rules, architecture constraints, naming conventions, testing requirements. Written per project (from template, then customized).

**Layer 3 — Agent Team:** Role definitions, expertise areas, ownership boundaries, and delegation prompts. Tells Claude when to work directly vs. spawn specialist sub-agents.

**Layer 4 — Commands:** Task-specific instructions Claude can execute on demand. Includes team-wide operations like `team-review` and `new-feature`.

---

## Tips

### Keep CLAUDE.md focused
Long CLAUDE.md files waste Claude's context window. Aim for 50-100 lines per file. If you need more detail, put it in separate docs and reference them: "See docs/architecture.md for full system design."

### Evolve templates over time
After using a template on a few projects, you'll discover missing conventions. Update the template in `~/.claude/templates/` so future projects benefit.

### Add project-specific commands
As you work on a project, create new `.claude/commands/` files for repetitive tasks:
```bash
# Example: create a new command for your order-service project
cat > ~/projects/order-service/.claude/commands/deploy-staging.md << 'CMD'
Deploy to staging:
1. Run full build and test suite
2. Build Docker image with tag staging-{date}
3. Push to container registry
4. Apply k8s manifests from infra/k8s/staging/
5. Wait for rollout to complete
6. Run smoke tests against staging URL
CMD
```

### Session management (token efficiency)
Claude Code accumulates context over a conversation. Left unchecked, this bloats token usage and degrades quality. Three habits keep it tight:

**One task per session.** If you finish a feature and pivot to something unrelated (e.g., API design → test refactoring), start a fresh session. The launcher's per-project tmux sessions help — but even within a project, `/clear` resets context when you shift focus.

**Compact at boundaries.** When you finish a logical unit of work (a feature, a bug fix, a migration), run `/compact` with a focus hint:
```
/compact Summarize recent work focusing on the Kafka consumer changes
```
This compresses the conversation history into a tight summary, freeing context for the next task.

**Point to files, don't paste.** Instead of dumping code into the chat, tell Claude which files to read:
```
Read src/api/users.ts and generate tests for its exported functions.
```
Claude loads only what's needed rather than carrying everything in context.

### Permission patterns
Configure `/permissions` to reduce confirmation prompts. See [permissions-guide.md](permissions-guide.md) for per-stack Allow/Deny patterns.

### Multiple Claude sessions
The launcher creates separate tmux sessions per project directory. You can have multiple running:
```bash
# Terminal 1
claude-code ~/projects/order-service    # → tmux session: claude-order-service

# Terminal 2
claude-code ~/projects/medical-rag      # → tmux session: claude-medical-rag

# List all sessions
tmux list-sessions
```

---

## Output Styles

Claude Code supports three output styles that control response verbosity:

| Style | Behavior | Best for |
|---|---|---|
| **Concise** | Short answers, minimal explanation, code-focused | Build phase, quick fixes, experienced users |
| **Normal** | Balanced explanation with code | General development, default for most sessions |
| **Explanatory** | Detailed reasoning, trade-off discussion, alternatives | Plan/review phases, learning, architecture decisions |

**How to configure:**
- Run `/config` → select "Output style" → choose your preference
- The setting persists across sessions

**Phase recommendations:**
- **Plan / Review:** Use Explanatory — you want reasoning and trade-offs visible
- **Build:** Use Concise — faster iteration, less noise in context window
- **Debug:** Use Normal — enough context to understand suggestions without overwhelming

---

## Launcher Command Reference

```
claude-code [path]                  Start/resume Claude session (default: current dir)
claude-code init <type> [path]      Initialize project from template
claude-code list                    List available templates
claude-code help                    Show full usage
```
