# Tests for content redaction — incl. the tool-output leak fix (P1).
#
# Regression: error tool-results bypassed redaction and stored raw output
# (secrets, file contents) into copilot_tool_result.error_message and
# copilot_error.error_message/error_type. Both inserts now route through the
# redaction layer; under any non-`none` mode no raw output is persisted.

from __future__ import annotations

import ntpath
import os
import posixpath
import unittest
from unittest import mock

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



class OutboundFloor(unittest.TestCase):
    """#457 FR-005: the rule every off-machine path applies."""

    def test_the_stricter_mode_wins(self):
        from session_analytics.ingest.redaction import outbound_mode

        self.assertEqual(outbound_mode(C.REDACT_NONE, C.REDACT_CODE, False), C.REDACT_CODE)
        self.assertEqual(outbound_mode(C.REDACT_METADATA_ONLY, C.REDACT_CODE, False), C.REDACT_METADATA_ONLY)
        self.assertEqual(outbound_mode(None, C.REDACT_CODE, False), C.REDACT_CODE)

    def test_an_unknown_mode_fails_closed(self):
        from session_analytics.ingest.redaction import outbound_mode

        self.assertEqual(outbound_mode("bogus", C.REDACT_NONE, False), C.REDACT_METADATA_ONLY)

    def test_an_opted_out_project_is_skipped(self):
        from session_analytics.ingest.redaction import outbound_mode

        self.assertIsNone(outbound_mode(C.REDACT_METADATA_ONLY, C.REDACT_METADATA_ONLY, True))

    def test_an_id_that_is_not_a_session_row_id_is_not_kept(self):
        from session_analytics.ingest.redaction import OutboundPolicy

        policy = OutboundPolicy(skip_ids=frozenset({7}))
        self.assertTrue(policy.keeps(8))
        self.assertFalse(policy.keeps(7))
        for bad in (None, "seven", "", 1.5j):
            with self.subTest(value=bad):
                self.assertFalse(policy.keeps(bad))

    def test_text_tightened_after_ingest_leaves_as_a_marker_not_a_rerun(self):
        from session_analytics.ingest.redaction import outbound_text

        # A preview stored under none is already cut at 500 chars, so a
        # fence opened before the cut has no closing marker: re-redacting
        # it under code would leave the secret. The marker never does.
        cut = ("x" * 480) + "```\nsk-secret"
        self.assertNotIn("sk-secret", outbound_text(cut, C.REDACT_NONE, C.REDACT_CODE))
        self.assertTrue(outbound_text(cut, C.REDACT_NONE, C.REDACT_CODE).startswith("[redacted"))
        self.assertEqual(outbound_text("kept", C.REDACT_CODE, C.REDACT_CODE), "kept")
        self.assertIsNone(outbound_text(None, C.REDACT_NONE, C.REDACT_METADATA_ONLY))

    def test_archived_text_is_judged_by_its_rows_own_recorded_mode(self):
        """After a tightening and `ingest --full` the session is re-recorded
        under the current mode, so it is not floored, but a row archived
        before it keeps its older mode until `archive --full`."""
        from session_analytics.ingest.redaction import OutboundPolicy

        M, N = C.REDACT_METADATA_ONLY, C.REDACT_NONE
        policy = OutboundPolicy(current={1: M}, recorded={1: M})
        self.assertFalse(policy.floors(1))
        self.assertEqual(policy.text(1, "sk-secret"), "sk-secret")  # previews were re-redacted
        self.assertTrue(policy.archived_text(1, "sk-secret", N).startswith("[redacted"))
        self.assertTrue(policy.archive_floors(1, N))
        # A row archived under the current mode, or a stricter one, is as stored.
        self.assertEqual(policy.archived_text(1, "kept", M), "kept")
        self.assertFalse(policy.archive_floors(1, M))
        loosened = OutboundPolicy(current={2: N}, recorded={2: N})
        self.assertEqual(loosened.archived_text(2, "[redacted 9 chars sha256:x]", M), "[redacted 9 chars sha256:x]")
        self.assertFalse(loosened.archive_floors(2, M))

    def test_an_archived_row_with_no_or_an_unknown_mode_fails_closed(self):
        """Not the session's mode: a re-ingest may have made it stricter
        than the row was written under."""
        from session_analytics.ingest.redaction import OutboundPolicy

        policy = OutboundPolicy(current={1: C.REDACT_METADATA_ONLY}, recorded={1: C.REDACT_METADATA_ONLY})
        for row_mode in (None, "", "bogus"):
            with self.subTest(row_mode=row_mode):
                self.assertTrue(policy.archived_text(1, "sk-secret", row_mode).startswith("[redacted"))
                self.assertTrue(policy.archive_floors(1, row_mode))

    def test_the_loosest_mode_of_several_counts_a_missing_or_unknown_one_as_none(self):
        from session_analytics.ingest.redaction import loosest_mode

        M, K, N = C.REDACT_METADATA_ONLY, C.REDACT_CODE, C.REDACT_NONE
        self.assertEqual(loosest_mode([M, K]), K)
        self.assertEqual(loosest_mode([M, M]), M)
        self.assertEqual(loosest_mode([M, None]), N)
        self.assertEqual(loosest_mode([M, "bogus"]), N)
        self.assertIsNone(loosest_mode([]))

    def test_the_mode_text_leaves_under_is_metadata_only_when_it_leaves_as_the_marker(self):
        from session_analytics.ingest.redaction import OutboundPolicy

        M, K, N = C.REDACT_METADATA_ONLY, C.REDACT_CODE, C.REDACT_NONE
        policy = OutboundPolicy(current={1: K}, recorded={1: K})
        self.assertEqual(policy.leaving_mode(1, N), M)  # looser than the current mode: the marker
        self.assertEqual(policy.leaving_mode(1, K), K)
        self.assertEqual(policy.leaving_mode(1, M), M)
        self.assertEqual(policy.leaving_mode(1, None), M)  # missing counts as none, then floored
        self.assertEqual(policy.recorded_mode(1), K)
        self.assertIsNone(policy.recorded_mode(2))

    def test_the_archived_methods_are_the_recorded_ones(self):
        from session_analytics.ingest.redaction import OutboundPolicy

        policy = OutboundPolicy(current={1: C.REDACT_METADATA_ONLY}, recorded={1: C.REDACT_METADATA_ONLY})
        for mode in (C.REDACT_NONE, C.REDACT_METADATA_ONLY, None):
            with self.subTest(mode=mode):
                self.assertEqual(policy.archived_text(1, "t", mode), policy.recorded_text(1, "t", mode))
                self.assertEqual(policy.archive_floors(1, mode), policy.recorded_floors(1, mode))

    def test_a_session_the_policy_does_not_know_keeps_the_session_floor(self):
        from session_analytics.ingest.redaction import OutboundPolicy

        policy = OutboundPolicy(floored={3: (C.REDACT_NONE, C.REDACT_METADATA_ONLY)})
        self.assertTrue(policy.archived_text(3, "sk-secret", C.REDACT_NONE).startswith("[redacted"))
        self.assertEqual(policy.archived_text(4, "kept", C.REDACT_NONE), "kept")
        self.assertEqual((policy.archive_floors(3, C.REDACT_NONE), policy.archive_floors(4, C.REDACT_NONE)), (True, False))


