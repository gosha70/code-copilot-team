# benchmark_runner.backends.claude_code — Claude Code headless backend.
#
# Spawns ``claude -p "<prompt>"`` in the worktree (launcher mode by
# default — full autodiscovery, OAuth/keychain auth) and captures the
# structured JSON output.
#
# File editing is delegated to Claude Code's internal Edit tool — the
# adapter's prepare_task placed the starter files in the worktree, the
# backend tells Claude what to do, and Claude Code edits in place.
#
# Provider routing (per spec.md "Backends vs providers"):
# Claude Code itself routes its model calls to whatever the user has
# configured via ANTHROPIC_BASE_URL + friends (per
# https://code.claude.com/docs/en/llm-gateway). The harness *records*
# these env vars in backend_metadata so reports can distinguish
# Anthropic-API runs from gateway-routed runs (vLLM, Ollama, LM
# Studio, OpenRouter). It does NOT set them — provider configuration
# is the user's responsibility, or eventually CCT's standalone
# provider-config feature (specs/provider-config/).
#
# Invocation mode:
# - Default: launcher (no --bare) — full autodiscovery + OAuth/keychain.
#   Measures real product behavior. The user's hooks/skills/MCP/auto
#   memory/CLAUDE.md all participate.
# - Opt-in: CCT_CLAUDE_BARE=1 -> --bare flag passed. Skips OAuth/keychain
#   reads (requires ANTHROPIC_API_KEY). Useful for cross-machine
#   reproducibility (CI, controlled comparisons). The chosen mode is
#   recorded in backend_metadata.claude_code_invocation.
#
# The transcript JSON shape isn't fully spec'd in the public docs, so
# the parser uses defensive field-name fallbacks (input_tokens vs
# prompt_tokens, output_tokens vs completion_tokens, etc.) and treats
# every count as Optional[int] — null when absent, never fabricated.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from ..contracts import BackendResult, RunContext

BACKEND_FAMILY = "claude-code"

# Env vars (canonical names — referenced by README + tests).
BARE_OPT_IN_ENV_VAR = "CCT_CLAUDE_BARE"
EFFORT_OPT_IN_ENV_VAR = "CCT_CLAUDE_EFFORT"
TIMEOUT_OPT_IN_ENV_VAR = "CCT_CLAUDE_TIMEOUT_SECONDS"
GATEWAY_BASE_URL_ENV_VAR = "ANTHROPIC_BASE_URL"
GATEWAY_AUTH_TOKEN_ENV_VAR = "ANTHROPIC_AUTH_TOKEN"

# Values Claude Code's ``--effort`` CLI flag accepts. Surfaced as a
# probe/tuning knob — NOT defaulted to anything by the harness. Higher
# levels give the model more thinking + response budget; useful for
# verbose-thinking local models like qwen3.6:27b that exhaust default
# budgets mid-thinking. Whether ``--effort`` actually propagates to
# non-Anthropic backends (Ollama, vLLM, …) routed via a gateway is
# untested and provider-specific.
VALID_EFFORT_LEVELS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})

# Conservative default; per-task adapters override via RunContext.timeout_seconds.
_DEFAULT_TIMEOUT_SECONDS = 600

# Default tools to allow non-interactively. The adapter's prompt tells
# the model what to edit; we let Claude Code use Read+Edit+Bash without
# prompting.
_DEFAULT_ALLOWED_TOOLS = "Read,Edit,Bash"


class InvalidClaudeTimeoutError(ValueError):
    """Raised when ``CCT_CLAUDE_TIMEOUT_SECONDS`` is set to a non-positive-integer value.

    Reason this knob exists: the harness's default subprocess timeout
    of 600s is tight for slow local models — qwen3.6:27b on multi-turn
    agent loops can run >10 min for one attempt. The flag lets users
    bump the budget per-candidate via the compare-config ``env`` block.
    Failing loud on bad values keeps run records reproducible.
    """


class InvalidClaudeEffortError(ValueError):
    """Raised when ``CCT_CLAUDE_EFFORT`` is set to a value Claude Code does not accept.

    Failing loud beats silently dropping a typo'd setting — the
    benchmark is meant to be reproducible, and a silently-ignored
    effort value would produce a run that looks like it ran with
    the requested level but actually didn't.
    """


class ClaudeCliNotFoundError(RuntimeError):
    pass


