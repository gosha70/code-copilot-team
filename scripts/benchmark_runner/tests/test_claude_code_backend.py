# tests/test_claude_code_backend.py — Claude Code backend tests.
#
# These tests do NOT spawn the real ``claude`` CLI. The transcript
# parser is exercised against committed fixtures, and the run() path
# is exercised against a fake CLI executable that echoes a chosen
# fixture, so we can validate end-to-end behavior (worktree-cwd,
# stdin-prompt, file output, --bare opt-in, provider env recording)
# without network or auth.

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmark_runner._register import unregister_all_for_tests
from benchmark_runner.backends.claude_code import (
    BACKEND_FAMILY,
    BARE_OPT_IN_ENV_VAR,
    GATEWAY_AUTH_TOKEN_ENV_VAR,
    GATEWAY_BASE_URL_ENV_VAR,
    ClaudeCliNotFoundError,
    ClaudeCodeBackend,
    factory,
    parse_transcript_json,
)
from benchmark_runner.contracts import Backend, RunContext


_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "claude_code"
_FAKE_CLAUDE = """#!{shebang}
# Fake `claude` for tests: echoes a chosen fixture from CCT_FAKE_CLAUDE_TRANSCRIPT,
# optionally writes to stderr from CCT_FAKE_CLAUDE_STDERR, and exits with
# CCT_FAKE_CLAUDE_EXIT_CODE (default 0). Captures argv + stdin + cwd into
# CCT_FAKE_CLAUDE_LOG for assertions.
import json, os, sys
log_path = os.environ.get("CCT_FAKE_CLAUDE_LOG", "")
fixture_path = os.environ["CCT_FAKE_CLAUDE_TRANSCRIPT"]
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
stderr_msg = os.environ.get("CCT_FAKE_CLAUDE_STDERR", "")
if stderr_msg:
    sys.stderr.write(stderr_msg)
sys.exit(int(os.environ.get("CCT_FAKE_CLAUDE_EXIT_CODE", "0")))
"""


def _install_fake_claude(tmpdir: Path) -> Path:
    """Drop a tiny Python shim called 'claude' onto a tmpdir we put on PATH."""
    bindir = tmpdir / "fake-bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text(_FAKE_CLAUDE.format(shebang=sys.executable), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake


class TestParseTranscript(unittest.TestCase):
    def test_success_transcript_yields_full_usage(self) -> None:
        stdout = (_FIXTURES / "transcript-success.json").read_text(encoding="utf-8")
        parsed = parse_transcript_json(stdout)
        self.assertIn("Gregorian rule", parsed.result_text)
        self.assertEqual(parsed.session_id, "01HV1Z00000000000000000000")
        self.assertEqual(parsed.tokens_input, 12450)
        self.assertEqual(parsed.tokens_output, 184)
        self.assertEqual(parsed.cache_read_tokens, 11200)
        self.assertEqual(parsed.cache_write_tokens, 0)  # 0 distinct from None
        self.assertEqual(parsed.tool_calls, {"Read": 2, "Edit": 1, "Bash": 1})

    def test_missing_usage_yields_none_not_zero(self) -> None:
        stdout = (_FIXTURES / "transcript-no-usage.json").read_text(encoding="utf-8")
        parsed = parse_transcript_json(stdout)
        self.assertIsNone(parsed.tokens_input)
        self.assertIsNone(parsed.tokens_output)
        self.assertIsNone(parsed.cache_read_tokens)
        self.assertIsNone(parsed.cache_write_tokens)
        self.assertEqual(parsed.tool_calls, {})

    def test_openai_shape_keys_accepted(self) -> None:
        stdout = (_FIXTURES / "transcript-openai-shape.json").read_text(encoding="utf-8")
        parsed = parse_transcript_json(stdout)
        self.assertEqual(parsed.tokens_input, 9000)
        self.assertEqual(parsed.tokens_output, 200)

    def test_empty_stdout_returns_empty_parsed(self) -> None:
        parsed = parse_transcript_json("")
        self.assertEqual(parsed.result_text, "")
        self.assertIsNone(parsed.tokens_input)
        self.assertEqual(parsed.tool_calls, {})

    def test_unparseable_stdout_returns_empty(self) -> None:
        parsed = parse_transcript_json("not JSON, not even close")
        self.assertEqual(parsed.result_text, "")
        self.assertIsNone(parsed.tokens_input)

    def test_streamjson_recovery_uses_last_object(self) -> None:
        stream = (
            '{"type":"system","subtype":"init","session_id":"x"}\n'
            '{"type":"assistant","content":"thinking..."}\n'
            '{"result":"final answer","session_id":"abc","usage":{"input_tokens":10,"output_tokens":3}}\n'
        )
        parsed = parse_transcript_json(stream)
        self.assertEqual(parsed.result_text, "final answer")
        self.assertEqual(parsed.tokens_input, 10)
        self.assertEqual(parsed.tokens_output, 3)


