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
from ..embedding.cluster_reader import KuzuGraphSnapshot
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
TAGS = tuple(mcp_tools.SESSION_TAG_FILTERS)
#: How many projects the opening facts name (the exact count is beside them).
TOP_PROJECTS = 15

#: What a read-only open of the graph store finds.
GRAPH_READY = "ready"
GRAPH_ABSENT = "absent"
GRAPH_UNBUILT = "unbuilt"
GRAPH_UNOPENABLE = "unopenable"
GRAPH_NO_KUZU = "kuzu-missing"
_GRAPH_STATE_MESSAGE = {
    GRAPH_ABSENT: "the knowledge graph has not been built",
    GRAPH_UNBUILT: "the knowledge graph has not been built",
    GRAPH_UNOPENABLE: "the graph store could not be opened",
    GRAPH_NO_KUZU: "the kuzu package is not installed",
}


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


def _keep(ctx: AskContext, alias: str) -> tuple[str, tuple[Any, ...]]:
    """The pages' noise policy for lists, searches and aggregates: probe
    and temp-dir sessions are left out. A tool given one session id
    still reads that session — asking about a thing by name is not a
    discovery."""
    return keep_clause(ctx.noise, alias) if ctx.noise else ("1=1", ())


def _open_graph(ctx: AskContext):
    """(state, read-only handle or None). Never creates the store, and
    never reads an error's text: readiness is the catalog's answer
    (``CALL show_tables()``), the rule the graph substrate settled on."""
    if not ctx.kuzu_path or not Path(ctx.kuzu_path).exists():
        return GRAPH_ABSENT, None
    try:
        from ..graph.schema import GraphDatabase
    except ImportError:
        return GRAPH_NO_KUZU, None
    try:
        g = GraphDatabase.connect_read_only(ctx.kuzu_path)
    except RuntimeError:
        return GRAPH_UNOPENABLE, None
    if not KuzuGraphSnapshot(g).graph_ready():
        g.close()
        return GRAPH_UNBUILT, None
    return GRAPH_READY, g


def graph_state(ctx: AskContext) -> str:
    """ready | absent | unbuilt | unopenable | kuzu-missing — from a
    read-only open and the catalog, not from whether a path exists (a
    path can exist and hold nothing)."""
    state, g = _open_graph(ctx)
    if g is not None:
        g.close()
    return state


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
    limit = _int(args, "limit", 20, lo=1, hi=SESSIONS_MAX)
    try:
        rows = mcp_tools.search_sessions(
            ctx.db,
            _str(args, "query") or None,
            copilot=_str(args, "copilot") or None,
            date_from=_str(args, "date_from") or None,
            date_to=_str(args, "date_to") or None,
            tag=tag or None,
            limit=limit,
            noise=ctx.noise,
            sort=sort,
        )
    except (mcp_tools.UnknownSortError, mcp_tools.UnknownTagError) as exc:
        raise BadArgumentsError(str(exc)) from None
    sessions = [_session_row(s) for s in rows]
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
    keep_sql, keep_params = _keep(ctx, "s")
    hits: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    # Same policy as every list on the pages: noise is left out of a
    # search — BEFORE the ranked top-N is cut, in the search itself.
    for h in arch.search_traces(ctx.db, query, limit=limit, noise=ctx.noise):
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
            f"""
            SELECT t.session_id, t.sequence_num, s.project_path, t.content_preview
            FROM copilot_turn t JOIN copilot_session s ON s.id = t.session_id
            WHERE LOWER(t.content_preview) LIKE LOWER(?) ESCAPE '\\' AND {keep_sql}
            ORDER BY t.session_id DESC, t.sequence_num LIMIT ?
            """,
            (like, *keep_params, limit * 2),
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
        noise=ctx.noise,
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
    entry = gq.catalogue_entry(query_id)
    if entry is None:
        raise BadArgumentsError(
            f"unknown catalogue query {query_id!r}; the ids are listed under FACTS"
        )
    # The same rule as the top-level arguments: a parameter the model
    # invents is refused, not silently ignored — otherwise it would
    # believe it filtered by something the query never saw.
    declared = [p["name"] for p in entry.get("params", [])]
    unknown = sorted(set(params) - set(declared))
    if unknown:
        raise BadArgumentsError(
            f"{query_id} does not take {', '.join(unknown)}; its parameters are: "
            + (", ".join(declared) or "none")
        )
    # Readiness is settled from the catalog before the query runs, so a
    # failed query is never read for what state the store is in.
    state, g = _open_graph(ctx)
    if g is None:
        return {"error": _GRAPH_STATE_MESSAGE[state], "prerequisite": "graph"}
    try:
        try:
            result = gq.run_catalogue(g, query_id, dict(params))
        except ValueError as exc:
            raise BadArgumentsError(str(exc)) from None
    finally:
        g.close()
    # A graph-rendered answer carries its evidence as nodes and
    # relationships, not rows; the model gets them in a form it can read.
    elements = result.pop("elements", None)
    if elements is not None:
        # No empty `rows` beside the nodes: a model reads "rows: []" as
        # "nothing found" and argues with the relationships under it.
        result.pop("rows", None)
        result.pop("columns", None)
        result["shape"] = "graph"
        result["nodes"] = [
            {"id": n["id"], **_session_ref(ctx, n), **_brief(n["props"])}
            for n in elements["nodes"]
        ]
        result["relationships"] = [
            {"from": e["source"], "rel": e["rel"], "to": e["target"], **_brief(e["props"])}
            for e in elements["edges"]
        ]
    return result


