# session_analytics.api.alerts — budgets, runaway sessions, alerts (#174 D).
#
# Alerts are DERIVED, never stored: every read re-evaluates the store
# against the configured thresholds, so the audit trail is the rows
# themselves. Two families:
#
#   budget  — the team status windows against team.budgets (team per
#             day and per 30 days, developer per day, project per day);
#             warning at BUDGET_WARNING_SHARE, breach at the budget.
#   runaway — sessions whose newest turn is recent and that are turning
#             too fast, erroring too often, or spending too fast.
#
# Cost honesty (E5): a window with no priced turn never breaches, and
# every budget alert names how many priceable turns had no price, so
# "the true spend is higher" is said, not hidden. Liveness is not a
# signal (a heartbeat is last-seen, nothing more).

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .. import constants as C
from ..config import BudgetsConfig, NoiseConfig, RunawayConfig
from ..mcp.tools import _parse_ts
from ..relational.db import Database
from ..session_filter import keep_clause

KIND_BUDGET = "budget"
KIND_RUNAWAY_TURNS = "runaway-turns"
KIND_RUNAWAY_ERRORS = "runaway-errors"
KIND_RUNAWAY_COST = "runaway-cost"

_LEVEL_ORDER = {C.ALERT_WARNING: 0, C.ALERT_BREACH: 1}


def _money(v: Optional[float]) -> str:
    return "—" if v is None else f"${v:.2f}"


def _budget_alert(scope: str, subject: str, window: str, rollup: dict[str, Any], budget: float) -> Optional[dict[str, Any]]:
    spent = rollup.get("cost_usd")
    if spent is None or (budget <= 0 and spent <= 0):
        # Nothing priced in the window: the bound cannot be judged crossed.
        return None
    share = spent / budget if budget > 0 else float("inf")
    if share < C.BUDGET_WARNING_SHARE:
        return None
    level = C.ALERT_BREACH if share >= 1 else C.ALERT_WARNING
    unpriced = max(0, int(rollup.get("priceable_turns", 0)) - int(rollup.get("priced_turns", 0)))
    label = {"team": "the team", "developer": subject, "project": subject.rstrip("/").split("/")[-1] or subject}[scope]
    when = {"today": "today", "30d": "in the last 30 days"}[window]
    verb = "has passed" if level == C.ALERT_BREACH else "is at"
    message = f"{label} {verb} {int(round(share * 100))}% of the {_money(budget)} budget {when}: {_money(spent)} spent"
    if unpriced:
        message += f"; {unpriced:,} priceable turns had no price, so the true spend is higher"
    return {
        "kind": KIND_BUDGET, "level": level, "scope": scope, "subject": subject, "window": window,
        "message": message + ".",
        "figures": {"spent_usd": spent, "budget_usd": budget, "share": round(share, 3), "unpriced_turns": unpriced},
    }


def budget_alerts(status: dict[str, Any], budgets: BudgetsConfig) -> list[dict[str, Any]]:
    """Alerts from a team status payload (api/team.team_status) against
    the configured budgets. Pure."""
    out: list[dict[str, Any]] = []
    totals = status["totals"]["windows"]
    if budgets.team_daily_usd is not None:
        a = _budget_alert("team", "team", "today", totals["today"], budgets.team_daily_usd)
        if a:
            out.append(a)
    if budgets.team_monthly_usd is not None:
        a = _budget_alert("team", "team", "30d", totals["30d"], budgets.team_monthly_usd)
        if a:
            out.append(a)
    if budgets.developer_daily_usd is not None:
        for d in status["developers"]:
            a = _budget_alert("developer", d["developer_id"], "today", d["windows"]["today"], budgets.developer_daily_usd)
            if a:
                out.append(a)
    if budgets.project_daily_usd is not None:
        for p in status["projects"]:
            a = _budget_alert("project", p["project_path"], "today", p["windows"]["today"], budgets.project_daily_usd)
            if a:
                out.append(a)
    return out


