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
from .contracts import PARSE_BACKEND_ERROR, Rubric, TurnContext, TurnLabels
from .parse import parse_labels

_log = logging.getLogger(__name__)

JUDGE_FAMILY = "openai"
_TIMEOUT_SECONDS = 120


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
        if not self._base_url:
            raise MissingBaseUrlError(
                "the openai judge needs a base URL — set CCT_SA_JUDGE_BASE_URL "
                "(e.g. http://localhost:1234/v1 for LM Studio) in .env or the "
                "Settings page."
            )
        prompt = rubric.prompt_template.format(
            role=ctx.role, prev_text=ctx.prev_text or "", text=ctx.text or ""
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            raw = self._post("/chat/completions", payload)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _log.warning("openai-compatible judge call failed: %s", exc)
            return _err(rubric, self.judge_id, self._model, str(exc))

        content = _extract_content(raw)
        return parse_labels(content, rubric, judge_id=self.judge_id, judge_model=self._model)

    def _post(self, path: str, payload: dict) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8")


def _extract_content(raw: str) -> str:
    """Pull the assistant message text out of a Chat Completions response."""
    try:
        obj = json.loads(raw)
        return obj["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return raw


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
