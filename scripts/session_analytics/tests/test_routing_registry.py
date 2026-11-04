# Tests for the read-only routing-registry summary (Studio Routing page).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from session_analytics.routing_registry import registry_summary

TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "shared/templates/routing/routing.toml.example"
)


class TestRoutingRegistrySummary(unittest.TestCase):
    def test_missing_registry_is_a_normal_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = registry_summary(Path(tmp) / "routing.toml")
        self.assertFalse(summary["configured"])
        self.assertFalse(summary["valid"])
        self.assertIsNone(summary["error"])
        self.assertEqual(summary["profiles"], [])

    def test_the_shipped_template_is_validated_and_summarised(self) -> None:
        # The verdict is the CONSTRAINED validator's, not tomllib's: the
        # registry is policy surface, and the supervisor refuses constructs
        # the full TOML library would accept.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routing.toml"
            path.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
            summary = registry_summary(path)
        self.assertTrue(summary["configured"])
        self.assertTrue(summary["valid"], summary["error"])
        ids = [p["id"] for p in summary["profiles"]]
        self.assertIn("anthropic-sonnet", ids)
        self.assertIn("tier1_only", summary["route_classes"])
        blob = repr(summary)
        self.assertNotIn("DEEPSEEK_API_KEY", blob)
        self.assertNotIn("https://api.deepseek.com", blob)

    def test_a_rejected_toml_feature_is_not_reported_as_valid(self) -> None:
        # Valid TOML (an inline table), refused by the constrained reader:
        # the page must not show profiles the supervisor will reject.
        text = TEMPLATE.read_text(encoding="utf-8").replace(
            'failback = "auto"',
            'failback = "auto"\nmeta = { a = 1 }',
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routing.toml"
            path.write_text(text, encoding="utf-8")
            summary = registry_summary(path)
        self.assertTrue(summary["configured"])
        self.assertFalse(summary["valid"])
        self.assertTrue(summary["error"])
        self.assertEqual(summary["profiles"], [])

    def test_malformed_toml_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "routing.toml"
            path.write_text("this is not toml\n", encoding="utf-8")
            summary = registry_summary(path)
        self.assertTrue(summary["configured"])
        self.assertFalse(summary["valid"])
        self.assertTrue(summary["error"])
        self.assertEqual(summary["profiles"], [])
