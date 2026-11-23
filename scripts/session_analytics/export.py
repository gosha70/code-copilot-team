# session_analytics.export — CSV/Parquet export over the relational store
# (E7, issue #87).
#
# Read-only over the relational store: it NEVER re-reads raw transcripts, so
# an export can only ever surface what ingest already wrote — redaction-safe
# by construction (FR-6). A project opted out under E8 before ingest has no
# rows; one opted out or tightened after ingest is handled by the privacy
# floor below (#487).
#
# Each table has a FIXED, documented column order (below) and a deterministic
# ``ORDER BY``, so two exports of an unchanged store are identical. Row
# generators stream via the DB-API cursor directly (``for row in cur``) — the
# full table is never materialized as a Python list for CSV. Parquet
# (D-parquet-in-memory) still needs the whole table in memory to build one
# ``pyarrow.Table``, so only the Parquet path materializes the generator's
# output; CSV never does.

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from . import constants as C
from .relational.db import Database

# ── column orders (fixed, documented — see spec FR-2) ───────────────────

# One row per session (denormalized): the core session_analytics.session
# columns, the E5 cost rollup (Σ its turns' cost_usd), and the session_kpi
# columns (LEFT JOIN — NULL when the session has no labeled turns). A
# session with labels under more than one rubric contributes exactly one
# session_kpi row here (the lexicographically-first rubric_name), matching
# the dedup convention used for per-turn sentiment in api/dashboard.py. The
# trailing benchmark_run_dir column (E9, #91) is the linked benchmark
# attempt's artifact directory — NULL for an organic (non-benchmark) session.
SESSIONS_COLUMNS: tuple[str, ...] = (
    "id", "copilot", "session_id", "project_path", "model", "phase",
    "developer_id", "redaction_mode", "turn_count", "tool_call_count",
    "error_count", "started_at", "ended_at", "duration_seconds", "cost_usd",
    "kpi_rubric_name", "kpi_labeled_turn_count", "kpi_correction_rate",
    "kpi_rework_rate", "kpi_first_attempt_success_rate", "kpi_autonomy_score",
    "kpi_avg_interaction_quality", "kpi_computed_at",
    C.COL_BENCHMARK_RUN_DIR,
)

# One row per turn. ``redaction_mode`` is the parent session's mode (the turn
# table has no column of its own); ``content_preview`` is the stored,
# already-redacted value (decision D-turns-content — export = what the store
# holds; a ``redaction: none`` session's raw preview is the operator's own
# ingest-time choice, and the per-row ``redaction_mode`` documents it).
TURNS_COLUMNS: tuple[str, ...] = (
    "session_id", "sequence_num", "role", "content_length", "has_tool_use",
    "tokens_input", "tokens_output", "cache_read_tokens", "cache_write_tokens",
    "cost_usd", "model", "cost_price_version", "redaction_mode",
    "content_preview",
)

# One row per heuristic_label (the judge's per-turn labels).
LABELS_COLUMNS: tuple[str, ...] = (
    "id", "turn_id", "rubric_name", "user_corrects_agent", "user_asks_question",
    "user_gives_command", "agent_asks_clarification", "user_changes_approach",
    "agent_changes_approach", "has_misunderstanding", "response_helpful",
    "rework_detected", "sentiment", "interaction_quality",
    "judge_id", "judge_model", "parse_status", "created_at",
)

# One row per session_kpi (the session-level rollup a rubric produced).
KPIS_COLUMNS: tuple[str, ...] = (
    "id", "session_id", "rubric_name", "labeled_turn_count", "correction_rate",
    "rework_rate", "first_attempt_success_rate", "autonomy_score",
    "avg_interaction_quality", "computed_at",
)

# One row per benchmark attempt outcome (E9 outcomes, #92) — the stable
# identity + result the ``correlate`` command ingested from score.json.
# ``session_ref`` is the linked copilot_session.id (NULL for unmatched /
# out-of-scope-backend attempts).
BENCHMARK_RESULTS_COLUMNS: tuple[str, ...] = (
    "id", "run_dir", "benchmark_id", "task_id", "backend_id", "run_id",
    "attempt", "result", "tests_passed", "lint_passed", "typecheck_passed",
    "elapsed_seconds", "files_changed", "lines_added", "lines_removed",
    "session_ref", "ingested_at",
)

