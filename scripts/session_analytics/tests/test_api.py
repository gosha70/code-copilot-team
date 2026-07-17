# API tests via FastAPI TestClient. Run only when fastapi is importable (CI
# installs it for the API job); skips are logged, never silently passed.

from __future__ import annotations

import importlib.util
import unittest

from session_analytics import constants as C
from session_analytics.ingest.pipeline import ingest

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

        self.client = TestClient(create_app(self.dsn))

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

    def test_settings_does_not_leak_dsn(self) -> None:
        r = self.client.get("/api/settings")
        self.assertEqual(r.status_code, 200)
        body = r.text
        self.assertNotIn(self.dsn, body)  # raw DSN must never be returned
        self.assertEqual(r.json()["dsn_dialect"], "sqlite")

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
