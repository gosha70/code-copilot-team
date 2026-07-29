# wiki_ingest.backends — backend registry and resolution.
#
# Backend resolution precedence (first match wins):
#   1. cli_flag argument to resolve_backend()  — most specific signal
#   2. WIKI_INGEST_BACKEND environment variable — developer override
#   3. auto_detect()                            — first CLI found on PATH
#
# Registered backends (by name):
#   "test" — deterministic in-process backend for CI / fixture runs
#
# Copilot-CLI backends are NOT registered in _REGISTRY; resolve_backend()
# handles them by name. This keeps precedence logic in one place.

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..ingestor import Backend

from ..errors import BackendNotFoundError
from .copilot_cli import CopilotCliBackend, cli_binary_for
from .test import TestBackend

_REGISTRY: dict[str, type] = {
    "test": TestBackend,
}

# Every valid copilot-CLI backend name. Explicit `--backend <name>` (or the
# WIKI_INGEST_BACKEND env override) accepts any of these first-class — pi
# included. Auto-detect is a separate, capability-gated concern (see below).
_COPILOT_NAMES: tuple[str, ...] = ("claude", "codex", "cursor", "pi")


def _pi_capability_enabled() -> bool:
    """True iff the providers.pi capability reports `enabled` (FR-025/FR-028).

    Read from shared/capabilities/pi.yaml — the same declaration the runtime
    binds to its acceptance suite. PATH presence of pi-code is NOT sufficient;
    auto-detect only considers pi when the capability is genuinely enabled.
    """
    yaml_path = Path(__file__).resolve().parents[3] / "shared" / "capabilities" / "pi.yaml"
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except OSError:
        return False
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- id: providers.pi"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("- id:"):
                break
            if stripped.startswith("runtime_status:"):
                return stripped.split(":", 1)[1].strip() == "enabled"
    return False


def _auto_detect_order() -> tuple[str, ...]:
    """Auto-detect probe order. pi is inserted (claude → codex → pi → cursor)
    ONLY when its capability is enabled; explicit --backend pi is unaffected."""
    order = ["claude", "codex"]
    if _pi_capability_enabled():
        order.append("pi")
    order.append("cursor")
    return tuple(order)


def get_backend(name: str) -> "Backend":
    """Return an instantiated backend for the given registered name.

    Raises KeyError if the name is not in the registry.
    """
    cls = _REGISTRY[name]
    return cls()


def list_registered() -> list[str]:
    """Return the list of registered backend names (excluding auto-detect candidates)."""
    return list(_REGISTRY.keys())


def auto_detect() -> "Backend":
    """Auto-detect the best available copilot-CLI backend.

    Probes PATH for claude, codex, cursor in order. Returns a CopilotCliBackend
    for the first match.

    Raises BackendNotFoundError if none of the candidates are on PATH.
    """
    order = _auto_detect_order()
    for cli_name in order:
        if shutil.which(cli_binary_for(cli_name)):
            return CopilotCliBackend(cli_name)
    raise BackendNotFoundError(
        "No copilot CLI on PATH. Tried: " + ", ".join(order) +
        ". Install one or use --backend test for fixture runs."
    )


def resolve_backend(cli_flag: str | None) -> "Backend":
    """Resolve the backend to use, implementing the three-level precedence.

    Precedence:
      1. cli_flag (from --backend CLI argument) — if provided, use it.
      2. WIKI_INGEST_BACKEND environment variable — if set, use it.
      3. auto_detect() — probe PATH for claude, codex, cursor.

    Registered names (currently "test") are looked up in _REGISTRY.
    Copilot-CLI names (claude, codex, cursor) are checked on PATH via
    shutil.which and wrapped in CopilotCliBackend. Any other name raises
    BackendNotFoundError naming the valid options.

    Parameters
    ----------
    cli_flag : str | None
        Value of the --backend flag, or None if not provided.

    Raises
    ------
    BackendNotFoundError
        If the named CLI is not found on PATH, or the name is unknown.
    """
    if cli_flag is not None:
        return _resolve_by_name(cli_flag)

    env_val = os.environ.get("WIKI_INGEST_BACKEND")
    if env_val:
        return _resolve_by_name(env_val)

    return auto_detect()


def _resolve_by_name(name: str) -> "Backend":
    """Resolve a single backend name string.

    Checks the registry first (for "test"), then checks copilot-CLI names
    (claude/codex/cursor) against PATH, then raises BackendNotFoundError.
    """
    # Registered backends (e.g. "test") — no PATH check required.
    if name in _REGISTRY:
        return get_backend(name)

    # Copilot-CLI backends — verify the CLI is on PATH (fail-fast semantics).
    # Look up the on-disk binary name (cursor → cursor-agent, etc.) so the
    # PATH probe finds the right executable.
    if name in _COPILOT_NAMES:
        binary = cli_binary_for(name)
        if shutil.which(binary):
            return CopilotCliBackend(name)
        raise BackendNotFoundError(
            f"Backend CLI '{binary}' not found on PATH. "
            "Install it or use --backend test for fixture runs."
        )

    # Unknown name.
    valid_options = list(_REGISTRY.keys()) + list(_COPILOT_NAMES)
    raise BackendNotFoundError(
        f"Unknown backend name: {name!r}. "
        "Valid options: " + ", ".join(valid_options) + "."
    )