# One row per archived (REDACTED) trace turn (E10 Slice A, #98). Redaction-
# safe by construction: trace_document only ever holds text that passed
# redact_text under the FR-4 floor; the per-row redaction_mode documents it.
# NOTE: unlike every other export table this carries FULL redacted turn
# text, not 500-char previews — `--table all` includes it (see README's
# export section for the disclosure note). Turns are anchored by
# (session_ref, sequence_num), not turn ids (stable across re-ingests).
TRACE_DOCUMENTS_COLUMNS: tuple[str, ...] = (
    "id", "session_ref", "sequence_num", "source_kind", "content",
    "content_hash", "source_path", "redaction_mode", "archived_at",
)

# #371 A3. Like trace_documents this carries a person's own words
# (value_text, rationale), unredacted by design; anchored by sequence
# numbers, not turn/tool-call ids. value_bool is normalized to 0/1.
FEEDBACK_COLUMNS: tuple[str, ...] = (
    "id", "session_ref", "sequence_num", "tool_sequence_num", "name",
    "value_bool", "value_num", "value_text", "rationale", "source_type",
    "source_id", "supersedes", "created_at",
)

_COLUMNS: dict[str, tuple[str, ...]] = {
    C.EXPORT_TABLE_SESSIONS: SESSIONS_COLUMNS,
    C.EXPORT_TABLE_TURNS: TURNS_COLUMNS,
    C.EXPORT_TABLE_LABELS: LABELS_COLUMNS,
    C.EXPORT_TABLE_KPIS: KPIS_COLUMNS,
    C.EXPORT_TABLE_BENCHMARK_RESULTS: BENCHMARK_RESULTS_COLUMNS,
    C.EXPORT_TABLE_TRACE_DOCUMENTS: TRACE_DOCUMENTS_COLUMNS,
    C.EXPORT_TABLE_FEEDBACK: FEEDBACK_COLUMNS,
}

# Boolean columns are stored with dialect-dependent affinity (SQLite returns
# 0/1 ints; psycopg returns real bools) — normalize to 0/1 so an export looks
# identical regardless of the backing store.
_TURNS_BOOL_IDX = (4,)  # has_tool_use
# DERIVED from LABELS_COLUMNS by NAME, not hardcoded positions. These
# indices used to be a literal tuple, and removing one boolean column
# (#300's phase_violation) silently shifted `sentiment` into the bool
# range — the normalizer then coerced 'NEUTRAL' to 1 and exported a
# corrupted column. A positional list that must be re-counted by hand
# whenever a column moves is a defect waiting for the next edit.
_LABELS_BOOL_NAMES = C.LABEL_BOOL_NAMES
_LABELS_BOOL_IDX = tuple(
    LABELS_COLUMNS.index(name) for name in _LABELS_BOOL_NAMES
)
_BENCHMARK_RESULTS_BOOL_IDX = (8, 9, 10)  # tests/lint/typecheck _passed

# ── SQL (dialect-agnostic: plain SELECT/JOIN, ``?`` placeholders unused —
#    no filters in v1) ───────────────────────────────────────────────────

# Mirrors the E5 session-cost rollup shape used by mcp/tools.py's
# ``_COST_ROLLUP_SQL``: session cost = Σ its turns' cost_usd, computed at
# query time (not a materialized column) — NULL when no turn in the session
# has a priced model.
_SESSIONS_SQL = f"""
    SELECT
        s.id, s.copilot, s.session_id, s.project_path, s.model, s.phase,
        s.developer_id, s.redaction_mode, s.turn_count, s.tool_call_count,
        s.error_count, s.started_at, s.ended_at, s.duration_seconds,
        (SELECT SUM(t.cost_usd) FROM copilot_turn t WHERE t.session_id = s.id),
        k.rubric_name, k.labeled_turn_count, k.correction_rate, k.rework_rate,
        k.first_attempt_success_rate, k.autonomy_score,
        k.avg_interaction_quality, k.computed_at, s.{C.COL_BENCHMARK_RUN_DIR}
    FROM copilot_session s
    LEFT JOIN (
        SELECT sk.session_id, sk.rubric_name, sk.labeled_turn_count,
               sk.correction_rate, sk.rework_rate, sk.first_attempt_success_rate,
               sk.autonomy_score,
               sk.avg_interaction_quality, sk.computed_at
        FROM session_kpi sk
        WHERE sk.rubric_name = (
            SELECT MIN(sk2.rubric_name) FROM session_kpi sk2
            WHERE sk2.session_id = sk.session_id
        )
    ) k ON k.session_id = s.id
    ORDER BY s.id
"""

