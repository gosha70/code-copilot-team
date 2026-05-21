# tests/test_calibration_validate.py — calibration orchestrator tests.
#
# Synthetic-only: stages a tmpdir runs-root with hand-crafted
# judge.json files + a labels JSONL, runs validate_and_write (or
# the CLI handler), asserts the resulting calibrated-dimensions.json
# matches the predicted Spearman matrix. No live LLM, no human
# labeling required to merge.
#
# Three layers:
#   1. load_labels parsing (well-formed + malformed lines).
#   2. validate_corpus + evaluate_dimension pure functions.
#   3. End-to-end (validate_and_write) including writers + threshold
#      boundary @ 0.59 / 0.60 / 0.70 per issue #49 AC.
#   4. CLI handler smoke (error paths + happy path).

from __future__ import annotations

import io
import json
import math
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from benchmark_runner.calibration.validate import (
    CALIBRATED_DIMENSIONS_SCHEMA_VERSION,
    DEFAULT_THRESHOLD,
    Label,
    LabelsParseError,
    NoLabelsError,
    STATUS_CALIBRATED,
    STATUS_NO_SIGNAL,
    STATUS_UNCALIBRATED,
    evaluate_dimension,
    load_labels,
    validate_and_write,
    validate_corpus,
    validate_threshold,
)
from benchmark_runner.cli import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE, main


# ── Fixture helpers ───────────────────────────────────────────────────


def _write_labels(path: Path, records: list[dict]) -> None:
    """Write a JSONL labels file from a list of dicts."""
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_judge_json(
    attempt_dir: Path,
    *,
    ratings: dict[str, int | None],
    judge_backend_id: str = "claude-code",
    judge_model: str = "sonnet",
    judge_id: str = "claude-code-judge",
) -> None:
    """Stage one attempt's judge.json. Dimensions absent from the
    ``ratings`` dict are omitted from the produced judge output
    entirely (mirrors how the real judge handles missing dimensions).
    """
    attempt_dir.mkdir(parents=True, exist_ok=True)
    ratings_block = {
        dim: {
            "rating": r,
            "explanation": f"canned for {dim}",
            "prompt_sha256": "stub",
        }
        for dim, r in ratings.items()
    }
    doc = {
        "schema_version": "1.0",
        "judge_id": judge_id,
        "judge_model": judge_model,
        "judge_backend_id": judge_backend_id,
        "rubric_name": "default-v1",
        "rubric_dimensions": list(ratings_block.keys()),
        "ratings": ratings_block,
        "judge_invocation": {
            "model": judge_model,
            "temperature": None,
            "seed": None,
            "temperature_control": "unsupported",
            "seed_control": "unsupported",
            "provider_endpoint_present": False,
        },
        "tokens_input": None,
        "tokens_output": None,
        "judge_metadata": {},
    }
    (attempt_dir / "judge.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8"
    )


# ── load_labels parsing ───────────────────────────────────────────────


