# session_analytics.embedding.ollama_embed — the local Ollama embedding
# backend (#285 T3).
#
# EVERY wire assumption here derives from the recorded capture at
# specs/session-analytics-similarity-embed/verification-ollama-embed.md
# (Ollama 0.32.6, nomic-embed-text, synthetic input). The load-bearing
# capture facts:
#
#   - ``POST /api/embed`` is the ONLY usable endpoint: its response
#     carries a server-produced ``model`` field. The legacy
#     ``/api/embeddings`` returns no model identity at all, so under
#     FR-5 it is unusable regardless of convenience.
#   - The server REFUSES every model it cannot serve embeddings from —
#     empty, unknown, and generative models all error rather than fall
#     back — so a 200 with a ``model`` field attests that exactly that
#     model produced the vector, to the full extent Ollama exposes
#     serving identity. The envelope stores THAT field, never the
#     config string.
#   - Ollama has NO default embedding model: ``model: ""`` errors
#     (``model '' not found``). So an empty configured model REFUSES
#     BEFORE ANY HTTP CALL with operator guidance — embedding under
#     ``""`` cannot produce an authoritative identity, and FR-5 says
#     no identity, no envelope.
#   - ``embeddings`` is a list of lists (one inner vector per input);
#     this backend sends exactly one input and requires exactly one
#     vector back.
#   - Errors arrive as JSON ``{"error": "<message>"}`` on a non-200
#     status. Any ``error`` key is a failed call; provider wording is
#     never parsed into semantics.

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .contracts import EmbeddingResult

BACKEND_FAMILY = "ollama"

_EMBED_PATH = "/api/embed"
_TIMEOUT_SECONDS = 120


class EmbeddingBackendError(RuntimeError):
    """A failed embedding call — the runner counts it, the session
    stays NULL (FR-3). Never carries a vector."""


class OllamaEmbedding:
    """Local-only Ollama embedding backend (FR-2)."""

    def __init__(self, model: str = "", *, base_url: str = "") -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")

    # ── the FR-5 gate that needs no network ──────────────────────────
    def _require_model(self) -> None:
        if not self._model:
            raise EmbeddingBackendError(
                "no embedding model configured, and Ollama has no default "
                "embedding model (capture: `model ''` errors with "
                "\"model '' not found\") — set `embedding.model` (e.g. "
                "nomic-embed-text, after `ollama pull nomic-embed-text`)"
            )

    def probe(self) -> None:
        """Prove the backend can actually serve THIS model.

        A tags listing cannot: generative models are listed yet refuse
        embeddings (captured). The only authoritative probe is a real
        embed call, so this embeds a one-word fixed string. The runner
        calls it once per pass, and only when work exists (FR-6).
        """
        self.embed("probe")

    def embed(self, text: str) -> EmbeddingResult:
        self._require_model()
        raw = self._post(_EMBED_PATH, {"model": self._model, "input": text})
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise EmbeddingBackendError(
                f"ollama returned non-JSON from {_EMBED_PATH}: {raw[:200]!r}"
            ) from None
        if not isinstance(data, dict):
            raise EmbeddingBackendError(
                f"ollama returned a non-object from {_EMBED_PATH}"
            )
        if "error" in data:
            raise EmbeddingBackendError(f"ollama error: {data['error']}")

        resolved = data.get("model")
        if not isinstance(resolved, str) or not resolved:
            # The legacy endpoint's shape, or a future surface change:
            # without a server-produced identity there is no envelope
            # (FR-5) — and the CONFIGURED name is never substituted.
            raise EmbeddingBackendError(
                "ollama response carries no model identity — refusing to "
                "attribute the vector to the configured name"
            )

        outer = data.get("embeddings")
        if not isinstance(outer, list) or len(outer) != 1:
            raise EmbeddingBackendError(
                "ollama response did not contain exactly one embedding "
                f"(got {type(outer).__name__} of len "
                f"{len(outer) if isinstance(outer, list) else 'n/a'})"
            )
        vector = outer[0]
        if not isinstance(vector, list) or not vector:
            raise EmbeddingBackendError("ollama returned an empty embedding")

        return EmbeddingResult(
            vector=tuple(float(x) for x in vector),
            resolved_model=resolved,
        )

    # ── transport (the judge's idiom; errors normalized) ─────────────
    def _post(self, path: str, payload: dict) -> str:
        req = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # Ollama puts {"error": ...} in non-200 bodies (404 captured
            # for empty/unknown model) — surface the body, not just the
            # status line.
            body = ""
            try:
                body = exc.read().decode("utf-8")
            except Exception:
                pass
            return body or json.dumps({"error": f"HTTP {exc.code}"})
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EmbeddingBackendError(
                f"ollama unreachable at {self._base_url}: {exc}"
            ) from None


def factory(model: str) -> OllamaEmbedding:
    return OllamaEmbedding(model=model)