_TURNS_SQL = """
    SELECT t.session_id, t.sequence_num, t.role, t.content_length,
           t.has_tool_use, t.tokens_input, t.tokens_output,
           t.cache_read_tokens, t.cache_write_tokens, t.cost_usd, t.model,
           t.cost_price_version, s.redaction_mode, t.content_preview
    FROM copilot_turn t
    JOIN copilot_session s ON s.id = t.session_id
    ORDER BY t.session_id, t.sequence_num
"""

_LABELS_SQL = """
    SELECT id, turn_id, rubric_name, user_corrects_agent, user_asks_question,
           user_gives_command, agent_asks_clarification, user_changes_approach,
           agent_changes_approach, has_misunderstanding, response_helpful,
           rework_detected, sentiment, interaction_quality,
           judge_id, judge_model, parse_status, created_at
    FROM heuristic_label
    ORDER BY turn_id, rubric_name
"""

_KPIS_SQL = """
    SELECT id, session_id, rubric_name, labeled_turn_count, correction_rate,
           rework_rate, first_attempt_success_rate, autonomy_score,
           avg_interaction_quality, computed_at
    FROM session_kpi
    ORDER BY session_id, rubric_name
"""

_BENCHMARK_RESULTS_SQL = f"""
    SELECT id, run_dir, benchmark_id, task_id, backend_id, run_id, attempt,
           result, tests_passed, lint_passed, typecheck_passed,
           elapsed_seconds, files_changed, lines_added, lines_removed,
           session_ref, ingested_at
    FROM {C.TBL_BENCHMARK_RESULT}
    ORDER BY id
"""

_TRACE_DOCUMENTS_SQL = f"""
    SELECT id, session_ref, sequence_num, source_kind, content, content_hash,
           source_path, redaction_mode, archived_at
    FROM {C.TBL_TRACE_DOCUMENT}
    ORDER BY id
"""

_FEEDBACK_SQL = f"""
    SELECT id, session_ref, sequence_num, tool_sequence_num, name,
           value_bool, value_num, value_text, rationale, source_type,
           source_id, supersedes, created_at
    FROM {C.TBL_FEEDBACK}
    ORDER BY id
"""
_FEEDBACK_BOOL_IDX = (FEEDBACK_COLUMNS.index("value_bool"),)


def _bool01(v: Any) -> Any:
    """Normalize a stored boolean-affinity value to 0/1 (``None`` stays ``None``)."""
    return v if v is None else int(bool(v))


def _stream(db: Database, sql: str, bool_idx: tuple[int, ...] = ()) -> Iterator[tuple]:
    """Yield rows one at a time from the DB-API cursor (no ``fetchall()``).

    ``execute()`` returns the live cursor; iterating it directly is the
    actual streaming mechanism (sqlite3 and psycopg cursors both support
    row-by-row iteration) — no second Python list is built here.
    """
    cur = db.execute(sql)
    for row in cur:
        if not bool_idx:
            yield tuple(row)
            continue
        r = list(row)
        for i in bool_idx:
            r[i] = _bool01(r[i])
        yield tuple(r)


def iter_sessions(db: Database) -> Iterator[tuple]:
    """Stream ``sessions`` rows in ``SESSIONS_COLUMNS`` order, by ``id``."""
    return _stream(db, _SESSIONS_SQL)


def iter_turns(db: Database) -> Iterator[tuple]:
    """Stream ``turns`` rows in ``TURNS_COLUMNS`` order, by (session_id, sequence_num)."""
    return _stream(db, _TURNS_SQL, _TURNS_BOOL_IDX)


def iter_labels(db: Database) -> Iterator[tuple]:
    """Stream ``labels`` rows in ``LABELS_COLUMNS`` order, by (turn_id, rubric_name)."""
    return _stream(db, _LABELS_SQL, _LABELS_BOOL_IDX)


def iter_kpis(db: Database) -> Iterator[tuple]:
    """Stream ``kpis`` rows in ``KPIS_COLUMNS`` order, by (session_id, rubric_name)."""
    return _stream(db, _KPIS_SQL)


