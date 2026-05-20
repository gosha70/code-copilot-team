# tests/test_judge_runner.py — judge runner tests.
#
# Stages a synthetic run-dir matching the layout
# benchmark_runner.run writes (run_dir/<task-slug>/attempt-NN-run-MM/
# with score.json, run-record.json, diff.patch, prompt.md,
# verify-output.txt) and drives ``run_judge`` with a stub Judge.
#
# THE central invariant under test: score.json is byte-identical
# before and after each rate() call. A judge that mutates score.json
# is rejected with ScoreJsonMutatedError.

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Mapping, Optional

from benchmark_runner.judge.contracts import (
    DimensionRating,
    JudgeInput,
    JudgeInvocation,
    JudgeResult,
    RubricSpec,
)
from benchmark_runner.judge.runner import (
    JUDGE_JSON_SCHEMA_VERSION,
    RunJudgeStats,
    ScoreJsonMutatedError,
    run_judge,
)


_RUBRIC = RubricSpec(
    name="default-v1",
    dimensions=("idiomaticity", "error_handling", "test_thoughtfulness", "security_hygiene"),
    prompt_template="Task: {task_id} ({benchmark_id})\n{prompt}\n{diff}\n{verify_output}\n",
)


def _make_run_dir(tmp_path: Path, attempts: list[dict]) -> Path:
    """Stage a run-dir matching benchmark_runner.run's layout.

    Each ``attempts`` entry shapes one attempt directory:
      {
        "task_slug": "python-bowling",
        "attempt_id": "attempt-01-run-001",
        "task_id": "python/bowling",
        "benchmark_id": "aider-polyglot",
        "result": "fail",
        "diff": "diff content\\n",         # default if missing
        "prompt": "prompt content\\n",     # default if missing
        "verify_output": "tests ran\\n",   # default if missing
        "skip_files": {"diff", "score"},   # override which files to write
      }
    """
    run_dir = tmp_path / "20260520T000000Z-aider-polyglot-claude-code-001"
    run_dir.mkdir()
    for a in attempts:
        task_slug = a["task_slug"]
        attempt_id = a["attempt_id"]
        task_dir = run_dir / task_slug
        task_dir.mkdir(exist_ok=True)
        attempt_dir = task_dir / attempt_id
        attempt_dir.mkdir()
        skip = a.get("skip_files", set())
        if "score" not in skip:
            score = {
                "schema_version": "1.0",
                "benchmark_id": a.get("benchmark_id", "aider-polyglot"),
                "task_id": a.get("task_id", task_slug.replace("-", "/", 1)),
                "backend_id": "claude-code",
                "run_id": "run-001",
                "attempt": 1,
                "scores": {
                    "tests_passed": a.get("result", "fail") == "pass",
                },
                "result": a.get("result", "fail"),
            }
            (attempt_dir / "score.json").write_text(
                json.dumps(score, indent=2) + "\n", encoding="utf-8"
            )
        if "diff" not in skip:
            (attempt_dir / "diff.patch").write_text(
                a.get("diff", "diff content\n"), encoding="utf-8"
            )
        if "prompt" not in skip:
            (attempt_dir / "prompt.md").write_text(
                a.get("prompt", "prompt content\n"), encoding="utf-8"
            )
        if "verify" not in skip:
            (attempt_dir / "verify-output.txt").write_text(
                a.get("verify_output", "tests ran\n"), encoding="utf-8"
            )
    return run_dir


# ── Stub judges ────────────────────────────────────────────────────────


class _CannedJudge:
    """Returns the same canned JudgeResult for every attempt. No I/O."""

    judge_id = "canned-judge"

    def __init__(self, *, rating: Optional[int] = 4) -> None:
        self._rating = rating
        self.calls: list[JudgeInput] = []

    def rate(self, attempt: JudgeInput) -> JudgeResult:
        self.calls.append(attempt)
        return JudgeResult(
            judge_id=self.judge_id,
            judge_model="canned",
            judge_backend_id="canned",
            rubric_name=attempt.rubric.name,
            ratings={
                dim: DimensionRating(
                    rating=self._rating,
                    explanation=f"canned rating for {dim}",
                    prompt_sha256="canned-sha",
                )
                for dim in attempt.rubric.dimensions
            },
            invocation=JudgeInvocation(model="canned"),
        )


