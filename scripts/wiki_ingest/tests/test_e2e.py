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
import shutil
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


class TestE2EFenceNeutralization(unittest.TestCase):
    """Regression for the prompt-echo fence-capture issue: a real CLI
    that echoes the prompt to stdout before its response would otherwise
    let extract_json_object return a ```json block from source/wiki
    reference content instead of the model's actual response.
    Reference fences are neutralized to ```ref-json / ```ref-block in
    the rendered prompt so the extractor only sees the model's fence."""

    def test_source_json_fence_is_neutralized(self) -> None:
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
            "source": {
                "kind": "file",
                "path": "src.md",
                "content": (
                    "# Source\n"
                    "\n"
                    "An example response shape:\n"
                    "\n"
                    "```json\n"
                    '{"disposition": "accept", "slug": "decoy"}\n'
                    "```\n"
                    "\n"
                    "End.\n"
                ),
            },
            "response_schema": "{}",
        }
        rendered = _render_plain_text_prompt(prompt)

        # The opening ```json from the source content MUST NOT appear
        # verbatim — that's exactly what the extractor first-fence-wins.
        self.assertNotIn("\n```json\n", rendered)
        # Disarmed variant IS present (proves the source content was rendered).
        self.assertIn("```ref-json", rendered)
        # Inner content is preserved (verbatim for the model to read).
        self.assertIn('"disposition": "accept"', rendered)
        self.assertIn('"slug": "decoy"', rendered)

    def test_candidate_page_json_fence_is_neutralized(self) -> None:
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
                "index_md": "# Wiki Index\n",
                "log_md": "- 2026-01-01 — promote x.\n",
                "candidate_pages": {
                    "workflows/run-wiki-ingest.md": (
                        "# Run Wiki Ingest\n\n"
                        "Example backend response:\n\n"
                        "```json\n"
                        '{"version": 1, "edits": [], "rationale": "decoy"}\n'
                        "```\n"
                    ),
                },
            },
            "response_schema": "{}",
        }
        rendered = _render_plain_text_prompt(prompt)
        self.assertNotIn("\n```json\n", rendered)
        self.assertIn("```ref-json", rendered)
        self.assertIn('"rationale": "decoy"', rendered)

    def test_neutralize_only_rewrites_opening_fences(self) -> None:
        """Closing fences must stay ``` so rendered code blocks remain
        well-formed for the model to parse. Only OPENING fences are
        rewritten."""
        from wiki_ingest.backends.copilot_cli import _neutralize_extractor_fences

        text = "before\n```json\n{}\n```\nafter\n"
        out = _neutralize_extractor_fences(text)
        self.assertEqual(
            out,
            "before\n```ref-json\n{}\n```\nafter\n",
        )

    def test_neutralize_handles_bare_fence(self) -> None:
        from wiki_ingest.backends.copilot_cli import _neutralize_extractor_fences

        text = "before\n```\n{}\n```\nafter\n"
        out = _neutralize_extractor_fences(text)
        self.assertEqual(
            out,
            "before\n```ref-block\n{}\n```\nafter\n",
        )

    def test_extractor_skips_neutralized_fence_in_prompt_echo(self) -> None:
        """End-to-end: simulate a CLI that echoes the prompt before its
        response. The extractor must return the model's response, not
        the source's example fence."""
        from wiki_ingest.backends.copilot_cli import (
            _render_plain_text_prompt,
        )
        from wiki_ingest.backends.json_extract import extract_json_object

        prompt = {
            "version": 1,
            "system_instructions": "be a curator",
            "task": "ingest",
            "schema_excerpts": {
                "ingest_rules": "",
                "page_types": "",
                "citation_rules": "",
            },
            "source": {
                "kind": "file",
                "path": "src.md",
                "content": (
                    "# Source\n\n"
                    "Reference example:\n\n"
                    "```json\n"
                    '{"disposition": "DECOY", "slug": "wrong"}\n'
                    "```\n"
                ),
            },
            "response_schema": "{}",
        }
        echoed = _render_plain_text_prompt(prompt)
        # Simulate CLI echoing the prompt + appending its real response.
        real_response = (
            '\n```json\n{"version": 1, "disposition": "accept", '
            '"reason": "REAL", "page_type": "incident", "slug": "real", '
            '"title": "Real", "draft_markdown": null, "sources": [{}]}\n'
            '```\n'
        )
        stdout = echoed + real_response

        extracted = extract_json_object(stdout)
        # The extractor must return the REAL response, not the decoy.
        self.assertEqual(extracted.get("reason"), "REAL")
        self.assertEqual(extracted.get("slug"), "real")
        self.assertNotEqual(extracted.get("disposition"), "DECOY")


