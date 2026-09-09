# Tests for the team store's status (#174 B2 + C): liveness from
# heartbeats, windows by turn timestamp, cost honesty, noise policy.

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

from session_analytics import constants as C
from session_analytics.api import team as T
from session_analytics.config import NoiseConfig
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import RegistryResetTestCase

NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
_NOISE = NoiseConfig(min_turns=0, min_duration_seconds=0, path_patterns=("cct-probe",))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestTeamStatus(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.db = Database.connect(self.sqlite_dsn())
        apply_ddl(self.db)
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO developer (developer_id, display_name) VALUES (?, ?)", ("ana", "Ana"))
        self.db.execute("INSERT INTO developer (developer_id, display_name) VALUES (?, ?)", ("registered-only", None))
        # ana: active heartbeat, turns today and 20 days ago; ben: idle
        # heartbeat, one turn 3 days ago, unpriced; cy: no heartbeat,
        # a probe session (noise) with a turn today.
        self.ana = self._session("ana", "/repo/proj", "s-ana")
        self.ben = self._session("ben", "/repo/other", "s-ben")
        self.cy = self._session("cy", "/tmp/cct-probe.x", "s-cy")
        self._turn(self.ana, 1, NOW - timedelta(hours=1), 1.25, "m")
        self._turn(self.ana, 2, NOW - timedelta(days=20), 2.00, "m")
        self._turn(self.ana, 3, NOW - timedelta(days=40), 99.0, "m")     # outside 30d
        self._turn(self.ana, 4, NOW - timedelta(minutes=5), None, "m")    # priceable, unpriced
        self._turn(self.ana, 5, None, 5.0, "m")                            # unstamped
        self._turn(self.ben, 1, NOW - timedelta(days=3), None, "m")
        self._turn(self.cy, 1, NOW - timedelta(minutes=1), 7.0, "m")
        self._beat("/repo/proj", "ana", "build", "174-team", 12, NOW - timedelta(seconds=60))
        self._beat("/repo/old", "ana", "plan", "old", 1, NOW - timedelta(days=2))   # older beat, ignored
        self._beat("/repo/other", "ben", "research", None, 3, NOW - timedelta(hours=2))
        self.db.commit()

    def _session(self, dev: str, project: str, native: str) -> int:
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, turn_count, "
            "started_at, duration_seconds) VALUES (?, ?, ?, ?, 5, ?, 600)",
            (C.COPILOT_CLAUDE_CODE, native, project, dev, _iso(NOW)),
        )
        return int(self.db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", (native,))[0])

    def _turn(self, sid: int, seq: int, at, cost, model) -> None:
        self.db.execute(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, content_preview, timestamp, cost_usd, model) "
            "VALUES (?, ?, ?, '', ?, ?, ?)",
            (sid, seq, C.ROLE_ASSISTANT, _iso(at) if at else None, cost, model),
        )

    def _beat(self, project, dev, phase, feature, count, at) -> None:
        self.db.execute(
            f"INSERT INTO {C.TBL_LOCAL_HEARTBEAT} (project_path, developer_id, phase, feature_id, checkpoint_count, "
            "last_heartbeat_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project, dev, phase, feature, count, _iso(at)),
        )

    def _status(self, noise=_NOISE, window=300):
        return T.team_status(self.db, noise=noise, active_window_seconds=window, now=NOW)

    def test_liveness_is_last_seen_never_a_verdict(self) -> None:
        self.assertEqual(T.liveness(_iso(NOW - timedelta(seconds=299)), NOW, 300), "active")
        self.assertEqual(T.liveness(_iso(NOW - timedelta(seconds=301)), NOW, 300), "idle")
        self.assertEqual(T.liveness(None, NOW, 300), "unknown")
        self.assertEqual(T.liveness("not a time", NOW, 300), "unknown")

    def test_developers_liveness_current_work_and_order(self) -> None:
        s = self._status()
        by = {d["developer_id"]: d for d in s["developers"]}
        self.assertEqual([d["developer_id"] for d in s["developers"]][:2], ["ana", "ben"])
        self.assertEqual(by["ana"]["liveness"], "active")
        self.assertEqual(by["ana"]["display_name"], "Ana")
        # the NEWEST heartbeat is the current work, not the older project
        self.assertEqual((by["ana"]["current"]["project_path"], by["ana"]["current"]["phase"],
                          by["ana"]["current"]["feature_id"], by["ana"]["current"]["checkpoint_count"]),
                         ("/repo/proj", "build", "174-team", 12))
        self.assertEqual(by["ben"]["liveness"], "idle")
        self.assertEqual(by["registered-only"]["liveness"], "unknown")
        self.assertIsNone(by["registered-only"]["current"])
        self.assertEqual(s["totals"]["active_now"], 1)
        self.assertEqual(s["active_window_seconds"], 300)

    def test_windows_by_turn_timestamp_and_cost_honesty(self) -> None:
        by = {d["developer_id"]: d for d in self._status()["developers"]}
        ana = by["ana"]["windows"]
        # today: the 1h-ago priced turn and the 5-min-ago unpriced one
        self.assertEqual((ana["today"]["turns"], ana["today"]["cost_usd"], ana["today"]["priced_turns"],
                          ana["today"]["priceable_turns"]), (2, 1.25, 1, 2))
        self.assertEqual((ana["7d"]["turns"], ana["7d"]["cost_usd"]), (2, 1.25))
        # 30d adds the 20-day-old turn, not the 40-day-old one
        self.assertEqual((ana["30d"]["turns"], ana["30d"]["cost_usd"]), (3, 3.25))
        self.assertEqual(ana["30d"]["sessions"], 1)
        # ben: one unpriced turn → cost None, never 0
        self.assertIsNone(by["ben"]["windows"]["7d"]["cost_usd"])
        self.assertEqual(by["ben"]["windows"]["7d"]["priceable_turns"], 1)
        self.assertEqual(by["ben"]["windows"]["today"]["turns"], 0)

    def test_noise_policy_and_unstamped_turns(self) -> None:
        s = self._status()
        ids = {d["developer_id"] for d in s["developers"]}
        # cy's only session is a probe: not a developer the team view counts
        self.assertNotIn("cy", ids)
        self.assertEqual(s["totals"]["windows"]["today"]["cost_usd"], 1.25)
        self.assertEqual(s["totals"]["unstamped_turns"], 1)
        everything = self._status(noise=None)
        self.assertIn("cy", {d["developer_id"] for d in everything["developers"]})
        self.assertEqual(everything["totals"]["windows"]["today"]["cost_usd"], 8.25)

    def test_projects_and_store(self) -> None:
        s = self._status()
        self.assertEqual(s["store"], {"dialect": "sqlite", "shared": False})
        self.assertEqual([p["project_path"] for p in s["projects"]], ["/repo/proj", "/repo/other"])
        self.assertEqual(s["projects"][0]["developers"], ["ana"])
        self.assertEqual(s["projects"][1]["windows"]["7d"]["sessions"], 1)

    def test_render_status_is_the_same_figures(self) -> None:
        lines = T.render_status(self._status())
        self.assertIn("local store (SQLite)", lines[0])
        self.assertIn("1 of 3 active", lines[0])
        ana = next(line for line in lines if line.startswith("Ana (ana)"))
        self.assertIn("active", ana)
        self.assertIn("proj · build · 174-team", ana)
        self.assertIn("$1.25*", ana)      # today: partial pricing
        self.assertIn("$3.25*", ana)      # 30d
        ben = next(line for line in lines if line.startswith("ben"))
        self.assertIn("idle", ben)
        self.assertRegex(ben, r"—\s+—\s+—$")
        self.assertTrue(any("1 turns without a timestamp" in line for line in lines))


