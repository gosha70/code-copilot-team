# tests/test_claude_code_judge.py — ClaudeCodeJudge tests.
#
# These tests do NOT spawn the real ``claude`` CLI. The transcript
# parser is exercised against committed fixtures, and the rate()
# path is exercised against a fake `claude` shim that echoes a
# chosen fixture. Mirrors the codex/aider/claude_code backend
# fake-CLI pattern; no network, no auth, no live LLM.
#
# Coverage:
#   - parse_judge_output (pure function): 7 fixture cases + edge cases.
#   - ClaudeCodeJudge shape: protocol conformance, factory, CLI-missing.
#   - End-to-end against the fake `claude` shim: argv contract
#     flag-by-flag, prompt via stdin, cwd = attempt_dir, env-var
#     recording, the corrected determinism contract (no --temperature,
#     no --seed; judge_invocation records null/"unsupported"),
#     defensive paths (out-of-band ratings, missing dimensions,
#     unparseable inner, timeout).

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark_runner.judge.claude_code_judge import (
    BARE_OPT_IN_ENV_VAR,
    GATEWAY_AUTH_TOKEN_ENV_VAR,
    GATEWAY_BASE_URL_ENV_VAR,
    JUDGE_BACKEND_ID,
    JUDGE_FAMILY,
    PARSE_STATUS_INNER_UNPARSEABLE,
    PARSE_STATUS_MISSING_DIMENSIONS,
    PARSE_STATUS_OK,
    PARSE_STATUS_OUTER_UNPARSEABLE,
    PARSE_STATUS_OUT_OF_BAND_RATING,
    TIMEOUT_OPT_IN_ENV_VAR,
    ClaudeCliNotFoundError,
    ClaudeCodeJudge,
    InvalidJudgeTimeoutError,
    factory,
    parse_judge_output,
)
from benchmark_runner.judge.contracts import (
    SEED_CONTROL_UNSUPPORTED,
    TEMPERATURE_CONTROL_UNSUPPORTED,
    Judge,
    JudgeInput,
    RubricSpec,
)


_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "judge"
_DIMENSIONS = (
    "idiomaticity",
    "error_handling",
    "test_thoughtfulness",
    "security_hygiene",
)

# Minimal prompt template — exercises every placeholder the judge
# substitutes. Real rubric-default-v1.md is richer; this synthetic
# template keeps the test independent of the rubric loader (TB1.3).
_TEST_PROMPT_TEMPLATE = (
    "Task: {task_id} ({benchmark_id})\n"
    "PROMPT:\n{prompt}\n"
    "DIFF:\n{diff}\n"
    "VERIFY:\n{verify_output}\n"
    "Rate four dimensions and return JSON.\n"
)


_FAKE_CLAUDE = """#!{shebang}
# Fake `claude` for judge tests: echoes a chosen fixture, captures
# argv + cwd + stdin into CCT_FAKE_CLAUDE_LOG, exits with
# CCT_FAKE_CLAUDE_EXIT_CODE (default 0).
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
sys.exit(int(os.environ.get("CCT_FAKE_CLAUDE_EXIT_CODE", "0")))
"""


