# Tests for dashboard aggregates (pure DB, no FastAPI).

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.api import dashboard
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class TestDashboard(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def test_kpis(self) -> None:
        k = dashboard.kpis(self.db)
        self.assertEqual(k["totals"]["sessions"], 1)
        self.assertEqual(k["totals"]["turns"], 6)
        self.assertEqual(k["totals"]["tool_calls"], 2)
        self.assertEqual(k["totals"]["errors"], 1)
        copilots = {c["copilot"] for c in k["by_copilot"]}
        self.assertEqual(copilots, {C.COPILOT_CLAUDE_CODE})
        tools = {t["tool"] for t in k["tool_usage"]}
        self.assertEqual(tools, {"bash", "file_read"})

    def test_label_distribution_empty_before_judge(self) -> None:
        dist = dashboard.label_distribution(self.db)
        self.assertEqual(len(dist["labels"]), 10)
        self.assertTrue(all(item["total"] == 0 for item in dist["labels"]))


if __name__ == "__main__":
    unittest.main()
