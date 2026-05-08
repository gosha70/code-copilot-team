# tests/test_stub_backend.py — stub backend conformance.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_runner._register import unregister_all_for_tests
from benchmark_runner.backends.stub import BACKEND_FAMILY, StubBackend, factory
from benchmark_runner.contracts import (
    Backend,
    RunContext,
)


class TestStubBackend(unittest.TestCase):
    def setUp(self) -> None:
        unregister_all_for_tests()
        # The backend resolves its task via the registered adapter, so
        # we register the stub adapter explicitly here.
        from benchmarks.adapters.stub.adapter import register as register_stub_adapter
        register_stub_adapter()
        self.backend = StubBackend(model="")

    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(self.backend, Backend)

    def test_backend_id_is_family(self) -> None:
        self.assertEqual(self.backend.backend_id, BACKEND_FAMILY)

    def test_factory_returns_backend_instance(self) -> None:
        b = factory("any-model")
        self.assertIsInstance(b, StubBackend)
        self.assertEqual(b._model, "any-model")  # noqa: SLF001 (test-only access)

    def test_run_copies_golden_into_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td) / "wt"
            wt.mkdir()
            ctx = RunContext(
                benchmark_id="stub",
                task_id="hello-world",
                backend_id=BACKEND_FAMILY,
                run_id="run-001",
                attempt=1,
                worktree=wt,
                model="",
            )
            result = self.backend.run("ignored prompt", ctx)
            self.assertTrue((wt / "hello.txt").is_file())
            self.assertEqual(
                (wt / "hello.txt").read_text(encoding="utf-8"),
                "Hello, World!\n",
            )
        # Token counts: zero, not None — stub deliberately fabricates 0
        # to exercise the null-vs-zero path through the runner.
        self.assertEqual(result.tokens_input, 0)
        self.assertEqual(result.tokens_output, 0)
        # Cache fields still null (stub doesn't model cache).
        self.assertIsNone(result.cache_read_tokens)
        self.assertIsNone(result.cache_write_tokens)

    def test_run_unknown_task_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td) / "wt"
            wt.mkdir()
            ctx = RunContext(
                benchmark_id="stub",
                task_id="not-real",
                backend_id=BACKEND_FAMILY,
                run_id="run-001",
                attempt=1,
                worktree=wt,
                model="",
            )
            with self.assertRaises(KeyError):
                self.backend.run("p", ctx)


if __name__ == "__main__":
    unittest.main()
