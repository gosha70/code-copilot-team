# session_analytics.mcp.tools — MCP tool implementations (DB-backed).
#
# Plain functions over the relational store, returning JSON-ready dicts. Kept
# free of the MCP SDK so they are unit-testable directly; server.py wires them
# to the protocol.

from __future__ import annotations

from typing import Any, Optional

from ..relational.db import Database

_SESSION_COLS = (
    "id, copilot, session_id, project_path, model, developer_id, phase, "
    "turn_count, tool_call_count, error_count, started_at, ended_at, "
    "duration_seconds"
)


def _session_dict(row) -> dict[str, Any]:
    keys = [c.strip() for c in _SESSION_COLS.split(",")]
    return dict(zip(keys, row))


def search_sessions(
    db: Database,
    query: Optional[str] = None,
    *,
    copilot: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Find sessions by keyword (project path / model) + optional filters."""
    where: list[str] = []
    params: list[Any] = []
    if query:
        where.append("(project_path LIKE ? OR model LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    if copilot:
        where.append("copilot = ?")
        params.append(copilot)
    if date_from:
        where.append("started_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("started_at <= ?")
        params.append(date_to)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(
        f"SELECT {_SESSION_COLS} FROM copilot_session{where_sql} "
        f"ORDER BY started_at DESC LIMIT {int(limit)}",
        tuple(params),
    )
    return [_session_dict(r) for r in rows]


def get_session_details(db: Database, session_id: int) -> dict[str, Any]:
    """Full turn/tool/error breakdown for one session."""
    srow = db.query_one(
        f"SELECT {_SESSION_COLS} FROM copilot_session WHERE id = ?", (session_id,)
    )
    if srow is None:
        return {"error": f"session {session_id} not found"}
    session = _session_dict(srow)

    turns = db.query(
        """
        SELECT t.sequence_num, t.role, t.content_preview, t.has_tool_use,
               t.slash_command, h.sentiment, h.interaction_quality,
               h.user_corrects_agent, h.rework_detected
        FROM copilot_turn t
        LEFT JOIN heuristic_label h ON h.turn_id = t.id
        WHERE t.session_id = ? ORDER BY t.sequence_num
        """,
        (session_id,),
    )
    session["turns"] = [
        {
            "sequence_num": r[0], "role": r[1], "content_preview": r[2],
            "has_tool_use": bool(r[3]), "slash_command": r[4],
            "sentiment": r[5], "interaction_quality": r[6],
            "user_corrects_agent": _b(r[7]), "rework_detected": _b(r[8]),
        }
        for r in turns
    ]
    session["tool_usage"] = [
        {"tool": r[0], "count": int(r[1])}
        for r in db.query(
            """
            SELECT tc.tool_name, COUNT(*) FROM copilot_tool_call tc
            JOIN copilot_turn t ON t.id = tc.turn_id
            WHERE t.session_id = ? GROUP BY tc.tool_name ORDER BY COUNT(*) DESC
            """,
            (session_id,),
        )
    ]
    session["errors"] = [
        {"error_type": r[0], "tool_name": r[1], "message": r[2]}
        for r in db.query(
            "SELECT error_type, tool_name, error_message FROM copilot_error "
            "WHERE session_id = ? LIMIT 50",
            (session_id,),
        )
    ]
    return session


def analyze_patterns(
    db: Database,
    *,
    workspace: Optional[str] = None,
    tool: Optional[str] = None,
    error_type: Optional[str] = None,
) -> dict[str, Any]:
    """Aggregate pattern analysis across sessions."""
    session_filter = ""
    sparams: list[Any] = []
    if workspace:
        session_filter = " AND s.project_path LIKE ?"
        sparams.append(f"%{workspace}%")

    tool_where = ""
    tparams = list(sparams)
    if tool:
        tool_where = " AND tc.tool_name = ?"
        tparams.append(tool)
    tool_rows = db.query(
        f"""
        SELECT tc.tool_name, COUNT(*) AS n,
               SUM(CASE WHEN tr.is_error THEN 1 ELSE 0 END) AS errs
        FROM copilot_tool_call tc
        JOIN copilot_turn t ON t.id = tc.turn_id
        JOIN copilot_session s ON s.id = t.session_id
        LEFT JOIN copilot_tool_result tr ON tr.tool_call_id = tc.id
        WHERE 1=1{session_filter}{tool_where}
        GROUP BY tc.tool_name ORDER BY errs DESC, n DESC LIMIT 50
        """,
        tuple(tparams),
    )

    err_where = ""
    eparams = list(sparams)
    if error_type:
        err_where = " AND e.error_type LIKE ?"
        eparams.append(f"%{error_type}%")
    error_rows = db.query(
        f"""
        SELECT e.tool_name, e.error_type, COUNT(*) AS n
        FROM copilot_error e
        JOIN copilot_session s ON s.id = e.session_id
        WHERE 1=1{session_filter}{err_where}
        GROUP BY e.tool_name, e.error_type ORDER BY n DESC LIMIT 50
        """,
        tuple(eparams),
    )

    return {
        "tools": [
            {"tool": r[0], "invocations": int(r[1]), "errors": int(r[2] or 0)}
            for r in tool_rows
        ],
        "errors": [
            {"tool": r[0], "error_type": r[1], "count": int(r[2])}
            for r in error_rows
        ],
    }


def compare_approaches(db: Database, task_description: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Find past sessions resembling a task and report their KPIs.

    Keyword match over project_path + first user turn; outcomes come from
    session_kpi when present. (Embedding similarity is the E2 enhancement.)
    """
    terms = [t for t in (task_description or "").lower().split() if len(t) > 3][:6]
    rows = db.query(
        f"""
        SELECT {_SESSION_COLS} FROM copilot_session
        ORDER BY started_at DESC LIMIT 500
        """
    )
    scored = []
    for r in rows:
        s = _session_dict(r)
        hay = (s.get("project_path") or "").lower()
        score = sum(1 for t in terms if t in hay)
        if score:
            kpi = db.query_one(
                "SELECT correction_rate, rework_rate, avg_interaction_quality "
                "FROM session_kpi WHERE session_id = ? LIMIT 1",
                (s["id"],),
            )
            if kpi:
                s["kpi"] = {
                    "correction_rate": kpi[0],
                    "rework_rate": kpi[1],
                    "avg_interaction_quality": kpi[2],
                }
            s["match_score"] = score
            scored.append(s)
    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:limit]


def _b(v):
    if v is None:
        return None
    return bool(v)
