# Tests for session_analytics.watch.run_watch (E6 polling core, issue #89).
#
# Pure unit tests: no real time.sleep, no real DB, no real signals — every
# dependency (`ingest_fn`, `sleep_fn`, `should_stop`) is a plain fake.

from __future__ import annotations

import argparse
import unittest

from session_analytics.watch import run_watch


class TestRunWatch(unittest.TestCase):
    def test_iterations_runs_exact_cycle_count(self) -> None:
        calls = []
        result = run_watch(lambda: calls.append(1), 5, iterations=3, sleep_fn=lambda s: None)
        self.assertEqual(result, 3)
        self.assertEqual(len(calls), 3)

    def test_exception_in_one_cycle_does_not_stop_the_loop(self) -> None:
        calls = []

        def ingest_fn() -> None:
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("transient failure")

        result = run_watch(ingest_fn, 5, iterations=3, sleep_fn=lambda s: None)
        self.assertEqual(result, 3)
        self.assertEqual(len(calls), 3)

    def test_sleep_fn_called_with_interval_every_cycle_when_bounded(self) -> None:
        sleeps = []
        result = run_watch(
            lambda: None, 7, iterations=4, sleep_fn=lambda s: sleeps.append(s)
        )
        self.assertEqual(result, 4)
        # Bounded (iterations, no should_stop) runs: sleep_fn is called once
        # per cycle, including the last — exactly N times for N iterations.
        self.assertEqual(sleeps, [7, 7, 7, 7])

    def test_should_stop_ends_the_loop_at_expected_cycle_count(self) -> None:
        counter = [0]

        def ingest_fn() -> None:
            counter[0] += 1

        def should_stop() -> bool:
            return counter[0] >= 3

        result = run_watch(
            ingest_fn, 1, iterations=None, sleep_fn=lambda s: None, should_stop=should_stop
        )
        self.assertEqual(result, 3)
        self.assertEqual(counter[0], 3)

    def test_should_stop_skips_the_trailing_sleep(self) -> None:
        counter = [0]
        sleeps = []

        def ingest_fn() -> None:
            counter[0] += 1

        def should_stop() -> bool:
            return counter[0] >= 3

        run_watch(
            ingest_fn,
            1,
            iterations=None,
            sleep_fn=lambda s: sleeps.append(s),
            should_stop=should_stop,
        )
        # 3 cycles ran, but the sleep after the final (stopping) cycle is
        # skipped — only 2 sleeps for 3 cycles.
        self.assertEqual(len(sleeps), 2)

    def test_ingest_runs_before_the_first_sleep(self) -> None:
        events = []
        run_watch(
            lambda: events.append("ingest"),
            9,
            iterations=2,
            sleep_fn=lambda s: events.append("sleep"),
        )
        self.assertEqual(events[:2], ["ingest", "sleep"])

    def test_fail_fast_first_propagates_a_first_cycle_error(self) -> None:
        # A setup/config failure on cycle 0 must abort (not be swallowed).
        def ingest_fn() -> None:
            raise RuntimeError("unreachable DB")

        with self.assertRaises(RuntimeError):
            run_watch(
                ingest_fn, 1, iterations=3, sleep_fn=lambda s: None, fail_fast_first=True
            )

    def test_fail_fast_first_still_resilient_after_first_cycle(self) -> None:
        # Cycle 0 succeeds; a later transient failure is caught, loop continues.
        calls = []

        def ingest_fn() -> None:
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("transient failure")

        result = run_watch(
            ingest_fn, 1, iterations=3, sleep_fn=lambda s: None, fail_fast_first=True
        )
        self.assertEqual(result, 3)
        self.assertEqual(len(calls), 3)


class TestWatchCliWiring(unittest.TestCase):
    def test_watch_subcommand_registered(self) -> None:
        from session_analytics.cli import _build_parser, _HANDLERS

        self.assertIn("watch", _HANDLERS)
        parser = _build_parser()
        args = parser.parse_args(["watch", "--interval", "5", "--copilots", "claude-code"])
        self.assertEqual(args.subcommand, "watch")
        self.assertEqual(args.interval, 5)
        self.assertEqual(args.copilots, ["claude-code"])

    def test_watch_rejects_sub_second_interval(self) -> None:
        # --interval < 1 exits EXIT_USAGE before any setup / ingest work.
        from session_analytics import constants as C
        from session_analytics.cli import _cmd_watch

        for bad in (0, -5):
            args = argparse.Namespace(interval=bad, dsn=None, copilots=None)
            self.assertEqual(_cmd_watch(args), C.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
