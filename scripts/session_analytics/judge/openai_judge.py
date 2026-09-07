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
        self._base_url = (base_url if base_url is not None else cfg.base_url).rstrip("/")
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
        }
        try:
            raw = self._post("/chat/completions", payload, timeout=timeout)
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
