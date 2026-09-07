# session_analytics.judge.runner — label un-labeled turns (additive).
#
# Selects turns that have no heuristic_label for the rubric, runs the judge
# (optionally across worker threads — the judges are I/O-bound on HTTP /
# subprocess), and writes one heuristic_label row per turn. Turn rows are
# never mutated. Idempotent: ON CONFLICT(turn_id, rubric_name) DO UPDATE.

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from ..relational.db import Database
from .contracts import Rubric, TurnContext, TurnJudge, TurnLabels
from .label_sources import label_source_join

_log = logging.getLogger(__name__)


@dataclass
class JudgeStats:
    labeled: int = 0
    parse_ok: int = 0
    parse_failed: int = 0
    #: How many turns this run set out to label, and the reason the
    #: most recent failure gave — what a progress display needs.
    total: int = 0
    last_error: str = ""
    judge: str = ""
    per_copilot: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {
            "labeled": self.labeled, "parse_ok": self.parse_ok, "parse_failed": self.parse_failed,
            "total": self.total, "last_error": self.last_error, "judge": self.judge,
        }
        if self.per_copilot:
            out["by_copilot"] = self.per_copilot
        return out


#: Called after every turn is written, with the running stats.
ProgressFn = Callable[[JudgeStats], None]


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
    only_labelled_by: Optional[str] = None,
    progress: Optional[ProgressFn] = None,
    stats: Optional[JudgeStats] = None,
) -> JudgeStats:
    """``only_labelled_by`` (#313) restricts the run to turns that already
    carry labels from another source — `rubric:<name>` or
    `human:<labeler>` — so a second run labels the SAME turns as the
    first and the two can be compared pair by pair.

    Each label is written and committed AS IT ARRIVES, and ``progress``
    is called after each one. The run used to collect every answer
    before writing any: a 50-turn run that died at turn 49 kept nothing,
    and nothing could be shown while it ran. ``stats`` lets a caller
    accumulate across several runs (one per copilot)."""
    contexts = _select_turns(
        db, rubric, overwrite=overwrite, session_id=session_id, copilot=copilot,
        limit=limit, only_labelled_by=only_labelled_by,
    )
    stats = stats if stats is not None else JudgeStats()
    stats.total += len(contexts)
    stats.judge = f"{getattr(judge, 'judge_id', '')}:{getattr(judge, '_model', '') or ''}".strip(":")
    if not contexts:
        if progress:
            progress(stats)
        return stats

    from .contracts import PARSE_OK

    def _rate(ctx: TurnContext) -> tuple[TurnContext, TurnLabels]:
        return ctx, judge.rate_turn(ctx, rubric)

    def _record(ctx: TurnContext, labels: TurnLabels) -> None:
        # DB writes are serialized here (one connection, not thread-safe).
        _write_label(db, ctx, rubric, labels)
        db.commit()
        stats.labeled += 1
        if labels.parse_status == PARSE_OK:
            stats.parse_ok += 1
        else:
            stats.parse_failed += 1
            stats.last_error = str(
                (labels.metadata or {}).get("error") or labels.parse_status
            )[:300]
        if progress:
            progress(stats)

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_rate, c) for c in contexts]
            for fut in as_completed(futures):
                ctx, labels = fut.result()
                _record(ctx, labels)
    else:
        for c in contexts:
            _record(*_rate(c))
    return stats


def _select_turns(
    db: Database,
    rubric: Rubric,
    *,
    overwrite: bool,
    session_id: Optional[int],
    copilot: Optional[str] = None,
    limit: Optional[int] = None,
    only_labelled_by: Optional[str] = None,
) -> list[TurnContext]:
    where = []
    params: list = [rubric.name]
    join = "LEFT JOIN heuristic_label h ON h.turn_id = t.id AND h.rubric_name = ?"
    if only_labelled_by:
        source_join, source_params = label_source_join(only_labelled_by, "t")
        join += " " + source_join
        params += list(source_params)
    if copilot is not None:
        join += " JOIN copilot_session s ON s.id = t.session_id"
        where.append("s.copilot = ?")
        params.append(copilot)
    if not overwrite:
        where.append("h.id IS NULL")
    # A turn with no text (a tool-result turn under redaction) gives the
    # judge nothing to judge: under the old prompt it answered "false"
    # for everything, which inflated agreement; under the new one it
    # answers null. Either way the call is wasted — skip it (#313).
    where.append("t.content_preview IS NOT NULL AND t.content_preview <> ''")
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
    only_labelled_by: Optional[str] = None,
    progress: Optional[ProgressFn] = None,
    stats: Optional[JudgeStats] = None,
) -> dict:
    """Route each copilot's turns to its configured judge (the path taken
    when no explicit ``--judge`` is given). The packaged default routes every
    copilot to the local-only ollama judge; ``.env``/Settings can opt
    individual copilots into other judges. Returns a per-copilot stats map;
    ``stats``/``progress`` accumulate across the copilots."""
    from .registry import get_judge

    copilots = _unlabeled_copilots(db, rubric.name, overwrite=overwrite, session_id=session_id)
    out: dict = {}
    total = stats if stats is not None else JudgeStats()
    for copilot in copilots:
        backend, model = config.judge.resolve(copilot)
        judge = get_judge(backend, model)
        before = (total.labeled, total.parse_ok, total.parse_failed, total.total)
        run_judge(
            db, judge, rubric,
            workers=workers, overwrite=overwrite, session_id=session_id,
            copilot=copilot, limit=limit, only_labelled_by=only_labelled_by,
            progress=progress, stats=total,
        )
        out[copilot] = {
            "judge": f"{backend}:{model or '(default)'}",
            "labeled": total.labeled - before[0],
            "parse_ok": total.parse_ok - before[1],
            "parse_failed": total.parse_failed - before[2],
            "total": total.total - before[3],
        }
        total.per_copilot = out
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
