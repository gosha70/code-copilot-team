# API tests via FastAPI TestClient. Run only when fastapi is importable (CI
# installs it for the API job); skips are logged, never silently passed.

from __future__ import annotations

import importlib.util
import json
import unittest
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
        self.assertIn("Re-generate", detail["guidance"])

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
        status = self.client.get("/api/pipeline/status").json()["counts"]
        self.assertEqual((status["sessions"], status["excluded_noise"]), (1, 1))
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

    def test_get_config(self) -> None:
        r = self.client.get("/api/config")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("configured", body)
        keys = {f["key"] for f in body["fields"]}
        self.assertIn("CCT_SA_DSN", keys)
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
                "CCT_SA_DSN": "sqlite:////tmp/y.db",
                "CCT_SA_JUDGE_API_KEY": "",      # blank secret = unchanged → dropped
            }})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertIn("CCT_SA_DSN", captured)
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
