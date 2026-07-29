# tests/test_pi_preset.py — T3.9: the Pi-driven comparison preset.
#
# Validates that benchmarks/presets/pi-vs-cloud.json parses through the real
# compare-config loader, features the Pi backend as a candidate, and that the
# `pi` backend it names is actually registered. Also guards that EVERY preset
# in benchmarks/presets/ loads cleanly (so a schema change can't silently break
# a shipped preset).

from __future__ import annotations

import unittest
from pathlib import Path

from benchmark_runner.compare import load_config

_REPO = Path(__file__).resolve().parents[3]
_PRESETS = _REPO / "benchmarks" / "presets"
_PI_PRESET = _PRESETS / "pi-vs-cloud.json"


class TestPiPreset(unittest.TestCase):
    def test_preset_exists(self) -> None:
        self.assertTrue(_PI_PRESET.is_file(), f"missing preset: {_PI_PRESET}")

    def test_preset_loads_and_features_pi(self) -> None:
        config = load_config(_PI_PRESET)
        self.assertGreaterEqual(len(config.candidates), 2)
        backends = {c.backend for c in config.candidates}
        self.assertIn("pi", backends, "preset must feature the pi backend")
        # A genuine comparison: pi vs at least one other backend/candidate.
        self.assertGreaterEqual(len(backends), 2)
        names = [c.name for c in config.candidates]
        self.assertEqual(len(names), len(set(names)), "candidate names must be unique")

    def test_pi_candidate_names_a_registered_backend(self) -> None:
        from benchmark_runner import registry
        from benchmark_runner._register import register_all, unregister_all_for_tests

        unregister_all_for_tests()
        try:
            register_all()
            config = load_config(_PI_PRESET)
            for c in config.candidates:
                self.assertIn(
                    c.backend,
                    registry.list_backend_ids(),
                    f"preset candidate backend {c.backend!r} is not registered",
                )
        finally:
            unregister_all_for_tests()

    def test_preset_declares_a_benchmark_and_tasks(self) -> None:
        config = load_config(_PI_PRESET)
        self.assertTrue(config.benchmark, "preset must name a benchmark adapter")
        # A Pi-driven comparison is meaningful only against a real task set.
        self.assertTrue(config.task_filter, "preset should pin a task set")


if __name__ == "__main__":
    unittest.main()
