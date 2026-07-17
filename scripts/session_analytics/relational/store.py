# session_analytics.relational.store — idempotent session persistence.
#
# Idempotency (AC): the natural key is ``(copilot, session_id)``. A session
# upsert is INSERT … ON CONFLICT DO UPDATE RETURNING id; its children
# (turns, tool calls/results, file access, errors, heuristic labels, kpi)
# are delete-then-reinsert scoped to that session id inside one transaction.
# Re-ingesting an unchanged session converges to the identical row set; a
# re-ingested-and-grown session converges to the correct larger set — never
# duplicated, never orphaned.
#
# file_access and copilot_error are DERIVED here from each turn's tool calls
# (the adapter stays format-focused; derivation lives in one place).

from __future__ import annotations

import logging
from typing import Optional

from .. import constants as C
from ..config import PricingConfig
from ..contracts import RawSession, RawTurn
from ..cost import UnpricedStats, compute_turn_cost
from ..ingest import redaction
from ..normalize import files as files_norm
from ..normalize import tool_names
from .db import Database

_log = logging.getLogger(__name__)

# Normalized tool id → file access type.
_ACCESS_BY_TOOL = {
    "file_read": C.ACCESS_READ,
    "file_search": C.ACCESS_READ,
    "file_write": C.ACCESS_WRITE,
    "file_edit": C.ACCESS_WRITE,
}


def upsert_session(
    db: Database,
    raw: RawSession,
    *,
    developer_id: str = C.DEFAULT_DEVELOPER_ID,
    redaction_mode: str = C.REDACT_CODE,
    pricing: Optional[PricingConfig] = None,
    unpriced: Optional[UnpricedStats] = None,
) -> int:
    """Idempotently persist ``raw`` and its children. Returns the session id.

    Commits on success; the caller may also wrap multiple sessions in an
    outer transaction by passing a shared ``db`` and committing once.

    ``pricing`` is the E5 price table (``None`` — the default — leaves every
    turn's ``cost_usd`` NULL, matching pre-E5 behavior). When given, a turn
    whose model isn't in the table also stays NULL but is tallied in
    ``unpriced`` when the caller passes one (for end-of-ingest reporting).
    """
    turn_count = len(raw.turns)
    tool_call_count = sum(len(t.tool_calls) for t in raw.turns)
    error_count = sum(
        1 for t in raw.turns for tc in t.tool_calls if tc.result_is_error
    )
    duration = _duration_seconds(raw.started_at, raw.ended_at)
    content_redacted = redaction.content_is_redacted(redaction_mode)

    session_id = _upsert_session_row(
        db,
        raw,
        developer_id=developer_id,
        redaction_mode=redaction_mode,
        content_redacted=content_redacted,
        turn_count=turn_count,
        tool_call_count=tool_call_count,
        error_count=error_count,
        duration=duration,
    )

    _delete_children(db, session_id)

    for turn in raw.turns:
        _insert_turn_tree(db, session_id, turn, redaction_mode, pricing, unpriced)

    db.commit()
    return session_id


# ── session row ────────────────────────────────────────────────────────


def _upsert_session_row(
    db: Database,
    raw: RawSession,
    *,
    developer_id: str,
    redaction_mode: str,
    content_redacted: bool,
    turn_count: int,
    tool_call_count: int,
    error_count: int,
    duration: Optional[int],
) -> int:
    sql = """
        INSERT INTO copilot_session
            (copilot, session_id, project_path, model, agent_profile, phase,
             developer_id, turn_count, tool_call_count, error_count,
             started_at, ended_at, duration_seconds,
             redaction_mode, content_redacted, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'local')
        ON CONFLICT (copilot, session_id) DO UPDATE SET
            project_path=excluded.project_path,
            model=excluded.model,
            agent_profile=excluded.agent_profile,
            phase=excluded.phase,
            developer_id=excluded.developer_id,
            turn_count=excluded.turn_count,
            tool_call_count=excluded.tool_call_count,
            error_count=excluded.error_count,
            started_at=excluded.started_at,
            ended_at=excluded.ended_at,
            duration_seconds=excluded.duration_seconds,
            redaction_mode=excluded.redaction_mode,
            content_redacted=excluded.content_redacted
        RETURNING id
    """
    return db.insert_returning_id(
        sql,
        (
            raw.copilot,
            raw.native_session_id,
            raw.project_path,
            raw.model,
            raw.agent_profile,
            raw.phase,
            developer_id,
            turn_count,
            tool_call_count,
            error_count,
            raw.started_at,
            raw.ended_at,
            duration,
            redaction_mode,
            content_redacted,
        ),
    )


