# Tests for the Claude Code JSONL adapter.

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.adapters.claude_code import ClaudeCodeAdapter

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class TestClaudeCodeAdapter(RegistryResetTestCase):
    def _load_only_session(self):
        adapter = ClaudeCodeAdapter()
        refs = adapter.discover(CLAUDE_CODE_ROOT)
        self.assertEqual(len(refs), 1)
        return adapter.load(refs[0]), refs[0]

    def test_discover_groups_by_session_id(self) -> None:
        adapter = ClaudeCodeAdapter()
        refs = adapter.discover(CLAUDE_CODE_ROOT)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].native_session_id, "sess-tiny-001")
        self.assertEqual(refs[0].copilot, C.COPILOT_CLAUDE_CODE)
        self.assertGreater(refs[0].latest_mtime, 0)

    def test_skips_non_conversational_types(self) -> None:
        session, _ = self._load_only_session()
        # 8 lines, but system + queue-operation are skipped → 6 turns.
        self.assertEqual(len(session.turns), 6)
        roles = [t.role for t in session.turns]
        self.assertEqual(
            roles,
            ["user", "assistant", "user", "assistant", "user", "assistant"],
        )

    def test_session_metadata(self) -> None:
        session, _ = self._load_only_session()
        self.assertEqual(session.model, "claude-opus-4-8")
        self.assertEqual(session.project_path, "/repo/demo")
        self.assertEqual(session.started_at, "2026-05-29T10:00:02.000Z")
        self.assertEqual(session.ended_at, "2026-05-29T10:00:07.000Z")
        self.assertEqual(session.metadata.get("git_branch"), "main")

    def test_slash_command_detected(self) -> None:
        session, _ = self._load_only_session()
        first_user = session.turns[0]
        self.assertEqual(first_user.slash_command, "/clear")

    def test_tool_use_paired_with_result_across_turns(self) -> None:
        session, _ = self._load_only_session()
        assistant1 = session.turns[1]
        self.assertEqual(len(assistant1.tool_calls), 1)
        call = assistant1.tool_calls[0]
        self.assertEqual(call.name_raw, "Bash")
        self.assertEqual(call.tool_use_id, "tool-1")
        self.assertIs(call.result_is_error, False)
        self.assertEqual(call.result_text, "3 passed")

    def test_error_result_flagged(self) -> None:
        session, _ = self._load_only_session()
        read_call = session.turns[3].tool_calls[0]
        self.assertEqual(read_call.name_raw, "Read")
        self.assertIs(read_call.result_is_error, True)
        self.assertIn("FileNotFoundError", read_call.result_text)

    def test_tokens_extracted(self) -> None:
        session, _ = self._load_only_session()
        a1 = session.turns[1]
        self.assertEqual(a1.tokens_input, 120)
        self.assertEqual(a1.tokens_output, 45)
        self.assertEqual(a1.cache_read_tokens, 1000)
        self.assertEqual(a1.cache_write_tokens, 50)

    def test_sidechain_marked(self) -> None:
        session, _ = self._load_only_session()
        self.assertFalse(session.turns[1].is_sidechain)
        # The trailing assistant turn (a3) is a sidechain branch.
        self.assertTrue(any(t.is_sidechain for t in session.turns))

    def test_thinking_blocks_excluded_from_text(self) -> None:
        session, _ = self._load_only_session()
        a1 = session.turns[1]
        self.assertIn("I'll run the tests.", a1.text)
        self.assertNotIn("let me look", a1.text)


if __name__ == "__main__":
    unittest.main()
