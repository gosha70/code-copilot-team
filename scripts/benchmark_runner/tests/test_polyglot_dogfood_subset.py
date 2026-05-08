# tests/test_polyglot_dogfood_subset.py — dogfood subset file integrity.
#
# Phase 2d: validates the committed dogfood-subset.txt parses cleanly,
# is well-shaped, and covers each upstream language at least once.
# Phase 4 wires the subset into ``./scripts/benchmark dogfood``; this
# test pins the file's contract until then.

from __future__ import annotations

import os
import unittest
from pathlib import Path

from benchmarks.adapters.aider_polyglot import fetch
from benchmarks.adapters.aider_polyglot.adapter import (
    AiderPolyglotAdapter,
    LANGUAGES,
    load_dogfood_subset,
)


class TestDogfoodSubsetShape(unittest.TestCase):
    def setUp(self) -> None:
        self.subset = load_dogfood_subset()

    def test_subset_is_non_empty(self) -> None:
        self.assertGreater(len(self.subset), 0)

    def test_size_in_documented_range(self) -> None:
        # spec.md / tasks.md call for 10–15 tasks.
        self.assertGreaterEqual(len(self.subset), 10)
        self.assertLessEqual(len(self.subset), 15)

    def test_each_entry_is_lang_slash_exercise(self) -> None:
        for task_id in self.subset:
            self.assertIn("/", task_id, f"malformed task id: {task_id!r}")
            lang, _, exercise = task_id.partition("/")
            self.assertIn(lang, LANGUAGES, f"unknown language in {task_id!r}")
            self.assertTrue(exercise, f"empty exercise in {task_id!r}")

    def test_at_least_one_task_per_language(self) -> None:
        # Breadth requirement: dogfood compares per-language pass rates
        # against Aider's leaderboard, so each language must appear.
        languages_in_subset = {t.split("/", 1)[0] for t in self.subset}
        for lang in LANGUAGES:
            self.assertIn(
                lang,
                languages_in_subset,
                f"dogfood subset missing coverage for {lang!r}",
            )

    def test_no_duplicates(self) -> None:
        self.assertEqual(
            len(self.subset),
            len(set(self.subset)),
            "duplicate task IDs in dogfood-subset.txt",
        )


class TestDogfoodSubsetResolvesAgainstRealCache(unittest.TestCase):
    """Live integration: every listed task must resolve via the adapter
    against the real upstream cache. Skipped when the cache is absent."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._cache = fetch.cache_dir()
        cls._has_cache = fetch.is_cached()

    def test_each_dogfood_task_resolves(self) -> None:
        if not self._has_cache:
            self.skipTest(
                f"real polyglot cache missing at {self._cache}; "
                f"run python -m benchmarks.adapters.aider_polyglot.fetch first"
            )
        adapter = AiderPolyglotAdapter()
        all_task_ids = {t.task_id for t in adapter.list_tasks()}
        missing = [t for t in load_dogfood_subset() if t not in all_task_ids]
        self.assertEqual(
            missing,
            [],
            f"{len(missing)} dogfood task(s) not present in upstream cache: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
