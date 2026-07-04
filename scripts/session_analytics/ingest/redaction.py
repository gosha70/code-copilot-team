# session_analytics.ingest.redaction — content redaction (privacy AC).
#
# Applied BEFORE any DB write or judge prompt. Default mode is ``code``:
# keep human-readable text previews but strip fenced code blocks and tool
# inputs to a length + sha256 marker, so dashboards stay useful while raw
# code never lands in the store. ``metadata-only`` stores no content at all;
# ``none`` stores verbatim.

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Optional

from .. import constants as C

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


def redact_text(text: str, mode: str) -> str:
    """Redact a turn's visible text according to ``mode``."""
    if not text:
        return text
    if mode == C.REDACT_NONE:
        return text
    if mode == C.REDACT_METADATA_ONLY:
        return f"[redacted {len(text)} chars sha256:{_digest(text)}]"
    # REDACT_CODE: replace fenced code blocks with a marker, keep prose.
    def _sub(m: "re.Match[str]") -> str:
        body = m.group(0)
        return f"[code redacted {len(body)} chars sha256:{_digest(body)}]"

    return _FENCE_RE.sub(_sub, text)


def redact_tool_input(input_obj: Mapping[str, Any], mode: str) -> str:
    """Render a tool input object to a stored preview string under ``mode``."""
    import json

    try:
        raw = json.dumps(input_obj, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        raw = str(input_obj)
    if mode == C.REDACT_NONE:
        return raw[: C.INPUT_PREVIEW_CHARS]
    if mode == C.REDACT_METADATA_ONLY:
        return f"[redacted {len(raw)} chars sha256:{_digest(raw)}]"
    # REDACT_CODE: keep the key names (cheap, useful for analytics) but
    # strip values that look code-like (any value over 80 chars).
    if isinstance(input_obj, Mapping):
        keys = ",".join(sorted(str(k) for k in input_obj.keys()))
        return f"keys:[{keys}] ({len(raw)} chars sha256:{_digest(raw)})"
    return f"[redacted {len(raw)} chars sha256:{_digest(raw)}]"


def content_is_redacted(mode: str) -> bool:
    """Whether ``mode`` strips any content (for the content_redacted flag)."""
    return mode != C.REDACT_NONE


# Tool OUTPUT (results / error messages) is the highest-risk surface: it can
# contain command output, file contents, paths, or secrets, none of which we
# can reliably distinguish from safe prose. So under any non-``none`` mode we
# reduce it to a length+hash marker (never readable content), while keeping the
# true length as separate metadata. ``--redact none`` is the explicit opt-in
# for full fidelity.
_EXC_RE = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning|Failure|Fault))\b")


def redact_result(text: Optional[str], mode: str, *, limit: int = 2000) -> Optional[str]:
    """Redact a tool result / error message before it is stored."""
    if text is None:
        return None
    if mode == C.REDACT_NONE:
        return text[:limit]
    return f"[output redacted {len(text)} chars sha256:{_digest(text)}]"


def safe_error_type(text: str, mode: str) -> str:
    """A grouping-friendly error type that does not leak content.

    Under ``none`` the first line is used verbatim. Under any redacting mode we
    keep ONLY a recognized exception-class token (e.g. ``FileNotFoundError``)
    so error grouping still works; anything else (a secret, a path, free text)
    collapses to ``"redacted"``.
    """
    if mode == C.REDACT_NONE:
        first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
        return first[:200] if first else "error"
    m = _EXC_RE.match(text or "")
    return m.group(1)[:200] if m else "redacted"
