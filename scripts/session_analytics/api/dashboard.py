# session_analytics.api.dashboard — dashboard aggregate queries (pure DB).
#
# JSON-ready aggregates for the Studio dashboard. No FastAPI dependency, so
# these are unit-tested directly against SQLite.

from __future__ import annotations

from typing import Any, Optional

from .. import constants as C
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


def effective_redaction_by_project(db: Database) -> dict[str, Any]:
    """FR-5: per-project "effective redaction mode" the project's already-
    ingested sessions were recorded with — read-only, derived purely by
    grouping ``copilot_session.redaction_mode`` by ``project_path`` (no new
    DB column, no migration). A project's mode can differ across ingests if
    the layered config changed between runs, so when a project's sessions
    don't all share one mode the effective mode is the literal string
    ``"mixed"`` (surfacing the ambiguity rather than silently picking one)."""
    rows = db.query(
        """
        SELECT project_path, redaction_mode, COUNT(*)
        FROM copilot_session
        WHERE project_path IS NOT NULL
        GROUP BY project_path, redaction_mode
        """
    )
    by_project: dict[str, dict[str, int]] = {}
    for project_path, redaction_mode, count in rows:
        modes = by_project.setdefault(project_path, {})
        modes[redaction_mode] = modes.get(redaction_mode, 0) + int(count)

    projects = []
    for project_path, modes in by_project.items():
        session_count = sum(modes.values())
        effective = next(iter(modes)) if len(modes) == 1 else "mixed"
        projects.append({
            "project_path": project_path,
            "session_count": session_count,
            "redaction_modes": modes,
            "effective_redaction_mode": effective,
        })
    projects.sort(key=lambda p: p["session_count"], reverse=True)
    return {"projects": projects}


def developer_aggregates(db: Database) -> dict[str, Any]:
    """E1 (#65): per-developer activity rollup for the team dashboard.

    Grouped on ``copilot_session.developer_id``, which the ingest already
    resolves (``--developer-id`` > env > config > git email local-part >
    ``constants.DEFAULT_DEVELOPER_ID``). No new column and no migration.

    Two things this deliberately does NOT do.

    It does not rank developers by volume as if that were performance.
    Sessions and turns measure how much a copilot was used, not how well
    anyone works, and a dashboard that sorts people by a productivity-
    shaped number invites exactly that reading. Rows are ordered by
    ``developer_id`` — stable and alphabetical, not a leaderboard.

    It does not report unknown cost as zero. ``cost_usd`` is None when a
    developer has no priced turns, with ``priced_turns`` as the visible
    denominator; only a real total is a number.

    It does not hide the single-developer case. A store ingested on one
    machine has one row, and ``is_single_developer`` says so plainly so
    the UI can explain an empty-looking team view instead of implying
    the team is idle. ``unattributed_sessions`` counts sessions still on
    the default id, which is what an unconfigured ``developer_id`` looks
    like from here — a team that never set it reads as one person.
    """
    rows = db.query(
        """
        SELECT developer_id,
               COUNT(*),
               COALESCE(SUM(turn_count), 0),
               COALESCE(SUM(tool_call_count), 0),
               COALESCE(SUM(error_count), 0),
               COUNT(DISTINCT project_path),
               MIN(started_at),
               MAX(started_at)
        FROM copilot_session
        GROUP BY developer_id
        ORDER BY developer_id
        """
    )
    # Cost lives on copilot_turn, so it is a separate grouped read rather
    # than a join that would multiply the session-level SUMs above.
    #
    # A developer with no priced turns gets None, NOT 0.0. NULL cost_usd
    # means "not priced" and rendering that as $0.00 would report unknown
    # cost as free — a number someone could budget against. `priced_turns`
    # is exposed for the same reason `kpis()` exposes `priced_sessions`:
    # the denominator behind a cost figure has to be visible.
    cost_by_dev: dict[str, tuple[Optional[float], int]] = {
        r[0]: (float(r[1]) if r[1] is not None else None, int(r[2] or 0))
        for r in db.query(
            """
            SELECT s.developer_id, SUM(t.cost_usd), COUNT(t.cost_usd)
            FROM copilot_turn t
            JOIN copilot_session s ON s.id = t.session_id
            WHERE t.cost_usd IS NOT NULL
            GROUP BY s.developer_id
            """
        )
    }
    # Registered developers may have no sessions yet; the registry is the
    # source of display names, and a name is only shown if one was set.
    display_names = {
        r[0]: r[1]
        for r in db.query("SELECT developer_id, display_name FROM developer")
    }

    developers = [
        {
            "developer_id": r[0],
            "display_name": display_names.get(r[0]),
            "sessions": int(r[1]),
            "turns": int(r[2]),
            "tool_calls": int(r[3]),
            "errors": int(r[4]),
            "projects": int(r[5]),
            "first_seen": r[6],
            "last_seen": r[7],
            "cost_usd": cost_by_dev.get(r[0], (None, 0))[0],
            "priced_turns": cost_by_dev.get(r[0], (None, 0))[1],
        }
        for r in rows
    ]
    unattributed = next(
        (
            d["sessions"]
            for d in developers
            if d["developer_id"] == C.DEFAULT_DEVELOPER_ID
        ),
        0,
    )
    return {
        "developers": developers,
        "developer_count": len(developers),
        "is_single_developer": len(developers) <= 1,
        "unattributed_sessions": unattributed,
        "registered_without_sessions": sorted(
            set(display_names) - {d["developer_id"] for d in developers}
        ),
    }


