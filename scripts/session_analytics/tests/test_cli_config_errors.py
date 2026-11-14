from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr
from unittest import mock

from session_analytics import constants as C
from session_analytics.cli import main


class ConfigErrorsAreUsageErrors(unittest.TestCase):
    """A bad value in the environment is the user's mistake, not a crash."""

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
        self.assertNotIn("Traceback", err)

    def test_config_error_names_the_remedy(self):
        with mock.patch.dict(os.environ, {"CCT_SA_REDACTION": "bogus"}, clear=False):
            _, err = self.run_main(
                ["ingest", "--db", "sqlite:///:memory:", "--copilot", "claude-code"])
        self.assertIn("expected one of", err)
