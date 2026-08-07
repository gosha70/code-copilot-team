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
import os
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from . import constants as C
from .relational.db import Database

_log = logging.getLogger(__name__)

HEARTBEAT_REL = ".cct/heartbeat.json"

_MAX_TEXT = 128
_MAX_PHASE = 64
_MAX_TIMESTAMP = 40
_MAX_COUNT = 1_000_000_000

# ISO-8601 date-time prefix — the sortable shape the monotonic guard relies on.
_ISO_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")

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
    WHERE excluded.last_heartbeat_at > local_heartbeat.last_heartbeat_at
"""
# The WHERE guard makes last_heartbeat_at MONOTONIC per row (review F6): an
# older heartbeat file re-read never rewinds the row. ISO-8601 Z strings
# sort lexicographically, so string comparison is chronological; valid on
# both dialects.


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
    if last_heartbeat_at is None or not _ISO_PREFIX_RE.match(last_heartbeat_at):
        # The ISO shape check is what makes the monotonic lexicographic
        # comparison in the upsert SOUND: an accepted non-ISO string (e.g.
        # "zzzz") would win every future comparison and freeze the row
        # forever (final review N-1). Tamper-tolerant means skip, not jam.
        _log.warning("skipping heartbeat %s: no usable updatedAt", file)
        return None
    # Phase MEMBERSHIP is validated on read (review F8): the writer checks
    # PHASE_ORDER, but a hand-edited file can hold anything — an unknown
    # phase becomes None, never stored text.
    phase = _sanitize_text(parsed.get("phase"), _MAX_PHASE)
    if phase not in C.CCT_PHASES:
        phase = None
    return {
        "session_id": _sanitize_text(parsed.get("sessionId"), _MAX_TEXT),
        "phase": phase,
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
    it carries ``.cct/``. STORED strings are never canonicalized (review
    B-6: the stamp must match the pi adapter's, which does not
    canonicalize) — but DEDUP uses ``os.path.realpath`` so a
    symlink-divergent cwd (``/tmp`` vs ``/private/tmp``) cannot create a
    second permanent row for the same project (review F3). First
    discoverer wins the stored shape; adapter-shaped sources run first."""
    seen: dict[str, Path] = {}

    def _add(root: Path) -> None:
        real = os.path.realpath(str(root))
        seen.setdefault(real, root)

    for root in _scan_roots(base):
        _add(root)
    try:
        rows = db.query(
            "SELECT DISTINCT project_path FROM copilot_session WHERE copilot = ?",
            (C.COPILOT_PI,),
        )
    except Exception:  # noqa: BLE001 — a fresh DB without the table is fine
        rows = []
    for (project_path,) in rows:
        if project_path:
            _add(Path(project_path))
    if cwd is not None and (cwd / ".cct").is_dir():
        _add(cwd)
    return list(seen.values())


def ingest_heartbeats(
    db: Database,
    developer_id: str,
    *,
    base: Optional[Path],
    cwd: Optional[Path] = None,
    projects: Optional[Mapping[str, Any]] = None,
    resolver: Optional[Any] = None,
) -> int:
    """Upsert ``local_heartbeat`` for every readable heartbeat; returns the
    row count. Commits its own work (like the developer registration, this
    must survive an otherwise-empty run). Never raises: a bad file warns
    and skips, and a DB error on one root rolls back and skips (review F2 —
    a heartbeat problem must never poison the session ingest; on Postgres
    an un-rolled-back failure would abort the whole transaction).

    The per-project ``ingest = "off"`` opt-out is the codebase's HARD
    privacy boundary and applies here in full (review F1): a heartbeat row
    carries the project's absolute path + feature id, so an opted-out
    project gets NOTHING written — resolved with the SAME key resolution
    the session path uses."""
    count = 0
    projects = projects or {}
    for root in discover_heartbeat_projects(db, base, cwd):
        if resolver is not None and projects:
            key = resolver.resolve(str(root))
            override = projects.get(key) if key else None
            if override is not None and getattr(override, "ingest", None) == C.INGEST_OFF:
                continue  # hard boundary: write NOTHING for this project
        fields = read_heartbeat(root)
        if fields is None:
            continue
        try:
            cur = db.execute(
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
            # Count rows actually APPLIED (final review N-2): an upsert
            # suppressed by the monotonic WHERE guard is not "ingested".
            applied = getattr(cur, "rowcount", -1)
            count += 1 if applied != 0 else 0
        except Exception as exc:  # noqa: BLE001 — isolate per-root DB errors
            try:
                db.rollback()
            except Exception:  # noqa: BLE001 — rollback is best-effort too
                pass
            _log.warning("skipping heartbeat for %s: %s", root, exc)
    if count:
        db.commit()
    return count
