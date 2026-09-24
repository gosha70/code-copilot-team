# session_analytics.feedback — #371 A3: feedback as a general record.
#
# One row is a named, typed judgement on a session, a turn or a tool
# call, from a person, a judge or a script. The rules a row must obey
# live here ONCE, so the API, a future judge and a script all write the
# same shape:
#
# * the target exists in the session, addressed by sequence numbers
#   (re-ingest reinserts turns and tool calls with fresh ids);
# * the value is typed by the name: an offered name (FEEDBACK_VOCABULARY)
#   takes its one type, a custom name takes any one supported type;
#   `bool` is checked before `int` because a Python bool IS an int;
# * supersession is history, not editing: the superseded row is in the
#   same session, is current, has the same target and name, and is
#   superseded at most once (the table's UNIQUE says so too, for a
#   racing writer); any source may correct any source.
#
# "Current" is computed, never stored: a row no other row's `supersedes`
# names. current_feedback() is ONE query for the whole session, so the
# detail payload folds it onto turns and tool calls without a query per
# turn.

from __future__ import annotations

import importlib
from typing import Any, Optional

from . import constants as C
from .relational.db import Database, now_iso


class FeedbackError(ValueError):
    """Base for the two refusals; the API maps each to its status."""


class UnknownTargetError(FeedbackError):
    """The session, turn or tool call is not in the store (404)."""


class InvalidFeedbackError(FeedbackError):
    """A malformed name, value, source or supersession (400)."""


_VOCABULARY = dict(C.FEEDBACK_VOCABULARY)

_ROW_COLS = (
    "f.id, f.session_ref, f.sequence_num, f.tool_sequence_num, f.name, "
    "f.value_bool, f.value_num, f.value_text, f.rationale, f.source_type, "
    "f.source_id, f.supersedes, f.created_at, later.id"
)
# The self-join that decides "current": `later` is the row that names
# this one, null when none does.
_ROW_FROM = (
    f"FROM {C.TBL_FEEDBACK} f "
    f"LEFT JOIN {C.TBL_FEEDBACK} later ON later.supersedes = f.id"
)


# ── typing ─────────────────────────────────────────────────────────────


def vocabulary() -> list[dict[str, Any]]:
    """The offered names with their types, for the API and the control.
    ``rating`` carries its bounds so the control can say them."""
    out: list[dict[str, Any]] = []
    for name, kind in C.FEEDBACK_VOCABULARY:
        entry: dict[str, Any] = {"name": name, "type": kind}
        if name == C.FEEDBACK_NAME_RATING:
            entry["min"], entry["max"] = C.FEEDBACK_RATING_MIN, C.FEEDBACK_RATING_MAX
        out.append(entry)
    return out


def coerce_value(name: str, value: Any) -> tuple[Optional[bool], Optional[float], Optional[str]]:
    """Return the ``(value_bool, value_num, value_text)`` triple for
    ``value`` under ``name``'s rules, or raise InvalidFeedbackError.
    Exactly one element is set."""
    required = _VOCABULARY.get(name)
    # bool first: isinstance(True, int) is True in Python.
    if isinstance(value, bool):
        kind = C.FEEDBACK_TYPE_BOOL
    elif isinstance(value, (int, float)):
        kind = C.FEEDBACK_TYPE_NUM
    elif isinstance(value, str):
        kind = C.FEEDBACK_TYPE_TEXT
    else:
        raise InvalidFeedbackError(
            f"feedback value must be a boolean, a number or text, not {type(value).__name__}"
        )
    if required is not None and kind != required:
        raise InvalidFeedbackError(f"feedback {name!r} takes a {required} value, not {kind}")
    if kind == C.FEEDBACK_TYPE_BOOL:
        return value, None, None
    if kind == C.FEEDBACK_TYPE_NUM:
        num = float(value)
        if num != num or num in (float("inf"), float("-inf")):
            raise InvalidFeedbackError("feedback number must be finite")
        if name == C.FEEDBACK_NAME_RATING and (
            num != int(num) or not C.FEEDBACK_RATING_MIN <= num <= C.FEEDBACK_RATING_MAX
        ):
            raise InvalidFeedbackError(
                f"feedback {name!r} is an integer from {C.FEEDBACK_RATING_MIN} to "
                f"{C.FEEDBACK_RATING_MAX}"
            )
        return None, num, None
    text = value.strip()
    if not text:
        raise InvalidFeedbackError("feedback text must not be blank")
    if len(text) > C.FEEDBACK_TEXT_MAX_CHARS:
        raise InvalidFeedbackError(f"feedback text is over {C.FEEDBACK_TEXT_MAX_CHARS} characters")
    return None, None, text


