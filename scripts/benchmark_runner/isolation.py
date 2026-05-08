# benchmark_runner.isolation — per-attempt worktree provisioning.
#
# Phase 1 implements ``worktree`` (a clean directory per attempt under
# the run-dir; not a literal git worktree — the contract is "isolation,
# never shared," and that holds with a plain dir for the stub adapter).
# Phase 2 adds ``worktree+venv``. Issue #33 adds ``docker``.

from __future__ import annotations

from pathlib import Path

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


def provision_worktree(tier: IsolationTier, attempt_dir: Path) -> Path:
    """Create a fresh worktree directory for one attempt.

    Returns the worktree path. The caller (run.py) is responsible for
    invoking ``adapter.prepare_task(task, worktree)`` afterwards to
    populate it.
    """
    if tier not in _KNOWN_TIERS:
        raise ValueError(
            f"unknown isolation tier: {tier!r}; known: {', '.join(_KNOWN_TIERS)}"
        )

    if tier == ISOLATION_WORKTREE:
        wt = attempt_dir / "worktree"
        wt.mkdir(parents=True, exist_ok=False)
        return wt

    if tier == ISOLATION_WORKTREE_VENV:
        # Phase 2: provision venv + install_command. For now treat as
        # a plain worktree; real venv creation lands with the Aider
        # Polyglot adapter.
        raise NotImplementedError(
            "isolation tier 'worktree+venv' lands in Phase 2 "
            "(see specs/benchmark-harness/plan.md)"
        )

    if tier == ISOLATION_DOCKER:
        raise NotImplementedError(
            "isolation tier 'docker' lands with issue #33's SWE-bench adapter"
        )

    # Unreachable due to the early check, but keep mypy happy.
    raise AssertionError(f"unhandled tier: {tier!r}")
