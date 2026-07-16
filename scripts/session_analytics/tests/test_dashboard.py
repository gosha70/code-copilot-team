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

    def test_effective_redaction_by_project(self) -> None:
        # Uniform project: every session shares one redaction_mode.
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, redaction_mode) "
            "VALUES (?, ?, ?, ?)",
            (C.COPILOT_CLAUDE_CODE, "s-uniform-1", "/work/client-a", "code"),
        )
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, redaction_mode) "
            "VALUES (?, ?, ?, ?)",
            (C.COPILOT_CLAUDE_CODE, "s-uniform-2", "/work/client-a", "code"),
        )
        # Mixed project: redaction_mode changed between ingests.
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, redaction_mode) "
            "VALUES (?, ?, ?, ?)",
            (C.COPILOT_CLAUDE_CODE, "s-mixed-1", "/work/client-b", "code"),
        )
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, redaction_mode) "
            "VALUES (?, ?, ?, ?)",
            (C.COPILOT_CLAUDE_CODE, "s-mixed-2", "/work/client-b", "metadata-only"),
        )
        self.db.commit()

        result = dashboard.effective_redaction_by_project(self.db)
        by_path = {p["project_path"]: p for p in result["projects"]}

        uniform = by_path["/work/client-a"]
        self.assertEqual(uniform["session_count"], 2)
        self.assertEqual(uniform["redaction_modes"], {"code": 2})
        self.assertEqual(uniform["effective_redaction_mode"], "code")

        mixed = by_path["/work/client-b"]
        self.assertEqual(mixed["session_count"], 2)
        self.assertEqual(mixed["redaction_modes"], {"code": 1, "metadata-only": 1})
        self.assertEqual(mixed["effective_redaction_mode"], "mixed")


if __name__ == "__main__":
    unittest.main()
