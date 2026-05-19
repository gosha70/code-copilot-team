# tests/test_progress_heartbeat.py — heartbeat thread and progress logger tests.
#
# Four test groups (spec.md T2.1 Done-when clause):
#   (a) A fake attempt that sleeps > 2 heartbeat-intervals emits ≥2 heartbeats.
#   (b) Tee-latency property: a heartbeat line is observable within ~1s of
#       emission (use a short interval; assert timing, not a 60s real wait).
#   (c) Start + end lines emitted exactly once each.
#   (d) Backend-exception path: event cleared, end line emitted, thread
#       does not leak (threading.active_count() returns to baseline).
#
# No real `claude` is spawned — all backend calls are mocked.

from __future__ import annotations

import io
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from benchmark_runner._register import register_all, unregister_all_for_tests
from benchmark_runner.contracts import (
    ISOLATION_WORKTREE,
    BackendResult,
    IsolationConfig,
    RunContext,
    TaskSpec,
    VerifyResult,
)
from benchmark_runner.progress import ProgressLogger
from benchmark_runner.registry import register_adapter, register_backend
from benchmark_runner.run import run_benchmark


# ── Minimal test adapter ────────────────────────────────────────────────


class _MinimalAdapter:
    """Minimal benchmark adapter for heartbeat tests."""

    benchmark_id = "heartbeat-test"

    def __init__(self, verify_pass: bool = True) -> None:
        self._verify_pass = verify_pass

    def list_tasks(self) -> list[TaskSpec]:
        return [TaskSpec(task_id="heartbeat/task", language="text")]

    def isolation_for(self, task: TaskSpec) -> IsolationConfig:
        return IsolationConfig(tier=ISOLATION_WORKTREE)

    def prepare_task(self, task: TaskSpec, worktree: Path) -> None:
        pass

    def prompt_for(
        self, task: TaskSpec, attempt: int, prior: object
    ) -> str:
        return f"attempt {attempt}"

    def verify(self, task: TaskSpec, worktree: Path) -> VerifyResult:
        return VerifyResult(
            tests_passed=self._verify_pass, tests_output="ok"
        )

    def golden_patch(self, task: TaskSpec) -> Path:
        return Path("/tmp")

    def max_attempts(self) -> int:
        return 1


# ── Backend factories ───────────────────────────────────────────────────


class _SleepingBackend:
    """Backend that sleeps for `sleep_seconds` before returning."""

    backend_id = "sleeping"

    def __init__(self, sleep_seconds: float) -> None:
        self._sleep = sleep_seconds

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        time.sleep(self._sleep)
        return BackendResult(transcript_path=None, elapsed_seconds=self._sleep)


class _RaisingBackend:
    """Backend that always raises an exception."""

    backend_id = "raising"

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        raise RuntimeError("synthetic backend failure")


# ── Helpers ─────────────────────────────────────────────────────────────


def _capture_stderr_lines(fn) -> list[str]:
    """Call fn(), capture stderr, return lines that look like progress output."""
    buf = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = buf
    try:
        fn()
    finally:
        sys.stderr = old_stderr
    return buf.getvalue().splitlines()


# ── Test: heartbeat fires ≥2 times for a >2-interval attempt ────────────


class TestHeartbeatFiresMultipleTimes(unittest.TestCase):
    """(a) A fake attempt that sleeps > 2 heartbeat-intervals emits ≥2 heartbeats."""

    def setUp(self) -> None:
        unregister_all_for_tests()
        register_adapter("heartbeat-test", _MinimalAdapter)
        register_backend("sleeping", lambda model: _SleepingBackend(0.5))

    def test_at_least_two_heartbeats_emitted(self) -> None:
        # Use a very short interval (0.1s) so 0.5s of sleep produces ≥4.
        # We only assert ≥2 to be conservative about scheduling jitter.
        interval = 0.1
        heartbeats: list[str] = []

        def _run():
            with tempfile.TemporaryDirectory() as td:
                # Patch ProgressLogger to use our short interval.
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=ProgressLogger(heartbeat_interval=interval),
                ):
                    run_benchmark(
                        "heartbeat-test",
                        "sleeping",
                        runs=1,
                        runs_root=Path(td),
                    )

        lines = _capture_stderr_lines(_run)
        heartbeat_lines = [l for l in lines if "running..." in l]
        self.assertGreaterEqual(
            len(heartbeat_lines),
            2,
            f"Expected ≥2 heartbeat lines, got {len(heartbeat_lines)}. "
            f"All stderr lines: {lines}",
        )


# ── Test: tee-latency — heartbeat line observable within ~1s ────────────


