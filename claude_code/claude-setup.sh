#!/bin/bash
# claude-setup.sh - One-time setup for Claude Code project templates
#
# Creates:
#   ~/.claude/CLAUDE.md                    Global configuration
#   ~/.claude/hooks/                       Global hook scripts (verify, notify)
#   ~/.claude/settings.json                Global settings with hooks wired
#   ~/.claude/templates/<type>/CLAUDE.md   Project templates (with Agent Team configs)
#   ~/.claude/templates/<type>/commands/   Custom slash commands per type
#   Installs claude-code launcher to ~/.local/bin/
#
# Run once, then use 'claude-code init <type> [path]' to scaffold projects.

set -e

CLAUDE_DIR="$HOME/.claude"
TEMPLATES_DIR="$CLAUDE_DIR/templates"
LAUNCHER_SOURCE="$(dirname "$0")/claude-code"
LAUNCHER_TARGET="$HOME/.local/bin/claude-code"

echo "============================================"
echo "  Claude Code Project Template Setup v2"
echo "  (with Agent Team configurations)"
echo "============================================"
echo ""

# ══════════════════════════════════════════════════════════════
# 1. GLOBAL CLAUDE.md
# ══════════════════════════════════════════════════════════════

mkdir -p "$CLAUDE_DIR"

if [[ -f "$CLAUDE_DIR/CLAUDE.md" ]]; then
    echo "[skip] ~/.claude/CLAUDE.md already exists (not overwriting)"
else
cat > "$CLAUDE_DIR/CLAUDE.md" << 'GLOBALEOF'
# Global Claude Configuration

## Identity
- Developer: Gosha (i.am.goga@gmail.com)

## General Principles
- Write clean, well-documented, production-quality code
- Follow SOLID principles; prefer composition over inheritance
- Handle errors explicitly; never swallow exceptions
- No magic numbers; use named constants
- Keep functions focused (< 30 lines preferred)
- Log meaningful messages at appropriate levels (DEBUG/INFO/WARN/ERROR)

## Git & Commits
- Use conventional commits: feat:, fix:, refactor:, docs:, test:, chore:
- Write descriptive commit messages explaining WHY, not just WHAT
- Keep commits atomic; one logical change per commit

## Code Review Mindset
- Flag potential security or performance concerns proactively
- Suggest tests for any new logic
- When multiple approaches exist, explain trade-offs before implementing
- When uncertain about requirements, ask before building

## Communication Style
- Be direct and concise
- Lead with the answer, then explain
- Use code examples over prose when possible

