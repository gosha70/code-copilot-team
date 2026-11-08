# Tests for the Aider markdown-history adapter (provisional format).

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.adapters.aider import AiderAdapter

from session_analytics.tests.support import FIXTURES, RegistryResetTestCase

_AIDER_ROOT = FIXTURES / "aider"


class TestAiderAdapter(RegistryResetTestCase):
    def test_packaged_default_declares_no_root(self) -> None:
        # #402: the packaged default used to be HOME, so every load and
        # listing walked the whole home directory. Aider is scanned only
        # under a root the user declares; with none, discovery is empty
        # and touches no directory.
        from types import SimpleNamespace
        from unittest import mock

        from session_analytics import config as cfgmod
        from session_analytics.adapters import aider as aider_mod

        defaults = cfgmod._read_defaults()["sources"]
        # The KEY stays, as null: load_config's env loop only consults
        # copilots present in the sources map, so deleting the entry
        # would silently disable CCT_SA_SOURCE_AIDER.
        self.assertIn("aider", defaults)
        self.assertIsNone(defaults["aider"])
        # Discovery resolves a missing root through load_config(), which
        # merges ~/.cct/session-analytics.json and CCT_SA_SOURCE_AIDER from
        # the host — the very setting aider users are told to add. Pin the
        # packaged default so this measures the package, not this machine.
        packaged = SimpleNamespace(source_root=lambda copilot: None)
        with mock.patch.object(aider_mod, "load_config", return_value=packaged):
            self.assertEqual(AiderAdapter(default_root=None).discover(None), [])

    def test_discover_skips_hidden_dependency_and_library_dirs(self) -> None:
        # A declared root may be a whole tree of projects; walking every
        # dot-cache, node_modules and ~/Library took 88 s per load when the
        # root was HOME. A history file inside those is not a project and
        # is not visited; one in a plain subdir is.
        import shutil
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-aider-walk-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src = _AIDER_ROOT / "proj" / ".aider.chat.history.md"
        for rel in ("work/proj", ".cache/proj", "app/node_modules/pkg", "Library/x"):
            d = tmp / rel
            d.mkdir(parents=True)
            shutil.copy(src, d / ".aider.chat.history.md")
        refs = AiderAdapter().discover(tmp)
        self.assertEqual(
            [str(r.source_files[0].parent.relative_to(tmp)) for r in refs], ["work/proj"]
        )

    def _load(self):
        adapter = AiderAdapter()
        refs = adapter.discover(_AIDER_ROOT)
        self.assertEqual(len(refs), 1)
        return adapter.load(refs[0])

    def test_discover(self) -> None:
        refs = AiderAdapter().discover(_AIDER_ROOT)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].copilot, C.COPILOT_AIDER)

    def test_turns_alternate_user_assistant(self) -> None:
        session = self._load()
        roles = [t.role for t in session.turns]
        self.assertEqual(
            roles,
            ["user", "assistant", "user", "assistant", "user", "assistant"],
        )

    def test_user_text_extracted(self) -> None:
        session = self._load()
        self.assertIn("bowling scorer", session.turns[0].text)
        self.assertIn("strike bug", session.turns[4].text)

    def test_session_start_timestamp(self) -> None:
        session = self._load()
        self.assertEqual(session.started_at, "2026-05-01 09:00:00")

    def test_marked_provisional(self) -> None:
        session = self._load()
        self.assertTrue(session.metadata.get("provisional_format"))


if __name__ == "__main__":
    unittest.main()
