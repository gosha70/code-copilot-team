# benchmark_runner.isolation — per-attempt worktree provisioning.
#
# Phase 1 implements ``worktree`` (a clean directory per attempt under
# the run-dir; not a literal git worktree — the contract is "isolation,
# never shared," and that holds with a plain dir for the stub adapter).
# Phase 2c adds ``worktree+venv``: same plain dir, plus a
# ``.venv/`` provisioned with the adapter's ``python`` interpreter and
# the adapter's ``install_command`` run inside it.
# Issue #33 will add ``docker``.

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .contracts import (
    ISOLATION_DOCKER,
    ISOLATION_WORKTREE,
    ISOLATION_WORKTREE_VENV,
    IsolationConfig,
    IsolationTier,
)


_KNOWN_TIERS = (ISOLATION_WORKTREE, ISOLATION_WORKTREE_VENV, ISOLATION_DOCKER)


def is_known_tier(tier: str) -> bool:
    return tier in _KNOWN_TIERS


def known_tiers() -> tuple[str, ...]:
    return _KNOWN_TIERS


class IsolationProvisionError(RuntimeError):
    """Raised when the runner cannot provision the requested tier.

    Distinct from NotImplementedError (a tier the harness has not yet
    implemented) — this is for runtime failures inside an implemented
    tier (venv creation failure, install_command non-zero exit, etc.).
    """


def provision_worktree(
    config: "IsolationConfig | IsolationTier",
    attempt_dir: Path,
) -> Path:
    """Create a fresh worktree directory + (for the venv tier) a venv.

    Accepts either a fully-typed ``IsolationConfig`` (preferred, what
    the runner now passes via ``adapter.isolation_for(task)``) or a
    bare ``IsolationTier`` string (kept for ergonomic callers and the
    Phase-1 contract; equivalent to ``IsolationConfig(tier=...)``).

    For the ``worktree+venv`` tier, this creates the worktree dir and
    the ``.venv/`` inside it but does NOT yet run
    ``config.install_command``. The install step lives in
    ``install_dependencies`` so that adapter task files
    (pyproject.toml, requirements.txt, etc.) are present in the
    worktree before any project-aware install runs. Lifecycle:

        provision_worktree(config, attempt_dir)
        adapter.prepare_task(task, worktree)
        install_dependencies(config, worktree)
        # ...snapshot, prompt, backend, verify...
    """
    if isinstance(config, str):
        config = IsolationConfig(tier=config)  # type: ignore[arg-type]

    if config.tier not in _KNOWN_TIERS:
        raise ValueError(
            f"unknown isolation tier: {config.tier!r}; known: {', '.join(_KNOWN_TIERS)}"
        )

    if config.tier == ISOLATION_WORKTREE:
        return _provision_plain(attempt_dir)

    if config.tier == ISOLATION_WORKTREE_VENV:
        wt = _provision_plain(attempt_dir)
        _create_venv(wt, config)
        return wt

    if config.tier == ISOLATION_DOCKER:
        raise NotImplementedError(
            "isolation tier 'docker' lands with issue #33's SWE-bench adapter"
        )

    # Unreachable; placates mypy.
    raise AssertionError(f"unhandled tier: {config.tier!r}")


def install_dependencies(config: IsolationConfig, worktree: Path) -> None:
    """Run ``config.install_command`` inside the worktree's venv.

    Called by run.py AFTER ``adapter.prepare_task`` so that
    project-aware install commands (e.g. ``pip install -e .[dev]``)
    can see the task's pyproject.toml/setup.py. No-op when the tier
    is plain ``worktree`` or there is no install_command.
    """
    if config.tier != ISOLATION_WORKTREE_VENV or not config.install_command:
        return
    venv_dir = worktree / ".venv"
    if not venv_dir.is_dir():
        raise IsolationProvisionError(
            f"install_dependencies called before venv creation; expected {venv_dir} to exist"
        )
    _run_install_command(worktree, venv_dir, config.install_command)


# ── Internals ──────────────────────────────────────────────────────────


def _provision_plain(attempt_dir: Path) -> Path:
    wt = attempt_dir / "worktree"
    wt.mkdir(parents=True, exist_ok=False)
    return wt


def _create_venv(worktree: Path, config: IsolationConfig) -> None:
    """Create ``.venv`` only — install_command runs separately."""
    python = config.python or "python3"
    if shutil.which(python) is None:
        raise IsolationProvisionError(
            f"worktree+venv tier requires {python!r} on PATH; install it or "
            f"configure the adapter's python interpreter via IsolationConfig.python"
        )

    venv_dir = worktree / ".venv"
    proc = subprocess.run(
        [python, "-m", "venv", str(venv_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise IsolationProvisionError(
            f"venv creation failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


def _run_install_command(
    worktree: Path, venv_dir: Path, install_command: str
) -> None:
    # Run with the venv's bin directory at the front of PATH so
    # ``pip``, ``pytest``, etc., resolve to the venv's copies. We
    # don't activate the venv (no shell needed); just prepend.
    env_path = f"{venv_dir / 'bin'}:" + os.environ.get("PATH", "")
    proc = subprocess.run(
        ["bash", "-lc", install_command],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": env_path, "VIRTUAL_ENV": str(venv_dir)},
    )
    if proc.returncode != 0:
        raise IsolationProvisionError(
            f"install_command failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
