# session_analytics.judge._register — explicit judge registration.

from __future__ import annotations


def register_all_judges() -> None:
    from .registry import register_judge
    from . import ollama_judge, openai_judge, session_judge

    # claude-code = Anthropic via the local claude CLI (explicit opt-in).
    register_judge(session_judge.JUDGE_FAMILY, session_judge.factory)
    # ollama = local models (the packaged default judge); openai = any
    # OpenAI-compatible endpoint (LM Studio / vLLM / OpenAI / Azure).
    register_judge(ollama_judge.JUDGE_FAMILY, ollama_judge.factory)
    register_judge(openai_judge.JUDGE_FAMILY, openai_judge.factory)
