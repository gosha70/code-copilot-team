# session_analytics.judge.parse — shared label-JSON parser.
#
# Both judges (ollama, claude-code) produce a JSON object of labels; this
# pure function extracts and validates it against the rubric. Never raises —
# returns a TurnLabels with a parse_status that tells the caller what
# happened, mirroring the benchmark judge's defensive parser discipline.

from __future__ import annotations

import json
import re
from typing import Optional

from .contracts import (
    PARSE_INNER_UNPARSEABLE,
    PARSE_OK,
    Rubric,
    TurnLabels,
)

_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_labels(
    text: str,
    rubric: Rubric,
    *,
    judge_id: str,
    judge_model: str,
) -> TurnLabels:
    obj = _extract_json_object(text)
    if obj is None:
        return _empty(rubric, PARSE_INNER_UNPARSEABLE, judge_id, judge_model)

    bools: dict[str, Optional[bool]] = {}
    for label in rubric.bool_labels:
        bools[label] = _coerce_bool(obj.get(label))

    sentiment = _coerce_sentiment(obj.get("sentiment"), rubric)
    quality = _coerce_quality(obj.get("interaction_quality"), rubric)

    return TurnLabels(
        bool_labels=bools,
        sentiment=sentiment,
        interaction_quality=quality,
        parse_status=PARSE_OK,
        judge_id=judge_id,
        judge_model=judge_model,
    )


def _empty(rubric: Rubric, status: str, judge_id: str, judge_model: str) -> TurnLabels:
    return TurnLabels(
        bool_labels={label: None for label in rubric.bool_labels},
        sentiment=None,
        interaction_quality=None,
        parse_status=status,
        judge_id=judge_id,
        judge_model=judge_model,
    )


def _extract_json_object(text: str):
    if not text or not text.strip():
        return None
    # Try the whole string first, then the first {...} span.
    for candidate in (text, _first_object_span(text)):
        if candidate is None:
            continue
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _first_object_span(text: str) -> Optional[str]:
    m = _OBJECT_RE.search(text)
    return m.group(0) if m else None


def _coerce_bool(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes", "1"):
            return True
        if s in ("false", "no", "0"):
            return False
    return None


def _coerce_sentiment(v, rubric: Rubric) -> Optional[str]:
    if not isinstance(v, str):
        return None
    up = v.strip().upper()
    return up if up in rubric.sentiment_values else None


def _coerce_quality(v, rubric: Rubric) -> Optional[int]:
    if isinstance(v, bool):  # bool is an int subclass — reject
        return None
    if isinstance(v, int):
        iv = v
    elif isinstance(v, float) and v.is_integer():
        iv = int(v)
    elif isinstance(v, str) and v.strip().lstrip("-").isdigit():
        iv = int(v.strip())
    else:
        return None
    if rubric.quality_min <= iv <= rubric.quality_max:
        return iv
    return None
