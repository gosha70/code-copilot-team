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
import re
import subprocess
import sys
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFTEST = _REPO_ROOT / "conftest.py"
_FIXTURE_REL = "scripts/benchmark_runner/tests/fixtures/polyglot_mini"
_EXPECTED_GLOB = f"{_FIXTURE_REL}/*"
_BENCH_TESTS = _REPO_ROOT / "scripts" / "benchmark_runner" / "tests"
_COLLECT_TIMEOUT_SECONDS = 300


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

    def test_conftest_declares_exactly_the_effective_glob(self) -> None:
        """The declaration must be EFFECTIVE, not merely present.

        A prefix match proves nothing. Three ways a passing-looking
        conftest is still broken, all rejected here:

          `polyglot_mini_MOVED/*`  matches the prefix, matches no files
          an extra blanket entry   also hides real tests
          nested in `if False:`    parsed by ast.walk, never executed

        So: parse only MODULE-LEVEL assignments, require exactly one,
        and compare the list to the exact expected value. This is a
        pin, not a configuration interpreter — it deliberately knows
        one right answer rather than reasoning about globs in general.
        """
        if not _CONFTEST.is_file():
            self.fail(f"{_CONFTEST} is missing — the #268 guard is gone")
        tree = ast.parse(_CONFTEST.read_text(encoding="utf-8"))

        # tree.body, NOT ast.walk: a correct assignment inside `if False:`
        # or a function body would satisfy a walk and never run.
        assigns = [
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "collect_ignore_glob"
                for t in node.targets
            )
        ]
        self.assertEqual(
            len(assigns),
            1,
            "conftest.py must assign collect_ignore_glob exactly once, at "
            f"module level; found {len(assigns)} module-level assignments",
        )
        value = assigns[0].value
        self.assertIsInstance(
            value, ast.List, "collect_ignore_glob must be a list literal"
        )
        # Check the ELEMENTS, do not filter them: a comprehension that
        # kept only string constants silently discarded any other entry,
        # so `[expected, f"..."]` (an f-string is ast.JoinedStr) and
        # `[expected, 123]` both compared equal to the expected list.
        # The first broadens the exclusion; the second is invalid config.
        self.assertEqual(
            len(value.elts),
            1,
            f"the exclusion must be exactly one entry; found {len(value.elts)}"
            " — an extra entry hides real tests",
        )
        entry = value.elts[0]
        self.assertTrue(
            isinstance(entry, ast.Constant) and isinstance(entry.value, str),
            f"the entry must be a string literal, got {ast.dump(entry)}",
        )
        self.assertEqual(
            entry.value,
            _EXPECTED_GLOB,
            "the exclusion must be exactly this glob — a renamed target "
            f"silently matches nothing. Got: {entry.value!r}",
        )

    def test_the_expected_glob_actually_matches_the_fixture(self) -> None:
        # The pin above is only worth something if the value it pins is
        # the one that matches. Resolve it against the real tree.
        matched = list(_REPO_ROOT.glob(_EXPECTED_GLOB))
        self.assertTrue(
            matched,
            f"{_EXPECTED_GLOB} matches nothing under {_REPO_ROOT} — the "
            f"fixture tree moved and the guard is now inert",
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

    # A node id line looks like `path/to/file.py::Class::method`.
    # Assertions run against THESE, never against raw stdout: stdout also
    # carries warnings, error text and tracebacks, and matching those is
    # how a "leap_test" assertion once matched this test's own id.
    _NODE_ID = re.compile(r"^\S+\.py::")

    @classmethod
    def _node_ids(cls, *extra_args: str) -> list[str]:
        """Collected node ids, or an assertion failure with diagnostics.

        The exit status is checked. pytest exits 2 on a collection error
        while STILL printing the ids it managed to collect, so ignoring
        the status let all three of these tests pass against a run that
        had actually failed to import a module.
        """
        argv = [
            sys.executable, "-m", "pytest",
            "--collect-only", "-q", str(_BENCH_TESTS), *extra_args,
        ]
        try:
            proc = subprocess.run(
                argv,
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=_COLLECT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise AssertionError(
                f"pytest collection exceeded {_COLLECT_TIMEOUT_SECONDS}s: "
                f"{' '.join(argv)}"
            ) from None
        if proc.returncode != 0:
            raise AssertionError(
                f"pytest collection FAILED (exit {proc.returncode}) — its "
                f"output cannot be used as evidence.\n"
                f"argv: {' '.join(argv)}\n"
                f"--- stdout tail ---\n{proc.stdout[-2000:]}\n"
                f"--- stderr tail ---\n{proc.stderr[-2000:]}"
            )
        return [ln for ln in proc.stdout.splitlines() if cls._NODE_ID.match(ln)]

    def test_collection_succeeds_at_all(self) -> None:
        # Stated as its own test so a collection failure reports as
        # exactly that, rather than as a confusing count assertion.
        self.assertTrue(self._node_ids(), "no node ids collected")

    def test_no_fixture_file_is_collected(self) -> None:
        # Covers leap_test.py and any other fixture file. Matches the
        # fixture PATH within a node id, never a bare token.
        offenders = [nid for nid in self._node_ids() if "/fixtures/" in nid]
        self.assertEqual(offenders, [])

    def test_genuine_benchmark_tests_are_still_collected(self) -> None:
        # The exclusion must not have been achieved by excluding
        # everything — the failure mode a "no fixtures" assertion alone
        # would happily accept.
        ids = self._node_ids()
        for expected in ("test_polyglot_adapter.py::", "test_codex_backend.py::"):
            self.assertTrue(
                any(expected in nid for nid in ids), f"{expected} not collected"
            )
        self.assertGreater(len(ids), 500, f"far too few collected: {len(ids)}")

    def test_the_guard_is_what_removes_them(self) -> None:
        """Guarded vs unguarded, in one run — effectiveness, not presence.

        `--confcutdir` below the repo root stops pytest loading the root
        conftest without touching the file, so the delta between the two
        collections IS the guard's effect. A declaration that matched
        nothing would show a delta of zero here.
        """
        guarded = set(self._node_ids())
        unguarded = set(self._node_ids(f"--confcutdir={_BENCH_TESTS}"))
        removed = unguarded - guarded
        self.assertTrue(
            removed, "the conftest removes nothing — the glob is inert"
        )
        self.assertTrue(
            all("/fixtures/polyglot_mini/" in nid for nid in removed),
            f"the guard removed non-fixture tests: "
            f"{sorted(nid for nid in removed if '/fixtures/' not in nid)}",
        )
        self.assertEqual(
            guarded - unguarded, set(), "the guard must not ADD collected tests"
        )


if __name__ == "__main__":
    unittest.main()
