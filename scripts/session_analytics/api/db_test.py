# session_analytics.api.db_test — connection probe for Settings "Test
# Connection". Pure DB; returns a JSON-ready ok/error result.

from __future__ import annotations

from typing import Any

from ..relational.db import Database, apply_ddl


def probe(dsn: str) -> dict[str, Any]:
    if not dsn:
        return {"ok": False, "error": "no DSN provided"}
    try:
        db = Database.connect(dsn)
    except Exception as exc:  # noqa: BLE001 — report any connect failure
        return {"ok": False, "error": str(exc)}
    try:
        apply_ddl(db)
        row = db.query_one("SELECT COUNT(*) FROM copilot_session")
        return {"ok": True, "dialect": db.dialect, "sessions": int(row[0]) if row else 0}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()
