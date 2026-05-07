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


class TestE2EMultiPageIngest(unittest.TestCase):
    """Phase 1: ``./scripts/wiki ingest <source>`` (without --legacy-single-source)
    runs the multi-page DefaultMultiIngestor and produces a patch-set dir."""

    def test_multi_page_ingest_writes_plan_and_preview(self) -> None:
        import json

        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                "ingest",
                str(_SAMPLE_INCIDENT),
                "--backend", "test",
                "--output-dir", tmp,
            )
            self.assertEqual(
                result.returncode, 0,
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
            patch_dir = Path(result.stdout.strip())
            self.assertTrue(patch_dir.exists(), f"patch-set dir missing at {patch_dir}")

            plan = json.loads((patch_dir / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["version"], 1)
            self.assertEqual(plan["backend"], "test")
            # Test backend produces 3 edits: incident page + log + index.
            self.assertEqual(len(plan["edits"]), 3)
            actions = [e["action"] for e in plan["edits"]]
            self.assertIn("create", actions)
            self.assertIn("append-log", actions)
            self.assertIn("append-index", actions)

            # Each edit has a corresponding preview file.
            for edit in plan["edits"]:
                preview = patch_dir / "preview" / edit["path"]
                self.assertTrue(preview.exists(), f"preview missing for {edit['path']}")

    def test_multi_page_ingest_validates_per_edit_paths(self) -> None:
        """Patch-set with a duplicate-create or '..' in path raises contract violation."""
        from wiki_ingest.proposal import (
            PageEdit,
            WikiPatchSet,
            validate_patch_set,
        )

        # Duplicate create — same path twice
        dup = WikiPatchSet(
            edits=[
                PageEdit(path="incidents/x.md", action="create",
                         new_content="x", rationale="r"),
                PageEdit(path="incidents/x.md", action="create",
                         new_content="x", rationale="r"),
            ],
            source_path="src.md", backend="test", rationale="r",
        )
        errors = validate_patch_set(dup)
        self.assertTrue(any("duplicate create" in e for e in errors))

        # Path traversal
        bad = WikiPatchSet(
            edits=[
                PageEdit(path="../escape.md", action="create",
                         new_content="x", rationale="r"),
            ],
            source_path="src.md", backend="test", rationale="r",
        )
        errors = validate_patch_set(bad)
        self.assertTrue(any("relative" in e for e in errors))

        # append-log targeting wrong file
        bad2 = WikiPatchSet(
            edits=[
                PageEdit(path="something.md", action="append-log",
                         new_content="x", rationale="r"),
            ],
            source_path="src.md", backend="test", rationale="r",
        )
        errors = validate_patch_set(bad2)
        self.assertTrue(any("append-log" in e for e in errors))

    def test_legacy_single_source_still_works(self) -> None:
        """Backwards-compat: --legacy-single-source produces v1 IngestProposal output."""
        with tempfile.TemporaryDirectory() as tmp:
            result = _run_module(
                "ingest",
                "--legacy-single-source",
                str(_SAMPLE_INCIDENT),
                "--backend", "test",
                "--output-dir", tmp,
            )
            self.assertEqual(result.returncode, 0)
            output_path = Path(result.stdout.strip())
            self.assertTrue(output_path.exists())
            self.assertTrue(output_path.is_file())
            # v1 produces a single .md file; multi-page produces a directory.
            self.assertEqual(output_path.suffix, ".md")


class TestE2ERendererIncludesWikiState(unittest.TestCase):
    """Regression for [P1]: ``_render_plain_text_prompt`` MUST emit
    wiki-state content. Pre-fix bug: the renderer dropped wiki_state on
    the floor; only the in-process test backend (which reads the dict
    directly) saw it. Real Claude/Codex/Cursor backends got nothing."""

    def test_render_includes_index_log_and_candidate_pages(self) -> None:
        from wiki_ingest.backends.copilot_cli import _render_plain_text_prompt

        prompt = {
            "version": 1,
            "system_instructions": "be a curator",
            "task": "ingest-multi",
            "schema_excerpts": {
                "ingest_rules": "RULES",
                "page_types": "TYPES",
                "citation_rules": "CITES",
            },
            "source": {
                "kind": "file",
                "path": "src.md",
                "content": "# Source",
            },
            "wiki_state": {
                "index_md": "# Wiki Index\n- [Foo](concepts/foo.md)\n",
                "log_md": "- 2026-01-01 — promote foo (concept).\n",
                "candidate_pages": {
                    "concepts/foo.md": "---\npage_type: concept\nslug: foo\n---\n# Foo\n",
                    "incidents/bar.md": "---\npage_type: incident\nslug: bar\n---\n# Bar\n",
                },
            },
            "response_schema": "{}",
        }
        rendered = _render_plain_text_prompt(prompt)

        self.assertIn("=== EXISTING WIKI STATE ===", rendered)
        self.assertIn("knowledge/wiki/index.md", rendered)
        self.assertIn("# Wiki Index", rendered)
        self.assertIn("knowledge/wiki/log.md", rendered)
        self.assertIn("2026-01-01 — promote foo", rendered)
        self.assertIn("knowledge/wiki/concepts/foo.md", rendered)
        self.assertIn("# Foo", rendered)
        self.assertIn("knowledge/wiki/incidents/bar.md", rendered)
        self.assertIn("# Bar", rendered)

    def test_render_omits_wiki_state_block_when_empty(self) -> None:
        """Stage-1 (single-source) prompts have no wiki_state; the block
        must be omitted entirely so v1 prompts stay byte-identical."""
        from wiki_ingest.backends.copilot_cli import _render_plain_text_prompt

        prompt = {
            "version": 1,
            "system_instructions": "be a curator",
            "task": "ingest",
            "schema_excerpts": {
                "ingest_rules": "RULES",
                "page_types": "TYPES",
                "citation_rules": "CITES",
            },
            "source": {"kind": "file", "path": "src.md", "content": "# X"},
            "response_schema": "{}",
        }
        rendered = _render_plain_text_prompt(prompt)
        self.assertNotIn("=== EXISTING WIKI STATE ===", rendered)


class TestE2EPerEditSemanticValidation(unittest.TestCase):
    """Regression for [P2]: every PageEdit's create/update content goes
    through the same semantic validation as v1 IngestProposal frontmatter.
    Pre-fix bug: multi-page ingest only ran shape + set-level checks,
    so frontmatter mismatches, missing sources, root-only page types
    used as create targets, and updates to non-existent pages all
    slipped through to the proposal directory."""

    def test_validates_frontmatter_slug_matches_filename(self) -> None:
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        bad = PageEdit(
            path="concepts/foo.md",
            action="create",
            new_content=(
                "---\n"
                "page_type: concept\n"
                "slug: not-foo\n"          # mismatch
                "title: Foo\n"
                "sources:\n"
                "  - path: src.md\n"
                "    sha: abc\n"
                "---\n"
                "# Foo\n"
            ),
            rationale="r",
        )
        errors = validate_page_edit_semantics(bad, repo_root)
        self.assertTrue(any("slug" in e for e in errors))

    def test_validates_sources_non_empty(self) -> None:
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        bad = PageEdit(
            path="concepts/foo.md",
            action="create",
            new_content=(
                "---\n"
                "page_type: concept\n"
                "slug: foo\n"
                "title: Foo\n"
                "---\n"
                "# Foo\n"
            ),
            rationale="r",
        )
        errors = validate_page_edit_semantics(bad, repo_root)
        self.assertTrue(any("sources" in e for e in errors))

    def test_rejects_root_only_page_type_as_create_target(self) -> None:
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        bad = PageEdit(
            path="overview.md",
            action="create",
            new_content=(
                "---\n"
                "page_type: overview\n"
                "slug: overview\n"
                "title: Overview\n"
                "sources:\n"
                "  - path: src.md\n"
                "    sha: abc\n"
                "---\n"
                "# Overview\n"
            ),
            rationale="r",
        )
        errors = validate_page_edit_semantics(bad, repo_root)
        self.assertTrue(any("promotable" in e or "page_type" in e for e in errors))

    def test_rejects_update_to_nonexistent_path(self) -> None:
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        bad = PageEdit(
            path="concepts/does-not-exist.md",
            action="update",
            new_content=(
                "---\n"
                "page_type: concept\n"
                "slug: does-not-exist\n"
                "title: x\n"
                "sources:\n"
                "  - path: src.md\n"
                "    sha: abc\n"
                "---\n"
                "# x\n"
            ),
            rationale="r",
        )
        errors = validate_page_edit_semantics(bad, repo_root)
        self.assertTrue(any("does not exist" in e for e in errors))

    def test_rejects_directory_mismatch(self) -> None:
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        bad = PageEdit(
            path="incidents/foo.md",       # path under incidents/
            action="create",
            new_content=(
                "---\n"
                "page_type: concept\n"     # but page_type is concept
                "slug: foo\n"
                "title: Foo\n"
                "sources:\n"
                "  - path: src.md\n"
                "    sha: abc\n"
                "---\n"
                "# Foo\n"
            ),
            rationale="r",
        )
        errors = validate_page_edit_semantics(bad, repo_root)
        self.assertTrue(any("concepts" in e or "incidents" in e for e in errors))

    def test_well_formed_create_passes(self) -> None:
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        good = PageEdit(
            path="incidents/foo.md",
            action="create",
            new_content=(
                "---\n"
                "page_type: incident\n"
                "slug: foo\n"
                "title: Foo\n"
                "sources:\n"
                "  - path: src.md\n"
                "    sha: abc\n"
                "---\n"
                "# Foo\n"
            ),
            rationale="r",
        )
        self.assertEqual(validate_page_edit_semantics(good, repo_root), [])

    def test_append_log_skips_frontmatter_validation(self) -> None:
        """append-log content is a one-line bullet, not a full page —
        frontmatter validation must not fire on it."""
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        good = PageEdit(
            path="log.md",
            action="append-log",
            new_content="- 2026-05-06 — promote foo (concept): rationale.",
            rationale="r",
        )
        self.assertEqual(validate_page_edit_semantics(good, repo_root), [])

    def test_ingestor_multi_raises_on_bad_frontmatter(self) -> None:
        """End-to-end: a backend that returns a patch with bad frontmatter
        causes DefaultMultiIngestor.ingest_multi to raise ContractViolationError."""
        from wiki_ingest.errors import ContractViolationError
        from wiki_ingest.ingestor_multi import DefaultMultiIngestor
        from wiki_ingest.proposal import IngestRequest

        class _BadBackend:
            def call(self, prompt: dict) -> dict:
                return {
                    "version": 1,
                    "rationale": "test",
                    "edits": [
                        {
                            "path": "concepts/x.md",
                            "action": "create",
                            "new_content": (
                                "---\n"
                                "page_type: concept\n"
                                "slug: y\n"        # mismatch with x
                                "title: x\n"
                                "sources: []\n"   # empty
                                "---\n"
                                "# x\n"
                            ),
                            "rationale": "r",
                        }
                    ],
                }

        repo_root = _SCRIPTS_DIR.parent
        ingestor = DefaultMultiIngestor(backend=_BadBackend(), repo_root=repo_root)
        req = IngestRequest(
            source_path=_SAMPLE_INCIDENT,
            source_kind="file",
            backend_name="bad-test-backend",
        )
        with self.assertRaises(ContractViolationError) as ctx:
            ingestor.ingest_multi(req)
        msg = str(ctx.exception)
        self.assertIn("per-edit semantic validation", msg)


class TestE2EWikiState(unittest.TestCase):
    """Phase 1: WikiState loads the existing wiki for the multi-page prompt."""

    def test_loads_index_and_log(self) -> None:
        import sys as _sys
        _sys.path.insert(0, str(_SCRIPTS_DIR))
        try:
            from wiki_ingest.wiki_state import load_wiki_state
        finally:
            _sys.path.pop(0)
        # Repo root is the ancestor of scripts/.
        repo_root = _SCRIPTS_DIR.parent
        state = load_wiki_state(
            repo_root=repo_root,
            source_path=_SAMPLE_INCIDENT,
            source_content=_SAMPLE_INCIDENT.read_text(encoding="utf-8"),
        )
        # index.md and log.md should be loaded (they exist in the repo).
        self.assertTrue(state.index_md, "index.md should be loaded")
        self.assertTrue(state.log_md, "log.md should be loaded")
        # Candidate set should be a dict (may be empty for unrelated source).
        self.assertIsInstance(state.candidate_pages, dict)


if __name__ == "__main__":
    unittest.main()
