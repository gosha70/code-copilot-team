# session_analytics.api.db_test — connection probe for Settings "Test
# Connection". Pure DB; returns a JSON-ready ok/error result.
#
# SECURITY (#100): this endpoint accepts a CALLER-SUPPLIED DSN, so its
# response must never carry driver exception text — a real Postgres failure
# reads like `connection to server at "db.internal" (10.0.0.5), port 5432
# failed: FATAL: password authentication failed for user "admin"`, which
# would hand a caller hostnames, IPs, ports and usernames (CodeQL
# py/stack-trace-exposure). Every failure is therefore classified into the
# closed set in ``constants.PROBE_ERROR_MESSAGES``, and the response carries
# ONLY those curated strings. The exception is READ for classification and
# LOGGED in full — it is never echoed.

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any, Union

from .. import constants as C
from ..relational.db import Database, apply_ddl

_log = logging.getLogger(__name__)

# Which stage of the probe failed. Type-based rules (ImportError → missing
# driver, ValueError → malformed DSN) are only MEANINGFUL while connecting;
# applying them to a schema-phase failure would tell an operator whose
# connection succeeded that their DSN is malformed.
PHASE_CONNECT = "connect"
PHASE_SCHEMA = "schema"

Signature = Union[str, tuple[str, ...]]


@lru_cache(maxsize=None)
def _word_re(part: str) -> "re.Pattern[str]":
    """Word-boundary matcher for one signature part.

    Bare substring matching is too broad for short tokens: `role` occurs
    inside `role_store` and `payroles`, so a missing DATABASE whose name
    happens to contain those letters would be reported as an auth failure.
    """
    return re.compile(rf"\b{re.escape(part)}\b")


def _matches(signature: Signature, text: str) -> bool:
    """True when ``signature`` matches ``text`` on word boundaries.

    A signature is a phrase, or a TUPLE of phrases that must ALL appear
    (used where the discriminator is which noun accompanies a shared
    phrase — `role … does not exist` vs `database … does not exist`).
    """
    if isinstance(signature, tuple):
        return all(_word_re(part).search(text) for part in signature)
    return bool(_word_re(signature).search(text))


def classify_probe_error(exc: Exception, *, phase: str) -> str:
    """Map a probe failure to one ``constants.PROBE_ERR_*`` code.

    Pure and side-effect free (the caller logs, and looks the message up).
    In ``PHASE_CONNECT`` exception TYPES are checked first — they are
    unambiguous there. In ``PHASE_SCHEMA`` the connection already
    succeeded, so type rules are skipped and only driver signatures apply.
    Signature matching classifies ONLY: the matched text never leaves this
    function.
    """
    if phase == PHASE_CONNECT:
        if isinstance(exc, ImportError):
            return C.PROBE_ERR_DRIVER_MISSING
        if isinstance(exc, ValueError):
            # Database.connect raises ValueError for an empty/unsupported DSN.
            return C.PROBE_ERR_BAD_DSN
    text = str(exc).lower()
    for candidate, signatures in C.PROBE_ERROR_SIGNATURES:
        if any(_matches(sig, text) for sig in signatures):
            return candidate
    return C.PROBE_ERR_UNKNOWN


def _error_payload(code: str) -> dict[str, Any]:
    """The ONE place a failure response is shaped, and the ONE place a code
    is turned into text — so every failure path stays identical."""
    return {"ok": False, "error_code": code, "error": C.PROBE_ERROR_MESSAGES[code]}


def _failure(exc: Exception, *, phase: str) -> dict[str, Any]:
    """Log the full exception; return a payload built ONLY from constants."""
    _log.warning("test-connection probe failed (%s phase)", phase, exc_info=exc)
    return _error_payload(classify_probe_error(exc, phase=phase))


def probe(dsn: str) -> dict[str, Any]:
    if not dsn:
        return _error_payload(C.PROBE_ERR_BAD_DSN)
    try:
        db = Database.connect(dsn)
    except Exception as exc:  # noqa: BLE001 — report any connect failure
        return _failure(exc, phase=PHASE_CONNECT)
    try:
        apply_ddl(db)
        row = db.query_one("SELECT COUNT(*) FROM copilot_session")
        return {"ok": True, "dialect": db.dialect, "sessions": int(row[0]) if row else 0}
    except Exception as exc:  # noqa: BLE001
        return _failure(exc, phase=PHASE_SCHEMA)
    finally:
        db.close()