## Context Efficiency
- Keep this file and project CLAUDE.md lean; reference docs/* for deep detail
- When working on code, read specific files rather than scanning entire directories
- After completing a logical unit of work, suggest running /compact
- When switching tasks within a session, suggest running /clear first
- Prefer targeted file reads over broad codebase scans

## Model & Effort Strategy
Three phases, three configurations:
- PLANNING (architecture, API design, data modeling, security): use highest-capability
  model + high effort. Do NOT delegate to sub-agents. Plan holistically as Team Lead.
- BUILDING (implementation from an approved plan): use fast model + medium effort.
  Delegate to specialist sub-agents. Switch to highest-capability model only for
  complex/security-sensitive parts (auth, concurrency, state machines).
- REVIEW (verifying output, integration testing): use highest-capability model +
  high effort. Review holistically as Team Lead, do not delegate.
Quick tasks (rename, format, boilerplate): use lightest model + low effort.

## Agent Team Protocol (Global)
When this project defines an Agent Team section, follow these rules:
- Default role: Team Lead. You coordinate, plan, and review.
- PLANNING PHASE: Team Lead works alone. Do NOT delegate planning to sub-agents.
  Planning requires seeing the full architecture; sub-agents only see fragments.
- BUILDING PHASE: Team Lead decomposes the plan into tasks and delegates to
  specialist sub-agents via the Task tool.
- REVIEW PHASE: Team Lead reviews all output holistically. Do NOT delegate review.
- When spawning a sub-agent, include: (1) its role prompt from the team section,
  (2) relevant project context, (3) the specific task.
- Review ALL sub-agent output before presenting to the user.
- Never let two sub-agents modify the same file concurrently.
- If a sub-agent's output violates project conventions, reject and re-delegate.
GLOBALEOF
echo "[done] Created ~/.claude/CLAUDE.md"
fi

# ══════════════════════════════════════════════════════════════
# 2. TEMPLATE: ml-rag
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-rag/commands"

cat > "$TEMPLATES_DIR/ml-rag/CLAUDE.md" << 'EOF'
# ML/AI — RAG + Knowledge Graph

## Stack
- Python 3.11+, dependency management via Poetry
- FastAPI for the API layer
- Vector store: Chroma (dev) / Pinecone or Qdrant (prod) ← UPDATE per project
- Knowledge graph: Neo4j (Cypher queries, neo4j Python driver)
- Embeddings: OpenAI text-embedding-3-small ← UPDATE per project
- LLM: GPT-4o / Claude via LiteLLM ← UPDATE per project
- Frontend: Streamlit for POC; React+Vite for production UI

## Project Structure
```
src/
├── api/                  # FastAPI routes + middleware
├── rag/
│   ├── chunking.py       # Document chunking (configurable strategy)
│   ├── embeddings.py     # Embedding generation + caching
│   ├── retrieval.py      # Hybrid search: vector + keyword + graph
│   └── generation.py     # LLM response with source citations
├── graph/
│   ├── schema.py         # Node/relationship type definitions
│   ├── ingestion.py      # Entity + relation extraction pipeline
│   └── queries.py        # Parameterized Cypher query templates
├── config/               # Pydantic settings, .env loading
└── utils/
prompts/                  # Versioned YAML prompt templates
eval/                     # Evaluation datasets + harnesses
tests/
poc/                      # Streamlit prototypes
notebooks/                # Exploration
```

## Key Conventions
- All prompts: versioned YAML in `prompts/`, never inline strings
- Every LLM call: wrapped in traced function with latency + token logging
- Embeddings model: pinned in config, never hardcoded
- Chunking: strategy + chunk_size + overlap configurable via settings
- Graph schema: defined in code, changes via migration scripts
- All retrieval results must include source references for citation

## RAG Rules
- Default to hybrid search (vector + BM25 keyword) before graph traversal
- Graph traversal depth: configurable, default 2 hops
- Chunk overlap: 10-15% of chunk size
- Never embed raw HTML/markdown; always clean to plain text first
- Reranking step required before final context assembly

## Testing
- `pytest` with fixtures for mock LLM responses (no live API in unit tests)
- Retrieval eval: recall@k and precision@k on labeled dataset
- Answer quality: LLM-as-judge with rubrics defined in `eval/rubrics/`
- Graph tests: schema constraint validation, Cypher query correctness

## Commands
```bash
poetry install                                          # deps
poetry run pytest                                       # tests
poetry run uvicorn src.api.main:app --reload            # API
poetry run streamlit run poc/app.py                     # POC UI
docker compose up -d                                    # Neo4j + vector DB
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, architecture decisions, code review, user comms | Overall coordination |
| **RAG Engineer** | Chunking, retrieval, generation, prompt engineering | `src/rag/`, `prompts/` |
| **Knowledge Graph Engineer** | Neo4j schema, entity extraction, Cypher queries | `src/graph/` |
| **Data Analyst** | Evaluation harnesses, metrics, benchmarking, data exploration | `eval/`, `notebooks/` |
| **QA Engineer** | Testing, CI, code review for bugs/security | `tests/`, all test files |

### Team Lead — Default Behavior
You ARE the Team Lead. For every user request:
1. Assess complexity. Single-file, single-domain changes → handle directly.
2. Multi-domain or >50 lines of specialized code → delegate to specialist sub-agent.
3. Always review sub-agent output against project conventions before presenting.
4. Coordinate when a task spans domains (e.g., new entity type needs Graph + RAG + tests).

### Delegation Prompts
When spawning a sub-agent via Task tool, use this pattern:
```
You are the [ROLE] on a RAG + Knowledge Graph project.

Project conventions:
- [paste relevant section from this CLAUDE.md]

Your task: [specific task description]

Constraints:
- Follow all conventions above
- Write type-annotated Python with docstrings
- Do NOT modify files outside your ownership area without noting it
- Return: code changes + brief summary of decisions made
```

### RAG Engineer
Expertise: document chunking strategies, embedding models, vector search, hybrid retrieval, reranking, prompt engineering, LLM integration.
Constraints: never hardcode model names; always use config. Every retrieval function must return source metadata. All prompts go in `prompts/` as YAML.

### Knowledge Graph Engineer
Expertise: Neo4j, Cypher query optimization, entity/relation extraction, graph schema design, graph traversal algorithms.
Constraints: all schema changes via migration scripts. Parameterize all Cypher queries (no string interpolation). Test all queries against sample data.

### Data Analyst
Expertise: evaluation framework design, retrieval metrics (recall@k, precision@k, MRR), answer quality rubrics, statistical analysis, data visualization.
Constraints: never modify production data. All eval configs in `eval/`. Document methodology in notebook markdown cells.

### QA Engineer
Expertise: pytest, test architecture, mocking LLM calls, integration testing, security review, CI/CD pipeline.
Constraints: run existing tests before writing new ones. Mock all external APIs. Coverage targets: ≥80% on `src/rag/` and `src/graph/`. Flag any untested code paths.
EOF

cat > "$TEMPLATES_DIR/ml-rag/commands/eval.md" << 'EOF'
Run the RAG evaluation pipeline:
1. Load evaluation dataset from eval/datasets/
2. Run retrieval evaluation (recall@k, precision@k)
3. Run answer quality evaluation (LLM-as-judge)
4. Print summary table with pass/fail thresholds
5. If any metric is below threshold, flag it clearly
EOF

cat > "$TEMPLATES_DIR/ml-rag/commands/ingest.md" << 'EOF'
Run the document ingestion pipeline:
1. Check for new documents in the configured source directory
2. Run chunking with the current strategy settings
3. Generate embeddings and upsert to vector store
4. Extract entities/relations and update knowledge graph
5. Report: documents processed, chunks created, entities extracted
EOF

cat > "$TEMPLATES_DIR/ml-rag/commands/team-review.md" << 'EOF'
Perform a full team review of recent changes:
1. As QA Engineer: run full test suite, report pass/fail and coverage
2. As RAG Engineer: review any changes to retrieval/generation for correctness
3. As Knowledge Graph Engineer: verify graph schema consistency
4. As Data Analyst: check if eval metrics have regressed
5. As Team Lead: synthesize findings into a summary with action items
EOF

echo "[done] Created template: ml-rag"

# ══════════════════════════════════════════════════════════════
# 3. TEMPLATE: ml-app
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-app/commands"

cat > "$TEMPLATES_DIR/ml-app/CLAUDE.md" << 'EOF'
# ML/AI — Full-Stack LLM Application

## Stack
- Python 3.10+, setuptools (pyproject.toml), `pip install -e ".[dev]"`
- FastAPI + Uvicorn for the API layer
- LLM providers: LiteLLM abstraction (OpenAI, Anthropic, Ollama, vLLM) ← UPDATE per project
- Vector store: Chroma (dev) / Pinecone or Qdrant (prod) ← UPDATE per project
- Sandboxed execution: Docker container + RestrictedPython ← UPDATE if not needed
- Frontend: Next.js + React + TypeScript + Tailwind CSS + Radix UI
- Code quality: Black (formatter), Ruff (linter), mypy strict (type checker)

## Project Structure
```
src/<package>/
├── core/                # Core algorithm logic, budget tracking, guardrails
├── llm/                 # LLM provider clients (protocol-based abstraction)
│   ├── base.py          # Provider protocol (interface)
│   ├── auto.py          # Auto-detection from env vars
│   └── ...              # One client per provider
├── strategies/          # Pluggable interaction modes (strategy pattern)
│   ├── base.py          # Strategy protocol
│   ├── direct.py        # Single-pass LLM call
│   ├── rag.py           # Retrieval-augmented generation
│   └── ...              # Additional strategies
├── storage/             # Persistence layer
│   ├── database.py      # Base storage (SQLite for dev)
│   ├── conversation_store.py  # Chat history
│   └── vector_store.py  # Vector similarity search
├── envs/                # Execution environments
│   ├── sandbox.py       # Docker sandbox for untrusted code
│   └── timeout.py       # Execution timeout utilities
├── server/              # FastAPI application
│   ├── app.py           # FastAPI instance + middleware
│   ├── models.py        # Pydantic request/response schemas
│   ├── dependencies.py  # Dependency injection
│   └── routes/          # Endpoint handlers (one per domain)
├── domain/              # DDD entities, value objects, events, exceptions
├── infrastructure/      # Config loaders, external service adapters
├── benchmark/           # Evaluation harness (datasets, runner, report)
├── api.py               # Unified high-level API (simple entry point)
└── config.py            # Global configuration (Pydantic settings)
frontend/                # Next.js React app
├── src/
│   ├── app/             # Next.js App Router (pages + layouts)
│   ├── components/      # React components (Radix UI based)
│   └── lib/             # Utilities, API client, hooks
├── package.json
└── tailwind.config.js
docker/                  # Dockerfiles (sandbox container, services)
tests/
├── unit/                # Component-level tests
├── integration/         # Multi-component tests
└── e2e/                 # End-to-end tests
```

## Architecture Rules
- **Clean Architecture**: domain → application → infrastructure layers; dependencies flow inward
- **Protocol-based abstractions**: LLM providers, strategies, storage all defined as protocols (interfaces)
- **Provider-agnostic**: LLM clients pluggable via standardized protocol; auto-detect from env vars
- **Strategy pattern**: pluggable interaction modes (Direct, RAG, custom) with unified interface
- **Budget tracking**: all LLM operations tracked for tokens, cost, and execution steps
- **Sandboxed execution**: untrusted code runs in Docker containers with resource limits
- **Configuration-driven**: models, strategies, limits all configurable via env vars and config files

## Key Conventions
- All LLM calls: wrapped with tracing (latency, token count, cost)
- Provider selection: auto-detect from environment variables, never hardcode
- Pydantic models for all API request/response schemas
- Type annotations on all public functions; mypy strict mode
- Async handlers for all I/O-bound FastAPI operations
- YAML for prompt templates and configuration; never inline prompt strings
- Health check endpoint at `/health`

## LLM Provider Rules
- Define provider interface as a Python protocol (abstract base)
- Each provider in its own module (`llm/<provider>_client.py`)
- Auto-detection from env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)
- Never import provider SDKs at module level; use lazy imports (graceful when SDK missing)
- All providers must support: `generate()`, `stream()`, and token estimation
- Mock provider for testing (deterministic responses, no API calls)

## Execution Safety
- Docker sandbox: non-root user, memory/CPU limits, network disabled for untrusted code
- RestrictedPython for lightweight sandboxing when Docker is unavailable
- Execution timeout on all LLM calls and code execution
- Budget limits: max tokens, max cost, max execution steps per request

## Frontend Conventions
- Next.js App Router with server and client components
- SWR for data fetching with caching
- Tailwind CSS for styling; Radix UI for accessible components
- TypeScript strict mode; no `any` types
- Responsive design (mobile-first breakpoints)

## Testing
- Backend: `pytest` with markers (`integration`, `e2e`, `live`, `slow`)
- Mock all LLM calls in unit tests (use mock provider)
- Frontend: Vitest + React Testing Library
- Benchmark suite for strategy comparison (accuracy, cost, latency)
- Coverage target: ≥80% on core modules

## Commands
```bash
pip install -e ".[dev]"                                    # install with dev tools
pip install -e ".[all]"                                    # install everything
pytest --tb=short -q                                       # run tests
uvicorn src.<package>.server.app:app --reload              # API server
cd frontend && npm install && npm run dev                  # frontend dev server
ruff check . && mypy src/                                  # lint + type check
docker build -f docker/Dockerfile.sandbox -t sandbox .     # build sandbox
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, architecture decisions, API contracts, code review | Overall coordination, `src/<pkg>/domain/` |
| **Backend Developer** | FastAPI routes, server logic, core algorithm, storage | `src/<pkg>/server/`, `src/<pkg>/core/`, `src/<pkg>/storage/` |
| **Frontend Developer** | React components, pages, data fetching, UI state | `frontend/` |
| **ML/AI Engineer** | LLM providers, strategies, embeddings, benchmarks, prompts | `src/<pkg>/llm/`, `src/<pkg>/strategies/`, `src/<pkg>/benchmark/` |
| **QA Engineer** | Testing at all layers, coverage, mocking, CI | `tests/`, all test files |

### Team Lead — Default Behavior
You ARE the Team Lead. For every user request:
1. Assess complexity. Single-domain, single-layer changes → handle directly.
2. Multi-layer or >50 lines of specialized code → delegate to specialist sub-agent.
3. Always review sub-agent output against project conventions before presenting.
4. Coordinate when a task spans layers (e.g., new API endpoint needs server + frontend + tests).
5. Own domain entities and cross-cutting concerns (auth, config, error handling).

### Delegation Prompts
When spawning a sub-agent via Task tool, use this pattern:
```
You are the [ROLE] on a full-stack LLM application.

Architecture: Clean Architecture (domain → application → infrastructure).
Backend: Python 3.10+, FastAPI, protocol-based LLM abstraction, strategy pattern.
Frontend: Next.js + React + TypeScript + Tailwind + Radix UI.

Project conventions:
- [paste relevant section from this CLAUDE.md]

Your task: [specific task description]

Constraints:
- Follow all conventions above
- Type-annotated Python with mypy strict compliance
- Do NOT modify files outside your ownership area without noting it
- Return: code changes + brief summary of decisions made
```

### Backend Developer
Expertise: FastAPI, Pydantic, async Python, SQLite/PostgreSQL, dependency injection, Docker.
Constraints: Pydantic models for all API schemas. Async handlers for I/O. Health check at `/health`. Structured logging. Domain entities are plain Python (no framework deps). Business logic in core/services, not in route handlers.

### Frontend Developer
Expertise: Next.js App Router, React (server/client components), TypeScript, Tailwind CSS, Radix UI, SWR, responsive design.
Constraints: Server Components by default; `'use client'` only for interactivity. SWR for data fetching. TypeScript strict mode, no `any`. Accessible components (ARIA). Responsive at all breakpoints.

### ML/AI Engineer
Expertise: LLM API integration, prompt engineering, RAG pipelines, embedding models, evaluation frameworks, token optimization, multi-provider abstraction.
Constraints: all providers implement the base protocol. Auto-detect from env vars. Never hardcode model names; use config. Mock provider for tests. Lazy SDK imports. Budget tracking on all LLM calls. Prompts in YAML files.

### QA Engineer
Expertise: pytest, Vitest, React Testing Library, test architecture, mocking, benchmarking, CI/CD.
Constraints: run existing tests before writing new ones. Mock all external APIs in unit tests. Use pytest markers for test categories. Coverage ≥80% on core modules. Frontend tests with Vitest + RTL. Benchmark tests with labeled datasets.
EOF

cat > "$TEMPLATES_DIR/ml-app/commands/bench.md" << 'EOF'
Run the benchmark/evaluation pipeline:
1. Load benchmark datasets from the configured directory
2. Run each strategy (direct, RAG, etc.) against the test cases
3. Collect metrics: accuracy, token usage, cost, latency
4. Print summary table with per-strategy results
5. Flag any strategy that regresses below baseline thresholds
EOF

cat > "$TEMPLATES_DIR/ml-app/commands/providers.md" << 'EOF'
Check LLM provider status and connectivity:
1. Read configured provider environment variables
2. For each configured provider, attempt a minimal health check (list models or ping)
3. Report: provider name, status (connected/error), default model, estimated cost
4. If no providers are configured, show setup instructions
EOF

cat > "$TEMPLATES_DIR/ml-app/commands/team-review.md" << 'EOF'
Perform a full team review of recent changes:
1. As QA Engineer: run full test suite, report pass/fail and coverage
2. As Backend Developer: review API routes, core logic, storage layer
3. As ML/AI Engineer: review LLM integration, strategy logic, prompt quality
4. As Frontend Developer: check component accessibility, responsive behavior
5. As Team Lead: synthesize findings into a summary with action items
EOF

echo "[done] Created template: ml-app"

# ══════════════════════════════════════════════════════════════
# 4. TEMPLATE: ml-langchain
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-langchain/commands"

cat > "$TEMPLATES_DIR/ml-langchain/CLAUDE.md" << 'EOF'
# ML/AI — LangChain + LangGraph + LangSmith

## Stack
- Python 3.11+, Poetry
- LangChain (chains, tools, retrievers)
- LangGraph (stateful multi-step agent workflows)
- LangSmith (tracing, evaluation, monitoring)
- FastAPI for serving
- Frontend: Streamlit (POC) / React+Vite (production)

## Project Structure
```
src/
├── api/                  # FastAPI endpoints
├── agents/
│   ├── graphs/           # LangGraph state machines (one file per graph)
│   ├── tools/            # Custom tools (@tool decorated functions)
│   ├── prompts/          # ChatPromptTemplate definitions
│   └── callbacks/        # Custom callback handlers
├── chains/               # Simple LangChain chains (non-agentic)
├── config/               # Pydantic settings, model registry
└── utils/
eval/
├── datasets/             # LangSmith evaluation datasets
├── evaluators/           # Custom evaluator functions
└── config.yaml           # Eval run configurations
tests/
poc/
```

## Architecture Rules
- Use LangGraph for ANY multi-step workflow (not legacy AgentExecutor)
- Every LangGraph graph: explicit TypedDict state schema, no Any types
- All chains/graphs must be LangSmith-traceable (LANGCHAIN_TRACING_V2=true)
- Tools must have clear, complete docstrings (LLM reads them for selection)
- Prompts use ChatPromptTemplate; store in src/agents/prompts/

## Agent Patterns
- Tool-using single agent → ReAct pattern via LangGraph
- Multi-step complex tasks → Plan-and-Execute graph
- Multi-agent collaboration → Supervisor graph pattern
- Always implement human-in-the-loop breakpoints for destructive actions
- Max recursion depth: configurable, default 25
- All graph nodes must handle exceptions (return error state, don't crash)

## LangSmith
- All runs tagged with: project name, environment (dev/staging/prod)
- Evaluation datasets stored in eval/datasets/ as JSON
- Custom evaluators in eval/evaluators/ (correctness, tool_selection, latency)
- Run evaluations on every PR that touches agent logic

## Testing
- Unit: mock LLM via FakeLLM, test tool logic independently
- Integration: test full graph with recorded LLM responses
- Eval: LangSmith eval suite (correctness, tool accuracy, hallucination)
- Regression: baseline dataset comparison on each PR

## Commands
```bash
poetry install
poetry run pytest
LANGCHAIN_TRACING_V2=true poetry run uvicorn src.api.main:app --reload
poetry run python -m src.agents.graphs.main          # run agent directly
poetry run streamlit run poc/app.py
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, architecture, agent design review | Overall coordination |
| **Agent Developer** | LangGraph graphs, tools, prompts, callbacks | `src/agents/`, `src/chains/` |
| **Integration Engineer** | API layer, LangSmith config, deployment, infra | `src/api/`, `src/config/`, Docker |
| **QA & Eval Engineer** | Testing, LangSmith evaluations, benchmarks | `tests/`, `eval/` |

### Team Lead — Default Behavior
You ARE the Team Lead. You own agent architecture decisions:
1. Which pattern to use (ReAct, plan-and-execute, supervisor) for each use case.
2. How to decompose complex agent workflows into graph nodes.
3. Review all agent code for correctness, error handling, and prompt quality.
4. Single-domain tasks under ~50 lines → handle directly. Else → delegate.

### Delegation Prompts
```
You are the [ROLE] on a LangChain/LangGraph project.

Project conventions:
- [paste relevant section from this CLAUDE.md]

Your task: [specific task description]

Constraints:
- All graphs use TypedDict state schemas (no Any types)
- All tools have complete docstrings
- LangSmith tracing must be preserved
- Return: code changes + summary of design decisions
```

### Agent Developer
Expertise: LangGraph state machines, LangChain tool/chain design, prompt engineering, ReAct/plan-and-execute patterns, callback handlers.
Constraints: every graph must have explicit state schema. Tools must have docstrings (LLM uses them). Prompts in `src/agents/prompts/`. Error handling in every node. Max recursion configurable.

### Integration Engineer
Expertise: FastAPI, LangSmith configuration, Docker, CI/CD, environment management, API design, auth middleware.
Constraints: all config via Pydantic settings. LANGCHAIN_TRACING_V2 always enabled. Health check at `/health`. API versioning in URL path.

### QA & Eval Engineer
Expertise: pytest, LangSmith evaluation framework, mock LLM patterns, test architecture, regression testing.
Constraints: mock all LLM calls in unit tests (FakeLLM). Integration tests use recorded responses. Eval datasets in `eval/datasets/`. Run existing tests before writing new code. Track eval metrics over time.
EOF

cat > "$TEMPLATES_DIR/ml-langchain/commands/trace.md" << 'EOF'
Check recent LangSmith traces:
1. List the 10 most recent runs from LangSmith
2. Identify any runs with errors or high latency (> 30s)
3. For failed runs, show the error message and which node failed
4. Summarize: total runs, success rate, avg latency
EOF

cat > "$TEMPLATES_DIR/ml-langchain/commands/team-review.md" << 'EOF'
Perform a full team review of recent changes:
1. As QA & Eval Engineer: run tests, check eval metrics for regression
2. As Agent Developer: review graph logic, tool definitions, prompt quality
3. As Integration Engineer: verify API contracts, tracing, config consistency
4. As Team Lead: synthesize into summary with action items
EOF

echo "[done] Created template: ml-langchain"

# ══════════════════════════════════════════════════════════════
# 5. TEMPLATE: ml-n8n
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/ml-n8n/commands"

cat > "$TEMPLATES_DIR/ml-n8n/CLAUDE.md" << 'EOF'
# ML/AI — n8n Workflow Automation

## Stack
- n8n (self-hosted via Docker) for workflow orchestration
- Python 3.11+ for custom logic (FastAPI microservices)
- Node.js for n8n custom nodes (when needed)
- PostgreSQL for n8n backend + application data
- Redis for caching and job queues

## Project Structure
```
├── CLAUDE.md
├── docker-compose.yml          # n8n + Postgres + Redis + app services
├── workflows/                  # Exported n8n workflow JSON files
│   ├── production/             # Active production workflows
│   └── templates/              # Reusable workflow templates
├── services/                   # Python microservices called by n8n
│   ├── ml-service/             # ML inference endpoints
│   ├── data-service/           # Data processing endpoints
│   └── shared/                 # Shared libraries
├── custom-nodes/               # Custom n8n nodes (TypeScript)
├── credentials/                # Credential type definitions (not secrets!)
├── config/                     # Environment configs
└── tests/
```

## n8n Conventions
- Every workflow exported to `workflows/` as JSON (version controlled)
- Workflow naming: `{domain}-{action}-{version}` (e.g., `orders-sync-v2`)
- Use sub-workflows for reusable logic (DRY principle)
- Error handling: every workflow must have an error trigger node
- Webhook endpoints: document in README with method, path, expected payload
- Credentials: use n8n credential store, never hardcode in workflow JSON

## Integration Patterns
- n8n → Python service: HTTP Request node to FastAPI endpoints
- Python service → n8n: webhook triggers for async callbacks
- Scheduled workflows: use Cron trigger, document schedule in workflow notes
- Data passing: prefer JSON payloads; binary data via temporary S3/MinIO URLs
- Rate limiting: implement in Python service, not n8n (more control)

## Python Service Rules
- Each service: independent FastAPI app with its own Dockerfile
- Pydantic models for all request/response schemas
- Health check endpoint at /health for Docker Compose
- Async handlers for any I/O-bound operations
- Structured logging (JSON format) for aggregation

## Testing
- n8n workflows: manual test via n8n UI, document test cases in workflow notes
- Python services: pytest (unit + integration)
- Integration: docker-compose test profile with mock external services
- Workflow validation: script to check all workflows have error handlers

## Commands
```bash
docker compose up -d                      # start everything
docker compose logs -f n8n                # n8n logs
docker compose exec n8n n8n export:workflow --all --output=workflows/  # export
poetry -C services/ml-service run pytest  # test ML service
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, integration architecture, review | Overall coordination |
| **Workflow Designer** | n8n workflow creation/modification, node config | `workflows/`, `custom-nodes/` |
| **Python Developer** | Microservice code, ML logic, API endpoints | `services/` |
| **QA & DevOps Engineer** | Testing, Docker, CI/CD, monitoring | `tests/`, `docker-compose.yml`, `config/` |

### Team Lead — Default Behavior
You ARE the Team Lead. You own integration architecture:
1. How n8n workflows connect to Python services (webhook contracts).
2. Data flow design between workflow nodes and microservices.
3. Simple changes within one domain → handle directly. Cross-domain → delegate.
4. Always verify workflow JSON exports are committed after changes.

### Delegation Prompts
```
You are the [ROLE] on an n8n + Python microservices project.

Project conventions:
- [paste relevant section from this CLAUDE.md]

Your task: [specific task description]

Constraints:
- Follow all conventions above
- Document any new webhook endpoints or workflow triggers
- Return: changes + summary of integration points affected
```

### Workflow Designer
Expertise: n8n workflow design, node configuration, sub-workflow patterns, error handling nodes, webhook/cron triggers, custom node development (TypeScript).
Constraints: every workflow has error trigger node. Export to `workflows/` after changes. Use sub-workflows for reuse. Document webhooks in README. Never hardcode credentials.

### Python Developer
Expertise: FastAPI, Pydantic, async Python, ML model serving, Docker.
Constraints: each service is independent FastAPI app with Dockerfile. Pydantic models for all schemas. Health check at `/health`. Async handlers for I/O. Structured JSON logging.

### QA & DevOps Engineer
Expertise: pytest, Docker Compose, CI/CD, monitoring, workflow validation scripts.
Constraints: run tests before deploying. Docker-compose test profile for integration tests. Validate all workflows have error handlers. Monitor service health endpoints.
EOF

cat > "$TEMPLATES_DIR/ml-n8n/commands/export-workflows.md" << 'EOF'
Export all n8n workflows to version control:
1. Run n8n export command via docker compose
2. Format JSON files for readable diffs
3. Show which workflows changed since last export
4. Remind to commit the changes
EOF

cat > "$TEMPLATES_DIR/ml-n8n/commands/team-review.md" << 'EOF'
Perform a full team review:
1. As QA & DevOps: run all Python service tests, check Docker health
2. As Workflow Designer: validate all workflows have error handlers, check exports are current
3. As Python Developer: review service code for async correctness, schema validation
4. As Team Lead: synthesize into summary with action items
EOF

echo "[done] Created template: ml-n8n"

# ══════════════════════════════════════════════════════════════
# 6. TEMPLATE: java-enterprise
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/java-enterprise/commands"

cat > "$TEMPLATES_DIR/java-enterprise/CLAUDE.md" << 'EOF'
# Enterprise Java Full-Stack Application

## Stack
- Java 21, Spring Boot 3.x
- Build: Gradle (Kotlin DSL), multi-module project
- Databases: PostgreSQL (primary OLTP), MongoDB (documents), Redis (cache)
- Messaging: Apache Kafka (event streaming), RabbitMQ (task/command queues)
- API: GraphQL (schema-first, DGS framework or Spring GraphQL)
- Frontend: React 18+, TypeScript, Apollo Client
- Containerization: Docker Compose (dev), Kubernetes (prod)

## Architecture
```
├── build.gradle.kts                # Root build file
├── settings.gradle.kts             # Module declarations
├── api-schema/                     # GraphQL schema (.graphqls files) — THE CONTRACT
├── modules/
│   ├── common/                     # Shared kernel (value objects, events, utils)
│   ├── domain-a/                   # Bounded context A (hexagonal architecture)
│   │   ├── src/main/java/.../
│   │   │   ├── adapter/
│   │   │   │   ├── in/web/         # GraphQL resolvers (driving adapters)
│   │   │   │   ├── in/messaging/   # Kafka/RabbitMQ consumers
│   │   │   │   ├── out/persistence/# JPA repositories, entities
│   │   │   │   ├── out/messaging/  # Kafka producers, RabbitMQ publishers
│   │   │   │   └── out/cache/      # Redis cache adapters
│   │   │   ├── application/        # Use cases / application services
│   │   │   ├── domain/             # Domain model (entities, value objects, events)
│   │   │   └── port/               # Port interfaces (in + out)
│   │   └── src/test/
│   └── domain-b/                   # Bounded context B (same structure)
├── infra/
│   ├── docker-compose.yml
│   ├── docker-compose.test.yml
│   └── k8s/
├── frontend/                       # React + TypeScript + Apollo
│   ├── src/
│   │   ├── generated/              # GraphQL codegen output (DO NOT EDIT)
│   │   ├── components/
│   │   ├── pages/
│   │   ├── graphql/                # .graphql operation files
│   │   └── hooks/
│   ├── codegen.ts
│   └── package.json
└── db/
    └── migration/                  # Flyway migrations (V001__, V002__, ...)
```

## Hexagonal Architecture Rules
- Domain layer: ZERO framework dependencies (no Spring annotations)
- Application layer: orchestrates domain; depends only on port interfaces
- Adapters: implement ports; all framework coupling lives here
- Never bypass the service/application layer from controllers/resolvers
- Dependencies flow inward: adapter → application → domain

## Database Conventions
- Flyway migrations: sequential numbering (V001__description.sql)
- All entities: audit fields (created_at, updated_at, created_by, version)
- JPA entities in adapter layer only; domain entities are plain POJOs
- No raw SQL in application code; use Spring Data repositories or jOOQ
- Redis cache keys: `{service}:{entity}:{id}`, TTL always explicit
- Cache strategy: cache-aside for reads; invalidate on write

## Messaging Conventions
- Kafka topics: `{domain}.{entity}.{event}` (e.g., orders.order.created)
- Kafka: Avro serialization with Schema Registry ← UPDATE if using JSON/Protobuf
- Every consumer MUST be idempotent (deduplicate by event ID)
- Dead-letter topics: `{original-topic}.DLT`
- Consumer groups: `{service-name}-{consumer-purpose}`
- RabbitMQ: use for command/reply patterns; Kafka for event streaming
- JMS: legacy only; wrap behind port interface for future migration

## GraphQL Conventions
- Schema-first: all types defined in `api-schema/*.graphqls`
- Schema is the contract between backend and frontend
- Codegen: backend (DGS codegen) + frontend (graphql-codegen)
- No REST endpoints except /actuator/** health checks
- Pagination: Relay-style connections (edges, nodes, pageInfo)
- Errors: use GraphQL errors with extensions for error codes

## Frontend Conventions
- All data fetching via Apollo Client (no direct REST)
- GraphQL operations in `src/graphql/` (.graphql files)
- Generated types in `src/generated/` — never edit manually
- Component library: ← UPDATE: MUI / Ant Design / shadcn
- State: Apollo cache for server state; Zustand for local UI state
- Testing: React Testing Library + MSW for GraphQL mocking

## Testing Pyramid
- Unit: JUnit 5 + Mockito, ≥80% coverage on application/domain layers
- Integration: Testcontainers (Postgres, Kafka, Redis, RabbitMQ)
- Contract: GraphQL schema validation in CI (no breaking changes)
- Frontend: RTL + MSW for component tests; Cypress for critical flows
- Performance: Gatling scripts for critical API paths ← optional

## Commands
```bash
./gradlew build                              # build all modules
./gradlew test                               # all tests
./gradlew :modules:domain-a:test             # single module tests
./gradlew bootRun -p modules/domain-a        # run single service
docker compose -f infra/docker-compose.yml up -d   # infra
cd frontend && npm install && npm run dev    # frontend
cd frontend && npm run codegen               # regenerate GraphQL types
./gradlew flywayMigrate                      # run DB migrations
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead / Architect** (default) | Planning, DDD decisions, cross-module coordination | Overall, `api-schema/` |
| **Java Backend Developer** | Spring Boot services, domain logic, hexagonal structure | `modules/` |
| **Frontend Developer** | React components, Apollo Client, GraphQL operations | `frontend/` |
| **Data & Messaging Engineer** | DB schemas, Flyway, Kafka, RabbitMQ, Redis | `db/`, adapter/out layers |
| **QA Engineer** | All testing, coverage, contract tests | `**/test/`, test configs |
| **DevOps / Release Engineer** | Docker, K8s, CI/CD, build config | `infra/`, Gradle files |

### Team Lead / Architect — Default Behavior
You ARE the Team Lead. You own the architecture:
1. Domain boundaries: which bounded context owns which entity/event.
2. GraphQL schema changes: you modify `api-schema/`, then delegate implementation.
3. Cross-cutting concerns (auth, logging, error handling) → handle directly or coordinate.
4. Single-module, single-layer tasks → handle directly. Cross-module → delegate.
5. After any schema change, trigger both Backend and Frontend agents to update codegen.

### Delegation Prompts
```
You are the [ROLE] on an enterprise Java full-stack project.

