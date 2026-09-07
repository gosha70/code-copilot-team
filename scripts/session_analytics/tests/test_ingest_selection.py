# Choosing which discovered sessions to load (the owner's per-session
# selection requirement): the rules on SessionRef, the CLI flags, the
# discover listing, and the API body.

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from session_analytics import constants as C
from session_analytics.cli import main
from session_analytics.contracts import SessionRef
from session_analytics.ingest.pipeline import discover_sessions, ingest
from session_analytics.ingest.selection import IngestSelection, describe, parse_since

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


def _ref(sid: str, mtime: float) -> SessionRef:
    return SessionRef(copilot="x", native_session_id=sid, source_files=(), latest_mtime=mtime)


class TestSelectionRules(unittest.TestCase):
    def test_everything_by_default(self) -> None:
        refs = [_ref("a", 1), _ref("b", 2)]
        self.assertTrue(IngestSelection().is_everything)
        self.assertEqual(IngestSelection().apply(refs), refs)

    def test_since_limit_and_pick_compose(self) -> None:
        refs = [_ref("a", 10), _ref("b", 20), _ref("c", 30), _ref("d", 40)]
        self.assertEqual([r.native_session_id for r in IngestSelection(since=20).apply(refs)],
                         ["b", "c", "d"])
        # newest N, newest first
        self.assertEqual([r.native_session_id for r in IngestSelection(limit=2).apply(refs)],
                         ["d", "c"])
        self.assertEqual(
            [r.native_session_id for r in IngestSelection(since=20, limit=2).apply(refs)],
            ["d", "c"],
        )
        self.assertEqual(
            [r.native_session_id for r in
             IngestSelection(session_ids=frozenset({"a", "c"})).apply(refs)],
            ["a", "c"],
        )
        self.assertEqual(IngestSelection(limit=0).apply(refs), [])

    def test_parse_since_accepts_date_and_iso_and_names_bad_input(self) -> None:
        self.assertEqual(parse_since("1970-01-02"), 86400.0)
        self.assertEqual(parse_since("1970-01-01T00:00:10+00:00"), 10.0)
        with self.assertRaises(ValueError) as cm:
            parse_since("yesterday")
        self.assertIn("yesterday", str(cm.exception))

    def test_describe_reads_size_and_source_dir_without_parsing(self) -> None:
        f = next(CLAUDE_CODE_ROOT.glob("*/*.jsonl"))
        ref = SessionRef(copilot="claude-code", native_session_id="s", source_files=(f,),
                         latest_mtime=f.stat().st_mtime)
        row = describe(ref)
        self.assertEqual(row["source"], f.parent.name)
        self.assertEqual(row["bytes"], f.stat().st_size)
        self.assertEqual(row["files"], 1)


class TestSelectionInIngest(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        from session_analytics._register import register_all

        register_all()

    def test_selection_leaves_unselected_sessions_out_and_counts_them(self) -> None:
        dsn = self.sqlite_dsn()
        far_future = 4102444800.0  # 2100-01-01: nothing is that new
        st = ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
                    full=True, selection=IngestSelection(since=far_future))
        self.assertEqual(st.sessions_ingested, 0)
        self.assertEqual(st.sessions_not_selected, 1)
        self.assertEqual(st.as_dict()["sessions_not_selected"], 1)
        st = ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
                    full=True, selection=IngestSelection(limit=1))
        self.assertEqual(st.sessions_ingested, 1)
        self.assertEqual(st.sessions_not_selected, 0)

    def test_discover_lists_newest_first_with_loaded_state(self) -> None:
        dsn = self.sqlite_dsn()
        before = discover_sessions(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT)
        self.assertEqual(before["total"], 1)
        self.assertEqual(before["new"], 1)
        self.assertFalse(before["sessions"][0]["loaded"])
        self.assertGreater(before["total_bytes"], 0)
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        after = discover_sessions(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT)
        self.assertTrue(after["sessions"][0]["loaded"])
        self.assertEqual(after["new"], 0)
        self.assertEqual(after["new_bytes"], 0)
        # the pick, by the id the listing shows
        sid = after["sessions"][0]["session_id"]
        picked = discover_sessions(
            dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            selection=IngestSelection(session_ids=frozenset({sid})),
        )
        self.assertEqual(picked["total"], 1)
        none = discover_sessions(
            dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            selection=IngestSelection(session_ids=frozenset({"nope"})),
        )
        self.assertEqual(none["total"], 0)


def _run(argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class TestSelectionCli(RegistryResetTestCase):
    def test_list_then_load_by_id(self) -> None:
        dsn = self.sqlite_dsn()
        base = ["ingest", "--copilot", "claude-code", "--root", str(CLAUDE_CODE_ROOT), "--dsn", dsn]
        code, out, _ = _run([*base, "--list"])
        self.assertEqual(code, C.EXIT_OK)
        listing = json.loads(out)
        self.assertEqual(listing["new"], 1)
        sid = listing["sessions"][0]["session_id"]

        code, out, _ = _run([*base, "--session-id", "not-there"])
        self.assertEqual(code, C.EXIT_OK)
        self.assertEqual(json.loads(out)["sessions_ingested"], 0)
        self.assertEqual(json.loads(out)["sessions_not_selected"], 1)

        code, out, _ = _run([*base, "--session-id", sid, "--since", "1970-01-01", "--limit", "5"])
        self.assertEqual(code, C.EXIT_OK)
        self.assertEqual(json.loads(out)["sessions_ingested"], 1)

    def test_bad_since_is_a_usage_error(self) -> None:
        code, _, err = _run(["ingest", "--dsn", self.sqlite_dsn(), "--since", "last week"])
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("last week", err)


if __name__ == "__main__":
    unittest.main()
