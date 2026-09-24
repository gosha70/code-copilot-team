# Feedback as a general record (#371 A3): the store rules, the detail
# payload fold, re-ingest survival, the in-place schema bump and export.

from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from session_analytics import constants as C
from session_analytics import export as exp
from session_analytics import feedback as fb
from session_analytics.adapters import claude_code
from session_analytics.ingest.pipeline import ingest
from session_analytics.mcp import tools
from session_analytics.relational import db as dbmod
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class FeedbackBase(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        self.sid = int(self.db.query_one("SELECT id FROM copilot_session")[0])

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def add(self, name, value, **kw):
        kw.setdefault("source_type", C.FEEDBACK_SOURCE_HUMAN)
        kw.setdefault("source_id", "gosha")
        return fb.add_feedback(self.db, self.sid, name, value, kw.pop("source_type"), kw.pop("source_id"), **kw)


class TestValues(FeedbackBase):
    def test_each_value_type_lands_in_its_column_and_reads_back(self) -> None:
        note = self.add(C.FEEDBACK_NAME_NOTE, "  wrong file  ", sequence_num=1)
        rating = self.add(C.FEEDBACK_NAME_RATING, 4)
        flag = self.add(C.LABEL_BOOL_NAMES[0], False, sequence_num=3, tool_sequence_num=0)
        self.assertEqual(note["value"], "wrong file")
        self.assertEqual(rating["value"], 4)
        self.assertIs(flag["value"], False)
        rows = self.db.query(
            f"SELECT name, value_bool, value_num, value_text FROM {C.TBL_FEEDBACK} ORDER BY id"
        )
        self.assertEqual(rows[0][1:], (None, None, "wrong file"))
        self.assertEqual(rows[1][1:], (None, 4.0, None))
        self.assertEqual((rows[2][1], rows[2][2], rows[2][3]), (0, None, None))
        by_id = {r["id"]: r for r in fb.list_feedback(self.db, self.sid)}
        self.assertIs(by_id[flag["id"]]["value"], False)
        self.assertEqual(by_id[rating["id"]]["value"], 4)

    def test_offered_names_are_typed_bool_before_number(self) -> None:
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add(C.LABEL_BOOL_NAMES[0], 1)          # a number is not a boolean
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add(C.LABEL_BOOL_NAMES[0], "true")     # nor is text
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add(C.FEEDBACK_NAME_RATING, True)      # a bool is not a rating
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add(C.FEEDBACK_NAME_RATING, 6)
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add(C.FEEDBACK_NAME_RATING, 2.5)
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add(C.FEEDBACK_NAME_NOTE, 3)
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add(C.FEEDBACK_NAME_NOTE, "   ")
        self.assertEqual(self.add(C.FEEDBACK_NAME_RATING, 5.0)["value"], 5)

    def test_custom_names_take_any_one_type_but_are_bounded(self) -> None:
        self.assertEqual(self.add("risk", 0.75)["value"], 0.75)
        self.assertIs(self.add("flaky", True)["value"], True)
        self.assertEqual(self.add("verdict", "keep")["value"], "keep")
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("x" * (C.FEEDBACK_NAME_MAX_CHARS + 1), True)
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("   ", True)
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("long", "y" * (C.FEEDBACK_TEXT_MAX_CHARS + 1))
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("obj", {"a": 1})
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("nan", float("nan"))

    def test_source_and_rationale_rules(self) -> None:
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("n", True, source_type="oracle")
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("n", True, source_id="")
        row = self.add("n", True, source_type=C.FEEDBACK_SOURCE_JUDGE, source_id="heuristic-v1:qwen",
                       rationale="  because  ")
        self.assertEqual((row["source_type"], row["source_id"], row["rationale"]),
                         (C.FEEDBACK_SOURCE_JUDGE, "heuristic-v1:qwen", "because"))
        self.assertIsNone(self.add("m", True, rationale="  ")["rationale"])

    def test_check_constraint_refuses_two_values_or_none_at_the_database(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                f"INSERT INTO {C.TBL_FEEDBACK} (session_ref, name, value_bool, value_num, "
                "source_type, source_id, created_at) VALUES (?, 'n', 1, 1, 'human', 'x', 'now')",
                (self.sid,),
            )
        self.db.rollback()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                f"INSERT INTO {C.TBL_FEEDBACK} (session_ref, name, source_type, source_id, "
                "created_at) VALUES (?, 'n', 'human', 'x', 'now')",
                (self.sid,),
            )
        self.db.rollback()

    def test_a_large_whole_number_reads_back_as_a_float(self) -> None:
        self.assertEqual(self.add("big", 1e20)["value"], 1e20)
        self.assertIsInstance(fb.list_feedback(self.db, self.sid)[0]["value"], float)
        self.assertIs(type(self.add("small", 7.0)["value"]), int)


