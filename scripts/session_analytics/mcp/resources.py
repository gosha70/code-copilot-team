# session_analytics.mcp.resources — MCP resource payloads (DB-backed).
#
# history://recent-errors, history://tool-stats, history://session-summary.
# Plain functions returning JSON-ready dicts; unit-tested without the SDK.

from __future__ import annotations

from typing import Any

from ..relational.db import Database


def recent_errors(db: Database, limit: int = 50) -> dict[str, Any]:
    rows = db.query(
        """
        SELECT e.error_type, e.tool_name, e.error_message,
               s.copilot, s.project_path
        FROM copilot_error e
        JOIN copilot_session s ON s.id = e.session_id
        ORDER BY e.id DESC LIMIT ?
        """,
        (int(limit),),
    )
    return {
        "errors": [
            {
                "error_type": r[0], "tool_name": r[1], "message": r[2],
                "copilot": r[3], "project_path": r[4],
            }
            for r in rows
        ]
    }


def tool_stats(db: Database) -> dict[str, Any]:
    rows = db.query(
        """
        SELECT tc.tool_name, COUNT(*) AS n,
               SUM(CASE WHEN tr.is_error THEN 1 ELSE 0 END) AS errs
        FROM copilot_tool_call tc
        LEFT JOIN copilot_tool_result tr ON tr.tool_call_id = tc.id
        GROUP BY tc.tool_name ORDER BY n DESC
        """
    )
    return {
        "tools": [
            {
                "tool": r[0],
                "invocations": int(r[1]),
                "errors": int(r[2] or 0),
                "error_rate": (float(r[2] or 0) / r[1]) if r[1] else 0.0,
            }
            for r in rows
        ]
    }


def session_summary(db: Database, limit: int = 25) -> dict[str, Any]:
    rows = db.query(
        """
        SELECT id, copilot, project_path, model, turn_count, tool_call_count,
               error_count, started_at
        FROM copilot_session ORDER BY started_at DESC LIMIT ?
        """,
        (int(limit),),
    )
    return {
        "sessions": [
            {
                "id": r[0], "copilot": r[1], "project_path": r[2], "model": r[3],
                "turn_count": r[4], "tool_call_count": r[5], "error_count": r[6],
                "started_at": r[7],
            }
            for r in rows
        ]
    }
