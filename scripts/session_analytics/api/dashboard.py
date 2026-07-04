# session_analytics.api.dashboard — dashboard aggregate queries (pure DB).
#
# JSON-ready aggregates for the Studio dashboard. No FastAPI dependency, so
# these are unit-tested directly against SQLite.

from __future__ import annotations

from typing import Any

from ..relational.db import Database


def kpis(db: Database) -> dict[str, Any]:
    """Headline counters + distributions for the dashboard."""
    totals = db.query_one(
        """
        SELECT COUNT(*), COALESCE(SUM(turn_count),0), COALESCE(SUM(tool_call_count),0),
               COALESCE(SUM(error_count),0), COALESCE(AVG(duration_seconds),0)
        FROM copilot_session
        """
    ) or (0, 0, 0, 0, 0)

    by_copilot = [
        {"copilot": r[0], "sessions": int(r[1]), "errors": int(r[2] or 0)}
        for r in db.query(
            "SELECT copilot, COUNT(*), COALESCE(SUM(error_count),0) "
            "FROM copilot_session GROUP BY copilot ORDER BY COUNT(*) DESC"
        )
    ]

    by_day = [
        {"day": r[0], "sessions": int(r[1])}
        for r in db.query(
            # started_at is ISO TEXT; substr(…,1,10) is the date, portable.
            "SELECT substr(started_at,1,10) AS day, COUNT(*) FROM copilot_session "
            "WHERE started_at IS NOT NULL GROUP BY day ORDER BY day DESC LIMIT 30"
        )
    ]

    tool_usage = [
        {"tool": r[0], "count": int(r[1]), "errors": int(r[2] or 0)}
        for r in db.query(
            """
            SELECT tc.tool_name, COUNT(*),
                   SUM(CASE WHEN tr.is_error THEN 1 ELSE 0 END)
            FROM copilot_tool_call tc
            LEFT JOIN copilot_tool_result tr ON tr.tool_call_id = tc.id
            GROUP BY tc.tool_name ORDER BY COUNT(*) DESC LIMIT 25
            """
        )
    ]

    sentiment = [
        {"sentiment": r[0], "count": int(r[1])}
        for r in db.query(
            "SELECT sentiment, COUNT(*) FROM heuristic_label "
            "WHERE sentiment IS NOT NULL GROUP BY sentiment ORDER BY COUNT(*) DESC"
        )
    ]

    return {
        "totals": {
            "sessions": int(totals[0]),
            "turns": int(totals[1]),
            "tool_calls": int(totals[2]),
            "errors": int(totals[3]),
            "avg_duration_seconds": float(totals[4] or 0),
        },
        "by_copilot": by_copilot,
        "by_day": by_day,
        "tool_usage": tool_usage,
        "sentiment_distribution": sentiment,
    }


def label_distribution(db: Database, rubric_name: str = "heuristic-v1") -> dict[str, Any]:
    """Per-bool-label true-counts across all labeled turns."""
    from ..judge.rubric import load_rubric

    rubric = load_rubric()
    out = []
    for label in rubric.bool_labels:
        if not label.isidentifier():
            continue
        row = db.query_one(
            f"SELECT SUM(CASE WHEN {label} THEN 1 ELSE 0 END), COUNT(*) "
            f"FROM heuristic_label WHERE rubric_name = ?",
            (rubric_name,),
        )
        out.append({"label": label, "true": int((row[0] or 0)), "total": int((row[1] or 0))})
    return {"labels": out}
