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

    def test_team_alerts_exit_code_is_the_alarm(self) -> None:
        from unittest import mock

        from session_analytics import config as cfgmod

        dsn = self.sqlite_dsn()
        code, out = _run(["team", "alerts", "--db", dsn])
        self.assertEqual((code, out.splitlines()[0]), (C.EXIT_OK, "No alerts."))
        code, out = _run(["team", "alerts", "--db", dsn, "--json"])
        self.assertEqual(code, C.EXIT_OK)
        self.assertEqual(json.loads(out)["alerts"], [])
        # Seed one priced turn today and a tiny budget: a breach → exit 1,
        # a warning-level floor also 1, and status is unaffected.
        from datetime import datetime, timezone

        from session_analytics.relational.db import Database, apply_ddl

        db = Database.connect(dsn)
        apply_ddl(db)
        db.execute("INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, turn_count, started_at) "
                   "VALUES ('claude-code', 'b', '/repo/p', 'ana', 50, ?)", (datetime.now(timezone.utc).isoformat(),))
        sid = int(db.query_one("SELECT id FROM copilot_session WHERE session_id = 'b'")[0])
        db.execute("INSERT INTO copilot_turn (session_id, sequence_num, role, content_preview, timestamp, cost_usd, model) "
                   "VALUES (?, 1, 'assistant', '', ?, 3.0, 'm')", (sid, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
        db.commit(); db.close()
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_BUDGET_TEAM_DAILY: "2", cfgmod.ENV_NOISE_MIN_DURATION: "0"}):
            code, out = _run(["team", "alerts", "--db", dsn])
            self.assertEqual(code, 1)
            self.assertIn("[BREACH ] budget: the team has passed 150% of the $2.00 budget today", out)
            code, _ = _run(["team", "alerts", "--db", dsn, "--fail-on", "warning"])
            self.assertEqual(code, 1)
            self.assertEqual(_run(["team", "status", "--db", dsn])[0], C.EXIT_OK)
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_BUDGET_TEAM_DAILY: "3.5", cfgmod.ENV_NOISE_MIN_DURATION: "0"}):
            code, out = _run(["team", "alerts", "--db", dsn])            # 86%: warning, default floor is breach
            self.assertEqual(code, C.EXIT_OK)
            self.assertIn("[WARNING] budget: the team is at 86%", out)
            self.assertEqual(_run(["team", "alerts", "--db", dsn, "--fail-on", "warning"])[0], 1)

    def test_alias_fr4_team_status_folds_the_configured_aliases(self) -> None:
        from datetime import datetime, timezone
        from unittest import mock

        from session_analytics import config as cfgmod
        from session_analytics.relational.db import Database, apply_ddl

        dsn = self.sqlite_dsn()
        db = Database.connect(dsn)
        apply_ddl(db)
        db.execute("INSERT INTO developer (developer_id, display_name) VALUES ('i-am-goga', 'Table Name')")
        now = datetime.now(timezone.utc)
        for native, dev, cost in (("a", "i-am-goga", 1.0), ("b", "local", 0.5)):
            db.execute(
                "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, turn_count, "
                "started_at, duration_seconds) VALUES ('claude-code', ?, '/repo/p', ?, 50, ?, 600)",
                (native, dev, now.isoformat()),
            )
            sid = int(db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", (native,))[0])
            db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, content_preview, timestamp, cost_usd, model) "
                "VALUES (?, 1, 'assistant', '', ?, ?, 'm')",
                (sid, now.strftime("%Y-%m-%dT%H:%M:%SZ"), cost),
            )
        db.commit(); db.close()
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_TEAM_ALIASES: "i-am-goga=Gosha,local=Gosha",
                                            cfgmod.ENV_NOISE_MIN_DURATION: "0"}):
            code, out = _run(["team", "status", "--db", dsn])
            self.assertEqual(code, C.EXIT_OK)
            # one row, under the alias name — not the developer table's
            self.assertIn("Gosha (i-am-goga)", out)
            self.assertNotIn("Table Name", out)
            self.assertFalse([ln for ln in out.splitlines() if ln.startswith("local")])
            self.assertIn("$1.50", out)          # the two ids' costs, added
            self.assertIn("of 1 active", out.splitlines()[0])   # one person, not two
            code, out = _run(["team", "--db", dsn, "--json"])
            body = json.loads(out)
            self.assertEqual([(d["developer_id"], d["display_name"], d["merged_ids"]) for d in body["developers"]],
                             [("i-am-goga", "Gosha", ["i-am-goga", "local"])])

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
