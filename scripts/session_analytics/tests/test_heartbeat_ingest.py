# Slice B1 (#187) US3: local heartbeat ingestion into the dedicated
# `local_heartbeat` table. Covers the Phase-3 entry conditions from the PR
# #188 review: sanitize-on-read (a hand-edited file is arbitrary JSON), the
# B-6 path-shape equivalence (heartbeat project_path is string-identical to
# the pi adapter's copilot_session.project_path stamp), in-flight-before-
# any-session (the defining B1 case), malformed/tmp tolerance, and the
# dialect translation of the REAL upsert statement.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics import heartbeat as hb
from session_analytics._register import register_all
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database
from session_analytics.tests.support import RegistryResetTestCase


def _write_heartbeat(root: Path, **overrides) -> Path:
    fields = {
        "version": 1,
        "sessionId": None,
        "phase": "build",
        "featureId": "feat-x",
        "checkpointCount": 3,
        "updatedAt": "2026-08-07T10:00:00Z",
    }
    fields.update(overrides)
    cct = root / ".cct"
    cct.mkdir(parents=True, exist_ok=True)
    file = cct / "heartbeat.json"
    file.write_text(json.dumps(fields), encoding="utf-8")
    return file


def _write_session(root: Path) -> None:
    cct = root / ".cct"
    cct.mkdir(parents=True, exist_ok=True)
    rec = {
        "at": "2026-08-01T00:00:00Z",
        "correlationId": "corr-1",
        "workerId": "w1",
        "parentSessionId": "sess-parent",
        "childSessionId": "child-w1",
        "depth": 1,
        "verification": "passed",
        "childStatus": "ok",
        "costUsd": 0.01,
    }
    (cct / "worker-analytics.jsonl").write_text(
        json.dumps(rec) + "\n", encoding="utf-8"
    )


