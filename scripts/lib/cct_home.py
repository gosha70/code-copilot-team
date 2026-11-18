"""scripts/lib view of the CCT home resolver (#411).

The rule lives in ``scripts/session_analytics/home.py`` so the analytics
package, which runs with ``scripts/`` on ``PYTHONPATH``, and the ``cct``
helpers here share one implementation. This module only makes it
importable as a sibling of the other ``scripts/lib`` helpers.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from session_analytics.home import (  # noqa: E402,F401 — re-exported
    ENV_HOME,
    HOME_DEFAULT_REL,
    HOME_LEGACY_REL,
    cct_home,
    cct_home_path,
    MIGRATE_ASIDE_PREFIX,
    MIGRATE_STAGE_PREFIX,
    legacy_hits,
    legacy_home,
)
