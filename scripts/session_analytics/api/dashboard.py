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

    # E5: total cost + cost-per-session (primary cost KPI — D-outcome).
    # SUM ignores NULL cost_usd (unpriced turns) → total of what COULD be
    # priced. cost_per_session divides by sessions that HAVE at least one
    # priced turn (not all sessions): dividing a priced-only numerator by an
    # all-sessions denominator would understate the real per-session cost
    # whenever some sessions are unpriced. `priced_sessions` is exposed so the
    # denominator is transparent.
    total_cost_row = db.query_one("SELECT SUM(cost_usd) FROM copilot_turn") or (None,)
    total_cost_usd = float(total_cost_row[0]) if total_cost_row[0] is not None else 0.0
    priced_row = db.query_one(
        "SELECT COUNT(DISTINCT session_id) FROM copilot_turn WHERE cost_usd IS NOT NULL"
    ) or (0,)
    priced_sessions = int(priced_row[0] or 0)
    cost_per_session = (total_cost_usd / priced_sessions) if priced_sessions else 0.0

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
            "total_cost_usd": total_cost_usd,
            "cost_per_session": cost_per_session,
            "priced_sessions": priced_sessions,
        },
        "by_copilot": by_copilot,
        "by_day": by_day,
        "tool_usage": tool_usage,
        "sentiment_distribution": sentiment,
    }


def cost_by_outcome(db: Database) -> dict[str, Any]:
    """Cost-per-outcome (E5, FR-4): cost aggregated by session ``phase`` and
    by the judge's ``sentiment`` label — the two "outcome" dimensions the
    schema actually has (there is no single outcome column; ``sentiment`` is
    the same per-turn judge dimension ``kpis().sentiment_distribution``
    already reports elsewhere in this module). Only turns with a non-NULL
    ``cost_usd`` contribute (unpriced turns are excluded, not zeroed). The
    field is ``by_sentiment`` (not "label") because it groups by sentiment."""
    by_phase = [
        {"phase": r[0] or "(none)", "cost_usd": float(r[1] or 0), "sessions": int(r[2])}
        for r in db.query(
            """
            SELECT s.phase, SUM(t.cost_usd), COUNT(DISTINCT s.id)
            FROM copilot_session s
            JOIN copilot_turn t ON t.session_id = s.id
            WHERE t.cost_usd IS NOT NULL
            GROUP BY s.phase
            ORDER BY SUM(t.cost_usd) DESC
            """
        )
    ]
    # De-dupe to ONE sentiment per turn: heuristic_label is UNIQUE(turn_id,
    # rubric_name), so joining directly would count a turn's cost once per
    # rubric label. Pick a single sentiment per turn (first rubric_name) via a
    # correlated subquery so each priced turn's cost lands in exactly one
    # bucket — the by_sentiment totals then never exceed total_cost_usd.
    by_sentiment = [
        {"sentiment": r[0] or "(none)", "cost_usd": float(r[1] or 0), "turns": int(r[2])}
        for r in db.query(
            """
            SELECT tl.sentiment, SUM(tl.cost_usd), COUNT(*)
            FROM (
                SELECT t.id, t.cost_usd,
                    (SELECT h.sentiment FROM heuristic_label h
                     WHERE h.turn_id = t.id AND h.sentiment IS NOT NULL
                     ORDER BY h.rubric_name LIMIT 1) AS sentiment
                FROM copilot_turn t
                WHERE t.cost_usd IS NOT NULL
            ) tl
            WHERE tl.sentiment IS NOT NULL
            GROUP BY tl.sentiment
            ORDER BY SUM(tl.cost_usd) DESC
            """
        )
    ]
    return {"by_phase": by_phase, "by_sentiment": by_sentiment}


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
