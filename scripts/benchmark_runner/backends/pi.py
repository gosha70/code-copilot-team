# benchmark_runner.backends.pi — Pi (pi-code) agent backend (T3.5).
#
# Spawns ``pi-code --mode json [--model <model>]`` with the prompt on stdin in
# the attempt worktree and captures the JSON-mode transcript, mirroring the
# codex/claude_code backends.
#
# VERIFICATION STATUS — UNVERIFIED against a real pinned pi.
#   Unlike codex.py (verified argv for codex-cli 0.130.0), pi's exact
#   non-interactive JSON invocation and transcript schema have NOT been captured
#   against a real pi binary in this environment. This backend is written to a
#   DEFINED contract (documented below) and exercised end-to-end against a fake
#   pi-code shim in tests. Before using it against a real pi, capture the argv +
#   a real transcript and pin the version here (see specs/benchmark-harness/
#   verification/ for the codex/claude-code precedent). The backend records
#   ``verified: false`` in backend_metadata so a run is never mistaken for a
#   verified one.
#
# Defined transcript contract (JSONL, one JSON object per line):
#   {"type": "result",  "text": "<final model response>"}
#   {"type": "usage",   "input_tokens": N, "output_tokens": M,
#                        "cache_read_tokens": K}      # any field optional
#   {"type": "tool",    "name": "<tool>"}             # counted by name
# Unparseable lines are skipped; null-vs-zero is preserved.

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from ..contracts import BackendResult, RunContext

_log = logging.getLogger(__name__)

BACKEND_FAMILY = "pi"

_DEFAULT_TIMEOUT_SECONDS = 600
_STDERR_TAIL_CHARS = 1024


class PiCliNotFoundError(RuntimeError):
    """Raised when the ``pi-code`` launcher is not on PATH."""


class PiBackend:
    """Spawns ``pi-code --mode json`` and captures the JSON transcript."""

    backend_id = BACKEND_FAMILY

    def __init__(self, model: str = "", *, cli_executable: str = "pi-code") -> None:
        self._model = model
        self._cli = cli_executable

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        if shutil.which(self._cli) is None:
            raise PiCliNotFoundError(
                f"the pi backend needs the {self._cli!r} launcher on PATH; "
                f"install it with ./scripts/setup.sh --pi."
            )

        argv = self._build_argv()
        timeout = ctx.timeout_seconds or _DEFAULT_TIMEOUT_SECONDS

        started = time.monotonic()
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ctx.worktree),
            text=True,
            env=dict(os.environ),
            start_new_session=True,
        )
        try:
            stdout_data, stderr_data = proc.communicate(input=prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                _, stderr_late = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                stderr_late = ""
            elapsed = time.monotonic() - started
            return BackendResult(
                transcript_path=None,
                elapsed_seconds=elapsed,
                timed_out=True,
                failed_commands=1,
                backend_metadata=_build_metadata(
                    model=self._model,
                    exit_code=None,
                    stderr_tail=_tail(stderr_late or "", _STDERR_TAIL_CHARS),
                    note=f"pi-code timed out after {timeout}s (process group killed)",
                ),
            )

        elapsed = time.monotonic() - started

        attempt_dir = ctx.worktree.parent
        transcript_path = attempt_dir / "transcript.jsonl"
        transcript_path.write_text(stdout_data or "", encoding="utf-8")

        parsed = _parse_transcript(stdout_data or "")
        model_output_path: Optional[Path] = None
        if parsed.result_text:
            model_output_path = attempt_dir / "model-output.txt"
            model_output_path.write_text(parsed.result_text, encoding="utf-8")

        return BackendResult(
            transcript_path=transcript_path,
            model_output_path=model_output_path,
            elapsed_seconds=elapsed,
            tokens_input=parsed.tokens_input,
            tokens_output=parsed.tokens_output,
            cache_read_tokens=parsed.cache_read_tokens,
            tool_calls=parsed.tool_calls,
            failed_commands=0 if proc.returncode == 0 else 1,
            backend_metadata=_build_metadata(
                model=self._model,
                exit_code=proc.returncode,
                stderr_tail=_tail(stderr_data or "", _STDERR_TAIL_CHARS),
            ),
        )

    def _build_argv(self) -> list[str]:
        argv = [self._cli, "--mode", "json"]
        if self._model:
            argv.extend(["--model", self._model])
        return argv


# ── Module-level helpers ───────────────────────────────────────────────


def _build_metadata(
    *,
    model: str,
    exit_code: Optional[int],
    stderr_tail: str,
    note: Optional[str] = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "family": BACKEND_FAMILY,
        "model": model,
        "mode": "json",
        # Honest posture: this backend's argv/transcript are NOT verified
        # against a real pinned pi. Never record it as verified.
        "verified": False,
        "exit_code": exit_code,
        "stderr_tail": stderr_tail,
    }
    if note is not None:
        meta["note"] = note
    return meta


def _tail(text: str, max_chars: int) -> str:
    if not text:
        return ""
    return text[-max_chars:] if len(text) > max_chars else text


class _Parsed:
    __slots__ = ("result_text", "tokens_input", "tokens_output", "cache_read_tokens", "tool_calls")

    def __init__(self) -> None:
        self.result_text: str = ""
        self.tokens_input: Optional[int] = None
        self.tokens_output: Optional[int] = None
        self.cache_read_tokens: Optional[int] = None
        self.tool_calls: dict[str, int] = {}


def _parse_transcript(stdout: str) -> _Parsed:
    out = _Parsed()
    if not stdout.strip():
        return out
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "result":
            text = event.get("text")
            if isinstance(text, str) and text:
                out.result_text = out.result_text + "\n\n" + text if out.result_text else text
        elif etype == "usage":
            out.tokens_input = _int_or_none(event.get("input_tokens"))
            out.tokens_output = _int_or_none(event.get("output_tokens"))
            out.cache_read_tokens = _int_or_none(event.get("cache_read_tokens"))
        elif etype == "tool":
            name = event.get("name")
            if isinstance(name, str) and name:
                out.tool_calls[name] = out.tool_calls.get(name, 0) + 1
    return out


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def factory(model: str) -> PiBackend:
    return PiBackend(model)
