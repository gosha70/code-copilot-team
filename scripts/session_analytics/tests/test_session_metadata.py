# Tests for adapter-neutral session-metadata persistence (FU-1).
#
# Exercises store.upsert_session_metadata directly (encoding + full-replacement
# idempotency) and proves the pipeline persists ANY adapter's RawSession.metadata
# (Pi worker analytics, Claude git_branch) — not a Pi-specific surface.

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from session_analytics.contracts import RawSession
from session_analytics.relational import store
from session_analytics.relational.db import Database, apply_ddl


def _dsn():
    tmp = tempfile.mkdtemp(prefix="cct-sa-meta-")
    return f"sqlite:///{Path(tmp) / 'sa.db'}"


def _session(db, copilot="x", sid="s1", metadata=None):
    raw = RawSession(
        copilot=copilot, native_session_id=sid, turns=(), source_files=(),
        metadata=metadata or {},
    )
    return store.upsert_session(db, raw)


def _read(db, session_pk):
    rows = db.query(
        "SELECT key, value, value_json FROM copilot_session_metadata "
        "WHERE session_id = ? ORDER BY key",
        (session_pk,),
    )
    return {k: (json.loads(v) if j else v) for k, v, j in rows}


class SessionMetadataTest(unittest.TestCase):
    def setUp(self):
        self.db = Database.connect(_dsn())
        apply_ddl(self.db)

    def tearDown(self):
        self.db.close()

    def test_encoding_string_verbatim_complex_json(self):
        pk = _session(self.db)
        store.upsert_session_metadata(self.db, pk, {
            "git_branch": "feature/x",          # string -> verbatim
            "cost_usd": 1.25,                    # number -> json
            "outcomes": [{"w": "w1", "ok": True}],  # list -> json
        })
        self.db.commit()
        # raw row: string is not json-flagged; complex is
        raw = dict(
            (k, (v, j)) for k, v, j in self.db.query(
                "SELECT key, value, value_json FROM copilot_session_metadata WHERE session_id = ?", (pk,)
            )
        )
        self.assertEqual(raw["git_branch"], ("feature/x", 0))     # verbatim, value_json false
        self.assertEqual(raw["cost_usd"][1], 1)                    # value_json true
        got = _read(self.db, pk)
        self.assertEqual(got["cost_usd"], 1.25)
        self.assertEqual(got["outcomes"], [{"w": "w1", "ok": True}])

    def test_full_replacement_removes_stale_keys(self):
        pk = _session(self.db)
        store.upsert_session_metadata(self.db, pk, {"a": "1", "b": "2"})
        self.db.commit()
        # re-persist WITHOUT "b" -> b must be gone (delete-then-insert)
        store.upsert_session_metadata(self.db, pk, {"a": "9"})
        self.db.commit()
        got = _read(self.db, pk)
        self.assertEqual(got, {"a": "9"}, "omitted key must not leave a stale row")

    def test_empty_metadata_clears_and_does_not_error(self):
        pk = _session(self.db)
        store.upsert_session_metadata(self.db, pk, {"a": "1"})
        self.db.commit()
        store.upsert_session_metadata(self.db, pk, {})   # empty -> clears
        self.db.commit()
        self.assertEqual(_read(self.db, pk), {})
        store.upsert_session_metadata(self.db, pk, None)  # None -> no error
        self.db.commit()

    def test_value_is_length_bounded(self):
        pk = _session(self.db)
        store.upsert_session_metadata(self.db, pk, {"big": "z" * 10000})
        self.db.commit()
        got = _read(self.db, pk)
        self.assertLessEqual(len(got["big"]), store._MAX_METADATA_VALUE)

    def test_large_structured_value_stays_valid_json_when_truncated(self):
        # A big structured value must NOT be stored as a blindly-sliced (invalid)
        # JSON blob while value_json=true. _read() does json.loads for such rows,
        # so it would raise if the fix regressed.
        pk = _session(self.db)
        big = [{"worker": "w" * 200, "ok": True} for _ in range(200)]  # >> 4 KiB
        store.upsert_session_metadata(self.db, pk, {"worker_outcomes": big})
        self.db.commit()
        got = _read(self.db, pk)  # json.loads must succeed
        self.assertEqual(
            got["worker_outcomes"],
            {"_truncated": True, "bytes": len(json.dumps(big, sort_keys=True))},
        )

    def test_structured_value_under_cap_round_trips_fully(self):
        pk = _session(self.db)
        small = [{"worker": "w1", "ok": True}]
        store.upsert_session_metadata(self.db, pk, {"worker_outcomes": small})
        self.db.commit()
        self.assertEqual(_read(self.db, pk)["worker_outcomes"], small)


if __name__ == "__main__":
    unittest.main()
