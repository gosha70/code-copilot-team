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
import re
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
    """Run ``config.install_command`` inside the worktree's venv, then
    verify the declared ``verify_imports`` are actually importable.

    Called by run.py AFTER ``adapter.prepare_task`` so that
    project-aware install commands (e.g. ``pip install -e .[dev]``)
    can see the task's pyproject.toml/setup.py. No-op when the tier
    is plain ``worktree`` or there is no install_command.

    Post-install import check: ``pip install`` can exit 0 without
    actually installing the requested packages — most commonly under
    transient network failures where pip retries internally, prints
    a warning to stderr (which ``-q`` suppresses), and ultimately
    returns success without having downloaded anything. The harness
    has no way to detect this from the exit code alone. The
    ``verify_imports`` field on ``IsolationConfig`` lets the adapter
    declare which modules MUST be importable post-install; we run
    ``<venv>/bin/python -c "import <m>"`` for each and raise
    ``IsolationProvisionError`` if any fails. This converts a silent
    "install no-op'd but exited 0" into a loud, debuggable failure.
    Discovered on 2026-05-15 when 5 of 6 Polyglot attempts hit this.
    """
    if config.tier != ISOLATION_WORKTREE_VENV or not config.install_command:
        return
    venv_dir = worktree / ".venv"
    if not venv_dir.is_dir():
        raise IsolationProvisionError(
            f"install_dependencies called before venv creation; expected {venv_dir} to exist"
        )
    _run_install_command(worktree, venv_dir, config.install_command)
    _verify_installed_imports(venv_dir, config.verify_imports, config.install_command)


# Strict dotted-identifier match: same shape as Python's own module
# resolver accepts. Validating before invoking python prevents any
# value supplied to verify_imports from becoming Python source —
# even if the adapter is malicious, dataset-derived, or simply
# malformed. Defence-in-depth alongside the data-not-code import
# invocation below.
_MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _verify_installed_imports(
    venv_dir: Path, verify_imports: tuple[str, ...], install_command: str
) -> None:
    """Confirm every name in ``verify_imports`` is importable in the venv.

    Failure raises ``IsolationProvisionError`` with the offending
    module name, the install_command that was supposed to install it,
    and a hint that pip likely exited 0 without doing the work.

    Security: ``verify_imports`` entries are passed to the subprocess
    Python as ``sys.argv[1]`` — *data, not code* — and resolved via
    ``importlib.import_module``. Each entry is also validated as a
    dotted Python identifier before invocation, so even adapters
    that surface dataset-derived strings can't smuggle code into the
    subprocess via this surface.
    """
    if not verify_imports:
        return
    # Absolute path: ``subprocess.run`` resolves the binary relative
    # to its own cwd if given a bare or relative ``argv[0]``; we
    # don't pass ``cwd=`` here so it inherits the harness's cwd,
    # but absolutizing keeps the contract stable regardless of how
    # this helper gets called.
    python = (venv_dir / "bin" / "python").absolute()
    if not python.exists():
        raise IsolationProvisionError(
            f"verify_imports check requires {python} to exist; venv creation may have been incomplete"
        )
    for module in verify_imports:
        if not isinstance(module, str) or not _MODULE_NAME_RE.match(module):
            raise IsolationProvisionError(
                f"verify_imports entry {module!r} is not a valid Python module name "
                f"(dotted identifier required, e.g. 'pytest', 'numpy.linalg'). "
                f"Refusing to invoke subprocess with unvalidated input."
            )
        proc = subprocess.run(
            [
                str(python),
                "-c",
                "import importlib, sys; importlib.import_module(sys.argv[1])",
                module,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise IsolationProvisionError(
                f"install_command exited 0 but {module!r} is not importable. "
                f"Most likely pip silently no-op'd (transient network failure + "
                f"-q flag hides the warning). Install command was: {install_command!r}. "
                f"importlib.import_module({module!r}) stderr: {proc.stderr.strip()!r}"
            )


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
    #
    # IMPORTANT: ``bash -c``, NOT ``bash -lc``. A login shell on macOS
    # triggers ``/etc/profile`` → ``/usr/libexec/path_helper`` which
    # rebuilds PATH from ``/etc/paths{,.d/*}`` and clobbers the
    # venv-prepended PATH we just constructed.
    #
    # CRITICAL: the venv bin entry MUST be absolute. ``subprocess.run``
    # is called with ``cwd=str(worktree)``, and the kernel's PATH
    # lookup re-relativizes any relative entry against the subprocess
    # cwd. So a relative ``runs/.../worktree/.venv/bin`` ends up
    # searched as ``<worktree>/runs/.../worktree/.venv/bin/pip`` —
    # doesn't exist — falls through to the next PATH entry, which on
    # a Mac is typically the system Python's pip (or worse, a broken
    # `/usr/local/bin/pip` shim). Symptom in the field: pip exits 0
    # with "Requirement already satisfied" pulling from
    # ``~/Library/Python/3.<x>/lib/python/site-packages``, but the
    # venv keeps only ``pip + pip.dist-info``. Regression: see
    # ``test_isolation.py::test_install_command_uses_venv_pip_under_relative_worktree``.
    venv_bin_abs = (venv_dir / "bin").absolute()
    env_path = f"{venv_bin_abs}:" + os.environ.get("PATH", "")
    proc = subprocess.run(
        ["bash", "-c", install_command],
        cwd=str(worktree.absolute()),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": env_path, "VIRTUAL_ENV": str(venv_dir.absolute())},
    )
    if proc.returncode != 0:
        raise IsolationProvisionError(
            f"install_command failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
