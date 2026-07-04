# session_analytics — copilot session analytics & process-mining pipeline.
#
# Ingests Claude Code (and Aider) session data into PostgreSQL + an
# embedded Kùzu knowledge graph, runs an LLM-as-Judge heuristic pass over
# turns, exposes an MCP server, and serves a Next.js Studio UI.
#
# See specs/session-analytics/spec.md for the feature spec and plan.md for
# the build milestones. Mirrors the structure of ``benchmark_runner``.
