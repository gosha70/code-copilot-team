# tests/test_report_judge.py — judge + HTML/CSV/SVG report extensions.
#
# Covers issue #50 (rich reports) + issue #51 (calibrated-judge
# winner-extension). Pure-fixture: stages a tmpdir run-dir with
# score.json / run-record.json / judge.json per attempt + an
# optional calibrated-dimensions.json. Asserts:
#
# - Additivity invariant: a run-dir with no judge.json produces a
#   report.md/json byte-identical (modulo timestamps; none in this
#   path) to the pre-#50 baseline.
# - Judge enrichment activates when judge.json is present.
# - Calibrated dimensions get marked in summary.judge.
# - Deterministic-first ordering enforced: calibrated-judge
#   samples only count for tasks both candidates passed.
# - HTML / CSV / SVG emit when flags set.

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from benchmark_runner.report import render_report


# ── Fixture helpers ───────────────────────────────────────────────────


def _write_attempt(
    base: Path,
    *,
    task_id: str,
    model: str,
    result: str = "pass",
    elapsed: float = 1.0,
    judge_ratings: dict[str, int] | None = None,
    backend_id: str = "claude-code",
) -> Path:
    """Stage one attempt directory with score.json + run-record.json + optional judge.json."""
    base.mkdir(parents=True, exist_ok=True)
    score = {
        "schema_version": "1.0",
        "benchmark_id": "test-bench",
        "task_id": task_id,
        "backend_id": backend_id,
        "run_id": "run-001",
        "attempt": 1,
        "scores": {"tests_passed": result == "pass", "human_interventions": 0},
        "derived": {"elapsed_seconds": elapsed, "files_changed": 1, "failed_commands": 0},
        "result": result,
    }
    (base / "score.json").write_text(json.dumps(score, indent=2) + "\n", encoding="utf-8")
    run_record = {
        "schema_version": "1.0",
        "benchmark_id": "test-bench",
        "task_id": task_id,
        "backend_id": backend_id,
        "backend_invocation": {"model": model},
        "backend": {"metadata": {}},
    }
    (base / "run-record.json").write_text(json.dumps(run_record) + "\n", encoding="utf-8")
    if judge_ratings:
        judge_doc = {
            "schema_version": "1.0",
            "judge_id": "claude-code-judge",
            "judge_model": "sonnet",
            "judge_backend_id": "claude-code",
            "rubric_name": "default-v1",
            "rubric_dimensions": list(judge_ratings.keys()),
            "ratings": {
                d: {"rating": r, "explanation": "x", "prompt_sha256": "y"}
                for d, r in judge_ratings.items()
            },
            "judge_invocation": {
                "model": "sonnet", "temperature": None, "seed": None,
                "temperature_control": "unsupported", "seed_control": "unsupported",
                "provider_endpoint_present": False,
            },
        }
        (base / "judge.json").write_text(json.dumps(judge_doc) + "\n", encoding="utf-8")
    return base


# ── Additivity invariant ──────────────────────────────────────────────


