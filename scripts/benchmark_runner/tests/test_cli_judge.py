# tests/test_cli_judge.py — CLI 'judge' subcommand wiring tests.
#
# Argument parsing + dispatch + error paths only. The judge runner
# and rubric loader have their own dedicated test modules; this
# module just verifies the CLI handler routes through them with the
# right error semantics.
#
# End-to-end through the real ``claude`` CLI is out of scope (no
# live LLM in CI). The handler is tested by running the CLI against
# a synthetic run-dir + a monkeypatched judge factory that returns a
# stub.

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from benchmark_runner.cli import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE, main
from benchmark_runner.judge.contracts import (
    DimensionRating,
    JudgeInput,
    JudgeInvocation,
    JudgeResult,
)


class _CannedJudge:
    judge_id = "canned-judge"

    def rate(self, attempt: JudgeInput) -> JudgeResult:
        return JudgeResult(
            judge_id=self.judge_id,
            judge_model="canned",
            judge_backend_id="canned",
            rubric_name=attempt.rubric.name,
            ratings={
                dim: DimensionRating(
                    rating=3,
                    explanation="canned",
                    prompt_sha256="canned",
                )
                for dim in attempt.rubric.dimensions
            },
            invocation=JudgeInvocation(model="canned"),
        )


def _make_run_dir(tmp: Path) -> Path:
    run_dir = tmp / "20260520T000000Z-aider-polyglot-claude-code-001"
    run_dir.mkdir()
    attempt_dir = run_dir / "python-bowling" / "attempt-01-run-001"
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "score.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "benchmark_id": "aider-polyglot",
            "task_id": "python/bowling",
            "result": "fail",
        }) + "\n",
        encoding="utf-8",
    )
    (attempt_dir / "diff.patch").write_text("diff\n", encoding="utf-8")
    (attempt_dir / "prompt.md").write_text("prompt\n", encoding="utf-8")
    (attempt_dir / "verify-output.txt").write_text("ok\n", encoding="utf-8")
    return run_dir


class TestCliJudge(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-cli-judge-test-")
        self.tmpdir = Path(self._tmp)
        self.run_dir = _make_run_dir(self.tmpdir)
        # Call register_all() in setUp so mock.patch.dict can override
        # already-registered entries inside individual tests. Without
        # this, register_all() running inside the with-block would see
        # a registry pre-populated by mock.patch.dict and raise
        # "different factory" on the canonical token — TB1.5 registry
        # contract is strict about same-key/different-factory
        # collisions (test_different_factories_under_same_token_raises).
        from benchmark_runner._register import register_all
        register_all()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _invoke(self, *argv: str) -> tuple[int, str, str]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    # ── error paths (no monkeypatch needed) ─────────────────────────

    def test_run_dir_missing_returns_usage_error(self) -> None:
        code, _, err = self._invoke(
            "judge",
            "--run-dir", str(self.tmpdir / "does-not-exist"),
            "--judge", "claude-code:sonnet",
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("run-dir not found", err)

    def test_judge_arg_without_colon_returns_usage_error(self) -> None:
        code, _, err = self._invoke(
            "judge",
            "--run-dir", str(self.run_dir),
            "--judge", "claude-code",
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("<family>:<model>", err)

    def test_unknown_judge_family_returns_usage_error(self) -> None:
        code, _, err = self._invoke(
            "judge",
            "--run-dir", str(self.run_dir),
            "--judge", "totally-fake-judge:sonnet",
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("unknown judge family", err)

    def test_unknown_rubric_returns_usage_error(self) -> None:
        # The default rubric (default-v1) is on disk and loadable;
        # request a non-existent one.
        code, _, err = self._invoke(
            "judge",
            "--run-dir", str(self.run_dir),
            "--judge", "claude-code-judge:sonnet",
            "--rubric", "does-not-exist",
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("rubric-does-not-exist.md", err)

    # ── happy path with monkeypatched factory ─────────────────────

    def test_happy_path_invokes_runner_and_prints_summary(self) -> None:
        # The SDD-canonical CLI surface is `claude-code:sonnet`
        # (spec.md scenarios + Interface section). Monkeypatch the
        # factory to return a stub so the test doesn't need the real
        # `claude` CLI in CI.
        with mock.patch.dict(
            "benchmark_runner.judge.registry._JUDGES",
            {
                "claude-code": lambda model: _CannedJudge(),
                "claude-code-judge": lambda model: _CannedJudge(),
            },
        ):
            code, out, err = self._invoke(
                "judge",
                "--run-dir", str(self.run_dir),
                "--judge", "claude-code:sonnet",
            )
        self.assertEqual(code, EXIT_OK, msg=f"stderr: {err}")
        payload = json.loads(out)
        self.assertEqual(payload["attempts_processed"], 1)
        self.assertEqual(payload["attempts_skipped"], 0)
        self.assertEqual(payload["attempts_failed"], 0)
        self.assertEqual(payload["judge"], "claude-code:sonnet")
        self.assertEqual(payload["rubric"], "default-v1")
        # judge.json was actually written.
        produced = self.run_dir / "python-bowling" / "attempt-01-run-001" / "judge.json"
        self.assertTrue(produced.exists())

    def test_claude_code_judge_alias_also_accepted(self) -> None:
        # ``claude-code-judge`` is the internal judge_id (recorded in
        # judge.json's ``judge_id`` field). Accepting it as a CLI
        # alias for ``claude-code`` lets a user copy that value
        # verbatim into a re-run command without translation.
        with mock.patch.dict(
            "benchmark_runner.judge.registry._JUDGES",
            {
                "claude-code": lambda model: _CannedJudge(),
                "claude-code-judge": lambda model: _CannedJudge(),
            },
        ):
            code, out, err = self._invoke(
                "judge",
                "--run-dir", str(self.run_dir),
                "--judge", "claude-code-judge:sonnet",
            )
        self.assertEqual(code, EXIT_OK, msg=f"stderr: {err}")
        payload = json.loads(out)
        # Echoed as the user typed it (preserve their intent for log
        # readability), not normalized to the canonical family.
        self.assertEqual(payload["judge"], "claude-code-judge:sonnet")
        self.assertEqual(payload["attempts_processed"], 1)

    def test_runtime_error_on_score_mutation(self) -> None:
        # A judge that mutates score.json must surface as EXIT_RUNTIME
        # (not a silent success) — the additivity invariant is
        # load-bearing and the CLI is the user-facing gate that
        # surfaces the violation.

        class _MutatingJudge:
            judge_id = "mutating-judge"

            def rate(self, attempt: JudgeInput) -> JudgeResult:
                (attempt.attempt_dir / "score.json").write_text(
                    "MUTATED\n", encoding="utf-8"
                )
                return _CannedJudge().rate(attempt)

        with mock.patch.dict(
            "benchmark_runner.judge.registry._JUDGES",
            {"claude-code": lambda model: _MutatingJudge()},
        ):
            code, _, err = self._invoke(
                "judge",
                "--run-dir", str(self.run_dir),
                "--judge", "claude-code:sonnet",
            )
        self.assertEqual(code, EXIT_RUNTIME)
        self.assertIn("mutated", err.lower())


if __name__ == "__main__":
    unittest.main()
