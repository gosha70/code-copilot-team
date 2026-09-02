# session_analytics.embedding.registry — embedding-backend discovery.
#
# Mirrors judge/registry.py: families register explicitly, the model
# string is passed to the factory at resolution time.

from __future__ import annotations

from typing import Callable, Dict

from .contracts import EmbeddingBackend

# A factory takes (model, base_url). Both come from the ALREADY-RESOLVED
# EmbeddingConfig the caller holds — a backend never calls load_config()
# itself, because the runner's resolved instance (CLI layer included) is
# the configuration of record and an independent reload could differ.
_EmbeddingFactory = Callable[..., EmbeddingBackend]

_BACKENDS: Dict[str, _EmbeddingFactory] = {}


def register_embedding(family: str, factory: _EmbeddingFactory) -> None:
    if family in _BACKENDS:
        raise RuntimeError(f"embedding backend already registered: {family!r}")
    _BACKENDS[family] = factory


def list_embedding_ids() -> list[str]:
    return sorted(_BACKENDS)


def get_embedding(
    family: str, model: str = "", *, base_url: str = ""
) -> EmbeddingBackend:
    try:
        factory = _BACKENDS[family]
    except KeyError:
        known = ", ".join(list_embedding_ids()) or "(none)"
        raise UnknownEmbeddingError(
            f"unknown embedding backend: {family!r}; registered: {known}"
        ) from None
    return factory(model, base_url=base_url)


class UnknownEmbeddingError(LookupError):
    pass


def _reset_for_tests() -> None:
    _BACKENDS.clear()
