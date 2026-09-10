# Tests for budgets, runaway detection and alerts (#174 Slice D), and for
# the auto-build cap alerts (auto-build-cap-alerts FR-1..FR-4): every
# function named cap_fr<N> is the verifier verification.yaml selects for
# FR-N with `-k cap_fr<N>`.

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


# ── auto-build cap alerts (auto-build-cap-alerts) ──────────────────────

RUN_KEY = "47908-474720888"


def _run(**over) -> dict:
    """A run record in the shape api.auto_build.read_run returns: still
    building, 73% of a $10 cap, 10 minutes into a 90-minute cap."""
    base = {
        "key": RUN_KEY, "feature_id": "team-developer-aliases", "profile": "unattended",
        "status": "building", "outcome": None, "concluded": False, "live": True,
        "started_at": "2026-09-09T16:22:03Z", "updated_at": "2026-09-09T16:31:46Z", "elapsed_sec": 600,
        "caps": {"phases": 2, "fix_sessions_per_phase": 2, "wall_clock_sec": 5400, "cost_usd": 10.0},
        "cost": {"metered_usd": 5.3, "estimated_usd": 2.0},
        "pr": {"number": 331, "url": "https://github.com/gosha70/code-copilot-team/pull/331"},
        "ledger": "auto-build/team-developer-aliases",
    }
    base.update(over)
    return base


def _cost(spent: float, cap=10.0, estimated=0.0, **over) -> dict:
    return _run(cost={"metered_usd": spent - estimated, "estimated_usd": estimated},
                caps={"wall_clock_sec": None, "cost_usd": cap}, **over)


def _clock(elapsed, cap=1000, **over) -> dict:
    return _run(elapsed_sec=elapsed, caps={"wall_clock_sec": cap, "cost_usd": None}, **over)