def _install_fake_claude(tmpdir: Path) -> Path:
    bindir = tmpdir / "fake-bin"
    bindir.mkdir()
    fake = bindir / "claude"
    fake.write_text(_FAKE_CLAUDE.format(shebang=sys.executable), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def _make_attempt(
    tmp_path: Path,
    *,
    diff: str = "diff content\n",
    prompt: str = "Implement leap.py\n",
    verify: str = "1 passed\n",
) -> JudgeInput:
    attempt_dir = tmp_path / "attempt-01-run-001"
    attempt_dir.mkdir()
    (attempt_dir / "diff.patch").write_text(diff, encoding="utf-8")
    (attempt_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    rubric = RubricSpec(
        name="default-v1",
        dimensions=_DIMENSIONS,
        prompt_template=_TEST_PROMPT_TEMPLATE,
    )
    return JudgeInput(
        attempt_dir=attempt_dir,
        task_id="python/leap",
        benchmark_id="aider-polyglot",
        diff_path=attempt_dir / "diff.patch",
        prompt_path=attempt_dir / "prompt.md",
        verify_output=verify,
        rubric=rubric,
    )


# ── Parser unit tests ─────────────────────────────────────────────────


class TestParseJudgeOutput(unittest.TestCase):
    def test_success_yields_full_ratings_and_usage(self) -> None:
        stdout = (_FIXTURES / "transcript-success.json").read_text(encoding="utf-8")
        p = parse_judge_output(stdout, _DIMENSIONS)
        self.assertEqual(p.status, PARSE_STATUS_OK)
        self.assertEqual(set(p.ratings.keys()), set(_DIMENSIONS))
        self.assertEqual(p.ratings["idiomaticity"]["rating"], 4)
        self.assertEqual(p.ratings["error_handling"]["rating"], 3)
        self.assertEqual(p.ratings["test_thoughtfulness"]["rating"], 2)
        self.assertEqual(p.ratings["security_hygiene"]["rating"], 4)
        self.assertEqual(p.tokens_input, 3200)
        self.assertEqual(p.tokens_output, 480)
        self.assertEqual(p.session_id, "01HV1JUDGE0000000000000000")

    def test_null_dim_preserved_as_null(self) -> None:
        stdout = (_FIXTURES / "transcript-null-dim.json").read_text(encoding="utf-8")
        p = parse_judge_output(stdout, _DIMENSIONS)
        self.assertEqual(p.status, PARSE_STATUS_OK)
        self.assertIsNone(p.ratings["test_thoughtfulness"]["rating"])
        self.assertIsNone(p.ratings["security_hygiene"]["rating"])
        self.assertEqual(p.ratings["idiomaticity"]["rating"], 3)

    def test_out_of_band_flagged(self) -> None:
        stdout = (_FIXTURES / "transcript-out-of-band.json").read_text(encoding="utf-8")
        p = parse_judge_output(stdout, _DIMENSIONS)
        self.assertEqual(p.status, PARSE_STATUS_OUT_OF_BAND_RATING)
        self.assertIn("idiomaticity", p.note)
        self.assertIn("error_handling", p.note)
        # Parser preserves the raw values; the judge's per-dim
        # builder downgrades them to null.
        self.assertEqual(p.ratings["idiomaticity"]["rating"], 6)
        self.assertEqual(p.ratings["error_handling"]["rating"], 0)

    def test_missing_dim_flagged(self) -> None:
        stdout = (_FIXTURES / "transcript-missing-dim.json").read_text(encoding="utf-8")
        p = parse_judge_output(stdout, _DIMENSIONS)
        self.assertEqual(p.status, PARSE_STATUS_MISSING_DIMENSIONS)
        self.assertIn("test_thoughtfulness", p.note)
        self.assertIn("security_hygiene", p.note)
        # Present dims still recorded.
        self.assertEqual(p.ratings["idiomaticity"]["rating"], 4)

    def test_unparseable_inner_flagged(self) -> None:
        stdout = (_FIXTURES / "transcript-unparseable-inner.json").read_text(
            encoding="utf-8"
        )
        p = parse_judge_output(stdout, _DIMENSIONS)
        self.assertEqual(p.status, PARSE_STATUS_INNER_UNPARSEABLE)
        self.assertEqual(p.ratings, {})

    def test_empty_stdout_flagged(self) -> None:
        p = parse_judge_output("", _DIMENSIONS)
        self.assertEqual(p.status, PARSE_STATUS_OUTER_UNPARSEABLE)
        self.assertIsNone(p.tokens_input)

    def test_outer_unparseable_flagged(self) -> None:
        p = parse_judge_output("not JSON at all", _DIMENSIONS)
        self.assertEqual(p.status, PARSE_STATUS_OUTER_UNPARSEABLE)

    def test_no_usage_block_yields_none_tokens(self) -> None:
        stdout = (_FIXTURES / "transcript-no-usage.json").read_text(encoding="utf-8")
        p = parse_judge_output(stdout, _DIMENSIONS)
        self.assertEqual(p.status, PARSE_STATUS_OK)
        # Mirrors the backend's null-vs-zero discipline: missing usage
        # block → None, never coerced to 0.
        self.assertIsNone(p.tokens_input)
        self.assertIsNone(p.tokens_output)


# ── Judge shape tests ─────────────────────────────────────────────────


class TestJudgeShape(unittest.TestCase):
    def test_satisfies_judge_protocol(self) -> None:
        self.assertIsInstance(ClaudeCodeJudge(model="sonnet"), Judge)

    def test_judge_id_is_family(self) -> None:
        self.assertEqual(ClaudeCodeJudge().judge_id, JUDGE_FAMILY)

    def test_factory_carries_model(self) -> None:
        j = factory("claude-sonnet-4-6")
        self.assertEqual(j._model, "claude-sonnet-4-6")  # noqa: SLF001 (test-only)

    def test_rate_raises_when_cli_missing(self) -> None:
        j = ClaudeCodeJudge(model="", cli_executable="claude-not-installed-xyz")
        tmp = tempfile.mkdtemp(prefix="cct-judge-test-")
        try:
            attempt = _make_attempt(Path(tmp))
            with self.assertRaises(ClaudeCliNotFoundError):
                j.rate(attempt)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── End-to-end via fake claude shim ───────────────────────────────────


class TestJudgeEndToEndAgainstFakeCli(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-judge-test-")
        self._tmp_path = Path(self._tmp)
        self._fake = _install_fake_claude(self._tmp_path)
        self._invocation_log = self._tmp_path / "invocation.json"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _rate(
        self,
        fixture_name: str,
        *,
        model: str = "sonnet",
        env_overrides: dict[str, str] | None = None,
    ) -> dict:
        attempt = _make_attempt(self._tmp_path)
        fixture_path = _FIXTURES / fixture_name
        overrides = dict(env_overrides or {})
        overrides.update({
            "CCT_FAKE_CLAUDE_TRANSCRIPT": str(fixture_path),
            "CCT_FAKE_CLAUDE_LOG": str(self._invocation_log),
        })
        judge = ClaudeCodeJudge(model=model, cli_executable=str(self._fake))
        old_env = {k: os.environ.get(k) for k in overrides}
        try:
            os.environ.update(overrides)
            result = judge.rate(attempt)
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return {
            "result": result,
            "log": json.loads(self._invocation_log.read_text(encoding="utf-8")),
            "attempt": attempt,
        }

    # ── Argv contract ──────────────────────────────────────────────

    def test_argv_contract_flag_by_flag(self) -> None:
        out = self._rate("transcript-success.json")
        argv = out["log"]["argv"]
        # The CLI binary name is fake-bin/claude — argv[0] is the
        # full path; assert it ends with /claude rather than equals.
        self.assertTrue(argv[0].endswith("/claude"))
        self.assertIn("-p", argv)
        # Output format JSON for the wrapper.
        self.assertIn("--output-format", argv)
        ofmt_idx = argv.index("--output-format")
        self.assertEqual(argv[ofmt_idx + 1], "json")
        # Tools disabled — judge produces a rating, not file edits.
        # ``--tools ""`` is the documented disable per ``claude --help``;
        # ``--allowedTools`` is a different surface (which tools are
        # permitted, not which are available) and is deliberately NOT
        # used here. Peer review 2026-05-20.
        self.assertIn("--tools", argv)
        tools_idx = argv.index("--tools")
        self.assertEqual(argv[tools_idx + 1], "")
        self.assertNotIn("--allowedTools", argv)
        self.assertNotIn("--allowed-tools", argv)
        # Model passed through when set.
        self.assertIn("--model", argv)
        model_idx = argv.index("--model")
        self.assertEqual(argv[model_idx + 1], "sonnet")
        # Launcher mode by default — no --bare unless opted in.
        self.assertNotIn("--bare", argv)

    def test_no_temperature_or_seed_flags_in_argv(self) -> None:
        # Determinism contract: the CLI exposes neither knob, and the
        # judge MUST NOT pretend to pass them. Catching this as an
        # explicit test so a future contributor who adds the flag back
        # has to update this test deliberately.
        out = self._rate("transcript-success.json")
        argv = out["log"]["argv"]
        self.assertNotIn("--temperature", argv)
        self.assertNotIn("--seed", argv)
        # Also no --permission-mode — judge edits nothing.
        self.assertNotIn("--permission-mode", argv)

    def test_no_model_flag_when_model_empty(self) -> None:
        out = self._rate("transcript-success.json", model="")
        argv = out["log"]["argv"]
        self.assertNotIn("--model", argv)

    def test_bare_flag_added_under_env_opt_in(self) -> None:
        out = self._rate(
            "transcript-success.json",
            env_overrides={BARE_OPT_IN_ENV_VAR: "1"},
        )
        self.assertIn("--bare", out["log"]["argv"])
        # And recorded in metadata.
        self.assertEqual(
            out["result"].judge_metadata["claude_code_invocation"], "bare"
        )

    def test_launcher_is_default_metadata(self) -> None:
        out = self._rate("transcript-success.json")
        self.assertEqual(
            out["result"].judge_metadata["claude_code_invocation"], "launcher"
        )

    # ── Prompt + cwd ──────────────────────────────────────────────

    def test_prompt_sent_on_stdin_with_substitutions(self) -> None:
        out = self._rate("transcript-success.json")
        stdin = out["log"]["stdin"]
        # All five substitutions present.
        self.assertIn("python/leap", stdin)
        self.assertIn("aider-polyglot", stdin)
        self.assertIn("Implement leap.py", stdin)  # prompt
        self.assertIn("diff content", stdin)       # diff
        self.assertIn("1 passed", stdin)           # verify_output

    def test_cwd_is_attempt_dir(self) -> None:
        out = self._rate("transcript-success.json")
        # ``os.getcwd()`` returns a resolved path; on macOS
        # ``/var/folders/...`` resolves to ``/private/var/folders/...``.
        # Compare resolved paths so the test isn't platform-fragile.
        self.assertEqual(
            Path(out["log"]["cwd"]).resolve(),
            out["attempt"].attempt_dir.resolve(),
        )

    # ── Determinism contract on the result ──────────────────────────

    def test_judge_invocation_records_unsupported_determinism(self) -> None:
        # THE peer-reviewed correction: temperature/seed null +
        # control "unsupported", never silent 0.0.
        out = self._rate("transcript-success.json")
        inv = out["result"].invocation
        self.assertIsNone(inv.temperature)
        self.assertIsNone(inv.seed)
        self.assertEqual(inv.temperature_control, TEMPERATURE_CONTROL_UNSUPPORTED)
        self.assertEqual(inv.seed_control, SEED_CONTROL_UNSUPPORTED)

    def test_judge_metadata_contains_no_secrets(self) -> None:
        out = self._rate(
            "transcript-success.json",
            env_overrides={GATEWAY_AUTH_TOKEN_ENV_VAR: "sk-test-redacted"},
        )
        meta_str = str(dict(out["result"].judge_metadata))
        inv_str = str(out["result"].invocation)
        # Token value must not appear anywhere on the result.
        self.assertNotIn("sk-test-redacted", meta_str)
        self.assertNotIn("sk-test-redacted", inv_str)
        # And no "Bearer " prefix either.
        self.assertNotIn("Bearer ", meta_str)
        self.assertNotIn("Bearer ", inv_str)

    def test_provider_endpoint_recorded_as_boolean(self) -> None:
        # Presence recorded; URL never recorded.
        out = self._rate(
            "transcript-success.json",
            env_overrides={GATEWAY_BASE_URL_ENV_VAR: "http://127.0.0.1:8787"},
        )
        inv = out["result"].invocation
        self.assertIs(inv.provider_endpoint_present, True)
        meta_str = str(dict(out["result"].judge_metadata))
        inv_str = str(inv)
        self.assertNotIn("127.0.0.1", meta_str)
        self.assertNotIn("127.0.0.1", inv_str)

    def test_provider_endpoint_false_when_unset(self) -> None:
        # Make sure the env var isn't leaking from the host.
        out = self._rate(
            "transcript-success.json",
            env_overrides={GATEWAY_BASE_URL_ENV_VAR: ""},
        )
        self.assertIs(out["result"].invocation.provider_endpoint_present, False)

    # ── Result shape ──────────────────────────────────────────────

    def test_result_carries_all_dimensions(self) -> None:
        out = self._rate("transcript-success.json")
        ratings = out["result"].ratings
        self.assertEqual(set(ratings.keys()), set(_DIMENSIONS))
        self.assertEqual(ratings["idiomaticity"].rating, 4)
        self.assertEqual(ratings["security_hygiene"].rating, 4)

    def test_result_tokens_passed_through(self) -> None:
        out = self._rate("transcript-success.json")
        self.assertEqual(out["result"].tokens_input, 3200)
        self.assertEqual(out["result"].tokens_output, 480)

    def test_result_rubric_name_passed_through(self) -> None:
        out = self._rate("transcript-success.json")
        self.assertEqual(out["result"].rubric_name, "default-v1")

    def test_result_judge_ids(self) -> None:
        out = self._rate("transcript-success.json")
        self.assertEqual(out["result"].judge_id, JUDGE_FAMILY)
        self.assertEqual(out["result"].judge_backend_id, JUDGE_BACKEND_ID)
        self.assertEqual(out["result"].judge_model, "sonnet")

    def test_prompt_sha256_consistent_across_dimensions(self) -> None:
        # v1: one combined prompt per attempt → every dimension's
        # rating carries the same prompt_sha256.
        out = self._rate("transcript-success.json")
        shas = {r.prompt_sha256 for r in out["result"].ratings.values()}
        self.assertEqual(len(shas), 1)
        self.assertEqual(len(next(iter(shas))), 64)  # sha256 hex

    # ── Defensive paths ───────────────────────────────────────────

    def test_null_dim_passes_through_to_result(self) -> None:
        out = self._rate("transcript-null-dim.json")
        ratings = out["result"].ratings
        self.assertIsNone(ratings["test_thoughtfulness"].rating)
        self.assertIn("forbid", ratings["test_thoughtfulness"].explanation.lower())
        self.assertIsNone(ratings["security_hygiene"].rating)

    def test_out_of_band_downgraded_to_null_with_explanation(self) -> None:
        # The contract dataclass would reject rating=6 or rating=0.
        # The judge catches and substitutes null + explanation so
        # one bad rating from the LLM doesn't crash the whole call.
        out = self._rate("transcript-out-of-band.json")
        ratings = out["result"].ratings
        self.assertIsNone(ratings["idiomaticity"].rating)
        self.assertIn("out-of-band", ratings["idiomaticity"].explanation)
        self.assertIn("6", ratings["idiomaticity"].explanation)
        self.assertIsNone(ratings["error_handling"].rating)
        self.assertIn("0", ratings["error_handling"].explanation)
        # In-band ratings still come through.
        self.assertEqual(ratings["test_thoughtfulness"].rating, 3)
        self.assertEqual(ratings["security_hygiene"].rating, 4)
        # parse_status flags the anomaly.
        self.assertEqual(
            out["result"].judge_metadata["parse_status"],
            PARSE_STATUS_OUT_OF_BAND_RATING,
        )

    def test_missing_dim_recorded_as_null_with_diagnostic(self) -> None:
        out = self._rate("transcript-missing-dim.json")
        ratings = out["result"].ratings
        self.assertIsNone(ratings["test_thoughtfulness"].rating)
        self.assertIn("missing", ratings["test_thoughtfulness"].explanation)
        self.assertEqual(
            out["result"].judge_metadata["parse_status"],
            PARSE_STATUS_MISSING_DIMENSIONS,
        )

    def test_unparseable_inner_all_null_with_status(self) -> None:
        out = self._rate("transcript-unparseable-inner.json")
        ratings = out["result"].ratings
        for dim in _DIMENSIONS:
            self.assertIsNone(ratings[dim].rating)
        self.assertEqual(
            out["result"].judge_metadata["parse_status"],
            PARSE_STATUS_INNER_UNPARSEABLE,
        )

    def test_nonzero_exit_recorded(self) -> None:
        out = self._rate(
            "transcript-success.json",
            env_overrides={"CCT_FAKE_CLAUDE_EXIT_CODE": "1"},
        )
        self.assertEqual(out["result"].judge_metadata["exit_code"], 1)


# ── Env-var override validation ───────────────────────────────────────


class TestTimeoutOverride(unittest.TestCase):
    """``CCT_JUDGE_TIMEOUT_SECONDS`` must fail loud on bad values.

    Silently dropping a typo would mask a configuration error and
    let calibration use the wrong budget.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-judge-test-")
        self._fake = _install_fake_claude(Path(self._tmp))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _rate_with_timeout(self, value: str) -> None:
        attempt = _make_attempt(Path(self._tmp))
        judge = ClaudeCodeJudge(model="sonnet", cli_executable=str(self._fake))
        old = os.environ.get(TIMEOUT_OPT_IN_ENV_VAR)
        try:
            os.environ[TIMEOUT_OPT_IN_ENV_VAR] = value
            os.environ["CCT_FAKE_CLAUDE_TRANSCRIPT"] = str(
                _FIXTURES / "transcript-success.json"
            )
            judge.rate(attempt)
        finally:
            if old is None:
                os.environ.pop(TIMEOUT_OPT_IN_ENV_VAR, None)
            else:
                os.environ[TIMEOUT_OPT_IN_ENV_VAR] = old
            os.environ.pop("CCT_FAKE_CLAUDE_TRANSCRIPT", None)

    def test_non_integer_raises(self) -> None:
        with self.assertRaises(InvalidJudgeTimeoutError):
            self._rate_with_timeout("not-a-number")

    def test_zero_raises(self) -> None:
        with self.assertRaises(InvalidJudgeTimeoutError):
            self._rate_with_timeout("0")

    def test_negative_raises(self) -> None:
        with self.assertRaises(InvalidJudgeTimeoutError):
            self._rate_with_timeout("-10")


if __name__ == "__main__":
    unittest.main()