class TestBackendShape(unittest.TestCase):
    def setUp(self) -> None:
        unregister_all_for_tests()

    def test_satisfies_backend_protocol(self) -> None:
        self.assertIsInstance(ClaudeCodeBackend(model="sonnet"), Backend)

    def test_backend_id_is_family(self) -> None:
        self.assertEqual(ClaudeCodeBackend(model="").backend_id, BACKEND_FAMILY)

    def test_factory_carries_model(self) -> None:
        b = factory("claude-sonnet-4-6")
        self.assertEqual(b._model, "claude-sonnet-4-6")  # noqa: SLF001 (test-only)

    def test_run_raises_when_cli_missing(self) -> None:
        # Point at a guaranteed-absent executable so the early check fires.
        b = ClaudeCodeBackend(model="", cli_executable="claude-not-installed-xyz")
        ctx = RunContext(
            benchmark_id="x",
            task_id="y",
            backend_id=BACKEND_FAMILY,
            run_id="run-001",
            attempt=1,
            worktree=Path("/tmp"),
            model="",
        )
        with self.assertRaises(ClaudeCliNotFoundError):
            b.run("hello", ctx)


class TestBackendEndToEndAgainstFakeCli(unittest.TestCase):
    """Drives ClaudeCodeBackend against a fake `claude` shim.

    The shim records argv + cwd + stdin so we can assert the backend
    invokes the CLI correctly: -p, JSON output format, permission
    mode acceptEdits, allowedTools, model when given, prompt sent on
    stdin, cwd is the worktree. Default invocation should NOT include
    --bare (launcher mode); CCT_CLAUDE_BARE=1 should add it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-claude-test-")
        self._tmp_path = Path(self._tmp)
        self._fake = _install_fake_claude(self._tmp_path)
        self._invocation_log = self._tmp_path / "invocation.json"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run_backend(
        self,
        fixture_name: str,
        *,
        model: str = "sonnet",
        env_overrides: dict[str, str] | None = None,
    ) -> dict:
        worktree = self._tmp_path / "wt"
        worktree.mkdir()
        fixture_path = _FIXTURES / fixture_name
        env_overrides = dict(env_overrides or {})
        env_overrides.update({
            "CCT_FAKE_CLAUDE_TRANSCRIPT": str(fixture_path),
            "CCT_FAKE_CLAUDE_LOG": str(self._invocation_log),
        })

        backend = ClaudeCodeBackend(model=model, cli_executable=str(self._fake))
        ctx = RunContext(
            benchmark_id="x",
            task_id="t1",
            backend_id=BACKEND_FAMILY,
            run_id="run-001",
            attempt=1,
            worktree=worktree,
            model=model,
        )
        # Apply env overrides without leaking outside this test.
        old_env = {k: os.environ.get(k) for k in env_overrides}
        try:
            os.environ.update(env_overrides)
            result = backend.run("Implement leap.py", ctx)
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

    def test_default_invocation_does_not_include_bare(self) -> None:
        # Regression: launcher mode is the default — measures real
        # product behavior with autodiscovery + OAuth/keychain.
        # CCT_CLAUDE_BARE=1 is opt-in (asserted in the next test).
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(BARE_OPT_IN_ENV_VAR, None)
            out = self._run_backend("transcript-success.json", model="sonnet")
        argv = out["log"]["argv"]
        self.assertNotIn("--bare", argv)
        # Other expected flags are still present.
        self.assertIn("-p", argv)
        self.assertIn("--output-format", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertIn("--permission-mode", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")
        self.assertIn("--allowedTools", argv)
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        # Backend metadata records the chosen mode.
        self.assertEqual(
            out["result"].backend_metadata["claude_code_invocation"], "launcher"
        )

    def test_cct_claude_bare_opt_in_adds_bare_flag(self) -> None:
        out = self._run_backend(
            "transcript-success.json",
            model="sonnet",
            env_overrides={BARE_OPT_IN_ENV_VAR: "1"},
        )
        argv = out["log"]["argv"]
        self.assertIn("--bare", argv)
        self.assertEqual(
            out["result"].backend_metadata["claude_code_invocation"], "bare"
        )

    def test_prompt_sent_on_stdin(self) -> None:
        out = self._run_backend("transcript-success.json")
        self.assertIn("Implement leap.py", out["log"]["stdin"])

    def test_cwd_is_the_worktree(self) -> None:
        out = self._run_backend("transcript-success.json")
        self.assertEqual(
            Path(out["log"]["cwd"]).resolve(),
            out["worktree"].resolve(),
        )

    def test_run_persists_transcript_and_model_output(self) -> None:
        out = self._run_backend("transcript-success.json")
        result = out["result"]
        self.assertIsNotNone(result.transcript_path)
        self.assertTrue(result.transcript_path.exists())
        self.assertIsNotNone(result.model_output_path)
        self.assertTrue(result.model_output_path.exists())
        self.assertIn(
            "Gregorian rule",
            result.model_output_path.read_text(encoding="utf-8"),
        )

    def test_run_records_token_counts(self) -> None:
        out = self._run_backend("transcript-success.json")
        result = out["result"]
        self.assertEqual(result.tokens_input, 12450)
        self.assertEqual(result.tokens_output, 184)
        self.assertEqual(result.cache_read_tokens, 11200)
        self.assertEqual(result.cache_write_tokens, 0)
        self.assertEqual(
            result.tool_calls, {"Read": 2, "Edit": 1, "Bash": 1}
        )

    def test_run_metadata_includes_session_and_exit_code(self) -> None:
        out = self._run_backend("transcript-success.json")
        meta = out["result"].backend_metadata
        self.assertEqual(meta["family"], BACKEND_FAMILY)
        self.assertEqual(meta["model"], "sonnet")
        self.assertEqual(meta["session_id"], "01HV1Z00000000000000000000")
        self.assertEqual(meta["exit_code"], 0)

    def test_no_dollar_cost_in_backend_metadata(self) -> None:
        # spec.md § Constraints: cost reporting is permanently off.
        # The fixture includes total_cost_usd; the parser must NOT
        # surface it in any Phase 2/3 artifact.
        out = self._run_backend("transcript-success.json")
        meta = out["result"].backend_metadata
        self.assertNotIn("total_cost_usd", meta)
        self.assertNotIn("cost", str(meta).lower())

    def test_provider_endpoint_recorded_when_set(self) -> None:
        # The user has set ANTHROPIC_BASE_URL to a local gateway —
        # the harness must record this in backend_metadata so reports
        # can distinguish gateway-routed runs from default-Anthropic
        # runs. The harness does NOT set the env var; only records it.
        out = self._run_backend(
            "transcript-success.json",
            env_overrides={
                GATEWAY_BASE_URL_ENV_VAR: "http://localhost:8000",
                GATEWAY_AUTH_TOKEN_ENV_VAR: "secret-not-recorded",
            },
        )
        meta = out["result"].backend_metadata
        self.assertEqual(meta["provider_endpoint"], "http://localhost:8000")
        # Auth token presence is recorded as a boolean — never the value.
        self.assertTrue(meta["anthropic_auth_token_present"])
        self.assertNotIn("secret-not-recorded", str(meta))

    def test_provider_endpoint_null_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(GATEWAY_BASE_URL_ENV_VAR, None)
            os.environ.pop(GATEWAY_AUTH_TOKEN_ENV_VAR, None)
            out = self._run_backend("transcript-success.json")
        meta = out["result"].backend_metadata
        self.assertIsNone(meta["provider_endpoint"])
        self.assertFalse(meta["anthropic_auth_token_present"])

    # ── F9: full 4-state provider routing matrix ──────────────────────

    def test_provider_routing_state_url_only(self) -> None:
        # URL set, token unset — gateway with no auth (some local vLLM
        # deployments allow this).
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(GATEWAY_AUTH_TOKEN_ENV_VAR, None)
            out = self._run_backend(
                "transcript-success.json",
                env_overrides={GATEWAY_BASE_URL_ENV_VAR: "http://gw:1"},
            )
        meta = out["result"].backend_metadata
        self.assertEqual(meta["provider_endpoint"], "http://gw:1")
        self.assertFalse(meta["anthropic_auth_token_present"])

    def test_provider_routing_state_token_only(self) -> None:
        # Token set, URL unset — default Anthropic API with explicit
        # auth (rather than OAuth/keychain). Distinguishable from the
        # both-unset state.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(GATEWAY_BASE_URL_ENV_VAR, None)
            out = self._run_backend(
                "transcript-success.json",
                env_overrides={GATEWAY_AUTH_TOKEN_ENV_VAR: "redacted-value"},
            )
        meta = out["result"].backend_metadata
        self.assertIsNone(meta["provider_endpoint"])
        self.assertTrue(meta["anthropic_auth_token_present"])
        # Auth value never leaks (already covered, but locked again here).
        self.assertNotIn("redacted-value", str(meta))

    def test_provider_routing_state_both_set(self) -> None:
        # Already covered by test_provider_endpoint_recorded_when_set;
        # repeating with explicit naming so the 4-state matrix is
        # complete and grep-able as one block.
        out = self._run_backend(
            "transcript-success.json",
            env_overrides={
                GATEWAY_BASE_URL_ENV_VAR: "http://gw:2",
                GATEWAY_AUTH_TOKEN_ENV_VAR: "redacted-2",
            },
        )
        meta = out["result"].backend_metadata
        self.assertEqual(meta["provider_endpoint"], "http://gw:2")
        self.assertTrue(meta["anthropic_auth_token_present"])

    # ── F8: model-typo / unknown-model error path ─────────────────────

    def test_unknown_model_lands_as_backend_error(self) -> None:
        # Model-name validation is done by the upstream copilot, not
        # CCT — there's no whitelist. A typo lands as a non-zero exit
        # from the CLI; the harness records exit_code != 0 and the
        # stderr tail. This documents the contract: CCT does NOT
        # validate model names.
        out = self._run_backend(
            "transcript-success.json",
            model="totally-not-a-real-model-id",
            env_overrides={
                "CCT_FAKE_CLAUDE_EXIT_CODE": "1",
                "CCT_FAKE_CLAUDE_STDERR": "error: unknown model 'totally-not-a-real-model-id'",
            },
        )
        result = out["result"]
        meta = result.backend_metadata
        # Run completed but the CLI signaled failure.
        self.assertEqual(meta["exit_code"], 1)
        self.assertEqual(result.failed_commands, 1)
        # stderr is captured (truncated to 1024 chars by _tail).
        self.assertIn("unknown model", meta["stderr_tail"])
        # Model arg was passed through to argv unchanged — CCT doesn't
        # rewrite it.
        argv = out["log"]["argv"]
        self.assertIn("totally-not-a-real-model-id", argv)


class TestBackendTimeout(unittest.TestCase):
    """F10: timeout handling — high-probability real-world failure mode."""

    def test_timeout_returns_populated_result_not_crash(self) -> None:
        # Mock subprocess.run to raise TimeoutExpired. The backend
        # must return a populated BackendResult with failed_commands=1
        # and a "timed out" note in metadata, NOT crash the run.
        import subprocess as _subprocess

        backend = ClaudeCodeBackend(
            model="sonnet", cli_executable="claude"
        )

        # shutil.which gets called first; mock it to "find" the CLI.
        with mock.patch(
            "benchmark_runner.backends.claude_code.shutil.which",
            return_value="/usr/local/bin/claude",
        ), mock.patch(
            "benchmark_runner.backends.claude_code.subprocess.run",
            side_effect=_subprocess.TimeoutExpired(
                cmd=["claude"], timeout=1, output=b"", stderr=b"hung in tool loop",
            ),
        ):
            ctx = RunContext(
                benchmark_id="x",
                task_id="t1",
                backend_id=BACKEND_FAMILY,
                run_id="run-001",
                attempt=1,
                worktree=Path("/tmp"),
                model="sonnet",
                timeout_seconds=1,
            )
            result = backend.run("hi", ctx)

        self.assertEqual(result.failed_commands, 1)
        meta = result.backend_metadata
        self.assertEqual(meta["family"], BACKEND_FAMILY)
        self.assertIn("timed out", meta["note"].lower())
        self.assertIn("1s", meta["note"])  # the timeout value is mentioned
        # No transcript on timeout.
        self.assertIsNone(result.transcript_path)


if __name__ == "__main__":
    unittest.main()