class TestAdditivityInvariant(unittest.TestCase):
    """A run-dir WITHOUT judge.json must produce report.md / report.json
    with NO judge fields. The pre-#50 schema is preserved exactly."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-report-additivity-")
        self.run_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_summary_has_no_judge_key_without_judge_files(self) -> None:
        _write_attempt(self.run_dir / "task-a" / "attempt-01-run-001",
                       task_id="t/a", model="m1")
        _write_attempt(self.run_dir / "task-a" / "attempt-02-run-001",
                       task_id="t/a", model="m1")
        render_report(self.run_dir)
        doc = json.loads((self.run_dir / "report.json").read_text(encoding="utf-8"))
        self.assertNotIn("judge", doc)

    def test_markdown_has_no_judge_section_without_judge_files(self) -> None:
        _write_attempt(self.run_dir / "task-a" / "attempt-01-run-001",
                       task_id="t/a", model="m1")
        render_report(self.run_dir)
        md = (self.run_dir / "report.md").read_text(encoding="utf-8")
        self.assertNotIn("Judge ratings", md)
        self.assertNotIn("calibrated", md.lower())

    def test_html_csv_not_emitted_when_flags_false(self) -> None:
        _write_attempt(self.run_dir / "task-a" / "attempt-01-run-001",
                       task_id="t/a", model="m1")
        render_report(self.run_dir)
        self.assertFalse((self.run_dir / "report.html").exists())
        self.assertFalse((self.run_dir / "report-by-model.csv").exists())
        self.assertFalse((self.run_dir / "chart-pass-rate.svg").exists())


# ── Judge enrichment ─────────────────────────────────────────────────


class TestJudgeEnrichment(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-report-judge-")
        self.run_dir = Path(self._tmp)
        # Two candidates × two tasks × judge ratings on each.
        for model in ("m1", "m2"):
            for task in ("t/x", "t/y"):
                slug = task.replace("/", "-")
                _write_attempt(
                    self.run_dir / f"{model}-runs" / slug / "attempt-01-run-001",
                    task_id=task, model=model,
                    judge_ratings={
                        "idiomaticity": 4 if model == "m1" else 3,
                        "error_handling": 3 if model == "m1" else 4,
                    },
                )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_judge_block_appears_in_json_when_files_present(self) -> None:
        render_report(self.run_dir)
        doc = json.loads((self.run_dir / "report.json").read_text(encoding="utf-8"))
        self.assertIn("judge", doc)
        self.assertEqual(
            doc["judge"]["dimensions"],
            ["error_handling", "idiomaticity"],
        )

    def test_judge_block_appears_in_markdown(self) -> None:
        render_report(self.run_dir)
        md = (self.run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("Judge ratings", md)
        self.assertIn("idiomaticity", md)

    def test_calibrated_dimensions_marked_when_path_provided(self) -> None:
        # Stage a calibrated-dimensions.json.
        cal = self.run_dir / "calibrated.json"
        cal.write_text(json.dumps({
            "schema_version": "1.0",
            "name": "test",
            "threshold": 0.6,
            "calibrated": [{"dimension": "idiomaticity", "spearman": 0.8, "n_paired": 4}],
            "uncalibrated": [{"dimension": "error_handling", "spearman": 0.3, "n_paired": 4}],
            "no_signal": [],
        }), encoding="utf-8")
        render_report(self.run_dir, calibrated_dimensions_path=cal)
        doc = json.loads((self.run_dir / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["judge"]["calibrated_dimensions"], ["idiomaticity"])
        self.assertEqual(doc["judge"]["threshold"], 0.6)
        # Per-group flag matches.
        for label, g in doc["judge"]["groups"].items():
            self.assertTrue(g["per_dimension"]["idiomaticity"]["calibrated"])
            self.assertFalse(g["per_dimension"]["error_handling"]["calibrated"])


# ── Deterministic-first ordering (#51 AC8) ────────────────────────────


class TestDeterministicFirstOrdering(unittest.TestCase):
    """A calibrated-judge winner can only declare based on tasks BOTH
    candidates passed. Non-passing attempts are excluded from the
    Spearman-driven verdict samples."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-report-det-")
        self.run_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_failing_attempts_excluded_from_calibrated_verdict_samples(self) -> None:
        # m1: passes t/a (judge 5), fails t/b (judge 5 — but failing).
        # m2: passes t/a (judge 1), fails t/b (judge 1 — but failing).
        # Without the deterministic-first filter, m1 wins on both
        # tasks (judge ratings strictly higher). With the filter,
        # only t/a contributes; n=1 per side; declare_winner returns
        # 'directional' (insufficient samples). The test asserts the
        # filtered behavior.
        _write_attempt(self.run_dir / "m1" / "t-a" / "attempt-01-run-001",
                       task_id="t/a", model="m1", result="pass",
                       judge_ratings={"idiomaticity": 5})
        _write_attempt(self.run_dir / "m1" / "t-b" / "attempt-01-run-001",
                       task_id="t/b", model="m1", result="fail",
                       judge_ratings={"idiomaticity": 5})
        _write_attempt(self.run_dir / "m2" / "t-a" / "attempt-01-run-001",
                       task_id="t/a", model="m2", result="pass",
                       judge_ratings={"idiomaticity": 1})
        _write_attempt(self.run_dir / "m2" / "t-b" / "attempt-01-run-001",
                       task_id="t/b", model="m2", result="fail",
                       judge_ratings={"idiomaticity": 1})
        cal = self.run_dir / "cal.json"
        cal.write_text(json.dumps({
            "schema_version": "1.0", "threshold": 0.6,
            "calibrated": [{"dimension": "idiomaticity"}],
            "uncalibrated": [], "no_signal": [],
        }), encoding="utf-8")
        render_report(self.run_dir, calibrated_dimensions_path=cal)
        doc = json.loads((self.run_dir / "report.json").read_text(encoding="utf-8"))
        # n=1 per side after the deterministic-first filter →
        # 'directional' (min_samples_for_winner default is 2).
        pair = doc["judge"]["pairwise"][0]
        self.assertEqual(
            pair["calibrated_judge_verdicts"]["idiomaticity"],
            "directional",
        )


