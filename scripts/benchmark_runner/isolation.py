# benchmark_runner.isolation — per-attempt worktree provisioning.
#
# Phase 1 implements ``worktree`` (a clean directory per attempt under
# the run-dir; not a literal git worktree — the contract is "isolation,
# never shared," and that holds with a plain dir for the stub adapter).
# Phase 2c adds ``worktree+venv``: same plain dir, plus a
# ``.venv/`` provisioned with the adapter's ``python`` interpreter and
# the adapter's ``install_command`` run inside it.
# Issue #33 adds ``docker``: a long-lived container per attempt with the
# host worktree bind-mounted; container spans provision→verify→teardown.
# The container is tracked in a module-level registry keyed by worktree
# path; release_worktree() tears it down.

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .contracts import (
    ISOLATION_DOCKER,
    ISOLATION_WORKTREE,
    ISOLATION_WORKTREE_VENV,
    IsolationConfig,
    IsolationTier,
)

_log = logging.getLogger(__name__)

_KNOWN_TIERS = (ISOLATION_WORKTREE, ISOLATION_WORKTREE_VENV, ISOLATION_DOCKER)

# Module-level registry: worktree path (str) -> container_id (str).
# Populated by provision_worktree (docker tier), consumed + cleared by
# run_in_worktree and release_worktree. Keyed by the absolute string
# path so Path equality is not sensitive to symlink resolution.
_DOCKER_REGISTRY: dict[str, str] = {}
# Per-worktree in-container mount point (worktree path → mount). The
# docker-branch default cwd of run_in_worktree must match wherever the
# worktree was actually bind-mounted (SWE-bench uses /testbed, not the
# /workspace default) — conflating these was a real bug caught by
# docker verification.
_DOCKER_MOUNTS: dict[str, str] = {}

# Default in-container mount point for the bind-mounted host worktree.
# Single source of truth: used by _provision_docker (-v/-w) AND
# run_in_worktree's docker-branch default cwd. Must not be a bare
# literal in two places (host path != container path — conflating
# them was the real bug caught by docker verification).
_CONTAINER_MOUNT = "/workspace"


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
        return _provision_docker(config, attempt_dir)

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


# ── New public helpers (Issue #33) ────────────────────────────────────