def iter_benchmark_results(db: Database) -> Iterator[tuple]:
    """Stream ``benchmark_results`` rows in ``BENCHMARK_RESULTS_COLUMNS`` order, by ``id``."""
    return _stream(db, _BENCHMARK_RESULTS_SQL, _BENCHMARK_RESULTS_BOOL_IDX)


def iter_trace_documents(db: Database) -> Iterator[tuple]:
    """Stream ``trace_documents`` rows in ``TRACE_DOCUMENTS_COLUMNS`` order, by ``id``."""
    return _stream(db, _TRACE_DOCUMENTS_SQL)


def iter_feedback(db: Database) -> Iterator[tuple]:
    """Stream ``feedback`` rows in ``FEEDBACK_COLUMNS`` order, by ``id``."""
    return _stream(db, _FEEDBACK_SQL, _FEEDBACK_BOOL_IDX)


_ROW_ITERATORS = {
    C.EXPORT_TABLE_SESSIONS: iter_sessions,
    C.EXPORT_TABLE_TURNS: iter_turns,
    C.EXPORT_TABLE_LABELS: iter_labels,
    C.EXPORT_TABLE_KPIS: iter_kpis,
    C.EXPORT_TABLE_BENCHMARK_RESULTS: iter_benchmark_results,
    C.EXPORT_TABLE_TRACE_DOCUMENTS: iter_trace_documents,
    C.EXPORT_TABLE_FEEDBACK: iter_feedback,
}


class UnknownExportTableError(ValueError):
    """Raised for a table name outside ``constants.EXPORT_DATA_TABLES``."""


# ── the privacy floor (#487) ────────────────────────────────────────────
#
# By default `export` applies the floor every off-machine path applies
# (#457): each session's project is read under its CURRENT settings, with
# #478's combined check, through one OutboundPolicy per run. The rule for
# every column is in specs/export-privacy-floor/spec.md ("Column
# decisions"):
#
# * an opted-out project's sessions have no row in any table of session
#   data; a benchmark outcome linked to one keeps its row with session_ref
#   empty, and a run directory under an opted-out project's path is
#   emptied wherever it is written (benchmark_results.run_dir,
#   sessions.benchmark_run_dir);
# * a tightened project's stored text (turns.content_preview,
#   trace_documents.content) leaves as the metadata-only marker, and its
#   redaction_mode reads metadata-only; feedback text stays as stored;
# * every other column is written as stored.
#
# Under ``raw`` every row is written as stored, and the floor only records
# the sessions it would have dropped or changed, for the one-line notice. A
# store with nothing opted out or tightened takes the unfiltered path, so
# its export is byte for byte what it was before.

# heuristic_label has no session column: the session comes from the turn
# (turn_id is NOT NULL and references copilot_turn), as a trailing column
# that is used to filter and never written.
_LABELS_WITH_SESSION_SQL = f"""
    SELECT {", ".join(f"hl.{c}" for c in LABELS_COLUMNS)}, t.session_id
    FROM heuristic_label hl
    JOIN copilot_turn t ON t.id = hl.turn_id
    ORDER BY hl.turn_id, hl.rubric_name
"""

_DROPPED, _REDUCED, _EMPTIED = "dropped", "reduced", "emptied"


@dataclass(frozen=True)
class _FloorRule:
    """Where a table's session id and floored columns are."""

    session_idx: Optional[int]  # None: the session is joined on (labels)
    text_idx: tuple[int, ...] = ()  # stored text, replaced by the marker
    mode_idx: Optional[int] = None  # redaction_mode, set to metadata-only
    keeps_row: bool = False  # benchmark_results: empty the link, keep the row
    run_dir_idx: Optional[int] = None  # a run directory, emptied under an opted-out path
    emptied: str = ""  # what the summary says was emptied


