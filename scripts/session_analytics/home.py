"""The one place in Python that knows where CCT keeps a user's files (#411).

The home is ``${CCT_HOME:-~/.cct}``. Through the 2.1.x line a top-level
entry that is absent from the home but present in the legacy home
``~/.code-copilot-team`` is served from there, reads and writes alike, so a
directory is never split between the two; the first 2.2 change removes the
fallback. Nothing here moves a file: ``cct home migrate`` is the only mover.

Mirrors ``scripts/lib/cct-home.sh`` (bash) and
``adapters/pi/runtime/config/home.ts`` (TypeScript) rule for rule.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_HOME = "CCT_HOME"
HOME_DEFAULT_REL = ".cct"
HOME_LEGACY_REL = ".code-copilot-team"  # served as a fallback through 2.1.x; removed in 2.2


def cct_home() -> Path:
    """The home directory; it may not exist yet."""
    override = os.environ.get(ENV_HOME)
    return Path(override) if override else Path.home() / HOME_DEFAULT_REL


def legacy_home() -> Path:
    return Path.home() / HOME_LEGACY_REL


def cct_home_path(relative: str) -> Path:
    """The path to read, write or create ``relative`` at.

    ``CCT_HOME`` set: that directory, no fallback. Otherwise the TOP-LEVEL
    entry (the first segment of ``relative``) decides: the legacy home when
    that entry exists only there, else the home. ``pi/audit.log`` therefore
    goes wherever ``pi/`` lives and never splits the directory.
    """
    entry = Path(relative).parts[0]
    if not os.environ.get(ENV_HOME) and not (cct_home() / entry).exists() and (legacy_home() / entry).exists():
        return legacy_home() / relative
    return cct_home() / relative


def legacy_hits() -> list[str]:
    """Entries still served from the legacy home (absent from the home)."""
    if os.environ.get(ENV_HOME):
        return []
    legacy = legacy_home()
    if not legacy.is_dir():
        return []
    home = cct_home()
    return sorted(p.name for p in legacy.iterdir() if not (home / p.name).exists())
