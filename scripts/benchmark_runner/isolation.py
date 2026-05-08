# benchmark_runner.isolation — isolation tier resolver (Phase 0 stub).
#
# Phase 1 implements ``worktree`` (git worktree per task/attempt).
# Phase 2 implements ``worktree+venv``. Phase 3-or-later (issue #33's
# SWE-bench adapter) implements ``docker``. The schema slot for
# ``docker`` is reserved from day one — see specs/benchmark-harness/
# spec.md § "Isolation tiers."

from __future__ import annotations

from .contracts import (
    ISOLATION_DOCKER,
    ISOLATION_WORKTREE,
    ISOLATION_WORKTREE_VENV,
    IsolationTier,
)


_KNOWN_TIERS = (ISOLATION_WORKTREE, ISOLATION_WORKTREE_VENV, ISOLATION_DOCKER)


def is_known_tier(tier: str) -> bool:
    return tier in _KNOWN_TIERS


def known_tiers() -> tuple[str, ...]:
    return _KNOWN_TIERS


def assert_implemented(tier: IsolationTier) -> None:
    """Raise NotImplementedError for tiers not yet implemented.

    Phase 0 implements no tiers. Each later phase swaps the relevant
    branch to a working implementation.
    """
    if tier not in _KNOWN_TIERS:
        raise ValueError(
            f"unknown isolation tier: {tier!r}; known: {', '.join(_KNOWN_TIERS)}"
        )
    raise NotImplementedError(
        f"isolation tier {tier!r} is reserved in the schema but not yet "
        f"implemented in the runner (see specs/benchmark-harness/plan.md)"
    )
