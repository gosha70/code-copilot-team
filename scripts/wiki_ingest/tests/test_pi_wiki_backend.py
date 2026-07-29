# tests/test_pi_wiki_backend.py — T3.7: pi as a wiki-ingest backend.
#
# Explicit `--backend pi` is first-class and always resolvable (when pi-code is
# on PATH); auto-detect inserts pi (claude -> codex -> pi -> cursor) ONLY when
# the providers.pi capability is enabled (FR-025/FR-028).

from __future__ import annotations

import unittest
from unittest.mock import patch

import wiki_ingest.backends as be
from wiki_ingest.backends import auto_detect, resolve_backend
from wiki_ingest.backends.copilot_cli import CopilotCliBackend, cli_binary_for


class TestPiWikiBackend(unittest.TestCase):
    def test_pi_binary_map(self) -> None:
        self.assertEqual(cli_binary_for("pi"), "pi-code")

    def test_explicit_pi_resolves_when_on_path(self) -> None:
        with patch.object(be.shutil, "which", lambda b: "/usr/bin/" + b):
            backend = resolve_backend("pi")
        self.assertIsInstance(backend, CopilotCliBackend)
        self.assertEqual(backend._cli_name, "pi")  # noqa: SLF001

    def test_explicit_pi_works_even_when_capability_disabled(self) -> None:
        # Explicit override is not gated by the capability — only auto-detect is.
        with patch.object(be, "_pi_capability_enabled", lambda: False), patch.object(
            be.shutil, "which", lambda b: "/usr/bin/" + b
        ):
            backend = resolve_backend("pi")
        self.assertIsInstance(backend, CopilotCliBackend)
        self.assertEqual(backend._cli_name, "pi")  # noqa: SLF001

    def test_autodetect_order_includes_pi_when_capability_enabled(self) -> None:
        with patch.object(be, "_pi_capability_enabled", lambda: True):
            self.assertEqual(be._auto_detect_order(), ("claude", "codex", "pi", "cursor"))

    def test_autodetect_order_excludes_pi_when_capability_disabled(self) -> None:
        with patch.object(be, "_pi_capability_enabled", lambda: False):
            self.assertEqual(be._auto_detect_order(), ("claude", "codex", "cursor"))

    def test_autodetect_prefers_pi_over_cursor_when_enabled(self) -> None:
        # capability enabled; only pi + cursor on PATH -> pi wins by order.
        def which(binary: str):
            return "/x/" + binary if binary in ("pi-code", "cursor-agent") else None

        with patch.object(be, "_pi_capability_enabled", lambda: True), patch.object(
            be.shutil, "which", which
        ):
            backend = auto_detect()
        self.assertEqual(backend._cli_name, "pi")  # noqa: SLF001

    def test_autodetect_skips_pi_when_disabled_even_if_on_path(self) -> None:
        # capability disabled; only pi + cursor on PATH -> pi NOT considered,
        # cursor is selected.
        def which(binary: str):
            return "/x/" + binary if binary in ("pi-code", "cursor-agent") else None

        with patch.object(be, "_pi_capability_enabled", lambda: False), patch.object(
            be.shutil, "which", which
        ):
            backend = auto_detect()
        self.assertEqual(backend._cli_name, "cursor")  # noqa: SLF001

    def test_capability_reader_reflects_the_real_pi_yaml(self) -> None:
        # After T3.8 flipped providers.pi to enabled, the real reader returns True.
        self.assertTrue(be._pi_capability_enabled())

    def test_unknown_backend_lists_pi_as_valid(self) -> None:
        from wiki_ingest.errors import BackendNotFoundError

        with self.assertRaises(BackendNotFoundError) as cm:
            resolve_backend("bogus-xyz")
        self.assertIn("pi", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
