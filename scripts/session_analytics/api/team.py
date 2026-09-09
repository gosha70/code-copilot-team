# session_analytics.api.team — the team store's status (#174 B2 + C).
#
# One read-only payload over the shared store: who is active (a
# heartbeat within the window — last-seen, never alive/dead), what they
# are on, and what sessions cost per developer, per project and in
# total over three time windows. Every figure comes from rows the
# ingest already writes; nothing here is a new source of truth.
#
# Windows are by turn timestamp, bucketed in Python after one scan,
# because timestamps are ISO text in more than one shape ("2026-09-07
# 15:27:00" and "2026-09-07T15:27:00.154Z" both occur) and a string
# comparison at the boundary would misplace a turn.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from .. import constants as C
from ..config import NoiseConfig
from ..mcp.tools import _parse_ts
from ..relational.db import DIALECT_POSTGRES, Database
from ..session_filter import keep_clause

LIVENESS_ACTIVE = "active"
LIVENESS_IDLE = "idle"
LIVENESS_UNKNOWN = "unknown"

#: The three windows, in days, oldest last; "today" is the calendar day
#: in UTC, the others are rolling.
WINDOWS = ("today", "7d", "30d")
_WINDOW_DAYS = {"7d": 7, "30d": 30}


def liveness(last_heartbeat_at: Optional[str], now: datetime, window_seconds: int) -> str:
    """active | idle | unknown — from the LAST-SEEN time only."""
    if not last_heartbeat_at:
        return LIVENESS_UNKNOWN
    seen = _parse_ts(last_heartbeat_at)
    if seen is None:
        return LIVENESS_UNKNOWN
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return LIVENESS_ACTIVE if (now - seen).total_seconds() <= window_seconds else LIVENESS_IDLE


@dataclass
class _Rollup:
    sessions: set = field(default_factory=set)
    turns: int = 0
    cost_usd: Optional[float] = None
    priced_turns: int = 0
    priceable_turns: int = 0

    def add(self, session_id: int, cost: Any, model: Any) -> None:
        self.sessions.add(session_id)
        self.turns += 1
        if model:
            self.priceable_turns += 1
        if cost is not None:
            self.priced_turns += 1
            self.cost_usd = (self.cost_usd or 0.0) + float(cost)

    def merge(self, other: "_Rollup") -> None:
        """Fold another id's window into this one (aliases). Sessions are
        a union — a session belongs to one developer id, so the union IS
        the sum — and an unpriced window stays null, never 0."""
        self.sessions |= other.sessions
        self.turns += other.turns
        self.priced_turns += other.priced_turns
        self.priceable_turns += other.priceable_turns
        if other.cost_usd is not None:
            self.cost_usd = (self.cost_usd or 0.0) + other.cost_usd

    def as_dict(self) -> dict[str, Any]:
        return {
            "sessions": len(self.sessions),
            "turns": self.turns,
            "cost_usd": self.cost_usd,
            "priced_turns": self.priced_turns,
            "priceable_turns": self.priceable_turns,
        }


def _empty_windows() -> dict[str, _Rollup]:
    return {w: _Rollup() for w in WINDOWS}


def _fold(aliases: Mapping[str, str], dev_ids) -> list[tuple[str, Optional[str], list[str]]]:
    """One ``(row id, configured name, folded ids)`` per developer row.

    Ids the operator gave the same name in ``team.aliases`` are one
    person: they become one row, named by the alias, carrying every
    folded id in the order the mapping names them. Every other id is its
    own row with no configured name. Only ids the store actually knows
    are folded — an alias for someone with no rows is not a developer.
    """
    known = set(dev_ids)
    grouped: dict[str, list[str]] = {}
    for dev, name in aliases.items():
        if dev in known:
            grouped.setdefault(name, []).append(dev)
    folded = {dev for ids in grouped.values() for dev in ids}
    rows = [(ids[0], name, list(ids)) for name, ids in grouped.items()]
    rows += [(dev, None, [dev]) for dev in known - folded]
    return rows