class _ScoreMutatingJudge:
    """Bad-actor judge that mutates score.json during rate(). Used to
    prove the additivity invariant guard fires."""

    judge_id = "bad-judge"

    def rate(self, attempt: JudgeInput) -> JudgeResult:
        score_path = attempt.attempt_dir / "score.json"
        score_path.write_text("MUTATED\n", encoding="utf-8")
        return JudgeResult(
            judge_id=self.judge_id,
            judge_model="bad",
            judge_backend_id="bad",
            rubric_name=attempt.rubric.name,
            ratings={
                dim: DimensionRating(rating=3, explanation="x", prompt_sha256="y")
                for dim in attempt.rubric.dimensions
            },
            invocation=JudgeInvocation(model="bad"),
        )


class _RaisingJudge:
    """Raises during rate(). Used to prove per-attempt isolation."""

    judge_id = "raising-judge"

    def rate(self, attempt: JudgeInput) -> JudgeResult:
        raise RuntimeError("simulated rate failure")


class _MutateThenRaiseJudge:
    """Worst-of-both-worlds bad-actor: mutates score.json then raises.

    Without the after-hash check on the exception path, a per-attempt
    failure would record this as a normal isolated failure, leaving
    the mutated score.json on disk and letting the runner continue.
    The guard must trip on BOTH the success and the exception paths.
    """

    judge_id = "mutate-then-raise-judge"

    def rate(self, attempt: JudgeInput) -> JudgeResult:
        (attempt.attempt_dir / "score.json").write_text(
            "MUTATED-BEFORE-RAISE\n", encoding="utf-8"
        )
        raise RuntimeError("simulated rate failure AFTER mutating score.json")


# ── Walk + write tests ────────────────────────────────────────────────


class TestRunJudgeHappyPath(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-judge-runner-test-")
        self.tmpdir = Path(self._tmp)
        self.run_dir = _make_run_dir(self.tmpdir, [
            {"task_slug": "python-bowling", "attempt_id": "attempt-01-run-001"},
            {"task_slug": "python-bowling", "attempt_id": "attempt-02-run-001"},
            {"task_slug": "rust-react", "attempt_id": "attempt-01-run-001"},
        ])
        self.judge = _CannedJudge()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_processes_every_attempt(self) -> None:
        stats = run_judge(self.run_dir, self.judge, _RUBRIC)
        self.assertEqual(stats.attempts_processed, 3)
        self.assertEqual(stats.attempts_skipped, 0)
        self.assertEqual(stats.attempts_failed, 0)

    def test_writes_judge_json_adjacent_to_score_json(self) -> None:
        run_judge(self.run_dir, self.judge, _RUBRIC)
        for attempt_dir in sorted(self.run_dir.rglob("attempt-*")):
            self.assertTrue((attempt_dir / "judge.json").exists())
            self.assertTrue((attempt_dir / "score.json").exists())

    def test_judge_json_schema_shape(self) -> None:
        run_judge(self.run_dir, self.judge, _RUBRIC)
        first = next(self.run_dir.rglob("judge.json"))
        payload = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], JUDGE_JSON_SCHEMA_VERSION)
        self.assertEqual(payload["judge_id"], "canned-judge")
        self.assertEqual(payload["rubric_name"], "default-v1")
        self.assertEqual(
            payload["rubric_dimensions"], list(_RUBRIC.dimensions),
        )
        for dim in _RUBRIC.dimensions:
            self.assertIn(dim, payload["ratings"])
            self.assertEqual(payload["ratings"][dim]["rating"], 4)
        # Determinism contract serialized through.
        inv = payload["judge_invocation"]
        self.assertIsNone(inv["temperature"])
        self.assertIsNone(inv["seed"])
        self.assertEqual(inv["temperature_control"], "unsupported")
        self.assertEqual(inv["seed_control"], "unsupported")

    def test_input_carries_task_and_benchmark_ids_from_score_json(self) -> None:
        run_judge(self.run_dir, self.judge, _RUBRIC)
        # The judge stub recorded what it saw; assert task_id roundtrip.
        seen_tasks = {call.task_id for call in self.judge.calls}
        self.assertIn("python/bowling", seen_tasks)
        self.assertIn("rust/react", seen_tasks)
        seen_bench = {call.benchmark_id for call in self.judge.calls}
        self.assertEqual(seen_bench, {"aider-polyglot"})


