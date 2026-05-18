# tests/test_codex_backend.py — Codex backend tests.
#
# These tests do NOT spawn the real ``codex`` CLI. The transcript parser
# is exercised against committed fixtures, and the run() path is exercised
# against a fake CLI shim that echoes a chosen fixture + logs argv/stdin/cwd,
# so we can validate end-to-end behavior without network or auth.
#
# The fake shim pattern mirrors test_claude_code_backend.py exactly.
# No live CLI/network calls anywhere in this file.

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark_runner._register import unregister_all_for_tests
from benchmark_runner.backends.codex import (
    BACKEND_FAMILY,
    CodexBackend,
    CodexCliNotFoundError,
    _parse_transcript,
    factory,
)
from benchmark_runner.contracts import Backend, RunContext


_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "codex"

# Fake `codex` shim: echoes the chosen fixture, logs argv/stdin/cwd,
# exits with the requested code. Mirrors the fake `claude` shim.
_FAKE_CODEX = """#!{shebang}
import json, os, sys
log_path = os.environ.get("CCT_FAKE_CODEX_LOG", "")
fixture_path = os.environ["CCT_FAKE_CODEX_TRANSCRIPT"]
stdin_data = sys.stdin.read()
if log_path:
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({{
            "argv": sys.argv,
            "cwd": os.getcwd(),
            "stdin": stdin_data,
            "env_keys": sorted(os.environ.keys()),
        }}, f)
with open(fixture_path, "r", encoding="utf-8") as src:
    sys.stdout.write(src.read())
stderr_msg = os.environ.get("CCT_FAKE_CODEX_STDERR", "")
if stderr_msg:
    sys.stderr.write(stderr_msg)
sys.exit(int(os.environ.get("CCT_FAKE_CODEX_EXIT_CODE", "0")))
"""