def team_status(
    db: Database,
    *,
    noise: Optional[NoiseConfig],
    active_window_seconds: int,
    now: Optional[datetime] = None,
    aliases: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())

    # ── heartbeats: the live registry ────────────────────────────────
    beats: dict[str, dict[str, Any]] = {}
    for project, dev, session_id, phase, feature, count, at in db.query(
        f"SELECT project_path, developer_id, session_id, phase, feature_id, "
        f"checkpoint_count, last_heartbeat_at FROM {C.TBL_LOCAL_HEARTBEAT}"
    ):
        current = {
            "project_path": project, "session_id": session_id, "phase": phase,
            "feature_id": feature, "checkpoint_count": int(count or 0), "at": at,
        }
        prev = beats.get(dev)
        # The newest heartbeat is the developer's current work.
        if prev is None or (at or "") > (prev["at"] or ""):
            beats[dev] = current

    # ── turns in the last 30 days, bucketed by window ────────────────
    cutoff = (now - timedelta(days=_WINDOW_DAYS["30d"]))
    today = now.strftime("%Y-%m-%d")
    by_dev: dict[str, dict[str, _Rollup]] = {}
    by_project: dict[str, dict[str, _Rollup]] = {}
    project_devs: dict[str, set] = {}
    totals = _empty_windows()
    unstamped = 0
    rows = db.query(
        f"""
        SELECT s.developer_id, s.project_path, s.id, t.timestamp, t.cost_usd, t.model
        FROM copilot_turn t JOIN copilot_session s ON s.id = t.session_id
        WHERE {keep_sql} AND (t.timestamp IS NULL OR substr(t.timestamp, 1, 10) >= ?)
        """,
        (*keep_params, cutoff.strftime("%Y-%m-%d")),
    )
    for dev, project, sid, ts, cost, model in rows:
        when = _parse_ts(ts)
        if when is None:
            unstamped += 1
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age = now - when
        if age < timedelta(0):
            age = timedelta(0)
        windows = []
        if when.strftime("%Y-%m-%d") == today:
            windows.append("today")
        if age <= timedelta(days=7):
            windows.append("7d")
        if age <= timedelta(days=30):
            windows.append("30d")
        if windows:
            project_devs.setdefault(project or "", set()).add(dev)
        for w in windows:
            by_dev.setdefault(dev, _empty_windows())[w].add(int(sid), cost, model)
            by_project.setdefault(project or "", _empty_windows())[w].add(int(sid), cost, model)
            totals[w].add(int(sid), cost, model)

    # ── developers: everyone seen anywhere ───────────────────────────
    names = {r[0]: r[1] for r in db.query("SELECT developer_id, display_name FROM developer")}
    all_devs = set(names) | set(beats) | set(by_dev) | {
        r[0] for r in db.query(f"SELECT DISTINCT s.developer_id FROM copilot_session s WHERE {keep_sql}", keep_params)
    }
    # Aliased ids are folded into one row here, at READ time: the store
    # keeps every id it recorded, and `merged_ids` names them all, so
    # the fold hides no attribution.
    developers = []
    for dev, alias_name, merged_ids in _fold(aliases or {}, all_devs):
        beat = None
        for member in merged_ids:
            candidate = beats.get(member)
            # The newest heartbeat across the folded ids is the person's
            # current work — the same rule as within one id.
            if candidate and (beat is None or (candidate["at"] or "") > (beat["at"] or "")):
                beat = candidate
        windows = _empty_windows()
        for member in merged_ids:
            for w, rollup in by_dev.get(member, _empty_windows()).items():
                windows[w].merge(rollup)
        state = liveness(beat["at"] if beat else None, now, active_window_seconds)
        developers.append({
            "developer_id": dev,
            # A configured alias is the operator's own naming: it wins
            # over whatever the developer table recorded at ingest.
            "display_name": alias_name if alias_name is not None else names.get(dev),
            "merged_ids": merged_ids,
            "liveness": state,
            "current": beat,
            "windows": {w: r.as_dict() for w, r in windows.items()},
        })
    # Active first, then the most recently seen, then by id — the
    # people working now at the top, stable between polls.
    order = {LIVENESS_ACTIVE: 0, LIVENESS_IDLE: 1, LIVENESS_UNKNOWN: 2}

    def seen_key(d: dict[str, Any]) -> float:
        at = _parse_ts(d["current"]["at"]) if d["current"] else None
        if at is None:
            return 0.0
        return -(at.replace(tzinfo=at.tzinfo or timezone.utc)).timestamp()

    developers.sort(key=lambda d: (order[d["liveness"]], seen_key(d), d["developer_id"]))

    # Projects by 30-day cost, then sessions: where the money went.
    projects = [
        {
            "project_path": project,
            "developers": sorted(project_devs.get(project, set())),
            "windows": {w: r.as_dict() for w, r in windows.items()},
        }
        for project, windows in sorted(
            by_project.items(),
            key=lambda kv: (-(kv[1]["30d"].cost_usd or 0.0), -len(kv[1]["30d"].sessions), kv[0]),
        )
    ]

    return {
        "store": {"dialect": db.dialect, "shared": db.dialect == DIALECT_POSTGRES},
        "now": now.isoformat(),
        "active_window_seconds": active_window_seconds,
        "developers": developers,
        "projects": projects,
        "totals": {
            "developers": len(developers),
            "active_now": sum(1 for d in developers if d["liveness"] == LIVENESS_ACTIVE),
            "windows": {w: r.as_dict() for w, r in totals.items()},
            "unstamped_turns": unstamped,
        },
    }


