# benchmark_runner.backends.aider — Aider CLI backend.
#
# Spawns ``aider [--model <m>] --yes-always --no-auto-commits
# --no-dirty-commits --no-gitignore --no-git --no-check-update
# --no-stream --chat-history-file <attempt_dir>/aider.chat.history.md
# --llm-history-file  <attempt_dir>/aider.llm.history.txt
# [--edit-format <fmt>] --message-file <attempt_dir>/aider-message.txt``
# in the attempt worktree and captures the text transcript.
#
# Verified argv contract: see specs/benchmark-harness/verification/aider.md
# (aider 0.86.2 recorded transcript, captured 2026-05-19). Apples-to-apples
# caveat: ``--no-git`` is pinned to keep the worktree clean for run.py's
# _write_diff (which excludes only .venv) — Aider's published Polyglot
# leaderboard runs each exercise inside a git repo, so the repo-map may
# degrade on multi-file tasks. Tracked in #46 (git-with-cleanup pattern).
#
# Provider routing:
# Aider reads provider credentials from the environment (ANTHROPIC_API_KEY,
# OPENAI_API_KEY, OPENROUTER_API_KEY, OPENAI_API_BASE). The harness
# records only the *presence* of each variable as a boolean — never the
# value — in backend_metadata.provider_env_present. It does NOT set
# provider env vars; provider configuration is the user's responsibility.
#
# Prompt delivery:
# Aider has no codex-style stdin ``-`` flag. The prompt is written to a
# message file (``--message-file <attempt_dir>/aider-message.txt``) before
# spawning. Message + history files live in ``attempt_dir``
# (= ctx.worktree.parent), never in ``worktree``, so they are excluded
# from the scored diff (run.py's _write_diff excludes only .venv; files
# in worktree would pollute the diff).
#
# Transcript format:
# Aider emits plain text, not JSON. stdout -> attempt_dir/transcript.txt,
# stderr -> attempt_dir/transcript.stderr.txt. Token and cost metrics are
# parsed best-effort from Aider's ``Tokens:`` / cost summary line.
# cache_* fields are always None; tool_calls is always {} (Aider has no
# codex-style tool events).
#
# Flags NOT present:
# ``--yes`` does not exist (the flag is ``--yes-always`` — B0 confirmed).
# ``--temperature`` is not an Aider CLI flag (Aider-internal via litellm).
# ``--map-tokens`` is not pinned (methodology-fidelity: Design Decision 3).
# Edit-format is not pinned unless CCT_AIDER_EDIT_FORMAT is set.

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from ..contracts import BackendResult, RunContext

BACKEND_FAMILY = "aider"

# Pinned ``aider --version`` output, captured on the maintainer machine
# 2026-05-19 (see specs/benchmark-harness/verification/aider.md). The
# self-enforcing ``test_verified_version_not_placeholder`` asserts this
# string is not the B0 gate placeholder — a regression guard if anyone
# bumps the pin without re-capturing.
_VERIFIED_VERSION = "aider 0.86.2"

# Conservative default; per-task adapters can override via RunContext.timeout_seconds.
_DEFAULT_TIMEOUT_SECONDS = 600

# Maximum stderr tail to capture in backend_metadata.
_STDERR_TAIL_CHARS = 1024

# Env var name for the per-candidate timeout override (mirrors claude_code.py).
_TIMEOUT_ENV_VAR = "CCT_AIDER_TIMEOUT_SECONDS"

# Env var to force edit-format (omitted entirely when unset — methodology fidelity).
_EDIT_FORMAT_ENV_VAR = "CCT_AIDER_EDIT_FORMAT"

# Provider env vars recorded as presence booleans (never values).
_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_BASE",
)


class AiderCliNotFoundError(RuntimeError):
    """Raised when the ``aider`` CLI is not on PATH."""