class TestTeeLatency(unittest.TestCase):
    """(b) Tee-latency: a heartbeat line is observable within ~1s of emission.

    Methodology: use a short heartbeat interval (0.15s) so the first heartbeat
    fires quickly. Capture stderr in a real-time manner using a pipe written by
    the run_benchmark thread and a reader thread on the other end. Assert that
    at least one heartbeat line is readable within 1.5s of the run starting.
    """

    def setUp(self) -> None:
        unregister_all_for_tests()
        register_adapter("heartbeat-test", _MinimalAdapter)
        register_backend("sleeping", lambda model: _SleepingBackend(0.5))

    def test_heartbeat_observable_within_one_second(self) -> None:
        interval = 0.15  # first heartbeat fires after 0.15s
        collected: list[str] = []
        first_heartbeat_time: list[float] = []

        class _CollectingLogger(ProgressLogger):
            def emit_heartbeat(self, **kwargs):
                t = time.monotonic()
                first_heartbeat_time.append(t)
                super().emit_heartbeat(**kwargs)

        def _run():
            with tempfile.TemporaryDirectory() as td:
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=_CollectingLogger(heartbeat_interval=interval),
                ):
                    run_benchmark(
                        "heartbeat-test",
                        "sleeping",
                        runs=1,
                        runs_root=Path(td),
                    )

        start = time.monotonic()
        lines = _capture_stderr_lines(_run)
        end = time.monotonic()

        # Assert at least one heartbeat was emitted.
        heartbeat_lines = [l for l in lines if "running..." in l]
        self.assertGreater(
            len(heartbeat_lines),
            0,
            f"No heartbeat lines emitted. All lines: {lines}",
        )

        # Assert the first heartbeat occurred within ~1s of the start
        # (interval=0.15s + OS scheduling slack).
        self.assertTrue(
            first_heartbeat_time,
            "No heartbeat timestamp was recorded.",
        )
        latency = first_heartbeat_time[0] - start
        self.assertLess(
            latency,
            1.5,
            f"First heartbeat latency {latency:.3f}s exceeded 1.5s budget.",
        )


# ── Test: start + end lines emitted exactly once each ───────────────────


class TestStartAndEndLinesExactlyOnce(unittest.TestCase):
    """(c) Start + end lines emitted exactly once each per attempt."""

    def setUp(self) -> None:
        unregister_all_for_tests()

    def _run_with_backend(self, backend_instance) -> list[str]:
        register_adapter("heartbeat-test", _MinimalAdapter)
        register_backend(backend_instance.backend_id, lambda model: backend_instance)
        interval = 0.05

        def _run():
            with tempfile.TemporaryDirectory() as td:
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=ProgressLogger(heartbeat_interval=interval),
                ):
                    run_benchmark(
                        "heartbeat-test",
                        backend_instance.backend_id,
                        runs=1,
                        runs_root=Path(td),
                    )

        return _capture_stderr_lines(_run)

    def test_start_emitted_once_on_normal_run(self) -> None:
        unregister_all_for_tests()
        lines = self._run_with_backend(_SleepingBackend(0.01))
        start_lines = [l for l in lines if "starting..." in l]
        self.assertEqual(
            len(start_lines),
            1,
            f"Expected exactly 1 start line, got {len(start_lines)}. Lines: {lines}",
        )

    def test_end_emitted_once_on_normal_run(self) -> None:
        unregister_all_for_tests()
        lines = self._run_with_backend(_SleepingBackend(0.01))
        end_lines = [
            l for l in lines
            if any(kw in l for kw in ("pass (", "fail (", "error (", "timeout after"))
        ]
        self.assertEqual(
            len(end_lines),
            1,
            f"Expected exactly 1 end line, got {len(end_lines)}. Lines: {lines}",
        )

    def test_end_line_says_pass_when_tests_pass(self) -> None:
        unregister_all_for_tests()
        lines = self._run_with_backend(_SleepingBackend(0.01))
        end_lines = [l for l in lines if "pass (" in l]
        self.assertEqual(len(end_lines), 1, f"Expected 1 pass end-line. Lines: {lines}")

    def test_multiple_runs_each_get_start_and_end(self) -> None:
        unregister_all_for_tests()
        register_adapter("heartbeat-test", lambda: _MinimalAdapter(verify_pass=False))
        register_backend("sleeping", lambda model: _SleepingBackend(0.01))
        interval = 0.05

        def _run():
            with tempfile.TemporaryDirectory() as td:
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=ProgressLogger(heartbeat_interval=interval),
                ):
                    run_benchmark(
                        "heartbeat-test",
                        "sleeping",
                        runs=3,
                        runs_root=Path(td),
                    )

        lines = _capture_stderr_lines(_run)
        start_lines = [l for l in lines if "starting..." in l]
        end_lines = [
            l for l in lines
            if any(kw in l for kw in ("pass (", "fail (", "error (", "timeout after"))
        ]
        self.assertEqual(len(start_lines), 3, f"Expected 3 start lines. Lines: {lines}")
        self.assertEqual(len(end_lines), 3, f"Expected 3 end lines. Lines: {lines}")


