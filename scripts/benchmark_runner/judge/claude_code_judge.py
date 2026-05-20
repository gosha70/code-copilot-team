# benchmark_runner.judge.claude_code_judge — claude-code-headless Judge.
#
# Wraps the same ``claude -p`` headless invocation the claude_code
# backend uses, but configured for rating rather than editing:
# tools disabled (the judge produces a JSON rating, not file edits),
# permission mode irrelevant (no edits to permit), output-format JSON.
#
# Determinism contract (peer-reviewed 2026-05-20). The local ``claude``
# CLI exposes ``--model`` / ``--fallback-model`` only — re-confirmed
# 2026-05-20 against the installed CLI. No ``--temperature``, no
# ``--seed``. The judge therefore records:
#     temperature: None, seed: None,
#     temperature_control: "unsupported", seed_control: "unsupported"
# Re-run stability is empirical, surfaced by the calibration step's
# Spearman against human labels. NEVER silently claim T=0.
#
# Provider routing (mirrors the backend): the judge reads
# ``ANTHROPIC_BASE_URL`` + ``ANTHROPIC_AUTH_TOKEN`` from the env to
# record whether routing happened, but does NOT set or log those
# values — presence boolean only.
#
# Subprocess hardening: ``start_new_session=True`` + ``os.killpg`` on
# timeout, mirroring the backend's Bug #6 fix (Claude Code is a Node
# binary that spawns MCP/hook grandchildren; killing the immediate
# child alone leaves stdout/stderr FDs open and blocks ``communicate``).

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from .contracts import (
    JUDGE_RATING_MAX,
    JUDGE_RATING_MIN,
    SEED_CONTROL_UNSUPPORTED,
    TEMPERATURE_CONTROL_UNSUPPORTED,
    DimensionRating,
    JudgeInput,
    JudgeInvocation,
    JudgeResult,
)

JUDGE_FAMILY = "claude-code-judge"
JUDGE_BACKEND_ID = "claude-code"

# Env vars — judge-specific so backend and judge can coexist with
# different bare/timeout settings on the same machine. Names mirror
# the backend's ``CCT_CLAUDE_*`` convention but use ``CCT_JUDGE_*``.
BARE_OPT_IN_ENV_VAR = "CCT_JUDGE_BARE"
TIMEOUT_OPT_IN_ENV_VAR = "CCT_JUDGE_TIMEOUT_SECONDS"

# Provider-routing env (shared with the backend — same gateway env
# the user already configured for backend runs).
GATEWAY_BASE_URL_ENV_VAR = "ANTHROPIC_BASE_URL"
GATEWAY_AUTH_TOKEN_ENV_VAR = "ANTHROPIC_AUTH_TOKEN"

# Default judge timeout. Tighter than the backend's 600s because the
# judge does no file editing — typical claude_code rating call on
# sonnet completes in 5–60s. Overridable per-attempt via
# ``CCT_JUDGE_TIMEOUT_SECONDS``.
_DEFAULT_TIMEOUT_SECONDS = 300

_STDERR_TAIL_CHARS = 1024


# ── Parse-status sentinels ─────────────────────────────────────────────
# What the parser concluded. Distinct strings so the report can tell
# "judge said it doesn't apply" apart from "judge output was garbage."
# Recorded in ``JudgeResult.judge_metadata["parse_status"]``.
PARSE_STATUS_OK = "ok"
PARSE_STATUS_OUTER_UNPARSEABLE = "outer_unparseable"
PARSE_STATUS_INNER_UNPARSEABLE = "inner_unparseable"
PARSE_STATUS_MISSING_DIMENSIONS = "missing_dimensions"
PARSE_STATUS_OUT_OF_BAND_RATING = "out_of_band_rating"


class ClaudeCliNotFoundError(RuntimeError):
    pass


class InvalidJudgeTimeoutError(ValueError):
    """Raised when ``CCT_JUDGE_TIMEOUT_SECONDS`` is non-positive-integer.

    Fail-loud on bad values — silently dropping a typo'd timeout
    would mask a configuration error and change which judge results
    were used in calibration.
    """


# ── Judge implementation ───────────────────────────────────────────────