class AiderBackend:
    """Spawns ``aider --message-file`` and captures the text transcript.

    Construction is cheap; the work happens in ``run``. The model string
    is passed to aider via ``--model`` only when non-empty — an absent
    ``--model`` lets aider use its own default (the intended behavior
    when the caller has not specified a model).
    """

    backend_id = BACKEND_FAMILY

    def __init__(self, model: str = "") -> None:
        self._model = model

    # ── Backend protocol ───────────────────────────────────────────────

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        if shutil.which("aider") is None:
            raise AiderCliNotFoundError(
                "the aider backend needs the 'aider' CLI on PATH; "
                "install it with: pip install aider-chat. "
                "See specs/benchmark-harness/verification/aider.md for the "
                "verified invocation surface."
            )

        attempt_dir = ctx.worktree.parent

        # Write the prompt to a message file under attempt_dir (never worktree).
        message_file = attempt_dir / "aider-message.txt"
        message_file.write_text(prompt, encoding="utf-8")

        edit_format_raw = os.environ.get(_EDIT_FORMAT_ENV_VAR, "").strip()
        edit_format: Optional[str] = edit_format_raw if edit_format_raw else None

        argv = self._build_argv(attempt_dir=attempt_dir, edit_format=edit_format)
        timeout = ctx.timeout_seconds or _timeout_override() or _DEFAULT_TIMEOUT_SECONDS

        started = time.monotonic()
        # Use start_new_session=True (same pattern as codex.py / claude_code.py / Bug #6)
        # so the whole process group is killable on timeout — aider may spawn
        # sub-shells that keep pipes open.
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ctx.worktree),
            text=True,
            env=dict(os.environ),  # forward host env unchanged
            start_new_session=True,
        )
        try:
            # Prompt is in the message file; pass empty string to stdin (not None,
            # to avoid blocking if aider reads stdin).
            stdout_data, stderr_data = proc.communicate(input="", timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            stderr_tail = ""
            try:
                _, stderr_late = proc.communicate(timeout=10)
                stderr_tail = _tail(stderr_late or "", _STDERR_TAIL_CHARS)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            elapsed = time.monotonic() - started
            return BackendResult(
                transcript_path=None,
                elapsed_seconds=elapsed,
                backend_metadata=_build_metadata(
                    model=self._model,
                    edit_format_resolved=None,
                    edit_format_forced=edit_format is not None,
                    map_tokens_effective=None,
                    exit_code=None,
                    stderr_tail=stderr_tail,
                    note=f"aider timed out after {timeout}s (process group killed)",
                ),
                failed_commands=1,
                timed_out=True,  # D5: structured signal consumed by run._execute_attempt
            )

        elapsed = time.monotonic() - started

        # Persist raw transcripts before parsing.
        transcript_path = attempt_dir / "transcript.txt"
        transcript_path.write_text(stdout_data or "", encoding="utf-8")
        stderr_path = attempt_dir / "transcript.stderr.txt"
        stderr_path.write_text(stderr_data or "", encoding="utf-8")

        parsed = _parse_transcript(stdout_data or "")

        # model_output_path = chat history file if it exists and is non-empty.
        chat_history_file = attempt_dir / "aider.chat.history.md"
        model_output_path: Optional[Path] = None
        if chat_history_file.is_file() and chat_history_file.stat().st_size > 0:
            model_output_path = chat_history_file

        return BackendResult(
            transcript_path=transcript_path,
            model_output_path=model_output_path,
            elapsed_seconds=elapsed,
            tokens_input=parsed.tokens_input,
            tokens_output=parsed.tokens_output,
            cache_read_tokens=None,   # Aider does not report cache metrics
            cache_write_tokens=None,
            tool_calls={},            # Aider has no codex-style tool events
            failed_commands=0 if proc.returncode == 0 else 1,
            backend_metadata=_build_metadata(
                model=self._model,
                edit_format_resolved=parsed.edit_format_resolved,
                edit_format_forced=edit_format is not None,
                map_tokens_effective=parsed.map_tokens_effective,
                exit_code=proc.returncode,
                stderr_tail=_tail(stderr_data or "", _STDERR_TAIL_CHARS),
            ),
        )

    # ── Internals ──────────────────────────────────────────────────────

    def _build_argv(self, *, attempt_dir: Path, edit_format: Optional[str]) -> list[str]:
        """Build the verified argv for the Aider CLI.

        Exact form (B0-corrected + B3-recapture contract):
          aider [--model <model>]
                --yes-always
                --no-auto-commits
                --no-dirty-commits
                --no-gitignore
                --no-git                    # B3: prevents .git/ in worktree
                --no-check-update
                --no-stream
                --chat-history-file <attempt_dir>/aider.chat.history.md
                --llm-history-file  <attempt_dir>/aider.llm.history.txt
                [--edit-format <fmt>]       # only when CCT_AIDER_EDIT_FORMAT set
                --message-file <attempt_dir>/aider-message.txt

        ``--model`` is included only when self._model is non-empty.
        ``--yes`` does NOT exist; the flag is ``--yes-always`` (B0).
        ``--temperature`` is not an Aider CLI flag.
        ``--map-tokens`` is not pinned (methodology fidelity, Design Decision 3).
        ``--no-git`` yields ``Git repo: none``, ``Repo-map: disabled`` in
        the transcript (apples-to-apples caveat tracked in #46).
        """
        argv = ["aider"]
        if self._model:
            argv.extend(["--model", self._model])
        argv.extend([
            "--yes-always",
            "--no-auto-commits",
            "--no-dirty-commits",
            "--no-gitignore",
            "--no-git",  # B3: real aider creates .git/ in a non-git dir despite
                         # --no-gitignore; --no-git yields "Git repo: none",
                         # "Repo-map: disabled" (a-to-a caveat tracked in #46).
            "--no-check-update",
            "--no-stream",
            "--chat-history-file", str(attempt_dir / "aider.chat.history.md"),
            "--llm-history-file",  str(attempt_dir / "aider.llm.history.txt"),
        ])
        if edit_format:
            argv.extend(["--edit-format", edit_format])
        argv.extend(["--message-file", str(attempt_dir / "aider-message.txt")])
        return argv


# ── Module-level helpers ───────────────────────────────────────────────


def _timeout_override() -> Optional[int]:
    """Resolve a per-attempt timeout (seconds) from the environment.

    Returns the positive integer when set, ``None`` when unset (so the
    caller falls through to ``_DEFAULT_TIMEOUT_SECONDS``). Raises
    ``ValueError`` on non-numeric or non-positive values — silently
    dropping a bad value would let a typo'd setting masquerade as the
    default budget.
    """
    val = os.environ.get(_TIMEOUT_ENV_VAR, "").strip()
    if not val:
        return None
    try:
        seconds = int(val)
    except ValueError as exc:
        raise ValueError(
            f"{_TIMEOUT_ENV_VAR}={val!r} is not an integer. "
            f"Expected a positive integer number of seconds (e.g. 1800 for 30 min)."
        ) from exc
    if seconds <= 0:
        raise ValueError(
            f"{_TIMEOUT_ENV_VAR}={val!r} must be positive; got {seconds}."
        )
    return seconds


def _resolve_provider_env() -> dict[str, bool]:
    """Return presence booleans for known provider env vars.

    Values are NEVER recorded — only whether the variable is set and
    non-empty. This is the security invariant for all provider secrets.
    """
    return {k: bool(os.environ.get(k)) for k in _PROVIDER_ENV_KEYS}


def _build_metadata(
    *,
    model: str,
    edit_format_resolved: Optional[str],
    edit_format_forced: bool,
    map_tokens_effective: Optional[int],
    exit_code: Optional[int],
    stderr_tail: str,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble backend_metadata for an aider run.

    Key invariants:
    - No API keys or credential values are ever recorded.
    - ``provider_env_present`` carries only boolean presence flags.
    - No ``temperature`` key (Aider has no CLI temperature flag — B0).
    """
    meta: dict[str, Any] = {
        "family": BACKEND_FAMILY,
        "model": model,
        "aider_version": _VERIFIED_VERSION,
        "chat_mode": "code",
        "edit_format_resolved": edit_format_resolved,
        "edit_format_forced": edit_format_forced,
        "map_tokens_effective": map_tokens_effective,
        "auto_commits": False,
        "dirty_commits": False,
        "provider_env_present": _resolve_provider_env(),
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


# ── Transcript parser ──────────────────────────────────────────────────

# Aider summary line shapes — regenerated from the B3 recorded transcript
# (aider 0.86.2, 2026-05-19). The earlier hand-authored regexes did not
# match real output; see [[feedback_recorded_capture_is_fixture_ground_truth]].
#
# Tokens (the `k`/`M` suffixed form is the common real format, but plain
# integers and comma thousands also appear in other versions/contexts):
#   Tokens: 2.7k sent, 73 received.
#   Tokens: 2.7k sent, 73 received. Cost: $0.0091 message, $0.0091 session.
#   Tokens: 1,234 sent, 567 received.   (comma thousands)
#   Tokens: 1234 sent, 567 received.    (plain int)
# Edit format echo (substring of the Model: line, NOT a standalone line):
#   Model: anthropic/claude-sonnet-4-5 with diff edit format, infinite output
# Repo-map (only when active; under --no-git aider prints
# ``Repo-map: disabled`` and there is no token count to parse → None):
#   Repo-map: using 4096 tokens, auto refresh
#   Repo-map: disabled

_TOKEN_NUM = r"[\d][\d.,]*[kKmM]?"

_TOKENS_RE = re.compile(
    rf"Tokens:\s*({_TOKEN_NUM})\s+sent,\s*({_TOKEN_NUM})\s+received",
    re.IGNORECASE,
)
_EDIT_FORMAT_RE = re.compile(
    r"with\s+(\S+)\s+edit\s+format",
    re.IGNORECASE,
)
_MAP_TOKENS_RE = re.compile(
    r"Repo-map:\s*using\s+([\d,]+)\s+tokens",
    re.IGNORECASE,
)


class _Parsed:
    __slots__ = (
        "tokens_input",
        "tokens_output",
        "edit_format_resolved",
        "map_tokens_effective",
    )

    def __init__(self) -> None:
        self.tokens_input: Optional[int] = None
        self.tokens_output: Optional[int] = None
        self.edit_format_resolved: Optional[str] = None
        self.map_tokens_effective: Optional[int] = None


def _parse_token_count(s: str) -> int:
    """Parse Aider's token-count tokens — supports plain ints (``73``),
    comma thousands (``1,234``), and ``k``/``M`` suffixes (``2.7k`` → 2700,
    ``1.2M`` → 1_200_000). Per the B3 recorded transcript the ``k`` suffix
    is the common real form. The result is rounded to the nearest int.
    """
    s = s.strip().replace(",", "")
    mult = 1
    if s and s[-1] in ("k", "K"):
        mult, s = 1_000, s[:-1]
    elif s and s[-1] in ("m", "M"):
        mult, s = 1_000_000, s[:-1]
    return round(float(s) * mult)


def _parse_transcript(stdout: str) -> _Parsed:
    """Parse the plain-text stdout emitted by ``aider``.

    Best-effort: tolerant regex over Aider's ``Tokens:`` / cost summary
    line. Token field semantics:
    - If NO summary line is present → tokens_input and tokens_output are
      both ``None`` (backend did not provide the metric).
    - If a summary IS present with value 0 → ``0`` (NOT None).
      These are distinct paths; the distinction is asserted in B2 tests.

    ``cache_read_tokens`` and ``cache_write_tokens`` are always ``None``
    (Aider does not report cache metrics via the CLI).
    ``tool_calls`` is always ``{}`` (no codex-style tool events).
    """
    out = _Parsed()
    if not stdout.strip():
        return out

    # Parse token summary — use the LAST match (may appear per-message;
    # the final one is the session total).
    tokens_match = None
    for m in _TOKENS_RE.finditer(stdout):
        tokens_match = m
    if tokens_match is not None:
        out.tokens_input = _parse_token_count(tokens_match.group(1))
        out.tokens_output = _parse_token_count(tokens_match.group(2))
    # If no match: tokens_input and tokens_output remain None.

    # Parse edit format echo (first match).
    ef_match = _EDIT_FORMAT_RE.search(stdout)
    if ef_match:
        out.edit_format_resolved = ef_match.group(1).strip()

    # Parse repo-map token echo (last match).
    map_match = None
    for m in _MAP_TOKENS_RE.finditer(stdout):
        map_match = m
    if map_match is not None:
        out.map_tokens_effective = _parse_token_count(map_match.group(1))

    return out


# ── Factory ────────────────────────────────────────────────────────────


def factory(model: str) -> AiderBackend:
    return AiderBackend(model)
