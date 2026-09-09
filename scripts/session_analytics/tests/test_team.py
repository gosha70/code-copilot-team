# Tests for the team store's status (#174 B2 + C): liveness from
# heartbeats, windows by turn timestamp, cost honesty, noise policy.

from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

from session_analytics import constants as C
from session_analytics.api import team as T
from session_analytics.config import NoiseConfig
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import RegistryResetTestCase

_FASTAPI = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)

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

    def _status(self, noise=_NOISE, window=300, aliases=None):
        return T.team_status(
            self.db, noise=noise, active_window_seconds=window, now=NOW, aliases=aliases)

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

    # ── team.aliases: one person's several ids, folded at read time ──

    def test_alias_fr2_folds_ids_sharing_a_name_and_names_merged_ids(self) -> None:
        s = self._status(aliases={"ben": "Gosha", "ana": "Gosha"})
        rows = {d["developer_id"]: d for d in s["developers"]}
        # The row is named after the first id in the MAPPING's order, not
        # the first alphabetically.
        self.assertNotIn("ana", rows)
        self.assertEqual(rows["ben"]["display_name"], "Gosha")
        self.assertEqual(rows["ben"]["merged_ids"], ["ben", "ana"])
        # Nothing is hidden: an unaliased row still says what it is made of.
        self.assertEqual(rows["registered-only"]["merged_ids"], ["registered-only"])
        self.assertEqual((s["totals"]["developers"], len(s["developers"])), (2, 2))

    def test_alias_fr3_sums_the_windows_and_keeps_the_newest_heartbeat(self) -> None:
        rows = {d["developer_id"]: d
                for d in self._status(aliases={"ana": "Gosha", "ben": "Gosha"})["developers"]}
        folded = rows["ana"]
        # 30d: ana's three stamped turns (two priced, $3.25) + ben's one
        # unpriced turn, over both their sessions.
        self.assertEqual(folded["windows"]["30d"], {
            "sessions": 2, "turns": 4, "cost_usd": 3.25, "priced_turns": 2, "priceable_turns": 4})
        self.assertEqual(folded["windows"]["today"]["turns"], 2)   # ben has nothing today
        # ana's heartbeat is a minute old, ben's two hours: the newest wins.
        self.assertEqual(folded["liveness"], "active")
        self.assertEqual(folded["current"]["project_path"], "/repo/proj")
        self.assertEqual(self._status(aliases={"ana": "Gosha", "ben": "Gosha"})["totals"]["active_now"], 1)

    def test_alias_fr3_cost_is_null_when_no_folded_id_is_priced(self) -> None:
        rows = {d["developer_id"]: d
                for d in self._status(aliases={"ben": "Solo", "registered-only": "Solo"})["developers"]}
        folded = rows["ben"]
        self.assertEqual(folded["merged_ids"], ["ben", "registered-only"])
        self.assertIsNone(folded["windows"]["7d"]["cost_usd"])   # never $0.00
        self.assertEqual(folded["windows"]["7d"]["priceable_turns"], 1)
        self.assertEqual(folded["liveness"], "idle")             # ben's beat, hours old

    def test_alias_fr4_config_name_beats_the_developer_table(self) -> None:
        s = self._status(aliases={"ana": "Gosha"})
        rows = {d["developer_id"]: d for d in s["developers"]}
        self.assertEqual(rows["ana"]["display_name"], "Gosha")   # not "Ana"
        self.assertEqual(rows["ana"]["merged_ids"], ["ana"])
        line = next(line for line in T.render_status(s) if line.startswith("Gosha (ana)"))
        self.assertIn("$3.25*", line)


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; route test skipped (covered in CI)")
class TestTeamStatusRouteAliases(RegistryResetTestCase):
    """FR-4 on the API side: /api/team/status folds from the loaded
    config, so the Team tab shows the same row the CLI prints."""

    def test_alias_fr4_route_folds_from_the_loaded_config(self) -> None:
        from unittest import mock

        from fastapi.testclient import TestClient

        from session_analytics import config as cfgmod
        from session_analytics.api.server import create_app

        dsn = self.sqlite_dsn()
        db = Database.connect(dsn)
        apply_ddl(db)
        db.execute("INSERT INTO developer (developer_id, display_name) VALUES (?, ?)", ("i-am-goga", "Ivan"))
        for native, dev, cost in (("s-1", "i-am-goga", 1.0), ("s-2", "local", 0.5)):
            db.execute(
                "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, turn_count, "
                "started_at, duration_seconds) VALUES (?, ?, '/repo/proj', ?, 50, ?, 600)",
                (C.COPILOT_CLAUDE_CODE, native, dev, _iso(NOW)),
            )
            sid = int(db.query_one("SELECT id FROM copilot_session WHERE session_id = ?", (native,))[0])
            db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, content_preview, timestamp, "
                "cost_usd, model) VALUES (?, 1, ?, '', ?, ?, 'm')",
                (sid, C.ROLE_ASSISTANT, _iso(datetime.now(timezone.utc)), cost),
            )
        db.commit()
        db.close()
        client = TestClient(create_app(dsn), base_url="http://127.0.0.1:8765")
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", {cfgmod.ENV_TEAM_ALIASES: "i-am-goga=Gosha,local=Gosha"}):
            body = client.get("/api/team/status").json()
        self.assertEqual(len(body["developers"]), 1)
        row = body["developers"][0]
        self.assertEqual((row["developer_id"], row["display_name"]), ("i-am-goga", "Gosha"))
        self.assertEqual(row["merged_ids"], ["i-am-goga", "local"])
        self.assertEqual(row["windows"]["30d"]["cost_usd"], 1.5)


if __name__ == "__main__":
    unittest.main()
