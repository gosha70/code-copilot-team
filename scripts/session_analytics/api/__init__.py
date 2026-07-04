# session_analytics.api — FastAPI layer that the Next.js Studio calls.
#
# The Studio is pure presentation and never opens a DB directly (Kùzu is
# embedded/single-writer). All reads go through this API over 127.0.0.1. The
# aggregate logic lives in dashboard.py (pure DB, unit-tested without FastAPI);
# server.py wires it + the MCP tools + the graph query helpers into routes.
