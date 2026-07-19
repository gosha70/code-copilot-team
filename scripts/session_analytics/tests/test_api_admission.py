# Request-admission tests for the API (#103): Host + Origin guards.
#
# Host validation is the load-bearing control against DNS rebinding — a
# browser sets Host from the URL, so page script cannot forge it. The Origin
# check is a second layer for state-changing requests; absent Origin is
# allowed by design (non-browser clients never send one).

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

_ALLOWED_BASE = "http://127.0.0.1:8765"
_READ_ROUTE = "/api/health"
_WRITE_ROUTE = "/api/settings/test-connection"


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestRequestAdmission(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics._register import register_all

        register_all()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        self.client = TestClient(create_app(self.dsn), base_url=_ALLOWED_BASE)

    # ── Host guard (FR-1) ──────────────────────────────────────────────

    def test_allowed_hosts_pass(self) -> None:
        for host in C.API_ALLOWED_HOSTS:
            r = self.client.get(_READ_ROUTE, headers={"host": f"{host}:8765"})
            self.assertEqual(r.status_code, 200, msg=host)

    def test_rebinding_host_rejected_on_read_route(self) -> None:
        # The DNS-rebinding case: the browser's Host is the attacker's name.
        r = self.client.get(_READ_ROUTE, headers={"host": "attacker.com"})
        self.assertEqual(r.status_code, 400)

    def test_rebinding_host_rejected_on_state_changing_route(self) -> None:
        # Proves the guard runs before handlers on write routes too.
        r = self.client.post(
            _WRITE_ROUTE, json={"dsn": self.dsn}, headers={"host": "attacker.com"}
        )
        self.assertEqual(r.status_code, 400)

    def test_rejected_host_response_does_not_echo_the_value(self) -> None:
        r = self.client.get(_READ_ROUTE, headers={"host": "attacker.example.test"})
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("attacker.example.test", r.text)

    def test_data_bearing_routes_are_guarded_too(self) -> None:
        # #103's point: the exposure was never probe-specific.
        for route in ("/api/sessions", "/api/search?q=x", "/api/settings"):
            r = self.client.get(route, headers={"host": "attacker.com"})
            self.assertEqual(r.status_code, 400, msg=route)

    # ── Origin guard (FR-2) ────────────────────────────────────────────

    def test_absent_origin_allowed_on_state_changing_route(self) -> None:
        # By design: TestClient/curl/scripts never send Origin.
        r = self.client.post(_WRITE_ROUTE, json={"dsn": self.dsn})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_studio_origin_allowed(self) -> None:
        from session_analytics.api.server import studio_origins

        for origin in studio_origins():
            r = self.client.post(
                _WRITE_ROUTE, json={"dsn": self.dsn}, headers={"origin": origin}
            )
            self.assertEqual(r.status_code, 200, msg=origin)

    def test_own_origin_allowed_so_swagger_docs_work(self) -> None:
        # FastAPI mounts /docs by default and its "Try it out" issues a
        # SAME-ORIGIN POST — browsers send Origin on non-GET even same-origin.
        # Regression guard: this returned 403 before the own-origin rule.
        self.assertEqual(self.client.get("/docs").status_code, 200)
        r = self.client.post(
            _WRITE_ROUTE,
            json={"dsn": self.dsn},
            headers={"origin": "http://127.0.0.1:8765", "host": "127.0.0.1:8765"},
        )
        self.assertEqual(r.status_code, 200)

    def test_own_origin_rule_does_not_admit_a_mismatched_host(self) -> None:
        # The own-origin escape hatch compares against the REQUEST's Host,
        # which TrustedHost already validated — a foreign Origin cannot slip
        # through by merely looking self-referential.
        r = self.client.post(
            _WRITE_ROUTE,
            json={"dsn": self.dsn},
            headers={"origin": "http://evil.example:8765", "host": "127.0.0.1:8765"},
        )
        self.assertEqual(r.status_code, 403)

    def test_foreign_origin_rejected_on_state_changing_route(self) -> None:
        r = self.client.post(
            _WRITE_ROUTE,
            json={"dsn": self.dsn},
            headers={"origin": "https://evil.example"},
        )
        self.assertEqual(r.status_code, 403)
        # API-standard JSON error shape (matches HTTPException), not text.
        self.assertEqual(r.json(), {"detail": C.MSG_ORIGIN_NOT_ALLOWED})
        self.assertNotIn("evil.example", r.text)  # never echo the value

    def test_origins_follow_the_actual_ui_port(self) -> None:
        # #103 follow-up: a non-default --ui-port must not be silently
        # broken by hardcoded :3000 origins.
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app, studio_origins

        client = TestClient(create_app(self.dsn, ui_port=3100), base_url=_ALLOWED_BASE)
        self.assertIn("http://localhost:3100", studio_origins(3100))
        r = client.post(
            _WRITE_ROUTE,
            json={"dsn": self.dsn},
            headers={"origin": "http://localhost:3100"},
        )
        self.assertEqual(r.status_code, 200)
        # …and the default port is no longer allowed on that app.
        r = client.post(
            _WRITE_ROUTE,
            json={"dsn": self.dsn},
            headers={"origin": "http://localhost:3000"},
        )
        self.assertEqual(r.status_code, 403)

    def test_foreign_origin_allowed_on_safe_read(self) -> None:
        # GET is exempt: the Host guard already covers the rebinding threat,
        # and CORS stops the page from READING an ordinary cross-origin GET.
        r = self.client.get(_READ_ROUTE, headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 200)

    def test_origin_guard_covers_put_not_just_post(self) -> None:
        # Method-based, so new state-changing routes are covered without a
        # hand-maintained list.
        r = self.client.put(
            "/api/config",
            json={"values": {}},
            headers={"origin": "https://evil.example"},
        )
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