class ClaudeCodeBackend:
    """Spawns ``claude -p`` and captures structured output.

    Construction is cheap; the heavy work happens in ``run``. The model
    string (passed through the harness CLI's ``--model`` flag) is sent
    to Claude Code via ``--model``, so callers can use Anthropic's full
    IDs (``claude-sonnet-4-6``) or aliases (``sonnet``, ``opus``), or
    the served model name when routing through a gateway.
    """

    backend_id = BACKEND_FAMILY

    def __init__(
        self,
        model: str = "",
        *,
        cli_executable: str = "claude",
        allowed_tools: str = _DEFAULT_ALLOWED_TOOLS,
    ) -> None:
        self._model = model
        self._cli = cli_executable
        self._allowed_tools = allowed_tools

    # ── Backend protocol ───────────────────────────────────────────────

    def run(self, prompt: str, ctx: RunContext) -> BackendResult:
        if shutil.which(self._cli) is None:
            raise ClaudeCliNotFoundError(
                f"the claude-code backend needs the {self._cli!r} CLI on PATH; "
                f"install it from https://code.claude.com or override "
                f"--cli-executable in tests"
            )

        bare_mode = _bare_mode_enabled()
        effort = _effort_setting()  # may raise InvalidClaudeEffortError
        argv = self._build_argv(bare_mode=bare_mode, effort=effort)
        # Precedence: explicit ctx.timeout_seconds → CCT_CLAUDE_TIMEOUT_SECONDS
        # env override → built-in default. The env override is the
        # per-candidate knob for slow local models (set via the
        # compare-config ``env`` block). Discovered necessary on
        # 2026-05-16 when qwen3.6:27b consistently hit the 600s
        # default ceiling on multi-turn agent loops even though the
        # model + claude-code were both working correctly.
        timeout = ctx.timeout_seconds or _timeout_override() or _DEFAULT_TIMEOUT_SECONDS

        # Capture provider-routing env vars BEFORE the call (the user
        # may set them per-shell; we record what was true at run time).
        provider_endpoint = os.environ.get(GATEWAY_BASE_URL_ENV_VAR) or None
        auth_token_present = bool(os.environ.get(GATEWAY_AUTH_TOKEN_ENV_VAR))

        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                input=prompt,
                cwd=str(ctx.worktree),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env=self._build_env(),
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            return BackendResult(
                transcript_path=None,
                elapsed_seconds=elapsed,
                backend_metadata=_build_metadata(
                    model=self._model,
                    bare_mode=bare_mode,
                    effort=effort,
                    timeout_seconds=timeout,
                    provider_endpoint=provider_endpoint,
                    auth_token_present=auth_token_present,
                    session_id=None,
                    exit_code=None,
                    stderr_tail=(
                        exc.stderr.decode("utf-8", errors="replace")
                        if isinstance(exc.stderr, bytes)
                        else (exc.stderr or "")
                    ),
                    note=f"claude -p timed out after {timeout}s",
                ),
                failed_commands=1,
            )

        elapsed = time.monotonic() - started

        # Persist the raw transcript before parsing so an unparseable
        # response is still recoverable from the run-dir.
        attempt_dir = ctx.worktree.parent
        transcript_path = attempt_dir / "transcript.json"
        transcript_path.write_text(proc.stdout, encoding="utf-8")

        parsed = parse_transcript_json(proc.stdout)
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
            cache_write_tokens=parsed.cache_write_tokens,
            tool_calls=parsed.tool_calls,
            failed_commands=0 if proc.returncode == 0 else 1,
            backend_metadata=_build_metadata(
                model=self._model,
                bare_mode=bare_mode,
                effort=effort,
                timeout_seconds=timeout,
                provider_endpoint=provider_endpoint,
                auth_token_present=auth_token_present,
                session_id=parsed.session_id,
                exit_code=proc.returncode,
                stderr_tail=_tail(proc.stderr, 1024),
            ),
        )

    # ── Internals ──────────────────────────────────────────────────────

    def _build_argv(
        self, *, bare_mode: bool, effort: Optional[str] = None
    ) -> list[str]:
        argv = [
            self._cli,
            "-p",
            "--output-format", "json",
            "--permission-mode", "acceptEdits",
            "--allowedTools", self._allowed_tools,
        ]
        if bare_mode:
            # Per https://code.claude.com/docs/en/headless: --bare skips
            # OAuth/keychain (requires ANTHROPIC_API_KEY) and disables
            # autodiscovery of hooks/skills/plugins/MCP/CLAUDE.md.
            # Inserted after argv[0] to keep flag ordering stable.
            argv.insert(1, "--bare")
        if self._model:
            argv.extend(["--model", self._model])
        if effort:
            # Validated to be in VALID_EFFORT_LEVELS before reaching here
            # (see ``_effort_setting``). Untested whether ``--effort``
            # propagates beyond the Anthropic API into Ollama/vLLM
            # gateways — record-and-ship; correctness is empirical.
            argv.extend(["--effort", effort])
        return argv

    def _build_env(self) -> dict[str, str]:
        # Forward the host environment unchanged. We never read or echo
        # ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN — only their presence.
        return dict(os.environ)


