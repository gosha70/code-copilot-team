# session_analytics.normalize.files — file-path extraction + language detect.
#
# Extracts file paths from a tool call's input object (Read/Write/Edit/Glob)
# and detects language by extension via config_data/file-language-map.yaml.

from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping, Optional

from ..config import load_map

_MAP_FILE = "file-language-map.json"

# Common keys copilots use to carry a file path in a tool input object.
_PATH_KEYS = ("file_path", "path", "filePath", "notebook_path", "file", "filename")


@lru_cache(maxsize=1)
def _lang_map() -> Mapping[str, str]:
    data = load_map(_MAP_FILE)
    raw = data.get("map") or {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def language_for(path: str) -> Optional[str]:
    """Detect language from a file path's extension, or None if unknown."""
    if not path or "." not in path.rsplit("/", 1)[-1]:
        return None
    ext = path.rsplit(".", 1)[-1].lower()
    return _lang_map().get(ext)


def path_from_input(input_obj: Mapping[str, Any]) -> Optional[str]:
    """Best-effort extraction of a single file path from a tool input."""
    if not isinstance(input_obj, Mapping):
        return None
    for key in _PATH_KEYS:
        val = input_obj.get(key)
        if isinstance(val, str) and val:
            return val
    return None
