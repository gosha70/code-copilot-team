# session_analytics.registry — ingestion-adapter discovery.
#
# Resolution is by copilot id (``claude-code``, ``aider``).
# Duplicate registration is a programmer error and raises RuntimeError.
# Mirrors benchmark_runner.registry.

from __future__ import annotations

from typing import Callable, Dict

from .contracts import SessionAdapter

_AdapterFactory = Callable[[], SessionAdapter]

_ADAPTERS: Dict[str, _AdapterFactory] = {}


def register_adapter(copilot_id: str, factory: _AdapterFactory) -> None:
    if copilot_id in _ADAPTERS:
        raise RuntimeError(f"adapter already registered: {copilot_id!r}")
    _ADAPTERS[copilot_id] = factory


def list_adapter_ids() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(copilot_id: str) -> SessionAdapter:
    try:
        factory = _ADAPTERS[copilot_id]
    except KeyError:
        known = ", ".join(list_adapter_ids()) or "(none)"
        raise UnknownAdapterError(
            f"unknown copilot adapter: {copilot_id!r}; registered: {known}"
        ) from None
    return factory()


class UnknownAdapterError(LookupError):
    pass


def _reset_for_tests() -> None:
    """Clear the registry. Test-suite use only."""
    _ADAPTERS.clear()