# ── child deletion (dependency order) ──────────────────────────────────


def _delete_children(db: Database, session_id: int) -> None:
    # Delete in strict dependency order (referrers before referents) so the
    # SQLite FK enforcement (PRAGMA foreign_keys=ON) and Postgres both accept
    # it. file_access + error reference tool_call, so they go before it.
    turn_subq = "SELECT id FROM copilot_turn WHERE session_id = ?"
    tcall_subq = f"SELECT id FROM copilot_tool_call WHERE turn_id IN ({turn_subq})"
    db.execute(
        f"DELETE FROM heuristic_label WHERE turn_id IN ({turn_subq})", (session_id,)
    )
    db.execute(
        f"DELETE FROM copilot_tool_result WHERE tool_call_id IN ({tcall_subq})",
        (session_id,),
    )
    db.execute("DELETE FROM copilot_file_access WHERE session_id = ?", (session_id,))
    db.execute("DELETE FROM copilot_error WHERE session_id = ?", (session_id,))
    db.execute(
        f"DELETE FROM copilot_tool_call WHERE turn_id IN ({turn_subq})", (session_id,)
    )
    db.execute("DELETE FROM session_kpi WHERE session_id = ?", (session_id,))
    db.execute("DELETE FROM copilot_turn WHERE session_id = ?", (session_id,))


# ── child insertion ────────────────────────────────────────────────────


