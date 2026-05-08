# benchmark_runner.registry — adapter and backend discovery.
#
# Phase 0: empty registries; Phase 1+ populates them. Resolution is by
# string id (``benchmark_id``, ``backend_id``). Duplicate registration
# is a programmer error and raises ``RuntimeError``.

from __future__ import annotations

from typing import Callable, Dict

from .contracts import Backend, BenchmarkAdapter

_AdapterFactory = Callable[[], BenchmarkAdapter]
_BackendFactory = Callable[[str], Backend]  # accepts a model spec


_ADAPTERS: Dict[str, _AdapterFactory] = {}
_BACKENDS: Dict[str, _BackendFactory] = {}


# ── Adapters ───────────────────────────────────────────────────────────


def register_adapter(benchmark_id: str, factory: _AdapterFactory) -> None:
    if benchmark_id in _ADAPTERS:
        raise RuntimeError(f"adapter already registered: {benchmark_id!r}")
    _ADAPTERS[benchmark_id] = factory


def list_adapter_ids() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(benchmark_id: str) -> BenchmarkAdapter:
    try:
        factory = _ADAPTERS[benchmark_id]
    except KeyError:
        known = ", ".join(list_adapter_ids()) or "(none)"
        raise UnknownAdapterError(
            f"unknown adapter: {benchmark_id!r}; registered: {known}"
        ) from None
    return factory()


# ── Backends ───────────────────────────────────────────────────────────


def register_backend(backend_family: str, factory: _BackendFactory) -> None:
    """Register a backend family.

    A backend spec on the CLI is ``<family>:<model>`` (e.g.
    ``claude-code:sonnet``, ``vllm:llama-3.1-70b``) or a bare family
    name with no model (e.g. ``stub``). The family is what registers;
    the model is passed to the factory at resolution time.
    """
    if backend_family in _BACKENDS:
        raise RuntimeError(f"backend already registered: {backend_family!r}")
    _BACKENDS[backend_family] = factory


def list_backend_ids() -> list[str]:
    return sorted(_BACKENDS)


def get_backend(family: str, model: str = "") -> Backend:
    """Resolve a backend by family name + optional model id.

    The CLI surface separates these into ``--backend <family> --model <id>``
    (per the v3 architectural correction — see
    specs/benchmark-harness/audit-2026-05-08.md). Some backends (``stub``)
    take no model; pass ``""`` (the default).
    """
    try:
        factory = _BACKENDS[family]
    except KeyError:
        known = ", ".join(list_backend_ids()) or "(none)"
        raise UnknownBackendError(
            f"unknown backend family: {family!r}; registered families: {known}"
        ) from None
    return factory(model)


# ── Errors ─────────────────────────────────────────────────────────────


class UnknownAdapterError(LookupError):
    pass


class UnknownBackendError(LookupError):
    pass


# ── Test-only helpers ──────────────────────────────────────────────────


def _reset_for_tests() -> None:
    """Clear both registries. Test-suite use only."""
    _ADAPTERS.clear()
    _BACKENDS.clear()
