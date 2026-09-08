# API tests via FastAPI TestClient. Run only when fastapi is importable (CI
# installs it for the API job); skips are logged, never silently passed.

from __future__ import annotations

import importlib.util
import json
import tempfile
import time as _time
import unittest
from pathlib import Path
from unittest import mock

from session_analytics import constants as C
from session_analytics.config import ENV_NOISE_MIN_DURATION
from session_analytics.ingest.pipeline import ingest
from session_analytics.routing_calibration import GATE_IDS

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_FASTAPI = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestApi(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        # Register the full set (adapters + judges) so /api/config reflects the
        # real judge backends; create_app also calls register_all idempotently.
        from session_analytics._register import register_all
        register_all()
        # The fixture session is 5 seconds long, which the default noise
        # rule (#307) would hide from every list and aggregate. Turn the
        # duration rule off for this class; the turn-count and path rules
        # stay on, and test_sessions_exclude_noise_by_default exercises
        # them against an inserted probe.
        patcher = mock.patch.dict("os.environ", {ENV_NOISE_MIN_DURATION: "0"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        # #103: point at an allowlisted host. TestClient defaults to
        # `Host: testserver`, which the Host guard (correctly) rejects —
        # `testserver` is deliberately NOT in the shipped allowlist.
        self.client = TestClient(create_app(self.dsn), base_url="http://127.0.0.1:8765")

    def test_health(self) -> None:
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_judge_models_answers_even_when_ollama_is_down(self) -> None:
        # Unreachable is an answer, never a 500: the Analysis page decides
        # what to offer from `reachable`. (Regression: the handler read the
        # Ollama URL off the wrong config object and crashed every call.)
        r = self.client.get("/api/judge/models")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("reachable", body)
        self.assertIsInstance(body["models"], list)
        self.assertTrue(body["url"].startswith("http"))

    # ── session-level analysis (#65 Phase 1) ──────────────────────────
    def _register_fake_judge(self, text: str, *, down: bool = False) -> None:
        from session_analytics.judge.contracts import JudgeTransportError
        from session_analytics.judge.registry import register_judge

        class _Fake:
            judge_id = "fake"

            def __init__(self, model: str = "") -> None:
                # Like the real backends: a blank model means the
                # backend's own default, and the label reports THAT.
                self._model = model or "fake-default"

            def rate_turn(self, ctx, rubric):  # pragma: no cover
                raise NotImplementedError

            def complete(self, prompt: str, *, timeout: int = 120) -> str:
                if down:
                    raise JudgeTransportError("connection refused")
                return text

        register_judge("fake", _Fake)

    def _session_id(self) -> int:
        return self.client.get("/api/sessions").json()["sessions"][0]["id"]

    def test_session_analysis_absent_then_generated(self) -> None:
        self._register_fake_judge(json.dumps({
            "summary": "ok", "findings": [{
                "category": "hooks", "severity": "low", "title": "t",
                "evidence_turns": [1], "explanation": "e", "recommendation": "r",
                "config_change": None,
            }],
        }))
        sid = self._session_id()
        r = self.client.get(f"/api/sessions/{sid}/analysis")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body["kinds"]), set(C.ANALYSIS_KINDS))
        self.assertTrue(all(v is None for v in body["kinds"].values()))
        self.assertEqual(body["archive"]["archived_turns"], 0)
        self.assertEqual(body["archive"]["turns"], 6)

        r = self.client.post(
            f"/api/sessions/{sid}/analysis/tuning", json={"judge": "fake:x"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        row = r.json()
        self.assertEqual(row["parse_status"], "ok")
        self.assertEqual(row["judge"], "fake:x")
        self.assertEqual(row["result"]["findings"][0]["category"], "hooks")
        self.assertEqual(row["transcript_source"], C.TRANSCRIPT_SOURCE_PREVIEW)

        # A judge given without a model is labelled with the model the
        # backend will actually call, never "(default)".
        r = self.client.post(
            f"/api/sessions/{sid}/analysis/efficiency", json={"judge": "fake"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["judge"], "fake:fake-default")

        # Persisted: the GET now carries it.
        body = self.client.get(f"/api/sessions/{sid}/analysis").json()
        self.assertEqual(body["kinds"]["tuning"]["parse_status"], "ok")

    def test_session_analysis_bad_kind_and_unknown_judge(self) -> None:
        sid = self._session_id()
        self.assertEqual(
            self.client.post(f"/api/sessions/{sid}/analysis/vibes").status_code, 400
        )
        r = self.client.post(
            f"/api/sessions/{sid}/analysis/tuning", json={"judge": "nope:x"}
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            self.client.post("/api/sessions/99999/analysis/tuning").status_code, 404
        )
        # An explicit judge must not skip the existence check: a paid
        # backend would otherwise be invoked before the foreign key fails.
        self._register_fake_judge("{}")
        r = self.client.post(
            "/api/sessions/99999/analysis/tuning", json={"judge": "fake:x"}
        )
        self.assertEqual(r.status_code, 404)

    def test_session_analysis_backend_down_is_503_with_guidance(self) -> None:
        self._register_fake_judge("", down=True)
        sid = self._session_id()
        r = self.client.post(
            f"/api/sessions/{sid}/analysis/coaching", json={"judge": "fake:x"}
        )
        self.assertEqual(r.status_code, 503)
        detail = r.json()["detail"]
        self.assertEqual(detail["prerequisite"], "judge")
        self.assertIn("fake:x", detail["error"])
        self.assertIn("run it again", detail["guidance"])

    def test_session_detail_carries_latency(self) -> None:
        sid = self._session_id()
        d = self.client.get(f"/api/sessions/{sid}").json()
        self.assertIn("latency", d)
        self.assertIn("latency_seconds", d["turns"][1])
        self.assertIsNone(d["turns"][0]["content"])

    def test_dashboard_kpis(self) -> None:
        r = self.client.get("/api/dashboard/kpis")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["totals"]["sessions"], 1)
        # E5: total cost + cost-per-session always present, NULL-safe (this
        # fixture ingests with no pricing kwarg → 0.0, never an error).
        self.assertEqual(r.json()["totals"]["total_cost_usd"], 0.0)
        self.assertEqual(r.json()["totals"]["cost_per_session"], 0.0)

    def test_dashboard_developers(self) -> None:
        # E1 (#65). The fixture is one machine, so this is also the
        # single-developer shape every real store returns today.
        r = self.client.get("/api/dashboard/developers")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["developer_count"], 1)
        self.assertTrue(body["is_single_developer"])
        self.assertEqual(len(body["developers"]), 1)
        self.assertIn("cost_usd", body["developers"][0])

    def test_dashboard_phase_process(self) -> None:
        # #301: descriptive only. The fixture store has no Pi source
        # root, so this also pins the "nothing to read" answer being
        # explicit rather than an empty-but-healthy-looking payload.
        r = self.client.get("/api/dashboard/phase-process")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("retention_cap", body)
        self.assertIn("absence_note", body)
        self.assertEqual(body["projects_with_history"], 0)
        # No grading vocabulary may appear in this payload at all.
        blob = json.dumps(body).lower()
        for banned in ("compliance", "violation", "conformance"):
            self.assertNotIn(banned, blob)
    def test_labels_correlation_and_predict_endpoints(self) -> None:
        # E10 label correlation + E4 predictions (#65). The fixture store
        # is tiny, so this also pins the small-sample refusals reaching
        # the wire: coverage present, estimates withheld, not faked.
        r = self.client.get("/api/labels/correlation")
        self.assertEqual(r.status_code, 200)
        self.assertIn("coverage", r.json())

        r = self.client.get("/api/labels/nonexistent_label/traces")
        self.assertEqual(r.status_code, 404)

        r = self.client.get("/api/predict/effort")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("base rate", body["basis"])
        self.assertFalse(body["turns"]["sufficient"])   # one fixture session
        self.assertIsNone(body["turns"]["median"])

        r = self.client.get("/api/predict/outcome")
        self.assertEqual(r.status_code, 200)
        self.assertIn("sessions_with_outcome", r.json())

    def test_dashboard_cost(self) -> None:
        r = self.client.get("/api/dashboard/cost")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("by_phase", body)
        self.assertIn("by_sentiment", body)

    def test_dashboard_benchmark(self) -> None:
        # E9 (#91): the correlation summary endpoint. Fresh ingest → nothing
        # linked yet; after link_benchmark_run the counters move.
        r = self.client.get("/api/dashboard/benchmark")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["sessions_total"], 1)
        self.assertEqual(body["sessions_linked"], 0)
        self.assertEqual(body["sessions_unlinked"], 1)
        self.assertEqual(body["distinct_benchmark_attempts"], 0)
        self.assertEqual(body["by_result"], [])  # E9 outcomes (#92): merged payload

        from session_analytics import correlate as cor
        from session_analytics.relational.db import Database
        from session_analytics.relational.store import (
            link_benchmark_run,
            upsert_benchmark_result,
        )

        db = Database.connect(self.dsn)
        try:
            sid = db.query_one(
                "SELECT session_id FROM copilot_session WHERE copilot = ?",
                (C.COPILOT_CLAUDE_CODE,),
            )[0]
            self.assertTrue(
                link_benchmark_run(db, C.COPILOT_CLAUDE_CODE, sid, "/runs/x/attempt-01")
            )
            upsert_benchmark_result(
                db, "/runs/x/attempt-01", cor.Score(result="pass", tests_passed=True),
                copilot=C.COPILOT_CLAUDE_CODE, session_id=sid, ingested_at="x",
            )
            # Store helpers no longer commit (caller-owned transaction, #92) —
            # commit here so the API's own connection sees the rows.
            db.commit()
        finally:
            db.close()

        r = self.client.get("/api/dashboard/benchmark")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["sessions_linked"], 1)
        self.assertEqual(body["sessions_unlinked"], 0)
        self.assertEqual(body["distinct_benchmark_attempts"], 1)
        self.assertEqual(len(body["by_result"]), 1)
        self.assertEqual(body["by_result"][0]["result"], "pass")
        self.assertEqual(body["by_result"][0]["linked_sessions"], 1)

    def test_sessions_list_and_detail(self) -> None:
        r = self.client.get("/api/sessions")
        self.assertEqual(r.status_code, 200)
        sessions = r.json()["sessions"]
        self.assertEqual(len(sessions), 1)
        sid = sessions[0]["id"]
        self.assertIn("cost_usd", sessions[0])  # E5: present even when NULL

        r = self.client.get(f"/api/sessions/{sid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["turns"]), 6)
        self.assertIn("cost_usd", r.json())

        self.assertEqual(self.client.get("/api/sessions/99999").status_code, 404)

    def _insert_probe(self) -> int:
        from session_analytics.relational.db import Database

        conn = Database.connect(self.dsn)
        try:
            conn.execute(
                "INSERT INTO copilot_session (copilot, session_id, project_path, turn_count, "
                "tool_call_count, error_count, duration_seconds, started_at, developer_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (C.COPILOT_CLAUDE_CODE, "probe-1", "/private/var/folders/x/cct-probe.q",
                 2, 0, 0, 4, "2026-09-01T00:00:00Z", C.DEFAULT_DEVELOPER_ID),
            )
            conn.commit()
            return int(conn.query_one("SELECT MAX(id) FROM copilot_session")[0])
        finally:
            conn.close()

    def test_sessions_exclude_noise_by_default(self) -> None:
        # #307: a probe session is hidden from the list, counted in
        # excluded_noise, shown with include_noise=1, and still reachable
        # by id — the filter is for lists and aggregates only.
        probe_id = self._insert_probe()
        body = self.client.get("/api/sessions").json()
        self.assertEqual([s["id"] for s in body["sessions"] if s["id"] == probe_id], [])
        self.assertEqual(body["excluded_noise"], 1)
        self.assertFalse(body["include_noise"])
        shown = self.client.get("/api/sessions", params={"include_noise": "true"}).json()
        self.assertIn(probe_id, [s["id"] for s in shown["sessions"]])
        self.assertEqual(self.client.get(f"/api/sessions/{probe_id}").status_code, 200)
        # Aggregates agree with the list.
        kpis = self.client.get("/api/dashboard/kpis").json()["totals"]
        self.assertEqual(kpis["sessions"], 1)
        self.assertEqual(kpis["excluded_noise"], 1)
        status = self.client.get("/api/pipeline/status").json()
        self.assertEqual((status["counts"]["sessions"], status["counts"]["excluded_noise"]), (1, 1))
        effort = self.client.get("/api/predict/effort").json()
        self.assertEqual(effort["sessions"], 1)
        # Every other dashboard source excludes the same session: give the
        # probe a developer, an error, a priced turn and a label, and none
        # of them may surface.
        from session_analytics.relational.db import Database

        conn = Database.connect(self.dsn)
        try:
            conn.execute(
                "UPDATE copilot_session SET developer_id = ? WHERE id = ?", ("probe-dev", probe_id)
            )
            conn.execute(
                "INSERT INTO copilot_error (session_id, error_type, tool_name, error_message) "
                "VALUES (?, ?, ?, ?)", (probe_id, "ProbeError", "bash", "boom"),
            )
            conn.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, model, cost_usd) "
                "VALUES (?, ?, ?, ?, ?)", (probe_id, 0, C.ROLE_USER, "m", 9.5),
            )
            turn_id = int(conn.query_one("SELECT MAX(id) FROM copilot_turn")[0])
            conn.execute(
                "INSERT INTO heuristic_label (turn_id, rubric_name, sentiment, user_gives_command, "
                "parse_status) VALUES (?, ?, ?, ?, ?)",
                (turn_id, "heuristic-v1", "NEUTRAL", True, "ok"),
            )
            conn.commit()
        finally:
            conn.close()
        devs = self.client.get("/api/dashboard/developers").json()
        self.assertNotIn("probe-dev", [d["developer_id"] for d in devs["developers"]])
        errors = self.client.get("/api/resources/recent-errors").json()["errors"]
        self.assertNotIn("ProbeError", [e["error_type"] for e in errors])
        cost = self.client.get("/api/dashboard/cost").json()
        self.assertEqual(sum(p["cost_usd"] for p in cost["by_phase"]), 0.0)
        self.assertEqual(cost["by_sentiment"], [])
        labels = self.client.get("/api/dashboard/labels").json()["labels"]
        self.assertEqual(sum(l["total"] for l in labels), 0)
        # A store with only noise is NOT "done" loading: the probe alone
        # would show "Re-run load sessions" to someone who loaded nothing.
        from session_analytics.relational.db import Database as _Db

        conn = _Db.connect(self.dsn)
        try:
            conn.execute(
                "UPDATE copilot_session SET project_path = ? WHERE id <> ?",
                ("/tmp/cct-probe.demo", probe_id),
            )
            conn.commit()
        finally:
            conn.close()
        status = self.client.get("/api/pipeline/status").json()
        ingest = next(s for s in status["steps"] if s["id"] == "ingest")
        self.assertEqual((status["counts"]["sessions"], status["counts"]["excluded_noise"]), (0, 2))
        self.assertFalse(ingest["done"])

    def test_graph_node_counts_unopenable_store_is_503_with_guidance(self) -> None:
        # A kuzu path that is a directory (a real misconfiguration seen
        # on a host) must answer 503 + guidance, never an unhandled 500:
        # a 500 escapes without CORS headers and the browser reports the
        # whole API as unreachable (F10).
        import importlib.util
        import tempfile

        if importlib.util.find_spec("kuzu") is None:
            self.skipTest("kuzu not installed")
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        client = TestClient(
            create_app(self.dsn, kuzu_path=tempfile.mkdtemp()),
            base_url="http://127.0.0.1:8765",
        )
        r = client.get("/api/graph/node-counts")
        self.assertEqual(r.status_code, 503, r.text)
        detail = r.json()["detail"]
        self.assertEqual(detail["prerequisite"], "graph")
        self.assertIn("CCT_SA_KUZU_PATH", detail["guidance"])

    def test_pipeline_status_says_when_the_store_did_not_answer(self) -> None:
        # Zero counts from an unreachable store are not "0 sessions".
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        good = self.client.get("/api/pipeline/status").json()
        self.assertTrue(good["store_reachable"])
        bad = TestClient(
            create_app("sqlite:////nonexistent-dir/for-sure/x.db"),
            base_url="http://127.0.0.1:8765",
        ).get("/api/pipeline/status").json()
        self.assertFalse(bad["store_reachable"])
        self.assertEqual(bad["counts"]["sessions"], 0)

    def test_judge_runs_and_agreement_over_http(self) -> None:
        # #313: a named run through the API, listed, and compared.
        from session_analytics.judge.registry import register_judge
        from session_analytics.tests.test_judge_validation import _Judge

        register_judge("fakev", lambda model="": _Judge())
        r = self.client.post("/api/analyze", json={"judge": "fakev:x", "limit": 50})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["rubric_name"], "heuristic-v1")
        r = self.client.post("/api/analyze", json={
            "judge": "fakev:x", "limit": 50, "rubric_name": "rerun",
            "only_labelled_by": "heuristic-v1",
        })
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["rubric_name"], r.json()["labeled"]), ("rerun", 4))
        runs = self.client.get("/api/judge/runs").json()
        self.assertEqual([x["name"] for x in runs["rubrics"]], ["heuristic-v1", "rerun"])
        # The funnel counts the packaged rubric's run only — a rerun must
        # not double "Labelled turns".
        self.assertEqual(self.client.get("/api/pipeline/status").json()["counts"]["labels"], 4)
        rep = self.client.get("/api/judge/agreement", params={"a": "heuristic-v1", "b": "rubric:rerun"}).json()
        self.assertEqual(rep["turns_shared"], 4)
        self.assertEqual(len(rep["labels"]), 9)
        self.assertEqual(
            self.client.get("/api/judge/agreement", params={"a": "robot:x", "b": "rerun"}).status_code, 400
        )
        self.assertEqual(
            self.client.post("/api/analyze", json={"judge": "fakev:x", "only_labelled_by": "robot:x"}).status_code, 400
        )

    def test_dashboard_latency(self) -> None:
        r = self.client.get("/api/dashboard/latency")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreater(body["measured_turns"], 0)
        self.assertEqual(body["sessions"], 1)
        self.assertIsNotNone(body["p50"])
        self.assertEqual(body["by_copilot"][0]["copilot"], C.COPILOT_CLAUDE_CODE)
        self.assertIn("basis", body)

    def test_search_endpoint(self) -> None:
        # E10 Slice A (#98): substring search over archived trace text.
        from session_analytics import archive as arch
        from session_analytics.config import ProjectIdRule, ProjectOverride

        r = self.client.get("/api/search", params={"q": "anything"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"], [])  # nothing archived yet

        arch.archive(
            dsn=self.dsn,
            copilots=[C.COPILOT_CLAUDE_CODE],
            root=CLAUDE_CODE_ROOT,
            projects={"demo-project": ProjectOverride(trace_archive=True)},
            project_id_rules=(ProjectIdRule(match="/repo/demo", id="demo-project"),),
            full=True,
        )
        r = self.client.get("/api/search", params={"q": "e", "limit": 3})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertLessEqual(len(body["results"]), 3)
        if body["results"]:
            self.assertIn("snippet", body["results"][0])
            self.assertIn("session_ref", body["results"][0])

        # Empty query → 400, not an empty result set.
        r = self.client.get("/api/search", params={"q": "  "})
        self.assertEqual(r.status_code, 400)

    def test_settings_does_not_leak_dsn(self) -> None:
        r = self.client.get("/api/settings")
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertNotIn(self.dsn, body)  # raw DSN must never be returned
        self.assertEqual(r.json()["dsn_dialect"], "sqlite")

    def test_test_connection_failure_leaks_nothing(self) -> None:
        # #100: the failure payload must be curated constants only — asserted
        # over the RAW response body, so a leak through any field is caught.
        marker = "s3cret-host.example.internal"
        r = self.client.post(
            "/api/settings/test-connection",
            json={"dsn": f"mysql://user:pw@{marker}:3306/db"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(marker, r.text)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn(body["error_code"], C.PROBE_ERROR_MESSAGES)
        self.assertEqual(body["error"], C.PROBE_ERROR_MESSAGES[body["error_code"]])

    def test_test_connection(self) -> None:
        r = self.client.post("/api/settings/test-connection", json={"dsn": self.dsn})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["sessions"], 1)

    def test_pipeline_sessions_lists_what_load_would_read_and_the_pick_narrows_it(self) -> None:
        # The Analysis page's selection table (the owner's per-session
        # selection requirement): what is under the source roots, newest
        # first, with sizes and loaded state; then the same body narrows
        # what the ingest step reads.
        import time

        from session_analytics.config import ENV_SOURCE_PREFIX

        with mock.patch.dict(
            "os.environ", {ENV_SOURCE_PREFIX + "CLAUDE_CODE": str(CLAUDE_CODE_ROOT)}
        ):
            listing = self.client.get("/api/pipeline/sessions", params={"copilot": "claude-code"})
            self.assertEqual(listing.status_code, 200)
            body = listing.json()
            self.assertEqual(body["total"], 1)
            self.assertTrue(body["sessions"][0]["loaded"])  # setUp ingested it
            self.assertGreater(body["total_bytes"], 0)
            sid = body["sessions"][0]["session_id"]
            self.assertEqual(
                self.client.get("/api/pipeline/sessions", params={"since": "2100-01-01"}).json()["total"], 0
            )
            self.assertEqual(
                self.client.get("/api/pipeline/sessions", params={"since": "soon"}).status_code, 400
            )
            # An ingest narrowed to an id that is not there loads nothing and
            # says why; the pick of the real id loads it.
            messages = []
            for pick in ("nope", sid):
                r = self.client.post(
                    "/api/pipeline/run/ingest",
                    json={"load": {"copilots": ["claude-code"], "session_ids": [pick]}},
                )
                self.assertEqual(r.status_code, 200, r.text)
                for _ in range(100):
                    job = self.client.get("/api/pipeline/status").json()["steps"][0]["job"]
                    if job["state"] != "running":
                        break
                    time.sleep(0.05)
                self.assertEqual(job["state"], "done", job)
                messages.append(job["message"])
            self.assertIn("ingested 0 sessions", messages[0])
            self.assertIn("1 outside the selection", messages[0])
            self.assertIn("1 already up to date", messages[1])

    def test_judge_step_runs_as_a_job_with_progress_and_says_why_it_failed(self) -> None:
        # The judge used to run inside the request with nothing to show
        # until it returned. It is now a pipeline job: every turn is
        # written as it arrives, the status carries done/total, ok/failed
        # and the last failure's reason, and the final message says what
        # was labelled with which judge.
        import time

        from session_analytics.judge.contracts import PARSE_BACKEND_ERROR, TurnLabels
        from session_analytics.judge.registry import register_judge

        class _Flaky:
            judge_id = "flaky"

            def __init__(self, model: str = "") -> None:
                self._model = model or "m"

            def rate_turn(self, ctx, rubric):
                # user turns answer; assistant turns fail like a dead backend
                if ctx.role == "user":
                    return TurnLabels(
                        bool_labels={l: False for l in rubric.bool_labels}, sentiment="NEUTRAL",
                        interaction_quality=3, judge_id=self.judge_id, judge_model=self._model,
                    )
                return TurnLabels(
                    bool_labels={l: None for l in rubric.bool_labels}, sentiment=None,
                    interaction_quality=None, parse_status=PARSE_BACKEND_ERROR,
                    judge_id=self.judge_id, judge_model=self._model,
                    metadata={"error": "HTTP 404: model 'm' not found"},
                )

            def complete(self, prompt, *, timeout=120):  # pragma: no cover
                raise NotImplementedError

        register_judge("flaky", _Flaky)
        self.assertEqual(
            self.client.post("/api/pipeline/run/judge", json={"judge": {"judge": "nope:x"}}).status_code,
            400,
        )
        r = self.client.post("/api/pipeline/run/judge", json={"judge": {"judge": "flaky:m", "limit": 4}})
        self.assertEqual(r.status_code, 200, r.text)
        for _ in range(200):
            job = next(x for x in self.client.get("/api/pipeline/status").json()["steps"] if x["id"] == "judge")["job"]
            if job["state"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["state"], "done", job)
        prog = job["progress"]
        self.assertEqual((prog["total"], prog["labeled"]), (4, 4))
        self.assertEqual(prog["parse_ok"] + prog["parse_failed"], 4)
        self.assertGreater(prog["parse_failed"], 0)
        self.assertEqual(prog["last_error"], "HTTP 404: model 'm' not found")
        self.assertEqual(prog["judge"], "flaky:m")
        self.assertIn("with flaky:m", job["message"])
        self.assertIn("of 4 turns", job["message"])
        self.assertIn("last: HTTP 404", job["message"])
        # Failed rows are written too (attempted, not labelled), so the
        # funnel can say "N judge attempts failed" with a reason on hand.
        counts = self.client.get("/api/pipeline/status").json()["counts"]
        self.assertEqual(counts["labels"] + counts["label_failures"], 4)
        # The configured judge is reported once, for both pages to show.
        conf = self.client.get("/api/judge/models").json()["configured"]
        self.assertIn(conf["source"], ("settings", "packaged default"))
        self.assertTrue(conf["spec"])

    def test_benchmark_payload_names_the_runs_root_and_the_link_step_runs_it(self) -> None:
        # The Benchmark page: with no runs root the page says so; with one,
        # "Link benchmark runs" is the correlate step, run from the page.
        from session_analytics import config as cfgmod
        from session_analytics import pipeline_jobs as pj

        pj._jobs.clear()
        self.addCleanup(pj._jobs.clear)
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_BENCHMARK_RUNS_ROOT: ""}):
            body = self.client.get("/api/dashboard/benchmark").json()
            self.assertEqual(body["runs_root"], {"path": "", "configured": False, "is_dir": False})
            self.assertEqual(body["link_job"]["state"], "idle")
            steps = {s["id"]: s for s in self.client.get("/api/pipeline/status").json()["steps"]}
            self.assertIn("No runs root configured", steps["correlate"]["blurb"])
            self.assertFalse(steps["correlate"]["done"])
            self.assertIn(cfgmod.ENV_BENCHMARK_RUNS_ROOT, [f["key"] for f in self.client.get("/api/config").json()["fields"]])
            # Skipped by configuration: done, not failed, with the reason.
            self.assertEqual(self.client.post("/api/pipeline/run/correlate", json={}).status_code, 200)
            for _ in range(100):
                if pj.job_state(pj.STEP_CORRELATE)["state"] != "running":
                    break
                _time.sleep(0.02)
            job = pj.job_state(pj.STEP_CORRELATE)
            self.assertEqual((job["state"], job.get("skipped")), ("done", True))

        # A runs root with one record for the fixture session: linked.
        native = self.client.get("/api/sessions").json()["sessions"][0]["session_id"]
        root = Path(tempfile.mkdtemp(prefix="cct-sa-runs-"))
        attempt = root / "run-a" / "task" / "attempt-01"
        attempt.mkdir(parents=True)
        (attempt / C.RUN_RECORD_FILENAME).write_text(json.dumps(
            {"backend_id": "claude-code", "backend": {"metadata": {"session_id": native}}}
        ))
        (attempt / C.SCORE_FILENAME).write_text(json.dumps({
            "schema_version": "1.0", "benchmark_id": "b", "task_id": "t", "backend_id": "claude-code",
            "run_id": "run-a", "attempt": 1, "result": "pass",
            "scores": {"tests_passed": True, "lint_passed": True, "typecheck_passed": True},
            "derived": {"elapsed_seconds": 1.0, "files_changed": 1, "lines_added": 1, "lines_removed": 0},
        }))
        pj._jobs.clear()
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_BENCHMARK_RUNS_ROOT: str(root)}):
            self.assertEqual(self.client.post("/api/pipeline/run/correlate", json={}).status_code, 200)
            for _ in range(200):
                if pj.job_state(pj.STEP_CORRELATE)["state"] != "running":
                    break
                _time.sleep(0.02)
            job = pj.job_state(pj.STEP_CORRELATE)
            self.assertEqual(job["state"], "done", job)
            self.assertEqual(job["progress"]["linked"], 1)
            self.assertIn("linked 1 sessions", job["message"])
            body = self.client.get("/api/dashboard/benchmark").json()
            self.assertEqual(body["sessions_linked"], 1)
            self.assertTrue(body["runs_root"]["is_dir"])
            steps = {s["id"]: s for s in self.client.get("/api/pipeline/status").json()["steps"]}
            self.assertTrue(steps["correlate"]["done"])
            self.assertIn(str(root), steps["correlate"]["blurb"])

    def test_ask_streams_steps_and_the_answer_from_the_settings_judge(self) -> None:
        # Ask: the judge in Settings (and only that one) answers a question
        # by calling read-only tools; the page sees every step as NDJSON.
        from session_analytics import config as cfgmod
        from session_analytics.judge.registry import register_judge

        sid = self.client.get("/api/sessions").json()["sessions"][0]["id"]
        replies = [
            json.dumps({"tool": "session_summary", "args": {"session_id": sid}, "why": "look"}),
            json.dumps({"answer": f"Session #{sid} is the only one.", "sessions": [sid]}),
        ]

        class _Asker:
            judge_id = "asker"

            def __init__(self, model: str = "") -> None:
                self._model = model or "a"

            def rate_turn(self, ctx, rubric):  # pragma: no cover
                raise NotImplementedError

            def complete(self, prompt, *, timeout=120):
                return replies.pop(0)

        register_judge("asker", _Asker)
        absent = str(Path(tempfile.mkdtemp()) / "no-graph")
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_JUDGE_BACKEND: "asker",
                                            cfgmod.ENV_KUZU_PATH: absent}):
            info = self.client.get("/api/ask").json()
            self.assertEqual(info["judge"]["spec"], "asker:a")
            self.assertEqual(info["facts"]["sessions"], 1)
            self.assertTrue(info["examples"])
            r = self.client.post("/api/ask", json={"question": "what is there?", "history": []})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.headers["content-type"].startswith("application/x-ndjson"))
            events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
            self.assertEqual([e["event"] for e in events], ["judge", "step", "result", "answer"])
            self.assertEqual(events[0]["judge"], "asker:a")
            self.assertEqual(events[1]["tool"], "session_summary")
            self.assertEqual(events[2]["session_ids"], [sid])
            self.assertIn('"session_key": "claude-code:', events[2]["result_text"])
            self.assertEqual(events[3]["sessions"], [sid])
            self.assertEqual(events[3]["unverified"], [])
            self.assertEqual(info["facts"]["project_count"], 1)
            self.assertEqual(info["facts"]["graph_state"], "absent")
            r = self.client.post("/api/ask", json={"question": "   "})
            self.assertEqual(r.status_code, 400)

    def test_ask_without_a_judge_base_url_is_an_error_event(self) -> None:
        from session_analytics import config as cfgmod

        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_JUDGE_BACKEND: "openai",
                                            cfgmod.ENV_JUDGE_BASE_URL: ""}):
            r = self.client.post("/api/ask", json={"question": "anything"})
            events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
            self.assertEqual(events[-1]["event"], "error")
            self.assertEqual(events[-1]["prerequisite"], "judge")
            self.assertIn("base URL", events[-1]["error"])

    def test_judge_test_reports_the_answer_or_the_backends_own_reason(self) -> None:
        # Settings → "Test judge": one call to the SAVED judge, so a wrong
        # URL or model is seen before a batch, with the backend's reason.
        from session_analytics import config as cfgmod
        from session_analytics.judge.contracts import JudgeTransportError
        from session_analytics.judge.registry import register_judge

        class _Probe:
            judge_id = "probe"
            fail = False

            def __init__(self, model: str = "") -> None:
                self._model = model or "p"

            def rate_turn(self, ctx, rubric):  # pragma: no cover
                raise NotImplementedError

            def complete(self, prompt, *, timeout=120):
                if _Probe.fail:
                    raise JudgeTransportError("HTTP 404: The model `p` does not exist.")
                return '{"ok": true}'

        register_judge("probe", _Probe)
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_JUDGE_BACKEND: "probe"}):
            r = self.client.post("/api/judge/test").json()
            self.assertTrue(r["ok"], r)
            self.assertEqual((r["judge"], r["answer"]), ("probe:p", '{"ok": true}'))
            _Probe.fail = True
            r = self.client.post("/api/judge/test").json()
            self.assertFalse(r["ok"])
            self.assertIn("HTTP 404", r["error"])

    def test_sessions_sort_params_are_echoed_and_validated(self) -> None:
        r = self.client.get("/api/sessions", params={"sort": "error_count", "order": "asc"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["sort"], r.json()["order"]), ("error_count", "asc"))
        self.assertEqual(self.client.get("/api/sessions", params={"sort": "nope"}).status_code, 400)
        self.assertEqual(self.client.get("/api/sessions", params={"order": "sideways"}).status_code, 400)

    def test_session_tags_are_set_by_hand_shown_in_the_list_and_sortable(self) -> None:
        sid = self._session_id()
        row = self.client.get("/api/sessions").json()["sessions"][0]
        self.assertEqual(row["tags"], {"favorite": False, "todo": False, "analyzed_kinds": 0, "analysis_kinds_total": 3})
        # cost coverage rides on every row so a priced subtotal is never
        # presented as the whole cost
        cov = row["cost_coverage"]
        self.assertEqual(set(cov), {"priced_turns", "priceable_turns", "complete"})
        self.assertEqual(cov["complete"], cov["priceable_turns"] > 0 and cov["priced_turns"] >= cov["priceable_turns"])
        r = self.client.put(f"/api/sessions/{sid}/tags/favorite", json={"on": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["tags"]["favorite"])
        self.assertTrue(self.client.get(f"/api/sessions/{sid}").json()["tags"]["favorite"])
        self.assertEqual(self.client.get("/api/sessions", params={"sort": "favorite"}).status_code, 200)
        self.assertEqual(self.client.get("/api/sessions", params={"sort": "analyzed"}).status_code, 200)
        self.assertFalse(
            self.client.put(f"/api/sessions/{sid}/tags/favorite", json={"on": False}).json()["tags"]["favorite"]
        )
        # derived, not settable; unknown session
        self.assertEqual(self.client.put(f"/api/sessions/{sid}/tags/analyzed", json={"on": True}).status_code, 400)
        self.assertEqual(self.client.put("/api/sessions/99999/tags/todo", json={"on": True}).status_code, 404)
        # analyzed follows a parsed analysis
        self._register_fake_judge(json.dumps({"summary": "ok", "findings": []}))
        self.client.post(f"/api/sessions/{sid}/analysis/tuning", json={"judge": "fake:x"})
        self.assertEqual(self.client.get(f"/api/sessions/{sid}").json()["tags"]["analyzed_kinds"], 1)

    def test_embedding_endpoints_and_the_similar_steps_in_the_pipeline(self) -> None:
        # Settings → Embeddings: the configured embedding, its model list,
        # a probe; the pipeline knows embed + similar and their counts.
        from session_analytics.embedding.contracts import EmbeddingResult
        from session_analytics.embedding.registry import register_embedding

        class _Fake:
            def __init__(self, model="", *, base_url=""):
                self.model = model

            def probe(self):
                if self.model == "broken":
                    raise RuntimeError("model 'broken' not found")

            def embed(self, text):
                if self.model == "dead":
                    raise RuntimeError("connection refused")
                return EmbeddingResult(vector=(0.1, 0.2, 0.3), resolved_model=self.model or "fake-default")

        register_embedding("fake", _Fake)
        from session_analytics import config as cfgmod

        with mock.patch.dict("os.environ", {cfgmod.ENV_EMBED_BACKEND: "fake", cfgmod.ENV_EMBED_MODEL: "tiny"}):
            m = self.client.get("/api/embed/models").json()
            self.assertEqual(m["configured"], {"backend": "fake", "model": "tiny", "spec": "fake:tiny", "model_set": True})
            t = self.client.post("/api/embed/test").json()
            self.assertTrue(t["ok"], t)
            self.assertEqual((t["dimensions"], t["model"]), (3, "tiny"))
        with mock.patch.dict("os.environ", {cfgmod.ENV_EMBED_BACKEND: "fake", cfgmod.ENV_EMBED_MODEL: "broken"}):
            t = self.client.post("/api/embed/test").json()
            self.assertFalse(t["ok"])
            self.assertIn("not found", t["error"])
        st = self.client.get("/api/pipeline/status").json()
        self.assertEqual([s["id"] for s in st["steps"]], ["ingest", "correlate", "graph", "embed", "similar", "judge", "kpis"])
        self.assertIn("embedded", st["counts"])
        self.assertIn("similar_edges", st["counts"])
        # no embedding model → the embed step fails at once with the fix
        with mock.patch.dict("os.environ", {cfgmod.ENV_EMBED_BACKEND: "fake", cfgmod.ENV_EMBED_MODEL: ""}):
            self.assertEqual(self.client.post("/api/pipeline/run/embed").status_code, 200)
            import time as _t

            for _ in range(100):
                job = next(x for x in self.client.get("/api/pipeline/status").json()["steps"] if x["id"] == "embed")["job"]
                if job["state"] != "running":
                    break
                _t.sleep(0.05)
            self.assertEqual(job["state"], "failed")
            self.assertIn("Settings → Embeddings", job["message"])
        self.assertEqual(self.client.post("/api/pipeline/run-all", json={"steps": ["nope"]}).status_code, 400)
        # a pass in which every embedding failed is a FAILED step that
        # keeps the reason — not "done: embedded 0 of 1; 1 failed"
        with mock.patch.dict("os.environ", {cfgmod.ENV_EMBED_BACKEND: "fake", cfgmod.ENV_EMBED_MODEL: "dead"}):
            self.assertEqual(self.client.post("/api/pipeline/run/embed").status_code, 200)
            for _ in range(100):
                job = next(x for x in self.client.get("/api/pipeline/status").json()["steps"] if x["id"] == "embed")["job"]
                if job["state"] != "running":
                    break
                _t.sleep(0.05)
            self.assertEqual(job["state"], "failed", job)
            self.assertIn("connection refused", job["message"])
            self.assertIn("Settings → Embeddings", job["message"])

    def test_get_config(self) -> None:
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("configured", body)
        keys = {f["key"] for f in body["fields"]}
        self.assertIn("CCT_SA_DB", keys)
        self.assertIn("CCT_SA_JUDGE_API_KEY", keys)
        # The API-key field is secret → its value is never sent to the browser.
        apikey = next(f for f in body["fields"] if f["key"] == "CCT_SA_JUDGE_API_KEY")
        self.assertTrue(apikey["secret"])
        self.assertEqual(apikey["value"], "")
        # Privacy AC: the packaged default judge is local-only Ollama.
        self.assertTrue(body["judge_default"].startswith("ollama"))
        self.assertIn("openai", body["judge_backends"])

    def test_put_config_drops_blank_secret(self) -> None:
        from unittest import mock

        captured = {}
        with mock.patch("session_analytics.config.write_env_file",
                        side_effect=lambda v, *a, **k: captured.update(v)):
            r = self.client.put("/api/config", json={"values": {
                "CCT_SA_DB": "sqlite:////tmp/y.db",
                "CCT_SA_JUDGE_API_KEY": "",      # blank secret = unchanged → dropped
            }})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertIn("CCT_SA_DB", captured)
        self.assertNotIn("CCT_SA_JUDGE_API_KEY", captured)  # not overwritten with blank


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestRoutingEvidenceApi(RegistryResetTestCase):
    """routing-shadow T3: the routing evidence endpoints over HTTP —
    evidence, recommendations, empty, invalid, and evidence-file
    states, with the no-path boundary held at the HTTP layer."""

    def setUp(self) -> None:
        super().setUp()
        import tempfile
        from pathlib import Path
        from unittest import mock

        from session_analytics._register import register_all
        register_all()
        self.base = Path(tempfile.mkdtemp(prefix="SENSITIVE-API-ROOT."))
        self.addCleanup(__import__("shutil").rmtree, self.base,
                        ignore_errors=True)
        from session_analytics.tests.test_routing_evidence import (
            TestEvidenceLoading,
        )

        self.published = TestEvidenceLoading._publish_fixture(self, self.base)
        self._env = mock.patch.dict(
            "os.environ",
            {"CCT_SA_ROUTING_EVIDENCE_ROOTS": str(self.base / "out")},
        )
        self._env.start()
        self.addCleanup(self._env.stop)
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        self.client = TestClient(create_app(self.sqlite_dsn()),
                                 base_url="http://127.0.0.1:8765")

    def test_settings_expose_only_the_sanitized_shape(self) -> None:
        r = self.client.get("/api/settings")
        self.assertEqual(r.status_code, 200)
        shape = r.json()["routing_evidence"]
        self.assertEqual(shape, {"configured": True, "root_count": 1})
        self.assertNotIn("SENSITIVE-API-ROOT", r.text)

    def test_evidence_and_recommendation_flow(self) -> None:
        r = self.client.get("/api/routing/evidence")
        self.assertEqual(r.status_code, 200)
        (entry,) = r.json()["sets"]
        self.assertEqual(entry["state"], "valid")
        set_id = entry["set_id"]
        self.assertEqual(set_id, self.published.set_id)
        self.assertNotIn("SENSITIVE-API-ROOT", r.text)

        detail = self.client.get(f"/api/routing/evidence/{set_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["report"]["schema_version"], 1)
        self.assertNotIn("SENSITIVE-API-ROOT", detail.text)

        recs = self.client.get(
            f"/api/routing/evidence/{set_id}/recommendations")
        self.assertEqual(recs.status_code, 200)
        for rec in recs.json()["recommendations"]:
            self.assertEqual(rec["evidence_set_id"], set_id)
        self.assertNotIn("SENSITIVE-API-ROOT", recs.text)

        refs = sorted(
            json.loads(
                (self.published.path / "manifest.json").read_text(
                    encoding="utf-8")
            )["evidence_files"]
        )
        served = self.client.get(
            f"/api/routing/evidence/{set_id}/evidence-file",
            params={"ref": refs[0]},
        )
        self.assertEqual(served.status_code, 200)
        self.assertNotIn("SENSITIVE-API-ROOT", served.text)
        refused = self.client.get(
            f"/api/routing/evidence/{set_id}/evidence-file",
            params={"ref": "../outside"},
        )
        self.assertEqual(refused.status_code, 404)
        self.assertEqual(refused.json()["detail"], "unknown_reference")

    def test_artifact_surface_over_http(self) -> None:
        # T4 round-2: locators are followable — each validated artifact
        # serves verbatim through the closed read-only surface
        set_id = self.published.set_id
        for artifact in ("report", "routing_runs", "outcome_matrix"):
            r = self.client.get(
                f"/api/routing/evidence/{set_id}/artifact/{artifact}")
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body["artifact"], artifact)
            self.assertEqual(body["set_id"], set_id)
            self.assertNotIn("SENSITIVE-API-ROOT", r.text)
        records = self.client.get(
            f"/api/routing/evidence/{set_id}/artifact/routing_runs"
        ).json()["content"]["records"]
        self.assertTrue(records and records[0]["routing_decisions"])
        refused = self.client.get(
            f"/api/routing/evidence/{set_id}/artifact/manifest")
        self.assertEqual(refused.status_code, 404)
        self.assertEqual(refused.json()["detail"], "unknown_reference")

    def test_unknown_set_and_empty_root_states(self) -> None:
        r = self.client.get("/api/routing/evidence/" + "0" * 64)
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("SENSITIVE-API-ROOT", r.text)
        import os
        from unittest import mock as _mock

        with _mock.patch.dict(os.environ,
                              {"CCT_SA_ROUTING_EVIDENCE_ROOTS":
                               str(self.base / "does-not-exist")}):
            empty = self.client.get("/api/routing/evidence")
            self.assertEqual(empty.status_code, 200)
            self.assertEqual(empty.json()["sets"], [])

    def test_invalid_set_surfaces_over_http(self) -> None:
        report = self.published.path / "report.json"
        report.write_text("{not json", encoding="utf-8")
        r = self.client.get("/api/routing/evidence")
        self.assertEqual(r.status_code, 200)
        (entry,) = r.json()["sets"]
        self.assertEqual(entry["state"], "invalid_evidence")
        self.assertNotIn("SENSITIVE-API-ROOT", r.text)

    # ── routing-calibration (#266) T4: the three decision-10 routes ──
    def test_calibration_endpoints_over_http(self) -> None:
        import os
        from unittest import mock as _mock

        # Point BOTH calibration paths at identifiable locations: the
        # sweep below proves neither reaches a payload.
        with _mock.patch.dict(os.environ, {
            "CCT_SA_CALIBRATION_ROOT": str(self.base / "SENSITIVE-CALIB"),
            "CCT_SA_CALIBRATION_POLICY_SOURCE":
                str(self.base / "SENSITIVE-POLICY.toml"),
        }):
            gates = self.client.get("/api/routing/calibration")
            self.assertEqual(gates.status_code, 200)
            body = gates.json()
            self.assertEqual(body["state"], "report")
            self.assertEqual(
                sorted(g["id"] for g in body["report"]["gates"]),
                sorted(GATE_IDS))
            self.assertFalse(body["report"]["calibrated"])
            # agreement rides beside the verdicts in every state
            self.assertIn("agreement", body["evaluation"])
            self.assertFalse(body["evaluation"]["present"])
            self.assertNotIn("SENSITIVE", gates.text)

            evaluation = self.client.get(
                "/api/routing/calibration/evaluation")
            self.assertEqual(evaluation.status_code, 200)
            self.assertEqual(evaluation.json()["state"], "insufficient_data")
            self.assertNotIn("SENSITIVE", evaluation.text)

            knn = self.client.get(
                f"/api/routing/evidence/{self.published.set_id}/knn")
            self.assertEqual(knn.status_code, 200)
            self.assertEqual(knn.json()["set_id"], self.published.set_id)
            self.assertNotIn("SENSITIVE", knn.text)

            # an unknown set is a 404, never an empty recommendation list
            unknown = self.client.get(
                "/api/routing/evidence/" + "0" * 64 + "/knn")
            self.assertEqual(unknown.status_code, 404)

    def test_knn_route_uses_one_corpus_snapshot(self) -> None:
        # T4 review P2: the existence check and the derivation must read
        # ONE snapshot, or a set can pass the 404 check and still come
        # back empty. Counting loads proves it structurally.
        import os
        from unittest import mock as _mock

        from session_analytics import routing_evidence

        real = routing_evidence.load_evidence_sets
        calls = []

        def counting(roots):
            calls.append(tuple(roots))
            return real(roots)

        with _mock.patch.dict(os.environ, {
            "CCT_SA_CALIBRATION_POLICY_SOURCE": "",
        }), _mock.patch.object(routing_evidence, "load_evidence_sets",
                               counting):
            r = self.client.get(
                f"/api/routing/evidence/{self.published.set_id}/knn")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(calls), 1, calls)