def _check_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise InvalidFeedbackError("feedback name must be non-blank text")
    name = name.strip()
    if len(name) > C.FEEDBACK_NAME_MAX_CHARS:
        raise InvalidFeedbackError(f"feedback name is over {C.FEEDBACK_NAME_MAX_CHARS} characters")
    return name


def _check_rationale(rationale: Any) -> Optional[str]:
    if rationale is None:
        return None
    if not isinstance(rationale, str):
        raise InvalidFeedbackError("feedback rationale must be text")
    text = rationale.strip()
    if len(text) > C.FEEDBACK_RATIONALE_MAX_CHARS:
        raise InvalidFeedbackError(
            f"feedback rationale is over {C.FEEDBACK_RATIONALE_MAX_CHARS} characters"
        )
    return text or None


def _check_source(source_type: Any, source_id: Any) -> tuple[str, str]:
    if source_type not in C.FEEDBACK_SOURCE_TYPES:
        raise InvalidFeedbackError(
            f"unknown feedback source {source_type!r}; one of: {', '.join(C.FEEDBACK_SOURCE_TYPES)}"
        )
    if not isinstance(source_id, str) or not source_id.strip():
        raise InvalidFeedbackError("feedback source_id must be non-blank text")
    source_id = source_id.strip()
    if len(source_id) > C.FEEDBACK_SOURCE_ID_MAX_CHARS:
        raise InvalidFeedbackError(
            f"feedback source_id is over {C.FEEDBACK_SOURCE_ID_MAX_CHARS} characters"
        )
    return source_type, source_id


# ── targets ────────────────────────────────────────────────────────────


def _check_target(
    db: Database, session_id: int, sequence_num: Optional[int], tool_sequence_num: Optional[int]
) -> None:
    if db.query_one("SELECT 1 FROM copilot_session WHERE id = ?", (session_id,)) is None:
        raise UnknownTargetError(f"no session {session_id}")
    if sequence_num is None:
        if tool_sequence_num is not None:
            raise InvalidFeedbackError("a tool call target needs its turn's sequence_num")
        return
    turn = db.query_one(
        "SELECT id FROM copilot_turn WHERE session_id = ? AND sequence_num = ?",
        (session_id, sequence_num),
    )
    if turn is None:
        raise UnknownTargetError(f"no turn {sequence_num} in session {session_id}")
    if tool_sequence_num is None:
        return
    call = db.query_one(
        "SELECT 1 FROM copilot_tool_call WHERE turn_id = ? AND sequence_num = ?",
        (turn[0], tool_sequence_num),
    )
    if call is None:
        raise UnknownTargetError(
            f"no tool call {tool_sequence_num} in turn {sequence_num} of session {session_id}"
        )


def _check_supersedes(
    db: Database,
    session_id: int,
    supersedes: Any,
    sequence_num: Optional[int],
    tool_sequence_num: Optional[int],
    name: str,
) -> Optional[int]:
    if supersedes is None:
        return None
    if isinstance(supersedes, bool) or not isinstance(supersedes, int):
        raise InvalidFeedbackError("supersedes must be a feedback id")
    old = db.query_one(
        f"SELECT f.session_ref, f.sequence_num, f.tool_sequence_num, f.name, later.id "
        f"{_ROW_FROM} WHERE f.id = ?",
        (supersedes,),
    )
    if old is None or int(old[0]) != session_id:
        raise InvalidFeedbackError(f"no feedback {supersedes} in session {session_id}")
    if old[4] is not None:
        raise InvalidFeedbackError(f"feedback {supersedes} is already superseded by {old[4]}")
    if (old[1], old[2]) != (sequence_num, tool_sequence_num):
        raise InvalidFeedbackError(f"feedback {supersedes} is on a different target")
    if old[3] != name:
        raise InvalidFeedbackError(f"feedback {supersedes} is named {old[3]!r}, not {name!r}")
    return supersedes


# ── write ──────────────────────────────────────────────────────────────


