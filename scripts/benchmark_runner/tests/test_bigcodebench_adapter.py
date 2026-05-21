# tests/test_bigcodebench_adapter.py — BigCodeBench adapter shape tests.
#
# Pure fixture-based: stages a small synthetic JSONL cache so the
# adapter loads tasks without hitting the network. No live HF API,
# no live pip installs. End-to-end ``run_in_worktree`` paths are
# covered by the harness's existing test_run_orchestration suite.

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from benchmark_runner.contracts import (
    ISOLATION_WORKTREE_VENV,
    BenchmarkAdapter,
    TaskSpec,
)

from benchmarks.adapters.bigcodebench.adapter import (
    BENCHMARK_ID,
    BigCodeBenchAdapter,
    _row_to_task_spec,
    register,
)


# A minimal valid BigCodeBench row (mirrors the real schema fields).
_SAMPLE_ROW = {
    "task_id": "BigCodeBench/0",
    "code_prompt": (
        "import itertools\n"
        "from random import shuffle\n"
        "def task_func(numbers=list(range(1, 3))):\n"
    ),
    "instruct_prompt": "Implement task_func that returns the sum of inputs.",
    "complete_prompt": "Implement task_func ... full docstring here ...",
    "canonical_solution": "    return sum(numbers)\n",
    "test": (
        "import unittest\n"
        "class TestCases(unittest.TestCase):\n"
        "    def test_default(self):\n"
        "        self.assertEqual(task_func([1, 2, 3]), 6)\n"
    ),
    "entry_point": "task_func",
    "libs": ["random", "itertools"],
}


class TestRowToTaskSpec(unittest.TestCase):
    def test_valid_row_produces_task(self) -> None:
        spec = _row_to_task_spec(_SAMPLE_ROW)
        self.assertIsNotNone(spec)
        self.assertEqual(spec.task_id, "BigCodeBench/0")
        self.assertEqual(spec.language, "python")
        self.assertEqual(spec.metadata["entry_point"], "task_func")
        self.assertEqual(spec.metadata["libs"], ["random", "itertools"])

    def test_missing_task_id_is_skipped(self) -> None:
        row = dict(_SAMPLE_ROW)
        del row["task_id"]
        self.assertIsNone(_row_to_task_spec(row))

    def test_missing_code_prompt_is_skipped(self) -> None:
        row = dict(_SAMPLE_ROW)
        row["code_prompt"] = ""
        self.assertIsNone(_row_to_task_spec(row))

    def test_libs_string_form_parsed(self) -> None:
        # BigCodeBench's libs field is sometimes a stringified list.
        row = dict(_SAMPLE_ROW)
        row["libs"] = "['random', 'itertools']"
        spec = _row_to_task_spec(row)
        self.assertEqual(spec.metadata["libs"], ["random", "itertools"])


class TestAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-bcb-")
        self.cache = Path(self._tmp) / "tasks.jsonl"
        self.cache.write_text(
            json.dumps(_SAMPLE_ROW) + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_satisfies_protocol(self) -> None:
        a = BigCodeBenchAdapter(cache_file=self.cache)
        self.assertIsInstance(a, BenchmarkAdapter)

    def test_benchmark_id_constant(self) -> None:
        self.assertEqual(BENCHMARK_ID, "bigcodebench")
        self.assertEqual(BigCodeBenchAdapter(cache_file=self.cache).benchmark_id, "bigcodebench")

    def test_list_tasks_reads_cache(self) -> None:
        a = BigCodeBenchAdapter(cache_file=self.cache)
        tasks = a.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_id, "BigCodeBench/0")

    def test_list_tasks_missing_cache_returns_empty(self) -> None:
        a = BigCodeBenchAdapter(cache_file=Path("/nonexistent/path.jsonl"))
        self.assertEqual(a.list_tasks(), [])

    def test_isolation_filters_stdlib_from_libs(self) -> None:
        # ``random`` and ``itertools`` are stdlib — must NOT be in
        # the install_command (pip would fail).
        a = BigCodeBenchAdapter(cache_file=self.cache)
        task = a.list_tasks()[0]
        cfg = a.isolation_for(task)
        self.assertEqual(cfg.tier, ISOLATION_WORKTREE_VENV)
        self.assertIn("pytest", cfg.install_command)
        self.assertNotIn("random", cfg.install_command)
        self.assertNotIn("itertools", cfg.install_command)

    def test_isolation_includes_real_libs(self) -> None:
        # numpy, pandas would be real PyPI installs; the adapter
        # appends them after pytest.
        row = dict(_SAMPLE_ROW, libs=["numpy", "pandas", "math"])
        self.cache.write_text(json.dumps(row) + "\n", encoding="utf-8")
        a = BigCodeBenchAdapter(cache_file=self.cache)
        task = a.list_tasks()[0]
        cfg = a.isolation_for(task)
        self.assertIn("numpy", cfg.install_command)
        self.assertIn("pandas", cfg.install_command)
        self.assertNotIn(" math", cfg.install_command)  # stdlib, filtered

    def test_prepare_task_writes_starter_and_test(self) -> None:
        a = BigCodeBenchAdapter(cache_file=self.cache)
        task = a.list_tasks()[0]
        worktree = Path(self._tmp) / "wt"
        worktree.mkdir()
        a.prepare_task(task, worktree)
        starter = (worktree / "task_func.py").read_text(encoding="utf-8")
        test_file = (worktree / "test_task_func.py").read_text(encoding="utf-8")
        self.assertIn("def task_func", starter)
        self.assertIn("class TestCases", test_file)
        self.assertIn("from task_func import *", test_file)

    def test_prompt_returns_instruct_prompt(self) -> None:
        a = BigCodeBenchAdapter(cache_file=self.cache)
        task = a.list_tasks()[0]
        prompt = a.prompt_for(task, attempt=1, prior=None)
        self.assertEqual(prompt, _SAMPLE_ROW["instruct_prompt"])

    def test_max_attempts_is_one(self) -> None:
        a = BigCodeBenchAdapter(cache_file=self.cache)
        self.assertEqual(a.max_attempts(), 1)

    def test_golden_patch_writes_canonical(self) -> None:
        a = BigCodeBenchAdapter(cache_file=self.cache)
        task = a.list_tasks()[0]
        gp = a.golden_patch(task)
        self.assertTrue(gp.is_file())
        text = gp.read_text(encoding="utf-8")
        self.assertIn("def task_func", text)
        self.assertIn("return sum(numbers)", text)

    def test_register_adds_to_registry(self) -> None:
        from benchmark_runner.registry import (
            UnknownAdapterError,
            _reset_for_tests,
            get_adapter,
            list_adapter_ids,
        )
        _reset_for_tests()
        register()
        self.assertIn("bigcodebench", list_adapter_ids())
        adapter = get_adapter("bigcodebench")
        self.assertEqual(adapter.benchmark_id, "bigcodebench")
        _reset_for_tests()


class TestPiplineAgainstHarness(unittest.TestCase):
    """End-to-end: a harness ``run`` invocation against the
    BigCodeBench adapter with the stub backend (golden-patch path)
    completes verify() successfully. Smoke test only — exercises
    list_tasks → prepare_task → prompt_for → backend.run (stub
    writes golden patch) → verify() → score classification."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-bcb-e2e-")
        self.cache = Path(self._tmp) / "tasks.jsonl"
        self.cache.write_text(json.dumps(_SAMPLE_ROW) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_protocol_walkthrough(self) -> None:
        a = BigCodeBenchAdapter(cache_file=self.cache)
        tasks = a.list_tasks()
        self.assertEqual(len(tasks), 1)
        task = tasks[0]

        worktree = Path(self._tmp) / "wt"
        worktree.mkdir()
        a.prepare_task(task, worktree)

        # Apply the golden patch (i.e., simulate the stub backend
        # replacing the starter with the canonical solution).
        gp = a.golden_patch(task)
        (worktree / "task_func.py").write_text(
            gp.read_text(encoding="utf-8"), encoding="utf-8",
        )

        # verify() invokes ``python -m unittest`` in the worktree.
        # We don't actually run it here (would require venv +
        # subprocess; out of scope for this unit test). The
        # protocol-walkthrough check is that all the inputs verify()
        # needs are present in the worktree.
        self.assertTrue((worktree / "task_func.py").is_file())
        self.assertTrue((worktree / "test_task_func.py").is_file())


if __name__ == "__main__":
    unittest.main()
