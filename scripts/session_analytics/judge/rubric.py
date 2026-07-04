# session_analytics.judge.rubric — load the heuristic rubric (data file).

from __future__ import annotations

from functools import lru_cache

from ..config import load_map
from .contracts import Rubric

_RUBRIC_FILE = "heuristic-rubric.json"


@lru_cache(maxsize=1)
def load_rubric() -> Rubric:
    data = load_map(_RUBRIC_FILE)
    return Rubric(
        name=str(data["name"]),
        bool_labels=tuple(data["bool_labels"]),
        sentiment_values=tuple(data["sentiment_values"]),
        quality_min=int(data["quality_min"]),
        quality_max=int(data["quality_max"]),
        prompt_template=str(data["prompt_template"]),
    )