Architecture: Hexagonal (ports & adapters) within DDD bounded contexts.
API: GraphQL schema-first. Schema in api-schema/*.graphqls is THE CONTRACT.
Messaging: Kafka for events, RabbitMQ for commands.

Your task: [specific task description]

Constraints:
- Domain layer has ZERO framework dependencies
- Dependencies flow inward: adapter → application → domain
- Never bypass the application layer
- [role-specific constraints below]
- Return: code changes + summary of what was changed and why
```

### Java Backend Developer
Expertise: Spring Boot 3, JPA/Hibernate, DGS/Spring GraphQL resolvers, Kafka/RabbitMQ producers and consumers, hexagonal architecture, domain modeling.
Constraints: domain layer = plain POJOs (no Spring annotations). JPA entities in adapter layer only. All business logic in application services (not resolvers or consumers). Every public method in application layer must be tested.

### Frontend Developer
Expertise: React 18+, TypeScript, Apollo Client, GraphQL operations, component architecture, responsive design, state management (Apollo cache + Zustand).
Constraints: all data via Apollo Client (no REST). GraphQL operations in `src/graphql/`. Never edit `src/generated/` (codegen output). Run `npm run codegen` after schema changes. Component tests with RTL + MSW.

### Data & Messaging Engineer
Expertise: PostgreSQL, MongoDB, Redis, Flyway migrations, Kafka (Avro, Schema Registry, consumer groups, DLT), RabbitMQ (exchanges, queues, bindings), jOOQ.
Constraints: all schema changes via Flyway migration files. Every Kafka consumer must be idempotent (event ID dedup). Redis keys follow `{service}:{entity}:{id}` pattern with explicit TTL. Dead-letter queues for all consumers. Test with Testcontainers.

### QA Engineer
Expertise: JUnit 5, Mockito, Testcontainers, React Testing Library, MSW, Cypress, GraphQL contract testing, Gatling.
Constraints: run existing tests first. Unit test coverage ≥80% on application/domain. Integration tests use Testcontainers (never real external services). Contract tests validate GraphQL schema backward compatibility. Frontend tests mock GraphQL via MSW.

### DevOps / Release Engineer
Expertise: Docker, Docker Compose, Kubernetes manifests, Gradle build optimization, CI/CD pipelines, health checks, monitoring.
Constraints: every service has Dockerfile + health endpoint. Docker Compose for local dev must start all deps. K8s manifests in `infra/k8s/`. Build must pass all tests before release. Tag releases with semantic versioning.
EOF

cat > "$TEMPLATES_DIR/java-enterprise/commands/build.md" << 'EOF'
Full build and verification:
1. Run ./gradlew clean build
2. Run all unit tests
3. Run integration tests with Testcontainers
4. Check for any deprecation warnings
5. Report: build status, test counts (pass/fail), coverage summary
EOF

cat > "$TEMPLATES_DIR/java-enterprise/commands/new-module.md" << 'EOF'
Scaffold a new bounded context module. Ask for:
1. Module name (kebab-case)
2. Base package name
Then create:
- modules/{name}/build.gradle.kts with standard dependencies
- Hexagonal package structure: adapter/(in/out), application, domain, port
- A placeholder domain entity, port interface, and application service
- Unit test skeleton
- Add module to settings.gradle.kts
EOF

cat > "$TEMPLATES_DIR/java-enterprise/commands/db-migrate.md" << 'EOF'
Create a new database migration:
1. Find the latest migration number in db/migration/
2. Ask what the migration should do
3. Create the next numbered migration file (V{N+1}__description.sql)
4. Write the SQL (with rollback comment block)
5. Run ./gradlew flywayMigrate to apply
6. Verify with flywayInfo
EOF

cat > "$TEMPLATES_DIR/java-enterprise/commands/team-review.md" << 'EOF'
Perform a full team review of recent changes:
1. As QA Engineer: run ./gradlew test, report coverage + failures
2. As Java Backend Developer: review domain logic, hexagonal boundary compliance
3. As Frontend Developer: verify codegen is current, check component tests
4. As Data & Messaging Engineer: verify migration consistency, consumer idempotency
5. As DevOps: check Docker builds, health endpoints, k8s manifests
6. As Team Lead: synthesize all findings into prioritized action items
EOF

cat > "$TEMPLATES_DIR/java-enterprise/commands/new-feature.md" << 'EOF'
Implement a new feature end-to-end. Ask for:
1. Feature description
2. Which bounded context(s) it belongs to
Then coordinate the team:
- Team Lead: update GraphQL schema in api-schema/
- Java Backend Developer: implement resolvers, services, domain logic
- Data & Messaging Engineer: create migrations, set up events if needed
- Frontend Developer: add GraphQL operations, build UI components
- QA Engineer: write tests at every layer
- DevOps: update Docker/k8s if new services needed
Present implementation plan before starting.
EOF

echo "[done] Created template: java-enterprise"

# ══════════════════════════════════════════════════════════════
# 7. TEMPLATE: web-static
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/web-static/commands"

cat > "$TEMPLATES_DIR/web-static/CLAUDE.md" << 'EOF'
# Static Website

## Stack
- Framework: Astro ← UPDATE: Astro / Next.js (static export) / Hugo / 11ty
- Styling: Tailwind CSS
- Content: Markdown/MDX files in content/
- Deployment: Vercel ← UPDATE: Vercel / Netlify / Cloudflare Pages
- CMS: None (file-based) ← UPDATE if using headless CMS

## Project Structure
```
├── CLAUDE.md
├── src/
│   ├── pages/            # Route-based pages
│   ├── layouts/          # Page layouts (base, blog, landing)
│   ├── components/       # Reusable UI components
│   └── styles/           # Global styles + Tailwind config
├── content/              # Markdown/MDX content files
│   ├── blog/
│   └── pages/
├── public/               # Static assets (images, fonts, favicons)
└── astro.config.mjs
```

## Conventions
- All content in Markdown/MDX with frontmatter metadata
- Images: optimized at build time; use framework's image component
- SEO: every page must have title, description, og:image meta tags
- Performance budget: Lighthouse score ≥ 95 on all categories
- Accessibility: semantic HTML, ARIA labels, keyboard navigation
- No client-side JS unless absolutely necessary (progressive enhancement)

## Content Rules
- Blog posts: frontmatter must include title, date, description, tags
- Internal links: use relative paths, never absolute URLs to own domain
- Images: always include alt text; prefer WebP format
- Code blocks: always specify language for syntax highlighting

## Mobile Support
- Mobile-first responsive design (min-width breakpoints)
- Touch targets: minimum 44x44px
- Test at: 320px, 375px, 768px, 1024px, 1440px
- No horizontal scrolling at any breakpoint

## Commands
```bash
npm install
npm run dev                  # local dev server
npm run build                # production build
npm run preview              # preview production build
npx lighthouse http://localhost:4321 --view   # performance audit
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, site architecture, content strategy | Overall coordination |
| **Frontend Developer** | Components, layouts, styling, interactivity | `src/` |
| **Content & SEO Specialist** | Content structure, metadata, accessibility, performance | `content/`, SEO meta |
| **QA Engineer** | Cross-browser testing, Lighthouse audits, accessibility checks | Testing |

### Team Lead — Default Behavior
You ARE the Team Lead. Static sites are simpler, so you handle most tasks directly.
Delegate only when a task is heavily specialized (e.g., complex animation, SEO audit).

### Frontend Developer
Expertise: Astro/Next.js components, Tailwind CSS, responsive design, progressive enhancement, build optimization.
Constraints: no client-side JS unless essential. Mobile-first breakpoints. Semantic HTML. Components must be accessible (ARIA).

### Content & SEO Specialist
Expertise: content structure, frontmatter schemas, meta tags, Open Graph, structured data (JSON-LD), Lighthouse optimization, accessibility auditing.
Constraints: every page has title + description + og:image. Alt text on all images. Lighthouse ≥ 95. No broken internal links.

### QA Engineer
Expertise: cross-browser testing, responsive testing, Lighthouse CI, accessibility auditing (axe-core), link validation.
Constraints: test at all 5 breakpoints. Run Lighthouse after every significant change. Validate HTML semantics. Check all links.
EOF

cat > "$TEMPLATES_DIR/web-static/commands/team-review.md" << 'EOF'
Perform a full team review:
1. As QA: run build, check for warnings, run Lighthouse audit
2. As Content & SEO: verify all pages have proper meta tags, check alt texts
3. As Frontend Developer: review component accessibility, responsive behavior
4. As Team Lead: summarize findings with action items
EOF

echo "[done] Created template: web-static"

# ══════════════════════════════════════════════════════════════
# 8. TEMPLATE: web-dynamic
# ══════════════════════════════════════════════════════════════

mkdir -p "$TEMPLATES_DIR/web-dynamic/commands"

cat > "$TEMPLATES_DIR/web-dynamic/CLAUDE.md" << 'EOF'
# Dynamic Web Application

## Stack
- Framework: Next.js 14+ (App Router) ← UPDATE: Next.js / Remix / Nuxt
- Language: TypeScript (strict mode)
- Styling: Tailwind CSS + shadcn/ui components
- Database: PostgreSQL via Prisma ORM ← UPDATE per project
- Auth: NextAuth.js ← UPDATE: NextAuth / Clerk / Auth0
- Deployment: Vercel ← UPDATE per project
- API: tRPC for type-safe API ← UPDATE: tRPC / REST / GraphQL

## Project Structure
```
├── CLAUDE.md
├── src/
│   ├── app/                    # Next.js App Router pages + layouts
│   │   ├── (auth)/             # Auth-required route group
│   │   ├── (public)/           # Public route group
│   │   ├── api/                # API routes (or tRPC router)
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── components/
│   │   ├── ui/                 # Base UI components (shadcn)
│   │   └── features/           # Feature-specific components
│   ├── lib/                    # Utilities, config, helpers
│   ├── server/                 # Server-only code
│   │   ├── db/                 # Prisma client + helpers
│   │   ├── auth/               # Auth configuration
│   │   └── services/           # Business logic
│   └── types/                  # Shared TypeScript types
├── prisma/
│   ├── schema.prisma
│   └── migrations/
├── public/
└── tests/
```

## Architecture Rules
- Server Components by default; Client Components only when needed (interactivity)
- Data fetching in Server Components or Route Handlers; never in Client Components
- Business logic in src/server/services/; components should be thin
- Type safety end-to-end: DB schema → Prisma types → API → frontend
- Environment variables: validate with zod at startup, never use raw process.env

## Database Conventions
- Prisma as ORM; migrations via `prisma migrate`
- All models: id (cuid), createdAt, updatedAt fields
- Use Prisma transactions for multi-step operations
- Soft delete preferred (deletedAt field) over hard delete
- Index any field used in WHERE or ORDER BY queries

## Auth & Security
- Auth check at layout level for protected route groups
- API routes: validate auth + permissions before processing
- CSRF protection on all mutation endpoints
- Input validation: zod schemas on all API inputs
- Rate limiting on auth endpoints

## Mobile Support
- Responsive-first design using Tailwind breakpoints (sm/md/lg/xl)
- Touch targets: minimum 44x44px
- PWA support: manifest.json + service worker ← optional, UPDATE if needed
- Test at: 320px, 375px, 768px, 1024px, 1440px
- Bottom navigation pattern for mobile; sidebar for desktop

## Testing
- Unit: Vitest for utilities and server logic
- Component: React Testing Library
- Integration: Playwright for critical user flows
- API: supertest or direct tRPC caller tests

## Commands
```bash
npm install
npm run dev                              # dev server
npm run build && npm start               # production
npx prisma migrate dev                   # apply migrations
npx prisma studio                        # DB GUI
npx playwright test                      # e2e tests
npm run test                             # unit + component tests
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead / Architect** (default) | Planning, feature design, API contracts, code review | Overall, `src/types/` |
| **Frontend Developer** | React components, pages, styling, client interactivity | `src/app/`, `src/components/` |
| **Backend Developer** | API routes, services, auth, DB operations | `src/server/`, `prisma/`, `src/app/api/` |
| **QA Engineer** | Testing at all layers, Playwright e2e, accessibility | `tests/` |
| **DevOps / Release Engineer** | Deployment, CI/CD, environment config, performance | Vercel/infra config |

### Team Lead / Architect — Default Behavior
You ARE the Team Lead. You own the contract between frontend and backend:
1. API design: tRPC router shape, or REST endpoint contracts, or GraphQL schema.
2. Feature decomposition: split into frontend + backend tasks, delegate accordingly.
3. Type definitions in `src/types/` are shared — you maintain them.
4. Single-layer changes → handle directly. Full-stack features → delegate.

### Delegation Prompts
```
You are the [ROLE] on a Next.js full-stack application.

Architecture: App Router, Server Components by default. tRPC/REST for API.
DB: PostgreSQL via Prisma. Auth: NextAuth.js. Styling: Tailwind + shadcn.

Your task: [specific task description]

Constraints:
- TypeScript strict mode, no `any` types
- Server Components by default; 'use client' only when needed
- Business logic in src/server/services/ (not in components)
- [role-specific constraints below]
- Return: code changes + summary
```

### Frontend Developer
Expertise: React 18+ (Server/Client Components), Next.js App Router, Tailwind CSS, shadcn/ui, responsive design, form handling, loading/error states.
Constraints: Server Components by default. 'use client' only for interactivity (hooks, event handlers). No data fetching in Client Components. Use Suspense for loading states. All inputs validated with zod. Responsive at all breakpoints.

### Backend Developer
Expertise: Next.js API routes, tRPC, Prisma ORM, NextAuth, zod validation, server-only utilities, middleware.
Constraints: all inputs validated with zod before processing. Auth checked before any data access. Prisma transactions for multi-step ops. No raw SQL. Soft delete by default. Environment vars validated at startup.

### QA Engineer
Expertise: Vitest, React Testing Library, Playwright, accessibility testing, API testing, load testing.
Constraints: unit tests for all server services (Vitest). Component tests with RTL. E2e tests in Playwright for critical flows (auth, CRUD, checkout). Check responsive at all breakpoints. Accessibility audit with axe-core.

### DevOps / Release Engineer
Expertise: Vercel deployment, environment management, CI/CD, Prisma migration deployment, monitoring, performance optimization.
Constraints: all env vars documented. Prisma migrations run automatically on deploy. Preview deployments for all PRs. Lighthouse performance budget ≥ 90. Error tracking configured (Sentry or similar).
EOF

cat > "$TEMPLATES_DIR/web-dynamic/commands/db-migrate.md" << 'EOF'
Create and apply a database migration:
1. Ask what schema change is needed
2. Edit prisma/schema.prisma
3. Run npx prisma migrate dev --name {description}
4. Verify migration SQL looks correct
5. Update any affected TypeScript types
6. Run tests to check for breaking changes
EOF

cat > "$TEMPLATES_DIR/web-dynamic/commands/team-review.md" << 'EOF'
Perform a full team review of recent changes:
1. As QA: run all tests (unit, component, e2e), report coverage and failures
2. As Backend Developer: review API routes, auth checks, DB queries
3. As Frontend Developer: check responsive behavior, component accessibility
4. As DevOps: verify build succeeds, check bundle size, preview deployment
5. As Team Lead: synthesize into prioritized action items
EOF

cat > "$TEMPLATES_DIR/web-dynamic/commands/new-feature.md" << 'EOF'
Implement a new feature end-to-end. Ask for:
1. Feature description
2. Whether it needs auth
3. What data it needs (new models? existing?)
Then coordinate the team:
- Team Lead: design API contract + shared types
- Backend Developer: implement API + services + migrations
- Frontend Developer: build pages + components
- QA Engineer: write tests at every layer
Present implementation plan before starting.
EOF

echo "[done] Created template: web-dynamic"

# ══════════════════════════════════════════════════════════════
# 9. INSTALL LAUNCHER SCRIPT
# ══════════════════════════════════════════════════════════════

mkdir -p "$HOME/.local/bin"

if [[ -f "$LAUNCHER_SOURCE" ]]; then
    # Resolve both paths to avoid "identical file" error when re-running
    RESOLVED_SOURCE=$(cd "$(dirname "$LAUNCHER_SOURCE")" && pwd)/$(basename "$LAUNCHER_SOURCE")
    RESOLVED_TARGET=$(cd "$(dirname "$LAUNCHER_TARGET")" 2>/dev/null && pwd)/$(basename "$LAUNCHER_TARGET") 2>/dev/null || RESOLVED_TARGET=""
    if [[ "$RESOLVED_SOURCE" == "$RESOLVED_TARGET" ]]; then
        echo ""
        echo "[skip] claude-code launcher already up to date at $LAUNCHER_TARGET"
    else
        cp "$LAUNCHER_SOURCE" "$LAUNCHER_TARGET"
        chmod +x "$LAUNCHER_TARGET"
        echo ""
        echo "[done] Installed claude-code launcher to $LAUNCHER_TARGET"
    fi
else
    echo ""
    echo "[skip] claude-code launcher not found at $LAUNCHER_SOURCE"
    echo "       Copy it manually to $LAUNCHER_TARGET"
fi

# ══════════════════════════════════════════════════════════════
# 10. GLOBAL HOOKS
# ══════════════════════════════════════════════════════════════

HOOKS_SOURCE="$(dirname "$0")/.claude/hooks"
HOOKS_TARGET="$CLAUDE_DIR/hooks"

mkdir -p "$HOOKS_TARGET"

if [[ -d "$HOOKS_SOURCE" ]]; then
    cp "$HOOKS_SOURCE/notify.sh" "$HOOKS_TARGET/notify.sh"
    cp "$HOOKS_SOURCE/verify-after-edit.sh" "$HOOKS_TARGET/verify-after-edit.sh"
    cp "$HOOKS_SOURCE/verify-on-stop.sh" "$HOOKS_TARGET/verify-on-stop.sh"
    cp "$HOOKS_SOURCE/auto-format.sh" "$HOOKS_TARGET/auto-format.sh"
    cp "$HOOKS_SOURCE/protect-files.sh" "$HOOKS_TARGET/protect-files.sh"
    cp "$HOOKS_SOURCE/reinject-context.sh" "$HOOKS_TARGET/reinject-context.sh"
    chmod +x "$HOOKS_TARGET"/*.sh
    echo "[done] Installed hooks to $HOOKS_TARGET"
else
    echo "[skip] Hook scripts not found at $HOOKS_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 10b. GLOBAL AGENTS
# ══════════════════════════════════════════════════════════════

AGENTS_SOURCE="$(dirname "$0")/.claude/agents"
AGENTS_TARGET="$CLAUDE_DIR/agents"

mkdir -p "$AGENTS_TARGET"

if [[ -d "$AGENTS_SOURCE" ]]; then
    cp "$AGENTS_SOURCE"/*.md "$AGENTS_TARGET/" 2>/dev/null || true
    echo "[done] Installed agents to $AGENTS_TARGET"
else
    echo "[skip] Agent definitions not found at $AGENTS_SOURCE"
fi

# ══════════════════════════════════════════════════════════════
# 11. GLOBAL SETTINGS (hooks wiring)
# ══════════════════════════════════════════════════════════════

SETTINGS_FILE="$CLAUDE_DIR/settings.json"
HOOKS_CONFIG='{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/protect-files.sh",
            "timeout": 5000
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/verify-on-stop.sh",
            "timeout": 180000
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/verify-after-edit.sh",
            "timeout": 30000
          },
          {
            "type": "command",
            "command": "~/.claude/hooks/auto-format.sh",
            "timeout": 15000
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/notify.sh",
            "timeout": 10000
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/reinject-context.sh",
            "timeout": 10000
          }
        ]
      }
    ]
  }
}'

if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo "$HOOKS_CONFIG" > "$SETTINGS_FILE"
    echo "[done] Created $SETTINGS_FILE with hooks"
elif command -v jq &>/dev/null; then
    # Check if hooks key already exists
    HAS_HOOKS=$(jq 'has("hooks")' "$SETTINGS_FILE" 2>/dev/null)
    if [[ "$HAS_HOOKS" == "true" ]]; then
        echo "[skip] $SETTINGS_FILE already has hooks configured (not overwriting)"
    else
        # Add hooks key, preserve everything else (permissions, etc.)
        EXISTING=$(cat "$SETTINGS_FILE")
        MERGED=$(echo "$EXISTING" | jq --argjson hooks "$(echo "$HOOKS_CONFIG" | jq '.hooks')" '. + {hooks: $hooks}')
        echo "$MERGED" > "$SETTINGS_FILE"
        echo "[done] Added hooks to existing $SETTINGS_FILE"
    fi
else
    echo "[WARN] $SETTINGS_FILE already exists and jq is not installed for safe merge."
    echo "       Add the hooks configuration manually. See docs/hooks-guide.md"
fi

# ══════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Templates created (all with Agent Team configs):"
for dir in "$TEMPLATES_DIR"/*/; do
    type_name=$(basename "$dir")
    # Count team roles from CLAUDE.md (roles appear as "| **Role** |" in tables)
    roles=$(grep -c '| \*\*' "$dir/CLAUDE.md" 2>/dev/null || echo "?")
    printf "  %-20s (%s agent roles)\n" "$type_name" "$roles"
