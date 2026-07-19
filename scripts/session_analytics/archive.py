# session_analytics.archive — E10 Slice A (#98): durable, redaction-safe
# trace archive + portable substring search.
#
# The store keeps only 500-char redacted previews while full traces live in
# volatile sources (Claude Code's transcript cleanup; prunable runs trees).
# `archive()` walks the SAME sources ingest reads, re-parses via the SAME
# adapters, and — for projects that EXPLICITLY opted in
# (`projects.<key>.trace_archive: true`; OFF by default) — stores one
# `trace_document` row per turn holding the turn's FULL text, redacted by
# the same `redact_text` path ingest trusts, under the STRICTER of the
# config-resolved mode and the mode the session's ingest recorded (the FR-4
# redaction floor). No unredacted content is ever written; opted-out and
# not-opted-in projects produce ZERO rows.
#
# Search is deliberately humble (v1): case-insensitive SUBSTRING search via
# parameterized LIKE with escaped wildcards — portable across sqlite and
# postgres with one code path, deterministic (session_ref, sequence_num)
# ordering, and documented as NOT ranked. Real FTS is Slice B, gated on
# demonstrated pain.

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from . import constants as C
from .config import ProjectIdRule, ProjectOverride
from .contracts import SessionRef
from .ingest.project_key import ProjectKeyResolver
from .ingest.redaction import redact_text
from .registry import get_adapter, list_adapter_ids
from .relational.db import Database, apply_ddl, now_iso
from .relational import store

_log = logging.getLogger(__name__)


# ── stats (house guardrail: every counter visible via as_dict) ──────────


@dataclass
class ArchiveStats:
    """Exact coverage counters for one archive run.

    ``sessions_scanned`` = every discovered session considered this run;
    each lands in exactly one of archived / deferred / skipped_unchanged /
    opted_out / skipped_not_opted_in / not_ingested / source_failures —
    never silently dropped. ``sessions_deferred`` = sessions whose source
    carries turns the store hasn't ingested yet (their archived turns ARE
    persisted, but no walk state is stamped, so the next run retries the
    tail). ``sessions_purged`` = previously-archived sessions whose CURRENT
    policy no longer authorizes archiving (opted out or opt-in revoked) —
    their rows were deleted this run. ``per_project_not_opted_in`` names the
    project keys behind the skip counter so a typo'd opt-in key is visible,
    not silent. ``per_mode`` breaks archived sessions down by the redaction
    mode actually applied (post-floor).
    """

    sessions_scanned: int = 0
    sessions_archived: int = 0
    sessions_deferred: int = 0
    sessions_purged: int = 0
    sessions_skipped_unchanged: int = 0
    sessions_opted_out: int = 0
    sessions_skipped_not_opted_in: int = 0
    sessions_not_ingested: int = 0
    source_failures: int = 0
    turns_archived: int = 0
    per_project_not_opted_in: dict = field(default_factory=dict)
    per_mode: dict = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── pure helpers (unit-testable without DB/FS) ──────────────────────────


def stricter_mode(a: str, b: str) -> str:
    """FR-4 redaction floor: the stricter of two modes wins — FAIL CLOSED.

    Strictness rank is positional in ``constants.REDACTION_STRICTNESS``
    (none < code < metadata-only). An UNKNOWN mode collapses the result to
    ``metadata-only`` — the strictest mode ``redact_text`` actually
    implements. Returning the unknown string itself would be a hole:
    ``redact_text`` treats any unrecognized mode as ``code`` (fence-stripping
    only), which is LOOSER than a metadata-only floor.
    """
    if a not in C.REDACTION_STRICTNESS or b not in C.REDACTION_STRICTNESS:
        return C.REDACT_METADATA_ONLY
    rank = C.REDACTION_STRICTNESS.index
    return a if rank(a) >= rank(b) else b