#: Properties worth the model's window on a graph node or edge.
_BRIEF_PROPS = ("project_path", "model", "turn_count", "error_count", "started_at", "score", "name", "path")


def _session_ref(ctx: AskContext, node: Mapping[str, Any]) -> dict[str, Any]:
    """A Session node's relational id, so the answer can cite it and the
    page can link it; other nodes get nothing."""
    if node.get("label") != "Session" or ":" not in str(node.get("key", "")):
        return {}
    copilot, native = str(node["key"]).split(":", 1)
    row = ctx.db.query_one(
        "SELECT id FROM copilot_session WHERE copilot = ? AND session_id = ?", (copilot, native)
    )
    return {"session_id": int(row[0])} if row else {}


def _brief(props: Mapping[str, Any]) -> dict[str, Any]:
    return {k: props[k] for k in _BRIEF_PROPS if k in props and props[k] not in (None, "")}


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
    step at a time: counts, date span, copilots, the busiest projects
    (capped, and the cap is named), whether text is archived, which
    analyses exist, whether the graph can be read."""
    from ..graph import query as gq

    db = ctx.db
    # The same sessions the pages count: probes and temp dirs left out.
    keep_sql, keep_params = _keep(ctx, "copilot_session")
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
            f"GROUP BY project_path ORDER BY 2 DESC LIMIT {TOP_PROJECTS}",
            keep_params,
        )
    ]
    # The same universe as the counts above: an archived or analysed
    # probe must not be counted where the probe itself is not.
    archived = db.query_one(
        f"SELECT COUNT(DISTINCT td.session_ref) FROM {C.TBL_TRACE_DOCUMENT} td "
        f"JOIN copilot_session ON copilot_session.id = td.session_ref WHERE {keep_sql}",
        keep_params,
    ) or (0,)
    analysed = db.query_one(
        f"SELECT COUNT(DISTINCT a.session_ref) FROM {C.TBL_SESSION_ANALYSIS} a "
        f"JOIN copilot_session ON copilot_session.id = a.session_ref "
        f"WHERE a.parse_status = 'ok' AND {keep_sql}",
        keep_params,
    ) or (0,)
    project_count = db.query_one(
        f"SELECT COUNT(DISTINCT project_path) FROM copilot_session WHERE {keep_sql}", keep_params
    ) or (0,)
    return {
        "sessions": int(totals[0] or 0),
        "first_session": totals[1],
        "last_session": totals[2],
        "copilots": copilots,
        "project_count": int(project_count[0] or 0),
        "top_projects": projects,
        "top_projects_cap": TOP_PROJECTS,
        "sessions_with_archived_text": int(archived[0] or 0),
        "sessions_with_analyses": int(analysed[0] or 0),
        "graph_state": graph_state(ctx),
        "graph_questions": [
            {"id": q["id"], "question": q["question"], "params": [p["name"] for p in q["params"]]}
            for q in gq.catalogue()
        ],
    }
