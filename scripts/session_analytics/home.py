"""The one place in Python that knows where CCT keeps a user's files (#411).

The home is ``${CCT_HOME:-~/.cct}``. Through the 2.1.x line a file that is
absent from the home but present in the legacy home ``~/.code-copilot-team``
is read from there (a read-only fallback); the first 2.2 change removes the
fallback. Nothing here moves a file: ``cct home migrate`` is the only mover.

Mirrors ``scripts/lib/cct-home.sh`` (bash) and
``adapters/pi/runtime/config/home.ts`` (TypeScript) rule for rule.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_HOME = "CCT_HOME"
HOME_DEFAULT_REL = ".cct"
HOME_LEGACY_REL = ".code-copilot-team"  # read-only fallback through 2.1.x; removed in 2.2


def cct_home() -> Path:
    """The home directory; it may not exist yet."""
    override = os.environ.get(ENV_HOME)
    return Path(override) if override else Path.home() / HOME_DEFAULT_REL


def legacy_home() -> Path:
    return Path.home() / HOME_LEGACY_REL


def cct_home_path(relative: str) -> Path:
    """The path to read ``relative`` from, or to create it at under the home.

    ``CCT_HOME`` set: that directory, no fallback. Otherwise the home when the
    entry exists there, the legacy home when it exists only there, and the
    home as the place to create it.
    """
    new = cct_home() / relative
    if os.environ.get(ENV_HOME):
        return new
    if new.exists():
        return new
    legacy = legacy_home() / relative
    if legacy.exists():
        return legacy
    return new


def legacy_hits() -> list[str]:
    """Entries still served from the legacy home (absent from the home)."""
    if os.environ.get(ENV_HOME):
        return []
    legacy = legacy_home()
    if not legacy.is_dir():
        return []
    home = cct_home()
    return sorted(p.name for p in legacy.iterdir() if not (home / p.name).exists())
