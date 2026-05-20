# tests/test_corpus_select.py — calibration corpus selector tests.
#
# Three layers:
#   1. Synthetic-fixture unit tests for the pure select_corpus()
#      function (no I/O).
#   2. Filesystem-level tests for discover_candidates() against a
#      tmpdir runs/ tree (synthetic run-record.json + score.json).
#   3. Live-acceptance test against the real runs/ archive — gated by
#      a skip when the archive is absent (fresh-clone CI safety).
#      Asserts the issue #48 acceptance: target_n=50, axes=model +
#      repeated-runs, both axes represented.

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from benchmark_runner.calibration.corpus_select import (
    AXIS_ADAPTER,
    AXIS_BACKEND,
    AXIS_MODEL,
    AXIS_REPEATED_RUNS,
    CORPUS_SCHEMA_VERSION,
    Candidate,
    EmptyCandidatePoolError,
    InsufficientAxisRepresentationError,
    InvalidAxisError,
    SelectionResult,
    discover_candidates,
    parse_axes_arg,
    select_and_write,
    select_corpus,
    write_corpus,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIVE_RUNS_ROOT = _REPO_ROOT / "runs"


# ── Pure-function helpers ─────────────────────────────────────────────


def _candidate(
    *,
    rel_path: str,
    model: str,
    task_id: str = "python/leap",
    benchmark_id: str = "aider-polyglot",
    backend_id: str = "claude-code",
    result: str = "fail",
    attempt: int = 1,
    run_id: str = "run-001",
) -> Candidate:
    return Candidate(
        rel_path=rel_path,
        abs_path=Path(f"/tmp/{rel_path}"),
        benchmark_id=benchmark_id,
        backend_id=backend_id,
        model=model,
        task_id=task_id,
        result=result,
        attempt=attempt,
        run_id=run_id,
    )


# ── select_corpus pure-function tests ─────────────────────────────────


class TestParseAxesArg(unittest.TestCase):
    def test_valid_axes(self) -> None:
        self.assertEqual(
            parse_axes_arg("model,repeated-runs"),
            ["model", "repeated-runs"],
        )

    def test_preserves_order(self) -> None:
        # Order matters for the round-robin's grouping key
        # ((model, adapter) vs (adapter, model)). The CLI must
        # preserve what the user typed.
        self.assertEqual(
            parse_axes_arg("adapter,model,backend"),
            ["adapter", "model", "backend"],
        )

    def test_whitespace_tolerant(self) -> None:
        self.assertEqual(
            parse_axes_arg("  model , repeated-runs "),
            ["model", "repeated-runs"],
        )

    def test_empty_string_raises(self) -> None:
        with self.assertRaises(InvalidAxisError):
            parse_axes_arg("")
        with self.assertRaises(InvalidAxisError):
            parse_axes_arg(",,,")

    def test_unknown_axis_raises(self) -> None:
        with self.assertRaisesRegex(InvalidAxisError, "unknown axis"):
            parse_axes_arg("model,not-a-real-axis")

    def test_duplicate_raises(self) -> None:
        with self.assertRaisesRegex(InvalidAxisError, "duplicate"):
            parse_axes_arg("model,model")


class TestSelectCorpusModelAxis(unittest.TestCase):
    """The acceptance hinge for #48: `--axes model` round-robins by
    distinct model values to ensure ≥2 are represented."""

    def setUp(self) -> None:
        # 12 candidates across 3 models. Path-sorted such that the
        # first 5 lexicographically are all model-A; without the
        # round-robin guarantee, a naive head() would select 0 of B/C.
        self.candidates = [
            _candidate(rel_path=f"run-A/task-{i:02d}/attempt-01-run-001",
                       model="model-A")
            for i in range(5)
        ] + [
            _candidate(rel_path=f"run-B/task-{i:02d}/attempt-01-run-001",
                       model="model-B")
            for i in range(5)
        ] + [
            _candidate(rel_path=f"run-C/task-{i:02d}/attempt-01-run-001",
                       model="model-C")
            for i in range(5)
        ]

    def test_round_robin_includes_every_model_at_small_target(self) -> None:
        # target_n=3, 3 models → exactly one of each (round-robin
        # picks one per group on the first pass).
        result = select_corpus(self.candidates, [AXIS_MODEL], target_n=3)
        models = {c.model for c in result.selected}
        self.assertEqual(models, {"model-A", "model-B", "model-C"})
        self.assertEqual(len(result.selected), 3)

    def test_balanced_distribution_at_larger_target(self) -> None:
        result = select_corpus(self.candidates, [AXIS_MODEL], target_n=9)
        per_model: dict[str, int] = {}
        for c in result.selected:
            per_model[c.model] = per_model.get(c.model, 0) + 1
        # Round-robin → 3 per model.
        self.assertEqual(per_model, {"model-A": 3, "model-B": 3, "model-C": 3})

    def test_at_least_two_models_represented(self) -> None:
        # The issue #48 acceptance: with --axes model, the selected
        # set has ≥2 distinct values for model.
        result = select_corpus(self.candidates, [AXIS_MODEL], target_n=5)
        models = {c.model for c in result.selected}
        self.assertGreaterEqual(len(models), 2)

    def test_pool_with_single_model_raises_pre_selection(self) -> None:
        single = [_candidate(rel_path=f"run-A/t{i:02d}/attempt-01-run-001",
                             model="only-one")
                  for i in range(10)]
        with self.assertRaisesRegex(InsufficientAxisRepresentationError, "model"):
            select_corpus(single, [AXIS_MODEL], target_n=5)


class TestSelectCorpusRepeatedRunsAxis(unittest.TestCase):
    """The other acceptance hinge: `--axes repeated-runs` ensures at
    least one (task, backend, model) tuple has ≥2 selected attempts."""

    def setUp(self) -> None:
        # A pool with model variation AND repeated attempts. 5 distinct
        # tasks for model-A; for one task, 3 attempts (genuine repeats).
        # Other models have 1 attempt per task to avoid accidentally
        # satisfying repeated-runs from elsewhere.
        c = []
        # model-A repeats on python/leap (3 attempts).
        for run_n in (1, 2, 3):
            c.append(_candidate(
                rel_path=f"run-A-r{run_n}/python-leap/attempt-01-run-001",
                model="model-A",
                task_id="python/leap",
                run_id=f"run-00{run_n}",
            ))
        # model-A on other tasks, single attempts.
        for t in ("hello-world", "bowling", "raindrops", "leap-year-helper"):
            c.append(_candidate(
                rel_path=f"run-A-only/{t}/attempt-01-run-001",
                model="model-A",
                task_id=f"python/{t}",
            ))
        # model-B, single attempts each on distinct tasks.
        for t in ("alpha", "beta", "gamma", "delta", "epsilon"):
            c.append(_candidate(
                rel_path=f"run-B/{t}/attempt-01-run-001",
                model="model-B",
                task_id=f"python/{t}",
            ))
        self.candidates = c

    def test_repeated_runs_satisfied_naturally(self) -> None:
        # With target_n large enough to naturally pull both repeats,
        # the algorithm satisfies repeated-runs without repair.
        result = select_corpus(
            self.candidates,
            [AXIS_MODEL, AXIS_REPEATED_RUNS],
            target_n=10,
        )
        # At least one (task, backend, model) tuple has ≥2 entries.
        tuples: dict = {}
        for sc in result.selected:
            k = (sc.task_id, sc.backend_id, sc.model)
            tuples[k] = tuples.get(k, 0) + 1
        self.assertTrue(any(v >= 2 for v in tuples.values()),
                        msg=f"tuples: {tuples}")

    def test_repeated_runs_strategy_a_extends_existing_tuple(self) -> None:
        # target_n=10, axes=[model, repeated-runs] — round-robin pulls
        # one of each model alternately; among model-A's picks is
        # python/leap (the only repeating tuple in the pool). When
        # repeated-runs isn't yet satisfied at the end of round-robin,
        # repair Strategy A extends (python/leap, A) by adding its
        # unselected sibling, replacing the LAST entry that doesn't
        # belong to that tuple. Both axes remain satisfied because
        # Strategy A only sacrifices a NON-key entry.
        result = select_corpus(
            self.candidates,
            [AXIS_MODEL, AXIS_REPEATED_RUNS],
            target_n=10,
        )
        # Repeated-runs satisfied.
        tuples: dict = {}
        for sc in result.selected:
            k = (sc.task_id, sc.backend_id, sc.model)
            tuples[k] = tuples.get(k, 0) + 1
        self.assertTrue(any(v >= 2 for v in tuples.values()),
                        msg=f"tuples: {tuples}")
        # AND model axis still satisfied — Strategy A's whole point
        # is to preserve the other axes.
        models = {sc.model for sc in result.selected}
        self.assertGreaterEqual(len(models), 2,
                                msg=f"models lost after repair: {models}")

    def test_repair_that_would_break_model_axis_raises(self) -> None:
        # target_n=2, axes=[model, repeated-runs] — round-robin picks
        # one of each model (no repeats), no selected tuple has a
        # sibling in the pool, so Strategy A fails and Strategy B
        # would replace the last two entries with siblings of a
        # repeating tuple — which would collapse the model axis to
        # 1 distinct value. With the post-repair re-validation
        # (added 2026-05-20), this is now a hard error instead of
        # a silent degradation.
        with self.assertRaisesRegex(
            InsufficientAxisRepresentationError, "left axis 'model'"
        ):
            select_corpus(
                self.candidates,
                [AXIS_MODEL, AXIS_REPEATED_RUNS],
                target_n=2,
            )

    def test_repeated_runs_target_n_one_raises(self) -> None:
        # target_n=1 can never satisfy repeated-runs (need at least
        # 2 selections of the same tuple). Pre-validated before
        # round-robin so the error message names the real constraint.
        with self.assertRaisesRegex(
            InsufficientAxisRepresentationError, "target_n >= 2"
        ):
            select_corpus(
                self.candidates,
                [AXIS_MODEL, AXIS_REPEATED_RUNS],
                target_n=1,
            )

    def test_pool_with_no_repeats_raises_for_repeated_runs(self) -> None:
        # Pool has model variation but every (task, backend, model)
        # tuple is unique → repeated-runs axis cannot be satisfied.
        unique = []
        for i, m in enumerate(("a", "b", "c")):
            for t in (f"t{i}-x", f"t{i}-y", f"t{i}-z"):
                unique.append(_candidate(
                    rel_path=f"run/{m}/{t}/attempt-01-run-001",
                    model=m,
                    task_id=t,
                ))
        with self.assertRaisesRegex(
            InsufficientAxisRepresentationError, "repeated-runs"
        ):
            select_corpus(unique, [AXIS_MODEL, AXIS_REPEATED_RUNS], target_n=5)


class TestSelectCorpusDeterminism(unittest.TestCase):
    """Determinism + reproducibility (user-mandated constraint)."""

    def _pool(self) -> list[Candidate]:
        # Larger pool with varied paths to exercise sort stability.
        out = []
        for model in ("alpha", "beta", "gamma"):
            for t in range(8):
                for attempt in (1, 2):
                    out.append(_candidate(
                        rel_path=f"run-{model}/task-{t:02d}/attempt-{attempt:02d}-run-001",
                        model=model,
                        task_id=f"task-{t:02d}",
                        attempt=attempt,
                    ))
        # Shuffle to verify the algorithm doesn't depend on input order.
        return out[::-1]

    def test_same_inputs_same_outputs(self) -> None:
        r1 = select_corpus(self._pool(), [AXIS_MODEL, AXIS_REPEATED_RUNS], target_n=12)
        r2 = select_corpus(self._pool(), [AXIS_MODEL, AXIS_REPEATED_RUNS], target_n=12)
        self.assertEqual(
            [c.rel_path for c in r1.selected],
            [c.rel_path for c in r2.selected],
        )

    def test_output_sorted_by_rel_path(self) -> None:
        result = select_corpus(self._pool(), [AXIS_MODEL], target_n=9)
        paths = [c.rel_path for c in result.selected]
        self.assertEqual(paths, sorted(paths))


class TestSelectCorpusInputValidation(unittest.TestCase):
    def test_empty_candidates_raises(self) -> None:
        with self.assertRaises(EmptyCandidatePoolError):
            select_corpus([], [AXIS_MODEL], target_n=5)

    def test_target_n_zero_raises(self) -> None:
        c = [_candidate(rel_path=f"r/{i}/attempt-01-run-001", model="m")
             for i in range(2)]
        with self.assertRaisesRegex(ValueError, "target_n"):
            select_corpus(c, [AXIS_MODEL], target_n=0)

    def test_target_n_exceeds_pool_raises(self) -> None:
        c = [_candidate(rel_path=f"r/{i}/attempt-01-run-001", model="m")
             for i in range(3)]
        with self.assertRaisesRegex(
            InsufficientAxisRepresentationError, "exceeds candidate pool"
        ):
            select_corpus(c, [AXIS_MODEL], target_n=100)

    def test_unknown_axis_raises(self) -> None:
        c = [_candidate(rel_path=f"r/{i}/attempt-01-run-001", model="m")
             for i in range(2)]
        with self.assertRaisesRegex(InvalidAxisError, "unknown axis"):
            select_corpus(c, ["not-an-axis"], target_n=2)

    def test_empty_axes_raises(self) -> None:
        c = [_candidate(rel_path=f"r/{i}/attempt-01-run-001", model="m")
             for i in range(2)]
        with self.assertRaises(InvalidAxisError):
            select_corpus(c, [], target_n=2)


# ── discover_candidates filesystem tests ──────────────────────────────


def _write_attempt(
    base: Path,
    *,
    benchmark_id: str = "aider-polyglot",
    backend_id: str = "claude-code",
    model: str = "sonnet",
    task_id: str = "python/leap",
    result: str = "pass",
    attempt: int = 1,
    run_id: str = "run-001",
    skip_run_record: bool = False,
    skip_score: bool = False,
    malformed_run_record: bool = False,
    malformed_score: bool = False,
    omit_fields: Optional[set[str]] = None,
) -> Path:
    """Stage one attempt directory + run-record.json + score.json."""
    base.mkdir(parents=True, exist_ok=True)
    omit_fields = omit_fields or set()
    run_record = {
        "schema_version": "1.0",
        "benchmark_id": benchmark_id,
        "task_id": task_id,
        "backend_id": backend_id,
        "run_id": run_id,
        "attempt": attempt,
        "backend_invocation": {"model": model},
    }
    for f in omit_fields:
        # Allow tests to remove top-level fields to simulate corruption.
        run_record.pop(f, None)
    score = {
        "schema_version": "1.0",
        "benchmark_id": benchmark_id,
        "task_id": task_id,
        "result": result,
    }
    if not skip_run_record:
        text = "NOT JSON {{" if malformed_run_record else json.dumps(run_record)
        (base / "run-record.json").write_text(text + "\n", encoding="utf-8")
    if not skip_score:
        text = "ALSO NOT JSON" if malformed_score else json.dumps(score)
        (base / "score.json").write_text(text + "\n", encoding="utf-8")
    return base


class TestDiscoverCandidates(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-corpus-test-")
        self.runs_root = Path(self._tmp) / "runs"
        self.runs_root.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_discovers_single_run_layout(self) -> None:
        # runs/<run>/<task>/<attempt>
        _write_attempt(
            self.runs_root / "20260520-aider-001" / "python-leap" / "attempt-01-run-001",
            model="sonnet",
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].model, "sonnet")
        self.assertEqual(skipped, {})

    def test_discovers_compare_run_layout(self) -> None:
        # runs/<compare>/<run>/<task>/<attempt>
        _write_attempt(
            self.runs_root / "20260520-compare-001" / "20260520-aider-A"
            / "python-leap" / "attempt-01-run-001",
            model="sonnet",
        )
        _write_attempt(
            self.runs_root / "20260520-compare-001" / "20260520-aider-B"
            / "python-leap" / "attempt-01-run-001",
            model="opus",
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(skipped, {})

    def test_missing_score_json_reported_not_dropped(self) -> None:
        _write_attempt(
            self.runs_root / "run-A" / "python-leap" / "attempt-01-run-001",
            skip_score=True,
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(candidates, [])
        # Skip recorded with reason.
        self.assertEqual(len(skipped), 1)
        reason = next(iter(skipped.values()))
        self.assertIn("score.json missing", reason)

    def test_missing_run_record_reported_not_dropped(self) -> None:
        _write_attempt(
            self.runs_root / "run-A" / "python-leap" / "attempt-01-run-001",
            skip_run_record=True,
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(candidates, [])
        reason = next(iter(skipped.values()))
        self.assertIn("run-record.json missing", reason)

    def test_malformed_run_record_reported_not_dropped(self) -> None:
        _write_attempt(
            self.runs_root / "run-A" / "python-leap" / "attempt-01-run-001",
            malformed_run_record=True,
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(candidates, [])
        reason = next(iter(skipped.values()))
        self.assertIn("run-record.json unparseable", reason)

    def test_malformed_score_json_reported_not_dropped(self) -> None:
        _write_attempt(
            self.runs_root / "run-A" / "python-leap" / "attempt-01-run-001",
            malformed_score=True,
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(candidates, [])
        reason = next(iter(skipped.values()))
        self.assertIn("score.json unparseable", reason)

    def test_malformed_typed_attempt_reported_not_fatal(self) -> None:
        # ``attempt: "not-int"`` is JSON-parseable but the type is
        # wrong. The walker must record it as a skip (with reason)
        # and CONTINUE — not abort on the int() coercion.
        rec_dir = self.runs_root / "run-A" / "python-leap" / "attempt-01-run-001"
        rec_dir.mkdir(parents=True)
        rec = {
            "schema_version": "1.0",
            "benchmark_id": "aider-polyglot",
            "task_id": "python/leap",
            "backend_id": "claude-code",
            "run_id": "run-001",
            "attempt": "not-int",  # malformed type
            "backend_invocation": {"model": "sonnet"},
        }
        (rec_dir / "run-record.json").write_text(json.dumps(rec) + "\n", encoding="utf-8")
        (rec_dir / "score.json").write_text(
            json.dumps({"result": "fail"}) + "\n", encoding="utf-8",
        )
        # Add a HEALTHY second attempt so we can verify the walker
        # didn't abort prematurely — the healthy record must come
        # through even though the malformed one preceded it.
        _write_attempt(
            self.runs_root / "run-B" / "python-leap" / "attempt-01-run-001",
            model="opus",
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(len(candidates), 1)  # the healthy one
        self.assertEqual(candidates[0].model, "opus")
        # The malformed one was recorded as a skip, not crashed.
        self.assertEqual(len(skipped), 1)
        reason = next(iter(skipped.values()))
        self.assertIn("malformed typed field", reason)

    def test_malformed_backend_invocation_type_reported_not_fatal(self) -> None:
        # ``backend_invocation: "not-a-dict"`` would crash a
        # ``.get("model")`` call. Walker must skip with a reason,
        # not abort.
        rec_dir = self.runs_root / "run-bad" / "python-leap" / "attempt-01-run-001"
        rec_dir.mkdir(parents=True)
        rec = {
            "schema_version": "1.0",
            "benchmark_id": "aider-polyglot",
            "task_id": "python/leap",
            "backend_id": "claude-code",
            "run_id": "run-001",
            "attempt": 1,
            "backend_invocation": "this-should-be-a-dict",
        }
        (rec_dir / "run-record.json").write_text(json.dumps(rec) + "\n", encoding="utf-8")
        (rec_dir / "score.json").write_text(
            json.dumps({"result": "fail"}) + "\n", encoding="utf-8",
        )
        _write_attempt(
            self.runs_root / "run-good" / "python-leap" / "attempt-01-run-001",
            model="sonnet",
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].model, "sonnet")
        self.assertEqual(len(skipped), 1)
        reason = next(iter(skipped.values()))
        self.assertIn("backend_invocation", reason)
        self.assertIn("wrong type", reason)

    def test_missing_required_field_reported_not_dropped(self) -> None:
        # Drop benchmark_id from the run-record.json → required-field
        # skip rather than silent default.
        _write_attempt(
            self.runs_root / "run-A" / "python-leap" / "attempt-01-run-001",
            omit_fields={"benchmark_id"},
        )
        candidates, skipped = discover_candidates(self.runs_root)
        self.assertEqual(candidates, [])
        reason = next(iter(skipped.values()))
        self.assertIn("missing fields", reason)
        self.assertIn("benchmark_id", reason)

    def test_runs_root_missing_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            discover_candidates(self.runs_root.parent / "nope")

    def test_discovery_order_is_deterministic(self) -> None:
        # Lay out three attempts; assert the order returned matches
        # sorted-by-rel_path regardless of filesystem readdir order.
        for letter in ("c", "a", "b"):
            _write_attempt(
                self.runs_root / f"run-{letter}" / "task" / "attempt-01-run-001",
                model=letter,
            )
        candidates, _ = discover_candidates(self.runs_root)
        rels = [c.rel_path for c in candidates]
        self.assertEqual(rels, sorted(rels))


# ── write_corpus + select_and_write ───────────────────────────────────


class TestWriteCorpusAndEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-corpus-test-")
        self.runs_root = Path(self._tmp) / "runs"
        self.runs_root.mkdir()
        # Stage 3 models × 2 tasks × 2 attempts = 12 attempts.
        for m in ("alpha", "beta", "gamma"):
            for t in ("t-x", "t-y"):
                for a in (1, 2):
                    _write_attempt(
                        self.runs_root / f"run-{m}" / t
                        / f"attempt-{a:02d}-run-001",
                        model=m,
                        task_id=f"python/{t}",
                        attempt=a,
                    )
        self.output_dir = Path(self._tmp) / "out"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_select_and_write_produces_corpus_and_meta(self) -> None:
        corpus_path, meta_path, result = select_and_write(
            runs_root=self.runs_root,
            axes=[AXIS_MODEL, AXIS_REPEATED_RUNS],
            target_n=6,
            name="test-corpus",
            output_dir=self.output_dir,
            selection_command="pretend command",
        )
        self.assertTrue(corpus_path.exists())
        self.assertTrue(meta_path.exists())
        # corpus.jsonl has one JSON record per line.
        lines = corpus_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 6)
        for line in lines:
            rec = json.loads(line)
            self.assertIn("run_path", rec)
            self.assertIn("model", rec)
            self.assertIn("task_id", rec)
        # meta.json carries the reproducibility record.
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["schema_version"], CORPUS_SCHEMA_VERSION)
        self.assertEqual(meta["name"], "test-corpus")
        self.assertEqual(meta["target_n"], 6)
        self.assertEqual(meta["actual_n"], 6)
        self.assertEqual(meta["axes"], [AXIS_MODEL, AXIS_REPEATED_RUNS])
        self.assertEqual(meta["selection_command"], "pretend command")

    def test_runs_root_never_mutated(self) -> None:
        # Snapshot every file under runs/ pre- and post- and assert
        # nothing changed. The selector is additive ONLY to output_dir.
        before = {
            p: p.read_bytes()
            for p in self.runs_root.rglob("*") if p.is_file()
        }
        select_and_write(
            runs_root=self.runs_root,
            axes=[AXIS_MODEL, AXIS_REPEATED_RUNS],
            target_n=6,
            name="test-corpus",
            output_dir=self.output_dir,
        )
        after = {
            p: p.read_bytes()
            for p in self.runs_root.rglob("*") if p.is_file()
        }
        self.assertEqual(before.keys(), after.keys())
        for p, content in before.items():
            self.assertEqual(after[p], content)

    def test_meta_records_skipped_attempts(self) -> None:
        # Add a deliberately malformed attempt and confirm meta.json
        # surfaces it under "skipped".
        _write_attempt(
            self.runs_root / "run-bad" / "task" / "attempt-01-run-001",
            malformed_score=True,
        )
        _, meta_path, _ = select_and_write(
            runs_root=self.runs_root,
            axes=[AXIS_MODEL, AXIS_REPEATED_RUNS],
            target_n=6,
            name="with-skips",
            output_dir=self.output_dir,
        )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        # Exactly the malformed one was skipped (others were healthy).
        self.assertEqual(len(meta["skipped"]), 1)
        reason = next(iter(meta["skipped"].values()))
        self.assertIn("score.json unparseable", reason)

    def test_axis_summary_in_meta(self) -> None:
        _, meta_path, _ = select_and_write(
            runs_root=self.runs_root,
            axes=[AXIS_MODEL, AXIS_REPEATED_RUNS],
            target_n=6,
            name="axis-summary",
            output_dir=self.output_dir,
        )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertIn("model", meta["axis_summary"])
        self.assertIn("repeated-runs", meta["axis_summary"])
        # Model axis: ≥2 distinct values.
        self.assertGreaterEqual(len(meta["axis_summary"]["model"]), 2)
        # Repeated-runs: ≥1 tuple with ≥2 selections.
        self.assertGreaterEqual(
            meta["axis_summary"]["repeated-runs"]["tuples_with_>=2_runs"], 1,
        )


# ── Live acceptance against the real runs/ archive ────────────────────


@unittest.skipUnless(
    _LIVE_RUNS_ROOT.exists() and any(_LIVE_RUNS_ROOT.rglob("attempt-*")),
    "live runs/ archive absent on this machine (fresh clone / CI)",
)
class TestLiveCorpusAcceptance(unittest.TestCase):
    """Issue #48 acceptance gate.

    Runs the real selector against the maintainer's runs/ archive
    and asserts the corpus satisfies the documented threshold:
    target_n >= 50 and ≥2 axes represented (model + repeated-runs).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-corpus-live-")
        self.output_dir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_target_n_50_axes_model_and_repeated_runs(self) -> None:
        corpus_path, meta_path, result = select_and_write(
            runs_root=_LIVE_RUNS_ROOT,
            axes=[AXIS_MODEL, AXIS_REPEATED_RUNS],
            target_n=50,
            name="live-acceptance",
            output_dir=self.output_dir,
            selection_command="(test) live-acceptance probe",
        )
        # Acceptance bar #1: target_n hit.
        self.assertGreaterEqual(len(result.selected), 50)
        # Acceptance bar #2: model axis represented (≥2 distinct).
        models = {c.model for c in result.selected}
        self.assertGreaterEqual(
            len(models), 2,
            msg=f"only {len(models)} distinct models in selection: {models}",
        )
        # Acceptance bar #3: repeated-runs satisfied.
        tuples: dict = {}
        for c in result.selected:
            k = (c.task_id, c.backend_id, c.model)
            tuples[k] = tuples.get(k, 0) + 1
        repeats = [(k, v) for k, v in tuples.items() if v >= 2]
        self.assertGreaterEqual(
            len(repeats), 1,
            msg="no (task, backend, model) tuple has ≥2 attempts in the selection",
        )
        # meta.json was written + readable.
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["axes"], [AXIS_MODEL, AXIS_REPEATED_RUNS])
        # Sanity: runs_root in meta points at the live tree.
        self.assertEqual(
            Path(meta["runs_root"]).resolve(), _LIVE_RUNS_ROOT.resolve(),
        )


if __name__ == "__main__":
    unittest.main()
