# Tests for the query-time noise filter (#307, Studio Phase 2).

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from session_analytics import config as cfgmod
from session_analytics import constants as C
from session_analytics.config import NoiseConfig
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database
from session_analytics.session_filter import keep_clause, noise_clause

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class TestNoiseConfigLoading(unittest.TestCase):
    def _load(self, *, user_json=None, environ=None):
        tmp = Path(tempfile.mkdtemp())
        user_path = tmp / "session-analytics.json"
        if user_json is not None:
            user_path.write_text(json.dumps(user_json), encoding="utf-8")
        base = {k: v for k, v in os.environ.items() if not k.startswith("CCT_SA_")}
        base.update(environ or {})
        with mock.patch.object(cfgmod, "_USER_CONFIG", user_path), \
             mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", base, clear=True):
            return cfgmod.load_config().noise

    def test_defaults_come_from_the_data_file(self) -> None:
        n = self._load()
        self.assertEqual((n.min_turns, n.min_duration_seconds), (3, 60))
        self.assertIn("/cct-probe", n.path_patterns)

    def test_env_overrides_each_knob(self) -> None:
        n = self._load(environ={
            cfgmod.ENV_NOISE_MIN_TURNS: "5",
            cfgmod.ENV_NOISE_MIN_DURATION: "0",
            cfgmod.ENV_NOISE_PATH_PATTERNS: "/scratch/, /probe-",
        })
        self.assertEqual((n.min_turns, n.min_duration_seconds), (5, 0))
        self.assertEqual(n.path_patterns, ("/scratch/", "/probe-"))

    def test_user_json_layer(self) -> None:
        n = self._load(user_json={
            C.CFG_SESSIONS: {C.CFG_SESSIONS_NOISE: {C.CFG_NOISE_MIN_TURNS: 1}}
        })
        self.assertEqual(n.min_turns, 1)
        self.assertEqual(n.min_duration_seconds, 60)   # untouched keys keep defaults

    def test_bad_values_refuse_loudly(self) -> None:
        with self.assertRaises(ValueError):
            self._load(environ={cfgmod.ENV_NOISE_MIN_TURNS: "three"})
        with self.assertRaises(ValueError):
            self._load(environ={cfgmod.ENV_NOISE_MIN_DURATION: "-1"})


class TestPredicate(unittest.TestCase):
    def test_all_off_is_no_noise(self) -> None:
        off = NoiseConfig(min_turns=0, min_duration_seconds=0, path_patterns=())
        self.assertEqual(noise_clause(off, "s"), ("1=0", ()))
        self.assertEqual(keep_clause(off, "s"), ("1=1", ()))

    def test_like_metacharacters_are_escaped(self) -> None:
        cfg = NoiseConfig(min_turns=0, min_duration_seconds=0, path_patterns=("/a_b%",))
        sql, params = noise_clause(cfg, "s")
        self.assertIn("LIKE ? ESCAPE", sql)
        self.assertEqual(params, ("%/a\\_b\\%%",))


class TestPredicateAgainstAStore(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics.adapters import claude_code
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        # A second session that is unmistakably a probe: temp-dir path,
        # two turns, ten seconds.
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, turn_count, "
            "tool_call_count, error_count, duration_seconds, developer_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (C.COPILOT_CLAUDE_CODE, "probe-1", "/private/var/folders/xy/cct-probe.abc",
             2, 0, 0, 10, C.DEFAULT_DEVELOPER_ID),
        )
        # The fixture session is 5s long; make it a real session so each
        # rule below isolates the probe.
        self.db.execute(
            "UPDATE copilot_session SET duration_seconds = 3600 WHERE project_path = ?",
            ("/repo/demo",),
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def _count(self, sql: str, params) -> int:
        return int(self.db.query_one(
            f"SELECT COUNT(*) FROM copilot_session s WHERE {sql}", params
        )[0])

    def test_each_rule_alone_catches_the_probe_only(self) -> None:
        for cfg in (
            NoiseConfig(min_turns=3, min_duration_seconds=0, path_patterns=()),
            NoiseConfig(min_turns=0, min_duration_seconds=60, path_patterns=()),
            NoiseConfig(min_turns=0, min_duration_seconds=0, path_patterns=("/cct-probe",)),
        ):
            with self.subTest(cfg=cfg):
                self.assertEqual(self._count(*noise_clause(cfg, "s")), 1)
                self.assertEqual(self._count(*keep_clause(cfg, "s")), 1)

    def test_benchmark_linked_session_is_never_noise(self) -> None:
        # Attempt dirs are temp dirs and attempts are short; a session the
        # correlator linked was run on purpose and stays in every total.
        self.db.execute(
            f"UPDATE copilot_session SET {C.COL_BENCHMARK_RUN_DIR} = ? WHERE session_id = ?",
            ("/tmp/runs/attempt-1", "probe-1"),
        )
        self.db.commit()
        cfg = NoiseConfig(min_turns=3, min_duration_seconds=60, path_patterns=("/cct-probe",))
        self.assertEqual(self._count(*noise_clause(cfg, "s")), 0)
        self.assertEqual(self._count(*keep_clause(cfg, "s")), 2)

    def test_null_project_path_is_kept_and_counted(self) -> None:
        # A normal session whose path is unknown must land on exactly one
        # side of the predicate (kept), never vanish from both.
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, turn_count, "
            "tool_call_count, error_count, duration_seconds, developer_id) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?, ?)",
            (C.COPILOT_CLAUDE_CODE, "nopath-1", 4, 0, 0, 120, C.DEFAULT_DEVELOPER_ID),
        )
        self.db.commit()
        cfg = NoiseConfig(min_turns=3, min_duration_seconds=60, path_patterns=("/cct-probe",))
        kept = self._count(*keep_clause(cfg, "s"))
        noise = self._count(*noise_clause(cfg, "s"))
        total = int(self.db.query_one("SELECT COUNT(*) FROM copilot_session")[0])
        self.assertEqual((kept, noise, kept + noise), (2, 1, total))

    def test_unknown_duration_is_not_noise(self) -> None:
        self.db.execute("UPDATE copilot_session SET duration_seconds = NULL")
        self.db.commit()
        cfg = NoiseConfig(min_turns=0, min_duration_seconds=60, path_patterns=())
        self.assertEqual(self._count(*noise_clause(cfg, "s")), 0)
