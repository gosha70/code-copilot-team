# tests/test_aider_backend.py — Aider backend tests.
#
# These tests do NOT spawn the real ``aider`` CLI. The transcript parser
# is exercised against committed fixtures, and the run() path is exercised
# against a fake CLI shim that echoes a chosen fixture + logs argv/message_file
# contents/cwd, so we can validate end-to-end behavior without network or auth.
#
# The fake shim pattern mirrors test_codex_backend.py exactly, adapted for
# aider's --message-file delivery (not stdin).
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
from unittest import mock

from benchmark_runner._register import unregister_all_for_tests
from benchmark_runner.backends.aider import (
    BACKEND_FAMILY,
    AiderBackend,
    AiderCliNotFoundError,
    _parse_transcript,
    factory,
)
from benchmark_runner.contracts import Backend, RunContext


_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "aider"

# Fake ``aider`` shim:
# - reads CCT_FAKE_AIDER_TRANSCRIPT and writes its contents to stdout;
# - reads the file passed after --message-file (the prompt) and logs it;
# - logs JSON {argv, cwd, message_file, env_keys} to CCT_FAKE_AIDER_LOG;
# - optionally writes a fake aider.chat.history.md after --chat-history-file;
# - emits CCT_FAKE_AIDER_STDERR to stderr if set;
# - exits CCT_FAKE_AIDER_EXIT_CODE (default 0).
_FAKE_AIDER = """#!{shebang}
import json, os, sys
from pathlib import Path

log_path = os.environ.get("CCT_FAKE_AIDER_LOG", "")
fixture_path = os.environ["CCT_FAKE_AIDER_TRANSCRIPT"]

argv = sys.argv

# Extract --message-file argument and read the prompt from it.
message_file_contents = ""
for i, arg in enumerate(argv):
    if arg == "--message-file" and i + 1 < len(argv):
        mf = argv[i + 1]
        try:
            with open(mf, "r", encoding="utf-8") as f:
                message_file_contents = f.read()
        except OSError:
            message_file_contents = "<could not read>"
        break

# Optionally write a fake chat history file after --chat-history-file.
for i, arg in enumerate(argv):
    if arg == "--chat-history-file" and i + 1 < len(argv):
        chat_hist_path = argv[i + 1]
        try:
            with open(chat_hist_path, "w", encoding="utf-8") as f:
                f.write("# Aider chat history\\n\\nfake history entry\\n")
        except OSError:
            pass
        break

if log_path:
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({{
            "argv": argv,
            "cwd": os.getcwd(),
            "message_file": message_file_contents,
            "env_keys": sorted(os.environ.keys()),
        }}, f)

with open(fixture_path, "r", encoding="utf-8") as src:
    sys.stdout.write(src.read())

# Simulate real aider's worktree-pollution behavior: in a non-git dir,
# real aider creates a .git/ repo AND writes ``.aider*`` to .gitignore
# (B3 capture proved --no-gitignore alone does NOT suppress this; only
# --no-git does). The shim mimics that: if --no-git is NOT present in
# argv, attempt to create .git/ + .gitignore in cwd. The pinned argv
# passes --no-git, so a correctly-built backend keeps the worktree
# clean; a regression that drops --no-git would have the shim pollute
# the worktree and the cleanliness test would fail.
if "--no-git" not in argv:
    try:
        Path(".git").mkdir(exist_ok=True)
        (Path(".git") / "HEAD").write_text("ref: refs/heads/main\\n")
    except OSError:
        pass
    try:
        gi = Path(".gitignore")
        existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if ".aider" not in existing:
            gi.write_text(existing + ".aider*\\n", encoding="utf-8")
    except OSError:
        pass

stderr_msg = os.environ.get("CCT_FAKE_AIDER_STDERR", "")
if stderr_msg:
    sys.stderr.write(stderr_msg)

sys.exit(int(os.environ.get("CCT_FAKE_AIDER_EXIT_CODE", "0")))
"""