def add_feedback(
    db: Database,
    session_id: int,
    name: str,
    value: Any,
    source_type: str,
    source_id: str,
    *,
    rationale: Optional[str] = None,
    sequence_num: Optional[int] = None,
    tool_sequence_num: Optional[int] = None,
    supersedes: Optional[int] = None,
) -> dict[str, Any]:
    """Write one feedback row and return it as the API serves it.

    Raises UnknownTargetError for a session, turn or tool call that is
    not there and InvalidFeedbackError for everything the rules refuse.
    The caller supplies the source; the API's human route supplies the
    server's own developer id, never the client's.
    """
    name = _check_name(name)
    v_bool, v_num, v_text = coerce_value(name, value)
    rationale = _check_rationale(rationale)
    source_type, source_id = _check_source(source_type, source_id)
    _check_target(db, session_id, sequence_num, tool_sequence_num)
    supersedes = _check_supersedes(
        db, session_id, supersedes, sequence_num, tool_sequence_num, name
    )
    created_at = now_iso()
    try:
        new_id = db.insert_returning_id(
            f"""
            INSERT INTO {C.TBL_FEEDBACK}
                (session_ref, sequence_num, tool_sequence_num, name,
                 value_bool, value_num, value_text, rationale,
                 source_type, source_id, supersedes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                session_id, sequence_num, tool_sequence_num, name,
                v_bool, v_num, v_text, rationale,
                source_type, source_id, supersedes, created_at,
            ),
        )
    except _integrity_error(db) as exc:
        # The table's own constraints are the last word: a writer that
        # superseded the same row between the check above and this insert
        # trips UNIQUE (supersedes); the CHECK catches a value shape the
        # store never produces. Either is a refusal, not a server fault.
        db.rollback()
        raise InvalidFeedbackError(
            f"feedback refused by the store: {exc}"
            if supersedes is None
            else f"feedback {supersedes} was superseded by another writer"
        ) from None
    db.commit()
    return _row(
        (
            new_id, session_id, sequence_num, tool_sequence_num, name,
            v_bool, v_num, v_text, rationale, source_type, source_id,
            supersedes, created_at, None,
        )
    )


def _integrity_error(db: Database) -> type[Exception]:
    """The DB-API IntegrityError of whichever driver opened ``db``
    (sqlite3 or psycopg), so the store need not import either."""
    return importlib.import_module(type(db.conn).__module__.split(".")[0]).IntegrityError


# ── read ───────────────────────────────────────────────────────────────


def _row(r: tuple) -> dict[str, Any]:
    if r[5] is not None:
        value: Any = bool(r[5])
    elif r[6] is not None:
        value = float(r[6])
        # A whole number reads back as an int (a rating is 4, not 4.0),
        # within the range where the two agree exactly.
        if value.is_integer() and abs(value) < 2**53:
            value = int(value)
    else:
        value = r[7]
    return {
        "id": int(r[0]),
        "session_id": int(r[1]),
        "sequence_num": None if r[2] is None else int(r[2]),
        "tool_sequence_num": None if r[3] is None else int(r[3]),
        "name": r[4],
        "value": value,
        "rationale": r[8],
        "source_type": r[9],
        "source_id": r[10],
        "supersedes": None if r[11] is None else int(r[11]),
        "superseded_by": None if r[13] is None else int(r[13]),
        "created_at": r[12],
    }


def list_feedback(db: Database, session_id: int) -> list[dict[str, Any]]:
    """Every row on the session, current and superseded, newest first."""
    rows = db.query(
        f"SELECT {_ROW_COLS} {_ROW_FROM} WHERE f.session_ref = ? "
        "ORDER BY f.created_at DESC, f.id DESC",
        (session_id,),
    )
    return [_row(r) for r in rows]


def current_feedback(db: Database, session_id: int) -> list[dict[str, Any]]:
    """The session's current rows (no later row names them), oldest
    first so a target's list reads in the order it was given. One query
    for the whole session; the detail payload folds it by target."""
    rows = db.query(
        f"SELECT {_ROW_COLS} {_ROW_FROM} WHERE f.session_ref = ? AND later.id IS NULL "
        "ORDER BY f.created_at ASC, f.id ASC",
        (session_id,),
    )
    return [_row(r) for r in rows]


def fold_by_target(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]], dict[tuple[int, int], list[dict[str, Any]]]]:
    """Split current rows into (session-level, by turn sequence, by
    (turn sequence, tool sequence)) for the detail payload."""
    on_session: list[dict[str, Any]] = []
    on_turn: dict[int, list[dict[str, Any]]] = {}
    on_call: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        seq, tseq = row["sequence_num"], row["tool_sequence_num"]
        if seq is None:
            on_session.append(row)
        elif tseq is None:
            on_turn.setdefault(seq, []).append(row)
        else:
            on_call.setdefault((seq, tseq), []).append(row)
    return on_session, on_turn, on_call
