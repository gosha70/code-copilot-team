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


class Score(NamedTuple):
    """The validated outcome parsed from one attempt dir's ``score.json``.

    Every field is Optional: a MISSING key is tolerated (→ ``None`` → NULL
    column, row still stored). A PRESENT key with a malformed type is never
    carried here — ``_parse_score`` rejects the whole score instead
    (D-parse-strictness): a bad value that slipped into an aggregate would
    corrupt it silently, which is worse than an honestly-missing row.
    """

    benchmark_id: Optional[str] = None
    task_id: Optional[str] = None
    backend_id: Optional[str] = None
    run_id: Optional[str] = None
    attempt: Optional[int] = None
    result: Optional[str] = None
    tests_passed: Optional[bool] = None
    lint_passed: Optional[bool] = None
    typecheck_passed: Optional[bool] = None
    elapsed_seconds: Optional[float] = None
    files_changed: Optional[int] = None
    lines_added: Optional[int] = None
    lines_removed: Optional[int] = None


class RunRecord(NamedTuple):
    """A thin ``(session_id, run_dir, backend_id, score)`` tuple parsed from
    one run-record.json (+ its sibling score.json).

    ``run_dir`` is the directory CONTAINING that run-record.json — i.e. the
    per-attempt artifact directory (D-run-dir-granularity), not the top-level
    run directory — RESOLVED to an absolute, symlink-free path so the stamped
    value is stable across relative/absolute ``--runs-root`` invocations.
    ``session_id`` is ``None`` when the record carries no session id (bare
    mode, timeouts, or a non-claude backend) — the record is still yielded so
    the pure core can count it, never silently dropped. ``backend_id`` is the
    record's required top-level backend id (``None`` if absent), so the core
    can skip out-of-scope backends instead of miscounting them as unmatched.
    ``score`` is the attempt's validated outcome, or ``None`` when score.json
    is missing, unreadable, or malformed (strict-reject) — the IO layer folds
    all three into ``None`` so the pure core has one source of truth for the
    ``scores_missing`` counter.
    """

    session_id: Optional[str]
    run_dir: str
    backend_id: Optional[str] = None
    score: Optional[Score] = None


def iter_run_records(
    runs_root: Path, stats: Optional["CorrelationStats"] = None
) -> Iterator[RunRecord]:
    """Recursively walk ``runs_root`` for ``run-record.json`` files.

    Yields one ``RunRecord`` per well-formed file, in path-sorted order (a
    deterministic walk). The root is ``resolve()``d up front (input-boundary
    normalization) so every yielded ``run_dir`` is absolute and stable no
    matter how the caller spelled the root. A file that can't be read,
    decoded, or parsed as JSON is skipped with a logged warning — it never
    aborts the walk — and, when ``stats`` is given, is counted in
    ``skipped_run_records`` so the drop is a visible counter, not just a log
    line (its sibling score.json, if any, is dropped with it).
    """
    for path in sorted(Path(runs_root).resolve().rglob(C.RUN_RECORD_FILENAME)):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        # ValueError covers both json.JSONDecodeError and UnicodeDecodeError
        # (a bad-encoding file is NOT an OSError — it must not abort the walk).
        except (OSError, ValueError) as exc:
            _log.warning("skipping malformed run-record %s: %s", path, exc)
            if stats is not None:
                stats.skipped_run_records += 1
            continue
        yield RunRecord(
            session_id=_session_id(record),
            run_dir=str(path.parent),
            backend_id=_backend_id(record),
            score=load_score(path.parent / C.SCORE_FILENAME),
        )


