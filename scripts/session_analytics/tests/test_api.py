# API tests via FastAPI TestClient. Run only when fastapi is importable (CI
# installs it for the API job); skips are logged, never silently passed.

from __future__ import annotations

import importlib.util
import json
import unittest

from session_analytics import constants as C
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

    def test_dashboard_kpis(self) -> None:
        r = self.client.get("/api/dashboard/kpis")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["totals"]["sessions"], 1)
        # E5: total cost + cost-per-session always present, NULL-safe (this
        # fixture ingests with no pricing kwarg → 0.0, never an error).
        self.assertEqual(r.json()["totals"]["total_cost_usd"], 0.0)
        self.assertEqual(r.json()["totals"]["cost_per_session"], 0.0)

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
