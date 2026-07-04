# session_analytics.contracts — ingestion adapter contract surface.
#
# Mirrors benchmark_runner.contracts: frozen dataclasses + a
# runtime_checkable Protocol. The pipeline is copilot-agnostic — any
# copilot (Claude Code, Aider, future Cursor/Codex) implements
# ``SessionAdapter`` to turn its native on-disk format into a uniform
# ``RawSession``. The relational/graph/judge layers downstream never see
# copilot-specific shapes.
#
# Split of responsibility:
#   - the adapter owns "what is a session in this copilot and how do I
#     read it off disk."
#   - the harness owns normalization, persistence, the graph, the judge,
#     and the UI.
#
# All dataclasses are frozen — parsed records must not mutate after
# capture. Null-vs-zero discipline (mirrors BackendResult): ``None`` means
# "the source did not provide this signal"; ``0``/``False`` means "the
# source provided it and it was zero/false." Never coerce one to the other.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, runtime_checkable


# ── Discovery primitive ────────────────────────────────────────────────


@dataclass(frozen=True)
class SessionRef:
    """A cheap handle to one logical session, produced by ``discover``.

    ``discover`` must be cheap (a directory glob / index query) so the
    incremental layer can decide whether to ``load`` (full parse) at all.
    A logical session may span multiple source files (Claude Code writes
    one JSONL per continuation but they share a ``sessionId``);
    ``source_files`` lists every file that contributes, and
    ``latest_mtime`` is the max mtime across them — the incremental gate
    skips refs whose ``latest_mtime`` has not advanced since last ingest.
    """

    copilot: str
    native_session_id: str
    source_files: tuple[Path, ...]
    latest_mtime: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


# ── Parsed-session primitives ──────────────────────────────────────────


@dataclass(frozen=True)
class RawToolCall:
    """One tool invocation inside a turn, plus its paired result.

    ``name_raw`` is the copilot's original tool name (``Bash``,
    ``execute_bash``, ``Read``); ``normalize`` maps it to a canonical id
    downstream. ``result_is_error`` is ``None`` when no result was paired
    (the turn ended before the tool returned), ``True``/``False`` otherwise
    — distinct states the error layer relies on.
    """

    tool_use_id: Optional[str]
    name_raw: str
    input_obj: Mapping[str, Any]
    sequence_num: int
    result_is_error: Optional[bool] = None
    result_text: Optional[str] = None


@dataclass(frozen=True)
class RawTurn:
    """One message turn in a session.

    ``parent_uuid`` threads the turn DAG (Claude Code); ``is_sidechain``
    marks subagent branches. Token fields are ``Optional[int]`` —
    ``None`` when the source did not report them. ``slash_command`` is the
    bare command name (``/compact``) when the user turn was a slash
    command, else ``None``.
    """

    sequence_num: int
    role: str
    text: str
    content_length: int
    uuid: Optional[str] = None
    parent_uuid: Optional[str] = None
    is_sidechain: bool = False
    tool_calls: tuple[RawToolCall, ...] = ()
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    timestamp: Optional[str] = None
    slash_command: Optional[str] = None


@dataclass(frozen=True)
class RawSession:
    """A fully parsed session in copilot-agnostic form.

    ``native_session_id`` is the copilot's own id; the natural key for
    idempotent upsert is ``(copilot, native_session_id)``. ``source_files``
    is carried through for incremental-ingest bookkeeping. ``model`` /
    timestamps are ``Optional`` because not every source records them.
    """

    copilot: str
    native_session_id: str
    turns: tuple[RawTurn, ...]
    source_files: tuple[Path, ...]
    project_path: Optional[str] = None
    model: Optional[str] = None
    agent_profile: Optional[str] = None
    phase: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


# ── Protocol ───────────────────────────────────────────────────────────


@runtime_checkable
class SessionAdapter(Protocol):
    """Contract every copilot ingestion adapter must satisfy.

    Implementations live under
    ``scripts/session_analytics/adapters/<copilot>.py`` and register via
    ``session_analytics.registry``.
    """

    copilot_id: str

    def discover(self, root: Optional[Path]) -> list[SessionRef]:
        """Cheaply enumerate sessions under ``root`` (or the configured
        default when ``root`` is ``None``). Must not fully parse."""

    def load(self, ref: SessionRef) -> RawSession:
        """Fully parse the session referenced by ``ref`` into a
        ``RawSession``. Called only after the incremental gate decides
        the session is new or changed."""
