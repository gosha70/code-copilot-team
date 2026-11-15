"""The CCT home resolver (#411): one rule, the same in bash, Python and TypeScript."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from session_analytics import home as H


class TheHomeResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cct-home-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.tmp)}, clear=False)
        self.env.start()
        os.environ.pop(H.ENV_HOME, None)
        self.addCleanup(self.env.stop)

    def test_the_default_home_is_dot_cct(self) -> None:
        self.assertEqual(H.cct_home(), self.tmp / ".cct")
        self.assertEqual(H.cct_home_path("providers.toml"), self.tmp / ".cct" / "providers.toml")

    def test_a_legacy_only_entry_is_read_from_the_legacy_home(self) -> None:
        (self.tmp / ".code-copilot-team").mkdir()
        (self.tmp / ".code-copilot-team" / "providers.toml").write_text("x")
        self.assertEqual(H.cct_home_path("providers.toml"), self.tmp / ".code-copilot-team" / "providers.toml")
        # ...and an entry the legacy home lacks is still created under the home.
        self.assertEqual(H.cct_home_path("routing.toml"), self.tmp / ".cct" / "routing.toml")

    def test_a_nested_path_follows_its_top_level_entry(self) -> None:
        # A legacy pi/ and no pi/audit.log anywhere: the log goes into the
        # legacy pi/, never into a new ~/.cct/pi that would shadow it.
        (self.tmp / ".code-copilot-team" / "pi").mkdir(parents=True)
        self.assertEqual(H.cct_home_path("pi/audit.log"), self.tmp / ".code-copilot-team" / "pi" / "audit.log")
        self.assertFalse((self.tmp / ".cct" / "pi").exists())
        (self.tmp / ".cct" / "pi").mkdir(parents=True)
        self.assertEqual(H.cct_home_path("pi/audit.log"), self.tmp / ".cct" / "pi" / "audit.log")

    def test_the_home_wins_when_both_have_the_entry(self) -> None:
        for d in (".cct", ".code-copilot-team"):
            (self.tmp / d).mkdir()
            (self.tmp / d / "session-analytics.json").write_text("{}")
        self.assertEqual(H.cct_home_path("session-analytics.json"), self.tmp / ".cct" / "session-analytics.json")

    def test_cct_home_overrides_everything_with_no_fallback(self) -> None:
        (self.tmp / ".code-copilot-team").mkdir()
        (self.tmp / ".code-copilot-team" / "providers.toml").write_text("x")
        with mock.patch.dict(os.environ, {H.ENV_HOME: "/srv/cct"}):
            self.assertEqual(H.cct_home(), Path("/srv/cct"))
            self.assertEqual(H.cct_home_path("providers.toml"), Path("/srv/cct/providers.toml"))
            self.assertEqual(H.legacy_hits(), [])

    def test_legacy_hits_lists_what_is_only_in_the_legacy_home(self) -> None:
        self.assertEqual(H.legacy_hits(), [])
        (self.tmp / ".code-copilot-team" / "pi").mkdir(parents=True)
        (self.tmp / ".code-copilot-team" / "providers.toml").write_text("x")
        (self.tmp / ".cct").mkdir()
        (self.tmp / ".cct" / "providers.toml").write_text("y")
        self.assertEqual(H.legacy_hits(), ["pi"])


class ConfigUsesTheResolver(unittest.TestCase):
    """config.py's three home-relative defaults follow the one rule."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cct-home-cfg-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.tmp)}, clear=False)
        self.env.start()
        for k in (H.ENV_HOME, "CCT_HARNESS_STAMPS", "CCT_SA_KUZU_PATH"):
            os.environ.pop(k, None)
        self.addCleanup(self.env.stop)

    def test_defaults_point_at_the_home(self) -> None:
        from session_analytics.config import load_config
        cfg = load_config(dsn="sqlite:///:memory:")
        self.assertEqual(cfg.harness_stamps_path, (self.tmp / ".cct" / "harness-stamps.jsonl").as_posix())
        self.assertTrue(cfg.kuzu_path.startswith(str(self.tmp / ".cct")))

    def test_a_legacy_only_user_config_is_still_read(self) -> None:
        from session_analytics.config import load_config
        (self.tmp / ".code-copilot-team").mkdir()
        (self.tmp / ".code-copilot-team" / "session-analytics.json").write_text('{"redaction_mode": "none"}')
        cfg = load_config(dsn="sqlite:///:memory:")
        self.assertEqual(cfg.redaction_mode, "none")

    def test_a_legacy_only_ledger_is_still_read_by_default(self) -> None:
        from session_analytics.config import load_config
        (self.tmp / ".code-copilot-team").mkdir()
        (self.tmp / ".code-copilot-team" / "harness-stamps.jsonl").write_text("")
        cfg = load_config(dsn="sqlite:///:memory:")
        self.assertEqual(cfg.harness_stamps_path, (self.tmp / ".code-copilot-team" / "harness-stamps.jsonl").as_posix())


if __name__ == "__main__":
    unittest.main()
