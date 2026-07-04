# session_analytics.judge.session_judge — claude-code-headless turn judge.
#
# Reuses the proven headless `claude -p --output-format json` invocation
# pattern from benchmark_runner.judge.claude_code_judge: tools disabled
# (`--tools ""`), start_new_session=True + os.killpg on timeout (the Bug #6
# process-group kill — Claude Code spawns Node grandchildren whose open FDs
# block communicate() if only the immediate child is killed).
#
# NOTE: this is a cloud path unless the user routes ANTHROPIC_BASE_URL to a
# local gateway. It is explicit opt-in on the CLI (`--judge claude-code:...`);
# the default judge is the local-only OllamaJudge.

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
from typing import Optional

from .contracts import (
    PARSE_BACKEND_ERROR,
    PARSE_TIMEOUT,
    Rubric,
    TurnContext,
    TurnLabels,
)
from .parse import parse_labels

_log = logging.getLogger(__name__)

JUDGE_FAMILY = "claude-code"
_TIMEOUT_SECONDS = 120


class ClaudeCliNotFoundError(RuntimeError):
    pass


class ClaudeCodeSessionJudge:
    judge_id = JUDGE_FAMILY

    def __init__(self, model: str = "", *, cli_executable: str = "claude") -> None:
        # Empty model == use Claude Code's OWN default model (Opus 4.8 today):
        # the judge omits ``--model`` entirely so the CLI picks its default.
        self._model = model
        self._model_label = model or "claude-code-default"
        self._cli = cli_executable

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
        if shutil.which(self._cli) is None:
            raise ClaudeCliNotFoundError(
                f"the claude-code judge needs the {self._cli!r} CLI on PATH; "
                f"install from https://code.claude.com, or use --judge ollama:<model>."
            )
        prompt = rubric.prompt_template.format(
            role=ctx.role, prev_text=ctx.prev_text or "", text=ctx.text or ""
        )
        argv = [self._cli, "-p", "--output-format", "json", "--tools", ""]
        if self._model:
            argv += ["--model", self._model]

        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=dict(os.environ),
            start_new_session=True,  # see benchmark claude_code_judge Bug #6
        )
        try:
            stdout, _stderr = proc.communicate(input=prompt, timeout=_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            return _err(rubric, self.judge_id, self._model_label, PARSE_TIMEOUT, "judge timed out")

        content = _inner_result(stdout)
        if content is None:
            return _err(
                rubric, self.judge_id, self._model_label, PARSE_BACKEND_ERROR,
                "claude output not parseable",
            )
        return parse_labels(content, rubric, judge_id=self.judge_id, judge_model=self._model_label)


def _inner_result(stdout: str) -> Optional[str]:
    """Extract the inner result text from claude's --output-format json wrapper
    ({"result": "<text>", ...}); fall back to the raw stdout."""
    import json

    if not stdout or not stdout.strip():
        return None
    try:
        wrapper = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout
    if isinstance(wrapper, dict) and "result" in wrapper:
        return str(wrapper.get("result") or "")
    return stdout


def _err(rubric: Rubric, judge_id: str, model: str, status: str, msg: str) -> TurnLabels:
    return TurnLabels(
        bool_labels={label: None for label in rubric.bool_labels},
        sentiment=None,
        interaction_quality=None,
        parse_status=status,
        judge_id=judge_id,
        judge_model=model,
        metadata={"error": msg[:300]},
    )


def factory(model: str) -> ClaudeCodeSessionJudge:
    return ClaudeCodeSessionJudge(model)