def run_in_worktree(
    worktree: Path,
    argv: list[str],
    *,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run ``argv`` inside the container if ``worktree`` was docker-provisioned,
    else run it as a local subprocess.

    ``cwd`` is the working directory INSIDE the container (or on the host for
    non-docker worktrees); defaults to the worktree's absolute path.

    Returns a ``subprocess.CompletedProcess`` with ``returncode``,
    ``stdout``, and ``stderr``.
    """
    key = str(worktree.resolve())
    container_id = _DOCKER_REGISTRY.get(key)

    # cwd semantics differ by routing: inside the container the worktree
    # is bind-mounted at the fixed mount point (NOT the host tmp path —
    # `docker exec -w <host-path>` fails "chdir ... no such file or
    # directory"). The local branch uses the host worktree path. An
    # explicit `cwd` (e.g. SWE-bench's image repo dir) always wins.
    if container_id is not None:
        effective_cwd = cwd or _DOCKER_MOUNTS.get(key, _CONTAINER_MOUNT)
    else:
        effective_cwd = cwd or str(worktree.absolute())

    if container_id is not None:
        # Route through docker exec. NOTE: `docker exec` OPTIONS (incl.
        # `-w <dir>`) must precede the container id; anything after the
        # container id is the command to run in the container. Putting
        # `-w` after <cid> makes docker try to exec `-w` itself
        # (OCI "exec: -w: executable file not found"). Order is
        # load-bearing — caught by the real-docker verification, missed
        # by the docker-faked unit tests.
        docker_cmd = ["docker", "exec"]
        if effective_cwd:
            docker_cmd += ["-w", effective_cwd]
        docker_cmd += [container_id]
        docker_cmd += argv
        _log.debug("run_in_worktree (docker): %s", docker_cmd)
        return subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    else:
        # Non-docker worktree: local subprocess.
        _log.debug("run_in_worktree (local): %s", argv)
        return subprocess.run(
            argv,
            cwd=effective_cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )


def release_worktree(config: "IsolationConfig | IsolationTier", worktree: Path) -> None:
    """Tear down the isolation for ``worktree``.

    For the docker tier: ``docker rm -f <cid>`` and deregisters the
    worktree. For worktree/venv tiers: no-op (the runner keeps worktrees
    on disk for postmortem). Idempotent: double-call is safe.
    """
    if isinstance(config, str):
        tier = config
    else:
        tier = config.tier

    if tier != ISOLATION_DOCKER:
        return

    key = str(worktree.resolve())
    container_id = _DOCKER_REGISTRY.pop(key, None)
    _DOCKER_MOUNTS.pop(key, None)
    if container_id is None:
        # Already released or never registered (idempotent).
        return

    _log.debug("release_worktree: docker rm -f %s", container_id)
    proc = subprocess.run(
        ["docker", "rm", "-f", container_id],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        # Log but do not raise — teardown failures are not fatal; the
        # container is typically already gone (e.g. killed externally).
        _log.warning(
            "release_worktree: docker rm -f %s exited %d: %s",
            container_id,
            proc.returncode,
            (proc.stderr or proc.stdout).strip(),
        )


# ── Internals ──────────────────────────────────────────────────────────


def _provision_docker(config: IsolationConfig, attempt_dir: Path) -> Path:
    """Provision a docker-tier worktree.

    1. Probes ``docker version`` — a missing daemon is an ENVIRONMENT
       prerequisite failure (clear message, not a bug, not a skip).
    2. Creates the host worktree directory (mirrors ``_provision_plain``).
    3. Starts a long-lived container with the worktree bind-mounted at
       ``/workspace``:
           docker run -d -v <abs_worktree>:/workspace -w /workspace <image> sleep infinity
    4. Registers ``{worktree_path → container_id}`` in ``_DOCKER_REGISTRY``.
    5. Returns the host worktree ``Path`` (unchanged signature).

    No DinD, no image build, no provision-time copy. The worktree is
    empty at this point; ``prepare_task`` + the backend populate it
    before ``verify`` executes in-container via ``run_in_worktree``.
    """
    _require_docker()

    image = config.image
    if not image:
        raise IsolationProvisionError(
            "docker isolation tier requires IsolationConfig.image to be set "
            "(the prebuilt image reference, e.g. 'swebench/sweb.eval.x86_64.<id>')"
        )

    wt = _provision_plain(attempt_dir)
    abs_wt = str(wt.absolute())
    mount = config.container_mount or _CONTAINER_MOUNT

    _log.debug(
        "_provision_docker: starting container image=%s wt=%s mount=%s",
        image, abs_wt, mount,
    )
    proc = subprocess.run(
        [
            "docker", "run",
            "--detach",
            "--volume", f"{abs_wt}:{mount}",
            "--workdir", mount,
            image,
            "sleep", "infinity",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise IsolationProvisionError(
            f"docker run failed for image {image!r} (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )

    container_id = proc.stdout.strip()
    if not container_id:
        raise IsolationProvisionError(
            f"docker run succeeded but returned no container id (stdout empty); "
            f"image: {image!r}"
        )

    key = str(wt.resolve())
    _DOCKER_REGISTRY[key] = container_id
    _DOCKER_MOUNTS[key] = mount
    _log.info(
        "_provision_docker: container %s started for worktree %s (mount=%s)",
        container_id[:12], wt, mount,
    )
    return wt


def _require_docker() -> None:
    """Probe ``docker version``; raise ``IsolationProvisionError`` with an
    ENVIRONMENT-prerequisite message if Docker is absent.

    This is an environment check, not a harness bug. The error message
    explicitly says "install Docker" so the user knows the remedy.
    """
    if shutil.which("docker") is None:
        raise IsolationProvisionError(
            "ENVIRONMENT PREREQUISITE: the docker isolation tier requires "
            "'docker' on PATH. Install Docker Desktop or Docker Engine and "
            "start the daemon before running SWE-bench or other docker-tier "
            "benchmarks. (docker isolation is local-only; CI uses the stub tier.)"
        )
    proc = subprocess.run(
        ["docker", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise IsolationProvisionError(
            "ENVIRONMENT PREREQUISITE: 'docker version' failed "
            f"(exit {proc.returncode}). The Docker daemon may not be running. "
            f"Start the Docker daemon and retry. "
            f"stderr: {(proc.stderr or proc.stdout).strip()!r}"
        )


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
