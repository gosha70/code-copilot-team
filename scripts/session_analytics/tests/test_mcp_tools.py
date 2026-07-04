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

    def test_get_session_details(self) -> None:
        d = tools.get_session_details(self.db, self._session_id())
        self.assertEqual(len(d["turns"]), 6)
        self.assertEqual(d["error_count"], 1)
        tool_names = {t["tool"] for t in d["tool_usage"]}
        self.assertEqual(tool_names, {"bash", "file_read"})
        self.assertEqual(len(d["errors"]), 1)

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
