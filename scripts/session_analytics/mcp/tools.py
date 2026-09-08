# session_analytics.mcp.tools — MCP tool implementations (DB-backed).
#
# Plain functions over the relational store, returning JSON-ready dicts. Kept
# free of the MCP SDK so they are unit-testable directly; server.py wires them
# to the protocol.

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from typing import Any, Optional

from .. import constants as C
from ..config import NoiseConfig
from ..relational.db import Database
from ..session_filter import keep_clause, noise_clause

_SESSION_COLS = (
    "id, copilot, session_id, project_path, model, developer_id, phase, "
    "turn_count, tool_call_count, error_count, started_at, ended_at, "
    "duration_seconds"
)
# E5: session cost = Σ its turns' cost_usd (query-time rollup, not a
# materialized column — see D-outcome in
# specs/session-analytics-cost-tracking/plan.md). NULL when no turn in the
# session has a priced model.
_COST_ROLLUP_SQL = (
    "(SELECT SUM(t.cost_usd) FROM copilot_turn t "
    "WHERE t.session_id = copilot_session.id) AS cost_usd"
)
#: The three tags the Sessions grid shows as icons. The two hand-set
#: ones read session_flag; "analyzed" counts the analysis kinds that
#: produced a parsed result, so the icon can say "2 of 3".
_FLAG_EXPR = (
    "(SELECT COUNT(*) FROM " + C.TBL_SESSION_FLAG + " f "
    "WHERE f.session_ref = copilot_session.id AND f.flag = '{flag}')"
)
_FAVORITE_EXPR = _FLAG_EXPR.format(flag=C.FLAG_FAVORITE)
_TODO_EXPR = _FLAG_EXPR.format(flag=C.FLAG_TODO)
_ANALYZED_EXPR = (
    "(SELECT COUNT(DISTINCT a.kind) FROM " + C.TBL_SESSION_ANALYSIS + " a "
    "WHERE a.session_ref = copilot_session.id AND a.parse_status = 'ok')"
)
_TAG_SELECT_COLS = (
    f"{_FAVORITE_EXPR} AS favorite, {_TODO_EXPR} AS todo, {_ANALYZED_EXPR} AS analyzed_kinds"
)
#: Pricing coverage, with the dashboard's rule: a turn is priceable when
#: it has a model, priced when cost_usd is set. A session's cost is the
#: priced subtotal, so a reader must be told when that is not all of it.
_COST_COVERAGE_COLS = (
    "(SELECT COUNT(t.cost_usd) FROM copilot_turn t WHERE t.session_id = copilot_session.id) AS priced_turns, "
    "(SELECT COUNT(*) FROM copilot_turn t WHERE t.session_id = copilot_session.id "
    "AND t.model IS NOT NULL AND t.model <> '') AS priceable_turns"
)
_SESSION_SELECT_COLS = f"{_SESSION_COLS}, {_COST_ROLLUP_SQL}, {_TAG_SELECT_COLS}, {_COST_COVERAGE_COLS}"

#: Columns the sessions list can be ordered by — the CLOSED map from the
#: API's `sort` value to SQL, so a caller never names a column directly.
#: `cost_usd` is the rollup alias, so it sorts what the page shows.
#: Values are full SQL expressions, not output aliases: Postgres allows
#: an alias in ORDER BY only bare, and the NULLS-last wrapper needs an
#: expression on both dialects.
SESSION_SORT_COLUMNS: dict[str, str] = {
    "started_at": "started_at",
    "copilot": "copilot",
    "project_path": "project_path",
    "model": "model",
    "turn_count": "turn_count",
    "tool_call_count": "tool_call_count",
    "error_count": "error_count",
    "cost_usd": _COST_ROLLUP_SQL.split(" AS ")[0],
    "duration_seconds": "duration_seconds",
    "favorite": _FAVORITE_EXPR,
    "todo": _TODO_EXPR,
    "analyzed": _ANALYZED_EXPR,
}
SESSION_SORT_DEFAULT = "started_at"


class UnknownSortError(ValueError):
    """The requested sort column is not one the list can order by."""


