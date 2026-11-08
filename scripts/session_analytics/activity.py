from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence

from . import constants as C

GAP_HUMAN = "human"
GAP_TOOL_RESULT = "tool_result"
GAP_ASSISTANT = "assistant"
GAP_INJECTED = "injected"
GAP_KINDS = (GAP_HUMAN, GAP_TOOL_RESULT, GAP_ASSISTANT, GAP_INJECTED)

DEFAULT_CUTOFFS_MINUTES = (2, 5, 10, 15, 30)
PERCENTILES = (50, 90, 99)

_INJECTED = re.compile(
    r"^\s*(<task-notification>|<system-reminder>|<command-name>|<command-message>|"
    r"<local-command-stdout>|<local-command-caveat>|<bash-input>|<bash-stdout>|"
    r"This session is being continued)"
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


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
        start, end = parse_timestamp(prev.timestamp), parse_timestamp(cur.timestamp)
        if start is None or end is None:
            out.skipped_unstamped += 1
            continue
        seconds = (end - start).total_seconds()
        if seconds < 0:
            out.skipped_negative += 1
            continue
        out.gaps.append((gap_kind(cur), seconds))
    return out


def active_seconds(gaps: Iterable[float], cutoff_seconds: float) -> float:
    return sum(min(g, cutoff_seconds) for g in gaps)


def percentile(values: Sequence[float], p: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
    return ordered[index]


def load_session_turns(db: Any) -> dict[int, list[Turn]]:
    tool_results = {
        (session_id, completed_at)
        for session_id, completed_at in db.query(
            "SELECT t.session_id, r.completed_at FROM copilot_tool_result r "
            "JOIN copilot_tool_call tc ON tc.id = r.tool_call_id "
            "JOIN copilot_turn t ON t.id = tc.turn_id "
            "WHERE r.completed_at IS NOT NULL"
        )
    }
    sessions: dict[int, list[Turn]] = defaultdict(list)
    for session_id, role, length, preview, ts in db.execute(
        "SELECT session_id, role, content_length, substr(content_preview, 1, 64), timestamp "
        "FROM copilot_turn ORDER BY session_id, sequence_num"
    ):
        sessions[session_id].append(Turn(
            role=role,
            timestamp=ts,
            content_length=length or 0,
            preview=preview or "",
            is_tool_result=role == C.ROLE_USER and (session_id, ts) in tool_results,
        ))
    return sessions


def gap_report(db: Any, cutoffs_minutes: Sequence[float] = DEFAULT_CUTOFFS_MINUTES) -> dict[str, Any]:
    sessions = load_session_turns(db)
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
    row = db.query_one("SELECT SUM(duration_seconds) FROM copilot_session WHERE duration_seconds IS NOT NULL")
    human = by_kind[GAP_HUMAN]
    return {
        "sessions": len(sessions),
        "turns": turns,
        "gaps": len(every),
        "skipped_unstamped": unstamped,
        "skipped_negative": negative,
        "wall_clock_seconds": float(row[0] or 0) if row else 0.0,
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
                "minutes": minutes,
                "active_seconds": active_seconds(every, minutes * 60),
                "human_gaps_over": sum(1 for g in human if g > minutes * 60),
                "human_gaps": len(human),
            }
            for minutes in cutoffs_minutes
        ],
    }


def _duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.1f} min"
    return f"{seconds / 3600:.1f} h"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"Sample: {report['sessions']} sessions, {report['turns']:,} turns, {report['gaps']:,} gaps "
        f"({report['skipped_unstamped']} skipped for a missing stamp, {report['skipped_negative']} negative). "
        f"Wall clock: {report['wall_clock_seconds'] / 3600:,.1f} h.",
        "",
    ]
    if not report["gaps"]:
        lines.append("No gaps measured.")
        return "\n".join(lines)
    lines += ["| gap ends at | gaps | p50 | p90 | p99 | max |", "|---|---|---|---|---|---|"]
    for kind, row in report["kinds"].items():
        lines.append(
            f"| {kind} | {row['gaps']:,} | "
            + " | ".join(_duration(row[f"p{p}"]) for p in PERCENTILES)
            + f" | {_duration(row['max'])} |"
        )
    lines += ["", "| cutoff | active h | human gaps over the cutoff |", "|---|---|---|"]
    for row in report["cutoffs"]:
        share = row["human_gaps_over"] / row["human_gaps"] if row["human_gaps"] else 0.0
        lines.append(
            f"| {row['minutes']:g} min | {row['active_seconds'] / 3600:,.1f} | "
            f"{row['human_gaps_over']:,} ({share:.0%}) |"
        )
    return "\n".join(lines)
