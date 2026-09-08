# session_analytics.ask.tools — the read-only lookups the Ask loop can call.
#
# Every tool is a thin binding from a name the model uses to a read
# function that already exists (mcp.tools, archive, graph.query, the
# session analyses, the dashboard KPIs). Nothing here writes: the graph
# is opened read-only, catalogue Cypher goes through assert_readonly, and
# the relational reads are the same SELECTs the pages run. What the
# model sees is what the analyses see — turn previews (redacted at
# ingest) and archived full text where a project opted in.
#
# A tool returns a JSON-able dict. Errors that mean "not there" or "not
# built yet" are returned as {"error": ..., "prerequisite": ...}, never
# raised: the model reads them and moves on, and the page shows them as
# a step that found nothing, not as a crash.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .. import archive as arch
from .. import constants as C
from ..config import NoiseConfig
from ..mcp import tools as mcp_tools
from ..relational.db import Database
from ..session_filter import keep_clause

#: Turn-window defaults for session_turns; the cap bounds one result.
TURNS_DEFAULT = 30
TURNS_MAX = 80
#: List caps that keep one tool result within the model's window.
SESSIONS_MAX = 50
SEARCH_MAX = 50
SIMILAR_MAX = 20
ERRORS_SHOWN = 20
SNIPPET_CHARS = 240
#: The three tags find_sessions can filter on (the Sessions grid's icons).
TAGS = (C.FLAG_FAVORITE, C.FLAG_TODO, "analyzed")


@dataclass(frozen=True)
class AskContext:
    db: Database
    kuzu_path: str
    noise: Optional[NoiseConfig]


ToolFn = Callable[[AskContext, Mapping[str, Any]], dict[str, Any]]


class UnknownToolError(LookupError):
    pass


class BadArgumentsError(ValueError):
    pass


# ── helpers ─────────────────────────────────────────────────────────────


def _int(args: Mapping[str, Any], name: str, default: Optional[int], *, lo: int, hi: int) -> int:
    raw = args.get(name, default)
    if raw is None or raw == "":
        if default is None:
            raise BadArgumentsError(f"{name} is required")
        raw = default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BadArgumentsError(f"{name} must be an integer, got {raw!r}") from None
    return max(lo, min(hi, value))


def _str(args: Mapping[str, Any], name: str) -> str:
    raw = args.get(name)
    return "" if raw is None else str(raw).strip()


def _session_row(s: dict[str, Any]) -> dict[str, Any]:
    """The columns a model needs to name and compare sessions."""
    return {
        "id": s["id"],
        "session_key": f"{s['copilot']}:{s['session_id']}",
        "copilot": s["copilot"],
        "project_path": s["project_path"],
        "model": s["model"],
        "started_at": s["started_at"],
        "duration_seconds": s["duration_seconds"],
        "turns": s["turn_count"],
        "tool_calls": s["tool_call_count"],
        "errors": s["error_count"],
        "cost_usd": s.get("cost_usd"),
        "tags": {
            "favorite": s["tags"]["favorite"],
            "todo": s["tags"]["todo"],
            "analyzed": s["tags"]["analyzed_kinds"] > 0,
        },
    }


# ── tools ───────────────────────────────────────────────────────────────


