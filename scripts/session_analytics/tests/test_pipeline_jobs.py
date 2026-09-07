# pipeline_jobs: one running copy of a step at a time, whichever path
# starts it (a single step, or a run of all steps).

from __future__ import annotations

import threading
import time
import unittest

from session_analytics import pipeline_jobs as pj


class TestSingleFlight(unittest.TestCase):
    def setUp(self) -> None:
        pj._jobs.clear()
        self.addCleanup(pj._jobs.clear)

    def _blocking(self, gate: threading.Event):
        def fn() -> str:
            gate.wait(5)
            return "done"
        return fn

    def test_run_all_is_refused_while_a_step_it_would_run_is_running(self) -> None:
        # Reviewer's repro on #316: a standalone judge running, then Run
        # all with the judge included started a SECOND judge beside it
        # (duplicate model calls, two writers) and overwrote its status.
        gate = threading.Event()
        pj.start(pj.STEP_JUDGE, self._blocking(gate))
        runners = {s: (lambda: "ok") for s in pj.STEPS}
        with self.assertRaises(pj.StepBusyError):
            pj.start_all(runners, include_judge=True)
        # Without the judge, run-all does not touch it and may proceed.
        pj.start_all(runners, include_judge=False)
        for _ in range(100):
            if pj.job_state(pj.STEP_ALL)["state"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(pj.job_state(pj.STEP_ALL)["state"], "done")
        self.assertEqual(pj.job_state(pj.STEP_JUDGE)["state"], "running")
        gate.set()

    def test_single_step_is_refused_while_run_all_is_in_progress(self) -> None:
        gate = threading.Event()
        runners = {pj.STEP_INGEST: self._blocking(gate)}
        pj.start_all(runners, include_judge=False)
        time.sleep(0.05)
        with self.assertRaises(pj.StepBusyError):
            pj.start(pj.STEP_KPIS, lambda: "ok")
        with self.assertRaises(pj.StepBusyError):
            pj.start_all(runners, include_judge=False)
        gate.set()
        for _ in range(100):
            if pj.job_state(pj.STEP_ALL)["state"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(pj.job_state(pj.STEP_INGEST)["state"], "done")
        # Free again once the run-all has finished.
        pj.start(pj.STEP_KPIS, lambda: "ok")

    def test_progress_rides_on_the_running_job_and_survives_completion(self) -> None:
        gate = threading.Event()

        def fn() -> str:
            pj.set_progress(pj.STEP_JUDGE, {"labeled": 1, "total": 2})
            gate.wait(5)
            return "done"

        pj.start(pj.STEP_JUDGE, fn)
        time.sleep(0.05)
        self.assertEqual(pj.job_state(pj.STEP_JUDGE)["progress"], {"labeled": 1, "total": 2})
        gate.set()
        for _ in range(100):
            if pj.job_state(pj.STEP_JUDGE)["state"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(pj.job_state(pj.STEP_JUDGE)["progress"], {"labeled": 1, "total": 2})


if __name__ == "__main__":
    unittest.main()