def benchmark_correlation(db: Database) -> dict[str, Any]:
    """E9 (#91): benchmark-linked vs organic session coverage.

    ``sessions_linked`` = sessions whose ``benchmark_run_dir`` was stamped by
    ``correlate`` (``COUNT(col)`` counts non-NULL only); ``sessions_unlinked``
    is the organic remainder; ``distinct_benchmark_attempts`` is how many
    distinct attempt directories are linked — named for what the column
    actually stores (the per-ATTEMPT dir, D-run-dir-granularity), NOT runs: a
    run with N attempts contributes up to N. Backend-only summary — no Studio
    UI in this slice."""
    row = db.query_one(
        f"""
        SELECT COUNT(*),
               COUNT({C.COL_BENCHMARK_RUN_DIR}),
               COUNT(DISTINCT {C.COL_BENCHMARK_RUN_DIR})
        FROM copilot_session
        """
    ) or (0, 0, 0)
    total = int(row[0] or 0)
    linked = int(row[1] or 0)
    return {
        "sessions_total": total,
        "sessions_linked": linked,
        "sessions_unlinked": total - linked,
        "distinct_benchmark_attempts": int(row[2] or 0),
    }


def benchmark_outcomes(db: Database) -> dict[str, Any]:
    """E9 outcomes (#92): compare sessions BY benchmark result.

    Grouped over ``benchmark_result`` by ``result`` (pass/fail/error/timeout;
    ``(none)`` for rows whose score carried no result). Per group: ``attempts``
    = all outcome rows; ``linked_sessions`` = DISTINCT sessions with a
    resolved ``session_ref``; ``total_cost_usd`` = Σ of those DISTINCT linked
    sessions' turn costs (D-aggregate-cost-source — NULL-safe like the E5
    KPIs: unpriced turns excluded, unlinked attempts contribute NO cost);
    ``avg_duration_seconds`` over distinct linked sessions only. Session-level
    figures aggregate through ``SELECT DISTINCT (result, session_ref)`` so a
    session referenced by MULTIPLE attempt rows (the tolerated
    duplicate-session_id case) contributes its cost/duration exactly ONCE per
    result bucket — never once per row (that fan-out would double-count)."""
    attempts_by = {
        r[0]: int(r[1])
        for r in db.query(
            f"SELECT result, COUNT(*) FROM {C.TBL_BENCHMARK_RESULT} GROUP BY result"
        )
    }
    # Distinct (result, session) pairs drive every session-level figure; the
    # per-session cost is pre-aggregated once (one grouped scan of
    # copilot_turn), not re-computed per benchmark_result row.
    session_by = {
        r[0]: (int(r[1]), float(r[2] or 0), float(r[3] or 0))
        for r in db.query(
            f"""
            SELECT dr.result, COUNT(*), SUM(sc.cost), AVG(s.duration_seconds)
            FROM (
                SELECT DISTINCT result, session_ref
                FROM {C.TBL_BENCHMARK_RESULT}
                WHERE session_ref IS NOT NULL
            ) dr
            JOIN copilot_session s ON s.id = dr.session_ref
            LEFT JOIN (
                SELECT session_id, SUM(cost_usd) AS cost
                FROM copilot_turn GROUP BY session_id
            ) sc ON sc.session_id = dr.session_ref
            GROUP BY dr.result
            """
        )
    }
    by_result = [
        {
            "result": result if result is not None else "(none)",
            "attempts": attempts,
            "linked_sessions": session_by.get(result, (0, 0.0, 0.0))[0],
            "total_cost_usd": session_by.get(result, (0, 0.0, 0.0))[1],
            "avg_duration_seconds": session_by.get(result, (0, 0.0, 0.0))[2],
        }
        for result, attempts in sorted(
            attempts_by.items(), key=lambda kv: kv[1], reverse=True
        )
    ]
    return {"by_result": by_result}


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
