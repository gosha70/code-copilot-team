# Route-guard tests for the routing-calibration API (CodeQL alerts 21-23,
# py/stack-trace-exposure).
#
# Those three routes were the only ones in server.py with no exception
# guard, while their neighbours convert failures into curated details. An
# unexpected exception therefore reached the caller as a stack trace —
# the same class of leak the connection probe's closed error set exists
# to prevent, where a driver message carried hosts, IPs and usernames.
#
# The contract these pin:
#   an unexpected failure  -> 500, CONSTANT detail, no exception text
#   a deliberate 404       -> still a 404 (the guard must not swallow it)
#   the exception itself   -> logged in full, never returned

from __future__ import annotations

import importlib.util
import unittest
from unittest import mock

from session_analytics import constants as C
from session_analytics.ingest.pipeline import ingest
from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_FASTAPI = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)

_ALLOWED_BASE = "http://127.0.0.1:8765"

# A message shaped like the real leaks this guards against: a driver error
# carrying a host, an IP, a port and a username.
_LEAKY = (
    'connection to server at "db.internal" (10.0.0.5), port 5432 failed: '
    'FATAL: password authentication failed for user "admin"'
)

_GUARDED_ROUTES = (
    ("/api/routing/calibration", "calibration_payload"),
    ("/api/routing/calibration/evaluation", "evaluation_payload"),
)


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestRoutingRouteGuards(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics._register import register_all

        register_all()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        self.client = TestClient(
            create_app(self.dsn), base_url=_ALLOWED_BASE, raise_server_exceptions=False
        )

    def test_unexpected_failure_returns_a_curated_500(self) -> None:
        for route, target in _GUARDED_ROUTES:
            with self.subTest(route=route):
                with mock.patch(
                    f"session_analytics.routing_calibration.{target}",
                    side_effect=RuntimeError(_LEAKY),
                ):
                    r = self.client.get(route)
                self.assertEqual(r.status_code, 500, msg=route)
                self.assertEqual(r.json()["detail"], C.MSG_INTERNAL_ERROR, msg=route)

    def test_the_response_never_carries_the_exception_text(self) -> None:
        """THE finding: a stack trace or driver text must not reach the caller."""
        for route, target in _GUARDED_ROUTES:
            with self.subTest(route=route):
                with mock.patch(
                    f"session_analytics.routing_calibration.{target}",
                    side_effect=RuntimeError(_LEAKY),
                ):
                    r = self.client.get(route)
                body = r.text.lower()
                for fragment in ("db.internal", "10.0.0.5", "5432", "admin",
                                 "traceback", "runtimeerror"):
                    self.assertNotIn(fragment.lower(), body,
                                     msg=f"{route} leaked {fragment!r}")

    def test_knn_route_is_guarded_too(self) -> None:
        # The knn route's own helpers are closures inside create_app, so
        # the failure is injected at the first module-level call it makes
        # — which also runs BEFORE the 404 check, exercising the guard
        # rather than the not-found path.
        with mock.patch(
            "session_analytics.api.server.load_config",
            side_effect=RuntimeError(_LEAKY),
        ):
            r = self.client.get("/api/routing/evidence/anything/knn")
        self.assertEqual(r.status_code, 500, msg=r.text)
        self.assertEqual(r.json()["detail"], C.MSG_INTERNAL_ERROR)
        self.assertNotIn("db.internal", r.text)

    def test_a_deliberate_404_survives_the_guard(self) -> None:
        """The guard must re-raise HTTPException, not convert it to a 500.

        Catching broadly and returning 500 for everything would turn the
        knn route's unknown-set 404 into an internal error — losing a
        curated answer the caller depends on.
        """
        r = self.client.get("/api/routing/evidence/no-such-set-id/knn")
        self.assertEqual(r.status_code, 404, msg=r.text)
        self.assertNotEqual(r.json().get("detail"), C.MSG_INTERNAL_ERROR)

    def test_the_exception_is_logged_in_full(self) -> None:
        """Curated out of the RESPONSE, but never lost to the operator."""
        with mock.patch(
            "session_analytics.routing_calibration.calibration_payload",
            side_effect=RuntimeError(_LEAKY),
        ):
            with self.assertLogs("session_analytics.api.server", level="ERROR") as caught:
                self.client.get("/api/routing/calibration")
        self.assertTrue(
            any(_LEAKY in line for line in caught.output),
            "the exception text must reach the log even though it never "
            "reaches the caller",
        )


if __name__ == "__main__":
    unittest.main()
