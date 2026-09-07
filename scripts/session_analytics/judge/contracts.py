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


class JudgeTransportError(RuntimeError):
    """The backend could not be reached or did not answer.

    Raised by ``complete`` so a caller that wants raw text (session-level
    analysis) sees the failure as an exception, while ``rate_turn`` keeps
    its never-raises contract by converting it into a backend_error row.
    """


class JudgeAnswerTruncated(JudgeTransportError):
    """The backend answered, but cut the answer off at its output cap.

    Carries the partial text so the caller can store its head: "the
    model wrote 8k tokens and never closed the JSON" is a different
    problem from "the model is down", and the fix is different (shorter
    lists, a stronger model — not a restart).
    """

    def __init__(self, message: str, partial: str = "") -> None:
        super().__init__(message)
        self.partial = partial


@runtime_checkable
class TurnJudge(Protocol):
    """Contract every turn judge must satisfy."""

    judge_id: str

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels: ...

    def complete(self, prompt: str, *, timeout: int = 120) -> str:
        """Send one prompt, return the model's text. Raises
        JudgeTransportError when the backend is unreachable or times out.
        The same transport ``rate_turn`` uses, exposed so a whole-session
        prompt can go through the judge the user already configured."""
        ...
