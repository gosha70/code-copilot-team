# tests/test_polyglot_adapter.py — Aider Polyglot adapter contract tests.
#
# Tests run against the synthetic mini-Polyglot fixture under
# ``tests/fixtures/polyglot_mini/`` (one task per language); they do
# NOT clone the real upstream. Real toolchain integration is exercised
# in Phase 2c with the venv tier; Phase 2b tests are toolchain-light
# and skip pytest-dependent assertions when pytest isn't installed.

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from benchmark_runner.contracts import (
    BenchmarkAdapter,
    TaskSpec,
    VerifyResult,
)

from benchmarks.adapters.aider_polyglot.adapter import (
    BENCHMARK_ID,
    LANGUAGES,
    AiderPolyglotAdapter,
    TEST_COMMAND,
)


_FIXTURE_ROOT = (
    Path(__file__).resolve().parent / "fixtures" / "polyglot_mini"
)

_HAS_PYTEST = importlib.util.find_spec("pytest") is not None


def _adapter() -> AiderPolyglotAdapter:
    return AiderPolyglotAdapter(dataset_root=_FIXTURE_ROOT)


class TestProtocolConformance(unittest.TestCase):
    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(_adapter(), BenchmarkAdapter)

    def test_max_attempts_two_shot(self) -> None:
        # Aider's protocol is two-shot with retry.
        self.assertEqual(_adapter().max_attempts(), 2)

    def test_benchmark_id(self) -> None:
        self.assertEqual(_adapter().benchmark_id, BENCHMARK_ID)


class TestListTasks(unittest.TestCase):
    def test_lists_one_task_per_language(self) -> None:
        tasks = _adapter().list_tasks()
        # The synthetic fixture ships exactly one task per language.
        self.assertEqual(len(tasks), len(LANGUAGES))
        self.assertEqual(
            sorted(t.language for t in tasks),
            sorted(LANGUAGES),
        )

    def test_task_id_includes_language_prefix(self) -> None:
        for task in _adapter().list_tasks():
            self.assertEqual(task.task_id, f"{task.language}/leap")

    def test_metadata_carries_solution_and_test_files(self) -> None:
        for task in _adapter().list_tasks():
            self.assertTrue(task.metadata["solution_files"])
            self.assertTrue(task.metadata["test_files"])
            self.assertTrue(task.metadata["example_files"])

    def test_empty_when_dataset_root_missing(self) -> None:
        a = AiderPolyglotAdapter(dataset_root=Path("/nonexistent/cache"))
        self.assertEqual(a.list_tasks(), [])

    def test_skips_malformed_config(self) -> None:
        # Make a copy of the fixture, corrupt one language's config, list.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "ds"
            shutil.copytree(_FIXTURE_ROOT, tmp)
            (tmp / "go" / "exercises" / "practice" / "leap" / ".meta" / "config.json"
             ).write_text("{ NOT JSON", encoding="utf-8")
            tasks = AiderPolyglotAdapter(dataset_root=tmp).list_tasks()
            self.assertEqual(len(tasks), len(LANGUAGES) - 1)
            self.assertNotIn("go/leap", [t.task_id for t in tasks])


class TestPrepareTask(unittest.TestCase):
    def _task(self, language: str) -> TaskSpec:
        for t in _adapter().list_tasks():
            if t.language == language:
                return t
        raise KeyError(language)

    def test_copies_solution_and_tests(self) -> None:
        task = self._task("python")
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            _adapter().prepare_task(task, wt)
            for sol in task.metadata["solution_files"]:
                self.assertTrue((wt / sol).is_file(), sol)
            for test_file in task.metadata["test_files"]:
                self.assertTrue((wt / test_file).is_file(), test_file)

    def test_copies_docs(self) -> None:
        task = self._task("python")
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            _adapter().prepare_task(task, wt)
            self.assertTrue((wt / ".docs" / "instructions.md").is_file())

    def test_does_not_copy_meta_dir(self) -> None:
        # The reference solution lives under .meta/example.* — the model
        # must never see it. The whole .meta/ tree is skipped (it also
        # contains upstream-tooling files that are irrelevant at runtime).
        task = self._task("python")
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            _adapter().prepare_task(task, wt)
            self.assertFalse((wt / ".meta").exists(), ".meta/ leaked into worktree")

    def test_copies_nested_paths(self) -> None:
        # Rust's solution lives at src/lib.rs, test at tests/leap.rs —
        # exercise the nested-paths path so a future bug doesn't flatten.
        task = self._task("rust")
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            _adapter().prepare_task(task, wt)
            self.assertTrue((wt / "src" / "lib.rs").is_file())
            self.assertTrue((wt / "tests" / "leap.rs").is_file())


