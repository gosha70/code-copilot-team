# Tests for cross-copilot tool-name + file normalization.

from __future__ import annotations

import unittest

from session_analytics.normalize import files, tool_names


class TestToolNameNormalization(unittest.TestCase):
    def test_known_aliases_map_to_canonical(self) -> None:
        cases = {
            "Bash": "bash",
            "execute_bash": "bash",
            "Read": "file_read",
            "Write": "file_write",
            "Edit": "file_edit",
            "Glob": "file_search",
            "Grep": "file_search",
            "WebFetch": "web_fetch",
        }
        for raw, expected in cases.items():
            self.assertEqual(tool_names.normalize(raw), expected, raw)

    def test_unknown_falls_through_lowercased(self) -> None:
        self.assertEqual(tool_names.normalize("SomeNewTool"), "somenewtool")

    def test_empty(self) -> None:
        self.assertEqual(tool_names.normalize(""), "")


class TestFileNormalization(unittest.TestCase):
    def test_language_by_extension(self) -> None:
        self.assertEqual(files.language_for("/a/b/app.py"), "python")
        self.assertEqual(files.language_for("x.tsx"), "typescript")
        self.assertIsNone(files.language_for("/a/b/Makefile"))
        self.assertIsNone(files.language_for("noext"))

    def test_path_from_input(self) -> None:
        self.assertEqual(files.path_from_input({"file_path": "/x.py"}), "/x.py")
        self.assertEqual(files.path_from_input({"path": "/y.js"}), "/y.js")
        self.assertIsNone(files.path_from_input({"command": "ls"}))
        self.assertIsNone(files.path_from_input("notadict"))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
