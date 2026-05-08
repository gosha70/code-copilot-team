# tests/test_report.py — Phase 1 report aggregator.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_runner._register import register_all, unregister_all_for_tests
from benchmark_runner.report import (
    WINNER_DEFERRED_NOTE,
    render_report,
)
from benchmark_runner.run import run_benchmark


def _seed_run_dir(td: Path) -> Path:
    """Helper: produce a real run-dir by running stub × stub once."""
    return run_benchmark("stub", "stub", runs=1, runs_root=td)


class TestRenderReport(unittest.TestCase):
    def setUp(self) -> None:
        unregister_all_for_tests()
        register_all()

    def test_missing_run_dir_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            render_report(Path("/nonexistent/path"))

    def test_empty_run_dir_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                render_report(Path(td))

    def test_renders_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            md_path = render_report(run_dir)

            self.assertTrue(md_path.exists())
            self.assertEqual(md_path.name, "report.md")
            json_path = md_path.with_suffix(".json")
            self.assertTrue(json_path.exists())

            md = md_path.read_text(encoding="utf-8")
            self.assertIn("Backend `stub`", md)
            self.assertIn("hello-world", md)
            self.assertIn("100.0%", md)

    def test_json_schema_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())

        self.assertEqual(payload["run_count"], 1)
        self.assertIn("stub", payload["backends"])
        backend = payload["backends"]["stub"]
        self.assertEqual(backend["total_attempts"], 1)
        self.assertEqual(backend["passed"], 1)
        self.assertEqual(backend["pass_rate"], 1.0)
        self.assertIn("hello-world", backend["per_task"])
        self.assertEqual(backend["per_task"]["hello-world"]["pass_rate"], 1.0)

    def test_winner_verdict_absent_for_single_backend(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())
        # Only one backend in the run-dir → no comparison, no verdict.
        self.assertIsNone(payload["winner_verdict"])

    def test_winner_verdict_deferred_when_two_backends(self) -> None:
        # Inject a synthetic second-backend score.json into a real run-dir.
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            # Find the existing attempt dir + score.json.
            existing_score = next(run_dir.rglob("score.json"))
            second_attempt = existing_score.parent.with_name("attempt-fake")
            second_attempt.mkdir()
            synthetic = json.loads(existing_score.read_text())
            synthetic["backend_id"] = "synthetic"
            synthetic["run_id"] = "run-001"
            synthetic["attempt"] = 1
            (second_attempt / "score.json").write_text(json.dumps(synthetic))

            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())

        self.assertEqual(payload["winner_verdict"], WINNER_DEFERRED_NOTE)
        self.assertIn("stub", payload["backends"])
        self.assertIn("synthetic", payload["backends"])


if __name__ == "__main__":
    unittest.main()
