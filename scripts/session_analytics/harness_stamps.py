# session_analytics.harness_stamps — #371 A4: the harness-stamp ledger.
#
# harness-stamp.sh (a SessionStart hook installed by setup.sh) appends one
# JSON line per session start to ~/.cct/harness-stamps.jsonl: the CCT
# release and commit the instructions were installed from, a digest of
# the rules/skills/agents/commands present in ~/.claude, and a digest of
# the providers profile. This module reads that ledger for ingest.
#
# Two rules the reader is built around:
#
# * The ledger is UNTRUSTED local input (the heartbeat.py contract): a
#   hand-edited or torn file is arbitrary JSON. Every field is bounded and
#   shape-checked on read; a malformed line is skipped with one warning
#   per run; a missing file is a no-op; a ledger problem never fails an
#   ingest.
# * EARLIEST wins, and a difference is a fact. A resumed session may span
#   a harness update, so its stamp is the earliest valid line; a later
#   line that differs in any fact marks the session MIXED rather than
#   moving it to the newer harness (which would attribute its earlier
#   turns to instructions that were not in force). Identical lines from a
#   resume or compaction are not a difference.

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import constants as C

_log = logging.getLogger(__name__)

_HEX_RE = re.compile(r"^[0-9a-f]+$")


@dataclass(frozen=True)
class LedgerStamp:
    """The four ledger facts of one session's earliest valid line, and
    whether a later valid line differed in any of them."""

    cct_version: Optional[str]
    cct_sha: Optional[str]
    instructions_digest: Optional[str]
    providers_digest: Optional[str]
    mixed: bool

    def facts(self) -> tuple[Optional[str], ...]:
        return (self.cct_version, self.cct_sha, self.instructions_digest, self.providers_digest)


def _opt_text(value: Any, max_chars: int) -> tuple[bool, Optional[str]]:
    """(valid, value): None/absent is valid-and-None; text within bounds
    is valid; anything else is invalid."""
    if value is None:
        return True, None
    if not isinstance(value, str) or not value or len(value) > max_chars:
        return False, None
    return True, value


def _opt_hex(value: Any, length: int) -> tuple[bool, Optional[str]]:
    if value is None:
        return True, None
    if not isinstance(value, str) or len(value) != length or not _HEX_RE.match(value):
        return False, None
    return True, value


def _parse_line(obj: Any) -> Optional[tuple[str, str, tuple[Optional[str], ...]]]:
    """(session_id, recorded_at, facts) for a well-formed line, else None."""
    if not isinstance(obj, dict):
        return None
    ok, sid = _opt_text(obj.get(C.HARNESS_KEY_SESSION_ID), C.HARNESS_SESSION_ID_MAX_CHARS)
    if not ok or sid is None:
        return None
    ok, recorded_at = _opt_text(obj.get(C.HARNESS_KEY_RECORDED_AT), C.HARNESS_VERSION_MAX_CHARS)
    if not ok:
        return None
    checks = (
        _opt_text(obj.get(C.HARNESS_KEY_CCT_VERSION), C.HARNESS_VERSION_MAX_CHARS),
        _opt_hex(obj.get(C.HARNESS_KEY_CCT_SHA), C.HARNESS_SHA_HEX_CHARS),
        _opt_hex(obj.get(C.HARNESS_KEY_INSTRUCTIONS_DIGEST), C.HARNESS_DIGEST_HEX_CHARS),
        _opt_hex(obj.get(C.HARNESS_KEY_PROVIDERS_DIGEST), C.HARNESS_DIGEST_HEX_CHARS),
    )
    if not all(ok for ok, _ in checks):
        return None
    return sid, recorded_at or "", tuple(v for _, v in checks)


def _read(path: Path) -> dict[str, LedgerStamp]:
    lines: list[tuple[str, str, int, tuple[Optional[str], ...]]] = []
    skipped = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for index, raw_line in enumerate(fh):
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    parsed = _parse_line(json.loads(raw_line))
                except json.JSONDecodeError:
                    parsed = None
                if parsed is None:
                    skipped += 1
                    continue
                sid, recorded_at, facts = parsed
                lines.append((sid, recorded_at, index, facts))
    except OSError as exc:
        _log.warning("harness ledger %s unreadable (%s); every session unstamped", path, exc)
        return {}
    if skipped:
        _log.warning("harness ledger %s: %d malformed line(s) skipped", path, skipped)
    # Earliest by recorded_at, then file order; ISO-8601 sorts lexically.
    lines.sort(key=lambda item: (item[1], item[2]))
    out: dict[str, LedgerStamp] = {}
    for sid, _, _, facts in lines:
        first = out.get(sid)
        if first is None:
            out[sid] = LedgerStamp(*facts, mixed=False)
        elif not first.mixed and first.facts() != facts:
            out[sid] = LedgerStamp(*first.facts(), mixed=True)
    return out


_cache: dict[str, tuple[tuple[float, int], dict[str, LedgerStamp]]] = {}


def read_ledger(path: str) -> dict[str, LedgerStamp]:
    """The ledger keyed by session id, read once per (path, mtime, size)
    so an ingest run that loads sessions one adapter instance at a time
    parses the file once. A missing path is an empty ledger."""
    if not path:
        return {}
    p = Path(path).expanduser()
    try:
        st = os.stat(p)
    except OSError:
        return {}
    key = (st.st_mtime, st.st_size)
    cached = _cache.get(str(p))
    if cached is not None and cached[0] == key:
        return cached[1]
    stamps = _read(p)
    _cache[str(p)] = (key, stamps)
    return stamps