class TestTargets(FeedbackBase):
    def test_all_three_levels_and_missing_targets(self) -> None:
        s = self.add("n", True)
        t = self.add("n", True, sequence_num=1)
        c = self.add("n", True, sequence_num=1, tool_sequence_num=0)
        self.assertEqual((s["sequence_num"], s["tool_sequence_num"]), (None, None))
        self.assertEqual((t["sequence_num"], t["tool_sequence_num"]), (1, None))
        self.assertEqual((c["sequence_num"], c["tool_sequence_num"]), (1, 0))
        with self.assertRaises(fb.UnknownTargetError):
            fb.add_feedback(self.db, self.sid + 99, "n", True, C.FEEDBACK_SOURCE_HUMAN, "x")
        with self.assertRaises(fb.UnknownTargetError):
            self.add("n", True, sequence_num=999)
        with self.assertRaises(fb.UnknownTargetError):
            self.add("n", True, sequence_num=1, tool_sequence_num=7)
        with self.assertRaises(fb.UnknownTargetError):
            self.add("n", True, sequence_num=2, tool_sequence_num=0)  # turn 2 issued no call
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("n", True, tool_sequence_num=0)  # a call needs its turn

    def test_feedback_survives_reingest_at_every_level(self) -> None:
        before = [
            self.add("n", "session"),
            self.add("n", "turn", sequence_num=3),
            self.add("n", "call", sequence_num=3, tool_sequence_num=0),
        ]
        old_turn_ids = self.db.query("SELECT id FROM copilot_turn ORDER BY id")
        self.db.close()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        # Re-ingest really did reinsert the turns (fresh ids) …
        self.assertNotEqual(self.db.query("SELECT id FROM copilot_turn ORDER BY id"), old_turn_ids)
        # … and every row is still attached to its target in the payload.
        detail = tools.get_session_details(self.db, self.sid)
        self.assertEqual([r["value"] for r in detail["feedback"]], ["session"])
        turn3 = next(t for t in detail["turns"] if t["sequence_num"] == 3)
        self.assertEqual([r["value"] for r in turn3["feedback"]], ["turn"])
        self.assertEqual([r["value"] for r in turn3["tool_calls"][0]["feedback"]], ["call"])
        self.assertEqual({r["id"] for r in fb.list_feedback(self.db, self.sid)}, {r["id"] for r in before})


