# session_analytics.judge.human_labels — the 50-turn hand-label loop (#313).
#
# ``sample`` writes a CSV of random turns for a person to label; ``import``
# reads it back into human_label. The turn text in the sample is the SAME
# 500-char content_preview the judge is shown (runner._select_turns reads
# nothing else), so the person and the model judge identical evidence —
# handing the person the full archived text would compare two different
# tasks. Rows are keyed on (session, sequence), the anchor that survives a
# re-ingest; the CSV carries the store's row ids only for a reader's
# convenience.

from __future__ import annotations

import csv
import random
from typing import Any, Optional, TextIO

from .. import constants as C
from ..relational.db import Database, now_iso
from .rubric import load_rubric

_KEY_COLUMNS = ("session_ref", "sequence_num", "session_id", "copilot", "role")
_TEXT_COLUMNS = ("prev_text", "text")
_TRUE = {"true", "t", "yes", "y", "1", "x"}
_FALSE = {"false", "f", "no", "n", "0"}


def sample_columns() -> list[str]:
    rubric = load_rubric()
    return list(_KEY_COLUMNS) + list(_TEXT_COLUMNS) + list(rubric.bool_labels) + [
        "sentiment", "interaction_quality",
    ]


def write_sample(
    db: Database, fp: TextIO, *, n: int, seed: Optional[int] = None,
    only_labelled_by: Optional[str] = None,
) -> int:
    """``n`` random turns with text, label columns blank, one CSV row each.

    The draw is balanced by role — half user turns, half assistant, as
    far as the store allows — because a store is assistant-heavy (every
    tool call is an assistant turn) and the user-only labels
    (corrects, asks, commands, changes approach) would otherwise have a
    handful of pairs and no evidence. ``only_labelled_by`` (a label
    source) draws from turns that source already labelled — the way to
    get a human sample over exactly the turns a judge run covered.
    Returns the number of rows written.
    """
    from .label_sources import label_source_join

    join, params = "", ()
    if only_labelled_by:
        join, params = label_source_join(only_labelled_by, "t")
    rows = db.query(
        f"""
        SELECT t.session_id, t.sequence_num, s.session_id, s.copilot, t.role,
               t.content_preview,
               (SELECT p.content_preview FROM copilot_turn p
                 WHERE p.session_id = t.session_id AND p.sequence_num = t.sequence_num - 1)
        FROM copilot_turn t
        JOIN copilot_session s ON s.id = t.session_id
        {join}
        WHERE t.content_preview IS NOT NULL AND t.content_preview <> ''
        """,
        params,
    )
    rng = random.Random(seed)
    by_role: dict[str, list] = {}
    for r in rows:
        by_role.setdefault(str(r[4]), []).append(r)
    chosen = _balanced_draw(rng, by_role, n)
    chosen.sort(key=lambda r: (int(r[0]), int(r[1])))
    writer = csv.writer(fp)
    cols = sample_columns()
    writer.writerow(cols)
    blanks = [""] * (len(cols) - len(_KEY_COLUMNS) - len(_TEXT_COLUMNS))
    for session_ref, seq, native_id, copilot, role, text, prev in chosen:
        writer.writerow(
            [session_ref, seq, native_id, copilot, role, prev or "", text or ""] + blanks
        )
    return len(chosen)