def find_sessions(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    sort = _str(args, "sort") or mcp_tools.SESSION_SORT_DEFAULT
    tag = _str(args, "tag")
    if tag and tag not in TAGS:
        raise BadArgumentsError(f"tag must be one of {', '.join(TAGS)}")
    limit = _int(args, "limit", 20, lo=1, hi=SESSIONS_MAX)
    try:
        rows = mcp_tools.search_sessions(
            ctx.db,
            _str(args, "query") or None,
            copilot=_str(args, "copilot") or None,
            date_from=_str(args, "date_from") or None,
            date_to=_str(args, "date_to") or None,
            # A tag filter is applied on the rows, so fetch the grid's
            # full page and cut afterwards.
            limit=SESSIONS_MAX if tag else limit,
            noise=ctx.noise,
            sort=sort,
        )
    except mcp_tools.UnknownSortError as exc:
        raise BadArgumentsError(str(exc)) from None
    sessions = [_session_row(s) for s in rows]
    if tag:
        sessions = [s for s in sessions if s["tags"][tag]][:limit]
    return {"sessions": sessions, "count": len(sessions), "sort": sort}


def session_summary(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    from ..judge.session_analysis import all_analyses

    sid = _int(args, "session_id", None, lo=1, hi=2**31)
    details = mcp_tools.get_session_details(ctx.db, sid)
    if "error" in details:
        return {"error": details["error"]}
    analyses = all_analyses(ctx.db, sid)
    summary = _session_row(details)
    summary["ended_at"] = details["ended_at"]
    summary["tools"] = details["tool_usage"]
    # `errors` stays the session's COUNT (as in find_sessions); the
    # messages are a sample, named as one.
    summary["error_samples"] = details["errors"][:ERRORS_SHOWN]
    summary["response_time"] = details.get("latency")
    summary["archived_turns"] = sum(1 for t in details["turns"] if t["archived"])
    summary["analyses"] = {
        kind: (row["parse_status"] if row else "not run") for kind, row in analyses.items()
    }
    return summary


def session_turns(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    from ..judge.session_analysis import build_transcript, load_spec, render_transcript

    sid = _int(args, "session_id", None, lo=1, hi=2**31)
    start = _int(args, "from_turn", 1, lo=1, hi=2**31)
    count = _int(args, "count", TURNS_DEFAULT, lo=1, hi=TURNS_MAX)
    if ctx.db.query_one("SELECT id FROM copilot_session WHERE id = ?", (sid,)) is None:
        return {"error": f"session {sid} not found"}
    spec = load_spec()
    transcript = build_transcript(
        ctx.db, sid, max_chars=spec.max_transcript_chars, per_turn_cap=spec.per_turn_cap_chars
    )
    window = [t for t in transcript.all_turns if start <= t.sequence_num < start + count]
    total = len(transcript.all_turns)
    return {
        "session_id": sid,
        "turns_total": total,
        "from_turn": start,
        "to_turn": window[-1].sequence_num if window else start,
        "text_source": transcript.source,
        "text": render_transcript(window),
        "more": bool(window) and window[-1].sequence_num < (transcript.all_turns[-1].sequence_num if total else 0),
    }


def session_analyses(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    from ..judge.contracts import PARSE_OK
    from ..judge.session_analysis import all_analyses

    sid = _int(args, "session_id", None, lo=1, hi=2**31)
    if ctx.db.query_one("SELECT id FROM copilot_session WHERE id = ?", (sid,)) is None:
        return {"error": f"session {sid} not found"}
    out: dict[str, Any] = {"session_id": sid}
    for kind, row in all_analyses(ctx.db, sid).items():
        if row is None:
            out[kind] = {"status": "not run"}
        elif row["parse_status"] != PARSE_OK:
            out[kind] = {"status": row["parse_status"], "error": row["error"]}
        else:
            out[kind] = {"status": "ok", "judge": row["judge_model"], "result": row["result"]}
    return out


def search_text(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    query = _str(args, "query")
    if not query:
        raise BadArgumentsError("query is required")
    limit = _int(args, "limit", 20, lo=1, hi=SEARCH_MAX)
    hits: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for h in arch.search_traces(ctx.db, query, limit=limit):
        key = (h["session_ref"], h["sequence_num"])
        seen.add(key)
        hits.append({
            "session_id": h["session_ref"], "turn": h["sequence_num"],
            "project_path": h["project_path"], "source": "archive",
            "snippet": h["snippet"][:SNIPPET_CHARS],
        })
    if len(hits) < limit:
        # Previews exist for EVERY session; archived text only where a
        # project opted in. Search previews too, so a store with nothing
        # archived still answers "where did I say X".
        like = f"%{arch.escape_like(query)}%"
        rows = ctx.db.query(
            """
            SELECT t.session_id, t.sequence_num, s.project_path, t.content_preview
            FROM copilot_turn t JOIN copilot_session s ON s.id = t.session_id
            WHERE LOWER(t.content_preview) LIKE LOWER(?) ESCAPE '\\'
            ORDER BY t.session_id DESC, t.sequence_num LIMIT ?
            """,
            (like, limit * 2),
        )
        for sid, seq, project, preview in rows:
            key = (int(sid), int(seq))
            if key in seen:
                continue
            seen.add(key)
            hits.append({
                "session_id": int(sid), "turn": int(seq), "project_path": project,
                "source": "preview", "snippet": arch.make_snippet(preview or "", query)[:SNIPPET_CHARS],
            })
            if len(hits) >= limit:
                break
    return {"query": query, "hits": hits, "count": len(hits)}


def patterns(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    return mcp_tools.analyze_patterns(
        ctx.db,
        workspace=_str(args, "workspace") or None,
        tool=_str(args, "tool") or None,
        error_type=_str(args, "error_type") or None,
    )


def similar_sessions(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    sid = _int(args, "session_id", None, lo=1, hi=2**31)
    limit = _int(args, "limit", 8, lo=1, hi=SIMILAR_MAX)
    try:
        out = mcp_tools.similar_sessions(ctx.db, ctx.kuzu_path, sid, limit=limit)
    except ImportError:
        return {"error": "the kuzu package is not installed", "prerequisite": "kuzu"}
    if "neighbors" in out:
        out["neighbors"] = [
            {k: v for k, v in n.items() if k != "kpi"} for n in out["neighbors"]
        ]
    return out


def graph_question(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    from ..graph import query as gq

    query_id = _str(args, "id")
    if not query_id:
        raise BadArgumentsError("id is required")
    params = args.get("params") or {}
    if not isinstance(params, Mapping):
        raise BadArgumentsError("params must be an object")
    if not ctx.kuzu_path or not Path(ctx.kuzu_path).exists():
        return {"error": "the knowledge graph has not been built", "prerequisite": "graph"}
    try:
        from ..graph.schema import GraphDatabase
    except ImportError:
        return {"error": "the kuzu package is not installed", "prerequisite": "kuzu"}
    try:
        g = GraphDatabase.connect_read_only(ctx.kuzu_path)
    except RuntimeError as exc:
        return {"error": f"the graph store could not be opened: {exc}", "prerequisite": "graph"}
    try:
        try:
            result = gq.run_catalogue(g, query_id, dict(params))
        except ValueError as exc:
            raise BadArgumentsError(str(exc)) from None
        except Exception as exc:  # noqa: BLE001 — an unbuilt graph has no tables
            if "does not exist" in str(exc) or "Binder exception" in str(exc):
                return {"error": "the knowledge graph has not been built", "prerequisite": "graph"}
            raise
    finally:
        g.close()
    # The canvas elements are for drawing; the model reads rows.
    result.pop("elements", None)
    return result


def overview(ctx: AskContext, args: Mapping[str, Any]) -> dict[str, Any]:
    from ..api import dashboard

    k = dashboard.kpis(ctx.db, ctx.noise)
    return {key: k[key] for key in ("totals", "by_copilot", "tool_usage") if key in k}


TOOLS: dict[str, ToolFn] = {
    "find_sessions": find_sessions,
    "session_summary": session_summary,
    "session_turns": session_turns,
    "session_analyses": session_analyses,
    "search_text": search_text,
    "patterns": patterns,
    "similar_sessions": similar_sessions,
    "graph_question": graph_question,
    "overview": overview,
}


def call_tool(ctx: AskContext, name: str, args: Mapping[str, Any], *, declared: Mapping[str, Any]) -> dict[str, Any]:
    """Run one tool by name with the model's arguments. ``declared`` is
    the tool's ``args`` map from ask.json: a name the model invented is
    rejected before anything runs."""
    fn = TOOLS.get(name)
    if fn is None:
        raise UnknownToolError(f"unknown tool {name!r}; one of: {', '.join(TOOLS)}")
    unknown = sorted(set(args) - set(declared))
    if unknown:
        raise BadArgumentsError(
            f"{name} does not take {', '.join(unknown)}; its arguments are: "
            + (", ".join(declared) or "none")
        )
    return fn(ctx, args)


# ── facts the prompt opens with ─────────────────────────────────────────


def store_facts(ctx: AskContext) -> dict[str, Any]:
    """What is in the store, so the model does not have to discover it a
    step at a time: counts, date span, copilots, projects, whether text
    is archived, which analyses exist, whether the graph is built."""
    from ..graph import query as gq

    db = ctx.db
    # The same sessions the pages count: probes and temp dirs left out.
    keep_sql, keep_params = keep_clause(ctx.noise, "copilot_session") if ctx.noise else ("1=1", ())
    totals = db.query_one(
        f"SELECT COUNT(*), MIN(started_at), MAX(started_at) FROM copilot_session WHERE {keep_sql}",
        keep_params,
    ) or (0, None, None)
    copilots = [
        {"copilot": r[0], "sessions": int(r[1])}
        for r in db.query(
            f"SELECT copilot, COUNT(*) FROM copilot_session WHERE {keep_sql} GROUP BY copilot ORDER BY 2 DESC",
            keep_params,
        )
    ]
    projects = [
        {"project_path": r[0], "sessions": int(r[1])}
        for r in db.query(
            f"SELECT project_path, COUNT(*) FROM copilot_session WHERE {keep_sql} "
            "GROUP BY project_path ORDER BY 2 DESC LIMIT 15",
            keep_params,
        )
    ]
    archived = db.query_one(f"SELECT COUNT(DISTINCT session_ref) FROM {C.TBL_TRACE_DOCUMENT}") or (0,)
    analysed = db.query_one(
        f"SELECT COUNT(DISTINCT session_ref) FROM {C.TBL_SESSION_ANALYSIS} WHERE parse_status = 'ok'"
    ) or (0,)
    graph_built = bool(ctx.kuzu_path) and Path(ctx.kuzu_path).exists()
    return {
        "sessions": int(totals[0] or 0),
        "first_session": totals[1],
        "last_session": totals[2],
        "copilots": copilots,
        "projects": projects,
        "sessions_with_archived_text": int(archived[0] or 0),
        "sessions_with_analyses": int(analysed[0] or 0),
        "graph_built": graph_built,
        "graph_questions": [
            {"id": q["id"], "question": q["question"], "params": [p["name"] for p in q["params"]]}
            for q in gq.catalogue()
        ],
    }
