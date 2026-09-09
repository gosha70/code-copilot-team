# Tests for budgets, runaway detection and alerts (#174 Slice D).

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from session_analytics import constants as C
from session_analytics.api import alerts as A
from session_analytics.api import team as T
from session_analytics.config import BudgetsConfig, NoiseConfig, RunawayConfig
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import RegistryResetTestCase

NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
_NOISE = NoiseConfig(min_turns=0, min_duration_seconds=0, path_patterns=("cct-probe",))
_RUNAWAY = RunawayConfig(recent_minutes=60, max_turns_recent=10, recent_turns=8,
                         max_error_share=0.5, min_turns_for_error_share=4, max_cost_recent_usd=5.0)
NO_BUDGETS = BudgetsConfig(None, None, None, None)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rollup(cost, priced=1, priceable=1, sessions=1, turns=1):
    return {"sessions": sessions, "turns": turns, "cost_usd": cost, "priced_turns": priced, "priceable_turns": priceable}


def _status(**over):
    base = {
        "developers": [], "projects": [],
        "totals": {"windows": {"today": _rollup(None, 0, 0), "7d": _rollup(None, 0, 0), "30d": _rollup(None, 0, 0)}},
    }
    base.update(over)
    return base


class TestBudgetAlerts(unittest.TestCase):
    def test_thresholds_79_80_100_and_no_priced_turn_never_breaches(self) -> None:
        b = BudgetsConfig(team_daily_usd=100.0, team_monthly_usd=None, developer_daily_usd=None, project_daily_usd=None)
        for spent, expected in ((79.0, None), (80.0, C.ALERT_WARNING), (99.99, C.ALERT_WARNING), (100.0, C.ALERT_BREACH), (250.0, C.ALERT_BREACH)):
            s = _status(totals={"windows": {"today": _rollup(spent), "7d": _rollup(spent), "30d": _rollup(spent)}})
            got = A.budget_alerts(s, b)
            self.assertEqual(got[0]["level"] if got else None, expected, spent)
        s = _status(totals={"windows": {"today": _rollup(None, 0, 40), "7d": _rollup(None, 0, 40), "30d": _rollup(None, 0, 40)}})
        self.assertEqual(A.budget_alerts(s, b), [])   # 40 unpriced turns: no verdict, not a breach

    def test_zero_budget_breaches_at_any_priced_spend_without_a_percentage(self) -> None:
        # 0 is "no spending", accepted by config (non-negative): any priced
        # cent is a breach, and the message has no percentage to compute
        # (the reviewer reproduced an overflow here at 612d03a).
        b = BudgetsConfig(team_daily_usd=0.0, team_monthly_usd=None, developer_daily_usd=None, project_daily_usd=None)
        s = _status(totals={"windows": {"today": _rollup(0.5, priced=1, priceable=3), "7d": _rollup(0.5), "30d": _rollup(0.5)}})
        got = A.budget_alerts(s, b)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["level"], C.ALERT_BREACH)
        self.assertEqual(got[0]["message"], "the team has spent $0.50 today against a $0.00 budget; 2 priceable turns had no price, so the true spend is higher.")
        self.assertIsNone(got[0]["figures"]["share"])
        self.assertNotIn("%", got[0]["message"])
        # nothing spent (a priced zero) against a zero budget: no alert
        s = _status(totals={"windows": {"today": _rollup(0.0), "7d": _rollup(0.0), "30d": _rollup(0.0)}})
        self.assertEqual(A.budget_alerts(s, b), [])
        # and the whole surface survives it, which is what crashed before
        A.render_alerts({"alerts": got, "breaches": 1, "warnings": 0, "budgets": {"team_daily_usd": 0.0},
                         "runaway": {"recent_minutes": 60, "max_turns_recent": 300, "recent_turns": 50,
                                     "max_error_share": 0.5, "min_turns_for_error_share": 20, "max_cost_recent_usd": 20.0},
                         "derived": True})

    def test_unpriced_turns_are_named_and_scopes_are_separate(self) -> None:
        b = BudgetsConfig(team_daily_usd=None, team_monthly_usd=1000.0, developer_daily_usd=10.0, project_daily_usd=20.0)
        s = _status(
            developers=[{"developer_id": "ana", "windows": {"today": _rollup(12.0, priced=3, priceable=10), "7d": _rollup(12.0), "30d": _rollup(12.0)}},
                        {"developer_id": "ben", "windows": {"today": _rollup(1.0), "7d": _rollup(1.0), "30d": _rollup(1.0)}}],
            projects=[{"project_path": "/repo/proj", "windows": {"today": _rollup(17.0), "7d": _rollup(17.0), "30d": _rollup(17.0)}}],
            totals={"windows": {"today": _rollup(13.0), "7d": _rollup(13.0), "30d": _rollup(1200.0, priced=5, priceable=5)}},
        )
        got = A.budget_alerts(s, b)
        kinds = {(a["scope"], a["subject"], a["level"]) for a in got}
        self.assertEqual(kinds, {("team", "team", C.ALERT_BREACH), ("developer", "ana", C.ALERT_BREACH), ("project", "/repo/proj", C.ALERT_WARNING)})
        ana = next(a for a in got if a["subject"] == "ana")
        self.assertIn("7 priceable turns had no price, so the true spend is higher", ana["message"])
        self.assertEqual(ana["figures"]["unpriced_turns"], 7)
        team = next(a for a in got if a["scope"] == "team")
        self.assertNotIn("no price", team["message"])
        self.assertIn("120% of the $1000.00 budget in the last 30 days", team["message"])
        proj = next(a for a in got if a["scope"] == "project")
        self.assertIn("proj is at 85%", proj["message"])

    def test_no_budgets_no_alerts(self) -> None:
        s = _status(totals={"windows": {"today": _rollup(1e6), "7d": _rollup(1e6), "30d": _rollup(1e6)}})
        self.assertEqual(A.budget_alerts(s, NO_BUDGETS), [])


