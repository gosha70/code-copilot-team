# session_analytics.embedding.contracts — embedding backend Protocol,
# result, and the envelope contract (#285 T1, E2 slice 1).
#
# Mirrors judge/contracts.py. Two rules govern everything here:
#
#   RESOLVED MODEL OR NO WRITE (FR-5). ``EmbeddingResult.resolved_model``
#   is the identity the backend AUTHORITATIVELY reports for the call —
#   never the configured/requested model name, which is a request, not
#   serving evidence. A backend that cannot say which model produced the
#   vector must not produce a result at all.
#
#   THE ENVELOPE IS VALIDATED WHOLE (FR-9). What lands in
#   ``copilot_session.session_embedding`` is a versioned, self-describing
#   JSON object, and every contract field is load-bearing: an envelope
#   failing any check below is refused before the write, and the session
#   stays NULL (FR-3 — unknown stays unknown; never a zero-vector, never
#   a partial value).
#
# Whether/how a given backend can populate ``resolved_model`` is that
# backend's evidence problem — for Ollama it is pinned by the T3 recorded
# capture, not assumed here.

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

ENVELOPE_SCHEMA_VERSION = 1

# Envelope field names — one definition, used by builder, validator and
# (in T4) the runner's reader.
FIELD_SCHEMA_VERSION = "schema_version"
FIELD_MODEL = "model"
FIELD_DIM = "dim"
FIELD_PROVIDER = "provider"
FIELD_EMBEDDED_AT = "embedded_at"
FIELD_VECTOR = "vector"

_REQUIRED_FIELDS = (
    FIELD_SCHEMA_VERSION, FIELD_MODEL, FIELD_DIM,
    FIELD_PROVIDER, FIELD_EMBEDDED_AT, FIELD_VECTOR,
)


@dataclass(frozen=True)
class EmbeddingResult:
    """One backend call's outcome: the vector plus the AUTHORITATIVE
    model identity the backend reported for it."""

    vector: tuple[float, ...]
    resolved_model: str


@runtime_checkable
class EmbeddingBackend(Protocol):
    """A pluggable embedding backend (registry family = e.g. 'ollama').

    ``probe()`` checks reachability and raises on failure; the runner
    calls it ONLY when embedding work exists (FR-6 step 4 — the
    zero-backend-calls idempotency guarantee binds before any probe).
    ``embed(text)`` returns the vector plus the resolved model identity,
    or raises; it never fabricates either half.
    """

    def probe(self) -> None: ...

    def embed(self, text: str) -> EmbeddingResult: ...


def build_envelope(
    result: EmbeddingResult, *, provider: str, embedded_at: str
) -> dict[str, Any]:
    """The FR-4 envelope: provenance rides with the vector in one value."""
    return {
        FIELD_SCHEMA_VERSION: ENVELOPE_SCHEMA_VERSION,
        FIELD_MODEL: result.resolved_model,
        FIELD_DIM: len(result.vector),
        FIELD_PROVIDER: provider,
        FIELD_EMBEDDED_AT: embedded_at,
        FIELD_VECTOR: list(result.vector),
    }


def validate_envelope(env: Mapping[str, Any]) -> Optional[str]:
    """FR-9: the whole-envelope gate before any write.

    Returns None for a valid envelope, else a reason string. Each
    refusal has its OWN reason — a single 'shape is wrong' answer would
    let a weakened rule hide behind its neighbours (the lesson the
    routing arc's state machine already paid for).
    """
    if not isinstance(env, Mapping):
        return "envelope is not an object"
    missing = [f for f in _REQUIRED_FIELDS if f not in env]
    if missing:
        return f"envelope missing fields: {', '.join(missing)}"

    if env[FIELD_SCHEMA_VERSION] != ENVELOPE_SCHEMA_VERSION:
        return (
            f"schema_version {env[FIELD_SCHEMA_VERSION]!r} is not "
            f"{ENVELOPE_SCHEMA_VERSION} — an unknown version is refused, "
            f"never best-effort read"
        )

    model = env[FIELD_MODEL]
    if not isinstance(model, str) or not model:
        return "model is empty — an unattributed vector is a fabricated fact"

    provider = env[FIELD_PROVIDER]
    if not isinstance(provider, str) or not provider:
        return "provider is empty"

    embedded_at = env[FIELD_EMBEDDED_AT]
    if not isinstance(embedded_at, str) or not _is_iso8601(embedded_at):
        return f"embedded_at {embedded_at!r} is not an ISO-8601 timestamp"

    vector = env[FIELD_VECTOR]
    if not isinstance(vector, list):
        return "vector is not a list"
    if len(vector) == 0:
        return "empty vector"

    dim = env[FIELD_DIM]
    # bool is an int subclass; a boolean dim is malformed, not a size.
    if isinstance(dim, bool) or not isinstance(dim, int) or dim <= 0:
        return f"dim {dim!r} is not a positive integer"
    if dim != len(vector):
        return f"dim {dim} does not match vector length {len(vector)}"

    for i, el in enumerate(vector):
        if isinstance(el, bool):
            return f"vector[{i}] is a boolean — elements must be real numbers"
        if not isinstance(el, (int, float)):
            return f"vector[{i}] is not a number"
        if not math.isfinite(el):
            return f"vector[{i}] is not finite"

    if all(el == 0 for el in vector):
        return (
            "zero vector — cosine over a zero norm is undefined, and the "
            "contract promises 'never a zero-vector' (FR-3/FR-9)"
        )

    return None


def _is_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
