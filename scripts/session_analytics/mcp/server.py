# session_analytics.mcp.server — FastMCP adapter over tools.py / resources.py.
#
# Lazily imports the `mcp` SDK so importing this module (and the unit suite)
# does not require it. Each tool/resource call opens a short-lived DB
# connection against the configured DSN — read-only, local.

from __future__ import annotations

from typing import Any

from ..config import load_config
from ..relational.db import Database
from . import resources, tools

SERVER_NAME = "session-analytics"


def build_server(dsn: str):
    """Construct (but do not run) a FastMCP server bound to ``dsn``."""
    from mcp.server.fastmcp import FastMCP  # lazy: only needed to serve

    server = FastMCP(SERVER_NAME)

    def _db() -> Database:
        return Database.connect(dsn)

    # ── tools ──────────────────────────────────────────────────────────
    @server.tool()
    def search_sessions(
        query: str = "", copilot: str = "", date_from: str = "",
        date_to: str = "", limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Find sessions by keyword/workspace + optional copilot/date filters."""
        db = _db()
        try:
            return tools.search_sessions(
                db, query or None, copilot=copilot or None,
                date_from=date_from or None, date_to=date_to or None, limit=limit,
            )
        finally:
            db.close()

    @server.tool()
    def get_session_details(session_id: int) -> dict[str, Any]:
        """Full turn/tool/error breakdown for one session."""
        db = _db()
        try:
            return tools.get_session_details(db, session_id)
        finally:
            db.close()

    @server.tool()
    def analyze_patterns(
        workspace: str = "", tool: str = "", error_type: str = ""
    ) -> dict[str, Any]:
        """Aggregate tool-usage + error patterns across sessions."""
        db = _db()
        try:
            return tools.analyze_patterns(
                db, workspace=workspace or None, tool=tool or None,
                error_type=error_type or None,
            )
        finally:
            db.close()

    @server.tool()
    def compare_approaches(task_description: str, limit: int = 10) -> list[dict[str, Any]]:
        """Find similar past sessions and report their KPI outcomes."""
        db = _db()
        try:
            return tools.compare_approaches(db, task_description, limit=limit)
        finally:
            db.close()

    # ── resources ──────────────────────────────────────────────────────
    @server.resource("history://recent-errors")
    def recent_errors() -> dict[str, Any]:
        db = _db()
        try:
            return resources.recent_errors(db)
        finally:
            db.close()

    @server.resource("history://tool-stats")
    def tool_stats() -> dict[str, Any]:
        db = _db()
        try:
            return resources.tool_stats(db)
        finally:
            db.close()

    @server.resource("history://session-summary")
    def session_summary() -> dict[str, Any]:
        db = _db()
        try:
            return resources.session_summary(db)
        finally:
            db.close()

    return server


def run(dsn: str = "") -> None:
    """Run the MCP server over stdio."""
    resolved = dsn or load_config().dsn
    if not resolved:
        raise ValueError("no DSN configured for the MCP server (see --dsn).")
    server = build_server(resolved)
    server.run()  # FastMCP defaults to stdio transport
