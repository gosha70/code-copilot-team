# session_analytics.mcp — MCP server exposing the session history.
#
# The queryable logic lives in tools.py / resources.py (plain DB-backed
# functions, unit-tested without the MCP SDK). server.py is a thin adapter
# that lazily imports the `mcp` package and wires those functions to an MCP
# stdio server.