def _install_fake_codex(tmpdir: Path) -> Path:
    """Install a tiny Python shim called 'codex' on a tmpdir we put on PATH."""
    bindir = tmpdir / "fake-bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "codex"
    fake.write_text(_FAKE_CODEX.format(shebang=sys.executable), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake


class TestParseTranscript(unittest.TestCase):
    def test_success_transcript_yields_full_usage(self) -> None:
        stdout = (_FIXTURES / "transcript-success.jsonl").read_text(encoding="utf-8")
        parsed = _parse_transcript(stdout)
        # Two agent_message events concatenated.
        self.assertIn("I'll make the requested", parsed.result_text)
        self.assertIn("Created add.py", parsed.result_text)
        self.assertEqual(parsed.tokens_input, 76035)
        self.assertEqual(parsed.tokens_output, 261)
        self.assertEqual(parsed.cache_read_tokens, 47616)
        # Tool calls: 2 command_execution items + 1 file_change item.
        self.assertEqual(parsed.tool_calls.get("command_execution"), 2)
        self.assertEqual(parsed.tool_calls.get("file_change"), 1)

    def test_missing_usage_yields_none_not_zero(self) -> None:
        stdout = (_FIXTURES / "transcript-no-usage.jsonl").read_text(encoding="utf-8")
        parsed = _parse_transcript(stdout)
        self.assertIsNone(parsed.tokens_input)
        self.assertIsNone(parsed.tokens_output)
        self.assertIsNone(parsed.cache_read_tokens)

    def test_zero_usage_yields_zero_not_none(self) -> None:
        # 0 in the JSON means 0, not None — null vs zero is preserved.
        stdout = (_FIXTURES / "transcript-zero-usage.jsonl").read_text(encoding="utf-8")
        parsed = _parse_transcript(stdout)
        self.assertEqual(parsed.tokens_input, 0)
        self.assertEqual(parsed.tokens_output, 0)
        self.assertEqual(parsed.cache_read_tokens, 0)

    def test_empty_stdout_returns_empty_parsed(self) -> None:
        parsed = _parse_transcript("")
        self.assertEqual(parsed.result_text, "")
        self.assertIsNone(parsed.tokens_input)
        self.assertEqual(parsed.tool_calls, {})

    def test_unparseable_lines_are_skipped(self) -> None:
        # Partial/corrupt transcript: bad lines skipped, good line still parsed.
        stdout = (
            'not json\n'
            '{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":3,"cached_input_tokens":1}}\n'
        )
        parsed = _parse_transcript(stdout)
        self.assertEqual(parsed.tokens_input, 5)
        self.assertEqual(parsed.tokens_output, 3)
        self.assertEqual(parsed.cache_read_tokens, 1)


class TestBackendShape(unittest.TestCase):
    def setUp(self) -> None:
        unregister_all_for_tests()

    def test_satisfies_backend_protocol(self) -> None:
        self.assertIsInstance(CodexBackend(model="o4-mini"), Backend)

    def test_backend_id_is_family(self) -> None:
        self.assertEqual(CodexBackend(model="").backend_id, BACKEND_FAMILY)

    def test_factory_carries_model(self) -> None:
        b = factory("o4-mini")
        self.assertEqual(b._model, "o4-mini")  # noqa: SLF001

    def test_run_raises_when_cli_missing(self) -> None:
        b = CodexBackend(model="", cli_executable="codex-not-installed-xyz")
        ctx = RunContext(
            benchmark_id="x",
            task_id="y",
            backend_id=BACKEND_FAMILY,
            run_id="run-001",
            attempt=1,
            worktree=Path("/tmp"),
            model="",
        )
        with self.assertRaises(CodexCliNotFoundError):
            b.run("hello", ctx)


class TestBackendEndToEndAgainstFakeCli(unittest.TestCase):
    """Drives CodexBackend against a fake ``codex`` shim.

    Asserts the backend invokes the CLI with the verified argv:
      codex exec --json --sandbox workspace-write --skip-git-repo-check
      [--model <model> when non-empty] -
    with prompt on stdin, cwd = worktree. No live CLI/network.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-codex-test-")
        self._tmp_path = Path(self._tmp)
        self._fake = _install_fake_codex(self._tmp_path)
        self._invocation_log = self._tmp_path / "invocation.json"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run_backend(
        self,
        fixture_name: str,
        *,
        model: str = "o4-mini",
        env_overrides: dict[str, str] | None = None,
        exit_code: int = 0,
    ) -> dict:
        worktree = self._tmp_path / "wt"
        worktree.mkdir(exist_ok=True)
        # Attempt dir is the worktree's parent (where transcript.jsonl is written).
        # The harness creates attempt_dir/worktree/ — mimic that structure.
        attempt_dir = worktree.parent
        fixture_path = _FIXTURES / fixture_name

        env_overrides = dict(env_overrides or {})
        env_overrides.update({
            "CCT_FAKE_CODEX_TRANSCRIPT": str(fixture_path),
            "CCT_FAKE_CODEX_LOG": str(self._invocation_log),
            "CCT_FAKE_CODEX_EXIT_CODE": str(exit_code),
        })

        backend = CodexBackend(model=model, cli_executable=str(self._fake))
        ctx = RunContext(
            benchmark_id="x",
            task_id="t1",
            backend_id=BACKEND_FAMILY,
            run_id="run-001",
            attempt=1,
            worktree=worktree,
            model=model,
        )

        old_env = {k: os.environ.get(k) for k in env_overrides}
        try:
            os.environ.update(env_overrides)
            result = backend.run("Write add.py", ctx)
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        return {
            "result": result,
            "log": json.loads(self._invocation_log.read_text(encoding="utf-8")),
            "worktree": worktree,
        }

    # ── Argv assertions ─────────────────────────────────────────────────

    def test_argv_contains_exec_json_sandbox_skip_git(self) -> None:
        out = self._run_backend("transcript-success.jsonl", model="o4-mini")
        argv = out["log"]["argv"]
        # argv[0] is the shim path (not "codex"); rest is the real args.
        self.assertIn("exec", argv)
        self.assertIn("--json", argv)
        self.assertIn("--sandbox", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        self.assertIn("--skip-git-repo-check", argv)

    def test_model_flag_present_when_model_nonempty(self) -> None:
        out = self._run_backend("transcript-success.jsonl", model="o4-mini")
        argv = out["log"]["argv"]
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "o4-mini")

    def test_model_flag_absent_when_model_empty(self) -> None:
        out = self._run_backend("transcript-success.jsonl", model="")
        argv = out["log"]["argv"]
        self.assertNotIn("--model", argv)

    def test_no_ask_for_approval_flag(self) -> None:
        # Verified: codex exec has no --ask-for-approval flag in 0.130.0.
        out = self._run_backend("transcript-success.jsonl", model="o4-mini")
        argv = out["log"]["argv"]
        self.assertNotIn("--ask-for-approval", argv)

    def test_trailing_dash_present(self) -> None:
        # Prompt must be on stdin via the trailing ``-`` (not in argv).
        out = self._run_backend("transcript-success.jsonl", model="o4-mini")
        argv = out["log"]["argv"]
        self.assertEqual(argv[-1], "-")

    def test_prompt_sent_on_stdin(self) -> None:
        out = self._run_backend("transcript-success.jsonl")
        self.assertIn("Write add.py", out["log"]["stdin"])

    def test_cwd_is_the_worktree(self) -> None:
        out = self._run_backend("transcript-success.jsonl")
        self.assertEqual(
            Path(out["log"]["cwd"]).resolve(),
            out["worktree"].resolve(),
        )

    # ── Token + metadata assertions ─────────────────────────────────────

    def test_run_records_token_counts(self) -> None:
        out = self._run_backend("transcript-success.jsonl")
        result = out["result"]
        self.assertEqual(result.tokens_input, 76035)
        self.assertEqual(result.tokens_output, 261)
        self.assertEqual(result.cache_read_tokens, 47616)
        self.assertEqual(result.tool_calls.get("command_execution"), 2)
        self.assertEqual(result.tool_calls.get("file_change"), 1)

    def test_missing_usage_yields_none(self) -> None:
        out = self._run_backend("transcript-no-usage.jsonl")
        result = out["result"]
        self.assertIsNone(result.tokens_input)
        self.assertIsNone(result.tokens_output)
        self.assertIsNone(result.cache_read_tokens)

    def test_zero_usage_yields_zero_not_none(self) -> None:
        out = self._run_backend("transcript-zero-usage.jsonl")
        result = out["result"]
        self.assertEqual(result.tokens_input, 0)
        self.assertEqual(result.tokens_output, 0)
        self.assertEqual(result.cache_read_tokens, 0)

    def test_metadata_has_family_and_model(self) -> None:
        out = self._run_backend("transcript-success.jsonl", model="o4-mini")
        meta = out["result"].backend_metadata
        self.assertEqual(meta["family"], BACKEND_FAMILY)
        self.assertEqual(meta["model"], "o4-mini")

    def test_metadata_has_exit_code(self) -> None:
        out = self._run_backend("transcript-success.jsonl")
        self.assertEqual(out["result"].backend_metadata["exit_code"], 0)

    def test_metadata_has_codex_version(self) -> None:
        out = self._run_backend("transcript-success.jsonl")
        meta = out["result"].backend_metadata
        self.assertIn("codex", meta["codex_version"].lower())

    def test_metadata_has_config_toml_path_not_key(self) -> None:
        # config_toml_path is a filesystem path (not a secret).
        # provider_id is the config key name (not a secret value).
        out = self._run_backend("transcript-success.jsonl")
        meta = out["result"].backend_metadata
        # These keys must exist (may be None if config absent on test machine).
        self.assertIn("config_toml_path", meta)
        self.assertIn("provider_id", meta)
        # Neither should be an API key — values are paths or short id strings.
        # We can't assert exact values since they depend on the test machine's
        # ~/.codex/config.toml, but we can assert no "sk-" style key patterns.
        for field in ("config_toml_path", "provider_id"):
            val = meta[field]
            if val is not None:
                self.assertNotIn("sk-", str(val))
                self.assertNotIn("Bearer", str(val))

    def test_no_api_key_in_metadata(self) -> None:
        # Belt-and-suspenders: the full metadata string must not contain
        # any recognizable API key patterns.
        out = self._run_backend("transcript-success.jsonl")
        meta_str = str(out["result"].backend_metadata)
        self.assertNotIn("sk-", meta_str)
        self.assertNotIn("Bearer ", meta_str)

    def test_run_persists_transcript_and_model_output(self) -> None:
        out = self._run_backend("transcript-success.jsonl")
        result = out["result"]
        self.assertIsNotNone(result.transcript_path)
        self.assertTrue(result.transcript_path.exists())
        self.assertIsNotNone(result.model_output_path)
        self.assertTrue(result.model_output_path.exists())
        self.assertIn("Created add.py", result.model_output_path.read_text(encoding="utf-8"))

    def test_nonzero_exit_recorded_as_failed_command(self) -> None:
        out = self._run_backend(
            "transcript-success.jsonl",
            exit_code=1,
            env_overrides={"CCT_FAKE_CODEX_STDERR": "error from codex"},
        )
        result = out["result"]
        self.assertEqual(result.failed_commands, 1)
        self.assertEqual(result.backend_metadata["exit_code"], 1)
        self.assertIn("error from codex", result.backend_metadata["stderr_tail"])

    def test_zero_exit_recorded_as_no_failed_command(self) -> None:
        out = self._run_backend("transcript-success.jsonl", exit_code=0)
        self.assertEqual(out["result"].failed_commands, 0)


if __name__ == "__main__":
    unittest.main()
