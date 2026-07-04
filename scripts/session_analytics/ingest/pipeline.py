# session_analytics.ingest.pipeline — orchestrates adapter → store.
#
# discover() (cheap) → incremental gate → load() (full parse) → idempotent
# upsert → record ingest_state. Copilot-agnostic: it iterates whatever
# adapters are registered and selected.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .. import constants as C
from ..registry import get_adapter, list_adapter_ids
from ..relational import store
from ..relational.db import Database, apply_ddl
from . import incremental

_log = logging.getLogger(__name__)


@dataclass
class IngestStats:
    sessions_ingested: int = 0
    sessions_skipped: int = 0
    turns: int = 0
    tool_calls: int = 0
    errors: int = 0
    per_copilot: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "sessions_ingested": self.sessions_ingested,
            "sessions_skipped": self.sessions_skipped,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "errors": self.errors,
            "per_copilot": self.per_copilot,
        }


def ingest(
    *,
    dsn: str,
    copilots: Optional[Sequence[str]] = None,
    root: Optional[Path] = None,
    developer_id: str = C.DEFAULT_DEVELOPER_ID,
    redaction_mode: str = C.REDACT_CODE,
    full: bool = False,
) -> IngestStats:
    """Run ingestion for the selected copilots into ``dsn``.

    ``copilots`` defaults to every registered adapter. ``root`` overrides the
    configured source root for ALL selected copilots (mainly for tests /
    fixtures); pass ``None`` to use each adapter's configured default.
    """
    selected = list(copilots) if copilots else list_adapter_ids()
    stats = IngestStats()

    db = Database.connect(dsn)
    try:
        apply_ddl(db)
        for copilot in selected:
            adapter = get_adapter(copilot)
            c_ingested = c_skipped = 0
            for ref in adapter.discover(root):
                if not incremental.should_ingest(db, ref, full=full):
                    c_skipped += 1
                    stats.sessions_skipped += 1
                    continue
                raw = adapter.load(ref)
                store.upsert_session(
                    db,
                    raw,
                    developer_id=developer_id,
                    redaction_mode=redaction_mode,
                )
                incremental.record_ingested(db, ref)
                db.commit()
                c_ingested += 1
                stats.sessions_ingested += 1
                stats.turns += len(raw.turns)
                stats.tool_calls += sum(len(t.tool_calls) for t in raw.turns)
                stats.errors += sum(
                    1 for t in raw.turns for tc in t.tool_calls if tc.result_is_error
                )
            stats.per_copilot[copilot] = {
                "ingested": c_ingested,
                "skipped": c_skipped,
            }
            _log.info(
                "ingest %s: %d ingested, %d skipped", copilot, c_ingested, c_skipped
            )
    finally:
        db.close()
    return stats