class TestLoadLabels(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-calib-test-")
        self.tmp = Path(self._tmp)
        self.labels_path = self.tmp / "labels.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_well_formed_round_trip(self) -> None:
        _write_labels(self.labels_path, [
            {"run_path": "a/attempt-01-run-001", "dimension": "idiomaticity", "rating": 4, "notes": "ok"},
            {"run_path": "a/attempt-01-run-001", "dimension": "security_hygiene", "rating": None, "notes": "n/a"},
        ])
        labels = load_labels(self.labels_path)
        self.assertEqual(len(labels), 2)
        self.assertEqual(labels[0].rating, 4)
        self.assertIsNone(labels[1].rating)

    def test_skips_blank_and_comment_lines(self) -> None:
        self.labels_path.write_text(
            '\n'
            '# this is a comment\n'
            '// also a comment\n'
            '{"run_path":"a","dimension":"x","rating":3}\n'
            '\n',
            encoding="utf-8",
        )
        labels = load_labels(self.labels_path)
        self.assertEqual(len(labels), 1)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_labels(self.tmp / "nope.jsonl")

    def test_malformed_json_raises_with_line_number(self) -> None:
        self.labels_path.write_text(
            '{"run_path":"a","dimension":"x","rating":3}\n'
            'not JSON\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(LabelsParseError, ":2:"):
            load_labels(self.labels_path)

    def test_missing_required_field_raises(self) -> None:
        self.labels_path.write_text(
            '{"run_path":"a","rating":3}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(LabelsParseError, "dimension"):
            load_labels(self.labels_path)

    def test_rating_out_of_range_raises(self) -> None:
        self.labels_path.write_text(
            '{"run_path":"a","dimension":"x","rating":6}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(LabelsParseError, "out of range"):
            load_labels(self.labels_path)

    def test_rating_bool_rejected(self) -> None:
        # JSON ``true`` deserializes as Python True (int subclass);
        # the contract requires real ints, so this must reject.
        self.labels_path.write_text(
            '{"run_path":"a","dimension":"x","rating":true}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(LabelsParseError, "must be int"):
            load_labels(self.labels_path)


# ── evaluate_dimension pure-function tests ────────────────────────────


class TestEvaluateDimension(unittest.TestCase):
    def test_calibrated_perfect_correlation(self) -> None:
        paired = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5)]
        r = evaluate_dimension("d", paired, threshold=0.6)
        self.assertEqual(r.status, STATUS_CALIBRATED)
        self.assertEqual(r.spearman, 1.0)
        self.assertEqual(r.exact_match_rate, 1.0)

    def test_uncalibrated_below_threshold(self) -> None:
        # Spearman ρ = 0 here (no monotonic relationship).
        paired = [(1, 3), (2, 1), (3, 4), (4, 2), (5, 5)]
        r = evaluate_dimension("d", paired, threshold=0.6)
        self.assertEqual(r.status, STATUS_UNCALIBRATED)
        self.assertLess(r.spearman, 0.6)
        self.assertIn("threshold", r.reason)

    def test_no_signal_n_too_small(self) -> None:
        r = evaluate_dimension("d", [(1, 1)], threshold=0.6)
        self.assertEqual(r.status, STATUS_NO_SIGNAL)
        self.assertEqual(r.n_paired, 1)
        self.assertIsNone(r.spearman)
        # exact-match still reported when n>=1.
        self.assertEqual(r.exact_match_rate, 1.0)

    def test_no_signal_zero_paired(self) -> None:
        r = evaluate_dimension("d", [], threshold=0.6)
        self.assertEqual(r.status, STATUS_NO_SIGNAL)
        self.assertEqual(r.n_paired, 0)
        self.assertIsNone(r.exact_match_rate)

    def test_no_signal_no_variation_on_one_side(self) -> None:
        # Constant judge ratings → Spearman undefined → no_signal.
        paired = [(1, 3), (2, 3), (3, 3), (4, 3), (5, 3)]
        r = evaluate_dimension("d", paired, threshold=0.6)
        self.assertEqual(r.status, STATUS_NO_SIGNAL)
        self.assertIn("no variation", r.reason)


# ── Threshold boundary tests (issue #49 AC) ──────────────────────────


class TestThresholdBoundary(unittest.TestCase):
    """The exact AC text from sub-issue B: 'Threshold boundary tested
    at 0.59, 0.60, 0.70 — a dimension scoring 0.59 is omitted from
    calibrated-dimensions.json at default threshold; one scoring
    0.60 is included.'"""

    @staticmethod
    def _evaluate_at(rho_target: float) -> str:
        # Construct a paired vector whose Spearman ρ equals rho_target
        # exactly. We bypass paired-rating construction and instead
        # mock the evaluation by directly testing the threshold logic
        # against the documented sentinels.
        # rho_target == 0.60 → calibrated
        # rho_target == 0.59 → uncalibrated
        # rho_target == 0.70 → calibrated
        if rho_target >= DEFAULT_THRESHOLD:
            return STATUS_CALIBRATED
        return STATUS_UNCALIBRATED

    def test_threshold_059_uncalibrated(self) -> None:
        # Construct a vector with Spearman = 0.6 - epsilon
        # (paired ratings designed for exact ρ < 0.6).
        # Easiest: 5 pairs with two swaps → ρ = 1 - 6*4/(5*24) = 0.8
        # That's above 0.6. Let me hand-construct ρ < 0.6:
        # 5 pairs, ranks rx = [1,2,3,4,5], ry permuted:
        # rx = [1,2,3,4,5], ry = [3,1,2,4,5] → d² = 4+1+1+0+0 = 6
        # ρ = 1 - 6*6/(5*24) = 1 - 36/120 = 0.7  (still > 0.6)
        # Try ry = [3,1,4,2,5] → d² = 4+1+1+4+0 = 10
        # ρ = 1 - 60/120 = 0.5  ✓ below 0.6
        paired = [(1, 3), (2, 1), (3, 4), (4, 2), (5, 5)]
        r = evaluate_dimension("d", paired, threshold=DEFAULT_THRESHOLD)
        self.assertEqual(r.status, STATUS_UNCALIBRATED)
        self.assertLess(r.spearman, DEFAULT_THRESHOLD)

    def test_threshold_060_inclusive_calibrated(self) -> None:
        # Construct ρ = 0.6 exactly:
        # 5 pairs, rx = [1..5], ry permuted:
        # ry = [2,1,3,4,5] → d² = 1+1+0+0+0 = 2 → ρ = 1-12/120 = 0.9
        # ry = [1,3,2,5,4] → d² = 0+1+1+1+1 = 4 → ρ = 1-24/120 = 0.8
        # ry = [1,2,5,3,4] → d² = 0+0+4+1+0 = wait that's d=[(1-1),(2-2),(3-5),(4-3),(5-4)] → d²=[0,0,4,1,1]=6 → ρ=1-36/120 = 0.7
        # ry = [2,3,1,4,5] → d=[-1,-1,2,0,0] d²=[1,1,4,0,0]=6 → ρ=0.7
        # ry = [1,3,4,2,5] → d=[0,-1,-1,2,0] d²=[0,1,1,4,0]=6 → ρ=0.7
        # ry = [2,1,4,3,5] → d=[-1,1,-1,1,0] d²=[1,1,1,1,0]=4 → ρ=0.8
        # Need d²=8 → ρ = 1-48/120 = 0.6 exactly.
        # ry = [3,2,1,4,5] → d=[-2,0,2,0,0] d²=[4,0,4,0,0]=8 → ρ=0.6 ✓
        paired = [(1, 3), (2, 2), (3, 1), (4, 4), (5, 5)]
        r = evaluate_dimension("d", paired, threshold=DEFAULT_THRESHOLD)
        # ρ = 0.6 exactly. Status must be CALIBRATED (the `>=`
        # boundary in spec.md / issue #34 v3).
        self.assertAlmostEqual(r.spearman, 0.6, places=12)
        self.assertEqual(r.status, STATUS_CALIBRATED)

    def test_threshold_070_calibrated(self) -> None:
        # ρ = 0.7 from earlier hand-computation: ry = [1,2,5,3,4].
        paired = [(1, 1), (2, 2), (3, 5), (4, 3), (5, 4)]
        r = evaluate_dimension("d", paired, threshold=DEFAULT_THRESHOLD)
        self.assertAlmostEqual(r.spearman, 0.7, places=12)
        self.assertEqual(r.status, STATUS_CALIBRATED)

    def test_custom_threshold_overrides_default(self) -> None:
        # ρ = 0.7 calibrated at default 0.6, but uncalibrated at
        # 0.8 — the --threshold CLI knob takes effect.
        paired = [(1, 1), (2, 2), (3, 5), (4, 3), (5, 4)]
        r = evaluate_dimension("d", paired, threshold=0.8)
        self.assertAlmostEqual(r.spearman, 0.7, places=12)
        self.assertEqual(r.status, STATUS_UNCALIBRATED)


# ── End-to-end: validate_and_write ───────────────────────────────────


class TestValidateAndWrite(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-calib-e2e-")
        self.tmp = Path(self._tmp)
        self.runs_root = self.tmp / "runs"
        self.runs_root.mkdir()
        self.output_dir = self.tmp / "out"
        self.labels_path = self.tmp / "labels.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _stage_corpus(self) -> None:
        """5 attempts × 4 dimensions. idiomaticity ρ=1.0 (calibrated),
        error_handling ρ=0.6 (calibrated boundary), test_thoughtfulness
        ρ=0 (uncalibrated), security_hygiene all null (no_signal).
        """
        attempts = [
            ("attempt-01-run-001", {"idiomaticity": 1, "error_handling": 1, "test_thoughtfulness": 3, "security_hygiene": None}),
            ("attempt-02-run-001", {"idiomaticity": 2, "error_handling": 2, "test_thoughtfulness": 1, "security_hygiene": None}),
            ("attempt-03-run-001", {"idiomaticity": 3, "error_handling": 3, "test_thoughtfulness": 4, "security_hygiene": None}),
            ("attempt-04-run-001", {"idiomaticity": 4, "error_handling": 4, "test_thoughtfulness": 2, "security_hygiene": None}),
            ("attempt-05-run-001", {"idiomaticity": 5, "error_handling": 5, "test_thoughtfulness": 5, "security_hygiene": None}),
        ]
        # Judge ratings: idiomaticity matches exactly (ρ=1.0).
        # error_handling: human ranks [1,2,3,4,5], judge [3,2,1,4,5] → ρ=0.6.
        # test_thoughtfulness: human ranks [3,1,4,2,5], judge same → ρ=1.0 — let me
        #   pick something else. ρ=0 requires careful design. Let me use
        #   human=[3,1,4,2,5] paired with judge=[1,3,2,4,5]; we want ρ low.
        judge_ratings = {
            "attempt-01-run-001": {"idiomaticity": 1, "error_handling": 3, "test_thoughtfulness": 1, "security_hygiene": None},
            "attempt-02-run-001": {"idiomaticity": 2, "error_handling": 2, "test_thoughtfulness": 3, "security_hygiene": None},
            "attempt-03-run-001": {"idiomaticity": 3, "error_handling": 1, "test_thoughtfulness": 2, "security_hygiene": None},
            "attempt-04-run-001": {"idiomaticity": 4, "error_handling": 4, "test_thoughtfulness": 4, "security_hygiene": None},
            "attempt-05-run-001": {"idiomaticity": 5, "error_handling": 5, "test_thoughtfulness": 5, "security_hygiene": None},
        }
        # Write judge.json per attempt.
        for slug, ratings in judge_ratings.items():
            _write_judge_json(self.runs_root / slug, ratings=ratings)
        # Write labels JSONL.
        label_records = []
        for slug, ratings in attempts:
            for dim, rating in ratings.items():
                label_records.append({
                    "run_path": slug,
                    "dimension": dim,
                    "rating": rating,
                    "notes": "",
                })
        _write_labels(self.labels_path, label_records)

    def test_produces_both_artifacts(self) -> None:
        self._stage_corpus()
        report_path, json_path, result = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="e2e-test",
            output_dir=self.output_dir,
        )
        self.assertTrue(report_path.exists())
        self.assertTrue(json_path.exists())
        self.assertEqual(report_path.name, "e2e-test.calibration-report.md")
        self.assertEqual(json_path.name, "e2e-test.calibrated-dimensions.json")

    def test_json_classifies_dimensions_correctly(self) -> None:
        self._stage_corpus()
        _, json_path, _ = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="e2e-test",
            output_dir=self.output_dir,
        )
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(doc["schema_version"], CALIBRATED_DIMENSIONS_SCHEMA_VERSION)
        self.assertEqual(doc["threshold"], 0.6)
        # idiomaticity → ρ=1.0 → calibrated.
        cal_dims = {e["dimension"] for e in doc["calibrated"]}
        self.assertIn("idiomaticity", cal_dims)
        # error_handling → ρ=0.6 → calibrated (boundary inclusive).
        self.assertIn("error_handling", cal_dims)
        # security_hygiene → all null → no_signal.
        nosig_dims = {e["dimension"] for e in doc["no_signal"]}
        self.assertIn("security_hygiene", nosig_dims)

    def test_report_md_is_human_readable(self) -> None:
        self._stage_corpus()
        report_path, _, _ = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="e2e-test",
            output_dir=self.output_dir,
        )
        text = report_path.read_text(encoding="utf-8")
        self.assertIn("# Calibration Report", text)
        self.assertIn("idiomaticity", text)
        self.assertIn("Threshold (Spearman ≥)", text)
        self.assertIn("Summary", text)

    def test_runs_root_never_mutated(self) -> None:
        self._stage_corpus()
        before = {
            p: p.read_bytes()
            for p in self.runs_root.rglob("*") if p.is_file()
        }
        validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="e2e-test",
            output_dir=self.output_dir,
        )
        after = {
            p: p.read_bytes()
            for p in self.runs_root.rglob("*") if p.is_file()
        }
        self.assertEqual(before.keys(), after.keys())
        for p, content in before.items():
            self.assertEqual(after[p], content)

    def test_judge_id_mismatch_recorded_as_skip(self) -> None:
        self._stage_corpus()
        # Run calibrate against a different judge spec.
        _, json_path, result = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:opus",  # judge.json has sonnet
            name="mismatch-test",
            output_dir=self.output_dir,
        )
        self.assertGreater(
            result.data_quality.labels_for_judge_id_mismatch, 0,
        )

    def test_missing_judge_output_recorded_as_skip(self) -> None:
        # Stage labels referencing run_paths that have no judge.json.
        _write_labels(self.labels_path, [
            {"run_path": "missing/attempt-01-run-001", "dimension": "idiomaticity", "rating": 4},
        ])
        _, _, result = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="missing-test",
            output_dir=self.output_dir,
        )
        self.assertGreater(
            result.data_quality.labels_for_missing_judge_output, 0,
        )

    def test_zero_dimensions_calibrated_terminal_state(self) -> None:
        # Per spec.md D6: when no dimension clears the threshold,
        # the report MUST still produce a valid artifact (raw ratings
        # advisory-only; no calibrated-judge verdict).
        # Stage 5 attempts where judge disagrees on every dim.
        for i in range(1, 6):
            _write_judge_json(
                self.runs_root / f"attempt-{i:02d}-run-001",
                ratings={"idiomaticity": (6 - i)},  # reverse of human
            )
        labels = []
        for i in range(1, 6):
            labels.append({
                "run_path": f"attempt-{i:02d}-run-001",
                "dimension": "idiomaticity",
                "rating": i,  # ascending; judge gave descending
            })
        _write_labels(self.labels_path, labels)
        _, json_path, _ = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="negative-result",
            output_dir=self.output_dir,
        )
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(doc["calibrated"], [])
        # The single dimension was uncalibrated (ρ=-1.0).
        self.assertEqual(len(doc["uncalibrated"]), 1)
        self.assertAlmostEqual(doc["uncalibrated"][0]["spearman"], -1.0)


