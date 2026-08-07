"""Developer identity derivation (Slice B1 of #174, issue #187).

Derives a stable, local-first ``developer_id`` with explicit precedence —
never fabricated: every source either yields a valid id or falls through,
and the terminal fallback is the pre-existing ``"local"`` stub.

    flag > CCT_DEVELOPER_ID (real env > repo .env, via the config loader)
         > config ``developer_id`` > git-global-email local-part > "local"

Two deliberate semantics (PR #188 review, 2026-08-07):

- **Explicit flag values are honored verbatim** (after control-character
  stripping and the column bound) — pre-B1 users passed ``--developer-id
  Team_A`` and their rows carry ``Team_A``; normalizing an explicit value
  would split their identity on upgrade. Only *derived* sources (env,
  config, git) are kebab-normalized. A flag value that survives as empty
  falls through, and the caller is expected to WARN — an explicit user
  instruction is never dropped silently.
- **The git source is the MACHINE/user identity**: ``git config --global
  user.email``, never the launch directory's repo-local email — a
  cwd-dependent id would stamp the same developer differently per launch
  dir, and B1 never migrates stamps retroactively.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from . import constants as C

# Column bound — MUST match developer.developer_id VARCHAR(100) in
# config_data/ddl/postgres/001_core.sql (drift means the DATABASE truncates
# instead of this code); explicit flag values
# are bounded by this, derived values by the tighter kebab bound below.
_MAX_COLUMN_LEN = 100

# Normalized (derived) ids: lowercase kebab, alphanumeric first, bounded.
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


def sanitize_explicit_id(raw: object) -> Optional[str]:
    """Minimal safety pass for an EXPLICIT ``--developer-id`` value.

    Strips control characters, trims, bounds to the column length —
    otherwise verbatim (case and punctuation preserved for upgrade
    compatibility with pre-B1 stamps). ``None`` when nothing remains.
    """
    if not isinstance(raw, str):
        return None
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", "", raw).strip()
    candidate = cleaned[:_MAX_COLUMN_LEN].strip()
    return candidate or None


def normalize_developer_id(raw: object) -> Optional[str]:
    """Normalize a DERIVED candidate into the bounded kebab form, or ``None``.

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


def _from_git_global_email() -> Optional[str]:
    """Local-part of ``git config --global user.email``, normalized.

    Global config ONLY — machine/user identity, independent of the launch
    directory (and of any repo-local ``user.email`` override). ``None`` on
    any failure: git missing, timeout, unset, or an unusable local part.
    """
    try:
        proc = subprocess.run(
            ["git", "config", "--global", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
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
    env_value: Optional[str] = None,
    config_value: Optional[str] = None,
) -> DerivedIdentity:
    """Resolve the developer id by precedence (see module docstring).

    ``env_value``/``config_value`` are the values the analytics config
    loader resolved (``CCT_DEVELOPER_ID`` through real env > repo ``.env``;
    the ``developer_id`` config key) — this function never reads the
    process environment itself, so the loader's documented layering is the
    single source of truth. A source whose candidate does not survive its
    sanitation falls through; the terminal fallback is
    ``constants.DEFAULT_DEVELOPER_ID`` (``"local"``), never fabricated.
    """
    explicit = sanitize_explicit_id(cli_value)
    if explicit:
        return DerivedIdentity(id=explicit, source=SOURCE_FLAG)

    for source, raw in (
        (SOURCE_ENV, env_value),
        (SOURCE_CONFIG, config_value),
    ):
        candidate = normalize_developer_id(raw)
        if candidate:
            return DerivedIdentity(id=candidate, source=source)

    from_git = _from_git_global_email()
    if from_git:
        return DerivedIdentity(id=from_git, source=SOURCE_GIT_EMAIL)

    return DerivedIdentity(id=C.DEFAULT_DEVELOPER_ID, source=SOURCE_FALLBACK)