class TestE2ECreateTargetExistsRejection(unittest.TestCase):
    """Regression: validate_page_edit_semantics rejects create against
    an existing wiki path (the curator would clobber otherwise)."""

    def test_rejects_create_to_existing_wiki_page(self) -> None:
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        # concepts/spec-driven-development.md is a real, committed wiki
        # page. A create against it must fail.
        bad = PageEdit(
            path="concepts/spec-driven-development.md",
            action="create",
            new_content=(
                "---\n"
                "page_type: concept\n"
                "slug: spec-driven-development\n"
                "title: Spec-Driven Development (clobber)\n"
                "sources:\n"
                "  - path: src.md\n"
                "    sha: abc\n"
                "---\n"
                "# Clobber\n"
            ),
            rationale="r",
        )
        errors = validate_page_edit_semantics(bad, repo_root)
        self.assertTrue(
            any("create target already exists" in e for e in errors),
            f"errors: {errors}",
        )

    def test_create_to_new_path_passes(self) -> None:
        """The happy path — create a brand-new file — still passes."""
        from wiki_ingest.proposal import (
            PageEdit,
            validate_page_edit_semantics,
        )
        repo_root = _SCRIPTS_DIR.parent
        good = PageEdit(
            path="concepts/this-page-does-not-yet-exist.md",
            action="create",
            new_content=(
                "---\n"
                "page_type: concept\n"
                "slug: this-page-does-not-yet-exist\n"
                "title: New\n"
                "sources:\n"
                "  - path: src.md\n"
                "    sha: abc\n"
                "---\n"
                "# New\n"
            ),
            rationale="r",
        )
        self.assertEqual(validate_page_edit_semantics(good, repo_root), [])


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