_FLOOR_RULES: dict[str, _FloorRule] = {
    C.EXPORT_TABLE_SESSIONS: _FloorRule(
        session_idx=SESSIONS_COLUMNS.index("id"),
        mode_idx=SESSIONS_COLUMNS.index("redaction_mode"),
        run_dir_idx=SESSIONS_COLUMNS.index(C.COL_BENCHMARK_RUN_DIR),
        emptied=C.COL_BENCHMARK_RUN_DIR,
    ),
    C.EXPORT_TABLE_TURNS: _FloorRule(
        session_idx=TURNS_COLUMNS.index("session_id"),
        text_idx=(TURNS_COLUMNS.index("content_preview"),),
        mode_idx=TURNS_COLUMNS.index("redaction_mode"),
    ),
    C.EXPORT_TABLE_LABELS: _FloorRule(session_idx=None),
    C.EXPORT_TABLE_KPIS: _FloorRule(session_idx=KPIS_COLUMNS.index("session_id")),
    C.EXPORT_TABLE_BENCHMARK_RESULTS: _FloorRule(
        session_idx=BENCHMARK_RESULTS_COLUMNS.index("session_ref"),
        keeps_row=True,
        run_dir_idx=BENCHMARK_RESULTS_COLUMNS.index("run_dir"),
        emptied="session_ref or run_dir",
    ),
    C.EXPORT_TABLE_TRACE_DOCUMENTS: _FloorRule(
        session_idx=TRACE_DOCUMENTS_COLUMNS.index("session_ref"),
        text_idx=(TRACE_DOCUMENTS_COLUMNS.index("content"),),
        mode_idx=TRACE_DOCUMENTS_COLUMNS.index("redaction_mode"),
    ),
    C.EXPORT_TABLE_FEEDBACK: _FloorRule(session_idx=FEEDBACK_COLUMNS.index("session_ref")),
}


def _under_any(path: Any, roots: frozenset) -> bool:
    """Whether ``path`` is one of ``roots`` or inside one, by whole path
    components (``/a/bc`` is not inside ``/a/b``)."""
    if not path or not roots:
        return False
    p = os.path.normpath(str(path))
    for root in roots:
        r = os.path.normpath(str(root))
        if p == r or p.startswith(r.rstrip(os.sep) + os.sep):
            return True
    return False


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


class ExportFloor:
    """One ``OutboundPolicy`` applied to every table an export writes.

    ``changes`` counts, per written table, the rows the floor dropped,
    reduced to metadata-only, or kept with a link emptied. Under ``raw``
    nothing is changed, and ``raw_opted_out`` / ``raw_tightened`` collect
    the sessions whose rows in the written tables it would have dropped or
    changed.
    """

    def __init__(self, policy: Any, *, raw: bool = False) -> None:
        self.policy = policy
        self.raw = raw
        self.changes: dict[str, dict[str, int]] = {}
        self.raw_opted_out: set[int] = set()
        self.raw_tightened: set[int] = set()

    @property
    def inert(self) -> bool:
        """Nothing in the store is opted out or tightened."""
        return not self.policy.skip_ids and not self.policy.any_floored

    def rows(self, db: Database, table: str) -> Iterator[tuple]:
        """``table``'s rows as the floor lets them leave (as stored under
        ``raw``), counting what it changed. Complete once exhausted."""
        rule = _FLOOR_RULES[table]
        counts = self.changes.setdefault(table, {_DROPPED: 0, _REDUCED: 0, _EMPTIED: 0})
        joined = rule.session_idx is None
        if self.inert or (joined and not self.policy.skip_ids):
            # Nothing in this table can change: the unfiltered path.
            yield from _ROW_ITERATORS[table](db)
            return
        source = _stream(db, _LABELS_WITH_SESSION_SQL, _LABELS_BOOL_IDX) if joined else _ROW_ITERATORS[table](db)
        for row in source:
            if joined:
                sid, row = row[-1], row[:-1]
            else:
                sid = row[rule.session_idx]
            out, changes = self._apply(rule, row, sid)
            for change in changes:
                counts[change] += 1
                if self.raw:
                    self._note_raw(change, sid)
            if self.raw:
                yield row
            elif out is not None:
                yield out

    def _apply(self, rule: _FloorRule, row: tuple, sid: Any) -> tuple[Optional[tuple], tuple[str, ...]]:
        """(the row as it may leave, or ``None`` when dropped; what changed —
        a kept row can be both reduced and have a link emptied)."""
        policy = self.policy
        if not rule.keeps_row and not policy.keeps(sid):
            return None, (_DROPPED,)
        r = list(row)
        changes: list[str] = []
        if policy.floors(sid):
            for i in rule.text_idx:
                r[i] = policy.text(sid, r[i])
            if rule.mode_idx is not None:
                r[rule.mode_idx] = C.REDACT_METADATA_ONLY
            if r != list(row):
                changes.append(_REDUCED)
        before = list(r)
        if rule.keeps_row and sid is not None and not policy.keeps(sid):
            r[rule.session_idx] = None
        if rule.run_dir_idx is not None and _under_any(r[rule.run_dir_idx], policy.excluded_projects):
            r[rule.run_dir_idx] = None
        if r != before:
            changes.append(_EMPTIED)
        return tuple(r), tuple(changes)

    def _note_raw(self, change: str, sid: Any) -> None:
        try:
            sid = int(sid)
        except (TypeError, ValueError):
            return  # a run_dir emptied in a row linked to no session
        if change == _REDUCED:
            self.raw_tightened.add(sid)
        elif not self.policy.keeps(sid):  # dropped, or its benchmark link emptied
            self.raw_opted_out.add(sid)

    def table_summary(self, table: str) -> Optional[str]:
        """One stderr line of what the floor changed in ``table``, in counts
        only; ``None`` when it changed nothing, and always under ``raw``."""
        if self.raw:
            return None
        c = self.changes.get(table) or {}
        parts = []
        if c.get(_DROPPED):
            parts.append(f"{_count(c[_DROPPED], 'row')} dropped (project opted out)")
        if c.get(_REDUCED):
            parts.append(f"{_count(c[_REDUCED], 'row')} reduced to metadata-only (project tightened since ingest)")
        if c.get(_EMPTIED):
            parts.append(f"{_count(c[_EMPTIED], 'row')} with {_FLOOR_RULES[table].emptied} emptied (opted-out project)")
        return f"export: {table}: " + "; ".join(parts) if parts else None

    def raw_summary(self) -> str:
        """The one stderr line ``--raw`` prints, zeros included."""
        return (
            f"export --raw: wrote {_count(len(self.raw_opted_out), 'session')} of opted-out projects "
            f"and {_count(len(self.raw_tightened), 'session')} of tightened projects as stored"
        )


