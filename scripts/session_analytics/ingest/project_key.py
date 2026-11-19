# session_analytics.ingest.project_key — resolve a session's project key.
#
# The "project key" is what per-project config (``projects.<key>`` in
# config.py) is keyed on. It is resolved from a session's raw ``cwd``
# (RawSession.project_path — never a repo root; see adapters/claude_code.py)
# in two steps, tried in order:
#
#   1. configured ``project_ids`` substring-match rules (config.ProjectIdRule).
#      An explicit rule is configuration and wins (#477): before it, a rule
#      was consulted only when step 2 failed, so a ``projects`` entry keyed
#      by an id was silently ignored for any repo checked out on disk —
#      ``ingest: "off"`` included.
#   2. git toplevel detection — ``git -C <cwd> rev-parse --show-toplevel`` —
#      for a cwd no rule matches; the key is then the repo's absolute path.
#
# Neither matching → ``None`` ("no override, the global redaction_mode
# applies" — the regression-safe default, FR-6). The resolver never falls
# back to returning the raw ``project_path`` itself unless step 2 genuinely
# detected it as the git toplevel.

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Optional, Sequence

from ..config import ProjectIdRule


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


class ProjectKeyResolver:
    """Resolves + caches a session's project key for the lifetime of one
    ingest run (one instance per ``ingest()`` call, so the cache never
    leaks across runs)."""

    def __init__(
        self,
        project_id_rules: Sequence[ProjectIdRule] = (),
        *,
        git_toplevel_fn: Callable[[str], Optional[str]] = git_toplevel,
    ) -> None:
        self._rules = tuple(project_id_rules)
        self._git_toplevel_fn = git_toplevel_fn
        self._cache: dict[str, Optional[str]] = {}

    def resolve(self, project_path: Optional[str]) -> Optional[str]:
        if not project_path:
            return None
        if project_path in self._cache:
            return self._cache[project_path]

        # An explicit rule wins over detection (#477); git runs only for a
        # path no rule matches.
        key = match_project_id(project_path, self._rules)
        if not key:
            key = self._git_toplevel_fn(project_path)

        self._cache[project_path] = key
        return key
