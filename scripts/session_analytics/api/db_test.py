# session_analytics.api.db_test — connection probe for Settings "Test
# Connection". Pure DB; returns a JSON-ready ok/error result.

from __future__ import annotations

import logging
from typing import Any

from ..relational.db import Database, apply_ddl

_log = logging.getLogger(__name__)


def _safe_error(exc: Exception) -> str:
    """First line of the error, capped — full detail goes to the server log,
    never into the HTTP response."""
    _log.warning("test-connection probe failed", exc_info=exc)
    first = (str(exc) or type(exc).__name__).splitlines()[0]
    return first[:200]


def probe(dsn: str) -> dict[str, Any]:
    if not dsn:
        return {"ok": False, "error": "no DSN provided"}
    try:
        db = Database.connect(dsn)
    except Exception as exc:  # noqa: BLE001 — report any connect failure
        return {"ok": False, "error": _safe_error(exc)}
    try:
        apply_ddl(db)
        row = db.query_one("SELECT COUNT(*) FROM copilot_session")
        return {"ok": True, "dialect": db.dialect, "sessions": int(row[0]) if row else 0}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _safe_error(exc)}
    finally:
        db.close()