def columns_for(table: str) -> tuple[str, ...]:
    """The fixed column order for ``table`` (one of ``EXPORT_DATA_TABLES``)."""
    try:
        return _COLUMNS[table]
    except KeyError:
        raise UnknownExportTableError(f"unknown export table: {table!r}") from None


def rows_for(db: Database, table: str, floor: Optional[ExportFloor] = None) -> Iterator[tuple]:
    """A streaming row generator for ``table`` (one of ``EXPORT_DATA_TABLES``):
    as ``floor`` lets the rows leave (#487), or as stored without one."""
    try:
        gen = _ROW_ITERATORS[table]
    except KeyError:
        raise UnknownExportTableError(f"unknown export table: {table!r}") from None
    return gen(db) if floor is None else floor.rows(db, table)


# ── CSV writer (stdlib csv, streamed) ───────────────────────────────────


def write_csv(db: Database, table: str, fp, floor: Optional[ExportFloor] = None) -> None:
    """Stream ``table`` to ``fp`` (any text-mode writable) as CSV.

    Rows are written one at a time as they arrive from the DB-API cursor —
    the full table is never materialized as a Python list here.
    """
    writer = csv.writer(fp)
    writer.writerow(columns_for(table))
    for row in rows_for(db, table, floor):
        writer.writerow(row)


# ── Parquet writer (pyarrow, lazy import — D-parquet-in-memory) ─────────


def write_parquet(db: Database, table: str, path, floor: Optional[ExportFloor] = None) -> None:
    """Write ``table`` to the Parquet file at ``path``; same columns/order as CSV.

    ``pyarrow`` is imported lazily here — never at module import time — so
    the rest of ``export`` (and the whole unit-test suite) works with zero
    third-party dependencies. Raises ``ImportError`` when ``pyarrow`` isn't
    installed; callers (``cli.py``) must catch it and turn it into a usage
    error with an install hint, never let it surface as a traceback.

    D-parquet-in-memory (v1): the full table is built in memory before
    writing — fine at local single-store scale; batched/streamed Parquet
    writing is out of scope for this slice.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    columns = columns_for(table)
    data = list(rows_for(db, table, floor))
    by_column: list[list[Any]] = (
        [list(col) for col in zip(*data)] if data else [[] for _ in columns]
    )
    pa_table = pa.table(dict(zip(columns, by_column)))
    pq.write_table(pa_table, str(path))