def _session_dict(row, *, has_cost: bool = True) -> dict[str, Any]:
    """``has_cost`` = the row came from _SESSION_SELECT_COLS (cost rollup
    + the three tags); False = the bare _SESSION_COLS."""
    keys = [c.strip() for c in _SESSION_COLS.split(",")]
    if has_cost:
        keys = keys + ["cost_usd", "favorite", "todo", "analyzed_kinds", "priced_turns", "priceable_turns"]
    d = dict(zip(keys, row))
    if d.get("cost_usd") is not None:
        d["cost_usd"] = float(d["cost_usd"])
    if has_cost:
        d["tags"] = {
            "favorite": bool(d.pop("favorite")),
            "todo": bool(d.pop("todo")),
            "analyzed_kinds": int(d.pop("analyzed_kinds") or 0),
            "analysis_kinds_total": len(C.ANALYSIS_KINDS),
        }
        priced, priceable = int(d.pop("priced_turns") or 0), int(d.pop("priceable_turns") or 0)
        d["cost_coverage"] = {
            "priced_turns": priced,
            "priceable_turns": priceable,
            "complete": priceable > 0 and priced >= priceable,
        }
    return d


def _now_iso() -> str:
    from datetime import timezone

    return datetime.now(timezone.utc).isoformat()


def set_session_flag(db: Database, session_id: int, flag: str, on: bool) -> dict[str, Any]:
    """Set or clear one hand-set tag; returns the session's tags after.
    Idempotent both ways. Raises ValueError for a flag that is not one a
    person sets (``analyzed`` is derived) or a session that is not there."""
    if flag not in C.SESSION_FLAGS:
        raise ValueError(f"unknown tag {flag!r}; one of: {', '.join(C.SESSION_FLAGS)}")
    if db.query_one("SELECT 1 FROM copilot_session WHERE id = ?", (session_id,)) is None:
        raise ValueError(f"no session {session_id}")
    if on:
        exists = db.query_one(
            f"SELECT 1 FROM {C.TBL_SESSION_FLAG} WHERE session_ref = ? AND flag = ?",
            (session_id, flag),
        )
        if exists is None:
            db.execute(
                f"INSERT INTO {C.TBL_SESSION_FLAG} (session_ref, flag, created_at) VALUES (?, ?, ?)",
                (session_id, flag, _now_iso()),
            )
    else:
        db.execute(
            f"DELETE FROM {C.TBL_SESSION_FLAG} WHERE session_ref = ? AND flag = ?",
            (session_id, flag),
        )
    db.commit()
    row = db.query_one(
        f"SELECT {_TAG_SELECT_COLS} FROM copilot_session WHERE id = ?", (session_id,)
    )
    return {
        "favorite": bool(row[0]), "todo": bool(row[1]),
        "analyzed_kinds": int(row[2] or 0), "analysis_kinds_total": len(C.ANALYSIS_KINDS),
    }


def search_sessions(
    db: Database,
    query: Optional[str] = None,
    *,
    copilot: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 20,
    noise: Optional[NoiseConfig] = None,
    include_noise: bool = False,
    sort: str = SESSION_SORT_DEFAULT,
    descending: bool = True,
) -> list[dict[str, Any]]:
    """Find sessions by keyword (project path / model) + optional filters.

    With ``noise`` given and ``include_noise`` False, probe/temp-dir/too-
    short sessions are left out (see session_filter). Use
    ``count_noise_sessions`` with the same filters to say how many.
    ``sort`` is one of SESSION_SORT_COLUMNS (the Sessions grid's column
    headers); the limit applies AFTER ordering, so "top 50 by errors"
    is what a sort by errors returns.
    """
    column = SESSION_SORT_COLUMNS.get(sort)
    if column is None:
        raise UnknownSortError(
            f"cannot sort sessions by {sort!r}; one of: {', '.join(SESSION_SORT_COLUMNS)}"
        )
    where, params = _session_filters(query, copilot, date_from, date_to)
    if noise is not None and not include_noise:
        keep_sql, keep_params = keep_clause(noise, "copilot_session")
        where.append(keep_sql)
        params += list(keep_params)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    # NULLs (an unpriced cost, a missing model) sort last either way;
    # started_at breaks ties so the order is stable between polls.
    direction = "DESC" if descending else "ASC"
    rows = db.query(
        f"SELECT {_SESSION_SELECT_COLS} FROM copilot_session{where_sql} "
        f"ORDER BY ({column} IS NULL), {column} {direction}, started_at DESC LIMIT {int(limit)}",
        tuple(params),
    )
    return [_session_dict(r) for r in rows]


