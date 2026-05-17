# tests/test_cct_dogfood_memkernel_adapter.py — adapter for memkernel#3 dogfood.
#
# Hermetic: builds a synthetic mini-memkernel git repo in a tempdir,
# points the adapter at it via CCT_MEMKERNEL_PATH, then exercises
# prepare_task + verify against the four scenarios that determine
# the verdict (empty agent / valid spec / pyproject tampering /
# rogue MCP code). No real memkernel clone or network required.

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmark_runner.contracts import BenchmarkAdapter, ISOLATION_WORKTREE_VENV


_FIXTURE_PYPROJECT = """[tool.poetry]
name = "memkernel"
version = "0.1.0"

[tool.poetry.dependencies]
python = ">=3.11"

[tool.poetry.group.dev.dependencies]
pytest = ">=8"
"""

_FIXTURE_MCP_INIT = "# fake mcp pkg\n"
_FIXTURE_MCP_SERVER = "def main() -> None:\n    pass\n"
_FIXTURE_MCP_TOOL = "def memory_tool() -> None:\n    pass\n"


def _make_fake_memkernel(root: Path) -> str:
    """Create a tiny git repo that resembles memkernel's layout. Return HEAD SHA."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(_FIXTURE_PYPROJECT, encoding="utf-8")
    mcp = root / "src" / "memkernel" / "mcp"
    (mcp / "tools").mkdir(parents=True)
    (mcp / "__init__.py").write_text(_FIXTURE_MCP_INIT, encoding="utf-8")
    (mcp / "server.py").write_text(_FIXTURE_MCP_SERVER, encoding="utf-8")
    (mcp / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (mcp / "tools" / "memory.py").write_text(_FIXTURE_MCP_TOOL, encoding="utf-8")

    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, env=env)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "fixture"],
        check=True, env=env,
    )
    sha = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, env=env,
    ).stdout.strip()
    return sha


class CctDogfoodMemkernelAdapterTest(unittest.TestCase):
    """Hermetic suite: synthetic memkernel + per-test worktree."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_root = Path(self._tmp.name)

        self.fake_memkernel = tmp_root / "fake-memkernel"
        self.fake_sha = _make_fake_memkernel(self.fake_memkernel)

        # Point the adapter at the fake repo + override REVISION to
        # match our fixture HEAD.
        from benchmarks.adapters.cct_dogfood_memkernel import adapter as _adapter
        self._adapter_module = _adapter
        self._patches = [
            mock.patch.dict(
                os.environ,
                {_adapter.MEMKERNEL_PATH_ENV: str(self.fake_memkernel)},
            ),
            mock.patch.object(_adapter, "pinned_revision", return_value=self.fake_sha),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

        self.adapter = _adapter.CctDogfoodMemkernelAdapter()
        self.task = self.adapter.list_tasks()[0]
        self.worktree = tmp_root / "wt"
        self.worktree.mkdir()
        self.adapter.prepare_task(self.task, self.worktree)

    # ── Identity / contract ────────────────────────────────────────────────

    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(self.adapter, BenchmarkAdapter)

    def test_lists_one_task_when_memkernel_present(self) -> None:
        tasks = self.adapter.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_id, "memory-brain-spec")
        self.assertEqual(tasks[0].language, "python")
        self.assertEqual(tasks[0].metadata["memkernel_revision"], self.fake_sha)

    def test_lists_no_tasks_when_memkernel_absent(self) -> None:
        with mock.patch.dict(
            os.environ, {self._adapter_module.MEMKERNEL_PATH_ENV: "/nonexistent/path"}
        ):
            self.assertEqual(self.adapter.list_tasks(), [])

    def test_isolation_is_worktree_venv(self) -> None:
        cfg = self.adapter.isolation_for(self.task)
        self.assertEqual(cfg.tier, ISOLATION_WORKTREE_VENV)
        self.assertEqual(cfg.python, "python3")
        self.assertIn("ruff", cfg.install_command or "")

    def test_max_attempts_single_shot(self) -> None:
        self.assertEqual(self.adapter.max_attempts(), 1)

    def test_golden_patch_not_implemented(self) -> None:
        with self.assertRaises(NotImplementedError):
            self.adapter.golden_patch(self.task)

    # ── Prompt composition ─────────────────────────────────────────────────

    def test_prompt_includes_framing_and_verbatim_body_sentinel(self) -> None:
        prompt = self.adapter.prompt_for(self.task, 1, None)
        # Framing lines:
        self.assertIn("specs/memory-brain/spec.md", prompt)
        self.assertIn("spec-first", prompt)
        self.assertIn(self.fake_sha, prompt)
        # Verbatim body sentinel — the directive said "verbatim" and the
        # source body opens with this exact phrase. If it ever changes
        # we want the test to fail loudly.
        self.assertIn("This is a spec-first issue. No code changes land here.", prompt)

    # ── Worktree preparation ───────────────────────────────────────────────

    def test_prepare_task_snapshots_at_pinned_sha(self) -> None:
        # Snapshot must include the fake repo's files at the pinned
        # commit; not the .git directory.
        self.assertTrue((self.worktree / "pyproject.toml").is_file())
        self.assertTrue((self.worktree / "src/memkernel/mcp/server.py").is_file())
        self.assertFalse((self.worktree / ".git").exists())

    def test_prepare_task_captures_baseline(self) -> None:
        self.assertTrue((self.worktree / ".cct-baseline" / "pyproject.toml").is_file())
        self.assertTrue((self.worktree / ".cct-baseline" / "mcp" / "server.py").is_file())

    def test_prepare_task_drops_verify_script(self) -> None:
        verify = self.worktree / ".cct-verify.sh"
        self.assertTrue(verify.is_file())
        # Executable bit must be set so `bash` invocation through the
        # runner finds it.
        self.assertTrue(os.access(verify, os.X_OK))

    # ── Verify scenarios ───────────────────────────────────────────────────

    def _write_valid_spec(self) -> None:
        spec_dir = self.worktree / "specs" / "memory-brain"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.md").write_text(
            "## 1. Problem Statement\nstub\n"
            "## 2. Proposed Architecture\nstub\n"
            "## 3. Memory Tier Model\nstub\n"
            "## 4. Lifecycle State Machine\nstub\n"
            "## 5. Routing Layer\nstub\n"
            "## 6. Synthesis Port\nstub\n"
            "## 7. Acceptance Criteria\nstub\n",
            encoding="utf-8",
        )

    def test_verify_fails_when_spec_absent(self) -> None:
        result = self.adapter.verify(self.task, self.worktree)
        self.assertFalse(result.tests_passed)
        self.assertFalse(result.required_files_present)
        self.assertIn("spec_exists", result.tests_output)

    def test_verify_passes_with_valid_spec(self) -> None:
        self._write_valid_spec()
        result = self.adapter.verify(self.task, self.worktree)
        self.assertTrue(result.tests_passed, msg=result.tests_output)
        self.assertTrue(result.required_files_present)
        # All seven section checks should appear as ✓.
        for section in (
            "Problem Statement", "Proposed Architecture", "Memory Tier Model",
            "Lifecycle State Machine", "Routing Layer", "Synthesis Port",
            "Acceptance Criteria",
        ):
            self.assertIn(f"✓ section: {section}", result.tests_output)

    def test_verify_fails_when_section_missing(self) -> None:
        # Write a spec missing the "Routing Layer" section.
        spec_dir = self.worktree / "specs" / "memory-brain"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "spec.md").write_text(
            "## 1. Problem Statement\n## 2. Proposed Architecture\n"
            "## 3. Memory Tier Model\n## 4. Lifecycle State Machine\n"
            "## 6. Synthesis Port\n## 7. Acceptance Criteria\n",
            encoding="utf-8",
        )
        result = self.adapter.verify(self.task, self.worktree)
        self.assertFalse(result.tests_passed)
        self.assertIn("✗ section: Routing Layer", result.tests_output)

    def test_verify_fails_when_pyproject_modified(self) -> None:
        self._write_valid_spec()
        pp = self.worktree / "pyproject.toml"
        pp.write_text(pp.read_text() + "\n# tampered\n", encoding="utf-8")
        result = self.adapter.verify(self.task, self.worktree)
        self.assertFalse(result.tests_passed)
        self.assertIn("✗ pyproject_unchanged", result.tests_output)

    def test_verify_fails_when_mcp_modified(self) -> None:
        self._write_valid_spec()
        (self.worktree / "src/memkernel/mcp/tools/rogue.py").write_text(
            "# unauthorized\n", encoding="utf-8"
        )
        result = self.adapter.verify(self.task, self.worktree)
        self.assertFalse(result.tests_passed)
        self.assertIn("✗ mcp_unchanged", result.tests_output)

    def test_verify_fails_when_verify_script_missing(self) -> None:
        # If prepare_task did not run (or its artifact was wiped), verify
        # should report a structured failure rather than crashing.
        (self.worktree / ".cct-verify.sh").unlink()
        result = self.adapter.verify(self.task, self.worktree)
        self.assertFalse(result.tests_passed)
        self.assertIn("missing", result.tests_output)


if __name__ == "__main__":
    unittest.main()
