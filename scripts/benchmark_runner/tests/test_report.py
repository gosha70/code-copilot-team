# tests/test_report.py — Phase 4 report aggregator with calibrated verdicts.
#
# Updated for the v3 architecture: groups are keyed by (backend, model)
# tuples (rendered as "backend:model" or just "backend" when model
# is empty). Provider-routing endpoint is surfaced per group. The
# Phase-1 "WINNER_DEFERRED_NOTE" stub is replaced by the calibrated
# rule from report_winner.py.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark_runner._register import register_all, unregister_all_for_tests
from benchmark_runner.report import render_report
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
            # New v3 group heading format: `<backend>:<model>` or just
            # `<backend>` when model is empty (stub case).
            self.assertIn("`stub`", md)
            self.assertIn("backend=stub", md)
            self.assertIn("hello-world", md)
            self.assertIn("100.0%", md)

    def test_json_carries_schema_version(self) -> None:
        # Pre-push review finding #2: every breaking change to the
        # report JSON shape MUST bump REPORT_SCHEMA_VERSION. The
        # field's presence is required so future consumers can
        # branch on the version rather than guessing from the
        # presence/absence of fields.
        from benchmark_runner.report import REPORT_SCHEMA_VERSION

        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())

        self.assertIn("schema_version", payload)
        self.assertEqual(payload["schema_version"], REPORT_SCHEMA_VERSION)
        # Type discipline: schema_version is a STRING, not int. A bump
        # from "1" to "2" stays string; consumers branching on this
        # value should `==`-compare strings, not int-cast. This pin
        # catches an accidental ``schema_version: 1`` (int) that would
        # later trip strict-type comparisons.
        self.assertIsInstance(payload["schema_version"], str)
        self.assertIsInstance(REPORT_SCHEMA_VERSION, str)
        # v1 → v2 bump (compare driver, 2026-05-13): group key tuple
        # gained a third element (candidate_name); group summary gained
        # a candidate_name field. Backwards-compatible for plain
        # `run` run-dirs (candidate_name="" preserves v1 labels).
        self.assertEqual(REPORT_SCHEMA_VERSION, "2")

    def test_json_schema_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())

        self.assertEqual(payload["run_count"], 1)
        # New schema: top-level "groups" keyed by "<backend>:<model>" or
        # just "<backend>" when model is empty.
        self.assertIn("groups", payload)
        self.assertIn("stub", payload["groups"])
        group = payload["groups"]["stub"]
        self.assertEqual(group["backend_id"], "stub")
        self.assertEqual(group["model"], "")
        self.assertEqual(group["total_attempts"], 1)
        self.assertEqual(group["passed"], 1)
        self.assertEqual(group["pass_rate"], 1.0)
        self.assertIn("hello-world", group["per_task"])
        self.assertEqual(group["per_task"]["hello-world"]["pass_rate"], 1.0)
        # Provider endpoint surfaced per group; stub has no metadata.provider_endpoint
        # so the value is None.
        self.assertIn("provider_endpoints", group)
        self.assertEqual(group["provider_endpoints"], [None])

    def test_verdicts_absent_for_single_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())
        # Only one (backend, model) group → no comparison, no verdicts.
        self.assertIsNone(payload["verdicts"])

    def test_verdicts_present_when_two_groups(self) -> None:
        # Inject a synthetic second-group score.json + run-record.json
        # to exercise the verdict-emission path.
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            existing_score = next(run_dir.rglob("score.json"))
            existing_rr = existing_score.parent / "run-record.json"
            second_attempt = existing_score.parent.with_name("attempt-fake")
            second_attempt.mkdir()
            synth_score = json.loads(existing_score.read_text())
            synth_score["backend_id"] = "synthetic"
            synth_score["run_id"] = "run-001"
            synth_score["attempt"] = 1
            (second_attempt / "score.json").write_text(json.dumps(synth_score))
            # run-record.json carries backend_invocation.model and
            # backend.metadata; preserve the shape from the existing one.
            synth_rr = json.loads(existing_rr.read_text()) if existing_rr.exists() else {}
            synth_rr.setdefault("backend_invocation", {})["model"] = "v1"
            synth_rr.setdefault("backend", {}).setdefault("metadata", {})["provider_endpoint"] = None
            (second_attempt / "run-record.json").write_text(json.dumps(synth_rr))

            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())

        self.assertIsNotNone(payload["verdicts"])
        self.assertIn("pairwise", payload["verdicts"])
        # Two groups -> 1 pairwise comparison.
        self.assertEqual(len(payload["verdicts"]["pairwise"]), 1)
        pair = payload["verdicts"]["pairwise"][0]
        # All four verdict metrics present (F-finding #5: failed_commands
        # and human_interventions are backend-stability signals worth
        # surfacing, not just pass_rate / elapsed_seconds).
        self.assertIn("pass_rate_verdict", pair)
        self.assertIn("elapsed_seconds_verdict", pair)
        self.assertIn("failed_commands_verdict", pair)
        self.assertIn("human_interventions_verdict", pair)
        # Both groups exist in the groups map.
        self.assertIn("stub", payload["groups"])
        self.assertIn("synthetic:v1", payload["groups"])

    def test_groups_keyed_by_backend_and_model(self) -> None:
        # Exercise the (backend, model) tuple keying directly: same
        # backend with two models should produce two groups, not one.
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            existing_score = next(run_dir.rglob("score.json"))
            existing_rr = existing_score.parent / "run-record.json"
            # First, give the existing run a model; then add a second
            # attempt with a different model under the same backend.
            rr0 = json.loads(existing_rr.read_text()) if existing_rr.exists() else {}
            rr0.setdefault("backend_invocation", {})["model"] = "alpha"
            existing_rr.write_text(json.dumps(rr0))

            second = existing_score.parent.with_name("attempt-beta")
            second.mkdir()
            s1 = json.loads(existing_score.read_text())
            s1["run_id"] = "run-002"
            (second / "score.json").write_text(json.dumps(s1))
            rr1 = json.loads(existing_rr.read_text())
            rr1["backend_invocation"]["model"] = "beta"
            (second / "run-record.json").write_text(json.dumps(rr1))

            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())

        # Two distinct groups despite the same backend.
        self.assertIn("stub:alpha", payload["groups"])
        self.assertIn("stub:beta", payload["groups"])

    def test_provider_endpoint_surfaces_into_group(self) -> None:
        # If run-record.backend.metadata.provider_endpoint is set,
        # the group's provider_endpoints list contains it.
        with tempfile.TemporaryDirectory() as td:
            run_dir = _seed_run_dir(Path(td))
            existing_rr = next(run_dir.rglob("run-record.json"))
            rr = json.loads(existing_rr.read_text())
            rr.setdefault("backend", {}).setdefault("metadata", {})[
                "provider_endpoint"
            ] = "http://localhost:8000"
            existing_rr.write_text(json.dumps(rr))

            render_report(run_dir)
            payload = json.loads((run_dir / "report.json").read_text())

        group = payload["groups"]["stub"]
        self.assertIn("http://localhost:8000", group["provider_endpoints"])


if __name__ == "__main__":
    unittest.main()