class TestRunawayAlerts(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = Database.connect(self.sqlite_dsn())
        apply_ddl(self.db)
        self.addCleanup(self.db.close)

    def _session(self, native: str, project="/repo/proj", dev="ana") -> int:
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, turn_count, started_at, duration_seconds) "
            "VALUES (?, ?, ?, ?, 0, ?, 60)", (C.COPILOT_CLAUDE_CODE, native, project, dev, _iso(NOW)))
        return int(self.db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", (native,))[0])

    def _turns(self, sid: int, n: int, *, minutes_ago_each, cost=None, error_every=None, start_seq=1) -> None:
        for i in range(n):
            seq = start_seq + i
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, content_preview, timestamp, cost_usd, model) "
                "VALUES (?, ?, ?, '', ?, ?, 'm')",
                (sid, seq, C.ROLE_ASSISTANT, _iso(NOW - timedelta(minutes=minutes_ago_each)), cost))
            if error_every and seq % error_every == 0:
                tid = int(self.db.query_one("SELECT id FROM copilot_turn WHERE session_id = ? AND sequence_num = ?", (sid, seq))[0])
                self.db.execute("INSERT INTO copilot_error (session_id, turn_id, error_type) VALUES (?, ?, 'E')", (sid, tid))
        self.db.commit()

    def _alerts(self, noise=_NOISE):
        return A.runaway_alerts(self.db, _RUNAWAY, noise=noise, now=NOW)

    def test_turn_rate(self) -> None:
        fast = self._session("fast")
        self._turns(fast, 11, minutes_ago_each=5)                  # 11 > 10 in the last hour
        slow = self._session("slow")
        self._turns(slow, 11, minutes_ago_each=90)                 # same count, but not recent
        got = self._alerts()
        self.assertEqual([(a["kind"], a["subject"]["session_id"]) for a in got], [(A.KIND_RUNAWAY_TURNS, fast)])
        self.assertIn("11 turns in the last 60 minutes (threshold 10) and is still going", got[0]["message"])
        self.assertEqual(got[0]["figures"], {"recent_turns": 11, "threshold": 10, "recent_minutes": 60})

    def test_error_share_with_the_min_turns_guard(self) -> None:
        noisy = self._session("noisy")
        self._turns(noisy, 6, minutes_ago_each=3, error_every=1)  # 6 of last 6 errored, 6 >= 4
        few = self._session("few")
        self._turns(few, 3, minutes_ago_each=3, error_every=1)    # 3 < min 4: no verdict
        got = self._alerts()
        self.assertEqual([(a["kind"], a["subject"]["session_id"]) for a in got], [(A.KIND_RUNAWAY_ERRORS, noisy)])
        self.assertIn("6 of its last 6 turns errored (100%, threshold 50%)", got[0]["message"])

    def test_cost_rate_and_unpriced_never_alerts(self) -> None:
        pricey = self._session("pricey")
        self._turns(pricey, 3, minutes_ago_each=2, cost=2.0)      # $6 > $5
        free = self._session("free")
        self._turns(free, 9, minutes_ago_each=2, cost=None)       # unpriced: no cost verdict
        got = self._alerts()
        self.assertEqual([(a["kind"], a["subject"]["session_id"]) for a in got], [(A.KIND_RUNAWAY_COST, pricey)])
        self.assertIn("spent $6.00 in the last 60 minutes (threshold $5.00)", got[0]["message"])

    def test_noise_never_alerts_and_report_shape(self) -> None:
        probe = self._session("probe", project="/tmp/cct-probe.x")
        self._turns(probe, 20, minutes_ago_each=1, cost=9.0, error_every=1)
        self.assertEqual(self._alerts(), [])
        self.assertEqual(len(self._alerts(noise=None)), 3)      # every kind fires without the rule
        status = T.team_status(self.db, noise=_NOISE, active_window_seconds=300, now=NOW)
        report = A.all_alerts(self.db, status, budgets=NO_BUDGETS, runaway=_RUNAWAY, noise=_NOISE, now=NOW)
        self.assertEqual((report["alerts"], report["breaches"], report["warnings"], report["derived"]), ([], 0, 0, True))
        self.assertEqual(report["budgets"][C.CFG_BUDGET_TEAM_DAILY], None)
        lines = A.render_alerts(report)
        self.assertEqual(lines[0], "No alerts.")
        self.assertIn("Budgets: none set", lines[2])
        self.assertIn("> 10 turns or > $5.00 in 60 min", lines[3])

    def test_breaches_first_and_levels(self) -> None:
        fast = self._session("fast")
        self._turns(fast, 11, minutes_ago_each=5)
        status = T.team_status(self.db, noise=_NOISE, active_window_seconds=300, now=NOW)
        status["totals"]["windows"]["today"] = _rollup(85.0)
        report = A.all_alerts(self.db, status, budgets=BudgetsConfig(100.0, None, None, None), runaway=_RUNAWAY, noise=_NOISE, now=NOW)
        self.assertEqual([a["level"] for a in report["alerts"]], [C.ALERT_BREACH, C.ALERT_WARNING])
        self.assertEqual((report["breaches"], report["warnings"]), (1, 1))
        self.assertEqual(A.worst_level(report["alerts"]), C.ALERT_BREACH)
        self.assertTrue(A.at_or_above(C.ALERT_WARNING, C.ALERT_WARNING))
        self.assertFalse(A.at_or_above(C.ALERT_WARNING, C.ALERT_BREACH))
        self.assertIsNone(A.worst_level([]))


if __name__ == "__main__":
    unittest.main()
