# tests/test_pi_backend.py — Pi backend tests (T3.5).
#
# No real pi-code is spawned. The transcript parser is exercised against inline
# transcripts, and run() is exercised against a fake pi-code shim that echoes a
# chosen transcript + logs argv/stdin/cwd — validating end-to-end behavior with
# no network/auth. Mirrors test_codex_backend.py.

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark_runner.backends.pi import (
    BACKEND_FAMILY,
    PiBackend,
    PiCliNotFoundError,
    _parse_transcript,
    factory,
)
from benchmark_runner.contracts import Backend, RunContext

_TRANSCRIPT = (
    '{"type":"result","text":"Done. Created add.py"}\n'
    '{"type":"tool","name":"write"}\n'
    '{"type":"tool","name":"write"}\n'
    '{"type":"usage","input_tokens":120,"output_tokens":45,"cache_read_tokens":10}\n'
)

_FAKE_PI = """#!{shebang}
import json, os, sys
stdin_data = sys.stdin.read()
log = os.environ.get("CCT_FAKE_PI_LOG", "")
if log:
    with open(log, "w", encoding="utf-8") as f:
        json.dump({{"argv": sys.argv, "cwd": os.getcwd(), "stdin": stdin_data}}, f)
with open(os.environ["CCT_FAKE_PI_TRANSCRIPT"], "r", encoding="utf-8") as src:
    sys.stdout.write(src.read())
sys.exit(int(os.environ.get("CCT_FAKE_PI_EXIT", "0")))
"""


def _install_fake_pi(tmpdir: Path) -> Path:
    bindir = tmpdir / "fake-bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "pi-code"
    fake.write_text(_FAKE_PI.format(shebang=sys.executable), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bindir


class TestParseTranscript(unittest.TestCase):
    def test_full_transcript(self) -> None:
        p = _parse_transcript(_TRANSCRIPT)
        self.assertIn("Created add.py", p.result_text)
        self.assertEqual(p.tokens_input, 120)
        self.assertEqual(p.tokens_output, 45)
        self.assertEqual(p.cache_read_tokens, 10)
        self.assertEqual(p.tool_calls.get("write"), 2)

    def test_missing_usage_is_none_not_zero(self) -> None:
        p = _parse_transcript('{"type":"result","text":"x"}\n')
        self.assertIsNone(p.tokens_input)
        self.assertIsNone(p.tokens_output)

    def test_zero_usage_is_zero_not_none(self) -> None:
        p = _parse_transcript('{"type":"usage","input_tokens":0,"output_tokens":0}\n')
        self.assertEqual(p.tokens_input, 0)
        self.assertEqual(p.tokens_output, 0)

    def test_unparseable_lines_skipped(self) -> None:
        p = _parse_transcript('garbage\n{"type":"usage","output_tokens":7}\n')
        self.assertEqual(p.tokens_output, 7)

    def test_empty_is_empty(self) -> None:
        p = _parse_transcript("")
        self.assertEqual(p.result_text, "")
        self.assertEqual(p.tool_calls, {})


class TestBackendShape(unittest.TestCase):
    def test_satisfies_protocol(self) -> None:
        self.assertIsInstance(PiBackend(model="m"), Backend)

    def test_backend_id_is_family(self) -> None:
        self.assertEqual(PiBackend().backend_id, BACKEND_FAMILY)

    def test_factory_carries_model(self) -> None:
        self.assertEqual(factory("m")._model, "m")  # noqa: SLF001

    def test_run_raises_when_cli_missing(self) -> None:
        b = PiBackend(cli_executable="pi-code-not-installed-xyz")
        ctx = RunContext(
            benchmark_id="x", task_id="y", backend_id="pi", run_id="r",
            attempt=1, worktree=Path("/tmp"), model="",
        )
        with self.assertRaises(PiCliNotFoundError):
            b.run("hi", ctx)


class TestBackendEndToEnd(unittest.TestCase):
    def test_run_against_fake_pi(self) -> None:
        prev_path = os.environ.get("PATH", "")
        prev = {k: os.environ.get(k) for k in ("CCT_FAKE_PI_TRANSCRIPT", "CCT_FAKE_PI_LOG")}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bindir = _install_fake_pi(tmp)
            worktree = tmp / "attempt" / "wt"
            worktree.mkdir(parents=True)
            tfile = tmp / "t.jsonl"
            tfile.write_text(_TRANSCRIPT, encoding="utf-8")
            log = tmp / "log.json"

            os.environ["PATH"] = str(bindir) + os.pathsep + prev_path
            os.environ["CCT_FAKE_PI_TRANSCRIPT"] = str(tfile)
            os.environ["CCT_FAKE_PI_LOG"] = str(log)
            try:
                ctx = RunContext(
                    benchmark_id="b", task_id="t", backend_id="pi", run_id="r",
                    attempt=1, worktree=worktree, model="local-model",
                )
                result = PiBackend(model="local-model").run("do the thing", ctx)
            finally:
                os.environ["PATH"] = prev_path
                for k, v in prev.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

            # Parsed run-record fields.
            self.assertEqual(result.tokens_input, 120)
            self.assertEqual(result.tokens_output, 45)
            self.assertEqual(result.failed_commands, 0)
            self.assertTrue(result.transcript_path.exists())
            self.assertIn("Created add.py", result.model_output_path.read_text())
            # Honest metadata: never claim verified.
            self.assertIs(result.backend_metadata["verified"], False)
            self.assertEqual(result.backend_metadata["family"], "pi")
            # Invoked with the --mode json contract + the model.
            logged = json.loads(log.read_text())
            self.assertEqual(logged["argv"][1:], ["--mode", "json", "--model", "local-model"])
            self.assertEqual(logged["stdin"], "do the thing")


class TestRegistration(unittest.TestCase):
    def test_pi_backend_is_registered(self) -> None:
        from benchmark_runner import registry
        from benchmark_runner._register import register_all, unregister_all_for_tests

        unregister_all_for_tests()
        try:
            register_all()
            self.assertIn("pi", registry.list_backend_ids())
        finally:
            unregister_all_for_tests()


if __name__ == "__main__":
    unittest.main()