class TestSupersession(FeedbackBase):
    def test_chain_keeps_history_and_computes_current(self) -> None:
        judge = self.add(C.LABEL_BOOL_NAMES[1], True, sequence_num=1,
                         source_type=C.FEEDBACK_SOURCE_JUDGE, source_id="heuristic-v1")
        person = self.add(C.LABEL_BOOL_NAMES[1], False, sequence_num=1, supersedes=judge["id"],
                          rationale="the judge misread the question")
        again = self.add(C.LABEL_BOOL_NAMES[1], True, sequence_num=1, supersedes=person["id"])
        current = fb.current_feedback(self.db, self.sid)
        self.assertEqual([r["id"] for r in current], [again["id"]])
        history = {r["id"]: r for r in fb.list_feedback(self.db, self.sid)}
        self.assertEqual(len(history), 3)
        self.assertEqual(history[judge["id"]]["superseded_by"], person["id"])
        self.assertEqual(history[person["id"]]["superseded_by"], again["id"])
        self.assertIsNone(history[again["id"]]["superseded_by"])
        self.assertEqual(history[person["id"]]["supersedes"], judge["id"])
        # Newest first.
        self.assertEqual([r["id"] for r in fb.list_feedback(self.db, self.sid)],
                         [again["id"], person["id"], judge["id"]])

    def test_supersession_invariants(self) -> None:
        base = self.add("n", "a", sequence_num=1)
        with self.assertRaisesRegex(fb.InvalidFeedbackError, "different target"):
            self.add("n", "b", sequence_num=3, supersedes=base["id"])
        with self.assertRaisesRegex(fb.InvalidFeedbackError, "different target"):
            self.add("n", "b", supersedes=base["id"])
        with self.assertRaisesRegex(fb.InvalidFeedbackError, "named"):
            self.add("m", "b", sequence_num=1, supersedes=base["id"])
        with self.assertRaisesRegex(fb.InvalidFeedbackError, "no feedback"):
            self.add("n", "b", sequence_num=1, supersedes=base["id"] + 99)
        with self.assertRaises(fb.InvalidFeedbackError):
            self.add("n", "b", sequence_num=1, supersedes=True)
        replacement = self.add("n", "b", sequence_num=1, supersedes=base["id"])
        # Branching: the base is no longer current.
        with self.assertRaisesRegex(fb.InvalidFeedbackError, "already superseded"):
            self.add("n", "c", sequence_num=1, supersedes=base["id"])
        # And the table refuses it even past the store's check.
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                f"INSERT INTO {C.TBL_FEEDBACK} (session_ref, sequence_num, name, value_text, "
                "source_type, source_id, supersedes, created_at) "
                "VALUES (?, 1, 'n', 'c', 'human', 'x', ?, 'now')",
                (self.sid, base["id"]),
            )
        self.db.rollback()
        # A racing writer: the store's check passes, the UNIQUE fires, and
        # the caller still gets the 400-class refusal, not a driver error.
        real_check = fb._check_supersedes
        with mock.patch.object(fb, "_check_supersedes", lambda *a, **k: base["id"]):
            with self.assertRaisesRegex(fb.InvalidFeedbackError, "another writer"):
                self.add("n", "d", sequence_num=1, supersedes=base["id"])
        self.assertIs(fb._check_supersedes, real_check)
        self.assertEqual([r["id"] for r in fb.current_feedback(self.db, self.sid)], [replacement["id"]])
        self.assertEqual([r["id"] for r in fb.current_feedback(self.db, self.sid)], [replacement["id"]])

    def test_a_row_in_another_session_cannot_be_superseded(self) -> None:
        base = self.add("n", "a")
        other = self.db.insert_returning_id(
            "INSERT INTO copilot_session (session_id, copilot, project_path, started_at) "
            "VALUES ('other', 'claude-code', '/p', '2026-01-01T00:00:00Z') RETURNING id", ()
        )
        self.db.commit()
        with self.assertRaisesRegex(fb.InvalidFeedbackError, "no feedback"):
            fb.add_feedback(self.db, other, "n", "b", C.FEEDBACK_SOURCE_HUMAN, "x", supersedes=base["id"])


