# tests/test_copilot_cli.py — tests for CopilotCliBackend and resolve_backend().

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wiki_ingest.backends import resolve_backend
from wiki_ingest.backends.copilot_cli import CopilotCliBackend
from wiki_ingest.backends.test import TestBackend
from wiki_ingest.errors import BackendInvocationError, BackendNotFoundError, ContractViolationError

# Locate fixtures directory.
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_STUB_BACKEND = str(_FIXTURES_DIR / "stub-backend.sh")
_STUB_BACKEND_FAIL = str(_FIXTURES_DIR / "stub-backend-fail.sh")

# A minimal valid BackendPrompt to pass to CopilotCliBackend.call().
_SAMPLE_PROMPT: dict = {
    "version": 1,
    "system_instructions": "You are a wiki curator.",
    "task": "ingest",
    "schema_excerpts": {
        "ingest_rules": "rule 1",
        "page_types": "incident",
        "citation_rules": "cite sources",
    },
    "source": {
        "kind": "file",
        "path": "stub-source.md",
        "content": "# Stub Test Source\n\nSome content.",
    },
    "response_schema": "{}",
}


def _write_script(path: str, content: str) -> None:
    """Write a shell script to path and make it executable."""
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# TestCopilotCliBackend
# ---------------------------------------------------------------------------

class TestCopilotCliBackend(unittest.TestCase):
    """Tests for CopilotCliBackend against shell stubs (no real CLI required)."""

    def test_success_path_with_stub(self) -> None:
        """Stub backend returns valid JSON in a ```json fence; backend returns parsed dict."""
        backend = CopilotCliBackend(sys.executable, timeout_seconds=10)
        # Build a one-shot Python script that echoes the same output as stub-backend.sh.
        valid_response = {
            "version": 1,
            "disposition": "accept",
            "reason": "Stub accept.",
            "page_type": "incident",
            "slug": "stub-test-source",
            "title": "Stub Test Source",
            "draft_markdown": (
                "---\npage_type: incident\nslug: stub-test-source\n"
                "title: Stub Test Source\nstatus: draft\nlast_reviewed: 2026-05-04\n"
                "sources:\n  - path: stub-source.md\n    sha: abc1234\n---\n\n"
                "# Stub Test Source\n\n## What happened\n\n(placeholder)\n"
            ),
            "sources": [{"path": "stub-source.md", "sha": "abc1234"}],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            script_path = f.name
            # Use sys.executable (-p is handled by the backend; we override by using
            # a Python script that ignores args and prints the fence to stdout).
            json_str = json.dumps(valid_response)
            f.write(f"import sys\nprint('```json')\nprint({json_str!r})\nprint('```')\n")
        try:
            backend2 = CopilotCliBackend(
                f"{sys.executable} {script_path}",
                timeout_seconds=10,
            )
            # CopilotCliBackend builds cmd = [cli_name, "-p", prompt_text].
            # For a multi-word cli_name that won't work directly; use the shell stub instead.
            # Use the actual stub-backend.sh which is already executable.
            sh_backend = CopilotCliBackend(_STUB_BACKEND, timeout_seconds=10)
            result = sh_backend.call(_SAMPLE_PROMPT)
            self.assertEqual(result["disposition"], "accept")
            self.assertEqual(result["slug"], "stub-test-source")
        finally:
            os.unlink(script_path)

    def test_stub_backend_returns_dict(self) -> None:
        """stub-backend.sh returns a valid dict from CopilotCliBackend.call()."""
        backend = CopilotCliBackend(_STUB_BACKEND, timeout_seconds=10)
        result = backend.call(_SAMPLE_PROMPT)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["page_type"], "incident")

    def test_nonzero_exit_raises_backend_invocation_error(self) -> None:
        """Backend that exits non-zero raises BackendInvocationError with stderr in message."""
        backend = CopilotCliBackend(_STUB_BACKEND_FAIL, timeout_seconds=10)
        with self.assertRaises(BackendInvocationError) as ctx:
            backend.call(_SAMPLE_PROMPT)
        msg = str(ctx.exception)
        self.assertIn("exited with code", msg)
        # The stub writes "simulated backend failure" to stderr
        self.assertIn("simulated backend failure", msg)

    def test_malformed_json_raises_contract_violation(self) -> None:
        """Backend that emits malformed JSON raises ContractViolationError."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir=_FIXTURES_DIR
        ) as f:
            script_path = f.name
            _write_script(script_path, "#!/usr/bin/env bash\necho 'not json at all'\n")
        try:
            backend = CopilotCliBackend(script_path, timeout_seconds=10)
            with self.assertRaises(ContractViolationError) as ctx:
                backend.call(_SAMPLE_PROMPT)
            self.assertIn("no JSON object", str(ctx.exception))
        finally:
            os.unlink(script_path)

    def test_timeout_raises_backend_invocation_error(self) -> None:
        """Backend that sleeps longer than timeout raises BackendInvocationError."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, dir=_FIXTURES_DIR
        ) as f:
            script_path = f.name
            _write_script(script_path, "#!/usr/bin/env bash\nsleep 10\n")
        try:
            backend = CopilotCliBackend(script_path, timeout_seconds=1)
            with self.assertRaises(BackendInvocationError) as ctx:
                backend.call(_SAMPLE_PROMPT)
            self.assertIn("timed out", str(ctx.exception))
        finally:
            os.unlink(script_path)

    def test_cli_not_found_raises_backend_not_found_error(self) -> None:
        """Non-existent CLI executable raises BackendNotFoundError (exit 2).

        Missing CLI is "not found", not "invocation failed". This matches
        resolve_backend()'s preflight semantics so direct
        CopilotCliBackend construction (e.g., contributor SDK adapters)
        produces the same error type as the resolver path.
        """
        backend = CopilotCliBackend("__no_such_cli__", timeout_seconds=5)
        with self.assertRaises(BackendNotFoundError) as ctx:
            backend.call(_SAMPLE_PROMPT)
        msg = str(ctx.exception)
        self.assertIn("__no_such_cli__", msg)


