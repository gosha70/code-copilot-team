# tests/test_collection_guard.py — the polyglot fixture tree must not be
# collected as tests (#268).
#
# `fixtures/polyglot_mini/` holds Exercism exercises used as INPUT DATA.
# Each ships an unsolved starter stub beside its test file, so
# `leap_test.py`'s four tests fail by design — that failure is what the
# adapter under test observes. `unittest discover` never sees them
# (pattern `test*.py`); pytest's default `python_files` includes
# `*_test.py`, so it does.
#
# The guard is a root `conftest.py`. These tests exist because a
# `collect_ignore_glob` that silently stops matching — a fixture tree
# renamed, the conftest moved or deleted — would restore the original
# defect with no signal at all.
#
# NOTE ON THE CANONICAL RUNNER: `unittest discover` remains it. Nothing
# here makes pytest a supported entry point; it only pins that a
# reasonable `pytest` invocation does not report fixture data as broken
# code.

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFTEST = _REPO_ROOT / "conftest.py"
_FIXTURE_REL = "scripts/benchmark_runner/tests/fixtures/polyglot_mini"
_BENCH_TESTS = _REPO_ROOT / "scripts" / "benchmark_runner" / "tests"


def _pytest_available() -> bool:
    try:
        import pytest  # noqa: F401
    except ImportError:
        return False
    return True


class TestCollectionGuardIsDeclared(unittest.TestCase):
    """Static half — runs everywhere, including where pytest is absent."""

    def test_root_conftest_exists(self) -> None:
        self.assertTrue(
            _CONFTEST.is_file(),
            f"{_CONFTEST} is the collection guard for #268; without it "
            f"pytest collects the polyglot fixture stubs as tests",
        )

    def test_conftest_ignores_the_polyglot_fixture_tree(self) -> None:
        # Parsed, not imported: this must hold even if a future conftest
        # grows imports that are unavailable here.
        if not _CONFTEST.is_file():
            self.fail(f"{_CONFTEST} is missing — the #268 guard is gone")
        tree = ast.parse(_CONFTEST.read_text(encoding="utf-8"))
        globs: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "collect_ignore_glob"
                for t in node.targets
            ):
                globs = [
                    el.value
                    for el in getattr(node.value, "elts", [])
                    if isinstance(el, ast.Constant) and isinstance(el.value, str)
                ]
        self.assertTrue(globs, "conftest.py declares no collect_ignore_glob")
        self.assertTrue(
            any(g.startswith(_FIXTURE_REL) for g in globs),
            f"no collect_ignore_glob covers {_FIXTURE_REL}; got {globs}",
        )

    def test_the_fixture_tree_still_exists_where_the_glob_points(self) -> None:
        # If the fixture moves, the glob silently stops matching and the
        # defect returns. This fails loudly instead.
        self.assertTrue(
            (_REPO_ROOT / _FIXTURE_REL).is_dir(),
            f"{_FIXTURE_REL} no longer exists — the #268 glob in "
            f"conftest.py now matches nothing and must be updated",
        )

    def test_the_stub_that_started_this_is_still_a_stub(self) -> None:
        # The guard's premise: leap_test.py is a *_test.py file that
        # pytest would collect and unittest would not.
        leap = _REPO_ROOT / _FIXTURE_REL / "python/exercises/practice/leap/leap_test.py"
        self.assertTrue(leap.is_file(), f"{leap} is the fixture #268 is about")
        self.assertTrue(leap.name.endswith("_test.py"))
        self.assertFalse(
            leap.name.startswith("test"),
            "leap_test.py must NOT match unittest's test*.py pattern — that "
            "asymmetry is the whole reason the fixture went unnoticed",
        )


@unittest.skipUnless(
    _pytest_available(),
    "pytest is not installed — the behavioural half of the #268 guard "
    "cannot run. The static half above still does, and CI runs "
    "`unittest discover`, which never collected these fixtures anyway.",
)
class TestPytestDoesNotCollectFixtures(unittest.TestCase):
    """Behavioural half — proves the guard actually takes effect."""

    @classmethod
    def _collect(cls) -> str:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", str(_BENCH_TESTS)],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
        )
        return proc.stdout

    def test_leap_test_is_not_collected(self) -> None:
        # Match the fixture PATH, not the bare string "leap_test": this
        # test's own id contains that substring, so asserting on it
        # matched itself and passed for the wrong reason. Caught while
        # verifying the fix.
        self.assertNotIn("leap/leap_test.py", self._collect())

    def test_no_fixture_file_is_collected_at_all(self) -> None:
        # Broader than leap_test: any fixture path appearing as a
        # collected item means the guard is not doing its job.
        collected = [
            line for line in self._collect().splitlines() if "fixtures/" in line
        ]
        self.assertEqual(collected, [])

    def test_genuine_benchmark_tests_are_still_collected(self) -> None:
        # The exclusion must not have been achieved by excluding
        # everything — the failure mode a "leap_test is gone" assertion
        # alone would happily accept.
        out = self._collect()
        self.assertIn("test_polyglot_adapter.py", out)
        self.assertIn("test_codex_backend.py", out)
        collected = [ln for ln in out.splitlines() if "::" in ln]
        self.assertGreater(len(collected), 500, "far too few tests collected")


if __name__ == "__main__":
    unittest.main()
