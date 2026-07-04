# session_analytics.normalize.tool_names — canonical tool-id normalization.
#
# The mapping table is DATA (config_data/tool-name-map.yaml), loaded once and
# cached. ``normalize`` returns the canonical id; the caller keeps both the
# canonical and the raw name (tool_name + tool_name_raw columns).

from __future__ import annotations

from functools import lru_cache
from typing import Mapping

from ..config import load_map

_MAP_FILE = "tool-name-map.json"


@lru_cache(maxsize=1)
def _load_map() -> Mapping[str, str]:
    data = load_map(_MAP_FILE)
    raw = data.get("map") or {}
    # Normalize keys to lowercase for case-insensitive lookup.
    return {str(k).lower(): str(v) for k, v in raw.items()}


def normalize(name_raw: str) -> str:
    """Map a copilot's raw tool name to a canonical cross-copilot id.

    Unmapped names fall through to their lowercased form so a brand-new
    tool still groups consistently (and surfaces in reports as its own id)
    rather than being dropped.
    """
    if not name_raw:
        return ""
    return _load_map().get(name_raw.lower(), name_raw.lower())
