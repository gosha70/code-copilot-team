# session_analytics.judge.runner — label un-labeled turns (additive).
#
# Selects turns that have no heuristic_label for the rubric, runs the judge
# (optionally across worker threads — the judges are I/O-bound on HTTP /
# subprocess), and writes one heuristic_label row per turn. Turn rows are
# never mutated. Idempotent: ON CONFLICT(turn_id, rubric_name) DO UPDATE.

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional, Sequence

from ..relational.db import Database
from .contracts import Rubric, TurnContext, TurnJudge, TurnLabels

_log = logging.getLogger(__name__)


@dataclass
class JudgeStats:
    labeled: int = 0
    parse_ok: int = 0
    parse_failed: int = 0

    def as_dict(self) -> dict:
        return {"labeled": self.labeled, "parse_ok": self.parse_ok, "parse_failed": self.parse_failed}


def run_judge(
    db: Database,
    judge: TurnJudge,
    rubric: Rubric,
    *,
    workers: int = 1,
    overwrite: bool = False,
    session_id: Optional[int] = None,
    copilot: Optional[str] = None,
    limit: Optional[int] = None,
) -> JudgeStats:
    contexts = _select_turns(
        db, rubric, overwrite=overwrite, session_id=session_id, copilot=copilot, limit=limit
    )
    stats = JudgeStats()
    if not contexts:
        return stats

    def _rate(ctx: TurnContext) -> tuple[TurnContext, TurnLabels]:
        return ctx, judge.rate_turn(ctx, rubric)

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_rate, contexts))
    else:
        results = [_rate(c) for c in contexts]

    # DB writes are serialized (single connection is not thread-safe).
    from .contracts import PARSE_OK

    for ctx, labels in results:
        _write_label(db, ctx, rubric, labels)
        stats.labeled += 1
        if labels.parse_status == PARSE_OK:
            stats.parse_ok += 1
        else:
            stats.parse_failed += 1
    db.commit()
    return stats


def _select_turns(
    db: Database,
    rubric: Rubric,
    *,
    overwrite: bool,
    session_id: Optional[int],
    copilot: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[TurnContext]:
    where = []
    params: list = [rubric.name]
    join = "LEFT JOIN heuristic_label h ON h.turn_id = t.id AND h.rubric_name = ?"
    if copilot is not None:
        join += " JOIN copilot_session s ON s.id = t.session_id"
        where.append("s.copilot = ?")
        params.append(copilot)
    if not overwrite:
        where.append("h.id IS NULL")
    if session_id is not None:
        where.append("t.session_id = ?")
        params.append(session_id)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    sql = f"""
        SELECT t.id, t.session_id, t.sequence_num, t.role, t.content_preview,
               t.has_tool_use,
               (SELECT content_preview FROM copilot_turn p
                WHERE p.session_id = t.session_id
                  AND p.sequence_num = t.sequence_num - 1) AS prev_preview
        FROM copilot_turn t
        {join}
        {where_sql}
        ORDER BY t.session_id, t.sequence_num
        {limit_sql}
    """
    rows = db.query(sql, tuple(params))
    return [
        TurnContext(
            turn_id=r[0],
            role=r[3],
            sequence_num=r[2],
            text=r[4] or "",
            prev_text=r[6] or "",
            has_tool_use=bool(r[5]),
        )
        for r in rows
    ]


def _write_label(db: Database, ctx: TurnContext, rubric: Rubric, labels: TurnLabels) -> None:
    # Bool columns come from the rubric (validated identifiers, matching the
    # DDL). Build the column list dynamically so rubric + schema stay aligned.
    bool_cols = list(rubric.bool_labels)
    for c in bool_cols:
        if not c.isidentifier():  # defensive — config could be hand-edited
            raise ValueError(f"invalid label column: {c!r}")
    cols = bool_cols + [
        "sentiment", "interaction_quality", "judge_id", "judge_model",
        "parse_status", "created_at",
    ]
    all_cols = ["turn_id", "rubric_name"] + cols
    placeholders = ", ".join("?" for _ in all_cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols)
    values: list = [ctx.turn_id, rubric.name]
    values += [labels.bool_labels.get(c) for c in bool_cols]
    values += [
        labels.sentiment,
        labels.interaction_quality,
        labels.judge_id,
        labels.judge_model,
        labels.parse_status,
        _now_iso(),
    ]
    db.execute(
        f"""
        INSERT INTO heuristic_label ({", ".join(all_cols)})
        VALUES ({placeholders})
        ON CONFLICT (turn_id, rubric_name) DO UPDATE SET {updates}
        """,
        values,
    )


def run_default_by_copilot(
    db: Database,
    rubric: Rubric,
    config,
    *,
    workers: int = 1,
    overwrite: bool = False,
    session_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> dict:
    """Route each copilot's turns to its configured judge (the path taken
    when no explicit ``--judge`` is given). The packaged default routes every
    copilot to the local-only ollama judge; ``.env``/Settings can opt
    individual copilots into other judges. Returns a per-copilot stats map."""
    from .registry import get_judge

    copilots = _unlabeled_copilots(db, rubric.name, overwrite=overwrite, session_id=session_id)
    out: dict = {}
    for copilot in copilots:
        backend, model = config.judge.resolve(copilot)
        judge = get_judge(backend, model)
        stats = run_judge(
            db, judge, rubric,
            workers=workers, overwrite=overwrite, session_id=session_id,
            copilot=copilot, limit=limit,
        )
        out[copilot] = {"judge": f"{backend}:{model or '(default)'}", **stats.as_dict()}
    return out


def _unlabeled_copilots(db: Database, rubric_name: str, *, overwrite: bool, session_id):
    where = []
    params: list = [rubric_name]
    if not overwrite:
        where.append("h.id IS NULL")
    if session_id is not None:
        where.append("t.session_id = ?")
        params.append(session_id)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(
        f"""
        SELECT DISTINCT s.copilot
        FROM copilot_turn t
        JOIN copilot_session s ON s.id = t.session_id
        LEFT JOIN heuristic_label h ON h.turn_id = t.id AND h.rubric_name = ?
        {where_sql}
        """,
        tuple(params),
    )
    return [r[0] for r in rows]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