class TestPayloadAndExport(FeedbackBase):
    def test_detail_payload_is_additive_and_folds_current_rows_only(self) -> None:
        old = self.add("n", "old", sequence_num=1)
        self.add("n", "new", sequence_num=1, supersedes=old["id"])
        self.add(C.FEEDBACK_NAME_RATING, 3)
        self.add("n", "c", sequence_num=1, tool_sequence_num=0)
        detail = tools.get_session_details(self.db, self.sid)
        self.assertEqual([(r["name"], r["value"]) for r in detail["feedback"]], [(C.FEEDBACK_NAME_RATING, 3)])
        turn1 = next(t for t in detail["turns"] if t["sequence_num"] == 1)
        self.assertEqual([r["value"] for r in turn1["feedback"]], ["new"])
        self.assertEqual([r["value"] for r in turn1["tool_calls"][0]["feedback"]], ["c"])
        for t in detail["turns"]:
            self.assertIn("feedback", t)
            for c in t["tool_calls"]:
                self.assertIn("feedback", c)
        for key in ("id", "source_type", "source_id", "name", "value", "rationale", "created_at"):
            self.assertIn(key, detail["feedback"][0])

    def test_the_payload_reads_feedback_in_one_query(self) -> None:
        self.add("n", "a", sequence_num=1)
        self.add("n", "b", sequence_num=3, tool_sequence_num=0)
        seen: list[str] = []
        original = self.db.execute

        def spy(sql, params=()):
            seen.append(" ".join(sql.split()))
            return original(sql, params)

        self.db.execute = spy  # type: ignore[method-assign]
        try:
            tools.get_session_details(self.db, self.sid)
        finally:
            self.db.execute = original  # type: ignore[method-assign]
        hits = [q for q in seen if f"FROM {C.TBL_FEEDBACK} " in q]
        self.assertEqual(len(hits), 1)
        # The one query is the current-rows self-join, filtered in SQL.
        self.assertIn(f"LEFT JOIN {C.TBL_FEEDBACK} later ON later.supersedes = f.id", hits[0])
        self.assertIn("later.id IS NULL", hits[0])

    def test_export_table(self) -> None:
        self.assertIn(C.EXPORT_TABLE_FEEDBACK, C.EXPORT_DATA_TABLES)
        self.add("n", True, sequence_num=1, tool_sequence_num=0, rationale="why")
        self.add(C.FEEDBACK_NAME_NOTE, "text")
        rows = list(exp.rows_for(self.db, C.EXPORT_TABLE_FEEDBACK))
        self.assertEqual(exp.columns_for(C.EXPORT_TABLE_FEEDBACK), exp.FEEDBACK_COLUMNS)
        as_dicts = [dict(zip(exp.FEEDBACK_COLUMNS, r)) for r in rows]
        self.assertEqual(as_dicts[0]["value_bool"], 1)
        self.assertEqual((as_dicts[0]["sequence_num"], as_dicts[0]["tool_sequence_num"]), (1, 0))
        self.assertEqual(as_dicts[1]["value_text"], "text")
        self.assertEqual(as_dicts[0]["rationale"], "why")


class TestSchemaBump(unittest.TestCase):
    def test_a_schema_8_store_gains_the_table_in_place(self) -> None:
        """A new table is the whole migration (D7): no refusal, no
        recreation; the store keeps its rows and is stamped 9."""
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp(prefix="cct-sa-v8-")) / "v8.db"
        store = Database.connect(f"sqlite:///{path}")
        dbmod.apply_ddl(store)
        store.execute(f"DROP TABLE {C.TBL_FEEDBACK}")
        store.execute("DELETE FROM schema_version WHERE version = ?", (dbmod._SCHEMA_VERSION,))
        store.execute("INSERT INTO schema_version (version, applied_at) VALUES (8, 'x')")
        store.execute(
            "INSERT INTO copilot_session (session_id, copilot, project_path, started_at) "
            "VALUES ('kept', 'claude-code', '/p', '2026-01-01T00:00:00Z')"
        )
        store.commit()
        self.assertEqual(store.query("SELECT MAX(version) FROM schema_version"), [(8,)])
        dbmod.apply_ddl(store)
        self.assertEqual(store.query("SELECT MAX(version) FROM schema_version"), [(9,)])
        self.assertTrue(dbmod._has_table(store, C.TBL_FEEDBACK))
        self.assertEqual(store.query("SELECT session_id FROM copilot_session"), [("kept",)])
        store.close()


if __name__ == "__main__":
    unittest.main()