# ---------------------------------------------------------------------------
# TestResolveBackend
# ---------------------------------------------------------------------------

class TestResolveBackend(unittest.TestCase):
    """Tests for resolve_backend() precedence logic in backends/__init__.py."""

    def test_resolve_test_returns_test_backend(self) -> None:
        """resolve_backend('test') returns a TestBackend instance."""
        backend = resolve_backend("test")
        self.assertIsInstance(backend, TestBackend)

    def test_resolve_claude_with_which_finds_it(self) -> None:
        """resolve_backend('claude') constructs a CopilotCliBackend when shutil.which finds it."""
        with patch("wiki_ingest.backends.shutil.which", return_value="/usr/local/bin/claude"):
            backend = resolve_backend("claude")
        self.assertIsInstance(backend, CopilotCliBackend)

    def test_resolve_claude_with_which_missing_raises(self) -> None:
        """resolve_backend('claude') raises BackendNotFoundError when shutil.which returns None."""
        with patch("wiki_ingest.backends.shutil.which", return_value=None):
            with self.assertRaises(BackendNotFoundError) as ctx:
                resolve_backend("claude")
        self.assertIn("claude", str(ctx.exception))

    def test_resolve_unknown_name_raises_with_valid_options(self) -> None:
        """resolve_backend with an unknown name raises BackendNotFoundError naming valid options."""
        with self.assertRaises(BackendNotFoundError) as ctx:
            resolve_backend("unknown-name")
        msg = str(ctx.exception)
        self.assertIn("unknown-name", msg)
        # Must name the valid options
        self.assertIn("test", msg)
        self.assertIn("claude", msg)

    def test_resolve_none_with_env_var_set_uses_env(self) -> None:
        """resolve_backend(None) with WIKI_INGEST_BACKEND=codex tries codex."""
        with patch.dict(os.environ, {"WIKI_INGEST_BACKEND": "codex"}):
            with patch("wiki_ingest.backends.shutil.which", return_value="/usr/bin/codex"):
                backend = resolve_backend(None)
        self.assertIsInstance(backend, CopilotCliBackend)

    def test_resolve_none_with_env_var_missing_from_path_raises(self) -> None:
        """resolve_backend(None) with WIKI_INGEST_BACKEND=codex but codex not on PATH raises."""
        with patch.dict(os.environ, {"WIKI_INGEST_BACKEND": "codex"}):
            with patch("wiki_ingest.backends.shutil.which", return_value=None):
                with self.assertRaises(BackendNotFoundError) as ctx:
                    resolve_backend(None)
        self.assertIn("codex", str(ctx.exception))

    def test_auto_detect_happy_path_returns_claude(self) -> None:
        """resolve_backend(None) with no env, shutil.which finds claude → CopilotCliBackend."""
        def which_side_effect(name: str) -> str | None:
            return "/usr/local/bin/claude" if name == "claude" else None

        env_without_backend = {k: v for k, v in os.environ.items() if k != "WIKI_INGEST_BACKEND"}
        with patch.dict(os.environ, env_without_backend, clear=True):
            with patch("wiki_ingest.backends.shutil.which", side_effect=which_side_effect):
                backend = resolve_backend(None)
        self.assertIsInstance(backend, CopilotCliBackend)

    def test_auto_detect_nothing_on_path_raises(self) -> None:
        """resolve_backend(None) with no env, nothing on PATH raises BackendNotFoundError."""
        env_without_backend = {k: v for k, v in os.environ.items() if k != "WIKI_INGEST_BACKEND"}
        with patch.dict(os.environ, env_without_backend, clear=True):
            with patch("wiki_ingest.backends.shutil.which", return_value=None):
                with self.assertRaises(BackendNotFoundError) as ctx:
                    resolve_backend(None)
        msg = str(ctx.exception)
        # Must name all three candidates
        self.assertIn("claude", msg)
        self.assertIn("codex", msg)
        self.assertIn("cursor", msg)

    def test_cli_flag_wins_over_env_var(self) -> None:
        """CLI flag wins over WIKI_INGEST_BACKEND env var: resolve_backend('test') ignores env."""
        with patch.dict(os.environ, {"WIKI_INGEST_BACKEND": "codex"}):
            backend = resolve_backend("test")
        # Should be TestBackend (from the "test" flag), not CopilotCliBackend
        self.assertIsInstance(backend, TestBackend)

    def test_resolve_codex_with_which_finds_it(self) -> None:
        """resolve_backend('codex') constructs a CopilotCliBackend when shutil.which finds it."""
        with patch("wiki_ingest.backends.shutil.which", return_value="/usr/local/bin/codex"):
            backend = resolve_backend("codex")
        self.assertIsInstance(backend, CopilotCliBackend)

    def test_resolve_cursor_with_which_finds_it(self) -> None:
        """resolve_backend('cursor') constructs a CopilotCliBackend when shutil.which finds it."""
        with patch("wiki_ingest.backends.shutil.which", return_value="/usr/local/bin/cursor"):
            backend = resolve_backend("cursor")
        self.assertIsInstance(backend, CopilotCliBackend)

    def test_resolve_env_test_returns_test_backend(self) -> None:
        """WIKI_INGEST_BACKEND=test resolves to TestBackend (registered backend, no PATH check)."""
        with patch.dict(os.environ, {"WIKI_INGEST_BACKEND": "test"}):
            backend = resolve_backend(None)
        self.assertIsInstance(backend, TestBackend)


if __name__ == "__main__":
    unittest.main()
