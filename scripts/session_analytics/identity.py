"""Developer identity derivation (Slice B1 of #174, issue #187).

Derives a stable, local-first ``developer_id`` with explicit precedence —
never fabricated: every source either yields a valid id or falls through,
and the terminal fallback is the pre-existing ``"local"`` stub.

    flag > CCT_DEVELOPER_ID env > analytics config > git-email local-part
         > "local"

The git derivation uses the sanitized LOCAL-PART of ``git config
user.email`` (plan D-1, settled 2026-08-07): readable in a local-first
database, and honestly *attribution*, not authentication — the epic's
identity/auth decision (Slice B2+) may replace it. The derivation runs
``git config user.email`` without requiring a repository (git falls back
to the user's global config), so identity is machine-stable.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from . import constants as C

# Env var carrying an explicit developer id (checked after the CLI flag).
DEVELOPER_ID_ENV = "CCT_DEVELOPER_ID"

# Config key under the analytics config root (``developer_id = "..."``).
DEVELOPER_ID_CONFIG_KEY = "developer_id"

# Normalized ids: lowercase kebab, alphanumeric first char, bounded.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_MAX_ID_LEN = 64

# Precedence sources, in order (reported in DerivedIdentity.source).
SOURCE_FLAG = "flag"
SOURCE_ENV = "env"
SOURCE_CONFIG = "config"
SOURCE_GIT_EMAIL = "git-email"
SOURCE_FALLBACK = "fallback"


@dataclass(frozen=True)
class DerivedIdentity:
    """The derived id plus which precedence source produced it."""

    id: str
    source: str


def normalize_developer_id(raw: object) -> Optional[str]:
    """Normalize a candidate into the bounded kebab form, or ``None``.

    Lowercases, maps separator-ish characters (``._ @+``) to ``-``,
    strips everything else, collapses runs of ``-``, trims edge dashes,
    and bounds the length. Returns ``None`` when nothing valid remains —
    the caller falls through to the next source (never invents).
    """
    if not isinstance(raw, str):
        return None
    lowered = raw.strip().lower()
    mapped = re.sub(r"[._ @+]+", "-", lowered)
    cleaned = re.sub(r"[^a-z0-9-]+", "", mapped)
    collapsed = re.sub(r"-{2,}", "-", cleaned).strip("-")
    candidate = collapsed[:_MAX_ID_LEN].rstrip("-")
    if not candidate or not _ID_RE.match(candidate):
        return None
    return candidate


def _from_git_email(repo_root: Optional[Path]) -> Optional[str]:
    """Local-part of ``git config user.email``, normalized; None on any failure."""
    try:
        proc = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_root) if repo_root else None,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    email = proc.stdout.strip()
    if not email:
        return None
    local_part = email.split("@", 1)[0]
    return normalize_developer_id(local_part)


def derive_developer_id(
    cli_value: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    config_value: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> DerivedIdentity:
    """Resolve the developer id by precedence (see module docstring).

    A source whose candidate does not normalize falls through to the next;
    the terminal fallback is ``constants.DEFAULT_DEVELOPER_ID`` (``"local"``),
    so the result is always usable and never fabricated.
    """
    for source, raw in (
        (SOURCE_FLAG, cli_value),
        (SOURCE_ENV, (env or {}).get(DEVELOPER_ID_ENV)),
        (SOURCE_CONFIG, config_value),
    ):
        candidate = normalize_developer_id(raw)
        if candidate:
            return DerivedIdentity(id=candidate, source=source)

    from_git = _from_git_email(repo_root)
    if from_git:
        return DerivedIdentity(id=from_git, source=SOURCE_GIT_EMAIL)

    return DerivedIdentity(id=C.DEFAULT_DEVELOPER_ID, source=SOURCE_FALLBACK)