class TestE2EPromote(unittest.TestCase):
    """Phase 2: ``./scripts/wiki promote <dir>`` applies a patch-set atomically.

    Tests use a tmp repo layout (``<tmp>/knowledge/wiki/...``) so the
    real repo's wiki is never touched, even if the promoter has a bug.
    """

    def _build_tmp_repo(self, tmp: Path) -> Path:
        """Create a minimal repo layout with a 1-page wiki under <tmp>."""
        wiki = tmp / "knowledge" / "wiki"
        wiki.mkdir(parents=True)
        # Minimal wiki: index.md + log.md (no other pages, but the
        # linter expects them).
        (wiki / "index.md").write_text(
            "---\n"
            "page_type: index\n"
            "slug: index\n"
            "title: Test Wiki\n"
            "status: stable\n"
            "last_reviewed: 2026-05-06\n"
            "---\n"
            "\n# Test Wiki\n\n## Incidents\n\n",
            encoding="utf-8",
        )
        (wiki / "log.md").write_text(
            "---\n"
            "page_type: log\n"
            "slug: log\n"
            "title: Wiki Log\n"
            "status: stable\n"
            "last_reviewed: 2026-05-06\n"
            "---\n"
            "\n# Log\n\n",
            encoding="utf-8",
        )
        # Mirror the schema/scripts dirs from the real repo so the
        # linter has its rules + script in the staged-tree validation.
        real_root = _SCRIPTS_DIR.parent
        for sub in ("schema", "scripts"):
            shutil.copytree(
                real_root / "knowledge" / "wiki" / sub,
                wiki / sub,
            )
        return wiki

    def _build_proposals_dir(
        self,
        tmp: Path,
        slug: str = "promote-fixture",
        page_type: str = "incident",
    ) -> Path:
        """Create a doc_internal/proposals/<date>-<slug>/ dir with a
        deterministic 3-edit patch-set (create + append-log + append-index)."""
        prop = tmp / "doc_internal" / "proposals" / f"2026-05-06-{slug}"
        (prop / "preview" / "incidents").mkdir(parents=True)
        (prop / "preview").mkdir(exist_ok=True)
        # create
        (prop / "preview" / "incidents" / f"{slug}.md").write_text(
            "---\n"
            f"page_type: {page_type}\n"
            f"slug: {slug}\n"
            "title: Promote Fixture\n"
            "status: draft\n"
            "last_reviewed: 2026-05-06\n"
            "sources:\n"
            "  - path: src.md\n"
            "    sha: abc1234\n"
            "---\n"
            "\n# Promote Fixture\n\nBody.\n",
            encoding="utf-8",
        )
        # append-log
        (prop / "preview" / "log.md").write_text(
            f"- 2026-05-06 — promote {slug} (incident): test fixture.",
            encoding="utf-8",
        )
        # append-index
        (prop / "preview" / "index.md").write_text(
            f"- [Promote Fixture](incidents/{slug}.md) — test fixture.",
            encoding="utf-8",
        )
        plan = {
            "version": 1,
            "source_path": "src.md",
            "backend": "test",
            "rationale": "test fixture",
            "edits": [
                {
                    "path": f"incidents/{slug}.md",
                    "action": "create",
                    "rationale": "create incident",
                    "preview": f"preview/incidents/{slug}.md",
                },
                {
                    "path": "log.md",
                    "action": "append-log",
                    "rationale": "append log",
                    "preview": "preview/log.md",
                },
                {
                    "path": "index.md",
                    "action": "append-index",
                    "rationale": "link from index",
                    "preview": "preview/index.md",
                },
            ],
        }
        import json as _json
        (prop / "plan.json").write_text(
            _json.dumps(plan, indent=2), encoding="utf-8"
        )
        return prop

    def test_promote_happy_path_applies_all_edits(self) -> None:
        from wiki_ingest.promoter import promote
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            wiki = self._build_tmp_repo(tmp_root)
            prop = self._build_proposals_dir(tmp_root)

            result = promote(prop, tmp_root)

            # Patch applied: incident page exists, log/index have new entries.
            incident = wiki / "incidents" / "promote-fixture.md"
            self.assertTrue(incident.exists())
            self.assertIn("# Promote Fixture", incident.read_text())

            log = wiki / "log.md"
            self.assertIn("promote promote-fixture", log.read_text())

            index = wiki / "index.md"
            self.assertIn("Promote Fixture", index.read_text())

            # Audit trail: proposals dir moved to .applied/.
            self.assertFalse(prop.exists())
            archived = (
                tmp_root / "doc_internal" / "proposals" / ".applied" / prop.name
            )
            self.assertTrue(archived.exists())
            self.assertEqual(result.archived_dir, archived)
            self.assertFalse(result.dry_run)

    def test_promote_dry_run_does_not_modify_wiki(self) -> None:
        from wiki_ingest.promoter import promote
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            wiki = self._build_tmp_repo(tmp_root)
            prop = self._build_proposals_dir(tmp_root)

            log_before = (wiki / "log.md").read_text()
            index_before = (wiki / "index.md").read_text()

            result = promote(prop, tmp_root, dry_run=True)

            self.assertTrue(result.dry_run)
            # Wiki unchanged.
            self.assertEqual((wiki / "log.md").read_text(), log_before)
            self.assertEqual((wiki / "index.md").read_text(), index_before)
            self.assertFalse((wiki / "incidents" / "promote-fixture.md").exists())
            # Proposals dir not moved.
            self.assertTrue(prop.exists())
            self.assertIsNone(result.archived_dir)

    def test_promote_validation_failure_leaves_wiki_untouched(self) -> None:
        """A patch-set that would fail the structural linter must NOT
        touch the live wiki tree."""
        from wiki_ingest.errors import PromoteValidationError
        from wiki_ingest.promoter import promote
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            wiki = self._build_tmp_repo(tmp_root)
            # Build a proposals dir with malformed frontmatter (slug
            # mismatch) so per-edit validation rejects.
            prop = self._build_proposals_dir(tmp_root, slug="bad-fixture")
            bad_preview = prop / "preview" / "incidents" / "bad-fixture.md"
            content = bad_preview.read_text()
            # Corrupt the slug so it doesn't match the filename stem.
            corrupted = content.replace("slug: bad-fixture", "slug: wrong-slug")
            bad_preview.write_text(corrupted)

            with self.assertRaises(PromoteValidationError):
                promote(prop, tmp_root)

            # Wiki tree still pristine.
            self.assertFalse((wiki / "incidents" / "bad-fixture.md").exists())
            # Proposals dir still in place (not moved to .applied/).
            self.assertTrue(prop.exists())

    def test_promote_idempotent_on_already_applied(self) -> None:
        """A second promote on an already-archived dir is a no-op."""
        from wiki_ingest.promoter import promote
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_tmp_repo(tmp_root)
            prop = self._build_proposals_dir(tmp_root)

            promote(prop, tmp_root)  # first apply

            archived = (
                tmp_root / "doc_internal" / "proposals" / ".applied" / prop.name
            )
            # Second promote on the .applied/ path is a no-op.
            result = promote(archived, tmp_root)
            self.assertEqual(result.applied_paths, [])

    def test_promote_missing_proposals_dir_raises(self) -> None:
        from wiki_ingest.errors import PromoteValidationError
        from wiki_ingest.promoter import promote
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_tmp_repo(tmp_root)
            with self.assertRaises(PromoteValidationError):
                promote(tmp_root / "doc_internal" / "proposals" / "nope", tmp_root)