# ── HTML / CSV / SVG emission ─────────────────────────────────────────


class TestRichOutputs(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-report-rich-")
        self.run_dir = Path(self._tmp)
        for model in ("m1", "m2"):
            for task in ("t/x", "t/y"):
                slug = task.replace("/", "-")
                _write_attempt(
                    self.run_dir / model / slug / "attempt-01-run-001",
                    task_id=task, model=model,
                    judge_ratings={"idiomaticity": 4, "error_handling": 3},
                )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_html_emitted_when_flag_set(self) -> None:
        render_report(self.run_dir, html=True)
        html = (self.run_dir / "report.html").read_text(encoding="utf-8")
        self.assertIn("<!doctype html>", html)
        self.assertIn("Benchmark report", html)
        # Deterministic block before judge block (AC5).
        self.assertLess(
            html.index("Deterministic results"),
            html.index("Judge ratings"),
        )
        # No JS — opens in browser with JS disabled.
        self.assertNotIn("<script", html.lower())

    def test_svg_charts_emitted_when_html_set(self) -> None:
        render_report(self.run_dir, html=True)
        self.assertTrue((self.run_dir / "chart-pass-rate.svg").exists())
        self.assertTrue((self.run_dir / "chart-judge-histogram.svg").exists())
        self.assertTrue((self.run_dir / "chart-verdict-forest.svg").exists())
        # SVG starts with the expected XML.
        svg = (self.run_dir / "chart-pass-rate.svg").read_text(encoding="utf-8")
        self.assertIn("<svg ", svg)
        self.assertNotIn("<script", svg.lower())

    def test_csv_emitted_when_flag_set(self) -> None:
        render_report(self.run_dir, csv=True)
        by_model = (self.run_dir / "report-by-model.csv").read_text(encoding="utf-8")
        per_task = (self.run_dir / "report-per-task.csv").read_text(encoding="utf-8")
        # Headers.
        self.assertTrue(by_model.startswith("label,backend_id,model,total_attempts"))
        self.assertTrue(per_task.startswith("label,task_id,attempts,passed"))
        # Each (model) × task = row.
        self.assertEqual(len(by_model.strip().splitlines()), 3)  # header + 2 groups
        self.assertEqual(len(per_task.strip().splitlines()), 5)  # header + 2 groups × 2 tasks

    def test_no_dollar_signs_in_any_emitted_artifact(self) -> None:
        # AC9 — no dollar-cost figures introduced anywhere.
        render_report(self.run_dir, html=True, csv=True)
        for fname in ("report.md", "report.json", "report.html",
                      "report-by-model.csv", "report-per-task.csv"):
            text = (self.run_dir / fname).read_text(encoding="utf-8")
            self.assertNotIn("$", text, msg=f"dollar sign found in {fname}")


# ── Reviewer-flagged regressions (post PR #60) ────────────────────────


class TestD6TerminalStateSurfaced(unittest.TestCase):
    """Reviewer-flagged P1: when ALL dimensions are uncalibrated
    (the spec.md D6 terminal state), the report MUST surface the
    'Zero calibrated dimensions' paragraph. The pre-fix code only
    emitted the paragraph inside a ``judge['pairwise']`` branch,
    which was empty when no dimension calibrated — making the D6
    message unreachable in practice.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-report-d6-")
        self.run_dir = Path(self._tmp)
        for model in ("m1", "m2"):
            _write_attempt(
                self.run_dir / model / "t" / "attempt-01-run-001",
                task_id="t/x", model=model,
                judge_ratings={"idiomaticity": 3},
            )

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _calibrated_dims_all_uncalibrated(self) -> Path:
        """Stage a calibrated-dimensions.json where every dimension
        is uncalibrated (the D6 terminal state)."""
        path = self.run_dir / "cal.json"
        path.write_text(json.dumps({
            "schema_version": "1.0",
            "threshold": 0.6,
            "calibrated": [],
            "uncalibrated": [{"dimension": "idiomaticity", "spearman": 0.3}],
            "no_signal": [],
        }), encoding="utf-8")
        return path

    def test_markdown_emits_d6_paragraph(self) -> None:
        render_report(
            self.run_dir,
            calibrated_dimensions_path=self._calibrated_dims_all_uncalibrated(),
        )
        md = (self.run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("Zero calibrated dimensions", md)
        self.assertIn("D6", md)

    def test_html_emits_d6_paragraph(self) -> None:
        render_report(
            self.run_dir,
            html=True,
            calibrated_dimensions_path=self._calibrated_dims_all_uncalibrated(),
        )
        html = (self.run_dir / "report.html").read_text(encoding="utf-8")
        self.assertIn("Zero calibrated dimensions", html)
        self.assertIn("D6", html)


class TestOutOfBandJudgeRatingsRejected(unittest.TestCase):
    """Reviewer-flagged P2: the validator (validate.py) rejects judge
    ratings outside 1..5, but the report path previously accepted any
    non-bool int. A stale/hand-edited judge.json with rating 6 fed
    into group means + verdict declarations. Same 1..5 guard now
    applies in report.py."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-report-oob-")
        self.run_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_out_of_band_rating_does_not_enter_group_mean(self) -> None:
        # m1 has rating=6 (out-of-band), m2 has rating=3 (in-band).
        # Pre-fix: m1's mean was 6.0; post-fix: m1's mean is None
        # (no valid samples).
        _write_attempt(
            self.run_dir / "m1" / "t" / "attempt-01-run-001",
            task_id="t/x", model="m1",
            judge_ratings={"idiomaticity": 6},
        )
        _write_attempt(
            self.run_dir / "m2" / "t" / "attempt-01-run-001",
            task_id="t/x", model="m2",
            judge_ratings={"idiomaticity": 3},
        )
        render_report(self.run_dir)
        doc = json.loads((self.run_dir / "report.json").read_text(encoding="utf-8"))
        # m1's mean MUST be None (the out-of-band 6 was filtered out
        # — no in-band samples remain).
        m1_group = doc["judge"]["groups"]["claude-code:m1"]
        self.assertIsNone(m1_group["per_dimension"]["idiomaticity"]["mean"])
        self.assertEqual(m1_group["per_dimension"]["idiomaticity"]["n"], 0)
        # m2's mean is 3.0 (the in-band sample is kept).
        m2_group = doc["judge"]["groups"]["claude-code:m2"]
        self.assertEqual(m2_group["per_dimension"]["idiomaticity"]["mean"], 3.0)

    def test_out_of_band_rating_does_not_swing_calibrated_verdict(self) -> None:
        # m1 has rating=6 on every passing attempt; m2 has rating=3.
        # Pre-fix: m1 wins (6.0 > 3.0). Post-fix: m1's samples are
        # filtered out → insufficient samples → directional.
        for i in range(3):
            _write_attempt(
                self.run_dir / "m1" / f"t-{i}" / "attempt-01-run-001",
                task_id=f"t/{i}", model="m1",
                judge_ratings={"idiomaticity": 6},
            )
            _write_attempt(
                self.run_dir / "m2" / f"t-{i}" / "attempt-01-run-001",
                task_id=f"t/{i}", model="m2",
                judge_ratings={"idiomaticity": 3},
            )
        cal = self.run_dir / "cal.json"
        cal.write_text(json.dumps({
            "schema_version": "1.0", "threshold": 0.6,
            "calibrated": [{"dimension": "idiomaticity"}],
            "uncalibrated": [], "no_signal": [],
        }), encoding="utf-8")
        render_report(self.run_dir, calibrated_dimensions_path=cal)
        doc = json.loads((self.run_dir / "report.json").read_text(encoding="utf-8"))
        verdict = doc["judge"]["pairwise"][0]["calibrated_judge_verdicts"]["idiomaticity"]
        # Pre-fix: would have been "A" (m1 wins from out-of-band 6s).
        # Post-fix: "directional" (m1's samples filtered, n=0 < 2).
        self.assertEqual(verdict, "directional")


if __name__ == "__main__":
    unittest.main()