def _balanced_draw(rng: random.Random, by_role: dict[str, list], n: int) -> list:
    """Up to ``n`` rows, an equal share per role; a role short of its
    share gives what it has and the rest is filled from the others."""
    roles = sorted(by_role)
    pools = {role: list(by_role[role]) for role in roles}
    for pool in pools.values():
        rng.shuffle(pool)
    chosen: list = []
    remaining = n
    active = [r for r in roles if pools[r]]
    while remaining > 0 and active:
        share = max(1, remaining // len(active))
        for role in list(active):
            take = pools[role][:share]
            pools[role] = pools[role][share:]
            chosen.extend(take)
            remaining -= len(take)
            if not pools[role]:
                active.remove(role)
            if remaining <= 0:
                break
    return chosen[:n]


class HumanLabelImportError(ValueError):
    pass


def _cell_bool(value: str, *, column: str, line: int) -> Optional[bool]:
    v = (value or "").strip().lower()
    if v == "":
        return None
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise HumanLabelImportError(f"line {line}: {column} must be true/false/blank, got {value!r}")


def import_labels(db: Database, fp: TextIO, *, labeler: str) -> dict[str, Any]:
    """Read a filled-in sample back into human_label under ``labeler``.

    Blank cells stay NULL. A row whose turn no longer exists (the store
    was re-ingested and the session dropped) is reported, not written.
    Re-importing the same file overwrites that labeler's rows, and a row
    left entirely blank WITHDRAWS an earlier answer for that turn — a
    person clearing a label must not leave the old one counting.
    """
    if not labeler.strip():
        raise HumanLabelImportError("labeler must not be empty")
    rubric = load_rubric()
    reader = csv.DictReader(fp)
    missing = [c for c in ("session_ref", "sequence_num") if c not in (reader.fieldnames or [])]
    if missing:
        raise HumanLabelImportError(f"CSV is missing columns: {', '.join(missing)}")
    written, skipped, unlabelled, withdrawn = 0, 0, 0, 0
    bool_cols = list(rubric.bool_labels)
    for i, row in enumerate(reader, start=2):
        try:
            session_ref, seq = int(row["session_ref"]), int(row["sequence_num"])
        except (TypeError, ValueError):
            raise HumanLabelImportError(f"line {i}: session_ref and sequence_num must be integers")
        exists = db.query_one(
            "SELECT 1 FROM copilot_turn WHERE session_id = ? AND sequence_num = ?", (session_ref, seq)
        )
        if exists is None:
            skipped += 1
            continue
        bools = [_cell_bool(row.get(c, ""), column=c, line=i) for c in bool_cols]
        sentiment = (row.get("sentiment") or "").strip().upper() or None
        if sentiment and sentiment not in rubric.sentiment_values:
            raise HumanLabelImportError(
                f"line {i}: sentiment must be one of {', '.join(rubric.sentiment_values)} or blank"
            )
        q_raw = (row.get("interaction_quality") or "").strip()
        quality: Optional[int] = None
        if q_raw:
            try:
                quality = int(q_raw)
            except ValueError:
                raise HumanLabelImportError(f"line {i}: interaction_quality must be an integer or blank")
            if not rubric.quality_min <= quality <= rubric.quality_max:
                raise HumanLabelImportError(
                    f"line {i}: interaction_quality must be {rubric.quality_min}–{rubric.quality_max}"
                )
        if all(b is None for b in bools) and sentiment is None and quality is None:
            had = db.query_one(
                f"SELECT 1 FROM {C.TBL_HUMAN_LABEL} WHERE session_ref = ? AND sequence_num = ? AND labeler = ?",
                (session_ref, seq, labeler),
            )
            if had is not None:
                db.execute(
                    f"DELETE FROM {C.TBL_HUMAN_LABEL} WHERE session_ref = ? AND sequence_num = ? AND labeler = ?",
                    (session_ref, seq, labeler),
                )
                withdrawn += 1
            else:
                unlabelled += 1
            continue
        cols = ["session_ref", "sequence_num", "labeler"] + bool_cols + [
            "sentiment", "interaction_quality", "created_at",
        ]
        updates = ", ".join(f"{c}=excluded.{c}" for c in bool_cols + ["sentiment", "interaction_quality", "created_at"])
        db.execute(
            f"INSERT INTO {C.TBL_HUMAN_LABEL} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT (session_ref, sequence_num, labeler) DO UPDATE SET {updates}",
            [session_ref, seq, labeler] + bools + [sentiment, quality, now_iso()],
        )
        written += 1
    db.commit()
    return {
        "labeler": labeler, "written": written, "withdrawn": withdrawn,
        "skipped_missing_turn": skipped, "left_blank": unlabelled,
    }