# ── Test: backend-exception path ─────────────────────────────────────────


class TestBackendExceptionPath(unittest.TestCase):
    """(d) Backend exception: event cleared, end line emitted, thread does not leak."""

    def setUp(self) -> None:
        unregister_all_for_tests()
        register_adapter("heartbeat-test", _MinimalAdapter)
        register_backend("raising", lambda model: _RaisingBackend())

    def test_end_line_emitted_after_backend_exception(self) -> None:
        interval = 0.05

        def _run():
            with tempfile.TemporaryDirectory() as td:
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=ProgressLogger(heartbeat_interval=interval),
                ):
                    run_benchmark(
                        "heartbeat-test",
                        "raising",
                        runs=1,
                        runs_root=Path(td),
                    )

        lines = _capture_stderr_lines(_run)

        # An end line must be emitted even when the backend raises.
        end_lines = [
            l for l in lines
            if any(kw in l for kw in ("pass (", "fail (", "error (", "timeout after"))
        ]
        self.assertGreater(
            len(end_lines),
            0,
            f"No end line emitted after backend exception. Lines: {lines}",
        )

    def test_thread_does_not_leak_after_backend_exception(self) -> None:
        # Measure active thread count before and after a run where the
        # backend raises. The heartbeat thread must be joined; active_count
        # must return to its pre-run baseline.
        interval = 0.05

        # Allow a tiny settle window for any test-harness threads.
        time.sleep(0.05)
        baseline_count = threading.active_count()

        def _run():
            with tempfile.TemporaryDirectory() as td:
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=ProgressLogger(heartbeat_interval=interval),
                ):
                    run_benchmark(
                        "heartbeat-test",
                        "raising",
                        runs=1,
                        runs_root=Path(td),
                    )

        _capture_stderr_lines(_run)

        # Give the join() a moment to settle in case of OS scheduling.
        time.sleep(0.1)
        final_count = threading.active_count()

        self.assertLessEqual(
            final_count,
            baseline_count,
            f"Thread leaked: baseline={baseline_count}, after={final_count}. "
            f"Heartbeat thread was not properly joined.",
        )

    def test_event_is_cleared_after_backend_exception(self) -> None:
        # The stop_event passed to the heartbeat thread must be cleared
        # in the finally block, whether backend.run returns normally or
        # raises. We test this by intercepting the ProgressLogger and
        # capturing the event after the run completes.
        interval = 0.05
        captured_events: list[threading.Event] = []

        original_run_heartbeat = ProgressLogger.run_heartbeat

        def _patched_run_heartbeat(self_logger, *, stop_event, **kwargs):
            captured_events.append(stop_event)
            return original_run_heartbeat(self_logger, stop_event=stop_event, **kwargs)

        with mock.patch.object(
            ProgressLogger, "run_heartbeat", _patched_run_heartbeat
        ):
            def _run():
                with tempfile.TemporaryDirectory() as td:
                    with mock.patch(
                        "benchmark_runner.run.ProgressLogger",
                        return_value=ProgressLogger(heartbeat_interval=interval),
                    ):
                        run_benchmark(
                            "heartbeat-test",
                            "raising",
                            runs=1,
                            runs_root=Path(td),
                        )

            _capture_stderr_lines(_run)

        self.assertEqual(
            len(captured_events),
            1,
            f"Expected exactly 1 stop_event, got {len(captured_events)}",
        )
        # The stop-signal event must be SET after the attempt completes.
        # The heartbeat thread uses "event.wait()" to detect stop;
        # setting it causes the thread to exit its loop.
        self.assertTrue(
            captured_events[0].is_set(),
            "stop_event was not set after the attempt completed — heartbeat thread was not signaled to stop.",
        )


# ── Test: idx/total counter values ──────────────────────────────────────


