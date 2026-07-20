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
import os
import re
from functools import lru_cache
from typing import Any, Optional, Sequence, Union
from urllib.parse import urlsplit

from .. import constants as C
from ..relational.db import (
    SQLITE_MEMORY,
    SQLITE_MODE_RW,
    Database,
    apply_ddl,
    is_sqlite_dsn,
    sqlite_target,
)

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


def _host_of(dsn: str) -> Optional[str]:
    """The hostname of a URL-shaped DSN, or ``None`` when it has none.

    ``None`` means "this DSN carries no host", never "we failed to read
    one" — ``urlsplit`` raises on a malformed netloc (e.g. an unterminated
    IPv6 literal) and that exception is left to propagate, because
    conflating the two made an unparseable netloc look local and admitted.
    """
    return urlsplit(dsn).hostname


def validate_probe_dsn(
    dsn: str, configured_dsns: Sequence[str] = ()
) -> Optional[str]:
    """Constrain what the probe will ATTEMPT (#101).

    Returns a ``constants.PROBE_ERR_*`` code to reject with, or ``None`` to
    proceed. This is the ONE place a DSN is admitted, so the empty case is
    classified here too rather than in a second check. Rejection happens
    BEFORE any connection, so this endpoint cannot be used to reach
    arbitrary hosts, nor — with ``SQLITE_MODE_RW`` at the open — to create
    files.

    ``configured_dsns`` are the operator's OWN DSNs (the saved config and
    whatever the server was started with — they differ after a config save,
    and both must stay testable). Their hosts are allowed alongside
    loopback, so "test the database I actually use" keeps working in either
    order. Pure apart from one existence check.
    """
    if not dsn:
        return C.PROBE_ERR_BAD_DSN

    # ONE parse for the whole policy — urlsplit raises on a malformed
    # netloc, so this single handler is what makes the function fail
    # CLOSED. Scheme is case-normalized: schemes are case-insensitive, so
    # `SQLITE://` must reach the SQLite rules rather than falling through
    # to the host branch.
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return C.PROBE_ERR_HOST_NOT_ALLOWED
    scheme = parts.scheme.lower()
    if scheme not in C.PROBE_ALLOWED_SCHEMES:
        return C.PROBE_ERR_SCHEME_NOT_ALLOWED

    if scheme == C.SCHEME_SQLITE:
        # Scheme says sqlite, so the `sqlite://` form is required — a
        # single-slash `sqlite:/path` is not one we can resolve, and must
        # not fall through to the host branch and be admitted.
        if not is_sqlite_dsn(dsn):
            return C.PROBE_ERR_SCHEME_NOT_ALLOWED
        target = sqlite_target(dsn)
        if target == SQLITE_MEMORY:
            return None  # touches no filesystem path at all
        # Existing FILE only. The open itself enforces this (SQLITE_MODE_RW);
        # checking here just makes the failure specific and actionable.
        if not os.path.isfile(target):
            return C.PROBE_ERR_SQLITE_FILE_MISSING
        return None

    allowed = set(C.PROBE_LOOPBACK_HOSTS)
    for configured in configured_dsns:
        if not configured:
            continue
        try:
            configured_host = _host_of(configured)
        except ValueError:
            continue  # unparseable: contributes nothing, refuses nothing
        if configured_host:
            allowed.add(configured_host)
    # `parts` came from the guarded urlsplit above, so reading the host off
    # it cannot raise here.
    host = parts.hostname
    # A hostless DSN (e.g. a local unix-socket postgres URL) is local by
    # nature — there is no remote target to constrain.
    if host is None or host in allowed:
        return None
    return C.PROBE_ERR_HOST_NOT_ALLOWED


def _error_payload(code: str) -> dict[str, Any]:
    """The ONE place a failure response is shaped, and the ONE place a code
    is turned into text — so every failure path stays identical."""
    return {"ok": False, "error_code": code, "error": C.PROBE_ERROR_MESSAGES[code]}


def _failure(exc: Exception, *, phase: str) -> dict[str, Any]:
    """Log the full exception; return a payload built ONLY from constants."""
    _log.warning("test-connection probe failed (%s phase)", phase, exc_info=exc)
    return _error_payload(classify_probe_error(exc, phase=phase))


def probe(dsn: str, configured_dsns: Sequence[str] = ()) -> dict[str, Any]:
    """Test a DSN. ``configured_dsns`` are the operator's own DSNs, kept
    SEPARATE from the caller-supplied one so policy can tell them apart
    (#101) — a caller-supplied host is only allowed if it is loopback or
    matches one of the configured ones."""
    # Constrain what we will attempt BEFORE attempting anything (the empty
    # DSN is classified in there too, so there is ONE admission decision).
    rejection = validate_probe_dsn(dsn, configured_dsns)
    if rejection is not None:
        return _error_payload(rejection)
    try:
        # SQLITE_MODE_RW: the open REFUSES to create, so the existing-file
        # rule is enforced where the file is actually opened — no TOCTOU
        # window between the check above and here.
        db = Database.connect(dsn, sqlite_mode=SQLITE_MODE_RW)
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
