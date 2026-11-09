from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import groupby
from typing import Any, Iterable, Optional, Sequence

from . import constants as C
from .config import NoiseConfig, load_config
from .mcp.tools import _parse_ts, _percentile, count_noise_sessions, turn_latency
from .session_filter import keep_clause

GAP_HUMAN = "human"
GAP_TOOL_RESULT = "tool_result"
GAP_ASSISTANT = "assistant"
GAP_INJECTED = "injected"
GAP_KINDS = (GAP_HUMAN, GAP_TOOL_RESULT, GAP_ASSISTANT, GAP_INJECTED)

DEFAULT_CUTOFFS_MINUTES = (2, 5, 10, 15, 30)
PERCENTILES = (50, 90, 99)

_log = logging.getLogger(__name__)

_INJECTED = re.compile(
    r"^\s*(<task-notification>|<system-reminder>|<local-command-stdout>|"
    r"<local-command-caveat>|<bash-stdout>|This session is being continued)"
)


@dataclass(frozen=True)
class Turn:
    role: str
    timestamp: Optional[str]
    content_length: int = 0
    preview: str = ""
    is_tool_result: bool = False


@dataclass
class SessionGaps:
    gaps: list[tuple[str, float]] = field(default_factory=list)
    skipped_unstamped: int = 0
    skipped_negative: int = 0


def gap_kind(turn: Turn) -> str:
    if turn.role == C.ROLE_ASSISTANT:
        return GAP_ASSISTANT
    if turn.is_tool_result:
        return GAP_TOOL_RESULT
    if turn.content_length and _INJECTED.match(turn.preview or ""):
        return GAP_INJECTED
    return GAP_HUMAN


def session_gaps(turns: Sequence[Turn]) -> SessionGaps:
    out = SessionGaps()
    for prev, cur in zip(turns, turns[1:]):
        start, end = _parse_ts(prev.timestamp), _parse_ts(cur.timestamp)
        if start is None or end is None:
            out.skipped_unstamped += 1
            continue
        seconds = turn_latency(start, end)
        if seconds is None:
            out.skipped_negative += 1
            continue
        out.gaps.append((gap_kind(cur), seconds))
    return out


def active_seconds(gaps: Iterable[float], cutoff_seconds: float) -> float:
    return sum(min(g, cutoff_seconds) for g in gaps)


def percentile(values: Sequence[float], p: float) -> float:
    return _percentile(sorted(values), p / 100)


def _missing_activity(db: Any, cutoff_seconds: int) -> int:
    rows = db.query(
        "SELECT s.id, t.role, t.timestamp FROM copilot_session s "
        f"LEFT JOIN {C.TBL_SESSION_ACTIVITY} a ON a.session_id = s.id AND a.idle_cutoff_seconds = ? "
        "LEFT JOIN copilot_turn t ON t.session_id = s.id "
        "WHERE a.session_id IS NULL ORDER BY s.id, t.sequence_num",
        (cutoff_seconds,),
    )
    written = 0
    for session_id, group in groupby(rows, key=lambda r: r[0]):
        result = session_gaps([Turn(role, ts) for _, role, ts in group if role is not None])
        cursor = db.execute(
            f"INSERT INTO {C.TBL_SESSION_ACTIVITY} (session_id, idle_cutoff_seconds, active_seconds, "
            "gaps_measured, gaps_unstamped, gaps_negative) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (session_id, idle_cutoff_seconds) DO NOTHING",
            (
                session_id,
                cutoff_seconds,
                round(active_seconds((g for _, g in result.gaps), cutoff_seconds), 1),
                len(result.gaps),
                result.skipped_unstamped,
                result.skipped_negative,
            ),
        )
        written += max(cursor.rowcount, 0)
    return written


def ensure_activity(db: Any, cutoff_seconds: Optional[int] = None) -> int:
    try:
        if cutoff_seconds is None:
            cutoff_seconds = load_config().idle_cutoff_seconds
        written = _missing_activity(db, cutoff_seconds)
        db.commit()
    except Exception as exc:
        _log.warning("activity: active time not stored (%s)", exc)
        db.rollback()
        return 0
    if written:
        _log.info("activity: stored active time for %s sessions at a %ss cutoff", written, cutoff_seconds)
    return written