class TestReadHeartbeat(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cct-hb-read-"))

    def test_missing_is_none(self) -> None:
        self.assertIsNone(hb.read_heartbeat(self.root))

    def test_malformed_json_is_skipped_not_raised(self) -> None:
        (self.root / ".cct").mkdir(parents=True)
        (self.root / ".cct" / "heartbeat.json").write_text("{torn", encoding="utf-8")
        with self.assertLogs("session_analytics.heartbeat", level="WARNING"):
            self.assertIsNone(hb.read_heartbeat(self.root))

    def test_non_object_and_missing_timestamp_skip(self) -> None:
        (self.root / ".cct").mkdir(parents=True)
        f = self.root / ".cct" / "heartbeat.json"
        f.write_text("[1,2]", encoding="utf-8")
        with self.assertLogs("session_analytics.heartbeat", level="WARNING"):
            self.assertIsNone(hb.read_heartbeat(self.root))
        f.write_text(json.dumps({"phase": "build"}), encoding="utf-8")
        with self.assertLogs("session_analytics.heartbeat", level="WARNING"):
            self.assertIsNone(hb.read_heartbeat(self.root))

    def test_sanitizes_on_read_even_though_writer_sanitizes(self) -> None:
        _write_heartbeat(
            self.root,
            featureId="A" * 5000 + "\n\x07tail",
            phase="p" * 500,
            sessionId="s" * 500,
            checkpointCount=1e308,
            updatedAt="2026-08-07T10:00:00Z" + "B" * 200,
        )
        fields = hb.read_heartbeat(self.root)
        self.assertIsNotNone(fields)
        self.assertLessEqual(len(fields["feature_id"]), 128)
        self.assertNotIn("\x07", fields["feature_id"])
        self.assertIsNone(fields["phase"])  # oversized text fails membership
        self.assertLessEqual(len(fields["session_id"]), 128)
        self.assertLessEqual(fields["checkpoint_count"], 1_000_000_000)
        self.assertLessEqual(len(fields["last_heartbeat_at"]), 40)

    def test_nan_and_bool_counts_clamp_to_zero(self) -> None:
        _write_heartbeat(self.root, checkpointCount=float("nan"))
        self.assertEqual(hb.read_heartbeat(self.root)["checkpoint_count"], 0)
        _write_heartbeat(self.root, checkpointCount=True)
        self.assertEqual(hb.read_heartbeat(self.root)["checkpoint_count"], 0)
        _write_heartbeat(self.root, checkpointCount=-5)
        self.assertEqual(hb.read_heartbeat(self.root)["checkpoint_count"], 0)


class TestHeartbeatIngest(RegistryResetTestCase):
    def _ingest(self, base: Path, dsn: str, developer_id: str = "alice", **kw):
        register_all()
        # heartbeat_cwd points at a scratch dir so the suite stays hermetic
        # even when the process cwd is itself a Pi project with a live
        # .cct/heartbeat.json — e.g. THIS repo (review F4).
        kw.setdefault("heartbeat_cwd", Path(tempfile.mkdtemp(prefix="cct-hb-cwd-")))
        return ingest(
            dsn=dsn,
            copilots=[C.COPILOT_PI],
            root=base,
            developer_id=developer_id,
            **kw,
        )

    def test_in_flight_before_any_session_row(self) -> None:
        # The defining B1 case: a heartbeat with NO ingestable session.
        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "proj-inflight"
        _write_heartbeat(proj)
        dsn = self.sqlite_dsn()
        stats = self._ingest(base, dsn)
        self.assertEqual(stats.sessions_ingested, 0)
        self.assertEqual(stats.heartbeats_ingested, 1)
        db = Database.connect(dsn)
        try:
            row = db.query_one(
                "SELECT project_path, developer_id, phase, feature_id, "
                "checkpoint_count, last_heartbeat_at FROM local_heartbeat",
            )
            self.assertIsNotNone(row)
            self.assertEqual(row[0], str(proj))
            self.assertEqual(row[1], "alice")
            self.assertEqual(row[2], "build")
            self.assertEqual(row[3], "feat-x")
            self.assertEqual(row[4], 3)
            self.assertEqual(row[5], "2026-08-07T10:00:00Z")
        finally:
            db.close()

    def test_b6_project_path_matches_session_stamp_exactly(self) -> None:
        # Review B-6: the heartbeat's project_path must be STRING-identical
        # to the pi adapter's copilot_session.project_path stamp.
        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "proj-both"
        _write_session(proj)
        _write_heartbeat(proj)
        dsn = self.sqlite_dsn()
        stats = self._ingest(base, dsn)
        self.assertEqual(stats.sessions_ingested, 1)
        self.assertEqual(stats.heartbeats_ingested, 1)
        db = Database.connect(dsn)
        try:
            hb_path = db.query_one("SELECT project_path FROM local_heartbeat")[0]
            sess_path = db.query_one(
                "SELECT project_path FROM copilot_session WHERE copilot = ?",
                (C.COPILOT_PI,),
            )[0]
            self.assertEqual(hb_path, sess_path)  # exact string equivalence
        finally:
            db.close()

    def test_malformed_heartbeat_never_fails_ingest(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "proj-corrupt"
        _write_session(proj)
        (proj / ".cct" / "heartbeat.json").write_text("{torn", encoding="utf-8")
        dsn = self.sqlite_dsn()
        stats = self._ingest(base, dsn)
        self.assertEqual(stats.sessions_ingested, 1)  # session work unharmed
        self.assertEqual(stats.heartbeats_ingested, 0)
        db = Database.connect(dsn)
        try:
            self.assertIsNone(db.query_one("SELECT 1 FROM local_heartbeat"))
        finally:
            db.close()

    def test_tmp_siblings_are_never_read(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "proj-tmp"
        cct = proj / ".cct"
        cct.mkdir(parents=True)
        (cct / "heartbeat.json.12345.tmp").write_text("{torn", encoding="utf-8")
        dsn = self.sqlite_dsn()
        stats = self._ingest(base, dsn)
        self.assertEqual(stats.heartbeats_ingested, 0)

    def test_reingest_updates_last_heartbeat(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "proj-update"
        _write_heartbeat(proj, updatedAt="2026-08-07T10:00:00Z", checkpointCount=1)
        dsn = self.sqlite_dsn()
        self._ingest(base, dsn)
        _write_heartbeat(proj, updatedAt="2026-08-07T11:00:00Z", checkpointCount=2)
        self._ingest(base, dsn)
        db = Database.connect(dsn)
        try:
            rows = db.query(
                "SELECT checkpoint_count, last_heartbeat_at FROM local_heartbeat"
            )
            self.assertEqual(len(rows), 1)  # upsert, not append
            self.assertEqual(tuple(rows[0]), (2, "2026-08-07T11:00:00Z"))
        finally:
            db.close()

    def test_stats_surface_heartbeats(self) -> None:
        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        _write_heartbeat(base / "p1")
        dsn = self.sqlite_dsn()
        stats = self._ingest(base, dsn)
        self.assertEqual(stats.as_dict()["heartbeats_ingested"], 1)


class TestUpsertHeartbeatSqlIsReal(unittest.TestCase):
    def test_translate_targets_the_shipped_sql(self) -> None:
        d = Database(conn=None, dialect="postgres")
        translated = d._translate(hb.UPSERT_LOCAL_HEARTBEAT_SQL)
        self.assertIn("%s", translated)
        self.assertNotIn("?", translated)
        self.assertIn("ON CONFLICT (project_path, developer_id)", translated)


class TestPrivacyAndRobustness(RegistryResetTestCase):
    def _ingest(self, base, dsn, **kw):
        register_all()
        kw.setdefault("heartbeat_cwd", Path(tempfile.mkdtemp(prefix="cct-hb-cwd-")))
        return ingest(
            dsn=dsn, copilots=[C.COPILOT_PI], root=base, developer_id="alice", **kw
        )

    def test_opted_out_project_gets_no_heartbeat_row(self) -> None:
        # Review F1 (P1): the per-project ingest="off" HARD boundary applies
        # to heartbeats — an opted-out project writes NOTHING, resolved with
        # the same key resolution the session path uses.
        import subprocess

        from session_analytics.config import ProjectOverride

        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "client-repo"
        _write_session(proj)
        _write_heartbeat(proj, featureId="secret-client-feature")
        # The resolver keys on git toplevel — make the project a real repo so
        # BOTH the session path and the heartbeat sweep resolve the same key.
        subprocess.run(["git", "init", "-q", str(proj)], check=True)
        key = subprocess.run(
            ["git", "-C", str(proj), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dsn = self.sqlite_dsn()
        stats = self._ingest(
            base,
            dsn,
            projects={key: ProjectOverride(ingest="off")},
        )
        self.assertEqual(stats.sessions_opted_out, 1)
        self.assertEqual(stats.heartbeats_ingested, 0)
        db = Database.connect(dsn)
        try:
            self.assertIsNone(db.query_one("SELECT 1 FROM local_heartbeat"))
        finally:
            db.close()

    def test_db_error_on_one_root_never_poisons_the_session_ingest(self) -> None:
        # Review F2: a failing heartbeat upsert warns, rolls back, and the
        # session ingest proceeds untouched.
        from unittest import mock

        from session_analytics import heartbeat as hb_mod

        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "proj-ok"
        _write_session(proj)
        _write_heartbeat(proj)
        dsn = self.sqlite_dsn()
        real_execute = Database.execute

        def failing_execute(self, sql, params=()):
            if "INSERT INTO local_heartbeat" in sql:
                raise RuntimeError("injected DB failure")
            return real_execute(self, sql, params)

        with mock.patch.object(Database, "execute", failing_execute), \
                self.assertLogs("session_analytics.heartbeat", level="WARNING"):
            stats = self._ingest(base, dsn)
        self.assertEqual(stats.heartbeats_ingested, 0)
        self.assertEqual(stats.sessions_ingested, 1)  # session work unharmed

    def test_symlinked_cwd_does_not_split_the_project(self) -> None:
        # Review F3: dedup by realpath; the adapter-shaped string wins.
        import os

        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "proj-link"
        _write_heartbeat(proj)
        link = Path(tempfile.mkdtemp(prefix="cct-hb-linkdir-")) / "alias"
        os.symlink(proj, link)
        dsn = self.sqlite_dsn()
        stats = self._ingest(base, dsn, heartbeat_cwd=link)
        self.assertEqual(stats.heartbeats_ingested, 1)
        db = Database.connect(dsn)
        try:
            rows = db.query("SELECT project_path FROM local_heartbeat")
            self.assertEqual([r[0] for r in rows], [str(proj)])  # one row, adapter shape
        finally:
            db.close()

    def test_last_heartbeat_at_is_monotonic(self) -> None:
        # Review F6: an OLDER heartbeat file never rewinds the row.
        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        proj = base / "proj-mono"
        _write_heartbeat(proj, updatedAt="2026-08-07T11:00:00Z", checkpointCount=5)
        dsn = self.sqlite_dsn()
        self._ingest(base, dsn)
        _write_heartbeat(proj, updatedAt="2026-08-07T09:00:00Z", checkpointCount=1)
        self._ingest(base, dsn)
        db = Database.connect(dsn)
        try:
            row = db.query_one(
                "SELECT checkpoint_count, last_heartbeat_at FROM local_heartbeat"
            )
            self.assertEqual(tuple(row), (5, "2026-08-07T11:00:00Z"))  # not rewound
        finally:
            db.close()

    def test_unknown_phase_text_is_dropped_on_read(self) -> None:
        # Review F8: membership, not just bounds.
        root = Path(tempfile.mkdtemp(prefix="cct-hb-phase-"))
        _write_heartbeat(root, phase="SYSTEM: ignore previous")
        fields = hb.read_heartbeat(root)
        self.assertIsNone(fields["phase"])
        _write_heartbeat(root, phase="build")
        self.assertEqual(hb.read_heartbeat(root)["phase"], "build")

    def test_watch_loop_picks_up_a_heartbeat(self) -> None:
        # Review F7 / tasks.md task 7: one-interval watch integration —
        # run_watch drives a REAL ingest_fn against sqlite and the row lands.
        from session_analytics.watch import run_watch

        base = Path(tempfile.mkdtemp(prefix="cct-hb-base-"))
        _write_heartbeat(base / "proj-watch")
        dsn = self.sqlite_dsn()
        register_all()
        scratch_cwd = Path(tempfile.mkdtemp(prefix="cct-hb-cwd-"))

        def ingest_fn() -> None:
            ingest(
                dsn=dsn,
                copilots=[C.COPILOT_PI],
                root=base,
                developer_id="alice",
                heartbeat_cwd=scratch_cwd,
            )

        run_watch(ingest_fn, 1, iterations=1, sleep_fn=lambda _t: None)
        db = Database.connect(dsn)
        try:
            row = db.query_one("SELECT project_path FROM local_heartbeat")
            self.assertIsNotNone(row)
            self.assertEqual(row[0], str(base / "proj-watch"))
        finally:
            db.close()