class TestE2ESingleWriterInvariant(unittest.TestCase):
    """Phase 2 invariant: ONLY ``promoter.py`` writes to knowledge/wiki/.

    Grep-based check across the wiki_ingest package for write-side
    filesystem operations targeting knowledge/wiki/. Any module other
    than promoter.py performing such writes is a bug — even if it's
    "safe" — because the single-writer property is what makes
    promote's atomicity guarantee meaningful.
    """

    _PACKAGE_ROOT = _SCRIPTS_DIR / "wiki_ingest"
    _ALLOWED_WRITERS = {"promoter.py"}

    def test_only_promoter_writes_to_knowledge_wiki(self) -> None:
        import re

        # Patterns that signal "writing to knowledge/wiki": any
        # filesystem-write call (.write_text, .write_bytes, shutil.copy*,
        # shutil.move, os.rename, os.replace, mkdir+write) where the
        # path expression mentions "knowledge" / "wiki".
        write_re = re.compile(
            r"(\.write_text|\.write_bytes|shutil\.(copy|move|rmtree)|"
            r"os\.(rename|replace))\s*\(",
        )

        offenders: list[tuple[str, int, str]] = []
        for py in self._PACKAGE_ROOT.rglob("*.py"):
            rel = py.relative_to(self._PACKAGE_ROOT)
            # Tests are allowed to touch fixture wiki dirs.
            if rel.parts and rel.parts[0] == "tests":
                continue
            if py.name in self._ALLOWED_WRITERS:
                continue
            for lineno, line in enumerate(
                py.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if write_re.search(line) and (
                    "knowledge/wiki" in line or "knowledge / \"wiki\"" in line
                    or 'knowledge"' in line
                ):
                    offenders.append((str(rel), lineno, line.strip()))

        self.assertEqual(
            offenders, [],
            f"Found {len(offenders)} non-promoter writes to knowledge/wiki/:\n"
            + "\n".join(f"  {p}:{n}: {l}" for p, n, l in offenders)
        )


class TestE2EQuery(unittest.TestCase):
    """Phase 3: ``./scripts/wiki query "<question>"`` reads index.md
    first, follows links to relevant pages, returns an answer with
    citations. Pages NOT linked from the index are unreachable."""

    def _build_tmp_repo_with_pages(self, tmp: Path) -> Path:
        """Create a minimal wiki with index.md + 3 linked pages."""
        wiki = tmp / "knowledge" / "wiki"
        wiki.mkdir(parents=True)
        (wiki / "concepts").mkdir()
        (wiki / "incidents").mkdir()
        (wiki / "index.md").write_text(
            "---\npage_type: index\nslug: index\ntitle: T\nstatus: stable\nlast_reviewed: 2026-05-06\n---\n\n"
            "# Index\n\n"
            "## Concepts\n\n"
            "- [Origin Alignment](concepts/origin-alignment.md) — the breaker.\n"
            "- [Spec Drift](concepts/spec-drift.md) — when specs diverge.\n\n"
            "## Incidents\n\n"
            "- [PR 27 Derailment](incidents/pr-27-derailment.md) — a real example.\n",
            encoding="utf-8",
        )
        (wiki / "concepts" / "origin-alignment.md").write_text(
            "# Origin Alignment\n\nBody about origin alignment and breakers.\n",
            encoding="utf-8",
        )
        (wiki / "concepts" / "spec-drift.md").write_text(
            "# Spec Drift\n\nBody about specs and drift.\n",
            encoding="utf-8",
        )
        (wiki / "incidents" / "pr-27-derailment.md").write_text(
            "# PR 27 Derailment\n\nBody about PR 27 and derailment from origin.\n",
            encoding="utf-8",
        )
        (wiki / "log.md").write_text(
            "---\npage_type: log\nslug: log\ntitle: L\nstatus: stable\nlast_reviewed: 2026-05-06\n---\n\n# Log\n",
            encoding="utf-8",
        )
        # Mirror schema/ from the real repo so load_schema_files works.
        real_root = _SCRIPTS_DIR.parent
        shutil.copytree(
            real_root / "knowledge" / "wiki" / "schema",
            wiki / "schema",
        )
        return wiki

    def test_query_reads_index_first_and_selects_relevant_pages(self) -> None:
        from wiki_ingest.querier import _select_query_candidates
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_tmp_repo_with_pages(tmp_root)
            index_md, pages_loaded, pages_content = _select_query_candidates(
                repo_root=tmp_root,
                question="what does the wiki say about origin alignment and the breaker?",
                max_pages=5,
            )
            self.assertIn("# Index", index_md)
            self.assertIn("concepts/origin-alignment.md", pages_loaded)
            # Stable: the page with the most token overlap should be first.
            self.assertEqual(pages_loaded[0], "concepts/origin-alignment.md")
            # All loaded pages were linked from index.md.
            for rel in pages_loaded:
                self.assertIn(rel, index_md)

    def test_query_with_test_backend_returns_answer_and_citations(self) -> None:
        from wiki_ingest.backends.test import TestBackend
        from wiki_ingest.querier import DefaultQuerier
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_tmp_repo_with_pages(tmp_root)
            q = DefaultQuerier(backend=TestBackend(), repo_root=tmp_root)
            answer = q.query("origin alignment")
            self.assertTrue(answer.answer)
            self.assertGreater(len(answer.citations), 0)
            self.assertGreater(len(answer.pages_loaded), 0)

    def test_query_logs_pages_loaded_to_jsonl(self) -> None:
        import json as _json
        from wiki_ingest.backends.test import TestBackend
        from wiki_ingest.querier import DefaultQuerier
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_tmp_repo_with_pages(tmp_root)
            q = DefaultQuerier(backend=TestBackend(), repo_root=tmp_root)
            q.query("origin alignment breaker")
            log_path = tmp_root / "doc_internal" / "wiki-query-log.jsonl"
            self.assertTrue(log_path.exists())
            entry = _json.loads(log_path.read_text().strip().splitlines()[0])
            self.assertEqual(entry["question"], "origin alignment breaker")
            self.assertIn("pages_loaded", entry)
            self.assertIsInstance(entry["pages_loaded"], list)

    def test_query_skips_pages_not_in_index(self) -> None:
        """A page on disk that is NOT linked from index.md must not be
        loaded, even if its content looks relevant. Index-first."""
        from wiki_ingest.querier import _select_query_candidates
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            wiki = self._build_tmp_repo_with_pages(tmp_root)
            # Add an orphan page on disk — NOT linked from index.md.
            orphan = wiki / "concepts" / "orphan-relevant.md"
            orphan.write_text(
                "# Orphan\n\nVery relevant: origin alignment breaker drift.\n",
                encoding="utf-8",
            )
            _index, pages_loaded, _content = _select_query_candidates(
                repo_root=tmp_root,
                question="origin alignment breaker drift",
                max_pages=10,
            )
            self.assertNotIn(
                "concepts/orphan-relevant.md", pages_loaded,
                "orphan page (not in index) must not be loaded",
            )

    def test_query_empty_answer_when_wiki_lacks_info(self) -> None:
        """When the test backend's deterministic response returns an
        empty answer, the orchestrator surfaces it as ``answer == ''``."""
        from wiki_ingest.querier import DefaultQuerier
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_tmp_repo_with_pages(tmp_root)

            class _NoMatchBackend:
                def call(self, prompt):
                    return {
                        "version": 1,
                        "answer": "",
                        "citations": [
                            {"page": "index.md", "fragment": "(index only)"}
                        ],
                    }

            q = DefaultQuerier(backend=_NoMatchBackend(), repo_root=tmp_root)
            ans = q.query("a question with no good answer")
            self.assertEqual(ans.answer, "")
            self.assertEqual(len(ans.citations), 1)

    def test_query_file_back_round_trip(self) -> None:
        """--file-back: query → answer → patch-set with at least one edit."""
        from wiki_ingest.backends.test import TestBackend
        from wiki_ingest.querier import DefaultQuerier
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_tmp_repo_with_pages(tmp_root)
            q = DefaultQuerier(backend=TestBackend(), repo_root=tmp_root)
            answer, patch = q.query_with_file_back(
                "origin alignment breaker"
            )
            self.assertTrue(answer.answer)
            # Test backend's ingest-multi response is deterministic and
            # produces 3 edits (create + log + index).
            self.assertEqual(len(patch.edits), 3)


class TestE2EHealthLint(unittest.TestCase):
    """Phase 4: knowledge-health lint — contradictions, stale claims,
    weak orphans, missing cross-links."""

    def _build_wiki(self, tmp: Path) -> Path:
        # Provide README.md so frontmatter sources resolve.
        (tmp / "README.md").write_text("# Root\n", encoding="utf-8")
        wiki = tmp / "knowledge" / "wiki"
        wiki.mkdir(parents=True)
        for sub in ("concepts", "incidents", "decisions"):
            (wiki / sub).mkdir()
        (wiki / "index.md").write_text(
            "---\npage_type: index\nslug: index\ntitle: I\nstatus: stable\nlast_reviewed: 2026-05-06\n---\n\n"
            "# Index\n\n"
            "## Concepts\n- [Foo](concepts/foo.md)\n- [Bar](concepts/bar.md)\n\n"
            "## Decisions\n- [Use Foo](decisions/use-foo.md)\n",
            encoding="utf-8",
        )
        (wiki / "log.md").write_text(
            "---\npage_type: log\nslug: log\ntitle: L\nstatus: stable\nlast_reviewed: 2026-05-06\n---\n\n# Log\n",
            encoding="utf-8",
        )
        # foo: no source path drift, mentioned by other pages.
        (wiki / "concepts" / "foo.md").write_text(
            "---\npage_type: concept\nslug: foo\ntitle: Foo\nstatus: stable\n"
            "last_reviewed: 2026-05-06\nsources:\n  - path: README.md\n    sha: abc\n---\n\n"
            "# Foo\n\nA durable concept.\n",
            encoding="utf-8",
        )
        # bar: cites a missing source path → stale-claim finding.
        (wiki / "concepts" / "bar.md").write_text(
            "---\npage_type: concept\nslug: bar\ntitle: Bar\nstatus: stable\n"
            "last_reviewed: 2026-05-06\nsources:\n  - path: docs/this-file-does-not-exist.md\n    sha: def\n---\n\n"
            "# Bar\n\nMentions foo but does not link foo.\n",
            encoding="utf-8",
        )
        # use-foo: links foo (one inbound edge to foo from this page).
        (wiki / "decisions" / "use-foo.md").write_text(
            "---\npage_type: decision\nslug: use-foo\ntitle: Use Foo\nstatus: stable\n"
            "last_reviewed: 2026-05-06\nsources:\n  - path: README.md\n    sha: abc\n---\n\n"
            "# Use Foo\n\nWe will use [foo](../concepts/foo.md). Mentions foo.\n",
            encoding="utf-8",
        )
        # Mirror schema/scripts so tests don't need them but the lint
        # script ignores those subdirs anyway.
        real_root = _SCRIPTS_DIR.parent
        for sub in ("schema",):
            shutil.copytree(
                real_root / "knowledge" / "wiki" / sub,
                wiki / sub,
            )
        return wiki

    def test_stale_claim_check_flags_missing_source_path(self) -> None:
        from wiki_ingest.health_lint import lint_health
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_wiki(tmp_root)
            result = lint_health(repo_root=tmp_root, backend=None)
            stale = [f for f in result.findings if f.kind == "stale-claim"]
            self.assertEqual(len(stale), 1)
            self.assertIn("concepts/bar.md", stale[0].pages)
            self.assertIn("does-not-exist.md", stale[0].description)

    def test_weak_orphan_check_flags_single_inbound(self) -> None:
        """concepts/foo.md is linked only from decisions/use-foo.md
        (and from index.md, but the orphan check counts non-index
        non-log inbound edges as both contribute)."""
        from wiki_ingest.health_lint import lint_health
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_wiki(tmp_root)
            result = lint_health(repo_root=tmp_root, backend=None)
            orphans = [f for f in result.findings if f.kind == "weak-orphan"]
            self.assertGreater(len(orphans), 0)

    def test_missing_cross_link_check(self) -> None:
        """Build a wiki where 'foo' is mentioned in many pages but
        only linked once → flagged."""
        from wiki_ingest.health_lint import lint_health
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            wiki = self._build_wiki(tmp_root)
            # Add 3 more pages that mention foo without linking it.
            for i in range(3):
                slug = f"mentions-foo-{i}"
                (wiki / "concepts" / f"{slug}.md").write_text(
                    f"---\npage_type: concept\nslug: {slug}\ntitle: M{i}\nstatus: stable\n"
                    "last_reviewed: 2026-05-06\nsources:\n  - path: README.md\n    sha: abc\n---\n\n"
                    f"# Mentions Foo {i}\n\nThis page mentions foo without linking it.\n",
                    encoding="utf-8",
                )
            result = lint_health(repo_root=tmp_root, backend=None)
            cross = [f for f in result.findings if f.kind == "missing-cross-link"]
            self.assertGreater(len(cross), 0)
            slugs = sum(("foo" in f.description) for f in cross)
            self.assertGreater(slugs, 0)

    def test_clean_wiki_produces_zero_findings(self) -> None:
        """A wiki where every cited path exists, every page has ≥2
        inbound edges, and every entity is cross-linked produces 0
        findings."""
        from wiki_ingest.health_lint import lint_health
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            wiki = tmp_root / "knowledge" / "wiki"
            wiki.mkdir(parents=True)
            (tmp_root / "README.md").write_text("# Root readme\n", encoding="utf-8")
            (wiki / "index.md").write_text(
                "---\npage_type: index\nslug: index\ntitle: I\nstatus: stable\nlast_reviewed: 2026-05-06\n---\n\n"
                "# Index\n\n## Concepts\n\n- [Alpha](concepts/alpha.md)\n- [Beta](concepts/beta.md)\n",
                encoding="utf-8",
            )
            (wiki / "log.md").write_text(
                "---\npage_type: log\nslug: log\ntitle: L\nstatus: stable\nlast_reviewed: 2026-05-06\n---\n\n# Log\n",
                encoding="utf-8",
            )
            (wiki / "concepts").mkdir()
            (wiki / "concepts" / "alpha.md").write_text(
                "---\npage_type: concept\nslug: alpha\ntitle: Alpha\nstatus: stable\n"
                "last_reviewed: 2026-05-06\nsources:\n  - path: README.md\n    sha: abc\n---\n\n"
                "# Alpha\n\nLinks to [beta](beta.md).\n",
                encoding="utf-8",
            )
            (wiki / "concepts" / "beta.md").write_text(
                "---\npage_type: concept\nslug: beta\ntitle: Beta\nstatus: stable\n"
                "last_reviewed: 2026-05-06\nsources:\n  - path: README.md\n    sha: abc\n---\n\n"
                "# Beta\n\nLinks to [alpha](alpha.md).\n",
                encoding="utf-8",
            )
            real_root = _SCRIPTS_DIR.parent
            shutil.copytree(real_root / "knowledge" / "wiki" / "schema", wiki / "schema")

            result = lint_health(repo_root=tmp_root, backend=None)
            # alpha and beta cross-link each other AND both are linked
            # from index → no weak orphans (each has 2 inbound edges).
            # Sources resolve. No frequent-mention entities.
            self.assertEqual(
                result.findings, [],
                f"clean wiki yielded findings: {result.findings}",
            )

    def test_paths_filter_scopes_findings(self) -> None:
        from wiki_ingest.health_lint import lint_health
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_wiki(tmp_root)
            # Scoped to bar.md only.
            scoped = lint_health(
                repo_root=tmp_root,
                paths=["concepts/bar.md"],
                backend=None,
            )
            for f in scoped.findings:
                self.assertIn("concepts/bar.md", f.pages)

    def test_contradiction_check_uses_backend_when_provided(self) -> None:
        from wiki_ingest.health_lint import lint_health
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            self._build_wiki(tmp_root)

            class _FixedBackend:
                """Returns contradicts=True for every page pair, with a
                fixed description. Lets us assert the contradictions
                code path runs and shapes findings correctly."""

                def call(self, prompt):
                    return {
                        "version": 1,
                        "contradicts": True,
                        "description": "fixture backend says yes",
                    }

            result = lint_health(
                repo_root=tmp_root,
                backend=_FixedBackend(),
            )
            contradictions = [
                f for f in result.findings if f.kind == "contradiction"
            ]
            self.assertGreater(len(contradictions), 0)
            self.assertIn(
                "fixture backend says yes",
                contradictions[0].description,
            )


if __name__ == "__main__":
    unittest.main()
