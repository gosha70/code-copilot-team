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


def stricter_mode(a: str, b: str) -> str:
    """FR-4 redaction floor: the stricter of two modes wins — FAIL CLOSED.

    Strictness rank is positional in ``constants.REDACTION_STRICTNESS``
    (none < code < metadata-only). An UNKNOWN mode collapses the result to
    ``metadata-only`` — the strictest mode ``redact_text`` actually
    implements. Returning the unknown string itself would be a hole:
    ``redact_text`` treats any unrecognized mode as ``code`` (fence-stripping
    only), which is LOOSER than a metadata-only floor.
    """
    if a not in C.REDACTION_STRICTNESS or b not in C.REDACTION_STRICTNESS:
        return C.REDACT_METADATA_ONLY
    rank = C.REDACTION_STRICTNESS.index
    return a if rank(a) >= rank(b) else b


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


# ── outbound floor (#457) ───────────────────────────────────────────────
#
# Redaction runs once, at ingest. Text that later leaves the machine (the
# judges, Ask, embeddings, MCP) is read back from the store, so it carries
# the mode in force at ingest. These helpers apply the project's CURRENT
# mode on the way out:
#
# * the stricter of the recorded and the current mode wins; when the
#   current one is stricter, the stored text is replaced by a
#   metadata-only marker. It is never re-redacted under `code`: a stored
#   preview is already truncated, and a fence cut by that truncation would
#   escape the fence pattern (the truncate-before-redact bug).
# * a project currently configured `ingest: "off"` is skipped: nothing
#   from its sessions leaves the machine, not even a marker or an id.


def outbound_mode(recorded: Optional[str], current: str, ingest_off: bool) -> Optional[str]:
    """The mode a session's text leaves the machine under, or ``None`` when
    the session must not leave it at all (its project is opted out)."""
    if ingest_off:
        return None
    return stricter_mode(recorded or current, current)


def outbound_text(text: Optional[str], recorded: Optional[str], outbound: str) -> Optional[str]:
    """``text`` as stored when ``outbound`` is the mode it was stored under,
    else a metadata-only marker. Never called for a skipped session."""
    if not text or outbound == (recorded or outbound):
        return text
    return redact_text(text, C.REDACT_METADATA_ONLY)


def current_mode(cfg: Any, override: Any) -> tuple[str, bool]:
    """(the project's current redaction mode, whether it is opted out),
    from its combined ``override`` (``ProjectKeyResolver.override``), else
    the global mode."""
    ingest_off = override is not None and override.ingest == C.INGEST_OFF
    if override is not None and override.redaction_mode is not None:
        return override.redaction_mode, ingest_off
    return cfg.redaction_mode, ingest_off


class OutboundPolicy:
    """The floor for every session in a store, computed once per call.

    ``load`` reads each session's recorded mode and project path in one
    query, resolves each distinct project path once, and keeps three sets:
    the sessions to skip (project opted out), their project paths, and the
    sessions whose stored text must leave as a marker (current mode
    stricter than recorded). When nothing is opted out or tightened, all
    three are empty and every output is unchanged.
    """

    def __init__(
        self,
        *,
        skip_ids: frozenset = frozenset(),
        skip_keys: frozenset = frozenset(),
        excluded_projects: frozenset = frozenset(),
        floored: Optional[Mapping[int, tuple[Optional[str], str]]] = None,
    ) -> None:
        self.skip_ids = skip_ids
        self.skip_keys = skip_keys
        self.excluded_projects = excluded_projects
        self._floored = dict(floored or {})

    @classmethod
    def load(cls, db: Any, cfg: Any = None, *, session_id: Optional[int] = None) -> "OutboundPolicy":
        """The policy for every session, or for ``session_id`` alone."""
        from ..config import load_config
        from .project_key import ProjectKeyResolver

        cfg = cfg if cfg is not None else load_config()
        resolver = ProjectKeyResolver(cfg.project_id_rules) if cfg.projects else None
        by_path: dict[Optional[str], tuple[str, bool]] = {}
        skip_ids: set[int] = set()
        skip_keys: set[str] = set()
        excluded: set[str] = set()
        floored: dict[int, tuple[Optional[str], str]] = {}
        sql = "SELECT id, copilot, session_id, project_path, redaction_mode FROM copilot_session"
        params: tuple = ()
        if session_id is not None:
            sql += " WHERE id = ?"
            params = (int(session_id),)
        for sid, copilot, native, path, recorded in db.query(sql, params):
            if path not in by_path:
                override = resolver.override(cfg.projects, path) if resolver is not None else None
                by_path[path] = current_mode(cfg, override)
            current, ingest_off = by_path[path]
            mode = outbound_mode(recorded, current, ingest_off)
            if mode is None:
                skip_ids.add(int(sid))
                skip_keys.add(f"{copilot}:{native}")
                if path:
                    excluded.add(str(path))
            elif mode != (recorded or mode):
                floored[int(sid)] = (recorded, mode)
        return cls(
            skip_ids=frozenset(skip_ids), skip_keys=frozenset(skip_keys),
            excluded_projects=frozenset(excluded), floored=floored,
        )

    def keeps(self, session_id: Any) -> bool:
        """Whether anything from this session may leave the machine."""
        try:
            return int(session_id) not in self.skip_ids
        except (TypeError, ValueError):
            # An id that is not a session row id cannot be checked against
            # the opt-outs, so it is not sent: fail closed.
            return False

    def keeps_key(self, session_key: Any) -> bool:
        """``keeps`` for a ``copilot:native_id`` session key."""
        return str(session_key) not in self.skip_keys

    def keeps_project(self, project_path: Any) -> bool:
        """Whether a project path may be named or broken down by."""
        return project_path not in self.excluded_projects

    @property
    def any_floored(self) -> bool:
        """Whether any session's stored text leaves as a marker."""
        return bool(self._floored)

    def error_type(self, session_id: Any, value: Optional[str]) -> Optional[str]:
        """A kept session's stored error type as it may leave the machine.
        Under ``none`` ingest stores an error's first line here, so a
        tightened project's value is reduced the way a redacting ingest
        reduces it: to a recognised exception-class name, else "redacted"."""
        if value is None or not self.floors(session_id):
            return value
        return safe_error_type(value, C.REDACT_METADATA_ONLY)

    def error_types(self, rows: list) -> list:
        """``error_type`` reduced on every row of an aggregate that groups
        across sessions, when any session is floored: an aggregate row
        cannot say which session it came from."""
        if not self.any_floored:
            return rows
        return [{**r, "error_type": safe_error_type(r.get("error_type") or "", C.REDACT_METADATA_ONLY)} for r in rows]

    def floors(self, session_id: Any) -> bool:
        """Whether this session's stored text leaves as a marker."""
        return session_id is not None and int(session_id) in self._floored

    def text(self, session_id: Any, text: Optional[str]) -> Optional[str]:
        """A kept session's stored text as it may leave the machine."""
        floor = self._floored.get(int(session_id)) if session_id is not None else None
        if floor is None:
            return text
        return outbound_text(text, floor[0], floor[1])

    def project_filter_sql(self, column: str) -> tuple[str, tuple]:
        """A WHERE fragment leaving out the opted-out projects' rows, for an
        aggregate a filter could otherwise narrow to one of them."""
        if not self.excluded_projects:
            return "1=1", ()
        marks = ", ".join("?" for _ in self.excluded_projects)
        return (
            f"({column} IS NULL OR {column} NOT IN ({marks}))",
            tuple(sorted(self.excluded_projects)),
        )
