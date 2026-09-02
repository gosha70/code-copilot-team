# session_analytics.embedding.composer — deterministic, redacted
# embedding input (#285 T2; FR-1, FR-7).
#
# THE ALLOWLIST IS THE FEATURE. The composed text is built from exactly
# three ``copilot_turn`` columns:
#
#     sequence_num | role | content_preview
#
# — a strict subset of what the judge already reads. Nothing from
# ``copilot_session`` (``project_path`` and ``benchmark_run_dir`` are
# STORED but not behind the E8 text-redaction boundary), no tool I/O,
# no raw transcript files, no other column of any table. The SQL below
# is generated from ``COMPOSER_COLUMNS`` so the allowlist and the query
# cannot drift apart, and a test pins both the constant and the
# behaviour (planted markers must never reach the composed text).
#
# DETERMINISM (FR-7): the composed text is a pure function of the
# stored rows — ordered by ``sequence_num``, role-tagged, truncated at
# the configured character cap with OLDEST-FIRST retention. Two calls
# over unchanged rows produce byte-identical output.
#
# A DUPLICATE ``sequence_num`` within a session is REFUSED. The schema
# does not enforce UNIQUE(session_id, sequence_num), and SQL guarantees
# nothing about the relative order of ties — so a session carrying one
# would make "byte-identical" a property of the query plan, not of the
# rows. Refusal is chosen over a secondary ordering key deliberately:
# ordering ties by row ``id`` would silently manufacture semantics for
# malformed sequencing, and ``id`` is outside the FR-1 allowlist anyway.
# Today's adapters number turns sequentially, so this is a defensive
# determinism boundary, not evidence of bad ingest.
#
# EMPTINESS IS EXPLICIT (feeds FR-3): a session with no usable preview
# text yields ``unembeddable=True``, never an empty string handed to a
# backend — embedding "" would fabricate a vector for no content.

from __future__ import annotations

from dataclasses import dataclass

from ..relational.db import Database

# The FR-1 allowlist, single-sourced into the query.
COMPOSER_COLUMNS = ("sequence_num", "role", "content_preview")

_SELECT = (
    f"SELECT {', '.join(COMPOSER_COLUMNS)} FROM copilot_turn "
    f"WHERE session_id = ? ORDER BY sequence_num"
)


@dataclass(frozen=True)
class ComposedInput:
    """The embedding input for one session.

    ``unembeddable`` is the explicit-absence half of the contract: True
    when no turn contributed text, and then ``text`` is "" and MUST NOT
    be embedded. ``truncated`` reports whether the cap cut anything —
    the runner surfaces it in the pass report (FR-7).
    """

    session_id: int
    text: str
    turns_used: int
    truncated: bool
    unembeddable: bool


def compose_input(db: Database, session_id: int, *, cap_chars: int) -> ComposedInput:
    """Compose the deterministic, redacted embedding input for a session."""
    if cap_chars <= 0:
        raise ValueError(f"cap_chars must be positive, got {cap_chars}")

    rows = db.query(_SELECT, (session_id,))

    parts: list[str] = []
    previous_seq = None
    for sequence_num, role, preview in rows:
        # Fail closed BEFORE composing: ties have no defined order, so
        # the FR-7 byte-identical promise cannot be kept over them.
        # Checked on every row — including preview-less ones — because
        # the malformation is in the sequencing, not the text.
        if sequence_num == previous_seq:
            raise ValueError(
                f"duplicate sequence_num {sequence_num} for session "
                f"{session_id} — tie order is undefined, so a "
                f"deterministic embedding input cannot be composed"
            )
        previous_seq = sequence_num
        if preview is None or preview == "":
            continue  # a turn with no preview contributes nothing
        parts.append(f"{role}: {preview}")

    if not parts:
        return ComposedInput(
            session_id=session_id, text="", turns_used=0,
            truncated=False, unembeddable=True,
        )

    text = "\n".join(parts)
    truncated = len(text) > cap_chars
    if truncated:
        # Oldest-first retention (FR-7): keep the head, cut the tail.
        text = text[:cap_chars]

    return ComposedInput(
        session_id=session_id, text=text, turns_used=len(parts),
        truncated=truncated, unembeddable=False,
    )