WINDOWS_RULES = mock.patch.object(redaction.os, "path", ntpath)


class OutboundProjectPaths(unittest.TestCase):
    """#548: a path inside an opted-out project is recognised however it is
    spelled, so the floor holds on Windows as it does elsewhere."""

    def policy(self, *roots: str) -> redaction.OutboundPolicy:
        return redaction.OutboundPolicy(excluded_projects=frozenset(roots))

    @WINDOWS_RULES
    def test_a_windows_path_inside_the_project_is_named(self):
        policy = self.policy("C:\\Users\\me\\repo")
        self.assertTrue(policy.names_project("C:\\Users\\me\\repo"))
        self.assertTrue(policy.names_project("C:\\Users\\me\\repo\\src\\app.py"))

    @WINDOWS_RULES
    def test_a_forward_slash_spelling_is_named(self):
        policy = self.policy("C:\\Users\\me\\repo")
        self.assertTrue(policy.names_project("C:/Users/me/repo"))
        self.assertTrue(policy.names_project("C:/Users/me/repo/src/app.py"))

    @WINDOWS_RULES
    def test_letter_case_and_a_trailing_separator_do_not_matter(self):
        policy = self.policy("c:\\users\\ME\\repo\\")
        self.assertTrue(policy.names_project("C:\\Users\\me\\Repo\\src\\app.py"))

    @WINDOWS_RULES
    def test_a_neighbouring_parent_or_other_drive_path_is_not_named(self):
        policy = self.policy("C:\\Users\\me\\repo")
        for other in ("C:\\Users\\me\\repo-other\\app.py", "C:\\Users\\me", "D:\\Users\\me\\repo\\app.py"):
            with self.subTest(other=other):
                self.assertFalse(policy.names_project(other))

    def test_a_path_inside_the_project_is_named_on_this_platform(self):
        root = os.path.abspath(os.path.join(os.sep, "work", "repo"))
        policy = self.policy(root)
        self.assertTrue(policy.names_project(os.path.join(root, "src", "app.py")))
        self.assertTrue(policy.names_project(root + os.sep))
        self.assertFalse(policy.names_project(root + "-other"))
        self.assertFalse(policy.names_project(os.path.dirname(root)))

    @WINDOWS_RULES
    def test_a_path_inside_a_longer_value_is_named(self):
        policy = self.policy("C:\\Users\\me\\repo")
        for value in (
            "Edited C:\\Users\\me\\repo\\a.py",
            "Edited C:\\Users\\me\\repo",
            "opened (C:\\Users\\me\\repo) and saved",
            "see C:/Users/me/repo/a.py.",
            "file:///C:/Users/me/repo/a.py",
            "\\\\?\\C:\\Users\\me\\repo\\a.py",
        ):
            with self.subTest(value=value):
                self.assertTrue(policy.names_project(value))

    @WINDOWS_RULES
    def test_a_file_url_is_decoded_before_it_is_compared(self):
        policy = self.policy("C:\\Users\\me\\My Repo")
        self.assertTrue(policy.names_project("file:///C:/Users/me/My%20Repo/a.py"))

    @WINDOWS_RULES
    def test_a_longer_value_that_only_looks_alike_is_not_named(self):
        policy = self.policy("C:\\Users\\me\\repo")
        for value in (
            "Edited C:\\Users\\me\\repo-other\\a.py",
            "Edited C:\\Users\\me\\repo2",
            "Edited D:\\Users\\me\\repo\\a.py",
            "Edited C:\\Users\\me",
            "Edited xC:\\Users\\me\\repo\\a.py",
        ):
            with self.subTest(value=value):
                self.assertFalse(policy.names_project(value))

    def test_a_path_inside_a_longer_value_is_named_on_this_platform(self):
        policy = self.policy("/work/repo")
        with mock.patch.object(redaction.os, "path", posixpath):
            self.assertTrue(policy.names_project("see /work/repo/secret.env"))
            self.assertTrue(policy.names_project("see /work/repo"))
            self.assertTrue(policy.names_project("file:///work/repo/a.py"))
            self.assertFalse(policy.names_project("see /work/repo-other/a.py"))
            self.assertFalse(policy.names_project("see /home/me/work/repo/a.py"))

    def test_letter_case_is_ignored_on_macos(self):
        for platform, named in (("darwin", True), ("linux", False)):
            with self.subTest(platform=platform):
                policy = self.policy("/Users/me/Repo")
                with mock.patch.object(redaction.os, "path", posixpath), mock.patch.object(
                    redaction.sys, "platform", platform
                ):
                    self.assertEqual(policy.names_project("/users/ME/repo/a.py"), named)

    def test_a_sibling_whose_name_starts_with_the_project_and_a_dot_is_not_named(self):
        policy = self.policy("/work/repo")
        with mock.patch.object(redaction.os, "path", posixpath):
            for value in ("/work/repo.bak/a.py", "/work/repo.git", "see /work/repo.old/a.py"):
                with self.subTest(value=value):
                    self.assertFalse(policy.names_project(value))
            for value in ("see /work/repo.", "see /work/repo, then", "/work/repo/.git/config"):
                with self.subTest(value=value):
                    self.assertTrue(policy.names_project(value))

    def test_a_project_at_the_filesystem_root_names_every_absolute_path(self):
        policy = self.policy("/")
        with mock.patch.object(redaction.os, "path", posixpath):
            for value in ("/etc/passwd", "/", "see /etc/passwd"):
                with self.subTest(value=value):
                    self.assertTrue(policy.names_project(value))
            self.assertFalse(policy.names_project("etc"))

    @WINDOWS_RULES
    def test_a_project_at_a_drive_root_names_that_drive_only(self):
        policy = self.policy("C:\\")
        self.assertTrue(policy.names_project("C:\\Users\\me\\a.py"))
        self.assertTrue(policy.names_project("C:/Users/me/a.py"))
        self.assertFalse(policy.names_project("D:\\Users\\me\\a.py"))

    def test_nothing_is_named_when_nothing_is_opted_out_or_the_value_is_empty(self):
        self.assertFalse(self.policy().names_project("/work/repo/app.py"))
        self.assertFalse(self.policy("/work/repo").names_project(""))
        self.assertFalse(self.policy("/work/repo").names_project(None))


if __name__ == "__main__":
    unittest.main()
