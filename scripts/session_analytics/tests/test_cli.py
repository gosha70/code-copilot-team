# CLI smoke tests: list / ingest / doctor exit codes + output shape.

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from session_analytics import constants as C
from session_analytics.cli import main

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


def _run(argv) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(io.StringIO()):
        code = main(argv)
    return code, buf.getvalue()


class TestCli(RegistryResetTestCase):
    def test_list(self) -> None:
        code, out = _run(["list"])
        self.assertEqual(code, C.EXIT_OK)
        data = json.loads(out)
        self.assertIn(C.COPILOT_CLAUDE_CODE, data["adapters"])

    def test_ingest_requires_dsn(self) -> None:
        code, _ = _run(["ingest", "--copilot", "claude-code", "--root", str(CLAUDE_CODE_ROOT)])
        # No DSN configured in the test env → usage error.
        self.assertEqual(code, C.EXIT_USAGE)

    def test_team_status_prints_the_table_and_json(self) -> None:
        dsn = self.sqlite_dsn()
        code, out = _run(["team", "status", "--db", dsn])
        self.assertEqual(code, C.EXIT_OK)
        self.assertIn("Team status — local store (SQLite)", out)
        self.assertIn("0 of 0 active", out)
        code, out = _run(["team", "--db", dsn, "--json", "--window", "60"])
        self.assertEqual(code, C.EXIT_OK)
        body = json.loads(out)
        self.assertEqual((body["active_window_seconds"], body["developers"]), (60, []))
        code, _ = _run(["team", "status", "--db", dsn, "--window", "0"])
        self.assertEqual(code, C.EXIT_USAGE)

    def test_ingest_then_doctor(self) -> None:
        dsn = self.sqlite_dsn()
        code, out = _run(
            [
                "ingest",
                "--copilot",
                "claude-code",
                "--root",
                str(CLAUDE_CODE_ROOT),
                "--dsn",
                dsn,
                "--full",
            ]
        )
        self.assertEqual(code, C.EXIT_OK)
        stats = json.loads(out)
        self.assertEqual(stats["sessions_ingested"], 1)

        code, out = _run(["doctor", "--dsn", dsn])
        self.assertEqual(code, C.EXIT_OK)
        report = json.loads(out)
        self.assertEqual(report["store"]["sessions"], 1)
        self.assertEqual(report["store"]["dsn_dialect"], "sqlite")


if __name__ == "__main__":
    unittest.main()
