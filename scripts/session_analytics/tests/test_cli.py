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
        # The alerts under test are the store's own; the auto-build caps
        # are a family with its own test, and this host's real ledger
        # root — where a live run may well be near its cap — must not
        # decide this test's output or exit codes.
        ledgers = mock.patch.dict("os.environ", {cfgmod.ENV_AUTO_BUILD_ROOT: "/nonexistent/cct-ledgers"})
        ledgers.start()
        self.addCleanup(ledgers.stop)
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
        # FR-4 (team-developer-aliases): the CLI table applies
        # load_config().team.aliases — two derived ids, one person, one row.
        from datetime import datetime, timezone
        from pathlib import Path
        from unittest import mock

        from session_analytics import config as cfgmod
        from session_analytics.relational.db import Database, apply_ddl

        dsn = self.sqlite_dsn()
        db = Database.connect(dsn)
        apply_ddl(db)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i, dev in enumerate(("i-am-goga", "local")):
            db.execute(
                "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, turn_count, "
                "started_at, duration_seconds) VALUES ('claude-code', ?, '/repo/p', ?, 5, ?, 600)",
                (f"s-{i}", dev, now),
            )
            sid = int(db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", (f"s-{i}",))[0])
            db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, content_preview, timestamp, "
                "cost_usd, model) VALUES (?, 1, 'assistant', '', ?, 1.5, 'm')", (sid, now))
        db.commit(); db.close()

        with mock.patch.object(cfgmod, "_USER_CONFIG", Path("/nonexistent/session-analytics.json")), \
             mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_TEAM_ALIASES: "i-am-goga=Gosha,local=Gosha"}):
            code, out = _run(["team", "status", "--db", dsn])
            self.assertEqual(code, C.EXIT_OK)
            self.assertIn("Gosha (i-am-goga)", out)
            # …and no second row for the folded id ("local store (SQLite)"
            # in the header is why this looks at line starts).
            self.assertFalse([ln for ln in out.splitlines() if ln.startswith("local")])
            self.assertIn("$3.00", out)          # both ids' priced turns, summed
            code, body = _run(["team", "--db", dsn, "--json"])
            row, = json.loads(body)["developers"]
            self.assertEqual((row["display_name"], row["merged_ids"]), ("Gosha", ["i-am-goga", "local"]))

    def test_cap_fr4_team_alerts_reads_the_ledgers_and_the_exit_code_covers_them(self) -> None:
        # FR-4 (auto-build-cap-alerts): `team alerts` evaluates the
        # auto-build caps from the ledger root the config names, and
        # --fail-on applies to them like it does to a budget.
        import tempfile
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        from unittest import mock

        from session_analytics import config as cfgmod

        def _root(cost_usd: float) -> str:
            now = datetime.now(timezone.utc)
            root = Path(tempfile.mkdtemp(prefix="cct-cli-cap-"))
            ledger = root / C.AUTO_BUILD_LIVE_DIR / "cap-alerts-fixture"
            ledger.mkdir(parents=True)
            (ledger / C.LEDGER_STATE_FILE).write_text(json.dumps({
                "schema_version": 1, "feature_id": "cap-alerts-fixture", "profile": "unattended",
                "attempt_id": "47908-474720888", "status": "building", "current_phase": 1, "phases": {},
                "caps": {"max_wall_clock_sec": 86400, "max_cost_usd": 10.0},
                "outcome": None, "escalations": [], "pr": {"number": None, "url": None},
                "totals": {"cost_usd": cost_usd, "cost_estimated_usd": 0,
                           "started_epoch": int((now - timedelta(seconds=600)).timestamp())},
                "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }), encoding="utf-8")
            return str(root)

        dsn = self.sqlite_dsn()
        base = {cfgmod.ENV_NOISE_MIN_DURATION: "0"}
        with mock.patch.object(cfgmod, "_USER_CONFIG", Path("/nonexistent/session-analytics.json")), \
             mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}):
            with mock.patch.dict("os.environ", {**base, cfgmod.ENV_AUTO_BUILD_ROOT: _root(9.0)}):
                code, out = _run(["team", "alerts", "--db", dsn])   # 90%: a warning
                self.assertEqual(code, C.EXIT_OK)
                self.assertIn("[WARNING] auto-build-cost: auto-build run cap-alerts-fixture "
                              "(47908-474720888) has spent $9.00 of its $10.00 cap (90%)", out)
                self.assertIn("Auto-build: runs evaluated, 1 still running", out)
                self.assertEqual(_run(["team", "alerts", "--db", dsn, "--fail-on", "warning"])[0], 1)
                report = json.loads(_run(["team", "alerts", "--db", dsn, "--json"])[1])
                self.assertEqual(report[C.ALERT_AUTO_BUILD][C.ALERT_AUTO_BUILD_LIVE_RUNS], 1)
                self.assertTrue(report[C.ALERT_AUTO_BUILD][C.ALERT_AUTO_BUILD_EVALUATED])
                self.assertEqual(_run(["team", "status", "--db", dsn])[0], C.EXIT_OK)
            with mock.patch.dict("os.environ", {**base, cfgmod.ENV_AUTO_BUILD_ROOT: _root(12.0)}):
                code, out = _run(["team", "alerts", "--db", dsn])   # 120%: past the cap
                self.assertEqual(code, 1)
                self.assertIn("[BREACH ] auto-build-cost:", out)
            # A ledger root that is not a directory: nothing has run here,
            # which is a state to report, not an error.
            with mock.patch.dict("os.environ", {**base, cfgmod.ENV_AUTO_BUILD_ROOT: "/nonexistent/cct-ledgers"}):
                code, out = _run(["team", "alerts", "--db", dsn])
                self.assertEqual((code, out.splitlines()[0]), (C.EXIT_OK, "No alerts."))
                self.assertIn("Auto-build: runs evaluated, 0 still running", out)

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
