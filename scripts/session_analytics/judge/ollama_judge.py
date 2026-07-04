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
from .contracts import PARSE_BACKEND_ERROR, Rubric, TurnContext, TurnLabels
from .parse import parse_labels

_log = logging.getLogger(__name__)

JUDGE_FAMILY = "ollama"
_DEFAULT_MODEL = "llama3"
_TIMEOUT_SECONDS = 120


class OllamaJudge:
    judge_id = JUDGE_FAMILY

    def __init__(self, model: str = "", *, base_url: Optional[str] = None) -> None:
        self._model = model or _DEFAULT_MODEL
        self._base_url = (base_url or load_config().judge.ollama_url).rstrip("/")

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
        prompt = rubric.prompt_template.format(
            role=ctx.role, prev_text=ctx.prev_text or "", text=ctx.text or ""
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            raw = self._post("/api/chat", payload)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _log.warning("ollama judge call failed: %s", exc)
            return _err(rubric, self.judge_id, self._model, str(exc))

        content = ""
        try:
            obj = json.loads(raw)
            content = (obj.get("message") or {}).get("content", "") or obj.get("response", "")
        except json.JSONDecodeError:
            content = raw
        return parse_labels(content, rubric, judge_id=self.judge_id, judge_model=self._model)

    def _post(self, path: str, payload: dict) -> str:
        req = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8")


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
