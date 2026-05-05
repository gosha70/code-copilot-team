# wiki_ingest.backends — backend registry and auto-detect mechanism.
#
# Phase 1: Only the "test" backend is registered.
# Phase 2: copilot_cli backend will be added here (claude → codex → cursor auto-detect).
#
# Auto-detect order (Phase 2 placeholder):
#   1. "claude"  — claude CLI on PATH
#   2. "codex"   — codex CLI on PATH
#   3. "cursor"  — cursor CLI on PATH
#
# The "test" backend must NOT be selected by auto-detect; it is only used when
# --backend test is given explicitly.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ingestor import Backend

from .test import TestBackend

_REGISTRY: dict[str, type] = {
    "test": TestBackend,
}

# Phase 2 will add:
# from .copilot_cli import CopilotCliBackend
# _COPILOT_CLI_NAMES = ("claude", "codex", "cursor")


def get_backend(name: str) -> "Backend":
    """Return an instantiated backend for the given name.

    Raises KeyError if the name is not registered.
    """
    cls = _REGISTRY[name]
    return cls()


def list_registered() -> list[str]:
    """Return the list of registered backend names (excluding auto-detect candidates)."""
    return list(_REGISTRY.keys())


def auto_detect() -> "Backend":
    """Auto-detect the best available copilot-CLI backend.

    Phase 1: raises NotImplementedError — no CLI backends registered yet.
    Phase 2: will probe PATH for claude, codex, cursor in order.
    """
    raise NotImplementedError(
        "Auto-detect is not implemented in Phase 1. "
        "Use --backend test for fixture runs, or wait for Phase 2 for copilot-CLI support. "
        "Candidates that will be probed in Phase 2: claude, codex, cursor."
    )
