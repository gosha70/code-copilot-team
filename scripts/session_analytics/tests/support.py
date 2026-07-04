# session_analytics.tests.support — shared unittest base + fixture paths.
#
# Tests run under ``python3 -m unittest discover`` (the repo convention and
# the CI smoke gate), so we use unittest.TestCase with setUp/tearDown registry
# resets rather than pytest fixtures.

from __future__ import annotations

import unittest
from pathlib import Path

from session_analytics._register import unregister_all_for_tests

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLAUDE_CODE_ROOT = FIXTURES / "claude_code"


class RegistryResetTestCase(unittest.TestCase):
    """Resets the adapter/judge registries around every test."""

    def setUp(self) -> None:
        unregister_all_for_tests()

    def tearDown(self) -> None:
        unregister_all_for_tests()

    def sqlite_dsn(self) -> str:
        """A throwaway file-backed SQLite DSN under a per-test temp dir."""
        import tempfile

        tmp = tempfile.mkdtemp(prefix="cct-sa-test-")
        return f"sqlite:///{Path(tmp) / 'sa.db'}"
