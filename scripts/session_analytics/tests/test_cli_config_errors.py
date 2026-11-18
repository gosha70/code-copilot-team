from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr
from unittest import mock

from session_analytics import cli
from session_analytics import constants as C
from session_analytics.cli import main
from session_analytics.config import ConfigError, load_config


class ConfigErrorsAreUsageErrors(unittest.TestCase):
    """A bad configuration value is the user's mistake, not a crash.

    load_config raises ConfigError for it, and main() turns that into one line on stderr and
    EXIT_USAGE for every command - including the ones that never call load_config themselves
    (embed, serve, start) and reach it through something else.
    """

    def run_main(self, argv):
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(argv)
        return code, err.getvalue()

    def test_invalid_redaction_mode_reports_one_line(self):
        with mock.patch.dict(os.environ, {"CCT_SA_REDACTION": "bogus"}, clear=False):
            code, err = self.run_main(
                ["ingest", "--db", "sqlite:///:memory:", "--copilot", "claude-code"])
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn("error: invalid redaction mode", err)
        self.assertIn("expected one of", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(err.count("\n"), 1)

    def assert_one_usage_line(self, code, err, needle):
        self.assertEqual(code, C.EXIT_USAGE)
        self.assertIn(f"error: {needle}" if not needle.startswith("error:") else needle, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(err.count("\n"), 1, err)

    def test_a_bad_judge_worker_count_reports_one_line(self):
        with mock.patch.dict(os.environ, {"CCT_SA_JUDGE_WORKERS": "bogus"}, clear=False):
            code, err = self.run_main(
                ["ingest", "--db", "sqlite:///:memory:", "--copilot", "claude-code"])
        self.assert_one_usage_line(code, err, "CCT_SA_JUDGE_WORKERS must be an integer")

    def test_a_bad_embedding_worker_count_reports_one_line(self):
        with mock.patch.dict(os.environ, {"CCT_SA_EMBED_WORKERS": "bogus"}, clear=False):
            code, err = self.run_main(
                ["ingest", "--db", "sqlite:///:memory:", "--copilot", "claude-code"])
        self.assert_one_usage_line(code, err, "CCT_SA_EMBED_WORKERS must be an integer")

    def test_a_malformed_user_config_file_is_named(self):
        import tempfile
        from pathlib import Path
        from session_analytics import config as cfgmod

        bad = Path(tempfile.mkdtemp(prefix="cct-sa-badcfg-")) / "session-analytics.json"
        bad.write_text("{bad", encoding="utf-8")
        with mock.patch.object(cfgmod, "_USER_CONFIG", bad):
            code, err = self.run_main(
                ["ingest", "--db", "sqlite:///:memory:", "--copilot", "claude-code"])
        self.assert_one_usage_line(code, err, f"error: {bad}: not valid JSON (line 1")

    def test_load_config_raises_config_error_not_bare_valueerror(self):
        with mock.patch.dict(os.environ, {"CCT_SA_REDACTION": "bogus"}, clear=False):
            with self.assertRaises(ConfigError) as caught:
                load_config(dsn="sqlite:///:memory:")
        self.assertIsInstance(caught.exception, ValueError)
        self.assertIn("invalid redaction mode", str(caught.exception))

    def test_every_command_reports_a_config_error_the_same_way(self):
        """embed, serve and start never call load_config in their own body; the boundary is
        main(), so the check is that a ConfigError out of any handler becomes the same line."""
        argv = {
            "embed": ["embed", "--db", "sqlite:///:memory:"],
            "serve": ["serve", "--db", "sqlite:///:memory:", "--api-port", "0"],
            "start": ["start", "--api-port", "0", "--ui-port", "0"],
        }

        def broken(args):
            raise ConfigError("invalid redaction mode 'bogus'; expected one of ('none',)")

        for command, args in argv.items():
            with self.subTest(command=command):
                with mock.patch.dict(cli._HANDLERS, {command: broken}, clear=False):
                    code, err = self.run_main(args)
                self.assertEqual(code, C.EXIT_USAGE)
                self.assertIn("error: invalid redaction mode", err)
                self.assertNotIn("Traceback", err)

    def test_an_unrelated_valueerror_still_propagates(self):
        """Catches ConfigError only: a ValueError from a handler bug is a bug, and must not be
        reported to the user as their configuration being wrong."""

        def buggy(args):
            raise ValueError("list index out of range")

        with mock.patch.dict(cli._HANDLERS, {"kpis": buggy}, clear=False):
            with self.assertRaises(ValueError) as caught:
                self.run_main(["kpis", "--db", "sqlite:///:memory:"])
        self.assertNotIsInstance(caught.exception, ConfigError)


if __name__ == "__main__":
    unittest.main()
