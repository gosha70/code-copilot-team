# Tests for content redaction — incl. the tool-output leak fix (P1).
#
# Regression: error tool-results bypassed redaction and stored raw output
# (secrets, file contents) into copilot_tool_result.error_message and
# copilot_error.error_message/error_type. Both inserts now route through the
# redaction layer; under any non-`none` mode no raw output is persisted.

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.contracts import RawSession, RawToolCall, RawTurn
from session_analytics.ingest import redaction
from session_analytics.relational import store
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import RegistryResetTestCase

_SECRET = "SECRET_TOKEN=sk-test-should-not-store"


class TestRedactionHelpers(unittest.TestCase):
    def test_redact_result_modes(self) -> None:
        self.assertEqual(redaction.redact_result(_SECRET, C.REDACT_NONE), _SECRET)
        for mode in (C.REDACT_CODE, C.REDACT_METADATA_ONLY):
            out = redaction.redact_result(_SECRET, mode)
            self.assertNotIn("sk-test", out)
            self.assertIn("redacted", out)
        self.assertIsNone(redaction.redact_result(None, C.REDACT_CODE))

    def test_safe_error_type(self) -> None:
        # Recognized exception classes survive (useful for grouping)…
        self.assertEqual(
            redaction.safe_error_type("FileNotFoundError: /a/app.py", C.REDACT_CODE),
            "FileNotFoundError",
        )
        # …arbitrary/secret content collapses to "redacted".
        self.assertEqual(redaction.safe_error_type(_SECRET, C.REDACT_CODE), "redacted")
        # none keeps the first line verbatim.
        self.assertEqual(
            redaction.safe_error_type(_SECRET, C.REDACT_NONE), _SECRET
        )


def _session_with_secret_error() -> RawSession:
    call = RawToolCall(
        tool_use_id="t1",
        name_raw="Bash",
        input_obj={"command": "env"},
        sequence_num=0,
        result_is_error=True,
        result_text=_SECRET,
    )
    turn = RawTurn(
        sequence_num=0, role=C.ROLE_ASSISTANT, text="run env", content_length=7,
        tool_calls=(call,),
    )
    return RawSession(
        copilot=C.COPILOT_CLAUDE_CODE,
        native_session_id="s-secret",
        turns=(turn,),
        source_files=(),
    )


class TestStoreRedaction(RegistryResetTestCase):
    def _ingest(self, mode: str) -> Database:
        db = Database.connect(self.sqlite_dsn())
        apply_ddl(db)
        store.upsert_session(db, _session_with_secret_error(), redaction_mode=mode)
        return db

    def test_secret_not_stored_under_code(self) -> None:
        db = self._ingest(C.REDACT_CODE)
        try:
            tr = db.query("SELECT error_message FROM copilot_tool_result")[0][0]
            err_msg = db.query("SELECT error_message FROM copilot_error")[0][0]
            err_type = db.query("SELECT error_type FROM copilot_error")[0][0]
            for field in (tr, err_msg, err_type):
                self.assertNotIn("sk-test", field or "")
                self.assertNotIn("SECRET_TOKEN", field or "")
            # True length is preserved as separate metadata.
            out_len = db.query("SELECT output_length FROM copilot_tool_result")[0][0]
            self.assertEqual(out_len, len(_SECRET))
        finally:
            db.close()

    def test_secret_not_stored_under_metadata_only(self) -> None:
        db = self._ingest(C.REDACT_METADATA_ONLY)
        try:
            for table in ("copilot_tool_result", "copilot_error"):
                msg = db.query(f"SELECT error_message FROM {table}")[0][0]
                self.assertNotIn("sk-test", msg or "")
        finally:
            db.close()

    def test_secret_stored_only_under_explicit_none(self) -> None:
        db = self._ingest(C.REDACT_NONE)
        try:
            tr = db.query("SELECT error_message FROM copilot_tool_result")[0][0]
            self.assertIn(_SECRET, tr)  # explicit opt-in for full fidelity
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
