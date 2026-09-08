# Tests for MCP tool + resource implementations (DB-backed, no MCP SDK).

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.ingest.pipeline import ingest
from session_analytics.mcp import resources, tools
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class TestMcpTools(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def _session_id(self) -> int:
        return self.db.query("SELECT id FROM copilot_session")[0][0]

    def test_search_sessions(self) -> None:
        res = tools.search_sessions(self.db, "demo")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["copilot"], C.COPILOT_CLAUDE_CODE)

        self.assertEqual(tools.search_sessions(self.db, "nonexistent-xyz"), [])
        self.assertEqual(len(tools.search_sessions(self.db, copilot="claude-code")), 1)

    def test_search_sessions_sorts_server_side_with_a_closed_column_map(self) -> None:
        # The Sessions grid sorts by clicking a header; the ORDER BY is
        # the server's (the list is the top N AFTER ordering) and the
        # column comes from a closed map, never from the caller's text.
        for sid, turns, errors, started in (("s-many", 500, 9, "2026-01-01T00:00:00Z"),
                                            ("s-few", 3, 0, "2026-03-01T00:00:00Z")):
            self.db.execute(
                "INSERT INTO copilot_session (copilot, session_id, project_path, turn_count, "
                "tool_call_count, error_count, duration_seconds, started_at, developer_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (C.COPILOT_CLAUDE_CODE, sid, "/w/" + sid, turns, 1, errors, 600, started,
                 C.DEFAULT_DEVELOPER_ID),
            )
        self.db.commit()
        by_turns = [r["session_id"] for r in tools.search_sessions(self.db, sort="turn_count")]
        self.assertEqual(by_turns[0], "s-many")
        self.assertEqual(by_turns[-1], "s-few")
        asc = [r["session_id"] for r in tools.search_sessions(self.db, sort="turn_count", descending=False)]
        self.assertEqual(asc[0], "s-few")
        by_err = [r["session_id"] for r in tools.search_sessions(self.db, sort="error_count")]
        self.assertEqual(by_err[0], "s-many")
        newest = [r["session_id"] for r in tools.search_sessions(self.db)]
        # default: started_at desc, as before (the fixture session is the newest)
        self.assertEqual(newest.index("s-few") + 1, newest.index("s-many"))
        # limit applies after ordering: top 1 by turns is the big one
        self.assertEqual(
            tools.search_sessions(self.db, sort="turn_count", limit=1)[0]["session_id"], "s-many"
        )
        with self.assertRaises(tools.UnknownSortError):
            tools.search_sessions(self.db, sort="id; DROP TABLE copilot_session")

    def test_get_session_details(self) -> None:
        d = tools.get_session_details(self.db, self._session_id())
        self.assertEqual(len(d["turns"]), 6)
        self.assertEqual(d["error_count"], 1)
        tool_names = {t["tool"] for t in d["tool_usage"]}
        self.assertEqual(tool_names, {"bash", "file_read"})
        self.assertEqual(len(d["errors"]), 1)

    def test_get_session_details_latency_and_text(self) -> None:
        d = tools.get_session_details(self.db, self._session_id())
        turns = d["turns"]
        # The first turn has no predecessor; every later one has a delta
        # derived from copilot_turn.timestamp, never negative.
        self.assertIsNone(turns[0]["latency_seconds"])
        self.assertTrue(all(t["timestamp"] for t in turns))
        later = [t["latency_seconds"] for t in turns[1:]]
        self.assertTrue(all(v is not None and v >= 0 for v in later))
        # Summary is over assistant turns only.
        n_assistant = sum(1 for t in turns[1:] if t["role"] == "assistant")
        self.assertEqual(d["latency"]["measured_turns"], n_assistant)
        self.assertEqual(d["latency"]["max"], max(
            t["latency_seconds"] for t in turns if t["role"] == "assistant"
        ))
        self.assertLessEqual(len(d["latency"]["slowest"]), 5)
        # No trace archive in this fixture: content is None, not "".
        self.assertTrue(all(t["content"] is None and not t["archived"] for t in turns))

    def test_two_rubric_rows_do_not_duplicate_a_turn(self) -> None:
        # heuristic_label is UNIQUE(turn_id, rubric_name): a turn judged
        # under two rubrics has two rows. The page must still see ONE
        # turn, with ONE latency sample, not [.., 3, 3] and a false 0s gap.
        sid = self._session_id()
        before = tools.get_session_details(self.db, sid)
        turn_id = self.db.query_one(
            "SELECT id FROM copilot_turn WHERE session_id = ? AND role = ? "
            "ORDER BY sequence_num LIMIT 1 OFFSET 1",
            (sid, C.ROLE_ASSISTANT),
        )[0]
        for rubric in ("a-rubric", "b-rubric"):
            self.db.execute(
                "INSERT INTO heuristic_label (turn_id, rubric_name, sentiment) VALUES (?, ?, ?)",
                (turn_id, rubric, "NEUTRAL"),
            )
        self.db.commit()
        after = tools.get_session_details(self.db, sid)
        self.assertEqual(
            [t["sequence_num"] for t in after["turns"]],
            [t["sequence_num"] for t in before["turns"]],
        )
        self.assertEqual(after["latency"], before["latency"])
        self.assertEqual(sum(1 for t in after["turns"] if t["sentiment"]), 1)

    def test_latency_needs_both_neighbours_stamped(self) -> None:
        # 00:00, NULL, 00:02 → the third turn's gap is unmeasurable (its
        # predecessor has no stamp), not "120s since the last stamp".
        sid = self._session_id()
        seqs = [
            r[0] for r in self.db.query(
                "SELECT sequence_num FROM copilot_turn WHERE session_id = ? "
                "ORDER BY sequence_num LIMIT 3", (sid,),
            )
        ]
        stamps = ["2026-01-01T00:00:00+00:00", None, "2026-01-01T00:02:00+00:00"]
        for seq, ts in zip(seqs, stamps):
            self.db.execute(
                "UPDATE copilot_turn SET timestamp = ? WHERE session_id = ? AND sequence_num = ?",
                (ts, sid, seq),
            )
        self.db.commit()
        turns = tools.get_session_details(self.db, sid)["turns"][:3]
        self.assertEqual([t["latency_seconds"] for t in turns], [None, None, None])

    def test_latency_percentile_is_nearest_rank(self) -> None:
        # The repository's rule (predict._percentile, #304): ceil(q·n).
        self.assertEqual(tools._percentile([1, 2, 3, 4, 5, 6], 0.9), 6)
        self.assertEqual(tools._percentile([1, 2, 3, 4, 5, 6], 0.5), 3)
        self.assertEqual(tools._percentile([7], 0.9), 7)

    def test_get_session_details_missing(self) -> None:
        self.assertIn("error", tools.get_session_details(self.db, 99999))

    def test_analyze_patterns(self) -> None:
        p = tools.analyze_patterns(self.db)
        tool_map = {t["tool"]: t for t in p["tools"]}
        self.assertEqual(tool_map["file_read"]["errors"], 1)
        self.assertEqual(tool_map["bash"]["errors"], 0)
        self.assertTrue(p["errors"])

    def test_resources(self) -> None:
        errs = resources.recent_errors(self.db)
        self.assertEqual(len(errs["errors"]), 1)
        stats = resources.tool_stats(self.db)
        read = next(t for t in stats["tools"] if t["tool"] == "file_read")
        self.assertEqual(read["error_rate"], 1.0)
        summary = resources.session_summary(self.db)
        self.assertEqual(len(summary["sessions"]), 1)


if __name__ == "__main__":
    unittest.main()
