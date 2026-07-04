# session_analytics.judge.contracts — turn-judge Protocol + dataclasses.
#
# Frozen dataclasses + a runtime_checkable Protocol, mirroring the benchmark
# judge contract surface but turn-centric. The judge READS a turn's context
# and returns labels; the runner writes the heuristic_label row (additive —
# turn rows are never mutated).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Protocol, runtime_checkable

# Parse-status sentinels (recorded on the label row for auditing).
PARSE_OK = "ok"
PARSE_EMPTY = "empty"
PARSE_OUTER_UNPARSEABLE = "outer_unparseable"
PARSE_INNER_UNPARSEABLE = "inner_unparseable"
PARSE_TIMEOUT = "timeout"
PARSE_BACKEND_ERROR = "backend_error"


@dataclass(frozen=True)
class Rubric:
    """The heuristic rubric, loaded from config_data/heuristic-rubric.json."""

    name: str
    bool_labels: tuple[str, ...]
    sentiment_values: tuple[str, ...]
    quality_min: int
    quality_max: int
    prompt_template: str


@dataclass(frozen=True)
class TurnContext:
    """One turn handed to a judge for labeling."""

    turn_id: int
    role: str
    sequence_num: int
    text: str
    prev_text: str = ""
    has_tool_use: bool = False


@dataclass(frozen=True)
class TurnLabels:
    """A judge's labels for one turn.

    ``bool_labels`` maps each rubric bool label → True/False/None (None =
    judge could not decide / inapplicable). ``sentiment`` is one of the
    rubric's enum values or None. ``interaction_quality`` is an int in the
    rubric band or None.
    """

    bool_labels: Mapping[str, Optional[bool]]
    sentiment: Optional[str]
    interaction_quality: Optional[int]
    parse_status: str = PARSE_OK
    judge_id: str = ""
    judge_model: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class TurnJudge(Protocol):
    """Contract every turn judge must satisfy."""

    judge_id: str

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels: ...
