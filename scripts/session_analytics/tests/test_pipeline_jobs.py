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

    def test_graph_writers_exclude_each_other(self) -> None:
        # Reviewer's repro on #318: a graph rebuild running, then an
        # embed→similar subset — both graph-writing steps entered
        # "running". Kùzu is single-writer: graph and similar exclude
        # each other, standalone and in a subset, either way round.
        gate = threading.Event()
        pj.start(pj.STEP_GRAPH, self._blocking(gate))
        with self.assertRaises(pj.StepBusyError) as cm:
            pj.start(pj.STEP_SIMILAR, lambda: "ok")
        self.assertIn("writing the graph", str(cm.exception))
        runners = {s: (lambda: "ok") for s in pj.STEPS}
        with self.assertRaises(pj.StepBusyError):
            pj.start_all(runners, include_judge=False, only=["embed", "similar"])
        # unrelated steps are not blocked by a graph write
        pj.start(pj.STEP_KPIS, lambda: "ok")
        gate.set()
        for _ in range(100):
            if pj.job_state(pj.STEP_GRAPH)["state"] != "running":
                break
            time.sleep(0.02)
        # and the other way round
        gate2 = threading.Event()
        pj.start(pj.STEP_SIMILAR, self._blocking(gate2))
        with self.assertRaises(pj.StepBusyError):
            pj.start(pj.STEP_GRAPH, lambda: "ok")
        gate2.set()

    def test_run_all_can_run_an_ordered_subset(self) -> None:
        # The Similar tab runs embed + similar (and graph first when the
        # graph is not built); the pipeline's order is kept whatever
        # order the caller named, and an unknown step is refused.
        ran: list[str] = []
        runners = {s: (lambda s=s: ran.append(s) or "ok") for s in pj.STEPS}
        pj.start_all(runners, include_judge=False, only=["similar", "embed", "graph"])
        for _ in range(100):
            if pj.job_state(pj.STEP_ALL)["state"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(ran, ["graph", "embed", "similar"])
        self.assertEqual(pj.job_state(pj.STEP_ALL)["message"], "completed graph, embed, similar")
        self.assertEqual(pj.job_state(pj.STEP_INGEST)["state"], "idle")
        with self.assertRaises(ValueError):
            pj.start_all(runners, include_judge=False, only=["nope"])
        # the full run links benchmark runs right after ingest, then
        # embed and similar between graph and kpis
        self.assertEqual(pj.RUN_ALL_SEQUENCE, ("ingest", "correlate", "graph", "embed", "similar", "kpis"))

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

    def test_a_step_skipped_by_configuration_ends_done_with_the_reason(self) -> None:
        # "Link benchmark runs" with no runs root: Run all carries on and
        # the page says why nothing happened — not a failure.
        def fn() -> str:
            raise pj.StepSkipped("no benchmark runs root configured")

        pj.start(pj.STEP_CORRELATE, fn)
        for _ in range(100):
            if pj.job_state(pj.STEP_CORRELATE)["state"] != "running":
                break
            time.sleep(0.02)
        job = pj.job_state(pj.STEP_CORRELATE)
        self.assertEqual(job["state"], "done")
        self.assertTrue(job["skipped"])
        self.assertIn("no benchmark runs root", job["message"])

    def test_correlate_is_a_step_right_after_ingest(self) -> None:
        self.assertIn(pj.STEP_CORRELATE, pj.STEPS)
        seq = list(pj.RUN_ALL_SEQUENCE)
        self.assertEqual(seq.index(pj.STEP_CORRELATE), seq.index(pj.STEP_INGEST) + 1)
        self.assertLess(seq.index(pj.STEP_CORRELATE), seq.index(pj.STEP_GRAPH))
        self.assertIn(pj.STEP_CORRELATE, pj.STEP_TITLES)
        self.assertIn(pj.STEP_CORRELATE, pj.STEP_BLURBS)

    def test_benchmark_runs_root_states(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        from session_analytics import config as cfgmod

        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_BENCHMARK_RUNS_ROOT: ""}):
            self.assertEqual(pj.benchmark_runs_root(), {"path": "", "configured": False, "is_dir": False})
        d = tempfile.mkdtemp(prefix="cct-sa-runs-")
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_BENCHMARK_RUNS_ROOT: d}):
            self.assertEqual(pj.benchmark_runs_root(), {"path": d, "configured": True, "is_dir": True})
        f = Path(d) / "a-file"
        f.write_text("x")
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_BENCHMARK_RUNS_ROOT: str(f)}):
            self.assertEqual(pj.benchmark_runs_root()["is_dir"], False)


if __name__ == "__main__":
    unittest.main()