def load_session_turns(db: Any, noise: Optional[NoiseConfig] = None) -> dict[int, list[Turn]]:
    tool_results = {
        (session_id, completed_at)
        for session_id, completed_at in db.query(
            "SELECT t.session_id, r.completed_at FROM copilot_tool_result r "
            "JOIN copilot_tool_call tc ON tc.id = r.tool_call_id "
            "JOIN copilot_turn t ON t.id = tc.turn_id "
            "WHERE r.completed_at IS NOT NULL"
        )
    }
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    sessions: dict[int, list[Turn]] = defaultdict(list)
    for session_id, role, length, preview, ts in db.execute(
        "SELECT t.session_id, t.role, t.content_length, substr(t.content_preview, 1, 64), t.timestamp "
        "FROM copilot_turn t JOIN copilot_session s ON s.id = t.session_id "
        f"WHERE {keep_sql} ORDER BY t.session_id, t.sequence_num",
        keep_params,
    ):
        sessions[session_id].append(Turn(
            role=role,
            timestamp=ts,
            content_length=length or 0,
            preview=preview or "",
            is_tool_result=role == C.ROLE_USER and (session_id, ts) in tool_results,
        ))
    return sessions


def gap_report(
    db: Any,
    cutoffs_minutes: Sequence[float] = DEFAULT_CUTOFFS_MINUTES,
    noise: Optional[NoiseConfig] = None,
) -> dict[str, Any]:
    sessions = load_session_turns(db, noise)
    by_kind: dict[str, list[float]] = defaultdict(list)
    every: list[float] = []
    unstamped = negative = turns = 0
    for turn_list in sessions.values():
        turns += len(turn_list)
        result = session_gaps(turn_list)
        unstamped += result.skipped_unstamped
        negative += result.skipped_negative
        for kind, seconds in result.gaps:
            by_kind[kind].append(seconds)
            every.append(seconds)
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    session_count, wall_clock = db.query_one(
        f"SELECT COUNT(*), SUM(s.duration_seconds) FROM copilot_session s WHERE {keep_sql}",
        keep_params,
    ) or (0, None)
    human = by_kind[GAP_HUMAN]
    return {
        "sessions": int(session_count or 0),
        "excluded_noise": count_noise_sessions(db, noise) if noise is not None else 0,
        "turns": turns,
        "gaps": len(every),
        "skipped_unstamped": unstamped,
        "skipped_negative": negative,
        "wall_clock_seconds": float(wall_clock or 0),
        "kinds": {
            kind: {
                "gaps": len(by_kind[kind]),
                **{f"p{p}": percentile(by_kind[kind], p) for p in PERCENTILES},
                "max": max(by_kind[kind]),
            }
            for kind in GAP_KINDS
            if by_kind[kind]
        },
        "cutoffs": [
            {
                "minutes": int(minutes) if float(minutes).is_integer() else minutes,
                "active_seconds": active_seconds(every, minutes * 60),
                "human_gaps_over": sum(1 for g in human if g > minutes * 60),
                "human_gaps": len(human),
            }
            for minutes in cutoffs_minutes
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    from .judge.session_analysis import _fmt_duration

    excluded = report.get("excluded_noise", 0)
    lines = [
        f"Sample: {report['sessions']} sessions, {report['turns']:,} turns, {report['gaps']:,} gaps "
        f"({report['skipped_unstamped']} skipped for a missing stamp, {report['skipped_negative']} negative). "
        f"Wall clock: {report['wall_clock_seconds'] / 3600:,.1f} h."
        + (f" Noise sessions left out: {excluded} (drop --exclude-noise to count them)." if excluded else ""),
        "",
    ]
    if not report["gaps"]:
        lines.append("No gaps measured.")
        return "\n".join(lines)
    lines += ["| gap ends at | gaps | p50 | p90 | p99 | max |", "|---|---|---|---|---|---|"]
    for kind, row in report["kinds"].items():
        lines.append(
            f"| {kind} | {row['gaps']:,} | "
            + " | ".join(_fmt_duration(row[f"p{p}"]) for p in PERCENTILES)
            + f" | {_fmt_duration(row['max'])} |"
        )
    lines += ["", "| cutoff | active h | human gaps over the cutoff |", "|---|---|---|"]
    for row in report["cutoffs"]:
        share = row["human_gaps_over"] / row["human_gaps"] if row["human_gaps"] else 0.0
        lines.append(
            f"| {row['minutes']:g} min | {row['active_seconds'] / 3600:,.1f} | "
            f"{row['human_gaps_over']:,} ({share:.0%}) |"
        )
    return "\n".join(lines)