def load_score(path: Path) -> Optional[Score]:
    """Parse + validate one ``score.json``; ``None`` = missing OR rejected.

    Missing file → ``None`` silently (an attempt that never got scored is a
    normal state, counted ``scores_missing``). Unreadable / bad JSON / non-dict
    / strict-reject (see ``_parse_score``) → ``None`` with a logged warning.
    Never raises.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    # ValueError catches UnicodeDecodeError (invalid bytes are a malformed
    # file to skip, not a scan-aborting crash — the docstring's "never
    # raises" has to hold for bad encodings too).
    except (OSError, ValueError) as exc:
        _log.warning("skipping unreadable score %s: %s", path, exc)
        return None
    try:
        payload = json.loads(text)
    except ValueError as exc:
        _log.warning("skipping malformed score %s: %s", path, exc)
        return None
    score = _parse_score(payload)
    if score is None:
        _log.warning("skipping malformed score %s: bad field type or result", path)
    return score


class _Malformed(Exception):
    """Internal: a present-but-wrong-typed score field (strict-reject)."""


def _opt_str(v: object) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise _Malformed
    return v


def _opt_bool(v: object) -> Optional[bool]:
    # STRICT: real bools only — 0/1/"true" would silently skew pass-rate
    # aggregates, so they are malformed, not coercible.
    if v is None:
        return None
    if not isinstance(v, bool):
        raise _Malformed
    return v


def _opt_int(v: object) -> Optional[int]:
    # bool check FIRST: isinstance(True, int) is True in Python.
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise _Malformed
    return v


def _opt_num(v: object) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _Malformed
    return float(v)


def _opt_dict(v: object) -> dict:
    # A missing nested block is tolerated as empty; a present non-dict block
    # is malformed (same missing-vs-malformed rule as the scalar validators).
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise _Malformed
    return v


def _parse_score(payload: object) -> Optional[Score]:
    """Validate a score.json payload (D-parse-strictness).

    Tolerant of MISSING keys (absent → ``None`` field); STRICT about
    malformed types where they would corrupt aggregates: a ``result`` outside
    ``constants.SCORE_RESULTS``, a non-numeric counter, a non-bool verify
    flag, or a ``scores``/``derived`` block that isn't a dict rejects the
    WHOLE score (returns ``None``). Missing ≠ malformed.
    """
    if not isinstance(payload, dict):
        return None
    try:
        scores = _opt_dict(payload.get(C.SCORE_KEY_SCORES))
        derived = _opt_dict(payload.get(C.SCORE_KEY_DERIVED))
        result = _opt_str(payload.get(C.SCORE_KEY_RESULT))
        if result is not None and result not in C.SCORE_RESULTS:
            raise _Malformed
        return Score(
            benchmark_id=_opt_str(payload.get(C.SCORE_KEY_BENCHMARK_ID)),
            task_id=_opt_str(payload.get(C.SCORE_KEY_TASK_ID)),
            backend_id=_opt_str(payload.get(C.RUN_RECORD_BACKEND_ID_KEY)),
            run_id=_opt_str(payload.get(C.SCORE_KEY_RUN_ID)),
            attempt=_opt_int(payload.get(C.SCORE_KEY_ATTEMPT)),
            result=result,
            tests_passed=_opt_bool(scores.get(C.SCORE_KEY_TESTS_PASSED)),
            lint_passed=_opt_bool(scores.get(C.SCORE_KEY_LINT_PASSED)),
            typecheck_passed=_opt_bool(scores.get(C.SCORE_KEY_TYPECHECK_PASSED)),
            elapsed_seconds=_opt_num(derived.get(C.SCORE_KEY_ELAPSED_SECONDS)),
            files_changed=_opt_int(derived.get(C.SCORE_KEY_FILES_CHANGED)),
            lines_added=_opt_int(derived.get(C.SCORE_KEY_LINES_ADDED)),
            lines_removed=_opt_int(derived.get(C.SCORE_KEY_LINES_REMOVED)),
        )
    except _Malformed:
        return None


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
    skipped_run_records: int = 0  # unreadable/malformed run-record.json files
    out_of_scope: int = 0
    with_session_id: int = 0
    null_session_id: int = 0
    linked: int = 0
    unmatched: int = 0
    duplicate_session_id: int = 0
    scores_ingested: int = 0  # E9 outcomes (#92)
    scores_missing: int = 0   # score.json absent OR strict-rejected

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


LinkFn = Callable[[str, str], bool]
# (record, in_scope) — the core passes its OWN scoping decision to the sink so
# the backend-scope policy has exactly one implementation (see correlate_links).
StoreResultFn = Callable[["RunRecord", bool], None]


def correlate_links(
    records: Iterable[RunRecord],
    link_fn: LinkFn,
    *,
    backend_id: Optional[str] = None,
    store_result_fn: Optional[StoreResultFn] = None,
    stats: Optional[CorrelationStats] = None,
) -> CorrelationStats:
    """Pure core: count + link. No DB or filesystem access happens here.

    ``link_fn(session_id, run_dir) -> bool`` is the injected side effect
    (``True`` = a session row was updated); the CLI wires the real
    ``relational.store.link_benchmark_run``, tests inject a fake.

    When ``backend_id`` is given, a record whose OWN backend_id is present and
    different is counted ``out_of_scope`` and its session is never linked — a
    foreign backend's session id (e.g. a future aider/codex run) must never be
    miscounted as an unmatched claude-code session. A record with NO
    backend_id stays in scope (lenient — the session_id equi-join still
    guards correctness).

    ``store_result_fn(record, in_scope)`` (E9 outcomes, #92) is the injected
    outcome sink, called for EVERY record whose ``score`` parsed — INCLUDING
    out-of-scope backends (D-store-outcomes-for-foreign-backends: the result
    table is backend-agnostic analytical record; only session LINKING is
    backend-scoped). ``in_scope`` is THIS function's own scoping decision,
    passed along so the sink never re-derives the policy (one source of
    truth). ``score is None`` → ``scores_missing``.

    ``stats`` may be passed in pre-created; it is mutated in place and also
    returned — the CLI uses this so a mid-run exception still has the partial
    counters to print (FR-4). Omitted → a fresh instance.

    D-collision: if the same session_id appears in more than one record
    (shouldn't happen — each benchmark attempt spawns a fresh session), every
    occurrence is still linked (last-writer-wins on the DB side); it is
    counted in ``duplicate_session_id`` and a warning is logged.
    """
    if stats is None:
        stats = CorrelationStats()
    seen_session_ids: set[str] = set()
    for record in records:
        stats.scanned += 1
        # THE scoping decision — computed once here, used for both the
        # out_of_scope counter and the sink's session linkage (a record with
        # NO backend_id stays in scope; lenient).
        in_scope = not (
            backend_id is not None
            and record.backend_id is not None
            and record.backend_id != backend_id
        )
        # Outcome sink first — backend-agnostic, independent of link scoping.
        if store_result_fn is not None:
            if record.score is not None:
                store_result_fn(record, in_scope)
                stats.scores_ingested += 1
            else:
                stats.scores_missing += 1
        if not in_scope:
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
