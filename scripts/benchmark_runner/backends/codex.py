# benchmark_runner.backends.codex — OpenAI Codex CLI backend.
#
# Spawns ``codex exec --json --sandbox workspace-write --skip-git-repo-check
# [--model <model>] -`` with the prompt on stdin (trailing ``-``) in the
# attempt worktree and captures the JSONL transcript.
#
# Verified argv for codex-cli 0.130.0 (2026-05-17). The full verification
# record — pinned version, real transcript, flag/env contract — lives at:
#   specs/benchmark-harness/verification/codex.md
#
# Provider routing (CORRECTED by #281):
# Codex reads model and provider from its own configuration. The harness
# records the BASE user config path — ``$CODEX_HOME/config.toml``, else
# ``~/.codex/config.toml`` — and records the provider as UNESTABLISHED
# (``provider_id: None``).
#
# It records no selected provider because it selects none: this backend
# passes codex neither ``-c model_provider=<id>`` nor ``--profile``, so
# codex chooses from its own layered configuration and the harness has no
# signal about which provider answered. The earlier claim that it
# "records the selected provider id" was untrue — the value came from the
# first key under ``[model_providers]``, in arbitrary dict order.
#
# The config is NOT parsed, and it does NOT set or rewrite it — provider
# configuration is the user's responsibility.
#
# IMPORTANT: codex exec is inherently non-interactive. There is NO
# --ask-for-approval flag on `exec` in 0.130.0. The earlier spec draft
# assumed such a flag existed; the verification probe returned exit=2 and
# `codex exec --help` confirmed no such flag. This is documented in the
# verification record.
#
# Transcript format (--json):
# JSONL events: thread.started → item.completed(agent_message) →
# turn.completed(usage.{input_tokens,cached_input_tokens,output_tokens,
# reasoning_output_tokens}). The parser maps codex keys to harness fields;
# null-vs-zero is preserved.

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

BACKEND_FAMILY = "codex"

# Verified CLI version (the version the argv contract was captured against).
_VERIFIED_VERSION = "codex-cli 0.130.0"

# Conservative default; per-task adapters can override via RunContext.timeout_seconds.
_DEFAULT_TIMEOUT_SECONDS = 600

# Maximum stderr tail to capture in backend_metadata.
_STDERR_TAIL_CHARS = 1024


class CodexCliNotFoundError(RuntimeError):
    """Raised when the ``codex`` CLI is not on PATH."""


class CodexBackend:
    """Spawns ``codex exec --json`` and captures the JSONL transcript.

    Construction is cheap; the work happens in ``run``. The model string
    is passed to codex via ``--model`` only when non-empty — an absent
    ``--model`` lets codex use the config.toml default (the intended
    behavior when the caller has not specified a model).
    """

    backend_id = BACKEND_FAMILY

    def __init__(
        self,
        model: str = "",
        *,
        cli_executable: str = "codex",
    ) -> None:
        self._model = model
        self._cli = cli_executable

    # ── Backend protocol ───────────────────────────────────────────────

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        if shutil.which(self._cli) is None:
            raise CodexCliNotFoundError(
                f"the codex backend needs the {self._cli!r} CLI on PATH; "
                f"install codex-cli (npm install -g @openai/codex or equivalent). "
                f"See specs/benchmark-harness/verification/codex.md for the "
                f"verified invocation surface."
            )

        argv = self._build_argv()
        timeout = ctx.timeout_seconds or _DEFAULT_TIMEOUT_SECONDS

        config_path, provider_id = _resolve_codex_config()

        started = time.monotonic()
        # Use start_new_session=True (same pattern as claude_code.py / Bug #6)
        # so the whole process group is killable on timeout — codex may spawn
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
            stdout_data, stderr_data = proc.communicate(input=prompt, timeout=timeout)
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
                    config_toml_path=config_path,
                    provider_id=provider_id,
                    exit_code=None,
                    stderr_tail=stderr_tail,
                    note=f"codex exec timed out after {timeout}s (process group killed)",
                ),
                failed_commands=1,
            )

        elapsed = time.monotonic() - started

        # Persist raw transcript before parsing.
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
                config_toml_path=config_path,
                provider_id=provider_id,
                exit_code=proc.returncode,
                stderr_tail=_tail(stderr_data or "", _STDERR_TAIL_CHARS),
            ),
        )

    # ── Internals ──────────────────────────────────────────────────────

    def _build_argv(self) -> list[str]:
        """Build the verified argv for codex-cli 0.130.0.

        Exact form: codex exec --json --sandbox workspace-write
                    --skip-git-repo-check [--model <model>] -

        The trailing ``-`` instructs codex to read the prompt from stdin.
        ``--model`` is included only when self._model is non-empty.
        There is NO --ask-for-approval flag (see verification record).
        """
        argv = [
            self._cli,
            "exec",
            "--json",
            "--sandbox", "workspace-write",
            "--skip-git-repo-check",
        ]
        if self._model:
            argv.extend(["--model", self._model])
        argv.append("-")  # read prompt from stdin
        return argv


