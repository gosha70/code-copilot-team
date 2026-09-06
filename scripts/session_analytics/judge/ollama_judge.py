# session_analytics.judge.ollama_judge — local-only Ollama turn judge.
#
# The privacy-preserving default: talks to a local Ollama server over HTTP via
# stdlib urllib (no third-party dependency, so the unit suite stays dep-free).
# Nothing leaves the machine. Ollama's /api/chat with format:"json" coaxes a
# JSON object out of the model; parse.py validates it against the rubric.

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

from ..config import load_config
from .contracts import (
    PARSE_BACKEND_ERROR,
    JudgeAnswerTruncated,
    JudgeTransportError,
    Rubric,
    TurnContext,
    TurnLabels,
)
from .parse import parse_labels

_log = logging.getLogger(__name__)

JUDGE_FAMILY = "ollama"
_DEFAULT_MODEL = "llama3"
_TIMEOUT_SECONDS = 120
#: Ollama's default context window is small (4k tokens on most models)
#: and a prompt that exceeds it is TRUNCATED FROM THE FRONT without any
#: error — a whole-session prompt would lose its instructions and most
#: of the transcript silently. So the window is sized to the prompt:
#: a rough chars-per-token estimate plus headroom for the answer, within
#: a ceiling that keeps memory use sane on a laptop.
_CHARS_PER_TOKEN = 3
_CTX_ANSWER_HEADROOM = 4096
_CTX_MIN = 4096
_CTX_MAX = 32768
#: Hard cap on the answer. Without it a small model that fails to close
#: its JSON keeps generating until the context is full — a 10-minute
#: hang on a laptop — and the caller cannot tell that from a slow model.
#: Reasoning models (gpt-oss, qwen3) spend this budget on their hidden
#: thinking too, so it is not tight.
_ANSWER_MAX_TOKENS = 8192
_DONE_REASON_LENGTH = "length"


class OllamaJudge:
    judge_id = JUDGE_FAMILY

    def __init__(self, model: str = "", *, base_url: Optional[str] = None) -> None:
        self._model = model or _DEFAULT_MODEL
        self._base_url = (base_url or load_config().judge.ollama_url).rstrip("/")

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
        prompt = rubric.prompt_template.format(
            role=ctx.role, prev_text=ctx.prev_text or "", text=ctx.text or ""
        )
        try:
            content = self.complete(prompt)
        except JudgeTransportError as exc:
            return _err(rubric, self.judge_id, self._model, str(exc))
        return parse_labels(content, rubric, judge_id=self.judge_id, judge_model=self._model)

    def complete(self, prompt: str, *, timeout: int = _TIMEOUT_SECONDS) -> str:
        num_ctx = min(
            _CTX_MAX,
            max(_CTX_MIN, len(prompt) // _CHARS_PER_TOKEN + _CTX_ANSWER_HEADROOM),
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": num_ctx,
                "num_predict": _ANSWER_MAX_TOKENS,
            },
        }
        try:
            raw = self._post("/api/chat", payload, timeout=timeout)
        except urllib.error.HTTPError as exc:
            # Ollama says WHY in the body ("model 'llama3' not found, try
            # pulling it first") — far more useful than "404".
            detail = _http_error_detail(exc)
            _log.warning("ollama judge call failed: %s", detail)
            raise JudgeTransportError(detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _log.warning("ollama judge call failed: %s", exc)
            raise JudgeTransportError(str(exc)) from exc
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        content = (obj.get("message") or {}).get("content", "") or obj.get("response", "")
        if not content.strip() and not obj.get("done_reason"):
            # Seen when a large model cannot fit the requested window in
            # memory: Ollama answers 200 with an empty message and no
            # done_reason at all. Name it, so the user is not left with
            # "unparseable" for what is an out-of-memory load.
            raise JudgeTransportError(
                f"{self._model} returned an empty answer with no completion reason at "
                f"num_ctx={num_ctx} — usually the model did not fit in memory at that "
                "context size; use a smaller model for whole-session analysis."
            )
        if not content.strip() and obj.get("done_reason") == _DONE_REASON_LENGTH:
            # A reasoning model that thought until the cap and never got
            # to its answer. Saying so beats returning "" and letting the
            # parser report "unparseable" as if the model had answered.
            raise JudgeTransportError(
                f"{self._model} used its whole {_ANSWER_MAX_TOKENS}-token answer budget "
                "on hidden reasoning and produced no answer; pick a non-reasoning "
                "model (llama3.2, qwen2.5-coder) for this job."
            )
        if obj.get("done_reason") == _DONE_REASON_LENGTH:
            # Answered, but ran out of budget before closing the document
            # (seen: 90+ coaching rows for a 350-turn session). The parser
            # would call this "unparseable"; the truth is more useful.
            raise JudgeAnswerTruncated(
                f"{self._model} hit its {_ANSWER_MAX_TOKENS}-token answer cap before "
                "finishing — it did not keep to the list limits in the prompt; "
                "a stronger model usually does.",
                partial=content,
            )
        return content

    def _post(self, path: str, payload: dict, *, timeout: int = _TIMEOUT_SECONDS) -> str:
        req = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8"))
        msg = body.get("error") if isinstance(body, dict) else None
        if msg:
            return f"HTTP {exc.code}: {msg}"
    except (ValueError, OSError):
        pass
    return str(exc)


def _err(rubric: Rubric, judge_id: str, model: str, msg: str) -> TurnLabels:
    return TurnLabels(
        bool_labels={label: None for label in rubric.bool_labels},
        sentiment=None,
        interaction_quality=None,
        parse_status=PARSE_BACKEND_ERROR,
        judge_id=judge_id,
        judge_model=model,
        metadata={"error": msg[:300]},
    )


def factory(model: str) -> OllamaJudge:
    return OllamaJudge(model)
