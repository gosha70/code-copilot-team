# session_analytics.judge.openai_judge — OpenAI-compatible turn judge.
#
# Works against ANY OpenAI-compatible Chat Completions endpoint — LM Studio
# (http://localhost:1234/v1), vLLM, OpenAI, Azure OpenAI, OpenRouter, etc. The
# base URL + optional API key come from config (.env: CCT_SA_JUDGE_BASE_URL /
# CCT_SA_JUDGE_API_KEY). Uses stdlib urllib so the unit suite stays dep-free;
# nothing is sent unless the user explicitly selects this backend + a base_url.

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

JUDGE_FAMILY = "openai"
_TIMEOUT_SECONDS = 120
#: Same runaway-generation guard as the Ollama backend.
_ANSWER_MAX_TOKENS = 4096
_FINISH_REASON_LENGTH = "length"
#: The OpenAI-compatible path prefix every server here uses (vLLM, LM
#: Studio, OpenAI, Azure's proxies). A base URL without it is completed.
_API_PREFIX = "/v1"
#: Qwen3-family "thinking" mode spends the answer budget on reasoning and
#: leaves `content` empty or truncated; vLLM turns it off per request
#: with this field. A server that rejects the field gets the request
#: again without it.
_NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}


def normalize_base_url(raw: str) -> str:
    """``http://host:8001`` → ``http://host:8001/v1``; a URL already
    ending in /v1 (or another explicit /vN) is kept; blank stays blank.
    The owner's first attempt was the bare host:port, which put every
    call at /chat/completions instead of /v1/chat/completions."""
    base = (raw or "").strip().rstrip("/")
    if not base:
        return ""
    # The full endpoint pasted from a working curl is a base URL too.
    for tail in ("/chat/completions", "/completions", "/models"):
        if base.endswith(tail):
            base = base[: -len(tail)]
            break
    from urllib.parse import urlsplit

    path = urlsplit(base).path
    if path.rstrip("/").split("/")[-1].startswith("v") and path.rstrip("/").split("/")[-1][1:].isdigit():
        return base
    return base + _API_PREFIX


class MissingBaseUrlError(ValueError):
    pass


class OpenAICompatJudge:
    judge_id = JUDGE_FAMILY

    def __init__(
        self,
        model: str = "",
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        cfg = load_config().judge
        self._model = model or "local-model"
        self._base_url = normalize_base_url(base_url if base_url is not None else cfg.base_url)
        self._api_key = api_key if api_key is not None else cfg.api_key

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
        self._require_base_url()
        prompt = rubric.prompt_template.format(
            role=ctx.role, prev_text=ctx.prev_text or "", text=ctx.text or ""
        )
        try:
            content = self.complete(prompt)
        except JudgeTransportError as exc:
            return _err(rubric, self.judge_id, self._model, str(exc))
        return parse_labels(content, rubric, judge_id=self.judge_id, judge_model=self._model)

    def complete(self, prompt: str, *, timeout: int = _TIMEOUT_SECONDS) -> str:
        self._require_base_url()
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": _ANSWER_MAX_TOKENS,
            "response_format": {"type": "json_object"},
            **_NO_THINKING,
        }
        try:
            try:
                raw = self._post("/chat/completions", payload, timeout=timeout)
            except urllib.error.HTTPError as exc:
                detail = _http_error_detail(exc)
                if exc.code == 400 and "chat_template_kwargs" in detail:
                    # A server that does not know the field: ask without it.
                    payload = {k: v for k, v in payload.items() if k not in _NO_THINKING}
                    raw = self._post("/chat/completions", payload, timeout=timeout)
                else:
                    raise JudgeTransportError(detail) from exc
        except JudgeTransportError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _log.warning("openai-compatible judge call failed: %s", exc)
            raise JudgeTransportError(str(exc)) from exc
        content, finish = _extract_content(raw)
        if finish == _FINISH_REASON_LENGTH:
            # Same outcome as Ollama's done_reason=length: the model did
            # answer, but the answer was cut at max_tokens — a named
            # result for the session analysis, not "unparseable".
            raise JudgeAnswerTruncated(
                f"{self._model} hit its {_ANSWER_MAX_TOKENS}-token answer cap before "
                "finishing — it did not keep to the list limits in the prompt; "
                "a stronger model usually does.",
                partial=content,
            )
        return content

    def _require_base_url(self) -> None:
        if not self._base_url:
            raise MissingBaseUrlError(
                "the openai judge needs a base URL — set CCT_SA_JUDGE_BASE_URL "
                "(e.g. http://localhost:1234/v1 for LM Studio) in .env or the "
                "Settings page."
            )

    def _post(self, path: str, payload: dict, *, timeout: int = _TIMEOUT_SECONDS) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    """"HTTP 404: model 'x' not found" — the server's own reason, which
    is the useful part, instead of a bare status code."""
    try:
        body = exc.read().decode("utf-8")
        obj = json.loads(body)
        msg = obj.get("error") if isinstance(obj, dict) else None
        if isinstance(msg, dict):
            msg = msg.get("message")
        if msg:
            return f"HTTP {exc.code}: {msg}"
        if body.strip():
            return f"HTTP {exc.code}: {body.strip()[:200]}"
    except (ValueError, OSError):
        pass
    return f"HTTP {exc.code}: {exc.reason}"


def _extract_content(raw: str) -> tuple[str, Optional[str]]:
    """The assistant message text and finish_reason of a Chat Completions
    response; (raw, None) when the body is not that shape."""
    try:
        obj = json.loads(raw)
        choice = obj["choices"][0]
        return choice["message"]["content"] or "", choice.get("finish_reason")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return raw, None


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


def factory(model: str) -> OpenAICompatJudge:
    return OpenAICompatJudge(model)