# ── Module-level helpers ───────────────────────────────────────────────


def _bare_mode_enabled() -> bool:
    """``CCT_CLAUDE_BARE=1`` (or any truthy non-empty value) opts into ``--bare``.

    Default is launcher mode (no ``--bare``) so the harness measures
    real product behavior — Claude Code with its full autodiscovery
    plus the user's OAuth/keychain auth.
    """
    val = os.environ.get(BARE_OPT_IN_ENV_VAR, "")
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _timeout_override() -> Optional[int]:
    """Resolve a per-attempt timeout (seconds) from the environment.

    Returns the positive integer when set, ``None`` when unset (so the
    caller falls through to ``_DEFAULT_TIMEOUT_SECONDS``). Raises
    ``InvalidClaudeTimeoutError`` on non-numeric or non-positive
    values — silently dropping a bad value would let a typo'd
    setting masquerade as the default budget.

    This is the per-candidate knob for slow local models (set via the
    compare-config ``env`` block). The 600s default is fine for
    cloud-hosted models like sonnet on Anthropic API; local 27B+
    models on multi-turn agent loops may need 1800-3600s.
    """
    val = os.environ.get(TIMEOUT_OPT_IN_ENV_VAR, "").strip()
    if not val:
        return None
    try:
        seconds = int(val)
    except ValueError as exc:
        raise InvalidClaudeTimeoutError(
            f"{TIMEOUT_OPT_IN_ENV_VAR}={val!r} is not an integer. "
            f"Expected a positive integer number of seconds (e.g. 1800 for 30 min)."
        ) from exc
    if seconds <= 0:
        raise InvalidClaudeTimeoutError(
            f"{TIMEOUT_OPT_IN_ENV_VAR}={val!r} must be positive; got {seconds}."
        )
    return seconds


def _effort_setting() -> Optional[str]:
    """Resolve the value to pass to ``claude -p --effort`` from the env.

    Returns the string when set + valid, ``None`` when unset (in which
    case ``--effort`` is omitted entirely and Claude Code picks its
    own default). Raises ``InvalidClaudeEffortError`` when set to a
    value Claude Code does not accept — fail loud, not silent-drop.

    This is a probe/tuning knob (see ``VALID_EFFORT_LEVELS``). NOT
    defaulted to anything by the harness — users opt in per-candidate
    via the compare-config ``env`` block (``CCT_CLAUDE_EFFORT=max``).
    """
    val = os.environ.get(EFFORT_OPT_IN_ENV_VAR, "").strip()
    if not val:
        return None
    if val not in VALID_EFFORT_LEVELS:
        raise InvalidClaudeEffortError(
            f"{EFFORT_OPT_IN_ENV_VAR}={val!r} is not a valid Claude Code "
            f"effort level. Allowed values: {sorted(VALID_EFFORT_LEVELS)}"
        )
    return val