def _live_state(*, cost_usd: float, cap_usd: float, started: datetime, updated: datetime) -> dict:
    """state.json for a run the driver has not concluded."""
    return {
        "schema_version": 1, "feature_id": "cap-alerts-fixture", "profile": "unattended",
        "attempt_id": RUN_KEY, "status": "building", "current_phase": 1, "phases": {},
        "branch": "feature/cap-alerts", "branch_base_ref": "0" * 40,
        "caps": {"max_phases": 2, "max_fix_sessions_per_phase": 2,
                 "max_wall_clock_sec": 86400, "max_cost_usd": cap_usd},
        "outcome": None, "escalations": [], "pr": {"number": None, "url": None},
        "totals": {"cost_usd": cost_usd, "cost_estimated_usd": 0,
                   "started_epoch": int(started.timestamp())},
        "updated": updated.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _ledger_root(state: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="cct-cap-alerts-"))
    ledger = root / C.AUTO_BUILD_LIVE_DIR / "cap-alerts-fixture"
    ledger.mkdir(parents=True)
    (ledger / C.LEDGER_STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    return root


class TestAutoBuildCapAlerts(unittest.TestCase):
    def test_cap_fr1_cost_and_clock_shares_at_the_boundaries(self) -> None:
        # 80% of the cap is the warning, the cap itself is the breach —
        # the same two thresholds a budget uses, so a person reading the
        # card does not have to hold two rules.
        for spent, expected in ((7.9, None), (8.0, C.ALERT_WARNING), (9.99, C.ALERT_WARNING),
                                (10.0, C.ALERT_BREACH), (25.0, C.ALERT_BREACH)):
            got = A.auto_build_alerts([_cost(spent)])
            self.assertEqual([a["level"] for a in got], [] if expected is None else [expected], spent)
            self.assertEqual([a["kind"] for a in got], [] if expected is None else [A.KIND_AUTO_BUILD_COST])
        for elapsed, expected in ((799, None), (800, C.ALERT_WARNING), (999, C.ALERT_WARNING),
                                  (1000, C.ALERT_BREACH), (4000, C.ALERT_BREACH)):
            got = A.auto_build_alerts([_clock(elapsed)])
            self.assertEqual([a["level"] for a in got], [] if expected is None else [expected], elapsed)
            self.assertEqual([a["kind"] for a in got], [] if expected is None else [A.KIND_AUTO_BUILD_WALL_CLOCK])

    def test_cap_fr2_percent_below_the_cap_never_reads_as_100(self) -> None:
        # DeepSeek's review of the first revision: 9.99 of 10.00 rounded
        # to "(100%)" beside level warning. Below the cap the percentage
        # is rounded but held at 99 at most; at and above it, rounded.
        alert, = A.auto_build_alerts([_cost(9.99)])
        self.assertEqual(alert["level"], C.ALERT_WARNING)
        self.assertIn("(99%)", alert["message"])
        alert, = A.auto_build_alerts([_cost(10.0)])
        self.assertEqual(alert["level"], C.ALERT_BREACH)
        self.assertIn("(100%)", alert["message"])
        alert, = A.auto_build_alerts([_clock(999)])
        self.assertIn("(99%)", alert["message"])

    def test_cap_fr1_cost_share_counts_the_estimated_portion(self) -> None:
        # The driver's cap is set against metered + estimated, so the
        # alert is too: $5.00 metered alone is 50% and silent, but with
        # $3.50 estimated on top it is 85% of the cap.
        self.assertEqual(A.auto_build_alerts([_cost(5.0)]), [])
        got = A.auto_build_alerts([_cost(8.5, estimated=3.5)])
        self.assertEqual([a["level"] for a in got], [C.ALERT_WARNING])
        self.assertEqual(got[0]["figures"]["spent_usd"], 8.5)
        self.assertEqual(got[0]["figures"]["estimated_usd"], 3.5)

    def test_cap_fr1_absent_or_non_positive_caps_and_concluded_runs_never_alert(self) -> None:
        for cap in (None, 0.0, -1.0):
            self.assertEqual(A.auto_build_alerts([_cost(1e6, cap=cap)]), [], cap)
            self.assertEqual(A.auto_build_alerts([_clock(1e6, cap=cap)]), [], cap)
        # A run the driver finished is history, not something to watch —
        # whatever it spent (the Runs tab is where it is read).
        for status in ("done", "terminated_policy", "parked"):
            self.assertEqual(A.auto_build_alerts([_cost(25.0, concluded=True, status=status)]), [], status)
        # Not live but not concluded either: a build phase longer than the
        # active window is still a run burning its cap.
        self.assertEqual(len(A.auto_build_alerts([_cost(25.0, live=False)])), 1)
        # An empty list is not an error, and neither is a run with no
        # figures the ledger never wrote.
        self.assertEqual(A.auto_build_alerts([]), [])
        self.assertEqual(A.auto_build_alerts([_run(cost={}, elapsed_sec=None)]), [])

    def test_cap_fr1_one_alert_per_run_per_cap(self) -> None:
        both = _run(cost={"metered_usd": 9.0, "estimated_usd": 0.0}, elapsed_sec=5000)
        other = _run(key="1-2", feature_id="another", cost={"metered_usd": 0.1, "estimated_usd": 0.0})
        got = A.auto_build_alerts([both, other])
        self.assertEqual([(a["kind"], a["subject"]["key"]) for a in got],
                         [(A.KIND_AUTO_BUILD_COST, RUN_KEY), (A.KIND_AUTO_BUILD_WALL_CLOCK, RUN_KEY)])

    def test_cap_fr2_alert_shape_and_message_name_the_run_and_the_figures(self) -> None:
        alert, = A.auto_build_alerts([_cost(8.5, estimated=2.0)])
        self.assertEqual(alert["kind"], "auto-build-cost")
        self.assertEqual(alert["level"], C.ALERT_WARNING)
        self.assertEqual(alert["scope"], "run")
        self.assertIsNone(alert["window"])
        self.assertEqual(alert["subject"], {"key": RUN_KEY, "feature_id": "team-developer-aliases",
                                            "ledger": "auto-build/team-developer-aliases", "pr_number": 331})
        self.assertEqual(alert["figures"], {"spent_usd": 8.5, "estimated_usd": 2.0, "cap_usd": 10.0, "share": 0.85})
        self.assertEqual(
            alert["message"],
            "auto-build run team-developer-aliases (47908-474720888) has spent $8.50 of its $10.00 cap "
            "(85%, $2.00 estimated) and is still running.")
        # Nothing estimated: no parenthetical aside about a guess.
        plain, = A.auto_build_alerts([_cost(8.5)])
        self.assertEqual(
            plain["message"],
            "auto-build run team-developer-aliases (47908-474720888) has spent $8.50 of its $10.00 cap "
            "(85%) and is still running.")

    def test_cap_fr2_wall_clock_alert_shape_and_message(self) -> None:
        alert, = A.auto_build_alerts([_clock(4800, cap=5400)])
        self.assertEqual(alert["kind"], "auto-build-wall-clock")
        self.assertEqual(alert["level"], C.ALERT_WARNING)
        self.assertEqual(alert["scope"], "run")
        self.assertEqual(alert["figures"], {"elapsed_sec": 4800, "cap_sec": 5400, "share": 0.89})
        self.assertEqual(
            alert["message"],
            "auto-build run team-developer-aliases (47908-474720888) has run 80 min of its 90 min "
            "wall-clock cap (89%) and is still running.")
        breach, = A.auto_build_alerts([_clock(5583, cap=5400)])
        self.assertEqual(breach["level"], C.ALERT_BREACH)
        self.assertIn("has run 93 min of its 90 min wall-clock cap (103%)", breach["message"])
        # A run whose ledger names no feature is still named by its key.
        unnamed, = A.auto_build_alerts([_clock(5000, feature_id=None)])
        self.assertIn(f"auto-build run an unnamed feature ({RUN_KEY})", unnamed["message"])


class TestAutoBuildInTheReport(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = Database.connect(self.sqlite_dsn())
        apply_ddl(self.db)
        self.addCleanup(self.db.close)

    def _report(self, runs, **over):
        kwargs = {"budgets": NO_BUDGETS, "runaway": _RUNAWAY, "noise": _NOISE, "now": NOW}
        kwargs.update(over)
        return A.all_alerts(self.db, _status(), runs=runs, **kwargs)

    def test_cap_fr3_runs_not_read_is_said_not_passed_off_as_quiet(self) -> None:
        report = self._report(None)
        self.assertEqual(report[C.ALERT_AUTO_BUILD],
                         {C.ALERT_AUTO_BUILD_EVALUATED: False, C.ALERT_AUTO_BUILD_LIVE_RUNS: 0})
        self.assertEqual(report["alerts"], [])
        self.assertIn("Auto-build: runs not evaluated.", A.render_alerts(report))

    def test_cap_fr3_report_block_counts_the_runs_still_running(self) -> None:
        report = self._report([_cost(1.0), _run(concluded=True, status="done"), _cost(9.0, live=False)])
        self.assertEqual(report[C.ALERT_AUTO_BUILD],
                         {C.ALERT_AUTO_BUILD_EVALUATED: True, C.ALERT_AUTO_BUILD_LIVE_RUNS: 2})
        self.assertEqual((report["breaches"], report["warnings"], report["derived"]), (0, 1, True))
        line = next(ln for ln in A.render_alerts(report) if ln.startswith("Auto-build:"))
        self.assertEqual(line, "Auto-build: runs evaluated, 2 still running; a run at 80% of its cost "
                               "or wall-clock cap warns, at 100% breaches.")

    def test_cap_fr3_auto_build_alerts_sort_and_render_with_the_others(self) -> None:
        status = _status(totals={"windows": {"today": _rollup(85.0), "7d": _rollup(85.0), "30d": _rollup(85.0)}})
        report = A.all_alerts(
            self.db, status, budgets=BudgetsConfig(100.0, None, None, None), runaway=_RUNAWAY,
            noise=_NOISE, now=NOW, runs=[_cost(11.0), _clock(850)])
        self.assertEqual([a["level"] for a in report["alerts"]],
                         [C.ALERT_BREACH, C.ALERT_WARNING, C.ALERT_WARNING])
        self.assertEqual([a["kind"] for a in report["alerts"]],
                         [A.KIND_AUTO_BUILD_COST, A.KIND_AUTO_BUILD_WALL_CLOCK, A.KIND_BUDGET])
        self.assertEqual((report["breaches"], report["warnings"]), (1, 2))
        self.assertEqual(A.worst_level(report["alerts"]), C.ALERT_BREACH)
        rendered = A.render_alerts(report)
        self.assertTrue(rendered[0].startswith("[BREACH ] auto-build-cost: auto-build run"))
        self.assertIn("has spent $11.00 of its $10.00 cap (110%)", rendered[0])
        self.assertIn("[WARNING] auto-build-wall-clock:", rendered[1])
        # The existing families keep their lines and their configuration.
        self.assertIn("[WARNING] budget:", rendered[2])
        self.assertTrue(any(ln.startswith("Budgets: ") for ln in rendered))
        self.assertTrue(any(ln.startswith("Runaway: ") for ln in rendered))


class TestAutoBuildAlertsOverALedgerRoot(RegistryResetTestCase):
    """FR-4: the route reads the ledgers with the loaded auto_build config."""

    def setUp(self) -> None:
        super().setUp()
        self.dsn = self.sqlite_dsn()
        db = Database.connect(self.dsn)
        apply_ddl(db)
        db.close()
        started = datetime.now(timezone.utc) - timedelta(seconds=600)
        self.root = _ledger_root(_live_state(
            cost_usd=9.0, cap_usd=10.0, started=started, updated=datetime.now(timezone.utc)))

    def _client(self, root: Path):
        import importlib.util
        from unittest import mock

        if importlib.util.find_spec("fastapi") is None or importlib.util.find_spec("httpx") is None:
            self.skipTest("fastapi/httpx not installed; API test skipped (covered in CI)")
        from fastapi.testclient import TestClient

        from session_analytics import config as cfgmod
        from session_analytics._register import register_all
        from session_analytics.api.server import create_app

        register_all()
        patches = [
            mock.patch.object(cfgmod, "_USER_CONFIG", Path("/nonexistent/session-analytics.json")),
            mock.patch.object(cfgmod, "parse_env_file", return_value={}),
            mock.patch.dict("os.environ", {cfgmod.ENV_AUTO_BUILD_ROOT: str(root)}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return TestClient(create_app(self.dsn), base_url="http://127.0.0.1:8765")

    def test_cap_fr4_team_routes_carry_the_cap_alert(self) -> None:
        client = self._client(self.root)
        for path in ("/api/team/alerts", "/api/team/status"):
            body = client.get(path).json()
            report = body if path.endswith("alerts") else body["alerts"]
            self.assertEqual(report[C.ALERT_AUTO_BUILD],
                             {C.ALERT_AUTO_BUILD_EVALUATED: True, C.ALERT_AUTO_BUILD_LIVE_RUNS: 1}, path)
            alert, = [a for a in report["alerts"] if a["kind"] == A.KIND_AUTO_BUILD_COST]
            self.assertEqual((alert["level"], alert["subject"]["key"]), (C.ALERT_WARNING, RUN_KEY), path)
            self.assertIn("has spent $9.00 of its $10.00 cap (90%)", alert["message"])

    def test_cap_fr4_a_root_that_is_not_a_directory_is_zero_runs_not_an_error(self) -> None:
        client = self._client(self.root / "nowhere")
        report = client.get("/api/team/alerts").json()
        self.assertEqual(report[C.ALERT_AUTO_BUILD],
                         {C.ALERT_AUTO_BUILD_EVALUATED: True, C.ALERT_AUTO_BUILD_LIVE_RUNS: 0})
        self.assertEqual(report["alerts"], [])
        self.assertIn("Auto-build: runs evaluated, 0 still running", "\n".join(A.render_alerts(report)))


if __name__ == "__main__":
    unittest.main()
