# Tests for the team store's status (#174 B2 + C): liveness from
# heartbeats, windows by turn timestamp, cost honesty, noise policy.

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    """FR-2/FR-3/FR-4 (team-developer-aliases): one person whose ids drifted
    over the project's life reads as one row, with every id named."""

    #: Three derived ids for one person, plus a second person whose two ids
    #: never priced a turn — the "cost stays null" case.
    ALIASES = {
        "i-am-goga": "Gosha", "i-am-goga-gmail-com": "Gosha", "local": "Gosha",
        "dev-x": "Xen", "dev-y": "Xen",
    }

    def setUp(self) -> None:
        super().setUp()
        self.dsn = self.sqlite_dsn()
        self.db = Database.connect(self.dsn)
        apply_ddl(self.db)
        self.addCleanup(self.db.close)
        # The developer table's own name for one of the folded ids: the
        # alias must win over it (FR-4).
        self.db.execute("INSERT INTO developer (developer_id, display_name) VALUES (?, ?)",
                        ("i-am-goga", "Old Derived Name"))
        self._turn(self._session("i-am-goga", "/repo/a", "s-a"), NOW - timedelta(hours=1), 1.00)
        self._turn(self._session("i-am-goga-gmail-com", "/repo/b", "s-b"), NOW - timedelta(hours=2), 2.50)
        self._turn(self._session("local", "/repo/c", "s-c"), NOW - timedelta(minutes=5), None)
        self._turn(self._session("dev-x", "/repo/d", "s-d"), NOW - timedelta(hours=1), None)
        self._turn(self._session("dev-y", "/repo/d", "s-e"), NOW - timedelta(hours=1), None)
        self._turn(self._session("ben", "/repo/f", "s-f"), NOW - timedelta(hours=1), 4.00)
        # The newest of the folded heartbeats is the person's current work.
        self._beat("/repo/a", "i-am-goga", "plan", NOW - timedelta(seconds=240))
        self._beat("/repo/b", "i-am-goga-gmail-com", "build", NOW - timedelta(seconds=30))
        self.db.commit()

    def _session(self, dev: str, project: str, native: str) -> int:
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, turn_count, "
            "started_at, duration_seconds) VALUES (?, ?, ?, ?, 5, ?, 600)",
            (C.COPILOT_CLAUDE_CODE, native, project, dev, _iso(NOW)),
        )
        return int(self.db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", (native,))[0])

    def _turn(self, sid: int, at, cost) -> None:
        self.db.execute(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, content_preview, timestamp, cost_usd, model) "
            "VALUES (?, 1, ?, '', ?, ?, 'm')",
            (sid, C.ROLE_ASSISTANT, _iso(at), cost),
        )

    def _beat(self, project, dev, phase, at) -> None:
        self.db.execute(
            f"INSERT INTO {C.TBL_LOCAL_HEARTBEAT} (project_path, developer_id, phase, feature_id, "
            "checkpoint_count, last_heartbeat_at) VALUES (?, ?, ?, NULL, 1, ?)",
            (project, dev, phase, _iso(at)),
        )

    def _status(self, aliases=None):
        return T.team_status(self.db, noise=_NOISE, active_window_seconds=300, now=NOW,
                             aliases=self.ALIASES if aliases is None else aliases)

    def test_alias_fr2_ids_sharing_a_name_are_one_row(self) -> None:
        rows = {d["developer_id"]: d for d in self._status()["developers"]}
        self.assertEqual(set(rows), {"i-am-goga", "dev-x", "ben"})
        goga = rows["i-am-goga"]
        self.assertEqual(goga["display_name"], "Gosha")
        # The row's id is the FIRST of the folded ids in mapping order, and
        # merged_ids names every one of them — including that first id.
        self.assertEqual(goga["merged_ids"], ["i-am-goga", "i-am-goga-gmail-com", "local"])
        self.assertEqual(rows["dev-x"]["merged_ids"], ["dev-x", "dev-y"])

    def test_alias_fr2_an_unaliased_row_is_merged_ids_of_itself(self) -> None:
        rows = {d["developer_id"]: d for d in self._status()["developers"]}
        self.assertEqual(rows["ben"]["merged_ids"], ["ben"])
        self.assertIsNone(rows["ben"]["display_name"])
        # Without aliases every row is its own id — the fold is opt-in.
        unfolded = {d["developer_id"]: d for d in self._status(aliases={})["developers"]}
        self.assertEqual(set(unfolded), {"i-am-goga", "i-am-goga-gmail-com", "local", "dev-x", "dev-y", "ben"})
        self.assertEqual(unfolded["local"]["merged_ids"], ["local"])

    def test_alias_fr3_windows_sum_over_the_folded_ids(self) -> None:
        rows = {d["developer_id"]: d for d in self._status()["developers"]}
        today = rows["i-am-goga"]["windows"]["today"]
        self.assertEqual(
            (today["sessions"], today["turns"], today["cost_usd"],
             today["priced_turns"], today["priceable_turns"]),
            (3, 3, 3.50, 2, 3),
        )
        # The same figures in every window that contains the turns…
        self.assertEqual(rows["i-am-goga"]["windows"]["30d"]["turns"], 3)
        # …and the totals are untouched by the fold: same turns, one team.
        self.assertEqual(self._status()["totals"]["windows"]["today"]["turns"],
                         self._status(aliases={})["totals"]["windows"]["today"]["turns"])

    def test_alias_fr3_cost_is_null_when_no_folded_id_priced_a_turn(self) -> None:
        xen = {d["developer_id"]: d for d in self._status()["developers"]}["dev-x"]
        today = xen["windows"]["today"]
        self.assertIsNone(today["cost_usd"])          # never 0.00
        self.assertEqual((today["turns"], today["priced_turns"], today["priceable_turns"]), (2, 0, 2))

    def test_alias_fr3_the_newest_folded_heartbeat_wins(self) -> None:
        goga = {d["developer_id"]: d for d in self._status()["developers"]}["i-am-goga"]
        self.assertEqual(goga["liveness"], "active")   # 30s ago, not the 240s one
        self.assertEqual((goga["current"]["project_path"], goga["current"]["phase"]), ("/repo/b", "build"))
        # A folded person with no heartbeat at all still reads "unknown".
        self.assertEqual(
            {d["developer_id"]: d for d in self._status()["developers"]}["dev-x"]["liveness"], "unknown")

    def test_alias_fr3_newest_heartbeat_within_one_id_is_by_parsed_time_not_text(self) -> None:
        # Two heartbeats for ONE developer id whose timestamp shapes make
        # string order and chronological order disagree: the older one is
        # written "2026-09-08T11:00:00Z" (a 'T' separator), the newer one
        # "2026-09-08 11:30:00" (a space sorts BEFORE 'T'). The newer must
        # win, so the fold hands _newest_beat the right heartbeat (FR-3).
        # Different project paths, because the table's key is (project, id).
        self.db.execute(
            f"INSERT INTO {C.TBL_LOCAL_HEARTBEAT} (project_path, developer_id, phase, feature_id, checkpoint_count, "
            "last_heartbeat_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("/repo/older", "mixed", "plan", "old", 1, (NOW - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        self.db.execute(
            f"INSERT INTO {C.TBL_LOCAL_HEARTBEAT} (project_path, developer_id, phase, feature_id, checkpoint_count, "
            "last_heartbeat_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("/repo/newer", "mixed", "build", "new", 2, (NOW - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        self.db.commit()
        # Lexically the 'T' row sorts after the space row; chronologically it is older.
        older, newer = (NOW - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ"), (NOW - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        self.assertGreater(older, newer, "the fixture must make string order disagree with time order")
        mixed = {d["developer_id"]: d for d in self._status(aliases={})["developers"]}["mixed"]
        self.assertEqual((mixed["current"]["project_path"], mixed["current"]["phase"]), ("/repo/newer", "build"))

    def test_alias_fr4_the_alias_name_beats_the_developer_table(self) -> None:
        goga = {d["developer_id"]: d for d in self._status()["developers"]}["i-am-goga"]
        self.assertEqual(goga["display_name"], "Gosha")
        # …and without the alias the table's own name is what shows.
        self.assertEqual(
            {d["developer_id"]: d for d in self._status(aliases={})["developers"]}["i-am-goga"]["display_name"],
            "Old Derived Name")

    def test_alias_fr4_the_route_applies_the_configured_aliases(self) -> None:
        import importlib.util
        from unittest import mock

        if importlib.util.find_spec("fastapi") is None or importlib.util.find_spec("httpx") is None:
            self.skipTest("fastapi/httpx not installed; API test skipped (covered in CI)")
        from fastapi.testclient import TestClient

        from session_analytics import config as cfgmod
        from session_analytics._register import register_all
        from session_analytics.api.server import create_app

        register_all()
        env = ",".join(f"{dev}={name}" for dev, name in self.ALIASES.items())
        with mock.patch.object(cfgmod, "_USER_CONFIG", Path("/nonexistent/session-analytics.json")), \
             mock.patch.object(cfgmod, "parse_env_file", return_value={}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_TEAM_ALIASES: env}):
            client = TestClient(create_app(self.dsn), base_url="http://127.0.0.1:8765")
            body = client.get("/api/team/status").json()
        rows = {d["developer_id"]: d for d in body["developers"]}
        self.assertEqual(set(rows), {"i-am-goga", "dev-x", "ben"})
        self.assertEqual(rows["i-am-goga"]["display_name"], "Gosha")
        self.assertEqual(rows["i-am-goga"]["merged_ids"],
                         ["i-am-goga", "i-am-goga-gmail-com", "local"])


if __name__ == "__main__":
    unittest.main()
