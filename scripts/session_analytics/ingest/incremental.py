# session_analytics.ingest.incremental — incremental-ingest gating.
#
# A session is (re)ingested only when one of its source files is new or has a
# newer mtime than what ``ingest_state`` recorded. ``--full`` bypasses the
# gate; idempotent upsert makes a full re-parse safe.

from __future__ import annotations

from .. import constants as C
from ..contracts import SessionRef
from ..relational.db import Database


def should_ingest(db: Database, ref: SessionRef, *, full: bool) -> bool:
    if full:
        return True
    recorded = _recorded_mtime(db, ref)
    if recorded is None:
        return True
    # Re-ingest if any contributing file is newer than the last record.
    return ref.latest_mtime > recorded + C.MTIME_EPSILON


def record_ingested(db: Database, ref: SessionRef) -> None:
    now = _now_iso()
    for path in ref.source_files:
        mtime = path.stat().st_mtime if path.exists() else ref.latest_mtime
        db.execute(
            """
            INSERT INTO ingest_state
                (copilot, source_file, last_mtime, last_byte_offset,
                 last_session_id, ingested_at)
            VALUES (?, ?, ?, 0, ?, ?)
            ON CONFLICT (copilot, source_file) DO UPDATE SET
                last_mtime=excluded.last_mtime,
                last_session_id=excluded.last_session_id,
                ingested_at=excluded.ingested_at
            """,
            (ref.copilot, str(path), mtime, ref.native_session_id, now),
        )


def _recorded_mtime(db: Database, ref: SessionRef):
    placeholders = ",".join("?" for _ in ref.source_files)
    if not placeholders:
        return None
    row = db.query_one(
        f"""
        SELECT MIN(last_mtime) FROM ingest_state
        WHERE copilot = ? AND source_file IN ({placeholders})
        """,
        (ref.copilot, *[str(p) for p in ref.source_files]),
    )
    if row is None or row[0] is None:
        return None
    # Require a record for EVERY source file; a newly-added continuation
    # file (not yet recorded) should force a re-ingest.
    count_row = db.query_one(
        f"""
        SELECT COUNT(*) FROM ingest_state
        WHERE copilot = ? AND source_file IN ({placeholders})
        """,
        (ref.copilot, *[str(p) for p in ref.source_files]),
    )
    if count_row and count_row[0] < len(ref.source_files):
        return None
    return float(row[0])


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