# ── the terminal view (`session-analytics team status`) ─────────────────


def _money(r: dict[str, Any]) -> str:
    if r["cost_usd"] is None:
        return "—"
    mark = "" if r["priced_turns"] >= r["priceable_turns"] else "*"
    return f"${r['cost_usd']:.2f}{mark}"


def render_status(status: dict[str, Any]) -> list[str]:
    """The developers table as lines, the same figures the Team tab
    shows. ``*`` after a cost means some priceable turns were unpriced."""
    minutes = status["active_window_seconds"] // 60
    store = "shared team store (Postgres)" if status["store"]["shared"] else "local store (SQLite) — one developer"
    out = [
        f"Team status — {store}; active = heartbeat within {minutes} min; "
        f"{status['totals']['active_now']} of {status['totals']['developers']} active",
        "",
        f"{'developer':<22} {'state':<8} {'current work':<44} {'today':>10} {'7d':>10} {'30d':>10}",
    ]
    for d in status["developers"]:
        cur = d["current"]
        work = "—"
        if cur:
            parts = [p for p in (cur.get("project_path", "").rsplit("/", 1)[-1] if cur.get("project_path") else "",
                                 cur.get("phase") or "", cur.get("feature_id") or "") if p]
            work = " · ".join(parts) or "—"
        name = d["developer_id"] if not d["display_name"] else f"{d['display_name']} ({d['developer_id']})"
        out.append(
            f"{name[:22]:<22} {d['liveness']:<8} {work[:44]:<44} "
            f"{_money(d['windows']['today']):>10} {_money(d['windows']['7d']):>10} {_money(d['windows']['30d']):>10}"
        )
    t = status["totals"]["windows"]
    out.append("")
    out.append(
        f"{'total':<22} {'':<8} {'':<44} {_money(t['today']):>10} {_money(t['7d']):>10} {_money(t['30d']):>10}"
    )
    if status["totals"]["unstamped_turns"]:
        out.append(f"({status['totals']['unstamped_turns']} turns without a timestamp are in no window)")
    return out
