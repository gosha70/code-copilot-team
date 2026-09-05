"""Tokenized, ranked search over archived traces (E10 Slice B, #65).

Slice A shipped ``LOWER(content) LIKE '%q%'`` and documented it as
*portable substring search, not ranked search*. Measured over a real
62k-turn corpus that promise held and the search did not: a three-word
query whose every word occurs hundreds of times returns ZERO rows,
because LIKE needs one contiguous literal. ``cluster threshold`` = 0 in
either word order; ``archiving`` = 1 against ``archive`` = 187. Latency
was never the problem (30-50 ms) — recall was, exactly as the shaping
doc pre-registered.

Three things drive the shape of this module:

**The index is a second view of trace text, so the archive's privacy
no-go applies to it in full.** Neither dialect gets its own copy: sqlite
uses an FTS5 *external-content* table (postings only; rows are read back
through ``trace_document``) and postgres a GENERATED column derived from
``trace_document.content``. So a policy purge — ``archive._purge_*``
deletes trace rows when a project stops authorising archiving — takes
the index with it, by trigger on sqlite and by definition on postgres.
Purged text that stayed searchable would be a privacy regression, not a
stale-data bug.

**The dialect fork lives here, not in the DDL files.** ``apply_ddl``
splits on ``;``, which a sqlite trigger body breaks, and the FTS5
availability probe and the rebuild path have to be executable anyway.
One Python module is a smaller fork than two DDL trees.

**FTS5 is a compile-time sqlite option.** Present in this environment,
not guaranteed in another. Its absence degrades to the Slice A LIKE
path with a warning rather than failing the store.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from . import constants as C
from .relational.db import DIALECT_POSTGRES, DIALECT_SQLITE, Database

_log = logging.getLogger(__name__)

# Query terms are bare words: FTS5 MATCH and to_tsquery both have operator
# syntax, and free-typed text must never reach either as syntax. Splitting
# on non-word runs and re-quoting each term keeps a query like `%` or
# `a OR b` literal on both sides.
_TERM_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: Suffixes of the three triggers that keep the sqlite external-content
#: index in step with ``trace_document`` (after insert / delete / update).
#: Named here so tests can address them without re-typing the literals.
FTS_TRIGGER_SUFFIXES = ("ai", "ad", "au")


def query_terms(query: str) -> list[str]:
    """The bare word terms of ``query``; operators and punctuation dropped."""
    return _TERM_RE.findall(query)


# ── index construction ─────────────────────────────────────────────────


def _fts5_available(db: Database) -> bool:
    """Whether this sqlite build has FTS5 compiled in."""
    try:
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _cct_fts5_probe USING fts5(x)"
        )
        db.execute("DROP TABLE IF EXISTS _cct_fts5_probe")
        return True
    except Exception:  # noqa: BLE001 — any failure means "not usable here"
        return False


def _ensure_sqlite(db: Database) -> str:
    # Only probe when there is no index yet: the probe creates and drops
    # a real table, and apply_ddl runs on every cli command. If the index
    # is already there, FTS5 is self-evidently available. The IF NOT
    # EXISTS creates below stay unguarded — they are catalog no-ops, and
    # they repair a store whose triggers were lost without its table.
    if detect_index(db) != C.SEARCH_INDEX_FTS5 and not _fts5_available(db):
        _log.warning(
            "search: sqlite build has no FTS5; falling back to substring "
            "search (unranked, no stemming, contiguous match only)"
        )
        return C.SEARCH_INDEX_NONE

    fts = C.TBL_TRACE_DOCUMENT_FTS
    base = C.TBL_TRACE_DOCUMENT
    # content=<table> is the load-bearing clause: postings only, no copy
    # of the text. content_rowid ties a posting to the row that owns it,
    # which is what lets a purge delete reach the index.
    db.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts} USING fts5("
        f"content, content='{base}', content_rowid='id', "
        f"tokenize=\"{C.FTS5_TOKENIZER}\")"
    )
    # External-content tables are NOT maintained automatically; without
    # these three the index answers with rows that no longer exist.
    ai, ad, au = FTS_TRIGGER_SUFFIXES
    db.execute(
        f"CREATE TRIGGER IF NOT EXISTS {fts}_{ai} AFTER INSERT ON {base} BEGIN "
        f"INSERT INTO {fts}(rowid, content) VALUES (new.id, new.content); END"
    )
    db.execute(
        f"CREATE TRIGGER IF NOT EXISTS {fts}_{ad} AFTER DELETE ON {base} BEGIN "
        f"INSERT INTO {fts}({fts}, rowid, content) "
        f"VALUES ('delete', old.id, old.content); END"
    )
    db.execute(
        f"CREATE TRIGGER IF NOT EXISTS {fts}_{au} AFTER UPDATE ON {base} BEGIN "
        f"INSERT INTO {fts}({fts}, rowid, content) "
        f"VALUES ('delete', old.id, old.content); "
        f"INSERT INTO {fts}(rowid, content) VALUES (new.id, new.content); END"
    )
    _backfill_sqlite(db)
    return C.SEARCH_INDEX_FTS5


def _backfill_sqlite(db: Database) -> None:
    """Rebuild the index when it does not cover every archived row.

    ``apply_ddl`` creates what is absent and runs no migration, so a store
    written before this slice arrives here with rows in ``trace_document``
    and an empty index. Left alone it would report success and answer
    nothing — the whole existing corpus silently unsearchable. The
    triggers only cover writes made from now on, so the backfill is the
    upgrade path, not an optimisation.
    """
    fts = C.TBL_TRACE_DOCUMENT_FTS
    # NOT `count(*) FROM {fts}`. An external-content table answers that
    # from the BASE table, so it reports "in sync" even when the index
    # holds nothing — a staleness probe that can never see staleness.
    # `_docsize` holds one row per genuinely indexed document.
    indexed = db.query_one(f"SELECT count(*) FROM {fts}_docsize")
    stored = db.query_one(f"SELECT count(*) FROM {C.TBL_TRACE_DOCUMENT}")
    n_indexed = int(indexed[0]) if indexed else 0
    n_stored = int(stored[0]) if stored else 0
    if n_indexed == n_stored:
        return
    _log.info(
        "search: rebuilding trace index (%s indexed vs %s archived)",
        n_indexed,
        n_stored,
    )
    db.execute(f"INSERT INTO {fts}({fts}) VALUES ('rebuild')")


def _ensure_postgres(db: Database) -> str:
    base = C.TBL_TRACE_DOCUMENT
    col = C.COL_TRACE_CONTENT_TSV
    # Both statements are guarded by a catalog read rather than left to
    # IF NOT EXISTS. apply_ddl runs on EVERY cli command, and unlike the
    # CREATE TABLE IF NOT EXISTS statements around it, ALTER TABLE ADD
    # COLUMN IF NOT EXISTS takes an ACCESS EXCLUSIVE lock even when it
    # does nothing — which would briefly block archive writes once per
    # command, forever, to re-establish a column that is already there.
    if detect_index(db) != C.SEARCH_INDEX_TSVECTOR:
        # GENERATED ALWAYS ... STORED is what makes backfill and purge
        # non-problems: postgres populates the column for every existing
        # row as part of the ALTER, and the value cannot outlive its row.
        db.execute(
            f"ALTER TABLE {base} ADD COLUMN {col} tsvector "
            f"GENERATED ALWAYS AS ("
            f"to_tsvector('{C.PG_TEXT_SEARCH_CONFIG}', coalesce(content, ''))"
            f") STORED"
        )
    has_index = db.query_one(
        "SELECT 1 FROM pg_indexes WHERE tablename = ? AND indexname = ?",
        (base, C.IDX_TRACE_CONTENT_TSV),
    )
    if not has_index:
        db.execute(
            f"CREATE INDEX {C.IDX_TRACE_CONTENT_TSV} ON {base} USING GIN ({col})"
        )
    return C.SEARCH_INDEX_TSVECTOR


def ensure_index(db: Database) -> str:
    """Create/refresh the trace search index; return which kind backs it.

    Idempotent, and safe to call on a store that cannot be written — a
    read-only or otherwise refusing store degrades to the substring path
    instead of failing the caller's search.
    """
    try:
        if db.dialect == DIALECT_SQLITE:
            kind = _ensure_sqlite(db)
        elif db.dialect == DIALECT_POSTGRES:
            kind = _ensure_postgres(db)
        else:  # pragma: no cover — Database admits exactly two dialects
            return C.SEARCH_INDEX_NONE
        db.commit()
        return kind
    except Exception as exc:  # noqa: BLE001 — index creation must not
        # take the caller down: a store that refuses DDL still serves the
        # substring path.
        _log.warning("search: index unavailable (%s); using substring search", exc)
        db.rollback()
        return C.SEARCH_INDEX_NONE


def detect_index(db: Database) -> str:
    """Which index backs this store, WITHOUT creating or altering anything.

    Searching must never run DDL. ``ensure_index`` is the write path and
    both entry points already reach it — every CLI command runs
    ``apply_ddl`` (``cli.py``), and the API applies it once at app
    creation — so a query only has to find out what is already there.

    Calling the write path per search would be wrong in three ways: the
    sqlite FTS5 probe creates and drops a table on every query; postgres
    would issue ``ALTER TABLE ADD COLUMN IF NOT EXISTS`` per read, which
    takes an ACCESS EXCLUSIVE lock even when it no-ops and so blocks
    concurrent archive writes; and a serving role without ALTER
    privilege would fail, have the failure swallowed, and silently answer
    from the substring path while a perfectly good index sat unused.
    """
    try:
        if db.dialect == DIALECT_SQLITE:
            row = db.query_one(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (C.TBL_TRACE_DOCUMENT_FTS,),
            )
            return C.SEARCH_INDEX_FTS5 if row else C.SEARCH_INDEX_NONE
        if db.dialect == DIALECT_POSTGRES:
            row = db.query_one(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = ? AND column_name = ?",
                (C.TBL_TRACE_DOCUMENT, C.COL_TRACE_CONTENT_TSV),
            )
            return C.SEARCH_INDEX_TSVECTOR if row else C.SEARCH_INDEX_NONE
    except Exception as exc:  # noqa: BLE001 — detection must never raise
        _log.warning("search: cannot detect index (%s); using substring", exc)
    return C.SEARCH_INDEX_NONE


# ── ranked search ──────────────────────────────────────────────────────

_SELECT_COLUMNS = (
    "td.session_ref, td.sequence_num, s.copilot, s.session_id, "
    "s.project_path, td.redaction_mode, td.content"
)


def ranked_rows(
    db: Database, kind: str, terms: list[str], limit: int
) -> Optional[list[tuple]]:
    """Ranked matches for ``terms``, or ``None`` if ``kind`` cannot serve."""
    if kind == C.SEARCH_INDEX_FTS5:
        fts = C.TBL_TRACE_DOCUMENT_FTS
        # Every term quoted as a phrase (literal) and ANDed: all terms
        # must appear, in ANY order, with anything in between — which is
        # precisely what the substring path could not do.
        match = " AND ".join(f'"{t}"' for t in terms)
        return db.query(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM {fts} f
            JOIN {C.TBL_TRACE_DOCUMENT} td ON td.id = f.rowid
            JOIN copilot_session s ON s.id = td.session_ref
            WHERE {fts} MATCH ?
            ORDER BY bm25({fts}), td.session_ref, td.sequence_num
            LIMIT ?
            """,
            (match, limit),
        )
    if kind == C.SEARCH_INDEX_TSVECTOR:
        col = C.COL_TRACE_CONTENT_TSV
        cfg = C.PG_TEXT_SEARCH_CONFIG
        # plainto_tsquery ANDs its terms and treats input as plain text,
        # so operator characters cannot reach the parser.
        return db.query(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM {C.TBL_TRACE_DOCUMENT} td
            JOIN copilot_session s ON s.id = td.session_ref
            WHERE td.{col} @@ plainto_tsquery('{cfg}', ?)
            ORDER BY ts_rank(td.{col}, plainto_tsquery('{cfg}', ?)) DESC,
                     td.session_ref, td.sequence_num
            LIMIT ?
            """,
            (" ".join(terms), " ".join(terms), limit),
        )
    return None
