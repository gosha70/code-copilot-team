# tests/test_e2e.py — end-to-end CLI tests for the wiki-ingest entrypoint.
#
# These tests invoke the CLI via subprocess. Two invocation paths are
# exercised:
#
#   1. ``python3 -m wiki_ingest …`` with PYTHONPATH set — always works
#      across platforms; the workhorse for negative-path / dry-run
#      assertions.
#   2. ``./scripts/wiki-ingest …`` (the Bash entrypoint) — pins the
#      acceptance criterion in specs/wiki-ingest-pipeline/spec.md.
#      Skipped when the entrypoint is not executable (e.g., fresh
#      checkout on a filesystem that drops the executable bit).
#
# All tests use a tempdir for ``--output-dir`` so the real
# ``doc_internal/proposals/`` is never touched.

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_SAMPLE_INCIDENT = _FIXTURES_DIR / "sample-incident.md"
_BASH_ENTRYPOINT = _SCRIPTS_DIR / "wiki-ingest"


def _module_env() -> dict[str, str]:
    """Return an env dict with PYTHONPATH set so ``-m wiki_ingest`` resolves."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_SCRIPTS_DIR}{os.pathsep}{existing}" if existing else str(_SCRIPTS_DIR)
    )
    return env


def _run_module(*args: str) -> subprocess.CompletedProcess:
    """Invoke the package via ``python3 -m wiki_ingest``."""
    cmd = [sys.executable, "-m", "wiki_ingest", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=_module_env(),
        timeout=30,
    )


def _run_bash_entrypoint(*args: str) -> subprocess.CompletedProcess:
    """Invoke the Bash wrapper directly. Caller is responsible for skipping
    when the entrypoint is not executable."""
    cmd = [str(_BASH_ENTRYPOINT), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestE2EAcceptHappyPath(unittest.TestCase):
    """End-to-end accept-disposition flow with the deterministic test backend."""

    def test_writes_proposal_file_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                str(_SAMPLE_INCIDENT),
                "--backend", "test",
                "--output-dir", tmp,
            )
            self.assertEqual(
                result.returncode, 0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            output_path = Path(result.stdout.strip())
            self.assertTrue(
                output_path.exists(),
                f"proposal file not at {output_path}; "
                f"tmp dir contents: {list(Path(tmp).iterdir())}"
            )
            self.assertEqual(output_path.parent, Path(tmp).resolve())

    def test_proposal_frontmatter_has_expected_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                str(_SAMPLE_INCIDENT),
                "--backend", "test",
                "--output-dir", tmp,
            )
            self.assertEqual(result.returncode, 0)
            content = Path(result.stdout.strip()).read_text(encoding="utf-8")
            self.assertIn("proposal_kind: accept", content)
            self.assertIn("gate_disposition: accept", content)
            self.assertIn("ingestor_version: 1", content)
            self.assertIn("backend: 'test'", content)
            # target_slug and target_page_type populated for accept
            self.assertIn("target_slug:", content)
            self.assertIn("target_page_type: 'incident'", content)

    def test_proposal_body_contains_full_draft_on_accept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                str(_SAMPLE_INCIDENT),
                "--backend", "test",
                "--output-dir", tmp,
            )
            self.assertEqual(result.returncode, 0)
            content = Path(result.stdout.strip()).read_text(encoding="utf-8")
            # Body must contain the wiki-page-shaped frontmatter from the draft
            self.assertIn("page_type: incident", content)
            # And the required incident-template H2s.
            for section in (
                "## What happened",
                "## Why it happened",
                "## What we changed",
                "## How to recognize a recurrence",
            ):
                self.assertIn(section, content)

    def test_filename_includes_today_and_slug(self) -> None:
        import datetime
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                str(_SAMPLE_INCIDENT),
                "--backend", "test",
                "--output-dir", tmp,
            )
            self.assertEqual(result.returncode, 0)
            output_path = Path(result.stdout.strip())
            today = datetime.date.today().isoformat()
            self.assertTrue(
                output_path.name.startswith(today + "-"),
                f"expected filename to start with {today}-, got {output_path.name}"
            )
            self.assertTrue(output_path.name.endswith(".md"))


class TestE2EDryRun(unittest.TestCase):
    """Dry-run drops the draft body but keeps the gate decision in frontmatter."""

    def test_dry_run_omits_draft_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                str(_SAMPLE_INCIDENT),
                "--backend", "test",
                "--dry-run",
                "--output-dir", tmp,
            )
            self.assertEqual(
                result.returncode, 0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            content = Path(result.stdout.strip()).read_text(encoding="utf-8")
            # Gate decision still present.
            self.assertIn("gate_disposition: accept", content)
            self.assertIn("gate_reason:", content)
            # Draft body is gone — no wiki-page frontmatter, no required H2s.
            self.assertNotIn("page_type: incident", content)
            self.assertNotIn("## What happened", content)
            self.assertNotIn("## Why it happened", content)


class TestE2ENegativePaths(unittest.TestCase):
    """Exit-code mapping for documented error conditions."""

    def test_missing_source_exits_5(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                "/nonexistent/path/that/does/not/exist.md",
                "--backend", "test",
                "--output-dir", tmp,
            )
            self.assertEqual(
                result.returncode, 5,
                f"expected exit 5; stderr={result.stderr!r}"
            )
            self.assertIn("source file not found", result.stderr)

    def test_unknown_backend_name_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                str(_SAMPLE_INCIDENT),
                "--backend", "totally-not-a-real-backend",
                "--output-dir", tmp,
            )
            self.assertEqual(
                result.returncode, 2,
                f"expected exit 2; stderr={result.stderr!r}"
            )

    def test_help_documents_exit_codes(self) -> None:
        result = _run_module("--help")
        self.assertEqual(result.returncode, 0)
        # argparse line-wraps the epilog at terminal width, so a phrase
        # like "3 backend invocation failed" can land split across a
        # newline. Flatten whitespace before asserting so the test
        # passes regardless of wrap column.
        import re
        flat = re.sub(r"\s+", " ", result.stdout)
        for token in ("0 success", "2 backend not found",
                      "3 backend invocation", "4 contract violation",
                      "5 source missing", "6 output write"):
            self.assertIn(token, flat)


class TestE2EBashEntrypoint(unittest.TestCase):
    """Smoke-test the Bash entrypoint to pin the spec's acceptance criterion.

    Skipped when the entrypoint is not executable (fresh checkouts on
    permission-restricted filesystems can drop the +x bit). The
    module-form tests above cover the Python-side behavior fully; this
    suite exists only to verify that ``./scripts/wiki-ingest`` works
    as advertised on filesystems that preserve executability.
    """

    def setUp(self) -> None:
        if not _BASH_ENTRYPOINT.exists():
            self.skipTest(f"{_BASH_ENTRYPOINT} not present")
        if not os.access(_BASH_ENTRYPOINT, os.X_OK):
            self.skipTest(
                f"{_BASH_ENTRYPOINT} not executable — chmod +x required"
            )

    def test_bash_entrypoint_runs_test_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_bash_entrypoint(
                str(_SAMPLE_INCIDENT),
                "--backend", "test",
                "--output-dir", tmp,
            )
            self.assertEqual(
                result.returncode, 0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            output_path = Path(result.stdout.strip())
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
