# session_analytics.correlate — E9 benchmark-run ↔ session linking (#91).
#
# Two layers, deliberately separated so the matching logic is deterministically
# testable with no real filesystem walk and no DB:
#
#   - ``iter_run_records`` (thin IO): recursively walks a benchmark runs root
#     for ``run-record.json`` files and parses each into a ``RunRecord``
#     (session_id, run_dir). A malformed/unreadable file is skipped (logged),
#     never fatal — one bad attempt directory shouldn't abort the rest of the
#     tree. Redaction-safe: this reads only the run-record's session_id and its
#     containing directory path, never any transcript/session content.
#
#   - ``correlate_links`` (pure core): takes already-parsed records and an
#     injected ``link_fn(session_id, run_dir) -> bool`` (True = a session row
#     was updated) and returns exact ``CorrelationStats``. No DB/FS here — the
#     CLI wires the real ``link_benchmark_run``, tests inject a fake.
#
# Exact-join only (FR-3): matching is a strict equi-join on session_id. A
# null/absent session_id is counted and skipped (no project_path/time-window
# fallback — deferred to a later E9 issue).

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, NamedTuple, Optional

from . import constants as C

_log = logging.getLogger(__name__)


class RunRecord(NamedTuple):
    """A thin ``(session_id, run_dir, backend_id)`` triple parsed from one
    run-record.json.

    ``run_dir`` is the directory CONTAINING that run-record.json — i.e. the
    per-attempt artifact directory (D-run-dir-granularity), not the top-level
    run directory — RESOLVED to an absolute, symlink-free path so the stamped
    value is stable across relative/absolute ``--runs-root`` invocations.
    ``session_id`` is ``None`` when the record carries no session id (bare
    mode, timeouts, or a non-claude backend) — the record is still yielded so
    the pure core can count it, never silently dropped. ``backend_id`` is the
    record's required top-level backend id (``None`` if absent), so the core
    can skip out-of-scope backends instead of miscounting them as unmatched.
    """

    session_id: Optional[str]
    run_dir: str
    backend_id: Optional[str] = None


def iter_run_records(runs_root: Path) -> Iterator[RunRecord]:
    """Recursively walk ``runs_root`` for ``run-record.json`` files.

    Yields one ``RunRecord`` per well-formed file, in path-sorted order (a
    deterministic walk). The root is ``resolve()``d up front (input-boundary
    normalization) so every yielded ``run_dir`` is absolute and stable no
    matter how the caller spelled the root. A file that can't be read or
    parsed as JSON is skipped with a logged warning — it never aborts the
    walk.
    """
    for path in sorted(Path(runs_root).resolve().rglob(C.RUN_RECORD_FILENAME)):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("skipping malformed run-record %s: %s", path, exc)
            continue
        yield RunRecord(
            session_id=_session_id(record),
            run_dir=str(path.parent),
            backend_id=_backend_id(record),
        )


def _session_id(record: object) -> Optional[str]:
    """Walk ``constants.RUN_RECORD_SESSION_ID_PATH`` into ``record``.

    Returns ``None`` (not raises) for any shape mismatch along the way — a
    record missing ``backend``/``metadata``/``session_id`` entirely, or one
    whose leaf is not a string (a dict/list/int would crash the dedup set or
    the parameterized UPDATE downstream), is just another null-session-id
    record, not a malformed file.
    """
    node = record
    for key in C.RUN_RECORD_SESSION_ID_PATH:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if not isinstance(node, str):
        return None
    return node or None


def _backend_id(record: object) -> Optional[str]:
    """The record's top-level ``backend_id`` string, or ``None``."""
    if not isinstance(record, dict):
        return None
    value = record.get(C.RUN_RECORD_BACKEND_ID_KEY)
    return value if isinstance(value, str) and value else None


@dataclass
class CorrelationStats:
    """Exact coverage counters for one ``correlate_links`` run (FR-2).

    ``scanned`` = ``out_of_scope`` + ``with_session_id`` + ``null_session_id``;
    ``linked`` + ``unmatched`` = ``with_session_id`` (every in-scope record
    with a session id is exactly one of the two — never silently dropped).
    ``duplicate_session_id`` counts the 2nd+ occurrence of a session id (those
    records are still linked, last-writer-wins) so a record-count vs
    session-count discrepancy is a visible counter, not a hidden log line.
    """

    scanned: int = 0
    out_of_scope: int = 0
    with_session_id: int = 0
    null_session_id: int = 0
    linked: int = 0
    unmatched: int = 0
    duplicate_session_id: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


LinkFn = Callable[[str, str], bool]


def correlate_links(
    records: Iterable[RunRecord],
    link_fn: LinkFn,
    *,
    backend_id: Optional[str] = None,
) -> CorrelationStats:
    """Pure core: count + link. No DB or filesystem access happens here.

    ``link_fn(session_id, run_dir) -> bool`` is the injected side effect
    (``True`` = a session row was updated); the CLI wires the real
    ``relational.store.link_benchmark_run``, tests inject a fake.

    When ``backend_id`` is given, a record whose OWN backend_id is present and
    different is counted ``out_of_scope`` and skipped — a foreign backend's
    session id (e.g. a future aider/codex run) must never be miscounted as an
    unmatched claude-code session. A record with NO backend_id stays in scope
    (lenient — the session_id equi-join still guards correctness).

    D-collision: if the same session_id appears in more than one record
    (shouldn't happen — each benchmark attempt spawns a fresh session), every
    occurrence is still linked (last-writer-wins on the DB side); it is
    counted in ``duplicate_session_id`` and a warning is logged.
    """
    stats = CorrelationStats()
    seen_session_ids: set[str] = set()
    for record in records:
        stats.scanned += 1
        if (
            backend_id is not None
            and record.backend_id is not None
            and record.backend_id != backend_id
        ):
            stats.out_of_scope += 1
            continue
        if not record.session_id:
            stats.null_session_id += 1
            continue
        stats.with_session_id += 1
        if record.session_id in seen_session_ids:
            stats.duplicate_session_id += 1
            _log.warning(
                "session_id %s appears in more than one run-record; "
                "last-writer-wins (%s)",
                record.session_id, record.run_dir,
            )
        seen_session_ids.add(record.session_id)
        if link_fn(record.session_id, record.run_dir):
            stats.linked += 1
        else:
            stats.unmatched += 1
    return stats
