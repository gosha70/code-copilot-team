# Idempotency AC: re-ingesting must not duplicate; a grown session converges.

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_COUNT_TABLES = (
    "copilot_session",
    "copilot_turn",
    "copilot_tool_call",
    "copilot_tool_result",
    "copilot_file_access",
    "copilot_error",
)


def _counts(dsn: str) -> dict:
    db = Database.connect(dsn)
    try:
        return {t: db.query("SELECT COUNT(*) FROM " + t)[0][0] for t in _COUNT_TABLES}
    finally:
        db.close()


class TestIdempotentIngest(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def test_reingest_does_not_duplicate(self) -> None:
        dsn = self.sqlite_dsn()
        s1 = ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        first = _counts(dsn)
        self.assertEqual(s1.sessions_ingested, 1)
        self.assertGreater(first["copilot_turn"], 0)

        # Re-ingest the same data → identical counts, same single session id.
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        second = _counts(dsn)
        self.assertEqual(first, second)

        db = Database.connect(dsn)
        try:
            ids = db.query("SELECT id FROM copilot_session")
            self.assertEqual(len(ids), 1)
        finally:
            db.close()

    def test_derived_rows(self) -> None:
        dsn = self.sqlite_dsn()
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        c = _counts(dsn)
        # Two tool calls (Bash, Read); one file access (Read on app.py); one error.
        self.assertEqual(c["copilot_tool_call"], 2)
        self.assertEqual(c["copilot_file_access"], 1)
        self.assertEqual(c["copilot_error"], 1)

    def test_grown_session_converges(self) -> None:
        dsn = self.sqlite_dsn()
        # Copy the fixture so we can grow it without touching the committed file.
        work = Path(self.sqlite_dsn()[len("sqlite:///"):]).parent / "cc"
        shutil.copytree(CLAUDE_CODE_ROOT, work)
        jsonl = next(work.glob("*/*.jsonl"))

        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=work, full=True)
        before = _counts(dsn)

        # Append a new assistant turn (the session "grew").
        with jsonl.open("a", encoding="utf-8") as fh:
            fh.write(
                '{"type":"assistant","sessionId":"sess-tiny-001","parentUuid":"u3",'
                '"uuid":"a9","timestamp":"2026-05-29T10:00:09.000Z","message":'
                '{"role":"assistant","model":"claude-opus-4-8","content":'
                '[{"type":"text","text":"done"}]}}\n'
            )

        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=work, full=True)
        after = _counts(dsn)

        self.assertEqual(after["copilot_session"], 1)
        self.assertEqual(after["copilot_turn"], before["copilot_turn"] + 1)


if __name__ == "__main__":
    unittest.main()
