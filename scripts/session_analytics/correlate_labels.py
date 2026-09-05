# session_analytics.correlate_labels — E10 label correlation (#65).
#
# Joins archived trace text to the judge's per-turn labels, so an
# operator can ask "show me what the agent actually said on the turns
# labelled X" instead of reading a boolean in isolation.
#
# The join is (session, sequence_num), NOT trace_document.id ↔
# heuristic_label.turn_id: re-ingest DELETEs and reinserts turn rows with
# fresh ids (001_core says so in as many words), so a stored turn id is
# not stable across runs while the (session, turn-number) pair is.
#
# COVERAGE IS REPORTED, NEVER ASSUMED. The archive is opt-in per project
# and the judge is run separately, so most stores have labels without
# traces, traces without labels, or neither. A correlation over a handful
# of rows is not a finding, and this says how many rows it had.

from __future__ import annotations

from typing import Any, Optional

from . import constants as C
from .relational.db import Database


def _bool_labels() -> tuple[str, ...]:
    """The rubric's boolean labels — the source of truth for what exists."""
    from .judge.rubric import load_rubric

    return tuple(
        label for label in load_rubric().bool_labels if label.isidentifier()
    )


def label_trace_coverage(db: Database) -> dict[str, Any]:
    """How much labelled material actually has archived trace text.

    This is the precondition for every other number here: a label with
    no archived traces cannot be correlated with anything, and saying so
    is more useful than an empty result that looks like a finding.
    """
    labelled = db.query_one(
        f"SELECT COUNT(*) FROM {C.TBL_HEURISTIC_LABEL}"
    ) or (0,)
    archived = db.query_one(
        f"SELECT COUNT(*) FROM {C.TBL_TRACE_DOCUMENT}"
    ) or (0,)
    both = db.query_one(
        f"""
        SELECT COUNT(*)
        FROM {C.TBL_HEURISTIC_LABEL} h
        JOIN copilot_turn t ON t.id = h.turn_id
        JOIN {C.TBL_TRACE_DOCUMENT} td
          ON td.session_ref = t.session_id
         AND td.sequence_num = t.sequence_num
        """
    ) or (0,)
    return {
        "labelled_turns": int(labelled[0] or 0),
        "archived_turns": int(archived[0] or 0),
        "labelled_turns_with_trace": int(both[0] or 0),
    }


def correlations(db: Database, *, min_support: int = 5) -> dict[str, Any]:
    """Per-label counts over turns that have BOTH a label and a trace.

    ``min_support`` is the number of correlated turns below which a
    label's figures are returned but marked ``sufficient=False``. A rate
    computed from one or two turns is noise wearing a percentage sign,
    and the caller must be able to tell the two apart — so the count is
    always reported alongside, never replaced by, the rate.
    """
    coverage = label_trace_coverage(db)
    out: list[dict[str, Any]] = []
    for label in _bool_labels():
        row = db.query_one(
            f"""
            SELECT COUNT(*),
                   SUM(CASE WHEN h.{label} THEN 1 ELSE 0 END),
                   AVG(LENGTH(td.content)),
                   AVG(h.interaction_quality)
            FROM {C.TBL_HEURISTIC_LABEL} h
            JOIN copilot_turn t ON t.id = h.turn_id
            JOIN {C.TBL_TRACE_DOCUMENT} td
              ON td.session_ref = t.session_id
             AND td.sequence_num = t.sequence_num
            WHERE h.{label} IS NOT NULL
            """
        ) or (0, 0, None, None)
        correlated = int(row[0] or 0)
        true_count = int(row[1] or 0)
        out.append({
            "label": label,
            "correlated_turns": correlated,
            "true_count": true_count,
            # None rather than 0.0 when there is nothing to divide by:
            # "no data" is not "never true".
            "true_rate": (true_count / correlated) if correlated else None,
            "avg_trace_chars": float(row[2]) if row[2] is not None else None,
            "avg_interaction_quality": float(row[3]) if row[3] is not None else None,
            "sufficient": correlated >= min_support,
        })
    out.sort(key=lambda r: (-r["correlated_turns"], r["label"]))
    return {
        "coverage": coverage,
        "labels": out,
        "min_support": min_support,
        "sufficient_labels": sum(1 for r in out if r["sufficient"]),
    }


def traces_for_label(
    db: Database,
    label: str,
    *,
    value: bool = True,
    limit: int = C.SEARCH_DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Archived trace snippets for turns carrying ``label``.

    The point of the slice: read what was actually said on the turns a
    label fired on. ``label`` is validated against the rubric rather than
    interpolated blind — it reaches SQL as an identifier, so an unchecked
    value would be an injection point.
    """
    if label not in _bool_labels():
        raise ValueError(f"unknown label: {label!r}")
    limit = max(1, min(int(limit), C.SEARCH_MAX_LIMIT))
    rows = db.query(
        f"""
        SELECT s.copilot, s.session_id, s.project_path, t.sequence_num,
               t.role, td.redaction_mode, td.content, h.sentiment
        FROM {C.TBL_HEURISTIC_LABEL} h
        JOIN copilot_turn t ON t.id = h.turn_id
        JOIN copilot_session s ON s.id = t.session_id
        JOIN {C.TBL_TRACE_DOCUMENT} td
          ON td.session_ref = t.session_id
         AND td.sequence_num = t.sequence_num
        WHERE h.{label} = ?
        ORDER BY t.session_id, t.sequence_num
        LIMIT ?
        """,
        (value, limit),
    )
    from .archive import make_snippet

    return [
        {
            "copilot": r[0],
            "session_id": r[1],
            "project_path": r[2],
            "sequence_num": int(r[3]),
            "role": r[4],
            "redaction_mode": r[5],
            "snippet": make_snippet(r[6] or "", ""),
            "sentiment": r[7],
        }
        for r in rows
    ]