class TestPromptFor(unittest.TestCase):
    def _task(self, language: str) -> TaskSpec:
        for t in _adapter().list_tasks():
            if t.language == language:
                return t
        raise KeyError(language)

    def test_attempt_1_includes_instructions(self) -> None:
        task = self._task("python")
        prompt = _adapter().prompt_for(task, attempt=1, prior=None)
        self.assertIn("Determine whether a given year is a leap year", prompt)
        self.assertIn("leap.py", prompt)        # solution file listed
        self.assertIn("leap_test.py", prompt)   # test file listed

    def test_attempt_1_includes_test_command(self) -> None:
        task = self._task("python")
        prompt = _adapter().prompt_for(task, attempt=1, prior=None)
        # The harness tells the model what test command will run.
        for word in TEST_COMMAND["python"]:
            self.assertIn(word, prompt)

    def test_attempt_1_includes_append_when_present(self) -> None:
        task = self._task("python")
        prompt = _adapter().prompt_for(task, attempt=1, prior=None)
        self.assertIn("Implement `leap_year(year: int) -> bool`", prompt)

    def test_attempt_2_appends_prior_output(self) -> None:
        task = self._task("python")
        prior = VerifyResult(
            tests_passed=False,
            tests_output="AssertionError: 2024 should be a leap year",
        )
        prompt = _adapter().prompt_for(task, attempt=2, prior=prior)
        self.assertIn("previous attempt failed", prompt.lower())
        self.assertIn("2024 should be a leap year", prompt)

    def test_attempt_1_does_not_include_retry_block(self) -> None:
        task = self._task("python")
        prompt = _adapter().prompt_for(task, attempt=1, prior=None)
        self.assertNotIn("previous attempt failed", prompt.lower())


class TestGoldenPatch(unittest.TestCase):
    def test_python_golden_renames_example_to_solution(self) -> None:
        adapter = _adapter()
        task = next(t for t in adapter.list_tasks() if t.language == "python")
        with tempfile.TemporaryDirectory() as td:
            # Re-root the adapter at a copy of the fixture so the golden
            # cache doesn't collide with future test runs.
            copied = Path(td) / "ds"
            shutil.copytree(_FIXTURE_ROOT, copied)
            local_adapter = AiderPolyglotAdapter(dataset_root=copied)
            golden = local_adapter.golden_patch(task)
            self.assertTrue((golden / "leap.py").is_file())
            content = (golden / "leap.py").read_text(encoding="utf-8")
            self.assertIn("def leap_year", content)
            self.assertIn("year % 4", content)

    def test_cpp_multifile_golden(self) -> None:
        # C++ task has two solution files (leap.cpp + leap.h) paired
        # with two example files. The pairing must be order-aligned.
        adapter = _adapter()
        task = next(t for t in adapter.list_tasks() if t.language == "cpp")
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "ds"
            shutil.copytree(_FIXTURE_ROOT, copied)
            local_adapter = AiderPolyglotAdapter(dataset_root=copied)
            golden = local_adapter.golden_patch(task)
            self.assertTrue((golden / "leap.cpp").is_file())
            self.assertTrue((golden / "leap.h").is_file())

    def test_golden_is_idempotent(self) -> None:
        adapter = _adapter()
        task = next(t for t in adapter.list_tasks() if t.language == "python")
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "ds"
            shutil.copytree(_FIXTURE_ROOT, copied)
            local_adapter = AiderPolyglotAdapter(dataset_root=copied)
            first = local_adapter.golden_patch(task)
            second = local_adapter.golden_patch(task)
            self.assertEqual(first, second)


