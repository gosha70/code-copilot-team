# tests/test_stub_adapter.py — stub adapter conformance.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_runner._register import unregister_all_for_tests
from benchmark_runner.contracts import BenchmarkAdapter, ISOLATION_WORKTREE


class TestStubAdapter(unittest.TestCase):
    def setUp(self) -> None:
        unregister_all_for_tests()
        from benchmarks.adapters.stub.adapter import StubAdapter, register
        register()
        self.adapter = StubAdapter()

    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(self.adapter, BenchmarkAdapter)

    def test_isolation_default(self) -> None:
        self.assertEqual(self.adapter.isolation_default, ISOLATION_WORKTREE)

    def test_lists_one_task(self) -> None:
        tasks = self.adapter.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_id, "hello-world")

    def test_max_attempts_single_shot(self) -> None:
        self.assertEqual(self.adapter.max_attempts(), 1)

    def test_prompt_for_returns_prompt_md(self) -> None:
        task = self.adapter.list_tasks()[0]
        prompt = self.adapter.prompt_for(task, attempt=1, prior=None)
        self.assertIn("hello.txt", prompt)
        self.assertIn("Hello, World!", prompt)

    def test_verify_passes_when_golden_present(self) -> None:
        task = self.adapter.list_tasks()[0]
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            (wt / "hello.txt").write_text("Hello, World!\n", encoding="utf-8")
            result = self.adapter.verify(task, wt)
        self.assertTrue(result.tests_passed)
        self.assertTrue(result.required_files_present)

    def test_verify_fails_when_missing(self) -> None:
        task = self.adapter.list_tasks()[0]
        with tempfile.TemporaryDirectory() as td:
            result = self.adapter.verify(task, Path(td))
        self.assertFalse(result.tests_passed)
        self.assertFalse(result.required_files_present)

    def test_verify_fails_on_content_mismatch(self) -> None:
        task = self.adapter.list_tasks()[0]
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            (wt / "hello.txt").write_text("wrong content\n", encoding="utf-8")
            result = self.adapter.verify(task, wt)
        self.assertFalse(result.tests_passed)
        self.assertTrue(result.required_files_present)  # file exists, content wrong

    def test_golden_patch_directory_exists(self) -> None:
        task = self.adapter.list_tasks()[0]
        golden = self.adapter.golden_patch(task)
        self.assertTrue(golden.is_dir())
        self.assertTrue((golden / "hello.txt").is_file())

    def test_unknown_task_raises(self) -> None:
        from benchmark_runner.contracts import TaskSpec

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(KeyError):
                self.adapter.prepare_task(
                    TaskSpec(task_id="not-real", language="text"),
                    Path(td),
                )


if __name__ == "__main__":
    unittest.main()
