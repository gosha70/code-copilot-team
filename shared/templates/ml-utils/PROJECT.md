# ML/AI — Headless Utility / MCP Tool Server

## Stack
- Python 3.11+, dependency management via Poetry (or pip with pyproject.toml)
- MCP SDK (stdio + Streamable HTTP) as primary interface
- FastAPI for admin/debug API (optional, secondary)
- Vector store: Chroma (dev) / Qdrant or pgvector (prod) — UPDATE per project
- Embeddings: sentence-transformers or Voyage Code — UPDATE per project
- Code parsing: tree-sitter (language-agnostic AST)
- Code quality: Ruff (linter + formatter), mypy strict (type checker)

## Project Structure
```
src/<package>/
├── mcp/                  # MCP server entry point + tool definitions
│   ├── server.py         # Server lifecycle, tool registration
│   └── tools/            # One module per tool group
├── core/                 # Domain logic (no framework deps)
│   ├── models.py         # Domain entities and value objects
│   ├── services.py       # Business logic / use cases
│   └── ports.py          # Abstract interfaces (protocols)
├── storage/              # Persistence adapters (implement protocols from core/ports.py)
│   ├── vector.py         # Vector store backend adapters (Chroma, Qdrant, pgvector)
│   ├── document.py       # Document/artifact store adapter
│   └── migrations/       # Schema migrations (if relational)
├── retrieval/            # Search and retrieval pipeline
│   ├── chunking.py       # Chunking strategies (AST-aware, token-based)
│   ├── embeddings.py     # Embedding model abstraction
│   ├── search.py         # Hybrid search (dense + sparse + fusion)
│   └── reranking.py      # Cross-encoder reranking
├── api/                  # FastAPI admin endpoints (optional)
│   ├── app.py            # FastAPI instance + middleware
│   ├── routes/           # Admin/debug route handlers
│   └── models.py         # Pydantic request/response schemas
├── config.py             # Pydantic settings (env vars, defaults)
└── __init__.py           # Package version + public API
tests/
├── unit/                 # Component-level tests
├── integration/          # Multi-component tests (real vector DB)
└── e2e/                  # End-to-end MCP client tests
eval/                     # Retrieval evaluation datasets + harnesses
prompts/                  # Versioned YAML prompt templates
specs/                    # SDD artifacts and lessons learned
```

## Architecture Rules
> **Non-negotiable.** Violations must be flagged during review, not silently accepted.

- **Ports and adapters**: domain logic in `core/` depends on protocols, never on concrete backends
- **MCP-first**: the MCP server is the primary interface; FastAPI is secondary (admin, debug, health)
- **Protocol-based abstractions**: vector stores, embedding models, chunking strategies all defined as protocols
- **Reference-based returns**: MCP tools return IDs + previews, not full content — callers request full content explicitly
- **Hybrid search by default**: dense + sparse (BM25) with configurable fusion (RRF)
- **Configuration-driven**: models, backends, chunk sizes, search params all configurable via env vars and config
- **No frontend**: this is a headless service/library — no UI code in this repo

## Key Conventions
- All LLM calls: wrapped with tracing (latency, token count, cost)
- Embedding model: pinned in config, never hardcoded
- Chunking: strategy + chunk_size + overlap configurable via settings
- All retrieval results must include source references (IDs, scores, metadata)
- Type annotations on all public functions; mypy strict mode
- Health check at `/health` (FastAPI) and via MCP resource
- YAML for prompt templates; never inline prompt strings

## MCP Server Rules
- Tool definitions must be concise — minimize token footprint in client context windows
- Each tool: clear name, one-sentence description, typed parameters with defaults
- Tools return structured JSON with `ref_id`, `preview`, `score`, `token_count` fields
- Full content retrieval is a separate tool call (by ref_id), never automatic
- Server must support both stdio (local) and Streamable HTTP (remote) transports
- Tool count target: < 10 tools total — consolidate related operations into parameterized tools

## Storage Rules
- Vector store backends implement the `VectorStorePort` protocol (upsert, search, delete, hybrid_search)
- Deduplication by content hash (SHA-256) on upsert
- Per-project collection isolation (collection name includes project identifier)
- Metadata on every stored item: `project_id`, `timestamp`, `type`, `source`, `hash`, `token_count`
- TTL/eviction policies are type-dependent, configurable per project