def _install_fake_aider(tmpdir: Path) -> Path:
    """Install a tiny Python shim called 'aider' on a tmpdir we put on PATH."""
    bindir = tmpdir / "fake-bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "aider"
    fake.write_text(_FAKE_AIDER.format(shebang=sys.executable), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake


class TestParseTranscript(unittest.TestCase):
    def test_success_transcript_yields_tokens_and_edit_format(self) -> None:
        # Fixture is the B3-recorded aider 0.86.2 transcript (under --no-git).
        # Tokens: `2.7k sent, 73 received.` → 2700 / 73. Edit format parsed
        # from the substring `with diff edit format` of the `Model:` line.
        # Repo-map line is `disabled` (the --no-git posture) → None.
        stdout = (_FIXTURES / "transcript-success.txt").read_text(encoding="utf-8")
        parsed = _parse_transcript(stdout)
        self.assertEqual(parsed.tokens_input, 2700)
        self.assertEqual(parsed.tokens_output, 73)
        self.assertEqual(parsed.edit_format_resolved, "diff")
        self.assertIsNone(parsed.map_tokens_effective)

    def test_map_tokens_using_n_form_parses(self) -> None:
        # When repo-map IS active (e.g. running WITHOUT --no-git, as Aider's
        # leaderboard does), the line is `Repo-map: using <N> tokens, …`.
        # Regression guard: the regex still handles this form even though our
        # pinned argv (and the success fixture) yields `Repo-map: disabled`.
        parsed = _parse_transcript(
            "Model: x with diff edit format\n"
            "Repo-map: using 4,096 tokens, auto refresh\n"
            "Tokens: 1.2M sent, 2,345 received.\n"
        )
        self.assertEqual(parsed.map_tokens_effective, 4096)
        self.assertEqual(parsed.tokens_input, 1_200_000)
        self.assertEqual(parsed.tokens_output, 2345)

    def test_no_summary_yields_none_not_zero(self) -> None:
        stdout = (_FIXTURES / "transcript-no-summary.txt").read_text(encoding="utf-8")
        parsed = _parse_transcript(stdout)
        self.assertIsNone(parsed.tokens_input)
        self.assertIsNone(parsed.tokens_output)

    def test_zero_tokens_yields_zero_not_none(self) -> None:
        # 0 in the line means 0, not None — the distinction is the key assertion.
        stdout = (_FIXTURES / "transcript-zero-tokens.txt").read_text(encoding="utf-8")
        parsed = _parse_transcript(stdout)
        self.assertIsNotNone(parsed.tokens_input)
        self.assertIsNotNone(parsed.tokens_output)
        self.assertEqual(parsed.tokens_input, 0)
        self.assertEqual(parsed.tokens_output, 0)

    def test_empty_stdout_returns_all_none(self) -> None:
        parsed = _parse_transcript("")
        self.assertIsNone(parsed.tokens_input)
        self.assertIsNone(parsed.tokens_output)
        self.assertIsNone(parsed.edit_format_resolved)
        self.assertIsNone(parsed.map_tokens_effective)

    def test_garbage_lines_tolerated_no_exception(self) -> None:
        stdout = (
            "not a tokens line\n"
            "random garbage: foo bar\n"
            "Tokens: 5 sent, 3 received.\n"
        )
        parsed = _parse_transcript(stdout)
        self.assertEqual(parsed.tokens_input, 5)
        self.assertEqual(parsed.tokens_output, 3)


class TestBackendShape(unittest.TestCase):
    def setUp(self) -> None:
        unregister_all_for_tests()

    def test_satisfies_backend_protocol(self) -> None:
        self.assertIsInstance(AiderBackend("m"), Backend)

    def test_backend_id_is_family(self) -> None:
        self.assertEqual(AiderBackend(model="").backend_id, BACKEND_FAMILY)

    def test_factory_carries_model(self) -> None:
        b = factory("claude-3-5-sonnet-20241022")
        self.assertEqual(b._model, "claude-3-5-sonnet-20241022")  # noqa: SLF001

    def test_run_raises_when_cli_missing(self) -> None:
        b = AiderBackend(model="")
        ctx = RunContext(
            benchmark_id="x",
            task_id="y",
            backend_id=BACKEND_FAMILY,
            run_id="run-001",
            attempt=1,
            worktree=Path("/tmp"),
            model="",
        )
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaises(AiderCliNotFoundError):
                b.run("hello", ctx)


class TestBackendEndToEndAgainstFakeCli(unittest.TestCase):
    """Drives AiderBackend against a fake ``aider`` shim.

    Asserts the backend invokes the CLI with the verified argv:
      aider [--model <model>]
            --yes-always
            --no-auto-commits --no-dirty-commits --no-gitignore
            --no-check-update --no-stream
            --chat-history-file <attempt_dir>/aider.chat.history.md
            --llm-history-file  <attempt_dir>/aider.llm.history.txt
            [--edit-format <fmt>]
            --message-file <attempt_dir>/aider-message.txt
    with prompt delivered via message file, cwd = worktree.
    No live CLI/network.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-aider-test-")
        self._tmp_path = Path(self._tmp)
        self._fake = _install_fake_aider(self._tmp_path)
        self._invocation_log = self._tmp_path / "invocation.json"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _run_backend(
        self,
        fixture_name: str,
        *,
        model: str = "claude-3-5-sonnet-20241022",
        env_overrides: dict[str, str] | None = None,
        exit_code: int = 0,
    ) -> dict:
        # attempt_dir/worktree/ mirrors the real harness layout.
        # worktree.parent == attempt_dir; message/history files go there.
        attempt_dir = self._tmp_path / "attempt"
        attempt_dir.mkdir(exist_ok=True)
        worktree = attempt_dir / "worktree"
        worktree.mkdir(exist_ok=True)
        fixture_path = _FIXTURES / fixture_name

        env_overrides = dict(env_overrides or {})
        env_overrides.update({
            "CCT_FAKE_AIDER_TRANSCRIPT": str(fixture_path),
            "CCT_FAKE_AIDER_LOG": str(self._invocation_log),
            "CCT_FAKE_AIDER_EXIT_CODE": str(exit_code),
        })

        backend = AiderBackend(model=model)
        # Patch shutil.which so the backend's PATH check resolves to our fake.
        # Also inject the fake-bin directory at the front of PATH so the
        # subprocess itself resolves to our shim.
        fake_bin = str(self._fake.parent)
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
        old_path = os.environ.get("PATH", "")
        try:
            os.environ.update(env_overrides)
            os.environ["PATH"] = fake_bin + os.pathsep + old_path
            result = backend.run("Write add.py", ctx)
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            os.environ["PATH"] = old_path

        log = json.loads(self._invocation_log.read_text(encoding="utf-8"))
        return {
            "result": result,
            "log": log,
            "worktree": worktree,
            "attempt_dir": attempt_dir,
        }

    # ── Argv assertions ─────────────────────────────────────────────────

    def test_argv_contains_aider(self) -> None:
        out = self._run_backend("transcript-success.txt")
        argv = out["log"]["argv"]
        # argv[0] is the shim path; the basename must be "aider".
        self.assertIn("aider", Path(argv[0]).name)

    def test_yes_always_present(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertIn("--yes-always", out["log"]["argv"])

    def test_yes_not_present(self) -> None:
        # --yes does not exist; the flag is --yes-always (B0-confirmed).
        out = self._run_backend("transcript-success.txt")
        self.assertNotIn("--yes", out["log"]["argv"])

    def test_temperature_not_present(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertNotIn("--temperature", out["log"]["argv"])

    def test_map_tokens_not_present(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertNotIn("--map-tokens", out["log"]["argv"])

    def test_no_git_present(self) -> None:
        # B3 contract: --no-git prevents aider from creating .git/ in a
        # non-git worktree (the fake-shim simulates that pollution; this
        # flag stops it; the worktree-cleanliness test verifies the effect).
        out = self._run_backend("transcript-success.txt")
        self.assertIn("--no-git", out["log"]["argv"])

    def test_model_flag_present_when_model_nonempty(self) -> None:
        out = self._run_backend("transcript-success.txt", model="claude-3-5-sonnet-20241022")
        argv = out["log"]["argv"]
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "claude-3-5-sonnet-20241022")

    def test_model_flag_absent_when_model_empty(self) -> None:
        out = self._run_backend("transcript-success.txt", model="")
        self.assertNotIn("--model", out["log"]["argv"])

    def test_no_auto_commits_present(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertIn("--no-auto-commits", out["log"]["argv"])

    def test_no_dirty_commits_present(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertIn("--no-dirty-commits", out["log"]["argv"])

    def test_no_gitignore_present(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertIn("--no-gitignore", out["log"]["argv"])

    def test_no_check_update_present(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertIn("--no-check-update", out["log"]["argv"])

    def test_no_stream_present(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertIn("--no-stream", out["log"]["argv"])

    def test_chat_history_file_under_attempt_dir_not_worktree(self) -> None:
        out = self._run_backend("transcript-success.txt")
        argv = out["log"]["argv"]
        attempt_dir = out["attempt_dir"]
        worktree = out["worktree"]
        idx = argv.index("--chat-history-file")
        chat_hist = Path(argv[idx + 1])
        self.assertTrue(str(chat_hist).startswith(str(attempt_dir)))
        self.assertFalse(str(chat_hist).startswith(str(worktree)))

    def test_llm_history_file_under_attempt_dir_not_worktree(self) -> None:
        out = self._run_backend("transcript-success.txt")
        argv = out["log"]["argv"]
        attempt_dir = out["attempt_dir"]
        worktree = out["worktree"]
        idx = argv.index("--llm-history-file")
        llm_hist = Path(argv[idx + 1])
        self.assertTrue(str(llm_hist).startswith(str(attempt_dir)))
        self.assertFalse(str(llm_hist).startswith(str(worktree)))

    def test_message_file_under_attempt_dir_not_worktree(self) -> None:
        out = self._run_backend("transcript-success.txt")
        argv = out["log"]["argv"]
        attempt_dir = out["attempt_dir"]
        worktree = out["worktree"]
        idx = argv.index("--message-file")
        msg_file = Path(argv[idx + 1])
        self.assertTrue(str(msg_file).startswith(str(attempt_dir)))
        self.assertFalse(str(msg_file).startswith(str(worktree)))

    def test_edit_format_absent_by_default(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertNotIn("--edit-format", out["log"]["argv"])

    def test_edit_format_present_when_env_set(self) -> None:
        out = self._run_backend(
            "transcript-success.txt",
            env_overrides={"CCT_AIDER_EDIT_FORMAT": "whole"},
        )
        argv = out["log"]["argv"]
        self.assertIn("--edit-format", argv)
        self.assertEqual(argv[argv.index("--edit-format") + 1], "whole")
        self.assertTrue(out["result"].backend_metadata["edit_format_forced"])

    def test_edit_format_forced_false_by_default(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertFalse(out["result"].backend_metadata["edit_format_forced"])

    # ── Prompt delivery ──────────────────────────────────────────────────

    def test_prompt_delivered_via_message_file_not_stdin_or_argv(self) -> None:
        out = self._run_backend("transcript-success.txt")
        log = out["log"]
        # The shim reads and logs the contents of the --message-file.
        self.assertIn("Write add.py", log["message_file"])
        # The prompt must NOT be on argv.
        self.assertNotIn("Write add.py", " ".join(log["argv"]))

    def test_cwd_is_worktree(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertEqual(
            Path(out["log"]["cwd"]).resolve(),
            out["worktree"].resolve(),
        )

    # ── Transcript + output file assertions ─────────────────────────────

    def test_transcript_txt_written_under_attempt_dir(self) -> None:
        out = self._run_backend("transcript-success.txt")
        result = out["result"]
        self.assertIsNotNone(result.transcript_path)
        self.assertTrue(result.transcript_path.exists())
        self.assertTrue(
            str(result.transcript_path).startswith(str(out["attempt_dir"]))
        )

    def test_transcript_stderr_written_under_attempt_dir(self) -> None:
        out = self._run_backend(
            "transcript-success.txt",
            env_overrides={"CCT_FAKE_AIDER_STDERR": "some stderr"},
        )
        stderr_path = out["attempt_dir"] / "transcript.stderr.txt"
        self.assertTrue(stderr_path.exists())

    def test_model_output_path_set_when_chat_history_written(self) -> None:
        # The fake shim writes a non-empty chat history file.
        out = self._run_backend("transcript-success.txt")
        result = out["result"]
        self.assertIsNotNone(result.model_output_path)
        self.assertTrue(result.model_output_path.exists())

    # ── Token + metadata assertions ─────────────────────────────────────

    def test_run_records_token_counts(self) -> None:
        out = self._run_backend("transcript-success.txt")
        result = out["result"]
        # Recorded transcript: `Tokens: 2.7k sent, 73 received.` → 2700 / 73.
        self.assertEqual(result.tokens_input, 2700)
        self.assertEqual(result.tokens_output, 73)

    def test_missing_tokens_yields_none(self) -> None:
        out = self._run_backend("transcript-no-summary.txt")
        result = out["result"]
        self.assertIsNone(result.tokens_input)
        self.assertIsNone(result.tokens_output)

    def test_zero_tokens_yields_zero_not_none(self) -> None:
        out = self._run_backend("transcript-zero-tokens.txt")
        result = out["result"]
        self.assertEqual(result.tokens_input, 0)
        self.assertEqual(result.tokens_output, 0)

    def test_metadata_family_is_aider(self) -> None:
        out = self._run_backend("transcript-success.txt")
        self.assertEqual(out["result"].backend_metadata["family"], "aider")

    def test_metadata_provider_env_present_all_bool(self) -> None:
        out = self._run_backend("transcript-success.txt")
        pep = out["result"].backend_metadata["provider_env_present"]
        for k, v in pep.items():
            self.assertIsInstance(v, bool, f"provider_env_present[{k!r}] is not bool")

    def test_metadata_no_temperature_key(self) -> None:
        # Aider has no CLI temperature flag — must not appear in metadata.
        out = self._run_backend("transcript-success.txt")
        self.assertNotIn("temperature", out["result"].backend_metadata)

    def test_no_api_key_in_metadata(self) -> None:
        # Set a dummy key; only the boolean True must be recorded, not the value.
        out = self._run_backend(
            "transcript-success.txt",
            env_overrides={"ANTHROPIC_API_KEY": "sk-ant-dummy-key-for-testing"},
        )
        meta_str = str(out["result"].backend_metadata)
        self.assertNotIn("sk-", meta_str)
        self.assertNotIn("Bearer ", meta_str)

    def test_nonzero_exit_recorded_as_failed_command(self) -> None:
        out = self._run_backend("transcript-success.txt", exit_code=2)
        self.assertEqual(out["result"].failed_commands, 1)

    def test_zero_exit_recorded_as_no_failed_command(self) -> None:
        out = self._run_backend("transcript-success.txt", exit_code=0)
        self.assertEqual(out["result"].failed_commands, 0)

    # ── Worktree cleanliness regression ─────────────────────────────────

    def test_worktree_contains_no_aider_files_after_run(self) -> None:
        out = self._run_backend("transcript-success.txt")
        worktree = out["worktree"]
        aider_files = list(worktree.glob(".aider*"))
        self.assertEqual(
            aider_files,
            [],
            f"Found .aider* files in worktree: {aider_files}",
        )

    def test_worktree_has_no_git_commits_after_run(self) -> None:
        # The worktree is not a git repo, and the pinned argv passes --no-git
        # so the shim (which simulates real aider's pollution) does NOT create
        # .git/. The fake shim creates files in cwd; the backend's cwd is the
        # worktree, so a regression would land .git there.
        worktree = self._run_backend("transcript-success.txt")["worktree"]
        self.assertFalse(
            (worktree / ".git").exists(),
            "A .git directory was created in the worktree",
        )
        self.assertFalse(
            (worktree / ".gitignore").exists(),
            "A .gitignore was written into the worktree",
        )

    def test_negative_control_shim_pollutes_without_no_git(self) -> None:
        # Negative control: prove the shim's pollution simulation is real
        # (and that the cleanliness guard above is therefore meaningful).
        # When --no-git is removed from argv, the shim DOES create .git/ +
        # .gitignore in cwd. This is the regression the pinned argv prevents.
        import subprocess
        from pathlib import Path

        tmpdir = Path(self._tmp_path) / "polluted-cwd"
        tmpdir.mkdir()
        # Run the shim directly with argv that LACKS --no-git.
        env = dict(os.environ, CCT_FAKE_AIDER_TRANSCRIPT=str(
            _FIXTURES / "transcript-success.txt"))
        proc = subprocess.run(
            [sys.executable, str(self._fake), "--yes-always"],
            cwd=str(tmpdir), env=env, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(
            (tmpdir / ".git").is_dir(),
            "shim should pollute with .git/ when --no-git is absent (control)",
        )
        self.assertTrue(
            (tmpdir / ".gitignore").is_file(),
            "shim should pollute with .gitignore when --no-git is absent",
        )


class TestVerifiedVersionGate(unittest.TestCase):
    """Self-enforcing B3 gate: `_VERIFIED_VERSION` must not be the loud
    placeholder string after B3 wires the real maintainer capture. If
    anyone bumps the pin without re-capturing, this test fails and the
    PR description's pre-merge gate (verification-record-matches) line
    is the second independent signal. Tracks the spec's invariant 1.
    """

    def test_verified_version_not_placeholder(self) -> None:
        from benchmark_runner.backends.aider import _VERIFIED_VERSION
        self.assertNotIn(
            "PHASE_B3_CAPTURE_REQUIRED",
            _VERIFIED_VERSION,
            "Pinned aider version is still the B0 placeholder. Run the "
            "live capture per specs/benchmark-harness/verification/aider.md "
            "before merging.",
        )
        self.assertTrue(
            _VERIFIED_VERSION.startswith("aider "),
            f"_VERIFIED_VERSION must match `aider --version` output shape; "
            f"got {_VERIFIED_VERSION!r}",
        )


if __name__ == "__main__":
    unittest.main()