class TestVerify(unittest.TestCase):
    """Phase 2b verify tests.

    The Python verify path runs ``python -m pytest -q`` against the
    worktree. When pytest isn't available on the host (which is the
    case on a fresh dev machine), we skip the pass/fail assertions
    and instead just confirm verify returns a VerifyResult of the
    right shape. Phase 2c provisions pytest inside a worktree-local
    venv, after which these checks become unconditional.
    """

    def _task(self, language: str) -> TaskSpec:
        for t in _adapter().list_tasks():
            if t.language == language:
                return t
        raise KeyError(language)

    def test_verify_returns_result_shape(self) -> None:
        # Always-runnable shape check.
        task = self._task("python")
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            _adapter().prepare_task(task, wt)
            result = _adapter().verify(task, wt)
            self.assertIsInstance(result, VerifyResult)
            self.assertIsInstance(result.tests_passed, bool)
            self.assertIsInstance(result.tests_output, str)

    @unittest.skipUnless(_HAS_PYTEST, "pytest not installed; Phase 2c venv tier covers this")
    def test_python_verify_passes_with_example_solution(self) -> None:
        adapter = _adapter()
        task = self._task("python")
        with tempfile.TemporaryDirectory() as td:
            copied = Path(td) / "ds"
            shutil.copytree(_FIXTURE_ROOT, copied)
            local_adapter = AiderPolyglotAdapter(dataset_root=copied)
            wt = Path(td) / "wt"
            wt.mkdir()
            local_adapter.prepare_task(task, wt)
            # Drop the reference example into the worktree to simulate
            # a successful backend.
            for src in local_adapter.golden_patch(task).rglob("*"):
                if src.is_file():
                    rel = src.relative_to(local_adapter.golden_patch(task))
                    (wt / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, wt / rel)
            result = local_adapter.verify(task, wt)
            self.assertTrue(
                result.tests_passed,
                f"verify should pass with the example solution; output:\n{result.tests_output}",
            )

    @unittest.skipUnless(_HAS_PYTEST, "pytest not installed; Phase 2c venv tier covers this")
    def test_python_verify_fails_with_starter(self) -> None:
        adapter = _adapter()
        task = self._task("python")
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            adapter.prepare_task(task, wt)
            # Leave the starter stub in place — pytest should fail.
            result = adapter.verify(task, wt)
            self.assertFalse(result.tests_passed)
            self.assertIn("starter stub", result.tests_output.lower())


class TestIsolationFor(unittest.TestCase):
    """Per-task isolation directive: Python -> worktree+venv, others -> worktree."""

    def _task(self, language: str) -> TaskSpec:
        for t in _adapter().list_tasks():
            if t.language == language:
                return t
        raise KeyError(language)

    def test_python_uses_worktree_plus_venv(self) -> None:
        from benchmark_runner.contracts import (
            ISOLATION_WORKTREE_VENV,
        )
        task = self._task("python")
        config = _adapter().isolation_for(task)
        self.assertEqual(config.tier, ISOLATION_WORKTREE_VENV)
        self.assertIsNotNone(config.python)
        self.assertIsNotNone(config.install_command)
        self.assertIn("pytest", config.install_command or "")

    def test_non_python_uses_plain_worktree(self) -> None:
        from benchmark_runner.contracts import ISOLATION_WORKTREE
        for lang in ("go", "javascript", "rust", "java", "cpp"):
            task = self._task(lang)
            config = _adapter().isolation_for(task)
            self.assertEqual(
                config.tier, ISOLATION_WORKTREE, f"{lang} should use plain worktree"
            )
            self.assertIsNone(config.install_command)


