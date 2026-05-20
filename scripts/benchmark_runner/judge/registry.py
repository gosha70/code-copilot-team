# benchmark_runner.judge.registry — judge discovery (parallel to
# benchmark_runner.registry for adapters/backends).
#
# A judge spec on the CLI is ``<family>:<model>`` (e.g.
# ``claude-code:sonnet``). The family is what registers; the model
# is passed to the factory at resolution time, mirroring the
# backend pattern.
#
# Aliases. The same factory may be registered under multiple family
# tokens — this is how the SDD-canonical ``claude-code`` and the
# internal ``claude-code-judge`` (the ``judge_id`` recorded in
# judge.json) coexist as accepted CLI inputs (see the round-3 peer
# review of TB1.2: spec.md scenarios use ``claude-code:sonnet``,
# while a maintainer reading a judge.json sees ``judge_id:
# "claude-code-judge"``; both spellings must work). Registering the
# same factory under multiple tokens is explicitly supported and
# not treated as a duplicate-registration error.
#
# Test isolation. ``_reset_for_tests`` clears the registry so the
# test suite can selectively register what it needs without
# coupling to the shipped set.

from __future__ import annotations

from typing import Callable, Dict

from .contracts import Judge

_JudgeFactory = Callable[[str], Judge]  # accepts a model spec

_JUDGES: Dict[str, _JudgeFactory] = {}


# ── Public API ─────────────────────────────────────────────────────────


def register_judge(family: str, factory: _JudgeFactory) -> None:
    """Register a judge family + factory.

    Registering the same factory under multiple tokens is allowed
    (the canonical-name / alias pattern; see module docstring).
    Re-registering the SAME family with a DIFFERENT factory raises
    ``RuntimeError`` — that's a programmer error.
    """
    existing = _JUDGES.get(family)
    if existing is not None and existing is not factory:
        raise RuntimeError(
            f"judge family {family!r} already registered with a "
            f"different factory; aliases must share the underlying "
            f"factory object"
        )
    _JUDGES[family] = factory


def list_judge_ids() -> list[str]:
    """Return registered family tokens, sorted lexicographically.

    Sorting is the load-bearing determinism guarantee: callers
    (e.g. ``benchmark list``) get the same order on every machine.
    """
    return sorted(_JUDGES)


def get_judge(family: str, model: str = "") -> Judge:
    """Resolve a judge by family token + model id.

    Raises ``UnknownJudgeError`` if the family is not registered.
    The error message lists every registered family (including
    aliases) so the user sees what they could have typed.
    """
    try:
        factory = _JUDGES[family]
    except KeyError:
        known = ", ".join(list_judge_ids()) or "(none)"
        raise UnknownJudgeError(
            f"unknown judge family: {family!r}; registered families: {known}"
        ) from None
    return factory(model)


# ── Errors ─────────────────────────────────────────────────────────────


class UnknownJudgeError(LookupError):
    pass


# ── Test-only helpers ──────────────────────────────────────────────────


def _reset_for_tests() -> None:
    """Clear the judge registry. Test-suite use only."""
    _JUDGES.clear()