def _build_metadata(
    *,
    model: str,
    bare_mode: bool,
    provider_endpoint: Optional[str],
    auth_token_present: bool,
    session_id: Optional[str],
    exit_code: Optional[int],
    stderr_tail: str,
    effort: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Assemble the ``backend_metadata`` dict with provider-routing record.

    Key invariant: ``ANTHROPIC_AUTH_TOKEN`` value is NEVER recorded —
    only its presence as a boolean. Same for any future API-key fields.

    ``effort`` is included as ``None`` when unset, so a successful
    run-record always carries the audit answer to "was --effort
    passed and at what level?"
    """
    meta: dict[str, Any] = {
        "family": BACKEND_FAMILY,
        "model": model,
        "claude_code_invocation": "bare" if bare_mode else "launcher",
        "effort": effort,  # None == --effort flag omitted
        "timeout_seconds": timeout_seconds,  # effective subprocess timeout
        "provider_endpoint": provider_endpoint,  # full URL, or None
        "anthropic_auth_token_present": auth_token_present,  # bool only
        "session_id": session_id,
        "exit_code": exit_code,
        "stderr_tail": stderr_tail,
    }
    if note is not None:
        meta["note"] = note
    return meta


# ── Transcript parser (pure function for testability) ─────────────────


class _Parsed:
    __slots__ = (
        "result_text",
        "session_id",
        "tokens_input",
        "tokens_output",
        "cache_read_tokens",
        "cache_write_tokens",
        "tool_calls",
    )

    def __init__(self) -> None:
        self.result_text: str = ""
        self.session_id: Optional[str] = None
        self.tokens_input: Optional[int] = None
        self.tokens_output: Optional[int] = None
        self.cache_read_tokens: Optional[int] = None
        self.cache_write_tokens: Optional[int] = None
        self.tool_calls: dict[str, int] = {}


# Field-name fallbacks. The Claude Code headless docs list ``result``
# and ``session_id`` explicitly but don't enumerate the usage block;
# we accept both Anthropic-shape and OpenAI-shape names defensively.
_INPUT_TOKEN_KEYS = ("input_tokens", "prompt_tokens", "tokens_input")
_OUTPUT_TOKEN_KEYS = ("output_tokens", "completion_tokens", "tokens_output")
_CACHE_READ_KEYS = ("cache_read_input_tokens", "cache_read_tokens")
_CACHE_WRITE_KEYS = (
    "cache_creation_input_tokens",
    "cache_write_tokens",
    "cache_creation_tokens",
)


def parse_transcript_json(stdout: str) -> _Parsed:
    """Parse the JSON emitted by ``claude --output-format json``.

    Defensive: an unparseable transcript still produces a populated
    ``_Parsed`` (empty result, all token fields None). Callers should
    surface the raw transcript path so the user can investigate.
    """
    out = _Parsed()
    if not stdout.strip():
        return out

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        # Some shells/cli versions emit a stream-json by line even
        # without --output-format stream-json; try the last JSON object
        # on its own line as a fallback.
        last_line = _last_json_line(stdout)
        if last_line is None:
            return out
        payload = last_line

    if not isinstance(payload, dict):
        return out

    out.result_text = str(payload.get("result", "") or "")
    sess = payload.get("session_id")
    if isinstance(sess, str):
        out.session_id = sess

    usage = payload.get("usage") or {}
    if isinstance(usage, dict):
        out.tokens_input = _first_int(usage, _INPUT_TOKEN_KEYS)
        out.tokens_output = _first_int(usage, _OUTPUT_TOKEN_KEYS)
        out.cache_read_tokens = _first_int(usage, _CACHE_READ_KEYS)
        out.cache_write_tokens = _first_int(usage, _CACHE_WRITE_KEYS)

    # Some json outputs put usage at the top level (older versions);
    # try there too if the nested usage block didn't yield anything.
    if out.tokens_input is None:
        out.tokens_input = _first_int(payload, _INPUT_TOKEN_KEYS)
    if out.tokens_output is None:
        out.tokens_output = _first_int(payload, _OUTPUT_TOKEN_KEYS)

    out.tool_calls = _extract_tool_calls(payload)
    return out


def _first_int(d: Mapping[str, Any], keys: tuple[str, ...]) -> Optional[int]:
    for key in keys:
        v = d.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def _extract_tool_calls(payload: Mapping[str, Any]) -> dict[str, int]:
    """Best-effort tool-call extraction.

    Tolerates ``tool_uses`` (list of dicts with a ``name`` field),
    ``tools_called`` (free-form list), or ``tool_calls``. Absent all,
    returns ``{}``.
    """
    counts: dict[str, int] = {}
    for key in ("tool_uses", "tools_called", "tool_calls"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            name: Optional[str] = None
            if isinstance(entry, str):
                name = entry
            elif isinstance(entry, dict):
                name = entry.get("name") or entry.get("tool")
            if isinstance(name, str) and name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def _last_json_line(stdout: str) -> Optional[Mapping[str, Any]]:
    """Return the last parseable JSON object from a multi-line stream."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _tail(text: str, max_chars: int) -> str:
    if not text:
        return ""
    return text[-max_chars:] if len(text) > max_chars else text


def factory(model: str) -> ClaudeCodeBackend:
    return ClaudeCodeBackend(model)
