# session_analytics.judge.registry — turn-judge discovery.
#
# Mirrors session_analytics.registry. A judge spec on the CLI is
# ``<family>:<model>`` (e.g. ``ollama:llama3``, ``claude-code:sonnet``); the
# family registers, the model is passed to the factory at resolution time.

from __future__ import annotations

from typing import Callable, Dict

from .contracts import TurnJudge

_JudgeFactory = Callable[[str], TurnJudge]

_JUDGES: Dict[str, _JudgeFactory] = {}


def register_judge(family: str, factory: _JudgeFactory) -> None:
    if family in _JUDGES:
        raise RuntimeError(f"judge already registered: {family!r}")
    _JUDGES[family] = factory


def list_judge_ids() -> list[str]:
    return sorted(_JUDGES)


def get_judge(family: str, model: str = "") -> TurnJudge:
    try:
        factory = _JUDGES[family]
    except KeyError:
        known = ", ".join(list_judge_ids()) or "(none)"
        raise UnknownJudgeError(
            f"unknown judge family: {family!r}; registered: {known}"
        ) from None
    return factory(model)


class UnknownJudgeError(LookupError):
    pass


def _reset_for_tests() -> None:
    _JUDGES.clear()