class ClaudeCodeJudge:
    """Rates one attempt by invoking ``claude -p`` headlessly.

    Construction is cheap; the work happens in ``rate``. The model
    string is the same alias convention as the backend
    (``sonnet`` / ``opus`` / a full model ID like
    ``claude-sonnet-4-6``).

    The judge does NOT modify the attempt directory. It reads
    ``attempt.diff_path`` + ``attempt.prompt_path`` + uses
    ``attempt.verify_output`` to render the rubric prompt, invokes
    claude with tools disabled, and returns a ``JudgeResult``. The
    caller (runner) is responsible for writing ``judge.json``.
    """

    judge_id = JUDGE_FAMILY

    def __init__(
        self,
        model: str = "sonnet",
        *,
        cli_executable: str = "claude",
    ) -> None:
        self._model = model
        self._cli = cli_executable

    # ── Judge protocol ─────────────────────────────────────────────────

    def rate(self, attempt: JudgeInput) -> JudgeResult:
        if shutil.which(self._cli) is None:
            raise ClaudeCliNotFoundError(
                f"the claude-code judge needs the {self._cli!r} CLI on PATH; "
                f"install it from https://code.claude.com or override "
                f"--cli-executable in tests"
            )

        bare_mode = _bare_mode_enabled()
        timeout = _timeout_override() or _DEFAULT_TIMEOUT_SECONDS
        argv = self._build_argv(bare_mode=bare_mode)

        # Capture provider-routing env vars BEFORE the call — presence
        # boolean only, never the URL/token.
        provider_endpoint_present = bool(os.environ.get(GATEWAY_BASE_URL_ENV_VAR))

        # Render the rubric prompt with attempt evidence. The rubric
        # is data (loaded by the caller); the judge just substitutes.
        rendered_prompt = _render_prompt(attempt)
        prompt_sha256 = hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest()

        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(attempt.attempt_dir),
            text=True,
            env=dict(os.environ),
            start_new_session=True,  # see backend.claude_code Bug #6
        )
        stderr_tail = ""
        timed_out = False
        try:
            stdout_data, stderr_data = proc.communicate(
                input=rendered_prompt, timeout=timeout
            )
            stderr_tail = _tail(stderr_data or "", _STDERR_TAIL_CHARS)
            exit_code: Optional[int] = proc.returncode
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass  # already dead — race with normal exit
            timed_out = True
            stdout_data = ""
            try:
                _stdout_late, stderr_late = proc.communicate(timeout=10)
                stderr_tail = _tail(stderr_late or "", _STDERR_TAIL_CHARS)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
            exit_code = None

        parsed = parse_judge_output(stdout_data or "", attempt.rubric.dimensions)

        ratings: dict[str, DimensionRating] = {}
        for dim in attempt.rubric.dimensions:
            raw = parsed.ratings.get(dim)
            ratings[dim] = _make_dimension_rating(
                dim,
                raw,
                prompt_sha256=prompt_sha256,
                parse_status=parsed.status,
                timed_out=timed_out,
            )

        invocation = JudgeInvocation(
            model=self._model,
            temperature=None,
            seed=None,
            temperature_control=TEMPERATURE_CONTROL_UNSUPPORTED,
            seed_control=SEED_CONTROL_UNSUPPORTED,
            provider_endpoint_present=provider_endpoint_present,
        )

        metadata: dict[str, Any] = {
            "claude_code_invocation": "bare" if bare_mode else "launcher",
            "timeout_seconds": timeout,
            "exit_code": exit_code,
            "stderr_tail": stderr_tail,
            "parse_status": parsed.status,
            "session_id": parsed.session_id,
        }
        if parsed.note:
            metadata["parse_note"] = parsed.note
        if timed_out:
            metadata["note"] = f"claude -p judge timed out after {timeout}s (process group killed)"

        return JudgeResult(
            judge_id=self.judge_id,
            judge_model=self._model,
            judge_backend_id=JUDGE_BACKEND_ID,
            rubric_name=attempt.rubric.name,
            ratings=ratings,
            invocation=invocation,
            tokens_input=parsed.tokens_input,
            tokens_output=parsed.tokens_output,
            judge_metadata=metadata,
        )

    # ── Internals ──────────────────────────────────────────────────────

    def _build_argv(self, *, bare_mode: bool) -> list[str]:
        argv = [
            self._cli,
            "-p",
            "--output-format", "json",
            # Disable all built-in tools — the judge produces a JSON
            # rating, not file edits. Per ``claude --help``:
            #   --tools <tools...>  Specify the list of available tools
            #     from the built-in set. Use "" to disable all tools,
            #     "default" to use all tools, or specify tool names.
            # ``--tools ""`` is the documented disable; ``--allowedTools``
            # is a different surface (controls which of the available
            # tools are permitted to run) and would NOT prevent the
            # judge from offering tools at all. Peer review 2026-05-20.
            "--tools", "",
        ]
        if bare_mode:
            argv.insert(1, "--bare")
        if self._model:
            argv.extend(["--model", self._model])
        # Deliberate omissions (peer-reviewed):
        # NO --temperature (CLI does not expose).
        # NO --seed (CLI does not expose).
        # NO --permission-mode (judge edits nothing).
        # NO --allowedTools (no separate reason to allow specific tools;
        #                   the available-tool set is already empty via
        #                   ``--tools ""``).
        return argv


# ── Helpers ────────────────────────────────────────────────────────────