class TestTeamAliases(RegistryResetTestCase):
    """FR-2/FR-3/FR-4: ids the operator listed under one name are one
    row, added together, at read time — the store keeps every id."""

    #: Order matters: the row's id is the FIRST folded id named here.
    #: "ghost" is an alias for an id the store has never seen.
    ALIASES = {
        "i-am-goga": "Gosha",
        "i-am-goga-gmail-com": "Gosha",
        "local": "Gosha",
        "dee-one": "Dee",
        "dee-two": "Dee",
        "ghost": "Gosha",
    }

    def setUp(self) -> None:
        super().setUp()
        self.db = Database.connect(self.sqlite_dsn())
        apply_ddl(self.db)
        self.addCleanup(self.db.close)
        # The developer table names one of the folded ids: the alias
        # name must win over it (FR-4).
        self.db.execute(
            "INSERT INTO developer (developer_id, display_name) VALUES (?, ?)",
            ("i-am-goga", "From The Developer Table"),
        )
        goga = self._session("i-am-goga", "/repo/a", "s-goga")
        gmail = self._session("i-am-goga-gmail-com", "/repo/a", "s-gmail")
        old = self._session("local", "/repo/b", "s-local")
        ben = self._session("ben", "/repo/b", "s-ben")
        d1 = self._session("dee-one", "/repo/c", "s-d1")
        d2 = self._session("dee-two", "/repo/c", "s-d2")
        self._turn(goga, 1, NOW - timedelta(hours=1), 1.00, "m")
        self._turn(goga, 2, NOW - timedelta(minutes=5), None, "m")   # priceable, unpriced
        self._turn(gmail, 1, NOW - timedelta(hours=2), 0.50, "m")
        self._turn(old, 1, NOW - timedelta(days=3), None, "m")
        self._turn(ben, 1, NOW - timedelta(hours=1), 0.25, "m")
        self._turn(d1, 1, NOW - timedelta(hours=1), None, "m")
        self._turn(d2, 1, NOW - timedelta(hours=1), None, "m")
        # The oldest id carries the NEWEST heartbeat: the folded row's
        # current work must come from it, not from the row's own id.
        self._beat("/repo/a", "i-am-goga", "build", "old-work", 2, NOW - timedelta(minutes=30))
        self._beat("/repo/b", "local", "review", "174-team", 7, NOW - timedelta(seconds=60))
        self.db.commit()

    def _session(self, dev: str, project: str, native: str) -> int:
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, turn_count, "
            "started_at, duration_seconds) VALUES (?, ?, ?, ?, 5, ?, 600)",
            (C.COPILOT_CLAUDE_CODE, native, project, dev, _iso(NOW)),
        )
        return int(self.db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", (native,))[0])

    def _turn(self, sid: int, seq: int, at, cost, model) -> None:
        self.db.execute(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, content_preview, timestamp, cost_usd, model) "
            "VALUES (?, ?, ?, '', ?, ?, ?)",
            (sid, seq, C.ROLE_ASSISTANT, _iso(at) if at else None, cost, model),
        )

    def _beat(self, project, dev, phase, feature, count, at) -> None:
        self.db.execute(
            f"INSERT INTO {C.TBL_LOCAL_HEARTBEAT} (project_path, developer_id, phase, feature_id, checkpoint_count, "
            "last_heartbeat_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project, dev, phase, feature, count, _iso(at)),
        )

    def _status(self, aliases=None, window=300):
        return T.team_status(
            self.db, noise=_NOISE, active_window_seconds=window, now=NOW, aliases=aliases)

    def test_alias_fr2_folds_ids_sharing_a_name_and_lists_merged_ids(self) -> None:
        rows = {d["developer_id"]: d for d in self._status(self.ALIASES)["developers"]}
        self.assertEqual(
            rows["i-am-goga"]["merged_ids"],
            ["i-am-goga", "i-am-goga-gmail-com", "local"],
        )
        self.assertEqual(rows["i-am-goga"]["display_name"], "Gosha")
        # the folded ids no longer stand on their own
        self.assertNotIn("i-am-goga-gmail-com", rows)
        self.assertNotIn("local", rows)
        # an alias for an id with no rows names nobody
        self.assertNotIn("ghost", rows)
        self.assertNotIn("ghost", rows["i-am-goga"]["merged_ids"])
        # an unaliased id is its own row, and still carries merged_ids
        self.assertEqual(rows["ben"]["merged_ids"], ["ben"])
        self.assertIsNone(rows["ben"]["display_name"])
        self.assertEqual(sorted(rows), ["ben", "dee-one", "i-am-goga"])
        self.assertEqual(self._status(self.ALIASES)["totals"]["developers"], 3)

    def test_alias_fr2_no_aliases_leaves_every_id_alone(self) -> None:
        rows = {d["developer_id"]: d for d in self._status()["developers"]}
        self.assertEqual(
            sorted(rows),
            ["ben", "dee-one", "dee-two", "i-am-goga", "i-am-goga-gmail-com", "local"],
        )
        self.assertEqual(rows["local"]["merged_ids"], ["local"])
        self.assertEqual(rows["i-am-goga"]["display_name"], "From The Developer Table")

    def test_alias_fr3_windows_sum_over_the_folded_ids(self) -> None:
        rows = {d["developer_id"]: d for d in self._status(self.ALIASES)["developers"]}
        today = rows["i-am-goga"]["windows"]["today"]
        # 1.00 + unpriced (i-am-goga) + 0.50 (…-gmail-com); "local" is 3 days old
        self.assertEqual(
            (today["sessions"], today["turns"], today["cost_usd"],
             today["priced_turns"], today["priceable_turns"]),
            (2, 3, 1.50, 2, 3),
        )
        week = rows["i-am-goga"]["windows"]["7d"]
        self.assertEqual((week["sessions"], week["turns"], week["cost_usd"]), (3, 4, 1.50))
        # the totals are unchanged by the fold — the same turns, regrouped
        self.assertEqual(self._status(self.ALIASES)["totals"]["windows"]["7d"],
                         self._status()["totals"]["windows"]["7d"])

    def test_alias_fr3_cost_is_null_when_no_folded_id_is_priced(self) -> None:
        rows = {d["developer_id"]: d for d in self._status(self.ALIASES)["developers"]}
        self.assertEqual(rows["dee-one"]["merged_ids"], ["dee-one", "dee-two"])
        dee = rows["dee-one"]["windows"]["today"]
        self.assertIsNone(dee["cost_usd"])   # null, never 0.00
        self.assertEqual((dee["turns"], dee["priced_turns"], dee["priceable_turns"]), (2, 0, 2))

    def test_alias_fr3_the_newest_heartbeat_among_folded_ids_wins(self) -> None:
        rows = {d["developer_id"]: d for d in self._status(self.ALIASES)["developers"]}
        goga = rows["i-am-goga"]
        # "local" beat 60s ago beats "i-am-goga"'s 30 min ago
        self.assertEqual((goga["current"]["project_path"], goga["current"]["feature_id"],
                          goga["current"]["checkpoint_count"]),
                         ("/repo/b", "174-team", 7))
        self.assertEqual(goga["liveness"], "active")
        # unfolded, the row's own id is idle — the fold is what makes it active
        unfolded = {d["developer_id"]: d for d in self._status()["developers"]}
        self.assertEqual(unfolded["i-am-goga"]["liveness"], "idle")

    def test_alias_fr4_the_alias_name_beats_the_developer_table(self) -> None:
        rows = {d["developer_id"]: d for d in self._status(self.ALIASES)["developers"]}
        self.assertEqual(rows["i-am-goga"]["display_name"], "Gosha")
        line = next(ln for ln in T.render_status(self._status(self.ALIASES))
                    if ln.startswith("Gosha (i-am-goga)"))
        self.assertIn("review · 174-team", line)
        self.assertIn("$1.50*", line)


if __name__ == "__main__":
    unittest.main()