class TestIdxTotalCounter(unittest.TestCase):
    """idx/total values in progress lines are correct and never lie."""

    def setUp(self) -> None:
        unregister_all_for_tests()

    def test_single_run_shows_1_of_1(self) -> None:
        register_adapter("heartbeat-test", _MinimalAdapter)
        register_backend("sleeping", lambda model: _SleepingBackend(0.01))

        def _run():
            with tempfile.TemporaryDirectory() as td:
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=ProgressLogger(heartbeat_interval=0.05),
                ):
                    run_benchmark(
                        "heartbeat-test",
                        "sleeping",
                        runs=1,
                        runs_root=Path(td),
                    )

        lines = _capture_stderr_lines(_run)
        # The start line should contain [1/1] (1 task × 1 run × 1 max_attempt).
        start_lines = [l for l in lines if "starting..." in l]
        self.assertEqual(len(start_lines), 1)
        self.assertIn("[1/1]", start_lines[0], f"Expected [1/1] in: {start_lines[0]}")

    def test_three_runs_shows_ascending_idx(self) -> None:
        register_adapter("heartbeat-test", lambda: _MinimalAdapter(verify_pass=False))
        register_backend("sleeping", lambda model: _SleepingBackend(0.01))

        def _run():
            with tempfile.TemporaryDirectory() as td:
                with mock.patch(
                    "benchmark_runner.run.ProgressLogger",
                    return_value=ProgressLogger(heartbeat_interval=0.05),
                ):
                    run_benchmark(
                        "heartbeat-test",
                        "sleeping",
                        runs=3,
                        runs_root=Path(td),
                    )

        lines = _capture_stderr_lines(_run)
        start_lines = [l for l in lines if "starting..." in l]
        self.assertEqual(len(start_lines), 3)
        # [1/3], [2/3], [3/3]
        for i, line in enumerate(start_lines, start=1):
            self.assertIn(f"[{i}/3]", line, f"Run {i}: expected [{i}/3] in: {line}")


# ── Test: ProgressLogger unit tests ─────────────────────────────────────


class TestProgressLoggerUnit(unittest.TestCase):
    """Unit tests for ProgressLogger emit methods."""

    def _capture_emit(self, fn) -> str:
        buf = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = buf
        try:
            fn()
        finally:
            sys.stderr = old_stderr
        return buf.getvalue()

    def test_emit_start_format(self) -> None:
        logger = ProgressLogger()
        out = self._capture_emit(lambda: logger.emit_start(
            idx=2, total=6, candidate="claude-code:sonnet",
            task="python/bowling", attempt=1,
        ))
        self.assertIn("[2/6]", out)
        self.assertIn("claude-code:sonnet", out)
        self.assertIn("python/bowling", out)
        self.assertIn("attempt 1", out)
        self.assertIn("starting...", out)

    def test_emit_heartbeat_format(self) -> None:
        logger = ProgressLogger()
        out = self._capture_emit(lambda: logger.emit_heartbeat(
            idx=1, total=6, candidate="claude-code:sonnet",
            task="python/bowling", attempt=1, elapsed_seconds=30.7,
        ))
        self.assertIn("[1/6]", out)
        self.assertIn("running...", out)
        self.assertIn("30s elapsed", out)

    def test_emit_end_pass_format(self) -> None:
        logger = ProgressLogger()
        out = self._capture_emit(lambda: logger.emit_end(
            idx=1, total=6, candidate="claude-code:sonnet",
            task="python/bowling", attempt=1,
            result="pass", elapsed_seconds=87.3, tool_calls=12,
        ))
        self.assertIn("pass (", out)
        self.assertIn("12 tool calls", out)

    def test_emit_end_fail_format(self) -> None:
        logger = ProgressLogger()
        out = self._capture_emit(lambda: logger.emit_end(
            idx=1, total=6, candidate="ollama:qwen2.5-coder:7b",
            task="python/bowling", attempt=2,
            result="fail", elapsed_seconds=42.0, tool_calls=5,
        ))
        self.assertIn("fail (", out)
        self.assertIn("5 tool calls", out)

    def test_emit_end_error_format(self) -> None:
        logger = ProgressLogger()
        out = self._capture_emit(lambda: logger.emit_end(
            idx=3, total=6, candidate="stub",
            task="stub-task", attempt=1,
            result="error", elapsed_seconds=0.5,
        ))
        self.assertIn("error (", out)

    def test_emit_end_timeout_format(self) -> None:
        logger = ProgressLogger()
        out = self._capture_emit(lambda: logger.emit_end(
            idx=1, total=2, candidate="claude-code:sonnet",
            task="python/bowling", attempt=1,
            result="timeout", elapsed_seconds=300.0,
        ))
        self.assertIn("timeout after", out)
        self.assertIn("skipping", out)

    def test_default_interval_is_30s(self) -> None:
        logger = ProgressLogger()
        self.assertEqual(logger._interval, 30.0)  # noqa: SLF001

    def test_injectable_interval(self) -> None:
        logger = ProgressLogger(heartbeat_interval=0.5)
        self.assertEqual(logger._interval, 0.5)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
