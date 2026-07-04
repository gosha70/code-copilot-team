# Incremental-ingest gating: unchanged sessions are skipped on re-run.

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.ingest.pipeline import ingest

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class TestIncremental(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def test_second_incremental_run_skips_unchanged(self) -> None:
        dsn = self.sqlite_dsn()
        s1 = ingest(
            dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=False
        )
        self.assertEqual(s1.sessions_ingested, 1)
        self.assertEqual(s1.sessions_skipped, 0)

        s2 = ingest(
            dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=False
        )
        self.assertEqual(s2.sessions_ingested, 0)
        self.assertEqual(s2.sessions_skipped, 1)


if __name__ == "__main__":
    unittest.main()
