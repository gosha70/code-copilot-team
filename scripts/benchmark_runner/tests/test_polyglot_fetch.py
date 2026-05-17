# tests/test_polyglot_fetch.py — Aider Polyglot fetch script.
#
# These tests do NOT clone the real upstream — they exercise the
# script's contract: pin lookup, idempotency, missing-git path,
# and clone-failure cleanup. Real network usage is exercised
# manually via ``python -m benchmarks.adapters.aider_polyglot.fetch``
# and is gated to local invocation per spec.md (the Polyglot adapter
# never runs in CI).

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmarks.adapters.aider_polyglot import fetch


SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class TestPinnedRevision(unittest.TestCase):
    def test_pin_is_a_full_sha(self) -> None:
        sha = fetch.pinned_revision()
        self.assertTrue(
            SHA_RE.match(sha),
            f"REVISION must contain a full 40-char hex SHA; got {sha!r}",
        )

    def test_pin_strips_whitespace(self) -> None:
        # Defensive: trailing newlines in REVISION must not pollute the
        # SHA string used for cache paths or git checkout.
        sha = fetch.pinned_revision()
        self.assertEqual(sha, sha.strip())


class TestCacheDirAddressing(unittest.TestCase):
    def test_cache_dir_is_under_repo_cache(self) -> None:
        path = fetch.cache_dir("a" * 40)
        self.assertEqual(path.name, "a" * 40)
        self.assertTrue(path.parent.name == "polyglot")
        self.assertTrue(path.parent.parent.name == ".cache")

    def test_different_shas_get_distinct_dirs(self) -> None:
        a = fetch.cache_dir("a" * 40)
        b = fetch.cache_dir("b" * 40)
        self.assertNotEqual(a, b)
        self.assertEqual(a.parent, b.parent)

    def test_default_uses_pin(self) -> None:
        explicit = fetch.cache_dir(fetch.pinned_revision())
        implicit = fetch.cache_dir()
        self.assertEqual(explicit, implicit)


class TestEnsureCachedNoGit(unittest.TestCase):
    def test_raises_when_git_missing(self) -> None:
        # Force shutil.which('git') to return None; the function must
        # raise GitNotFoundError before touching the filesystem.
        with mock.patch.object(shutil, "which", return_value=None):
            with self.assertRaises(fetch.GitNotFoundError):
                fetch.ensure_cached()


class TestEnsureCachedIdempotent(unittest.TestCase):
    """When the cache is already populated, ensure_cached is a no-op.

    We simulate a populated cache by creating the marker structure
    ``is_cached`` checks for (the .git dir + the python/ subdir),
    redirected to a temp root via patching of the cache root.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cct-polyglot-cache-")
        self._orig_cache_root = fetch._CACHE_ROOT  # noqa: SLF001 (test patch)
        fetch._CACHE_ROOT = Path(self.tmp)  # type: ignore[misc]

    def tearDown(self) -> None:
        fetch._CACHE_ROOT = self._orig_cache_root  # type: ignore[misc]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _populate(self, sha: str) -> Path:
        target = fetch.cache_dir(sha)
        (target / ".git").mkdir(parents=True)
        (target / "python").mkdir()
        return target

    def test_existing_cache_skips_clone(self) -> None:
        sha = fetch.pinned_revision()
        populated = self._populate(sha)

        # Replace subprocess.run so any clone attempt fails the test.
        def _fail(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError(
                "ensure_cached must NOT shell out when the cache is already populated"
            )

        with mock.patch.object(subprocess, "run", _fail):
            result = fetch.ensure_cached(sha)

        self.assertEqual(result, populated)


class TestEnsureCachedFailureCleansTmp(unittest.TestCase):
    """A failed clone must not leave a half-populated cache directory."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cct-polyglot-cache-")
        self._orig_cache_root = fetch._CACHE_ROOT  # noqa: SLF001
        fetch._CACHE_ROOT = Path(self.tmp)  # type: ignore[misc]

    def tearDown(self) -> None:
        fetch._CACHE_ROOT = self._orig_cache_root  # type: ignore[misc]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_failed_clone_leaves_no_target_dir(self) -> None:
        sha = "deadbeef" * 5  # 40 chars; never a real SHA target

        def _failing_run(args, **kwargs):  # type: ignore[no-untyped-def]
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout="", stderr="simulated failure"
            )

        with mock.patch.object(subprocess, "run", _failing_run):
            with self.assertRaises(fetch.FetchFailedError):
                fetch.ensure_cached(sha)

        # Neither the target nor the .tmp sibling should remain.
        target = fetch.cache_dir(sha)
        self.assertFalse(target.exists(), f"target dir leaked: {target}")
        self.assertFalse(
            target.with_name(target.name + ".tmp").exists(),
            "tmp dir leaked",
        )


class TestCLI(unittest.TestCase):
    def test_returns_git_missing_exit_code_when_git_absent(self) -> None:
        with mock.patch.object(shutil, "which", return_value=None):
            rc = fetch.main([])
        self.assertEqual(rc, fetch.EXIT_GIT_MISSING)

    def test_module_form_invocation_exists(self) -> None:
        # Sanity: the file is importable as a module-form entrypoint.
        # We don't actually run it via subprocess (network) — just
        # confirm main() is a callable.
        self.assertTrue(callable(fetch.main))


if __name__ == "__main__":
    unittest.main()