def runaway_alerts(
    db: Database, thresholds: RunawayConfig, *, noise: Optional[NoiseConfig], now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Sessions still producing turns that turn, error or spend past
    the thresholds. One scan of the recent turns, then per-session
    figures; every alert carries the figure and the threshold."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    recent_since = now - timedelta(minutes=thresholds.recent_minutes)
    # Turns from the cutoff day on (the date prefix works on both
    # timestamp shapes); exact bucketing happens in Python.
    rows = db.query(
        f"""
        SELECT s.id, s.developer_id, s.project_path, s.copilot, s.session_id,
               t.id, t.sequence_num, t.timestamp, t.cost_usd,
               EXISTS (SELECT 1 FROM copilot_error e WHERE e.turn_id = t.id) AS errored
        FROM copilot_turn t JOIN copilot_session s ON s.id = t.session_id
        WHERE {keep_sql} AND substr(t.timestamp, 1, 10) >= ?
        ORDER BY s.id, t.sequence_num
        """,
        (*keep_params, (recent_since - timedelta(days=1)).strftime("%Y-%m-%d")),
    )
    sessions: dict[int, dict[str, Any]] = {}
    for sid, dev, project, copilot, native, turn_id, seq, ts, cost, errored in rows:
        when = _parse_ts(ts)
        if when is None:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        info = sessions.setdefault(int(sid), {
            "developer_id": dev, "project_path": project, "session_key": f"{copilot}:{native}",
            "newest": when, "recent_turns": 0, "recent_cost": None, "turns": [],
        })
        if when > info["newest"]:
            info["newest"] = when
        info["turns"].append((int(seq), bool(errored)))
        if when >= recent_since:
            info["recent_turns"] += 1
            if cost is not None:
                info["recent_cost"] = (info["recent_cost"] or 0.0) + float(cost)

    out: list[dict[str, Any]] = []
    for sid, info in sessions.items():
        if info["newest"] < recent_since:
            continue  # not still running
        subject = {"session_id": sid, "session_key": info["session_key"],
                   "developer_id": info["developer_id"], "project_path": info["project_path"]}
        who = f"{info['developer_id']} in {(info['project_path'] or '').rstrip('/').split('/')[-1] or 'an unknown project'}"
        if info["recent_turns"] > thresholds.max_turns_recent:
            out.append({
                "kind": KIND_RUNAWAY_TURNS, "level": C.ALERT_BREACH, "scope": "session", "subject": subject,
                "message": f"session #{sid} ({who}) produced {info['recent_turns']:,} turns in the last "
                           f"{thresholds.recent_minutes} minutes (threshold {thresholds.max_turns_recent:,}) and is still going.",
                "figures": {"recent_turns": info["recent_turns"], "threshold": thresholds.max_turns_recent,
                            "recent_minutes": thresholds.recent_minutes},
            })
        last = sorted(info["turns"])[-thresholds.recent_turns:]
        if len(last) >= thresholds.min_turns_for_error_share:
            errors = sum(1 for _, e in last if e)
            share = errors / len(last)
            if share > thresholds.max_error_share:
                out.append({
                    "kind": KIND_RUNAWAY_ERRORS, "level": C.ALERT_BREACH, "scope": "session", "subject": subject,
                    "message": f"session #{sid} ({who}): {errors} of its last {len(last)} turns errored "
                               f"({int(round(share * 100))}%, threshold {int(round(thresholds.max_error_share * 100))}%) and it is still going.",
                    "figures": {"errors": errors, "turns": len(last), "share": round(share, 3),
                                "threshold": thresholds.max_error_share},
                })
        if info["recent_cost"] is not None and info["recent_cost"] > thresholds.max_cost_recent_usd:
            out.append({
                "kind": KIND_RUNAWAY_COST, "level": C.ALERT_BREACH, "scope": "session", "subject": subject,
                "message": f"session #{sid} ({who}) spent {_money(info['recent_cost'])} in the last "
                           f"{thresholds.recent_minutes} minutes (threshold {_money(thresholds.max_cost_recent_usd)}) and is still going.",
                "figures": {"recent_cost_usd": info["recent_cost"], "threshold": thresholds.max_cost_recent_usd,
                            "recent_minutes": thresholds.recent_minutes},
            })
    return out


def all_alerts(
    db: Database, status: dict[str, Any], *, budgets: BudgetsConfig, runaway: RunawayConfig,
    noise: Optional[NoiseConfig], now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Every alert, breaches first, plus what is configured — so a page
    with no alerts can say whether that is because nothing is set."""
    alerts = budget_alerts(status, budgets) + runaway_alerts(db, runaway, noise=noise, now=now)
    alerts.sort(key=lambda a: (-_LEVEL_ORDER[a["level"]], a["kind"], str(a["subject"])))
    return {
        "alerts": alerts,
        "breaches": sum(1 for a in alerts if a["level"] == C.ALERT_BREACH),
        "warnings": sum(1 for a in alerts if a["level"] == C.ALERT_WARNING),
        "budgets": {
            C.CFG_BUDGET_TEAM_DAILY: budgets.team_daily_usd,
            C.CFG_BUDGET_TEAM_MONTHLY: budgets.team_monthly_usd,
            C.CFG_BUDGET_DEVELOPER_DAILY: budgets.developer_daily_usd,
            C.CFG_BUDGET_PROJECT_DAILY: budgets.project_daily_usd,
        },
        "runaway": {
            C.CFG_RUNAWAY_RECENT_MINUTES: runaway.recent_minutes,
            C.CFG_RUNAWAY_MAX_TURNS_RECENT: runaway.max_turns_recent,
            C.CFG_RUNAWAY_RECENT_TURNS: runaway.recent_turns,
            C.CFG_RUNAWAY_MAX_ERROR_SHARE: runaway.max_error_share,
            C.CFG_RUNAWAY_MIN_TURNS_FOR_ERROR_SHARE: runaway.min_turns_for_error_share,
            C.CFG_RUNAWAY_MAX_COST_RECENT: runaway.max_cost_recent_usd,
        },
        "derived": True,
    }


def worst_level(alerts: list[dict[str, Any]]) -> Optional[str]:
    if not alerts:
        return None
    return max(alerts, key=lambda a: _LEVEL_ORDER[a["level"]])["level"]


def at_or_above(level: str, floor: str) -> bool:
    return _LEVEL_ORDER[level] >= _LEVEL_ORDER[floor]


def render_alerts(report: dict[str, Any]) -> list[str]:
    """The terminal view: one line per alert, then what is configured."""
    out: list[str] = []
    alerts = report["alerts"]
    if not alerts:
        out.append("No alerts.")
    for a in alerts:
        out.append(f"[{a['level'].upper():7}] {a['kind']}: {a['message']}")
    set_budgets = [f"{k}={_money(v)}" for k, v in report["budgets"].items() if v is not None]
    out.append("")
    out.append(
        "Budgets: " + (", ".join(set_budgets) if set_budgets else "none set (team.budgets / CCT_SA_BUDGET_*)")
    )
    r = report["runaway"]
    out.append(
        f"Runaway: > {r[C.CFG_RUNAWAY_MAX_TURNS_RECENT]} turns or > {_money(r[C.CFG_RUNAWAY_MAX_COST_RECENT])} "
        f"in {r[C.CFG_RUNAWAY_RECENT_MINUTES]} min, or > {int(round(r[C.CFG_RUNAWAY_MAX_ERROR_SHARE] * 100))}% errors "
        f"over the last {r[C.CFG_RUNAWAY_RECENT_TURNS]} turns (at least {r[C.CFG_RUNAWAY_MIN_TURNS_FOR_ERROR_SHARE]})."
    )
    out.append("Alerts are derived from the store on every read; nothing is stored.")
    return out