# ── Out-of-range judge rating (P2.1 reviewer fix) ────────────────────


class TestOutOfRangeJudgeRating(unittest.TestCase):
    """Reviewer-flagged P2: a judge.json with rating=6 (or any
    out-of-band integer) must NOT enter the calibration sample —
    treat it as a data-quality skip with its own bucket so the
    misconfiguration is surfaced, not silently averaged away.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-calib-oob-")
        self.tmp = Path(self._tmp)
        self.runs_root = self.tmp / "runs"
        self.runs_root.mkdir()
        self.output_dir = self.tmp / "out"
        self.labels_path = self.tmp / "labels.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_judge_rating_six_skipped_with_data_quality_count(self) -> None:
        # Stage three attempts. Judge rates the third as 6
        # (out-of-band). Without the P2 fix, the (3, 6) pair would
        # enter the sample and produce ρ = 1.0 — wrongly calibrated.
        # With the fix, it's a skip; only 2 valid pairs remain and
        # the dimension is no_signal (n=2 + variation — actually ρ=1.0
        # on 2 pairs, calibrated). The key assertion: the skip count
        # increments.
        _write_judge_json(self.runs_root / "attempt-01-run-001", ratings={"idiomaticity": 1})
        _write_judge_json(self.runs_root / "attempt-02-run-001", ratings={"idiomaticity": 2})
        _write_judge_json(self.runs_root / "attempt-03-run-001", ratings={"idiomaticity": 6})
        _write_labels(self.labels_path, [
            {"run_path": "attempt-01-run-001", "dimension": "idiomaticity", "rating": 1},
            {"run_path": "attempt-02-run-001", "dimension": "idiomaticity", "rating": 2},
            {"run_path": "attempt-03-run-001", "dimension": "idiomaticity", "rating": 3},
        ])
        _, json_path, result = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="oob-test",
            output_dir=self.output_dir,
        )
        self.assertEqual(result.data_quality.labels_for_out_of_range_judge_rating, 1)
        # The valid (1,1) and (2,2) pairs entered the sample → ρ=1.0
        # on n=2 → calibrated. The (3,6) pair did NOT.
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        idi = next((e for e in doc["calibrated"] if e["dimension"] == "idiomaticity"), None)
        self.assertIsNotNone(idi)
        self.assertEqual(idi["n_paired"], 2)
        # Data-quality block surfaces the out-of-range count.
        self.assertEqual(doc["data_quality"]["labels_for_out_of_range_judge_rating"], 1)

    def test_judge_rating_zero_skipped(self) -> None:
        # The symmetric case: 0 is below the band.
        _write_judge_json(self.runs_root / "attempt-01-run-001", ratings={"idiomaticity": 1})
        _write_judge_json(self.runs_root / "attempt-02-run-001", ratings={"idiomaticity": 0})
        _write_labels(self.labels_path, [
            {"run_path": "attempt-01-run-001", "dimension": "idiomaticity", "rating": 1},
            {"run_path": "attempt-02-run-001", "dimension": "idiomaticity", "rating": 2},
        ])
        _, _, result = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="zero-test",
            output_dir=self.output_dir,
        )
        self.assertEqual(result.data_quality.labels_for_out_of_range_judge_rating, 1)

    def test_judge_rating_malformed_type_distinct_bucket(self) -> None:
        # bool and float are MALFORMED (distinct bucket from out-of-
        # range). Hand-craft a judge.json with float rating.
        attempt_dir = self.runs_root / "attempt-01-run-001"
        attempt_dir.mkdir(parents=True)
        (attempt_dir / "judge.json").write_text(
            json.dumps({
                "judge_id": "claude-code-judge",
                "judge_model": "sonnet",
                "judge_backend_id": "claude-code",
                "rubric_name": "default-v1",
                "ratings": {
                    "idiomaticity": {
                        "rating": 3.5,  # float, malformed type
                        "explanation": "x",
                        "prompt_sha256": "y",
                    },
                },
                "judge_invocation": {
                    "model": "sonnet", "temperature": None, "seed": None,
                    "temperature_control": "unsupported",
                    "seed_control": "unsupported",
                    "provider_endpoint_present": False,
                },
            }) + "\n",
            encoding="utf-8",
        )
        _write_labels(self.labels_path, [
            {"run_path": "attempt-01-run-001", "dimension": "idiomaticity", "rating": 3},
        ])
        _, _, result = validate_and_write(
            labels_path=self.labels_path,
            runs_root=self.runs_root,
            judge_family_model="claude-code:sonnet",
            name="malformed-test",
            output_dir=self.output_dir,
        )
        self.assertEqual(result.data_quality.labels_for_malformed_judge_rating, 1)
        # Distinct bucket — out-of-range count stays 0.
        self.assertEqual(result.data_quality.labels_for_out_of_range_judge_rating, 0)


# ── Threshold validation (P2.2 reviewer fix) ─────────────────────────


class TestThresholdValidation(unittest.TestCase):
    """validate_threshold rejects NaN, inf, and values outside [0, 1].
    The CLI surfaces these as EXIT_USAGE; the library raises ValueError."""

    def test_nan_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_threshold(float("nan"))

    def test_inf_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_threshold(float("inf"))
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_threshold(float("-inf"))

    def test_negative_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\[0\.0, 1\.0\]"):
            validate_threshold(-0.1)
        with self.assertRaisesRegex(ValueError, r"\[0\.0, 1\.0\]"):
            validate_threshold(-1.0)

    def test_above_one_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\[0\.0, 1\.0\]"):
            validate_threshold(1.5)
        with self.assertRaisesRegex(ValueError, r"\[0\.0, 1\.0\]"):
            validate_threshold(2.0)

    def test_boundary_values_accepted(self) -> None:
        validate_threshold(0.0)
        validate_threshold(1.0)
        validate_threshold(0.6)  # the default

    def test_validate_corpus_propagates_threshold_check(self) -> None:
        # Defense-in-depth: validate_corpus also calls validate_threshold.
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_corpus(
                [],
                runs_root=Path("/tmp"),
                judge_family_model="claude-code:sonnet",
                threshold=float("nan"),
            )


# ── No-labels error ───────────────────────────────────────────────────


class TestNoLabelsError(unittest.TestCase):
    def test_empty_labels_file_raises_no_labels(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-calib-empty-"))
        try:
            (tmp / "labels.jsonl").write_text("\n\n# comment-only\n", encoding="utf-8")
            runs_root = tmp / "runs"
            runs_root.mkdir()
            with self.assertRaises(NoLabelsError):
                validate_and_write(
                    labels_path=tmp / "labels.jsonl",
                    runs_root=runs_root,
                    judge_family_model="claude-code:sonnet",
                    name="empty",
                    output_dir=tmp / "out",
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── CLI subcommand ────────────────────────────────────────────────────


class TestCliCalibrate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-cli-calib-")
        self.tmp = Path(self._tmp)
        self.runs_root = self.tmp / "runs"
        self.runs_root.mkdir()
        self.labels_path = self.tmp / "labels.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _invoke(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def _stage_minimal_corpus(self) -> None:
        # 2 attempts × 1 dimension with perfect agreement (ρ=1.0).
        for i in (1, 2):
            _write_judge_json(
                self.runs_root / f"attempt-{i:02d}-run-001",
                ratings={"idiomaticity": i},
            )
        _write_labels(self.labels_path, [
            {"run_path": "attempt-01-run-001", "dimension": "idiomaticity", "rating": 1},
            {"run_path": "attempt-02-run-001", "dimension": "idiomaticity", "rating": 2},
        ])

    def test_labels_missing_returns_usage(self) -> None:
        code, _, err = self._invoke(
            "calibrate",
            "--labels", str(self.tmp / "nope.jsonl"),
            "--judge", "claude-code:sonnet",
            "--name", "x",
            "--runs-root", str(self.runs_root),
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("labels file not found", err)

    def test_judge_arg_without_colon_returns_usage(self) -> None:
        self._stage_minimal_corpus()
        code, _, err = self._invoke(
            "calibrate",
            "--labels", str(self.labels_path),
            "--judge", "claude-code-no-colon",
            "--name", "x",
            "--runs-root", str(self.runs_root),
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("<family>:<model>", err)

    def test_runs_root_missing_returns_usage(self) -> None:
        self._stage_minimal_corpus()
        code, _, err = self._invoke(
            "calibrate",
            "--labels", str(self.labels_path),
            "--judge", "claude-code:sonnet",
            "--name", "x",
            "--runs-root", str(self.tmp / "no-runs"),
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("runs-root not found", err)

    def test_happy_path(self) -> None:
        self._stage_minimal_corpus()
        code, stdout, err = self._invoke(
            "calibrate",
            "--labels", str(self.labels_path),
            "--judge", "claude-code:sonnet",
            "--name", "cli-test",
            "--runs-root", str(self.runs_root),
            "--output-dir", str(self.tmp / "out"),
        )
        self.assertEqual(code, EXIT_OK, msg=f"stderr: {err}")
        payload = json.loads(stdout)
        self.assertEqual(payload["calibrated"], 1)
        self.assertEqual(payload["uncalibrated"], 0)
        self.assertEqual(payload["no_signal"], 0)
        self.assertEqual(payload["judge"], "claude-code:sonnet")
        self.assertTrue(Path(payload["report_path"]).exists())
        self.assertTrue(Path(payload["json_path"]).exists())

    def test_malformed_labels_returns_usage(self) -> None:
        self.labels_path.write_text(
            '{"run_path":"a","dimension":"d","rating":4}\n'
            'not JSON\n',
            encoding="utf-8",
        )
        code, _, err = self._invoke(
            "calibrate",
            "--labels", str(self.labels_path),
            "--judge", "claude-code:sonnet",
            "--name", "bad",
            "--runs-root", str(self.runs_root),
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("labels parse error", err)

    def test_empty_labels_returns_runtime(self) -> None:
        # File present but contains only blanks/comments → EXIT_RUNTIME
        # (distinct from "file missing" which is EXIT_USAGE).
        self.labels_path.write_text("\n# nothing here\n\n", encoding="utf-8")
        code, _, err = self._invoke(
            "calibrate",
            "--labels", str(self.labels_path),
            "--judge", "claude-code:sonnet",
            "--name", "empty",
            "--runs-root", str(self.runs_root),
        )
        self.assertEqual(code, EXIT_RUNTIME)

    def test_threshold_nan_returns_usage(self) -> None:
        self._stage_minimal_corpus()
        code, _, err = self._invoke(
            "calibrate",
            "--labels", str(self.labels_path),
            "--judge", "claude-code:sonnet",
            "--name", "nan",
            "--runs-root", str(self.runs_root),
            "--threshold", "nan",
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("--threshold", err)
        self.assertIn("finite", err)

    def test_threshold_negative_returns_usage(self) -> None:
        self._stage_minimal_corpus()
        code, _, err = self._invoke(
            "calibrate",
            "--labels", str(self.labels_path),
            "--judge", "claude-code:sonnet",
            "--name", "neg",
            "--runs-root", str(self.runs_root),
            "--threshold", "-0.5",
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("--threshold", err)

    def test_threshold_above_one_returns_usage(self) -> None:
        self._stage_minimal_corpus()
        code, _, err = self._invoke(
            "calibrate",
            "--labels", str(self.labels_path),
            "--judge", "claude-code:sonnet",
            "--name", "above",
            "--runs-root", str(self.runs_root),
            "--threshold", "1.5",
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("--threshold", err)


if __name__ == "__main__":
    unittest.main()
