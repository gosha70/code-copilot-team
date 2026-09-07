# session_analytics.judge.rubric — load the heuristic rubric (data file).

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from typing import Optional

from ..config import load_map
from .contracts import Rubric

_RUBRIC_FILE = "heuristic-rubric.json"


@lru_cache(maxsize=1)
def _base_rubric() -> Rubric:
    data = load_map(_RUBRIC_FILE)
    return Rubric(
        name=str(data["name"]),
        bool_labels=tuple(data["bool_labels"]),
        sentiment_values=tuple(data["sentiment_values"]),
        quality_min=int(data["quality_min"]),
        quality_max=int(data["quality_max"]),
        prompt_template=str(data["prompt_template"]),
    )


def load_rubric(name: Optional[str] = None) -> Rubric:
    """The packaged rubric, under its own name or a caller-chosen one.

    A named run (#313) is the same prompt and labels written under a
    different ``rubric_name``: heuristic_label is UNIQUE(turn_id,
    rubric_name), so two runs coexist and can be compared, and
    ``--overwrite`` only ever touches the run it was given. The base
    rubric stays cached; the rename is a frozen-dataclass replace.
    """
    base = _base_rubric()
    if not name or name == base.name:
        return base
    return replace(base, name=name)