def count_noise_sessions(
    db: Database,
    noise: NoiseConfig,
    query: Optional[str] = None,
    *,
    copilot: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> int:
    """How many sessions the same filters would list if noise were shown —
    the number behind the Sessions page's "Show excluded (n)"."""
    where, params = _session_filters(query, copilot, date_from, date_to)
    noise_sql, noise_params = noise_clause(noise, "copilot_session")
    where.append(noise_sql)
    params += list(noise_params)
    row = db.query_one(
        f"SELECT COUNT(*) FROM copilot_session WHERE {' AND '.join(where)}",
        tuple(params),
    )
    return int((row or (0,))[0] or 0)


def _session_filters(
    query: Optional[str], copilot: Optional[str],
    date_from: Optional[str], date_to: Optional[str],
) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if query:
        where.append("(project_path LIKE ? OR model LIKE ?)")
        params += [f"%{query}%", f"%{query}%"]
    if copilot:
        where.append("copilot = ?")
        params.append(copilot)
    if date_from:
        where.append("started_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("started_at <= ?")
        params.append(date_to)
    return where, params


def get_session_details(db: Database, session_id: int) -> dict[str, Any]:
    """Full turn/tool/error breakdown for one session."""
    srow = db.query_one(
        f"SELECT {_SESSION_SELECT_COLS} FROM copilot_session WHERE id = ?", (session_id,)
    )
    if srow is None:
        return {"error": f"session {session_id} not found"}
    session = _session_dict(srow)

    turns = db.query(
        f"""
        SELECT t.sequence_num, t.role, t.content_preview, t.has_tool_use,
               t.slash_command, h.sentiment, h.interaction_quality,
               h.user_corrects_agent, h.rework_detected, t.timestamp,
               td.content
        FROM copilot_turn t
        LEFT JOIN heuristic_label h
          ON h.id = (SELECT h2.id FROM heuristic_label h2
                     WHERE h2.turn_id = t.id
                     ORDER BY h2.rubric_name LIMIT 1)
        LEFT JOIN {C.TBL_TRACE_DOCUMENT} td
          ON td.session_ref = t.session_id
         AND td.sequence_num = t.sequence_num
         AND td.source_kind = ?
        WHERE t.session_id = ? ORDER BY t.sequence_num
        """,
        (C.SOURCE_KIND_COPILOT_TRANSCRIPT, session_id),
    )
    session["turns"] = [
        {
            "sequence_num": r[0], "role": r[1], "content_preview": r[2],
            "has_tool_use": bool(r[3]), "slash_command": r[4],
            "sentiment": r[5], "interaction_quality": r[6],
            "user_corrects_agent": _b(r[7]), "rework_detected": _b(r[8]),
            "timestamp": r[9],
            # Full archived text when the project opted into trace_archive;
            # None (not "") when there is no archive row, so the page can
            # say WHY there is no text rather than print "(no content)".
            "content": r[10],
            "archived": r[10] is not None,
        }
        for r in turns
    ]
    _attach_latency(session)
    session["tool_usage"] = [
        {"tool": r[0], "count": int(r[1])}
        for r in db.query(
            """
            SELECT tc.tool_name, COUNT(*) FROM copilot_tool_call tc
            JOIN copilot_turn t ON t.id = tc.turn_id
            WHERE t.session_id = ? GROUP BY tc.tool_name ORDER BY COUNT(*) DESC
            """,
            (session_id,),
        )
    ]
    session["errors"] = [
        {"error_type": r[0], "tool_name": r[1], "message": r[2]}
        for r in db.query(
            "SELECT error_type, tool_name, error_message FROM copilot_error "
            "WHERE session_id = ? LIMIT 50",
            (session_id,),
        )
    ]
    return session


def analyze_patterns(
    db: Database,
    *,
    workspace: Optional[str] = None,
    tool: Optional[str] = None,
    error_type: Optional[str] = None,
) -> dict[str, Any]:
    """Aggregate pattern analysis across sessions."""
    session_filter = ""
    sparams: list[Any] = []
    if workspace:
        session_filter = " AND s.project_path LIKE ?"
        sparams.append(f"%{workspace}%")

    tool_where = ""
    tparams = list(sparams)
    if tool:
        tool_where = " AND tc.tool_name = ?"
        tparams.append(tool)
    tool_rows = db.query(
        f"""
        SELECT tc.tool_name, COUNT(*) AS n,
               SUM(CASE WHEN tr.is_error THEN 1 ELSE 0 END) AS errs
        FROM copilot_tool_call tc
        JOIN copilot_turn t ON t.id = tc.turn_id
        JOIN copilot_session s ON s.id = t.session_id
        LEFT JOIN copilot_tool_result tr ON tr.tool_call_id = tc.id
        WHERE 1=1{session_filter}{tool_where}
        GROUP BY tc.tool_name ORDER BY errs DESC, n DESC LIMIT 50
        """,
        tuple(tparams),
    )

    err_where = ""
    eparams = list(sparams)
    if error_type:
        err_where = " AND e.error_type LIKE ?"
        eparams.append(f"%{error_type}%")
    error_rows = db.query(
        f"""
        SELECT e.tool_name, e.error_type, COUNT(*) AS n
        FROM copilot_error e
        JOIN copilot_session s ON s.id = e.session_id
        WHERE 1=1{session_filter}{err_where}
        GROUP BY e.tool_name, e.error_type ORDER BY n DESC LIMIT 50
        """,
        tuple(eparams),
    )

    return {
        "tools": [
            {"tool": r[0], "invocations": int(r[1]), "errors": int(r[2] or 0)}
            for r in tool_rows
        ],
        "errors": [
            {"tool": r[0], "error_type": r[1], "count": int(r[2])}
            for r in error_rows
        ],
    }


def compare_approaches(db: Database, task_description: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Find past sessions resembling a task and report their KPIs.

    Keyword match over project_path + first user turn; outcomes come from
    session_kpi when present. For EMBEDDING-based session-to-session
    similarity see ``similar_sessions`` (#287) — this tool's keyword
    output shape is unchanged and carries no ``basis`` field.
    """
    terms = [t for t in (task_description or "").lower().split() if len(t) > 3][:6]
    # compare_approaches ranks by task-term match and never reads cost, so
    # select without the per-row correlated cost rollup (avoids 500 needless
    # subqueries).
    rows = db.query(
        f"""
        SELECT {_SESSION_COLS} FROM copilot_session
        ORDER BY started_at DESC LIMIT 500
        """
    )
    scored = []
    for r in rows:
        s = _session_dict(r, has_cost=False)
        hay = (s.get("project_path") or "").lower()
        score = sum(1 for t in terms if t in hay)
        if score:
            kpi = db.query_one(
                "SELECT correction_rate, rework_rate, avg_interaction_quality "
                "FROM session_kpi WHERE session_id = ? LIMIT 1",
                (s["id"],),
            )
            if kpi:
                s["kpi"] = {
                    "correction_rate": kpi[0],
                    "rework_rate": kpi[1],
                    "avg_interaction_quality": kpi[2],
                }
            s["match_score"] = score
            scored.append(s)
    scored.sort(key=lambda x: x["match_score"], reverse=True)
    return scored[:limit]


def similar_sessions(
    db: Database, kuzu_path: str, session_id: int, *, limit: int = 10,
) -> dict[str, Any]:
    """Stored-edge similarity neighbors for one session (#287 T3, FR-F).

    READ-ONLY over the graph, and NON-CREATING: the path is checked
    before any connect, because ``GraphDatabase.connect`` mkdirs and
    opens create-capable — an MCP read must never create the store it
    reads (that is ``graph``'s job).

    AN EMPTY NEIGHBOR LIST IS A HEALTHY ANSWER: a singleton space or
    all-below-threshold scores legitimately produce no edges, and with
    no pass metadata this tool cannot know whether the pass ran — so
    it never prescribes one. Remedial guidance is reserved for
    prerequisites it INDEPENDENTLY establishes: the session has no
    validated envelope (relational read), the graph store is absent or
    uninitialized, or the session has no graph node. Scores are a
    SNAPSHOT of the last completed `similar` pass.
    """
    from ..embedding.contracts import validate_envelope

    row = db.query_one(
        "SELECT copilot, session_id, session_embedding, project_path "
        "FROM copilot_session WHERE id = ?", (session_id,))
    if row is None:
        return {"error": f"session {session_id} not found"}
    copilot, native_id, stored, src_project = row

    # prerequisite 1, independently established from the relational
    # store: a validated envelope.
    # MISSING and INVALID are different failures with different
    # recoveries (T3 review): an ordinary `embed` pass deliberately
    # skips existing envelopes, so it cannot repair an invalid
    # non-null one — that takes an explicit targeted overwrite.
    if stored is None:
        return {
            "error": f"session {session_id} has no embedding envelope",
            "prerequisite": "embedding",
            "guidance": "run './scripts/session-analytics embed' first",
        }
    try:
        env = json.loads(stored)
    except (json.JSONDecodeError, TypeError):
        env = None
    envelope_err = (
        "unparseable embedding envelope" if env is None
        else validate_envelope(env))
    if envelope_err is not None:
        return {
            "error": f"session {session_id} has an INVALID embedding "
                     f"envelope ({envelope_err})",
            "prerequisite": "embedding",
            "guidance": (
                f"an ordinary embed pass skips existing envelopes; "
                f"replace this one explicitly with "
                f"'./scripts/session-analytics embed --overwrite "
                f"--session-id {session_id}'"),
        }

    # prerequisite 2: the graph store — absent is checked BEFORE any
    # connect (zero filesystem creation from this read path).
    if not kuzu_path or not Path(kuzu_path).exists():
        return {
            "error": f"graph database absent at {kuzu_path or '(unset)'}",
            "prerequisite": "graph",
            "guidance": "run './scripts/session-analytics graph' first",
        }

    from ..embedding.similar_runner import KuzuEdgeStore
    from ..graph.schema import GraphDatabase

    session_key = f"{copilot}:{native_id}"
    # READ-ONLY, NON-CREATING at the database open itself (T3 review):
    # the exists() precheck alone is a TOCTOU — a path that disappears
    # between check and open must be refused, never recreated. Captured
    # on kuzu 0.11.3: read_only=True raises on an absent database
    # without touching the filesystem.
    try:
        gdb = GraphDatabase.connect_read_only(kuzu_path)
    except RuntimeError:
        return {
            "error": f"graph database absent or unopenable at {kuzu_path}",
            "prerequisite": "graph",
            "guidance": "run './scripts/session-analytics graph' first",
        }
    try:
        store = KuzuEdgeStore(gdb)
        if not store.graph_ready():
            return {
                "error": "graph store holds no Session table",
                "prerequisite": "graph",
                "guidance": "run './scripts/session-analytics graph' first",
            }
        if not store.node_exists(session_key):
            return {
                "error": f"session {session_id} has no graph node",
                "prerequisite": "graph",
                "guidance": "run './scripts/session-analytics graph' to "
                            "sync the graph, then 'similar'",
            }
        res = gdb.execute(
            "MATCH (a:Session {session_key: $k})-[r:SIMILAR_TO]->(b:Session) "
            "RETURN b.session_key, r.score", {"k": session_key})
        pairs = []
        while res.has_next():
            dst, score = res.get_next()
            pairs.append((str(dst), float(score)))
    finally:
        gdb.close()

    pairs.sort(key=lambda p: (-p[1], p[0]))
    # What the SOURCE session used — so each neighbour can say why it is
    # similar in words a person can check (shared tools, shared errors),
    # not only a cosine score.
    src_tools = _session_tool_names(db, session_id)
    src_errors = _session_error_types(db, session_id)
    src_files = _session_file_names(db, session_id)
    prevalence = _tool_prevalence(db)
    neighbors = []
    for dst_key, score in pairs[:limit]:
        dst_copilot, _, dst_native = dst_key.partition(":")
        info = db.query_one(
            f"SELECT id, project_path, started_at, model, turn_count, error_count, {_TAG_SELECT_COLS} "
            "FROM copilot_session WHERE copilot = ? AND session_id = ?",
            (dst_copilot, dst_native))
        # EXISTING KPIs ride along with their rubric identity (spec
        # scenario 1); honest absence — kpi is null when no row exists,
        # and nothing is computed here.
        kpi = None
        if info:
            krow = db.query_one(
                "SELECT rubric_name, correction_rate, rework_rate, "
                "avg_interaction_quality FROM session_kpi "
                "WHERE session_id = ? LIMIT 1", (info[0],))
            if krow:
                kpi = {
                    "rubric_name": krow[0],
                    "correction_rate": krow[1],
                    "rework_rate": krow[2],
                    "avg_interaction_quality": krow[3],
                }
        shared = None
        if info:
            shared_tools = src_tools & _session_tool_names(db, info[0])
            shared = {
                # Rarest first: a tool most sessions use says little
                # about why THESE two are alike; one few sessions use
                # says a lot. `common_tools` says how many of the shared
                # ones were the everyday kind, so the reason can say so.
                "tools": sorted(
                    (t for t in shared_tools if prevalence.get(t, 0.0) < COMMON_TOOL_SHARE),
                    key=lambda t: (prevalence.get(t, 0.0), t),
                )[:8],
                "common_tools": sum(1 for t in shared_tools if prevalence.get(t, 0.0) >= COMMON_TOOL_SHARE),
                "error_types": sorted(src_errors & _session_error_types(db, info[0]))[:5],
                "files": sorted(src_files & _session_file_names(db, info[0]))[:5],
                "same_project": bool(src_project and info[1] == src_project),
            }
        neighbors.append({
            "session_key": dst_key,
            "id": info[0] if info else None,
            "project_path": info[1] if info else None,
            "started_at": info[2] if info else None,
            "model": info[3] if info else None,
            "turn_count": int(info[4]) if info else None,
            "error_count": int(info[5]) if info else None,
            "tags": {
                "favorite": bool(info[6]), "todo": bool(info[7]),
                "analyzed_kinds": int(info[8] or 0), "analysis_kinds_total": len(C.ANALYSIS_KINDS),
            } if info else None,
            "score": score,
            "basis": "embedding",
            "kpi": kpi,
            "shared": shared,
        })
    # neighbors == [] is HEALTHY here: every prerequisite held, the
    # stored snapshot simply contains no edges for this session.
    return {
        "session_id": session_id,
        "basis": "embedding",
        "scores_are": "a snapshot of the last completed 'similar' pass",
        "neighbors": neighbors,
    }


def _session_tool_names(db: Database, session_id: int) -> set[str]:
    return {
        r[0] for r in db.query(
            "SELECT DISTINCT c.tool_name FROM copilot_tool_call c "
            "JOIN copilot_turn t ON t.id = c.turn_id WHERE t.session_id = ?", (session_id,))
        if r[0]
    }


#: A tool used by at least this share of sessions is "the usual kind":
#: shared by almost any two sessions, so not a reason they are alike.
COMMON_TOOL_SHARE = 0.5


def _tool_prevalence(db: Database) -> dict[str, float]:
    """tool → share of TOOL-USING sessions that used it. Sessions with
    no tool calls (probe runs, two-turn chats) are left out of the
    denominator, or every tool would look rare."""
    total = db.query_one(
        "SELECT COUNT(DISTINCT t.session_id) FROM copilot_tool_call c "
        "JOIN copilot_turn t ON t.id = c.turn_id"
    )
    n = int((total or (0,))[0] or 0)
    if n == 0:
        return {}
    rows = db.query(
        "SELECT c.tool_name, COUNT(DISTINCT t.session_id) FROM copilot_tool_call c "
        "JOIN copilot_turn t ON t.id = c.turn_id GROUP BY c.tool_name"
    )
    return {r[0]: int(r[1]) / n for r in rows if r[0]}


def _session_error_types(db: Database, session_id: int) -> set[str]:
    """Real error types only: the redaction placeholder is not one."""
    return {
        r[0] for r in db.query(
            "SELECT DISTINCT error_type FROM copilot_error WHERE session_id = ?", (session_id,))
        if r[0] and r[0].lower() not in ("redacted", "unknown")
    }


def _session_file_names(db: Database, session_id: int) -> set[str]:
    """Base names only: two sessions on the same repo touch the same
    files; the full path would also match on the project, which
    `same_project` already says."""
    return {
        r[0].rsplit("/", 1)[-1] for r in db.query(
            "SELECT DISTINCT file_path FROM copilot_file_access WHERE session_id = ?", (session_id,))
        if r[0]
    }


def session_clusters(
    db: Database,
    kuzu_path: str,
    session_id: Optional[int] = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Clusters over the stored SIMILAR_TO snapshot (#289 FR-F).

    With a ``session_id``: that session's cluster, or an honest
    ``"unclustered"`` outcome. Without one: clusters largest first, up
    to ``limit``.

    PREREQUISITE LADDER, consistent with ``similar_sessions`` and
    introducing NO new prerequisite/outcome literal FOR A MISSING
    GRAPH NODE. A relational session that is
    absent from the graph gets that tool's EXISTING
    ``prerequisite: "graph"`` answer with graph-sync guidance and
    "graph node" named in the error — never the word "unclustered",
    which is reserved for a session that IS in the graph and has no
    incident stored edge.

    There is deliberately NO embedding-envelope rung. Clustering reads
    the graph alone (FR-A), so demanding a current envelope would be a
    false prerequisite: a graph member with no edges is honestly
    unclustered, not un-embedded.

    Clusters are reported UNNAMED — no space triple, no per-space
    grouping — and results carry the same provenance notes and
    limitations the CLI reports, from one shared source, so the two
    surfaces cannot drift apart.
    """
    from ..embedding.cluster_reader import (
        BASIS_EMBEDDING,
        INVENTORY_BASIS_TEXT,
        LIMITATIONS_TEXT,
        MEMBERSHIP_BASIS_TEXT,
        KuzuGraphSnapshot,
        run_clusters,
    )
    from ..embedding.similar_runner import GraphNotReadyError
    from ..graph.schema import GraphDatabase

    # A negative page size is INVALID INPUT, refused by name before the
    # graph is touched — never silently reinterpreted as an empty page,
    # which would look like a successful answer. Zero stays valid: it
    # asks for no rows and still reports the honest total.
    # Validated, never COERCED: int(1.5) would silently accept a
    # fractional page size as 1, and bool is an int subclass so True
    # would pass as 1 — both contradict the integer-only contract this
    # very error message promises.
    if isinstance(limit, bool) or not isinstance(limit, int):
        return {"error": f"limit must be an integer, got {limit!r}"}
    if limit < 0:
        return {"error": f"limit must be >= 0, got {limit}"}

    session_key = None
    if session_id is not None:
        row = db.query_one(
            "SELECT copilot, session_id FROM copilot_session WHERE id = ?",
            (session_id,))
        if row is None:
            return {"error": f"session {session_id} not found"}
        session_key = f"{row[0]}:{row[1]}"

    # The graph store — absent is checked BEFORE any connect, so this
    # read path creates nothing.
    if not kuzu_path or not Path(kuzu_path).exists():
        return {
            "error": f"graph database absent at {kuzu_path or '(unset)'}",
            "prerequisite": "graph",
            "guidance": "run './scripts/session-analytics graph' first",
        }
    # The exists() check alone is a TOCTOU: a path that disappears
    # between check and open must be REFUSED, never recreated.
    try:
        gdb = GraphDatabase.connect_read_only(kuzu_path)
    except RuntimeError:
        return {
            "error": f"graph database absent or unopenable at {kuzu_path}",
            "prerequisite": "graph",
            "guidance": "run './scripts/session-analytics graph' first",
        }
    try:
        snapshot = KuzuGraphSnapshot(gdb)
        try:
            report = run_clusters(snapshot)
        except GraphNotReadyError:
            return {
                "error": "graph store holds no Session table",
                "prerequisite": "graph",
                "guidance": "run './scripts/session-analytics graph' first",
            }
    finally:
        gdb.close()

    notes = {
        "basis": BASIS_EMBEDDING,
        "membership_basis": MEMBERSHIP_BASIS_TEXT,
        "inventory_basis": INVENTORY_BASIS_TEXT,
        "limitations": list(LIMITATIONS_TEXT),
    }

    if session_key is None:
        ranked = list(report.clusters)[:limit]
        return {
            "clusters": [c.as_dict() for c in ranked],
            "cluster_count": len(report.clusters),
            "unclustered_sessions": report.unclustered_sessions,
            "graph_sessions": report.graph_sessions,
            **notes,
        }

    # A relational session with no graph node is a GRAPH prerequisite,
    # not an "unclustered" answer (#287 discipline retained). Presence
    # comes from the REPORT, so every classification below describes
    # the one snapshot `run_clusters` already read — re-reading the
    # inventory here could straddle two and answer inconsistently.
    if not report.has_session(session_key):
        return {
            "error": f"session {session_id} has no graph node",
            "prerequisite": "graph",
            "guidance": "run './scripts/session-analytics graph' to "
                        "sync the graph, then 'similar'",
        }
    for cluster in report.clusters:
        if session_key in cluster.members:
            return {
                "session_id": session_id,
                "outcome": "clustered",
                "cluster": cluster.as_dict(),
                **notes,
            }
    # NOT in a cluster. "Unclustered" is decided by FR-B's INCIDENCE
    # rule, not by cluster membership, so the two surfaces agree: a
    # session whose only stored edge is a self-loop HAS an incident
    # edge and is therefore not unclustered, while T1 suppresses its
    # size-one component so it is not clustered either. It is
    # deliberately neither, and `outcome` is null rather than a third
    # literal. #287's producer cannot create that shape; a hand-built
    # or future edge set can.
    unclustered = report.is_unclustered(session_key)
    return {
        "session_id": session_id,
        "outcome": "unclustered" if unclustered else None,
        "cluster": None,
        **notes,
    }


def _b(v):
    if v is None:
        return None
    return bool(v)


def _attach_latency(session: dict[str, Any]) -> None:
    """Per-turn latency from copilot_turn.timestamp — read side only.

    ``latency_seconds`` on a turn is the gap since the previous turn. The
    session-level summary aggregates ASSISTANT turns only: that gap is the
    agent's response time. A user turn's gap is the person's think time —
    shown per turn, but not a property of the harness.
    """
    prev = None
    assistant: list[tuple[int, float]] = []
    for turn in session["turns"]:
        ts = _parse_ts(turn.get("timestamp"))
        latency = turn_latency(prev, ts)
        # The IMMEDIATE predecessor is what the gap is measured from; a
        # turn without a timestamp makes the next gap unmeasurable, not
        # "since the last measurable turn".
        prev = ts
        turn["latency_seconds"] = latency
        if latency is not None and turn.get("role") == C.ROLE_ASSISTANT:
            assistant.append((int(turn["sequence_num"]), latency))

    if not assistant:
        session["latency"] = None
        return
    values = sorted(v for _, v in assistant)
    slowest = sorted(assistant, key=lambda p: -p[1])[:5]
    session["latency"] = {
        "measured_turns": len(values),
        "p50": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
        "max": values[-1],
        "slowest": [{"sequence_num": s, "seconds": v} for s, v in slowest],
    }


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest rank, the repository's rule (see predict._percentile):
    ceil(q * n) — for [1..6] the p90 is 6, not 5."""
    if not sorted_values:
        return 0.0
    rank = math.ceil(q * len(sorted_values))
    return sorted_values[min(len(sorted_values) - 1, max(0, rank - 1))]


def turn_latency(prev_ts: Optional[datetime], ts: Optional[datetime]) -> Optional[float]:
    """Seconds from the previous turn to this one; None unless BOTH are
    stamped and the clock did not go backwards. Shared with the session
    analysis so the page and the judge see the same numbers."""
    if ts is None or prev_ts is None:
        return None
    delta = round((ts - prev_ts).total_seconds(), 1)
    return delta if delta >= 0 else None


def _parse_ts(value: Any):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