class TestVenvPython(unittest.TestCase):
    """``_maybe_use_venv_python``: regression coverage for the
    relative-path-vs-subprocess-cwd interaction.

    Background: ``verify`` calls subprocess with ``cwd=worktree``, so
    the path passed as ``cmd[0]`` is resolved by the kernel relative
    to ``worktree`` — not to the harness's process cwd. A relative
    path like ``runs/.../worktree/.venv/bin/python`` becomes
    ``runs/.../worktree/runs/.../worktree/.venv/bin/python`` at exec
    time and fails ENOENT. ``Path.exists()`` doesn't catch this
    because Python resolves it against the process cwd. The fix is
    that ``_maybe_use_venv_python`` must return an absolute path.
    """

    def test_returned_path_is_absolute(self) -> None:
        from benchmarks.adapters.aider_polyglot.adapter import (
            _maybe_use_venv_python,
        )
        with tempfile.TemporaryDirectory() as td:
            # Build a fake worktree-relative-to-cwd: chdir to td's
            # parent and use a relative Path. The .venv/bin/python
            # must exist so the helper enters the substitution branch.
            old_cwd = os.getcwd()
            try:
                parent = Path(td)
                os.chdir(parent)
                rel_worktree = Path("wt")
                (rel_worktree / ".venv" / "bin").mkdir(parents=True)
                fake_python = rel_worktree / ".venv" / "bin" / "python"
                fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                fake_python.chmod(0o755)
                cmd = _maybe_use_venv_python(
                    "python", rel_worktree, ["python", "-m", "pytest", "-q"]
                )
                self.assertTrue(
                    Path(cmd[0]).is_absolute(),
                    f"_maybe_use_venv_python must return an absolute "
                    f"path for cmd[0]; got: {cmd[0]!r}",
                )
                # The absolute path must actually point at the venv
                # python (not at the cwd-relativized double-prefix).
                self.assertEqual(
                    Path(cmd[0]).resolve(),
                    fake_python.resolve(),
                )
            finally:
                os.chdir(old_cwd)

    def test_returned_path_preserves_symlinks(self) -> None:
        # Regression: `python3 -m venv` creates ``.venv/bin/python`` as
        # a symlink chain pointing at the system interpreter. We MUST
        # NOT follow the symlinks (no Path.resolve()), because the
        # venv's sys.path machinery is triggered by the path the
        # interpreter is invoked AS, not by where its binary actually
        # lives. Following the symlink chain ends up running the
        # system python, which has no access to the venv's
        # site-packages → "ModuleNotFoundError: No module named pytest".
        from benchmarks.adapters.aider_polyglot.adapter import (
            _maybe_use_venv_python,
        )
        with tempfile.TemporaryDirectory() as td:
            worktree = Path(td)
            venv_bin = worktree / ".venv" / "bin"
            venv_bin.mkdir(parents=True)
            # Real target (analog of /opt/homebrew/.../python3.13):
            real_python = worktree / "real-python"
            real_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            real_python.chmod(0o755)
            # Symlink chain mirroring how `python3 -m venv` lays it out
            # on macOS: .venv/bin/python -> python3 -> python3.13
            # -> /opt/.../python3.13
            (venv_bin / "python3.13").symlink_to(real_python.resolve())
            (venv_bin / "python3").symlink_to("python3.13")
            (venv_bin / "python").symlink_to("python3")

            cmd = _maybe_use_venv_python(
                "python", worktree, ["python", "-m", "pytest", "-q"]
            )
            self.assertEqual(
                str(Path(cmd[0])),
                str((worktree / ".venv" / "bin" / "python").absolute()),
                "Returned path must point at the venv's symlink, not "
                "the symlink target. Following the chain escapes the "
                "venv and breaks site-packages.",
            )
            # Sanity: the returned path is absolute and lives under
            # the venv (never under the symlink target).
            self.assertTrue(Path(cmd[0]).is_absolute())
            self.assertIn(".venv", str(cmd[0]))

    def test_falls_back_to_plain_python_when_venv_missing(self) -> None:
        from benchmarks.adapters.aider_polyglot.adapter import (
            _maybe_use_venv_python,
        )
        with tempfile.TemporaryDirectory() as td:
            worktree = Path(td)  # no .venv/ inside
            cmd = _maybe_use_venv_python(
                "python", worktree, ["python", "-m", "pytest", "-q"]
            )
            self.assertEqual(cmd, ["python", "-m", "pytest", "-q"])

    def test_passes_through_non_python_languages(self) -> None:
        from benchmarks.adapters.aider_polyglot.adapter import (
            _maybe_use_venv_python,
        )
        with tempfile.TemporaryDirectory() as td:
            worktree = Path(td)
            (worktree / ".venv" / "bin").mkdir(parents=True)
            (worktree / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            cmd = _maybe_use_venv_python("go", worktree, ["go", "test", "./..."])
            self.assertEqual(cmd, ["go", "test", "./..."])


class TestRegister(unittest.TestCase):
    """register() function side-effects.

    Confirms the adapter registers under the right id and that
    register() is idempotent within a single test (the registry
    raises on duplicate registration; calling register() twice from
    a clean registry is the test of that).
    """

    def setUp(self) -> None:
        from benchmark_runner._register import unregister_all_for_tests
        unregister_all_for_tests()

    def test_register_puts_adapter_in_registry(self) -> None:
        from benchmarks.adapters.aider_polyglot.adapter import register
        from benchmark_runner.registry import get_adapter, list_adapter_ids
        register()
        self.assertIn(BENCHMARK_ID, list_adapter_ids())
        adapter = get_adapter(BENCHMARK_ID)
        self.assertIsInstance(adapter, BenchmarkAdapter)


if __name__ == "__main__":
    unittest.main()
