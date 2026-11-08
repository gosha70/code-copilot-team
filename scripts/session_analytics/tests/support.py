# session_analytics.tests.support — shared unittest base + fixture paths.
#
# Tests run under ``python3 -m unittest discover`` (the repo convention and
# the CI smoke gate), so we use unittest.TestCase with setUp/tearDown registry
# resets rather than pytest fixtures.

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Optional
from unittest import mock

from session_analytics._register import unregister_all_for_tests

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLAUDE_CODE_ROOT = FIXTURES / "claude_code"
NO_USER_CONFIG = Path("/nonexistent/session-analytics.json")


@contextmanager
def packaged_config(env: Optional[Mapping[str, str]] = None) -> Iterator[None]:
    from session_analytics import config as cfgmod

    cleared = {k: "" for k in os.environ if k.startswith("CCT_SA_")}
    cleared.update(env or {})
    with mock.patch.object(cfgmod, "_USER_CONFIG", NO_USER_CONFIG), \
         mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
         mock.patch.dict("os.environ", cleared):
        yield


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
