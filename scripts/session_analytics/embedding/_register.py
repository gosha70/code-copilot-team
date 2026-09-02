# session_analytics.embedding._register — explicit backend registration.

from __future__ import annotations


def register_all_embeddings() -> None:
    from . import ollama_embed
    from .registry import register_embedding

    # ollama = local models, the packaged default (FR-2): no session
    # content leaves the machine on the default path.
    register_embedding(ollama_embed.BACKEND_FAMILY, ollama_embed.factory)
