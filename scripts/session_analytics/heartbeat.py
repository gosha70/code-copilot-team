"""Local heartbeat ingestion (Slice B1 of #174, issue #187, spec FR-4/FR-5).

Reads ``.cct/heartbeat.json`` files (written by the Pi runtime at checkpoint
time) and upserts the dedicated ``local_heartbeat`` table — LAST-SEEN
in-flight state keyed by ``(project_path, developer_id)``. Honest
semantics: a row proves "a CCT action happened at ``last_heartbeat_at``",
never that the session is alive now (alerting is Slice D).

The artifact is UNTRUSTED project-local input, and although the Pi writer
sanitizes on write, this reader sanitizes ON READ too (both directions, per
the spec): a hand-edited file is arbitrary JSON. Missing file ⇒ no-op;
malformed/torn file ⇒ warn + skip — heartbeat problems never fail an
ingest run.

Discovery mirrors the pi adapter's project shape EXACTLY (``base`` itself a
project, or a direct parent of projects; project root = the parent of
``.cct/``), so ``local_heartbeat.project_path`` is string-identical to the
``copilot_session.project_path`` the pi adapter stamps (review B-6 — a
shape mismatch would make the join silently empty). Two further sources
close the gaps: distinct pi ``project_path`` values already in the store
(projects outside the current scan root), and the analytics process's own
cwd when it carries ``.cct/``. A brand-new project with zero ingested
history and a remote watch process becomes visible on its first normal
ingest — a documented B1 boundary.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from . import constants as C
from .relational.db import Database

_log = logging.getLogger(__name__)

HEARTBEAT_REL = ".cct/heartbeat.json"

_MAX_TEXT = 128
_MAX_PHASE = 64
_MAX_TIMESTAMP = 40
_MAX_COUNT = 1_000_000_000

# Module-level so the dialect test exercises the REAL statement (the
# pattern established for UPSERT_DEVELOPER_SQL).
UPSERT_LOCAL_HEARTBEAT_SQL = """
    INSERT INTO local_heartbeat
        (project_path, developer_id, session_id, phase, feature_id,
         checkpoint_count, last_heartbeat_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT (project_path, developer_id) DO UPDATE SET
        session_id=excluded.session_id,
        phase=excluded.phase,
        feature_id=excluded.feature_id,
        checkpoint_count=excluded.checkpoint_count,
        last_heartbeat_at=excluded.last_heartbeat_at
"""


def _sanitize_text(value: Any, max_len: int) -> Optional[str]:
    """Single line, control-stripped, bounded — mirror of the TS discipline."""
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[\r\n\t]+", " ", value)
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
    cleaned = cleaned[:max_len].strip()
    return cleaned or None


def _clamp_count(value: Any) -> int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0
    try:
        n = int(value)
    except (OverflowError, ValueError):
        return 0
    return min(max(n, 0), _MAX_COUNT)


def read_heartbeat(project_root: Path) -> Optional[dict[str, Any]]:
    """Sanitized heartbeat fields, or ``None`` (missing/malformed/no timestamp).

    Malformed and torn files (the writer is atomic, but a hand-edit is not)
    are warned about and skipped — never raised.
    """
    file = project_root / HEARTBEAT_REL
    if not file.is_file():
        return None
    try:
        parsed = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("skipping malformed heartbeat %s: %s", file, exc)
        return None
    if not isinstance(parsed, dict):
        _log.warning("skipping malformed heartbeat %s: not an object", file)
        return None
    last_heartbeat_at = _sanitize_text(parsed.get("updatedAt"), _MAX_TIMESTAMP)
    if last_heartbeat_at is None:
        _log.warning("skipping heartbeat %s: no usable updatedAt", file)
        return None
    return {
        "session_id": _sanitize_text(parsed.get("sessionId"), _MAX_TEXT),
        "phase": _sanitize_text(parsed.get("phase"), _MAX_PHASE),
        "feature_id": _sanitize_text(parsed.get("featureId"), _MAX_TEXT),
        "checkpoint_count": _clamp_count(parsed.get("checkpointCount")),
        "last_heartbeat_at": last_heartbeat_at,
    }


def _scan_roots(base: Optional[Path]) -> list[Path]:
    """Project roots under ``base`` — the pi adapter's exact shape: ``base``
    itself a project, or a direct parent of projects."""
    if base is None or not base.exists():
        return []
    roots: list[Path] = []
    if (base / HEARTBEAT_REL).is_file():
        roots.append(base)
    for child in sorted(base.glob("*/" + HEARTBEAT_REL)):
        if child.is_file():
            roots.append(child.parent.parent)
    return roots


def discover_heartbeat_projects(
    db: Database,
    base: Optional[Path],
    cwd: Optional[Path] = None,
) -> list[Path]:
    """Candidate project roots: scan ``base`` (pi-adapter shape) ∪ distinct
    pi ``project_path`` values already in the store ∪ the process cwd when
    it carries ``.cct/``. Deduplicated by exact string (review B-6: no
    canonicalization here — the stamp must match the pi adapter's, which
    also does not canonicalize)."""
    seen: dict[str, Path] = {}
    for root in _scan_roots(base):
        seen.setdefault(str(root), root)
    try:
        rows = db.query(
            "SELECT DISTINCT project_path FROM copilot_session WHERE copilot = ?",
            (C.COPILOT_PI,),
        )
    except Exception:  # noqa: BLE001 — a fresh DB without the table is fine
        rows = []
    for (project_path,) in rows:
        if project_path:
            seen.setdefault(str(project_path), Path(project_path))
    if cwd is not None and (cwd / ".cct").is_dir():
        seen.setdefault(str(cwd), cwd)
    return list(seen.values())


def ingest_heartbeats(
    db: Database,
    developer_id: str,
    *,
    base: Optional[Path],
    cwd: Optional[Path] = None,
) -> int:
    """Upsert ``local_heartbeat`` for every readable heartbeat; returns the
    row count. Commits its own work (like the developer registration, this
    must survive an otherwise-empty run). Never raises for a bad file."""
    count = 0
    for root in discover_heartbeat_projects(db, base, cwd):
        fields = read_heartbeat(root)
        if fields is None:
            continue
        db.execute(
            UPSERT_LOCAL_HEARTBEAT_SQL,
            (
                str(root),
                developer_id,
                fields["session_id"],
                fields["phase"],
                fields["feature_id"],
                fields["checkpoint_count"],
                fields["last_heartbeat_at"],
            ),
        )
        count += 1
    if count:
        db.commit()
    return count