def _insert_turn_tree(
    db: Database,
    session_id: int,
    turn: RawTurn,
    redaction_mode: str,
    pricing: Optional[PricingConfig] = None,
    unpriced: Optional[UnpricedStats] = None,
) -> None:
    preview = redaction.redact_text(turn.text, redaction_mode)[: C.CONTENT_PREVIEW_CHARS]
    cost = compute_turn_cost(
        pricing,
        turn.model,
        tokens_input=turn.tokens_input,
        tokens_output=turn.tokens_output,
        cache_read_tokens=turn.cache_read_tokens,
        cache_write_tokens=turn.cache_write_tokens,
        unpriced=unpriced,
    )
    turn_id = db.insert_returning_id(
        """
        INSERT INTO copilot_turn
            (session_id, sequence_num, role, content_preview, content_length,
             has_tool_use, uuid, parent_uuid, is_sidechain, slash_command,
             tokens_input, tokens_output, cache_read_tokens, cache_write_tokens,
             model, cost_usd, cost_price_version, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            session_id,
            turn.sequence_num,
            turn.role,
            preview,
            turn.content_length,
            bool(turn.tool_calls),
            turn.uuid,
            turn.parent_uuid,
            turn.is_sidechain,
            turn.slash_command,
            turn.tokens_input,
            turn.tokens_output,
            turn.cache_read_tokens,
            turn.cache_write_tokens,
            turn.model,
            cost.cost_usd,
            cost.price_version,
            turn.timestamp,
        ),
    )

    for tc in turn.tool_calls:
        norm = tool_names.normalize(tc.name_raw)
        input_preview = redaction.redact_tool_input(tc.input_obj, redaction_mode)
        tool_call_id = db.insert_returning_id(
            """
            INSERT INTO copilot_tool_call
                (turn_id, tool_use_id, tool_name, tool_name_raw, input_preview,
                 sequence_num)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (turn_id, tc.tool_use_id, norm, tc.name_raw, input_preview, tc.sequence_num),
        )

        if tc.result_is_error is not None or tc.result_text is not None:
            status = C.STATUS_ERROR if tc.result_is_error else C.STATUS_SUCCESS
            db.execute(
                """
                INSERT INTO copilot_tool_result
                    (tool_call_id, status, is_error, output_length, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    tool_call_id,
                    status,
                    bool(tc.result_is_error),
                    len(tc.result_text or "") if tc.result_text is not None else None,
                    # Tool output is redacted before storage (privacy AC) — raw
                    # output can carry secrets/file contents. True length is
                    # kept above as separate metadata.
                    redaction.redact_result(tc.result_text, redaction_mode, limit=1000)
                    if tc.result_is_error
                    else None,
                ),
            )

        # Derived: file access.
        path = files_norm.path_from_input(tc.input_obj)
        if path:
            db.execute(
                """
                INSERT INTO copilot_file_access
                    (session_id, turn_id, tool_call_id, file_path, access_type,
                     language)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_id,
                    tool_call_id,
                    path[:1000],
                    _ACCESS_BY_TOOL.get(norm),
                    files_norm.language_for(path),
                ),
            )

        # Derived: error. Both the message and the derived error_type pass
        # through redaction so neither leaks raw content under code/
        # metadata-only modes (error_type keeps only a recognized exception
        # class for grouping; everything else collapses to "redacted").
        if tc.result_is_error:
            raw = tc.result_text or ""
            db.execute(
                """
                INSERT INTO copilot_error
                    (session_id, turn_id, tool_call_id, error_type, error_message,
                     tool_name, is_recovered)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_id,
                    tool_call_id,
                    redaction.safe_error_type(raw, redaction_mode),
                    redaction.redact_result(raw, redaction_mode),
                    norm,
                    False,
                ),
            )


# ── helpers ────────────────────────────────────────────────────────────


def link_benchmark_run(db: Database, copilot: str, session_id: str, run_dir: str) -> bool:
    """E9 (#91): stamp ``benchmark_run_dir`` on the matching session row.

    A parameterized, idempotent UPDATE on the natural key ``(copilot,
    session_id)`` — no value is ever string-interpolated into the SQL.
    Re-running with the same ``run_dir`` sets the identical value (idempotent
    by construction). Returns whether a row was affected: ``False`` means no
    session with that ``(copilot, session_id)`` exists yet (counted as
    ``unmatched`` by the caller — see ``correlate.correlate_links``).

    Transaction ownership (E9 outcomes, #92 / FR-4): this does NOT commit —
    the caller owns the transaction and commits once per scan (``_cmd_
    correlate``), not once per record.
    """
    cur = db.execute(
        f"UPDATE copilot_session SET {C.COL_BENCHMARK_RUN_DIR} = ? "
        "WHERE copilot = ? AND session_id = ?",
        (run_dir, copilot, session_id),
    )
    return cur.rowcount > 0


def upsert_benchmark_result(
    db: Database,
    run_dir: str,
    score,  # correlate.Score (duck-typed to avoid a store→correlate import)
    *,
    copilot: Optional[str] = None,
    session_id: Optional[str] = None,
    ingested_at: Optional[str] = None,
) -> None:
    """E9 outcomes (#92): upsert one attempt's outcome row.

    Keyed by ``UNIQUE(run_dir)`` (D-upsert-key — the same resolve()d attempt
    dir the link stamps); re-running a scan updates the row in place, never
    duplicates it. ``session_ref`` is resolved here via the SAME
    ``(copilot, session_id)`` equi-join the link uses — NULL when either part
    is absent (organic / out-of-scope-backend / unmatched attempts). Fully
    parameterized; does NOT commit (caller-owned transaction, FR-4).
    """
    session_ref = None
    if copilot and session_id:
        row = db.query_one(
            "SELECT id FROM copilot_session WHERE copilot = ? AND session_id = ?",
            (copilot, session_id),
        )
        session_ref = row[0] if row else None
    db.execute(
        f"""
        INSERT INTO {C.TBL_BENCHMARK_RESULT}
            (run_dir, benchmark_id, task_id, backend_id, run_id, attempt,
             result, tests_passed, lint_passed, typecheck_passed,
             elapsed_seconds, files_changed, lines_added, lines_removed,
             session_ref, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (run_dir) DO UPDATE SET
            benchmark_id=excluded.benchmark_id,
            task_id=excluded.task_id,
            backend_id=excluded.backend_id,
            run_id=excluded.run_id,
            attempt=excluded.attempt,
            result=excluded.result,
            tests_passed=excluded.tests_passed,
            lint_passed=excluded.lint_passed,
            typecheck_passed=excluded.typecheck_passed,
            elapsed_seconds=excluded.elapsed_seconds,
            files_changed=excluded.files_changed,
            lines_added=excluded.lines_added,
            lines_removed=excluded.lines_removed,
            session_ref=excluded.session_ref,
            ingested_at=excluded.ingested_at
        """,
        (
            run_dir,
            score.benchmark_id,
            score.task_id,
            score.backend_id,
            score.run_id,
            score.attempt,
            score.result,
            score.tests_passed,
            score.lint_passed,
            score.typecheck_passed,
            score.elapsed_seconds,
            score.files_changed,
            score.lines_added,
            score.lines_removed,
            session_ref,
            ingested_at,
        ),
    )


def _duration_seconds(started_at: Optional[str], ended_at: Optional[str]) -> Optional[int]:
    if not started_at or not ended_at:
        return None
    from datetime import datetime

    try:
        a = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        b = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = (b - a).total_seconds()
    return int(delta) if delta >= 0 else None
