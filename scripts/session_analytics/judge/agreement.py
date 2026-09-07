# session_analytics.judge.agreement — how far can the judge be trusted?
#
# The judge's labels are the assumption every downstream number rests on
# (#313). This module measures them: two label sources over the same
# turns — a rubric run against a repeat run (run-to-run agreement) or
# against a person (human agreement) — compared label by label, with the
# sample size beside every figure. A pair counts for a label only when
# BOTH sides said something (non-NULL): "not applicable" and "not sure"
# are not disagreements, and they are not agreements either.
#
# Cohen's kappa is reported next to raw agreement because raw agreement
# is inflated by a label that is almost always false on both sides; kappa
# is zero for two sources that agree only as often as chance would.

from __future__ import annotations

from typing import Any, Optional

from .. import constants as C
from ..relational.db import Database
from .label_sources import LabelSource, parse_label_source
from .rubric import load_rubric

#: Below this many pairs a figure is shown but not trusted.
MIN_PAIRS = 20


def _read_labels(db: Database, src: LabelSource) -> dict[tuple[int, int], dict[str, Any]]:
    """(session_id, sequence_num) → {label: value, ...} for one source."""
    rubric = load_rubric()
    cols = list(rubric.bool_labels) + ["sentiment", "interaction_quality"]
    if src.kind == C.LABEL_SOURCE_RUBRIC:
        rows = db.query(
            f"SELECT t.session_id, t.sequence_num, {', '.join('h.' + c for c in cols)} "
            f"FROM {C.TBL_HEURISTIC_LABEL} h JOIN copilot_turn t ON t.id = h.turn_id "
            f"WHERE h.rubric_name = ? AND h.parse_status = ?",
            (src.name, "ok"),
        )
    else:
        rows = db.query(
            f"SELECT session_ref, sequence_num, {', '.join(cols)} "
            f"FROM {C.TBL_HUMAN_LABEL} WHERE labeler = ?",
            (src.name,),
        )
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for r in rows:
        out[(int(r[0]), int(r[1]))] = dict(zip(cols, r[2:]))
    return out


def _as_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    return bool(v)


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> Optional[float]:
    """κ for two binary raters; None when undefined (no pairs, or both
    raters constant so chance agreement is 1)."""
    n = len(pairs)
    if n == 0:
        return None
    agree = sum(1 for a, b in pairs if a == b) / n
    pa = sum(1 for a, _ in pairs if a) / n
    pb = sum(1 for _, b in pairs if b) / n
    chance = pa * pb + (1 - pa) * (1 - pb)
    if chance >= 1.0:
        return None
    return round((agree - chance) / (1 - chance), 3)


def agreement(db: Database, a_spec: str, b_spec: str) -> dict[str, Any]:
    """Per-label agreement between two label sources over the turns both
    labelled. Every figure carries its n; ``sufficient`` says whether n
    clears MIN_PAIRS."""
    a_src, b_src = parse_label_source(a_spec), parse_label_source(b_spec)
    a, b = _read_labels(db, a_src), _read_labels(db, b_src)
    shared = sorted(set(a) & set(b))
    rubric = load_rubric()

    labels = []
    for label in rubric.bool_labels:
        pairs = []
        for key in shared:
            x, y = _as_bool(a[key].get(label)), _as_bool(b[key].get(label))
            if x is None or y is None:
                continue
            pairs.append((x, y))
        n = len(pairs)
        agree = sum(1 for x, y in pairs if x == y)
        labels.append({
            "label": label,
            "n": n,
            "agreement": round(agree / n, 3) if n else None,
            "kappa": cohen_kappa(pairs),
            "a_true": sum(1 for x, _ in pairs if x),
            "b_true": sum(1 for _, y in pairs if y),
            "sufficient": n >= MIN_PAIRS,
        })

    sent_pairs = [
        (a[k]["sentiment"], b[k]["sentiment"]) for k in shared
        if a[k].get("sentiment") and b[k].get("sentiment")
    ]
    qual_pairs = [
        (int(a[k]["interaction_quality"]), int(b[k]["interaction_quality"])) for k in shared
        if a[k].get("interaction_quality") is not None and b[k].get("interaction_quality") is not None
    ]
    return {
        "a": a_src.spec,
        "b": b_src.spec,
        "turns_a": len(a),
        "turns_b": len(b),
        "turns_shared": len(shared),
        "min_pairs": MIN_PAIRS,
        "labels": labels,
        "sentiment": {
            "n": len(sent_pairs),
            "exact": round(sum(1 for x, y in sent_pairs if x == y) / len(sent_pairs), 3) if sent_pairs else None,
            "sufficient": len(sent_pairs) >= MIN_PAIRS,
        },
        "interaction_quality": {
            "n": len(qual_pairs),
            "within_1": round(sum(1 for x, y in qual_pairs if abs(x - y) <= 1) / len(qual_pairs), 3) if qual_pairs else None,
            "exact": round(sum(1 for x, y in qual_pairs if x == y) / len(qual_pairs), 3) if qual_pairs else None,
            "sufficient": len(qual_pairs) >= MIN_PAIRS,
        },
        "basis": (
            "pairs are turns labelled non-null by both sources; kappa is Cohen's and is "
            "undefined (—) when both sources are constant — e.g. a label neither side "
            "ever fired, where 100% agreement says nothing about the label; under "
            "min_pairs a figure is shown but is not evidence"
        ),
    }


def label_runs(db: Database) -> dict[str, Any]:
    """What can be compared: every rubric run with its parsed-turn count
    and every human labeler with theirs."""
    rubric_rows = db.query(
        f"SELECT rubric_name, COUNT(*), MIN(created_at), MAX(created_at), MAX(judge_id), MAX(judge_model) "
        f"FROM {C.TBL_HEURISTIC_LABEL} WHERE parse_status = ? GROUP BY rubric_name ORDER BY rubric_name",
        ("ok",),
    )
    human_rows = db.query(
        f"SELECT labeler, COUNT(*), MIN(created_at), MAX(created_at) "
        f"FROM {C.TBL_HUMAN_LABEL} GROUP BY labeler ORDER BY labeler",
    )
    return {
        "rubrics": [
            {"source": f"{C.LABEL_SOURCE_RUBRIC}:{r[0]}", "name": r[0], "turns": int(r[1]),
             "first": r[2], "last": r[3], "judge": f"{r[4] or ''}:{r[5] or ''}".strip(":")}
            for r in rubric_rows
        ],
        "humans": [
            {"source": f"{C.LABEL_SOURCE_HUMAN}:{r[0]}", "labeler": r[0], "turns": int(r[1]),
             "first": r[2], "last": r[3]}
            for r in human_rows
        ],
        "min_pairs": MIN_PAIRS,
    }