# ── Additivity invariant ──────────────────────────────────────────────


class TestAdditivityInvariant(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-judge-runner-test-")
        self.tmpdir = Path(self._tmp)
        self.run_dir = _make_run_dir(self.tmpdir, [
            {"task_slug": "python-bowling", "attempt_id": "attempt-01-run-001"},
            {"task_slug": "python-bowling", "attempt_id": "attempt-02-run-001"},
        ])

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _snapshot_score_hashes(self) -> Mapping[Path, str]:
        out: dict[Path, str] = {}
        for p in self.run_dir.rglob("score.json"):
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            out[p] = h
        return out

    def test_score_json_byte_identical_pre_and_post(self) -> None:
        # The most load-bearing assertion in this whole subsystem:
        # judge.json is additive; score.json never changes.
        before = self._snapshot_score_hashes()
        run_judge(self.run_dir, _CannedJudge(), _RUBRIC)
        after = self._snapshot_score_hashes()
        self.assertEqual(before, after)

    def test_mutating_judge_raises(self) -> None:
        with self.assertRaises(ScoreJsonMutatedError):
            run_judge(self.run_dir, _ScoreMutatingJudge(), _RUBRIC)

    def test_mutating_then_raising_judge_raises_score_mutated(self) -> None:
        # Peer-reviewed gap (2026-05-20): the guard must run on the
        # exception path too. A judge that mutates score.json and then
        # raises must NOT be silently swallowed as a per-attempt
        # failure — the invariant violation is the more serious bug
        # and takes precedence. Without this test, the runner would
        # record an isolated failure and continue.
        with self.assertRaises(ScoreJsonMutatedError):
            run_judge(self.run_dir, _MutateThenRaiseJudge(), _RUBRIC)

    def test_mutating_then_raising_check_runs_before_failure_record(self) -> None:
        # And specifically: the guard fires BEFORE the runner records
        # the rate() exception. We can prove this indirectly by
        # confirming that ScoreJsonMutatedError surfaces (not the
        # RuntimeError from rate, not a normal stats summary).
        try:
            run_judge(self.run_dir, _MutateThenRaiseJudge(), _RUBRIC)
        except ScoreJsonMutatedError as exc:
            # The guard's error message names the offending judge
            # and the hash transition, so the operator sees the
            # invariant violation, not just "something failed."
            self.assertIn("mutate-then-raise-judge", str(exc))
            self.assertIn("sha256", str(exc).lower())
        else:
            self.fail("expected ScoreJsonMutatedError; no exception raised")


# ── Skip + failure semantics ──────────────────────────────────────────


class TestSkipsAndFailures(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-judge-runner-test-")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_skips_attempt_missing_score_json(self) -> None:
        run_dir = _make_run_dir(self.tmpdir, [
            {"task_slug": "python-bowling", "attempt_id": "attempt-01-run-001"},
            {
                "task_slug": "python-bowling",
                "attempt_id": "attempt-02-run-001",
                "skip_files": {"score"},
            },
        ])
        stats = run_judge(run_dir, _CannedJudge(), _RUBRIC)
        self.assertEqual(stats.attempts_processed, 1)
        self.assertEqual(stats.attempts_skipped, 1)
        skipped_key = next(iter(stats.skip_reasons))
        self.assertIn("attempt-02-run-001", skipped_key)
        self.assertIn("score.json", stats.skip_reasons[skipped_key])

    def test_skips_attempt_missing_diff(self) -> None:
        run_dir = _make_run_dir(self.tmpdir, [
            {
                "task_slug": "python-bowling",
                "attempt_id": "attempt-01-run-001",
                "skip_files": {"diff"},
            },
        ])
        stats = run_judge(run_dir, _CannedJudge(), _RUBRIC)
        self.assertEqual(stats.attempts_processed, 0)
        self.assertEqual(stats.attempts_skipped, 1)

    def test_skips_when_judge_json_already_exists_default(self) -> None:
        run_dir = _make_run_dir(self.tmpdir, [
            {"task_slug": "python-bowling", "attempt_id": "attempt-01-run-001"},
        ])
        # Pre-populate judge.json.
        existing = (
            run_dir / "python-bowling" / "attempt-01-run-001" / "judge.json"
        )
        existing.write_text('{"sentinel": true}\n', encoding="utf-8")
        stats = run_judge(run_dir, _CannedJudge(), _RUBRIC)
        self.assertEqual(stats.attempts_processed, 0)
        self.assertEqual(stats.attempts_skipped, 1)
        # Pre-existing content untouched.
        self.assertEqual(
            json.loads(existing.read_text(encoding="utf-8")),
            {"sentinel": True},
        )

    def test_overwrite_re_rates_existing_judge_json(self) -> None:
        run_dir = _make_run_dir(self.tmpdir, [
            {"task_slug": "python-bowling", "attempt_id": "attempt-01-run-001"},
        ])
        existing = (
            run_dir / "python-bowling" / "attempt-01-run-001" / "judge.json"
        )
        existing.write_text('{"sentinel": true}\n', encoding="utf-8")
        stats = run_judge(run_dir, _CannedJudge(), _RUBRIC, overwrite=True)
        self.assertEqual(stats.attempts_processed, 1)
        payload = json.loads(existing.read_text(encoding="utf-8"))
        self.assertEqual(payload["judge_id"], "canned-judge")

    def test_raising_judge_isolates_failure(self) -> None:
        run_dir = _make_run_dir(self.tmpdir, [
            {"task_slug": "python-bowling", "attempt_id": "attempt-01-run-001"},
            {"task_slug": "rust-react", "attempt_id": "attempt-01-run-001"},
        ])
        stats = run_judge(run_dir, _RaisingJudge(), _RUBRIC)
        # All attempts failed; runner continued past each so the
        # caller can see all failure reasons in one pass.
        self.assertEqual(stats.attempts_processed, 0)
        self.assertEqual(stats.attempts_failed, 2)
        self.assertEqual(len(stats.failure_reasons), 2)
        for reason in stats.failure_reasons.values():
            self.assertIn("RuntimeError", reason)
            self.assertIn("simulated rate failure", reason)


# ── Walk semantics ────────────────────────────────────────────────────


class TestDiscovery(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-judge-runner-test-")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_run_dir_missing_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            run_judge(self.tmpdir / "nope", _CannedJudge(), _RUBRIC)

    def test_ignores_non_attempt_subdirs(self) -> None:
        # Real run-dirs sometimes carry a top-level "report" or
        # similar dir. The walker must only recurse into
        # task-slug/attempt-NN-run-MM.
        run_dir = _make_run_dir(self.tmpdir, [
            {"task_slug": "python-bowling", "attempt_id": "attempt-01-run-001"},
        ])
        # Add a sibling non-attempt dir + a top-level report dir.
        (run_dir / "report").mkdir()
        (run_dir / "report" / "fake.json").write_text("{}\n", encoding="utf-8")
        (run_dir / "python-bowling" / "scratch").mkdir()
        (run_dir / "python-bowling" / "scratch" / "file.txt").write_text(
            "x", encoding="utf-8"
        )
        stats = run_judge(run_dir, _CannedJudge(), _RUBRIC)
        # Still just the one real attempt.
        self.assertEqual(stats.attempts_processed, 1)
        self.assertEqual(stats.attempts_skipped, 0)


# ── Return-type shape ─────────────────────────────────────────────────


class TestRunJudgeStats(unittest.TestCase):
    def test_default_construction(self) -> None:
        # The return type is a frozen dataclass — defaults documented.
        s = RunJudgeStats()
        self.assertEqual(s.attempts_processed, 0)
        self.assertEqual(s.attempts_skipped, 0)
        self.assertEqual(s.attempts_failed, 0)
        self.assertEqual(s.skip_reasons, {})
        self.assertEqual(s.failure_reasons, {})


if __name__ == "__main__":
    unittest.main()
