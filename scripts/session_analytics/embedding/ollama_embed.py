# session_analytics.embedding.ollama_embed — the local Ollama embedding
# backend (#285).
#
# T1 SHIP STATE: a registered stub, deliberately WITHOUT wire code.
#
# The endpoint, request shape, response shape, and — critically —
# whether and where Ollama authoritatively reports the model that
# served the call are pinned by T3's recorded live capture
# (specs/session-analytics-similarity-embed/verification-ollama-embed.md),
# not asserted from memory. Until that capture exists, this backend
# refuses to run rather than encode an assumption; the refusal message
# names the contract so a caller cannot mistake it for an outage.
#
# If the capture shows Ollama does NOT authoritatively report the
# serving model, this backend must refuse to embed AT ALL (FR-5) — a
# configured model string is a request, never serving evidence.

from __future__ import annotations

from .contracts import EmbeddingResult

BACKEND_FAMILY = "ollama"

_T3_MSG = (
    "the ollama embedding wire contract is pinned by the T3 recorded "
    "capture (specs/session-analytics-similarity-embed/"
    "verification-ollama-embed.md) and is not implemented before it"
)


class OllamaEmbedding:
    """Local-only Ollama embedding backend (FR-2). Wire code lands in T3."""

    def __init__(self, model: str = "", *, base_url: str = "") -> None:
        self._model = model
        self._base_url = base_url

    def probe(self) -> None:
        raise NotImplementedError(_T3_MSG)

    def embed(self, text: str) -> EmbeddingResult:
        raise NotImplementedError(_T3_MSG)


def factory(model: str) -> OllamaEmbedding:
    return OllamaEmbedding(model=model)
