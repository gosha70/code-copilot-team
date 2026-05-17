# benchmarks.adapters.aider_polyglot.fetch — pin-and-clone the upstream dataset.
#
# The Aider Polyglot dataset (Aider-AI/polyglot-benchmark) lives outside
# this repo. We pin it by SHA in ``REVISION``, clone it on demand into a
# gitignored cache, and refuse to clone if the host has no ``git``.
#
# Idempotent: a second invocation with the same SHA is a no-op.
# Deterministic: the cache is content-addressed by the SHA the adapter
# is currently pinned to, so different REVISION pins (across branches,
# bisects, etc.) coexist on the same host.
#
# Usage (CLI):
#   python -m benchmark_runner.adapters.aider_polyglot.fetch
# Usage (programmatic):
#   from benchmarks.adapters.aider_polyglot.fetch import ensure_cached
#   path = ensure_cached()
#
# Exit codes (CLI):
#   0  cache populated to the pinned SHA (or already was).
#   2  ``git`` not on PATH.
#   3  ``git clone`` / ``git checkout`` failed.

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

UPSTREAM_REPO = "https://github.com/Aider-AI/polyglot-benchmark.git"

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_REVISION_FILE = _HERE / "REVISION"
_CACHE_ROOT = _REPO_ROOT / "benchmarks" / ".cache" / "polyglot"


# Exit codes are exposed as constants so tests can assert against them.
EXIT_OK = 0
EXIT_GIT_MISSING = 2
EXIT_GIT_FAILED = 3


class GitNotFoundError(RuntimeError):
    pass


class FetchFailedError(RuntimeError):
    pass


# ── Public API ─────────────────────────────────────────────────────────


def pinned_revision() -> str:
    """Read the SHA the adapter is currently pinned to.

    The REVISION file is committed; updating the pin is a deliberate
    edit (see this file's docstring + benchmarks/README.md for the
    upgrade procedure).
    """
    sha = _REVISION_FILE.read_text(encoding="utf-8").strip()
    if not sha:
        raise FetchFailedError(
            f"REVISION file is empty: {_REVISION_FILE}"
        )
    return sha


def cache_dir(sha: str | None = None) -> Path:
    """Return the (content-addressed) cache directory for ``sha``."""
    return _CACHE_ROOT / (sha or pinned_revision())


def is_cached(sha: str | None = None) -> bool:
    """True if the cache directory exists and looks populated."""
    target = cache_dir(sha)
    return (target / ".git").is_dir() and (target / "python").is_dir()


def ensure_cached(sha: str | None = None) -> Path:
    """Idempotent. Clone the upstream at ``sha`` (or the pin) if missing.

    Returns the cache path. Raises ``GitNotFoundError`` if ``git`` is
    not on PATH; raises ``FetchFailedError`` on clone/checkout failure.
    """
    if shutil.which("git") is None:
        raise GitNotFoundError(
            "the Aider Polyglot adapter needs `git` on PATH to clone the "
            "upstream dataset; install git or set up the cache manually "
            f"under {_CACHE_ROOT}"
        )

    target_sha = sha or pinned_revision()
    target = cache_dir(target_sha)

    if is_cached(target_sha):
        return target

    target.parent.mkdir(parents=True, exist_ok=True)

    # Use a sibling tmp dir while cloning so a partial clone never
    # leaves the cache in a poisoned state.
    tmp = target.with_name(target.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)

    try:
        _run_git(["clone", "--quiet", UPSTREAM_REPO, str(tmp)])
        _run_git(["-C", str(tmp), "checkout", "--quiet", target_sha])
    except FetchFailedError:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise

    tmp.rename(target)
    return target


# ── Internals ──────────────────────────────────────────────────────────


def _run_git(args: list[str]) -> None:
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise FetchFailedError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )


# ── CLI entrypoint ─────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    # Argv is ignored — fetch always honors REVISION. Kept for parity
    # with other module-form entrypoints.
    _ = argv
    try:
        path = ensure_cached()
    except GitNotFoundError as exc:
        print(f"polyglot-fetch: {exc}", file=sys.stderr)
        return EXIT_GIT_MISSING
    except FetchFailedError as exc:
        print(f"polyglot-fetch: {exc}", file=sys.stderr)
        return EXIT_GIT_FAILED

    print(f"polyglot-fetch: cache ready at {path}")
    return EXIT_OK


__all__ = [
    "UPSTREAM_REPO",
    "EXIT_GIT_FAILED",
    "EXIT_GIT_MISSING",
    "EXIT_OK",
    "FetchFailedError",
    "GitNotFoundError",
    "cache_dir",
    "ensure_cached",
    "is_cached",
    "main",
    "pinned_revision",
]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
