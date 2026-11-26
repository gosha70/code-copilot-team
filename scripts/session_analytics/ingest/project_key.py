# session_analytics.ingest.project_key — the keys a project's settings are
# filed under, and the settings a session gets from them.
#
# Per-project config (``projects.<key>`` in config.py) can be keyed two
# ways. A session's raw ``cwd`` (RawSession.project_path — never a repo
# root; see adapters/claude_code.py) is resolved to both:
#
#   1. the ``id`` of the first configured ``project_ids`` rule whose
#      ``match`` is a substring of the cwd (config.ProjectIdRule);
#   2. the git toplevel — ``git -C <cwd> rev-parse --show-toplevel`` — the
#      repo's absolute path.
#
# A session's settings are the entries under BOTH keys, combined so that
# the stricter one holds (#477): opted out if either entry opts out, else
# the stricter of their redaction modes. Consulting one key only is how
# settings were lost: with the git root first, an entry keyed by an id was
# silently ignored for any repo checked out on disk — ``ingest: "off"``
# included — and with the rule first, an entry keyed by a repo's path
# would be ignored inside any rule broad enough to cover it.
#
# No entry under either key → ``None`` ("no override, the global
# redaction_mode applies" — the regression-safe default, FR-6). The raw
# ``project_path`` itself is never a key unless step 2 genuinely detected
# it as the git toplevel.

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from .. import constants as C
from ..config import ProjectIdRule, ProjectOverride
from .redaction import stricter_mode


def git_toplevel(path: str) -> Optional[str]:
    """The git repo toplevel for ``path``, or ``None`` if ``path`` doesn't
    exist, isn't inside a git repo, or the git call fails/times out.

    The existence check runs BEFORE any subprocess call — this matters both
    for performance and so fixture/fabricated paths (e.g. "/repo/demo") that
    don't exist on disk never spawn a git process.
    """
    if not Path(path).exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _same_key(key: str) -> str:
    """``key`` in the one spelling used to compare keys. A path is compared
    by ``normcase(normpath(...))``, because git prints a Windows repository
    as ``C:/Users/me/repo`` and a person writes it with backslashes; both
    must name the same project. An id is compared as written."""
    if os.path.isabs(key) or _DRIVE_PATH.match(key):
        return os.path.normcase(os.path.normpath(key))
    return key


def entry_keys(projects: Mapping[str, ProjectOverride], keys: Sequence[str]) -> list[str]:
    """The keys, as written in ``projects``, that name the same project as
    any of ``keys``, in the order of ``keys``."""
    written: dict[str, list[str]] = {}
    for key in projects:
        written.setdefault(_same_key(key), []).append(key)
    found: list[str] = []
    for key in keys:
        for match in written.get(_same_key(key), ()):
            if match not in found:
                found.append(match)
    return found


def match_project_id(path: str, rules: Sequence[ProjectIdRule]) -> Optional[str]:
    """The ``id`` of the first rule whose ``match`` is a substring of
    ``path`` (a prefix match is a substring match, so this covers both), or
    ``None`` if no rule matches or ``path`` is falsy."""
    if not path:
        return None
    for rule in rules:
        if rule.match in path:
            return rule.id
    return None


def combined_override(
    projects: Mapping[str, ProjectOverride], keys: Sequence[str]
) -> Optional[ProjectOverride]:
    """The settings of a project whose ``projects`` entries are filed under
    ``keys``, or ``None`` when there is no entry. With two entries the
    stricter setting of each kind holds: opted out if either opts out, the
    stricter of the redaction modes they state (``None`` — the global mode
    — when neither states one), and archived only if both opt in."""
    entries = [projects[key] for key in entry_keys(projects, keys)]
    if len(entries) < 2:
        return entries[0] if entries else None
    mode: Optional[str] = None
    for entry in entries:
        if entry.redaction_mode is not None:
            mode = entry.redaction_mode if mode is None else stricter_mode(mode, entry.redaction_mode)
    return ProjectOverride(
        redaction_mode=mode,
        ingest=C.INGEST_OFF if any(e.ingest == C.INGEST_OFF for e in entries) else C.INGEST_ON,
        trace_archive=all(e.trace_archive for e in entries),
    )


class ProjectKeyResolver:
    """Resolves + caches a project path's keys for the lifetime of one run
    (one instance per ``ingest()`` call, so the cache never leaks across
    runs). Settings are read with ``override``; ``resolve`` only names a
    project."""

    def __init__(
        self,
        project_id_rules: Sequence[ProjectIdRule] = (),
        *,
        git_toplevel_fn: Callable[[str], Optional[str]] = git_toplevel,
    ) -> None:
        self._rules = tuple(project_id_rules)
        self._git_toplevel_fn = git_toplevel_fn
        self._cache: dict[str, tuple[str, ...]] = {}

    def keys(self, project_path: Optional[str]) -> tuple[str, ...]:
        """Every key ``project_path``'s settings may be filed under: the
        matching rule's id, then the git root. Empty when neither resolves."""
        if not project_path:
            return ()
        if project_path not in self._cache:
            found = (match_project_id(project_path, self._rules), self._git_toplevel_fn(project_path))
            self._cache[project_path] = tuple(dict.fromkeys(key for key in found if key))
        return self._cache[project_path]

    def resolve(self, project_path: Optional[str]) -> Optional[str]:
        """The one key a project is named by in a summary: the matching
        rule's id, else the git root."""
        keys = self.keys(project_path)
        return keys[0] if keys else None

    def entry_keys(self, projects: Mapping[str, ProjectOverride], project_path: Optional[str]) -> list[str]:
        """The keys, as written in ``projects``, the project's settings are
        filed under."""
        return entry_keys(projects, self.keys(project_path))

    def override(
        self, projects: Mapping[str, ProjectOverride], project_path: Optional[str]
    ) -> Optional[ProjectOverride]:
        """The project's settings: its entries under every key, combined."""
        return combined_override(projects, self.keys(project_path))