# ── Module-level helpers ───────────────────────────────────────────────


def _resolve_codex_config() -> tuple[Optional[str], Optional[str]]:
    """Resolve the base user config path; the provider id is UNESTABLISHED.

    Returns (config_toml_path_str_or_None, None). The second element is
    always None, and that is the fix for #281 rather than an oversight.

    WHY THE PROVIDER ID IS ALWAYS NONE.

    This backend passes no provider selection to codex — no
    ``-c model_provider=<id>``, no ``--profile`` (see _build_argv). Codex
    therefore chooses its provider entirely from its own configuration,
    and this process has NO signal about which one it chose. The previous
    implementation reported ``next(iter(providers))`` — the first key
    under ``[model_providers]``, in arbitrary dict order — which with two
    providers configured recorded a provider the run may never have used.

    That is a fabricated fact in a metadata field that reads as evidence,
    and benchmark evidence is exactly what later decisions trust. An
    honest absence is worth more than a plausible attribution.

    Establishing it truthfully would mean reproducing codex's LAYERED
    configuration resolution — ``--profile`` layers
    ``$CODEX_HOME/<name>.config.toml`` over the base user config, and
    ``--ignore-user-config`` drops the base file entirely (codex-cli
    0.147.0) — so no single file answers the question. That work is
    deliberately not done here; see #281 and
    ``specs/routing-effective-endpoint/spec.md`` FR-E10, where the routed
    side reached the same conclusion and records null/none.

    The two returned values remain distinguishable without a third field:
    a non-null path with a null provider means "a base config exists, its
    selected provider is unestablished"; a null path means "no base
    config file".

    CODEX_HOME is honoured because codex honours it. Hardcoding
    ``~/.codex`` named a file codex may never have read.

    API keys are NEVER returned, and no provider configuration is read.
    """
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home) if codex_home else Path.home() / ".codex"
    config_path = base / "config.toml"
    if not config_path.is_file():
        return None, None
    # The file is NOT parsed. Nothing in it can be attributed to this run,
    # so opening it would only create the temptation to try.
    return str(config_path), None


def _build_metadata(
    *,
    model: str,
    config_toml_path: Optional[str],
    provider_id: Optional[str],
    exit_code: Optional[int],
    stderr_tail: str,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble backend_metadata for a codex run.

    Key invariant: API keys are NEVER recorded. Only:
    - family + model
    - base user config.toml path, honouring CODEX_HOME (presence is
      non-secret; path is not secret); None when no such file exists
    - provider id — ALWAYS None (#281). This backend passes codex no
      provider selection, so which provider served the run is
      unestablished, and a guess in an evidence field is worse than an
      honest absence. See _resolve_codex_config.
    - verified CLI version
    - exit code + stderr tail
    """
    meta: dict[str, Any] = {
        "family": BACKEND_FAMILY,
        "model": model,
        "config_toml_path": config_toml_path,
        "provider_id": provider_id,
        "codex_version": _VERIFIED_VERSION,
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


class _Parsed:
    __slots__ = (
        "result_text",
        "tokens_input",
        "tokens_output",
        "cache_read_tokens",
        "tool_calls",
    )

    def __init__(self) -> None:
        self.result_text: str = ""
        self.tokens_input: Optional[int] = None
        self.tokens_output: Optional[int] = None
        self.cache_read_tokens: Optional[int] = None
        self.tool_calls: dict[str, int] = {}


def _parse_transcript(stdout: str) -> _Parsed:
    """Parse the JSONL transcript emitted by ``codex exec --json``.

    Events of interest:
    - ``item.completed`` with ``item.type == "agent_message"``:
      ``item.text`` is the model's response text.
    - ``turn.completed``:
      ``usage.input_tokens`` → tokens_input
      ``usage.cached_input_tokens`` → cache_read_tokens
      ``usage.output_tokens`` → tokens_output
    - ``item.completed`` with ``item.type == "command_execution"`` or
      ``item.type == "file_change"``: counted in tool_calls.

    Defensive: an unparseable line is skipped. Null vs zero is preserved
    (None means the key was absent; 0 means it was present with value 0).
    """
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

        event_type = event.get("type")

        if event_type == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")

            if item_type == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text:
                    # Accumulate all agent messages (may be multiple turns).
                    if out.result_text:
                        out.result_text += "\n\n" + text
                    else:
                        out.result_text = text

            elif item_type in ("command_execution", "file_change"):
                # Count tool calls by type.
                out.tool_calls[item_type] = out.tool_calls.get(item_type, 0) + 1

        elif event_type == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                out.tokens_input = _int_or_none(usage.get("input_tokens"))
                out.tokens_output = _int_or_none(usage.get("output_tokens"))
                out.cache_read_tokens = _int_or_none(usage.get("cached_input_tokens"))

    return out


def _int_or_none(value: Any) -> Optional[int]:
    """Return ``value`` if it is a non-bool int, else ``None``."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


# ── Factory ────────────────────────────────────────────────────────────


def factory(model: str) -> CodexBackend:
    return CodexBackend(model)
