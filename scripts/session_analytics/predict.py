# session_analytics.predict — E4 predictive analytics (#65).
#
# Outcome prediction and effort estimation from the store's own history.
#
# WHAT THIS IS: base-rate forecasting. For a project, the distribution of
# what its past sessions actually cost in turns, time and dollars; and,
# where benchmark outcomes exist, the historical pass rate. Those are the
# honest predictions available from this data.
#
# WHAT THIS IS NOT: a trained model. There is no feature engineering, no
# fitted estimator and no accuracy claim, because there is nothing here
# to validate one against — the store holds no held-out outcome per
# session that a prediction could be scored on. A regression wearing a
# confidence interval would look more authoritative and be worth less.
#
# EVERY ESTIMATE CARRIES ITS SAMPLE SIZE, and refuses below a floor. A
# median over two sessions is not an estimate, and the caller must not
# have to infer that from a number that looks like every other number.

from __future__ import annotations

from typing import Any, Optional, Sequence

from . import constants as C
from .relational.db import Database

#: Below this many observations an estimate is returned as None with the
#: count intact, rather than a figure the reader would reasonably trust.
MIN_OBSERVATIONS = 5


def _percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    """Nearest-rank percentile over a sorted copy; None when empty.

    Deliberately not an interpolating percentile: with the small samples
    this operates on, interpolation invents a value between two real
    observations and reads as more precise than the data supports.
    """
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return float(ordered[idx])


def _summary(values: Sequence[float]) -> dict[str, Any]:
    """Median/p90/max plus the count that earned them."""
    usable = [v for v in values if v is not None]
    enough = len(usable) >= MIN_OBSERVATIONS
    return {
        "observations": len(usable),
        "sufficient": enough,
        "median": _percentile(usable, 0.5) if enough else None,
        "p90": _percentile(usable, 0.9) if enough else None,
        "max": (max(usable) if usable else None) if enough else None,
    }


def effort_estimate(db: Database, project_path: Optional[str] = None) -> dict[str, Any]:
    """Expected effort for the next session, from comparable past ones.

    Scoped to ``project_path`` when given, else the whole store. Cost is
    summed per session from priced turns only — unpriced turns are
    excluded rather than counted as zero, so the estimate describes what
    is known to have been spent, not a floor pretending to be a total.
    """
    where, params = "", []
    if project_path:
        where = "WHERE s.project_path = ?"
        params = [project_path]
    rows = db.query(
        f"""
        SELECT s.turn_count, s.tool_call_count, s.error_count,
               s.duration_seconds,
               (SELECT SUM(t.cost_usd) FROM copilot_turn t
                 WHERE t.session_id = s.id AND t.cost_usd IS NOT NULL)
        FROM copilot_session s
        {where}
        """,
        tuple(params),
    )
    return {
        "scope": project_path or "(all projects)",
        "sessions": len(rows),
        "turns": _summary([r[0] for r in rows if r[0] is not None]),
        "tool_calls": _summary([r[1] for r in rows if r[1] is not None]),
        "errors": _summary([r[2] for r in rows if r[2] is not None]),
        "duration_seconds": _summary([r[3] for r in rows if r[3] is not None]),
        "cost_usd": _summary([r[4] for r in rows if r[4] is not None]),
        "min_observations": MIN_OBSERVATIONS,
        "basis": (
            "Historical distribution of comparable sessions — a base rate, "
            "not a fitted model. Figures are withheld below "
            f"{MIN_OBSERVATIONS} observations."
        ),
    }


def outcome_prediction(db: Database) -> dict[str, Any]:
    """Base-rate outcome forecast from recorded benchmark results.

    The only ground-truth outcome this store holds is
    ``benchmark_result.result`` (E9). Where a project has enough attempts,
    its historical pass rate IS the prediction for the next one; where it
    does not, that is said rather than papered over.

    Sessions with no benchmark attempt are counted, not hidden — most
    organic work has no outcome label at all, and a pass rate computed
    only over benchmarked work must not be read as a rate over everything.
    """
    rows = db.query(
        f"""
        SELECT s.project_path, b.result, COUNT(*)
        FROM {C.TBL_BENCHMARK_RESULT} b
        LEFT JOIN copilot_session s ON s.id = b.session_ref
        GROUP BY s.project_path, b.result
        """
    )
    by_project: dict[Optional[str], dict[str, int]] = {}
    for project_path, result, count in rows:
        by_project.setdefault(project_path, {})[result] = int(count or 0)

    projects = []
    for project_path, results in by_project.items():
        attempts = sum(results.values())
        passes = results.get("pass", 0)
        enough = attempts >= MIN_OBSERVATIONS
        projects.append({
            "project_path": project_path,
            "attempts": attempts,
            "by_result": results,
            "predicted_pass_rate": (passes / attempts) if enough else None,
            "sufficient": enough,
        })
    projects.sort(key=lambda p: (-p["attempts"], p["project_path"] or ""))

    total_sessions = (db.query_one("SELECT COUNT(*) FROM copilot_session") or (0,))[0]
    linked = (
        db.query_one(
            f"SELECT COUNT(DISTINCT session_ref) FROM {C.TBL_BENCHMARK_RESULT} "
            f"WHERE session_ref IS NOT NULL"
        )
        or (0,)
    )[0]
    return {
        "projects": projects,
        "sessions_total": int(total_sessions or 0),
        "sessions_with_outcome": int(linked or 0),
        "min_observations": MIN_OBSERVATIONS,
        "basis": (
            "Historical pass rate over recorded benchmark attempts — a base "
            "rate, not a fitted model. Covers only benchmarked sessions; "
            "organic sessions carry no recorded outcome."
        ),
    }
