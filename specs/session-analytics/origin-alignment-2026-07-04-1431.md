# Origin alignment check — session-analytics

Origin: https://github.com/gosha70/code-copilot-team/issues/63

Origin claim:
> Issue #63 asks for a session analytics & process-mining pipeline mirroring
> the (now-unreachable) kiro-analyzer: ingest Claude Code + other copilot
> sessions into PostgreSQL + an embedded Kùzu knowledge graph, run an
> LLM-as-Judge heuristic pass over turns, expose an MCP server, and surface a
> rich Next.js Studio UI (Dashboard, 5-step Analysis wizard, Knowledge-Graph
> explorer, Settings, Agents, Session Detail with Insights/Agent-Tuning/
> Prompt-Coaching). Enhancements E1–E10 are "prioritized separately".
> Acceptance criteria include: "Privacy: no session content leaves the local
> machine unless explicitly configured." User-confirmed scope decisions
> (2026-05-29 planning session): deliver P1–P6 as ONE cohesive PR; E1–E10 are
> designed as extension points, not built; stores are PostgreSQL + embedded
> Kùzu exactly as the issue specifies; full rich Studio UI as described.

Working claim:
> The working tree delivers `scripts/session_analytics/` — a Python 3.11
> package with a `scripts/session-analytics` CLI (verbs: setup, list, ingest,
> doctor, analyze, kpis, graph, mcp, serve), a Claude Code JSONL adapter (DAG
> walker handling thinking blocks, sidechains, non-conversational line types)
> plus an Aider adapter as the second copilot, an idempotent relational store
> (PostgreSQL DDL, SQLite test dialect), an embedded Kùzu knowledge graph
> (Session→Turn→ToolInvocation→FileNode→ErrorNode + Workspace/Agent/Model/
> Copilot nodes), an LLM-as-Judge runner (12 boolean labels + sentiment + 1–5
> quality) with session KPIs, an MCP stdio server (search_sessions /
> get_session_details / analyze_patterns / compare_approaches tools;
> recent-errors / tool-stats / session-summary resources), a FastAPI backend,
> and the Next.js `studio/` UI (Dashboard, Sessions + Session Detail, Graph
> explorer with Cytoscape + Cypher IDE, 5-step Analysis wizard, Settings,
> Agents). The packaged default judge is local-only Ollama — a no-flag
> `analyze` sends nothing off the machine; the `claude-code` (Anthropic) and
> `openai` judges are explicit opt-ins via `--judge` / `.env` / Settings.
> CI smoke workflow and a unit suite are included. All ten issue acceptance
> criteria map to delivered, tested components.

Mismatches:
  - Issue phase P4 names a "Kiro CLI adapter"; the build ships Aider as the
    second adapter instead. Documented as an explicit Non-Goal in spec.md
    (upstream kiro-analyzer owns Kiro ingestion; schema stays copilot-
    agnostic). The issue's own acceptance criterion — "At least 2 copilot
    adapters working (Claude Code + one other)" — is satisfied.
  - The issue's premise "CCT already uses PostgreSQL in benchmarks" was
    verified false; Postgres is introduced here via docker-compose. Recorded
    as a documented deviation in the spec's origin block.
  - E1–E10 not implemented — matches the origin itself ("prioritized
    separately"); extension points (schema columns, redaction hooks,
    incremental ingestion) are present.
  - (Resolved 2026-07-04) Pre-review, the packaged default judge was
    `claude-code`, which violated the privacy acceptance criterion — a
    no-flag `analyze` would have sent redacted previews to Anthropic. Fixed
    in review: default is now local-only Ollama across defaults.json, the
    config fallback, guided setup, docs, and tests; cloud judges require
    explicit configuration.

Verdict: aligned
Confidence: high

Checked 2026-07-04 by re-reading issue #63 in full (gh issue view 63),
spec.md/plan.md/tasks.md, and the working tree on branch
feat/session-analytics-63 after the privacy-default fix and the CI-driven
spec-conformance edits (headers renamed to User Scenarios / Requirements,
Constraints section added — content unchanged in substance). Supersedes
origin-alignment-2026-07-04-1401.md.