def _bare_mode_enabled() -> bool:
    val = os.environ.get(BARE_OPT_IN_ENV_VAR, "")
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _timeout_override() -> Optional[int]:
    """Resolve ``CCT_JUDGE_TIMEOUT_SECONDS`` to a positive int or None.

    Raises ``InvalidJudgeTimeoutError`` on non-numeric or non-positive
    values — silently dropping would let a typo'd setting masquerade
    as the default budget and silently change which judge results
    were considered timely.
    """
    val = os.environ.get(TIMEOUT_OPT_IN_ENV_VAR, "").strip()
    if not val:
        return None
    try:
        seconds = int(val)
    except ValueError as exc:
        raise InvalidJudgeTimeoutError(
            f"{TIMEOUT_OPT_IN_ENV_VAR}={val!r} is not an integer. "
            f"Expected a positive integer number of seconds."
        ) from exc
    if seconds <= 0:
        raise InvalidJudgeTimeoutError(
            f"{TIMEOUT_OPT_IN_ENV_VAR}={val!r} must be positive; got {seconds}."
        )
    return seconds


def _render_prompt(attempt: JudgeInput) -> str:
    """Substitute attempt evidence into the rubric prompt template.

    Reads ``attempt.diff_path`` and ``attempt.prompt_path`` and
    formats the template with ``{task_id}``, ``{benchmark_id}``,
    ``{prompt}``, ``{diff}``, ``{verify_output}``.

    The rubric loader (TB1.3+) is responsible for pre-rendering any
    ``{rubric_dimensions_block}`` placeholder + escaping literal
    curly braces in the template's JSON-example sections; the judge
    here just calls ``str.format`` and propagates a KeyError if the
    caller passed an under-rendered template.
    """
    diff_text = Path(attempt.diff_path).read_text(encoding="utf-8")
    prompt_text = Path(attempt.prompt_path).read_text(encoding="utf-8")
    return attempt.rubric.prompt_template.format(
        task_id=attempt.task_id,
        benchmark_id=attempt.benchmark_id,
        prompt=prompt_text,
        diff=diff_text,
        verify_output=attempt.verify_output,
    )


def _tail(text: str, max_chars: int) -> str:
    if not text:
        return ""
    return text[-max_chars:] if len(text) > max_chars else text


def _make_dimension_rating(
    dim: str,
    raw: Optional[Mapping[str, Any]],
    *,
    prompt_sha256: str,
    parse_status: str,
    timed_out: bool,
) -> DimensionRating:
    """Build a DimensionRating from the parser's per-dim raw dict.

    Defensive paths (rating=None + diagnostic explanation):
      - Judge timed out.
      - Dimension missing from parsed output.
      - Rating value is out of band (the contract dataclass would
        reject; catch here and substitute null with explanation so
        one bad rating doesn't crash the whole judge call).
    """
    if timed_out:
        return DimensionRating(
            rating=None,
            explanation="judge timed out before producing a rating for this dimension",
            prompt_sha256=prompt_sha256,
        )
    if raw is None:
        return DimensionRating(
            rating=None,
            explanation=f"judge output missing dimension {dim!r}: {parse_status}",
            prompt_sha256=prompt_sha256,
        )
    rating_val = raw.get("rating")
    explanation = str(raw.get("explanation", "") or "")
    if rating_val is None:
        # Judge legitimately reported structural inapplicability.
        return DimensionRating(
            rating=None,
            explanation=explanation or "judge reported dimension as inapplicable",
            prompt_sha256=prompt_sha256,
        )
    # bool is a subclass of int — the contract dataclass would
    # reject it. Catch here to surface as a parse anomaly rather
    # than crashing the whole call.
    if isinstance(rating_val, bool) or not isinstance(rating_val, int):
        return DimensionRating(
            rating=None,
            explanation=(
                f"judge returned non-integer rating "
                f"{type(rating_val).__name__} {rating_val!r}; recorded as null"
            ),
            prompt_sha256=prompt_sha256,
        )
    if not (JUDGE_RATING_MIN <= rating_val <= JUDGE_RATING_MAX):
        return DimensionRating(
            rating=None,
            explanation=(
                f"judge returned out-of-band rating {rating_val} "
                f"(expected {JUDGE_RATING_MIN}..{JUDGE_RATING_MAX}); recorded as null"
            ),
            prompt_sha256=prompt_sha256,
        )
    return DimensionRating(
        rating=rating_val,
        explanation=explanation,
        prompt_sha256=prompt_sha256,
    )


# ── Parser (pure function for testability) ─────────────────────────────