def escape_like(query: str) -> str:
    r"""Escape LIKE wildcards so the query matches literally.

    ``\`` first (it is the ESCAPE character), then ``%`` and ``_``. The
    caller wraps the result in ``%...%`` and passes ``ESCAPE '\'``.
    """
    return (
        query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def make_snippet(content: str, query: str, *, window: int = C.SEARCH_SNIPPET_CHARS) -> str:
    """A ±``window``-char excerpt around the first case-insensitive match.

    Falls back to the head of the content if the match is not found (can
    happen when the DB matched but normalization differs — never raises).
    Ellipses mark truncation on either side.
    """
    idx = content.lower().find(query.lower())
    if idx < 0:
        idx = 0
    start = max(0, idx - window)
    end = min(len(content), idx + len(query) + window)
    snippet = content[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{snippet}{suffix}"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


# ── archive-walk bookkeeping (ingest_state-shaped, separate table) ──────


def should_archive(db: Database, ref: SessionRef, *, full: bool) -> bool:
    """mtime gate against ``trace_archive_state`` (D-bookkeeping: separate
    from ingest_state — the two walks gate independently)."""
    if full:
        return True
    placeholders = ",".join("?" for _ in ref.source_files)
    if not placeholders:
        return True
    params = (ref.copilot, *[str(p) for p in ref.source_files])
    row = db.query_one(
        f"SELECT MIN(last_mtime) FROM {C.TBL_TRACE_ARCHIVE_STATE} "
        f"WHERE copilot = ? AND source_file IN ({placeholders})",
        params,
    )
    if row is None or row[0] is None:
        return True
    count_row = db.query_one(
        f"SELECT COUNT(*) FROM {C.TBL_TRACE_ARCHIVE_STATE} "
        f"WHERE copilot = ? AND source_file IN ({placeholders})",
        params,
    )
    if count_row and count_row[0] < len(ref.source_files):
        return True
    return ref.latest_mtime > float(row[0]) + C.MTIME_EPSILON


def record_archived(db: Database, ref: SessionRef) -> None:
    """Record the walk state for ``ref``'s source files (no commit — the
    archive run owns the transaction, D-transactions)."""
    now = now_iso()
    for path in ref.source_files:
        mtime = path.stat().st_mtime if path.exists() else ref.latest_mtime
        db.execute(
            f"""
            INSERT INTO {C.TBL_TRACE_ARCHIVE_STATE}
                (copilot, source_file, last_mtime, last_session_id, archived_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (copilot, source_file) DO UPDATE SET
                last_mtime=excluded.last_mtime,
                last_session_id=excluded.last_session_id,
                archived_at=excluded.archived_at
            """,
            (ref.copilot, str(path), mtime, ref.native_session_id, now),
        )


# ── the archive run ─────────────────────────────────────────────────────


def archive(
    *,
    dsn: str,
    copilots: Optional[Sequence[str]] = None,
    root: Optional[Path] = None,
    redaction_mode: str = C.REDACT_CODE,
    full: bool = False,
    projects: Optional[Mapping[str, ProjectOverride]] = None,
    project_id_rules: Optional[Sequence[ProjectIdRule]] = None,
    stats: Optional[ArchiveStats] = None,
) -> ArchiveStats:
    """Archive full (redacted) TURN TEXT for opted-in projects.

    Scope honesty (v1): only ``RawTurn.text`` is archived. Tool inputs and
    tool results — the highest-risk redaction surface — are deliberately NOT
    archived in Slice A; that is a named follow-up once this contract has
    proven itself.

    Mirrors ``ingest()``'s walk and policy resolution exactly; the archive
    NEVER widens what ingest would allow:

    - a POLICY-RECONCILIATION PURGE runs first: any previously-archived
      session whose CURRENT policy no longer authorizes archiving (project
      opted out, or the ``trace_archive`` opt-in revoked) has its rows
      deleted this run — the "unauthorized projects have ZERO rows"
      invariant holds continuously, not just at write time;
    - opt-out (``ingest: "off"``) is checked before opt-in and writes
      nothing;
    - projects without the explicit ``trace_archive: true`` opt-in are
      counted (per project key, so a typo'd key is visible) and skipped —
      nothing is persisted for them (the source is parsed transiently for
      project identification, the same transient parse ingest itself
      performs before its own opt-out check);
    - sessions not yet in the store are counted ``sessions_not_ingested``
      and skipped (the archive complements ingest, it does not replace it);
    - a session whose source carries turns the store hasn't ingested yet is
      ``sessions_deferred``: its ingested turns ARE archived, but no walk
      state is stamped, so the next run retries until the store catches up
      — lagging tails are never silently dropped;
    - each stored turn's text passes ``redact_text`` under the FR-4 floor
      (stricter of config-resolved and session-recorded modes; unknown
      modes collapse to metadata-only — fail closed).

    Transactions (D-transactions): ONE commit at the end of a run. A
    RUN-level failure rolls everything back (nothing persisted). A
    PER-SOURCE failure is shielded: the run continues and commits, which
    may persist that source's already-upserted turns — they are redacted,
    correctly anchored rows, and because no walk state was stamped the next
    run repairs/completes them. ``stats`` may be passed in pre-created
    (mutated in place and returned) so a failure still reports partials.
    """
    selected = list(copilots) if copilots else list_adapter_ids()
    if stats is None:
        stats = ArchiveStats()
    projects = projects or {}
    resolver = ProjectKeyResolver(tuple(project_id_rules or ()))

    db = Database.connect(dsn)
    try:
        apply_ddl(db)
        _purge_unauthorized(db, projects, resolver, stats)
        for copilot in selected:
            adapter = get_adapter(copilot)
            for ref in adapter.discover(root):
                stats.sessions_scanned += 1
                try:
                    if not should_archive(db, ref, full=full):
                        stats.sessions_skipped_unchanged += 1
                        continue
                    raw = adapter.load(ref)

                    project_key = resolver.resolve(raw.project_path)
                    override = projects.get(project_key) if project_key else None

                    # Hard privacy boundary first (mirrors ingest FR-4):
                    # opted-out projects get NOTHING written, ever.
                    if override is not None and override.ingest == C.INGEST_OFF:
                        stats.sessions_opted_out += 1
                        continue

                    # Explicit opt-in gate (E10 FR-2): no override, or
                    # trace_archive absent/false → counted PER PROJECT KEY
                    # (so a typo'd opt-in key is visible in the summary),
                    # nothing persisted (not even walk bookkeeping — a later
                    # opt-in must archive this session).
                    if override is None or not override.trace_archive:
                        stats.sessions_skipped_not_opted_in += 1
                        key_label = project_key or "(unresolved)"
                        stats.per_project_not_opted_in[key_label] = (
                            stats.per_project_not_opted_in.get(key_label, 0) + 1
                        )
                        continue

                    session_row = db.query_one(
                        "SELECT id, redaction_mode FROM copilot_session "
                        "WHERE copilot = ? AND session_id = ?",
                        (raw.copilot, raw.native_session_id),
                    )
                    if session_row is None:
                        # Archive complements ingest; never duplicates it.
                        stats.sessions_not_ingested += 1
                        continue
                    session_ref, stored_mode = int(session_row[0]), session_row[1]

                    config_mode = (
                        override.redaction_mode
                        if override.redaction_mode is not None
                        else redaction_mode
                    )
                    # FR-4 redaction floor: never looser than ingest recorded.
                    effective = stricter_mode(config_mode, stored_mode or config_mode)

                    stored_seqs = {
                        int(r[0])
                        for r in db.query(
                            "SELECT sequence_num FROM copilot_turn "
                            "WHERE session_id = ?",
                            (session_ref,),
                        )
                    }
                    archived_at = now_iso()
                    source_path = (
                        str(ref.source_files[0]) if ref.source_files else None
                    )
                    deferred_turns = 0
                    for turn in raw.turns:
                        if turn.sequence_num not in stored_seqs:
                            # Turn absent from the store (source advanced past
                            # the last ingest). Its text is NOT stored yet —
                            # never archive unanchored text — and the session
                            # is DEFERRED below: no walk state is stamped, so
                            # the next run retries after ingest catches up.
                            deferred_turns += 1
                            continue
                        redacted = redact_text(turn.text, effective)
                        store.upsert_trace_document(
                            db,
                            session_ref=session_ref,
                            sequence_num=turn.sequence_num,
                            source_kind=C.SOURCE_KIND_COPILOT_TRANSCRIPT,
                            content=redacted,
                            content_hash=_digest(redacted) if redacted else None,
                            source_path=source_path,
                            redaction_mode=effective,
                            archived_at=archived_at,
                        )
                        stats.turns_archived += 1

                    stats.per_mode[effective] = stats.per_mode.get(effective, 0) + 1
                    if deferred_turns:
                        # Incomplete: archived what was anchorable, but leave
                        # the walk state unstamped so the tail is retried —
                        # lagging turns must never be silently dropped.
                        stats.sessions_deferred += 1
                    else:
                        record_archived(db, ref)
                        stats.sessions_archived += 1
                except Exception:  # noqa: BLE001 — per-source resilience
                    stats.source_failures += 1
                    _log.exception(
                        "archive: source failed for %s/%s — skipped",
                        copilot, ref.native_session_id,
                    )
        # D-transactions: ONE commit per successful run. A raise above this
        # line (outside the per-source shield) rolls everything back.
        db.commit()
    finally:
        db.close()
    return stats


def _purge_unauthorized(
    db: Database,
    projects: Mapping[str, ProjectOverride],
    resolver: ProjectKeyResolver,
    stats: ArchiveStats,
) -> None:
    """Policy-reconciliation purge: delete archived rows the CURRENT policy
    no longer authorizes.

    A session's rows survive only if its project resolves to an override
    with ``trace_archive: true`` AND ``ingest`` not off. Everything else —
    opted out later, opt-in revoked, project entry removed, unresolvable
    path — is purged and counted (``sessions_purged``). Runs before the
    walk, independent of mtime gates, so revocation takes effect even for
    sources that never change again. Cheap: it queries only sessions that
    HAVE archived rows.
    """
    rows = db.query(
        f"""
        SELECT DISTINCT td.session_ref, s.project_path
        FROM {C.TBL_TRACE_DOCUMENT} td
        JOIN copilot_session s ON s.id = td.session_ref
        """
    )
    for session_ref, project_path in rows:
        key = resolver.resolve(project_path)
        override = projects.get(key) if key else None
        authorized = (
            override is not None
            and override.ingest != C.INGEST_OFF
            and override.trace_archive
        )
        if not authorized:
            db.execute(
                f"DELETE FROM {C.TBL_TRACE_DOCUMENT} WHERE session_ref = ?",
                (int(session_ref),),
            )
            stats.sessions_purged += 1
            _log.info(
                "archive: purged trace rows for session_ref=%s "
                "(policy no longer authorizes archiving)",
                session_ref,
            )


# ── substring search (v1: portable, deterministic, NOT ranked) ──────────


def search_traces(
    db: Database, query: str, *, limit: int = C.SEARCH_DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    """Case-insensitive substring search over archived trace text.

    Portable across sqlite and postgres via LOWER(...) LIKE LOWER(pattern)
    with escaped wildcards (one code path, no dialect branch). Results are
    ordered deterministically by (session_ref, sequence_num) — this is
    SUBSTRING search, not ranked search; no relevance ordering is implied.
    """
    limit = max(1, min(int(limit), C.SEARCH_MAX_LIMIT))
    pattern = f"%{escape_like(query)}%"
    rows = db.query(
        f"""
        SELECT td.session_ref, td.sequence_num, s.copilot, s.session_id,
               s.project_path, td.redaction_mode, td.content
        FROM {C.TBL_TRACE_DOCUMENT} td
        JOIN copilot_session s ON s.id = td.session_ref
        WHERE LOWER(td.content) LIKE LOWER(?) ESCAPE '\\'
        ORDER BY td.session_ref, td.sequence_num
        LIMIT ?
        """,
        (pattern, limit),
    )
    return [
        {
            "session_ref": int(r[0]),
            "sequence_num": int(r[1]),
            "copilot": r[2],
            "session_id": r[3],
            "project_path": r[4],
            "redaction_mode": r[5],
            "snippet": make_snippet(r[6] or "", query),
        }
        for r in rows
    ]