done
echo ""
echo "Quick start:"
echo "  claude-code list                              # see all templates"
echo "  claude-code init java-enterprise ~/projects/my-app"
echo "  claude-code ~/projects/my-app                 # start Claude session"
echo ""
echo "Global hooks installed (active in all projects):"
echo "  - verify-on-stop.sh    — runs tests when Claude finishes"
echo "  - verify-after-edit.sh — runs type checker after source edits"
echo "  - auto-format.sh       — runs formatter after source edits"
echo "  - protect-files.sh     — blocks edits to .env, *.lock, .git/, credentials"
echo "  - reinject-context.sh  — re-injects project context on session start"
echo "  - notify.sh            — desktop notifications when Claude needs input"
echo ""
echo "Custom agents installed:"
echo "  - code-simplifier      — post-build code cleanup (read + edit)"
echo "  - verify-app           — end-to-end project verification (read + bash)"
echo "  - security-review      — vulnerability scanning (read-only)"
echo "  - doc-writer           — documentation updates (read + edit + write)"
echo "  - phase-recap          — phase recap generation (read + bash)"
echo ""
echo "Each project now includes:"
echo "  - CLAUDE.md with stack, conventions, and Agent Team config"
echo "  - /project:team-review command for full team review"
echo "  - Role-specific delegation prompts for the Task tool"
echo ""
echo "Remember to customize each project's CLAUDE.md after init!"
echo "Look for ← UPDATE comments for project-specific values."
echo ""