## Testing
- `pytest` with markers (`unit`, `integration`, `e2e`, `slow`)
- Mock vector stores in unit tests (use in-memory adapter)
- Integration tests hit a real Chroma/Qdrant instance
- E2E tests: MCP client → server round-trip
- Retrieval eval: recall@k, precision@k, MRR on labeled dataset in `eval/`
- Coverage target: >= 80% on `core/` and `retrieval/`

## Commands
```bash
poetry install                                              # deps
poetry run pytest --tb=short -q                             # tests
poetry run pytest -m "not slow" --tb=short -q               # fast tests
poetry run python -m src.<package>.mcp.server               # MCP server (stdio)
poetry run uvicorn src.<package>.api.app:app --reload        # admin API
ruff check . && mypy src/                                   # lint + type check
```

## Agent Team

### Roles

| Role | Trigger | Owns |
|------|---------|------|
| **Team Lead** (default) | Planning, architecture decisions, API contracts, code review | Overall coordination, `core/` |
| **MCP Engineer** | MCP tool definitions, server lifecycle, transport config, client integration | `mcp/` |
| **Retrieval Engineer** | Chunking, embeddings, search pipeline, hybrid retrieval, reranking | `retrieval/`, `prompts/` |
| **Storage Engineer** | Vector store adapters, persistence, migrations, deduplication | `storage/` |
| **QA Engineer** | Testing at all layers, coverage, eval harness, CI | `tests/`, `eval/` |

### Team Lead — Default Behavior
You ARE the Team Lead. For every user request:
1. Assess complexity. Single-domain, single-layer changes -> handle directly.
2. Multi-layer or >50 lines of specialized code -> delegate to specialist sub-agent.
3. Always review sub-agent output against project conventions before presenting.
4. Coordinate when a task spans layers (e.g., new MCP tool needs mcp/ + retrieval/ + storage/ + tests).
5. Own domain entities and cross-cutting concerns (config, error handling, protocols).

### Delegation Prompts
When spawning a sub-agent via Task tool, use this pattern:
```
You are the [ROLE] on a headless ML utility / MCP tool server project.

Architecture: Ports and adapters. Domain logic in core/ depends on protocols only.
Primary interface: MCP server. Secondary: FastAPI admin API.
Storage: pluggable vector store backends behind VectorStorePort protocol.

Project conventions:
- [paste relevant section from this CLAUDE.md]

Your task: [specific task description]

Constraints:
- Follow all conventions above
- Type-annotated Python with mypy strict compliance
- Do NOT modify files outside your ownership area without noting it
- Return: code changes + brief summary of decisions made
```

### MCP Engineer
Expertise: MCP protocol (JSON-RPC 2.0), tool definition, stdio/HTTP transports, MCP resources and subscriptions, client integration patterns.
Constraints: keep tool count under 10. Concise tool descriptions (minimize context window footprint). Structured JSON responses with ref_id + preview pattern. Both stdio and Streamable HTTP must work. Test with a real MCP client.

### Retrieval Engineer
Expertise: chunking strategies (AST-aware, token-based), embedding models, hybrid search (dense + BM25 + RRF fusion), cross-encoder reranking, retrieval evaluation.
Constraints: never hardcode model names; use config. Hybrid search is always the default. Reranking step required before final context assembly. All retrieval results include source metadata. Prompts in YAML files.

### Storage Engineer
Expertise: vector databases (Chroma, Qdrant, pgvector), schema design, migrations, deduplication, backup/restore, collection management.
Constraints: all backends implement VectorStorePort protocol. Dedup by content hash. Per-project collection isolation. Metadata requirements enforced at the adapter level. Integration tests against real backends.

### QA Engineer
Expertise: pytest, test architecture, mocking, MCP client testing, retrieval evaluation, CI/CD pipeline.
Constraints: run existing tests before writing new ones. Mock all external APIs in unit tests. Use pytest markers for test categories. Coverage >= 80% on core/ and retrieval/. E2E tests via MCP client round-trip.