class _ParsedJudge:
    __slots__ = (
        "ratings",
        "tokens_input",
        "tokens_output",
        "session_id",
        "status",
        "note",
    )

    def __init__(self) -> None:
        self.ratings: dict[str, Mapping[str, Any]] = {}
        self.tokens_input: Optional[int] = None
        self.tokens_output: Optional[int] = None
        self.session_id: Optional[str] = None
        self.status: str = PARSE_STATUS_OK
        self.note: str = ""


# Token-field fallbacks reused from the backend's defensive shape.
_INPUT_TOKEN_KEYS = ("input_tokens", "prompt_tokens", "tokens_input")
_OUTPUT_TOKEN_KEYS = ("output_tokens", "completion_tokens", "tokens_output")


def parse_judge_output(stdout: str, dimensions: tuple[str, ...]) -> _ParsedJudge:
    """Parse the claude wrapper JSON and the inner ratings JSON.

    The wrapper is what ``claude --output-format json`` emits:
    ``{"result": "<inner>", "usage": {...}, "session_id": "..."}``.
    The inner ``result`` is the LLM's free-text response, which the
    rubric template asks the model to format as
    ``{"ratings": {"<dim>": {"rating": int|null, "explanation": str}, ...}}``.

    Returns a populated ``_ParsedJudge`` in every case — the
    ``status`` field tells the caller what happened. Never raises
    on malformed output; the judge's job is to surface a result
    even when the LLM did not cooperate.
    """
    out = _ParsedJudge()
    if not stdout.strip():
        out.status = PARSE_STATUS_OUTER_UNPARSEABLE
        out.note = "empty stdout from claude"
        return out

    try:
        wrapper = json.loads(stdout)
    except json.JSONDecodeError as exc:
        out.status = PARSE_STATUS_OUTER_UNPARSEABLE
        out.note = f"claude wrapper not JSON: {exc}"
        return out
    if not isinstance(wrapper, dict):
        out.status = PARSE_STATUS_OUTER_UNPARSEABLE
        out.note = f"claude wrapper not a JSON object (got {type(wrapper).__name__})"
        return out

    # Token usage (best-effort, mirrors backend's defensive shape).
    usage = wrapper.get("usage") or {}
    if isinstance(usage, dict):
        out.tokens_input = _first_int(usage, _INPUT_TOKEN_KEYS)
        out.tokens_output = _first_int(usage, _OUTPUT_TOKEN_KEYS)
    if out.tokens_input is None:
        out.tokens_input = _first_int(wrapper, _INPUT_TOKEN_KEYS)
    if out.tokens_output is None:
        out.tokens_output = _first_int(wrapper, _OUTPUT_TOKEN_KEYS)
    sess = wrapper.get("session_id")
    if isinstance(sess, str):
        out.session_id = sess

    inner_text = str(wrapper.get("result", "") or "")
    if not inner_text.strip():
        out.status = PARSE_STATUS_INNER_UNPARSEABLE
        out.note = "claude result field empty"
        return out

    try:
        inner = json.loads(inner_text)
    except json.JSONDecodeError as exc:
        out.status = PARSE_STATUS_INNER_UNPARSEABLE
        out.note = f"inner ratings JSON not parseable: {exc}"
        return out
    if not isinstance(inner, dict):
        out.status = PARSE_STATUS_INNER_UNPARSEABLE
        out.note = (
            f"inner ratings JSON not an object (got {type(inner).__name__})"
        )
        return out

    ratings_block = inner.get("ratings")
    if not isinstance(ratings_block, dict):
        out.status = PARSE_STATUS_INNER_UNPARSEABLE
        out.note = "inner JSON missing 'ratings' object"
        return out

    missing: list[str] = []
    out_of_band: list[str] = []
    for dim in dimensions:
        entry = ratings_block.get(dim)
        if not isinstance(entry, dict):
            missing.append(dim)
            continue
        rating = entry.get("rating")
        if rating is not None:
            # Caller (``_make_dimension_rating``) re-validates and may
            # downgrade to null+explanation. Flag here so the parse
            # status reflects "the model returned values we had to
            # reject," not just "looks fine."
            if isinstance(rating, bool) or not isinstance(rating, int):
                out_of_band.append(dim)
            elif not (JUDGE_RATING_MIN <= rating <= JUDGE_RATING_MAX):
                out_of_band.append(dim)
        out.ratings[dim] = entry

    if missing:
        out.status = PARSE_STATUS_MISSING_DIMENSIONS
        out.note = f"missing dimensions: {missing}"
    elif out_of_band:
        out.status = PARSE_STATUS_OUT_OF_BAND_RATING
        out.note = f"out-of-band ratings on: {out_of_band}"
    # else: status stays PARSE_STATUS_OK

    return out


def _first_int(d: Mapping[str, Any], keys: tuple[str, ...]) -> Optional[int]:
    for key in keys:
        v = d.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
    return None


def factory(model: str) -> ClaudeCodeJudge:
    return ClaudeCodeJudge(model)
