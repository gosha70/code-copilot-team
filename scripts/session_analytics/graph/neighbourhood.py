# session_analytics.graph.neighbourhood — a session, or a project, and
# what it is connected to.
#
# The Graph page used to draw the SCHEMA: one bubble per node type,
# eight sample members on tap, edges with no name. Nobody learns
# anything about their sessions from that. These functions answer the
# question a person actually brings to a graph — "what is this session
# made of, and what is it connected to" — with every relationship named
# and the 65k-turn layer aggregated (tools per name with counts, not a
# bubble per call). Each query runs in milliseconds on a real store.

from __future__ import annotations

from typing import Any, Optional

from ..relational.db import Database
from .schema import GraphDatabase

#: The "context" relationships of a Session: one hop to the things it
#: ran on / in / as. Order is display order.
CONTEXT_RELS = ("IN_WORKSPACE", "USED_MODEL", "RAN_ON", "BY_DEVELOPER", "USED_AGENT")
#: How many of the longest lists the neighbourhood carries.
TOP_FILES = 12
TOP_SIMILAR = 8
TOP_TOOLS = 20
PROJECT_SESSIONS = 60
FILE_SESSIONS = 40


def _rows(result) -> list[list]:
    out: list[list] = []
    while result.has_next():
        out.append(list(result.get_next()))
    return out


def _count(gdb: GraphDatabase, cypher: str, params: dict) -> int:
    rows = _rows(gdb.execute(cypher, params))
    return int(rows[0][0]) if rows and rows[0][0] is not None else 0


def _key_of(node: dict) -> str:
    """A Kùzu node's primary key value, whatever its table."""
    for k in ("session_key", "path", "name", "developer_id", "turn_key", "tool_key", "error_key"):
        v = node.get(k)
        if v is not None:
            return str(v)
    return str(node.get("_id"))


def _session_row(rel: Database, session_key: str) -> Optional[dict[str, Any]]:
    copilot, _, native = session_key.partition(":")
    row = rel.query_one(
        "SELECT id, project_path, model, turn_count, tool_call_count, error_count, started_at, copilot "
        "FROM copilot_session WHERE copilot = ? AND session_id = ?",
        (copilot, native),
    )
    if row is None:
        return None
    return {
        "id": int(row[0]), "session_key": session_key, "project_path": row[1], "model": row[2],
        "turn_count": int(row[3] or 0), "tool_call_count": int(row[4] or 0),
        "error_count": int(row[5] or 0), "started_at": row[6], "copilot": row[7],
    }


def session_key_for(rel: Database, session_id: int) -> Optional[str]:
    row = rel.query_one("SELECT copilot, session_id FROM copilot_session WHERE id = ?", (session_id,))
    return f"{row[0]}:{row[1]}" if row else None


def session_neighbourhood(gdb: GraphDatabase, rel: Database, session_id: int) -> Optional[dict[str, Any]]:
    """Everything one hop (or one aggregated hop) from a session."""
    key = session_key_for(rel, session_id)
    if key is None:
        return None
    centre = _session_row(rel, key)
    p = {"k": key}

    context = []
    for row in _rows(gdb.execute(
        "MATCH (s:Session {session_key: $k})-[r]->(m) "
        "WHERE label(m) IN ['Workspace', 'Model', 'Copilot', 'Developer', 'Agent'] "
        "RETURN label(r), label(m), m", p,
    )):
        context.append({"rel": row[0], "label": row[1], "key": _key_of(row[2])})
    context.sort(key=lambda c: CONTEXT_RELS.index(c["rel"]) if c["rel"] in CONTEXT_RELS else 99)

    tools = [
        {"tool": r[0], "calls": int(r[1]), "errors": int(r[2] or 0)}
        for r in _rows(gdb.execute(
            "MATCH (s:Session {session_key: $k})-[:HAS_TURN]->(:Turn)-[:INVOKED]->(i:ToolInvocation) "
            "RETURN i.tool_name, count(i), sum(CASE WHEN i.is_error THEN 1 ELSE 0 END) "
            f"ORDER BY count(i) DESC LIMIT {TOP_TOOLS}", p,
        ))
    ]
    errors = [
        {"tool": r[0], "error_type": r[1], "count": int(r[2])}
        for r in _rows(gdb.execute(
            "MATCH (s:Session {session_key: $k})-[:HAS_TURN]->(:Turn)-[:INVOKED]->(:ToolInvocation)"
            "-[:PRODUCED_ERROR]->(e:ErrorNode) "
            "RETURN e.tool_name, e.error_type, count(e) ORDER BY count(e) DESC LIMIT 20", p,
        ))
    ]
    files = [
        {"path": r[0], "accesses": int(r[1]), "access_types": sorted(x for x in (r[2] or []) if x)}
        for r in _rows(gdb.execute(
            "MATCH (s:Session {session_key: $k})-[:HAS_TURN]->(:Turn)-[:INVOKED]->(:ToolInvocation)"
            "-[a:ACCESSED_FILE]->(f:FileNode) "
            "RETURN f.path, count(a), collect(DISTINCT a.access_type) "
            f"ORDER BY count(a) DESC LIMIT {TOP_FILES}", p,
        ))
    ]
    similar = []
    for r in _rows(gdb.execute(
        "MATCH (s:Session {session_key: $k})-[r:SIMILAR_TO]->(t:Session) "
        f"RETURN t.session_key, r.score, t.project_path, t.model, t.turn_count ORDER BY r.score DESC LIMIT {TOP_SIMILAR}", p,
    )):
        other = _session_row(rel, r[0])
        similar.append({
            "session_key": r[0], "id": other["id"] if other else None, "score": float(r[1]),
            "project_path": r[2], "model": r[3], "turn_count": int(r[4] or 0),
        })
    # Every list above is capped; the totals say what the cap hid, so
    # the page can say "12 of 31 files", never "the files".
    totals = {
        "tools": _count(gdb, "MATCH (s:Session {session_key: $k})-[:HAS_TURN]->(:Turn)-[:INVOKED]->(i:ToolInvocation) "
                             "RETURN count(DISTINCT i.tool_name)", p),
        "files": _count(gdb, "MATCH (s:Session {session_key: $k})-[:HAS_TURN]->(:Turn)-[:INVOKED]->(:ToolInvocation)"
                             "-[:ACCESSED_FILE]->(f:FileNode) RETURN count(DISTINCT f.path)", p),
        "similar": _count(gdb, "MATCH (s:Session {session_key: $k})-[r:SIMILAR_TO]->(:Session) RETURN count(r)", p),
        "errors": _count(gdb, "MATCH (s:Session {session_key: $k})-[:HAS_TURN]->(:Turn)-[:INVOKED]->(:ToolInvocation)"
                              "-[:PRODUCED_ERROR]->(e:ErrorNode) RETURN count(e)", p),
    }
    return {
        "kind": "session",
        "centre": centre,
        "context": context,
        "tools": tools,
        "errors": errors,
        "files": files,
        "similar": similar,
        "totals": totals,
        "limits": {"tools": TOP_TOOLS, "files": TOP_FILES, "similar": TOP_SIMILAR},
        "relationships": {
            "context": "the session's one-hop context: IN_WORKSPACE, USED_MODEL, RAN_ON, BY_DEVELOPER, USED_AGENT",
            "tools": "Session -HAS_TURN-> Turn -INVOKED-> ToolInvocation, aggregated per tool name",
            "errors": "ToolInvocation -PRODUCED_ERROR-> ErrorNode, per tool and type",
            "files": "ToolInvocation -ACCESSED_FILE-> FileNode, per file",
            "similar": "Session -SIMILAR_TO-> Session, the last similarity pass's score",
        },
    }


def tool_turns(gdb: GraphDatabase, rel: Database, session_id: int, tool: str) -> Optional[dict[str, Any]]:
    """The turns of one session that invoked one tool — the drill-in
    behind a tool bubble; each links to the transcript."""
    key = session_key_for(rel, session_id)
    if key is None:
        return None
    # One row per CALL (ToolInvocation), not per turn: a turn can call
    # the same tool several times, and grouping by turn collapsed them
    # (or split one turn in two when one call errored and another did
    # not). The turn number is what links into the transcript.
    rows = _rows(gdb.execute(
        "MATCH (s:Session {session_key: $k})-[:HAS_TURN]->(t:Turn)-[:INVOKED]->(i:ToolInvocation {tool_name: $tool}) "
        "OPTIONAL MATCH (i)-[:PRODUCED_ERROR]->(e:ErrorNode) "
        "RETURN i.tool_key, t.sequence_num, i.is_error, collect(e.error_type) ORDER BY t.sequence_num, i.tool_key",
        {"k": key, "tool": tool},
    ))
    calls = [
        {"call_key": r[0], "sequence_num": int(r[1]), "is_error": bool(r[2]),
         "error_types": sorted({x for x in (r[3] or []) if x})}
        for r in rows
    ]
    return {
        "session_id": session_id,
        "tool": tool,
        "calls": calls,
        "turns": len({c["sequence_num"] for c in calls}),
    }


def file_sessions(gdb: GraphDatabase, rel: Database, path: str) -> dict[str, Any]:
    """Every session that touched one file — the drill-in behind a file."""
    rows = _rows(gdb.execute(
        "MATCH (s:Session)-[:HAS_TURN]->(:Turn)-[:INVOKED]->(:ToolInvocation)-[a:ACCESSED_FILE]->(f:FileNode {path: $p}) "
        f"RETURN s.session_key, count(a), collect(DISTINCT a.access_type) ORDER BY count(a) DESC LIMIT {FILE_SESSIONS}",
        {"p": path},
    ))
    total = _count(gdb, "MATCH (s:Session)-[:HAS_TURN]->(:Turn)-[:INVOKED]->(:ToolInvocation)-[:ACCESSED_FILE]->(f:FileNode {path: $p}) "
                        "RETURN count(DISTINCT s)", {"p": path})
    sessions = []
    for r in rows:
        other = _session_row(rel, r[0])
        sessions.append({
            "session_key": r[0], "id": other["id"] if other else None,
            "project_path": other["project_path"] if other else None,
            "model": other["model"] if other else None,
            "started_at": other["started_at"] if other else None,
            "accesses": int(r[1]), "access_types": sorted(x for x in (r[2] or []) if x),
        })
    return {"path": path, "sessions": sessions, "total": total, "limit": FILE_SESSIONS}


def project_neighbourhood(gdb: GraphDatabase, rel: Database, project_path: str) -> dict[str, Any]:
    """A project's sessions and how they relate: SIMILAR_TO edges among
    them, the models they ran on, the tools and files they share."""
    p = {"w": project_path}
    sessions = []
    keys = set()
    for r in _rows(gdb.execute(
        "MATCH (s:Session)-[:IN_WORKSPACE]->(w:Workspace {path: $w}) "
        "RETURN s.session_key, s.model, s.turn_count, s.error_count, s.started_at "
        f"ORDER BY s.started_at DESC LIMIT {PROJECT_SESSIONS}", p,
    )):
        other = _session_row(rel, r[0])
        keys.add(r[0])
        sessions.append({
            "session_key": r[0], "id": other["id"] if other else None, "model": r[1],
            "turn_count": int(r[2] or 0), "error_count": int(r[3] or 0), "started_at": r[4],
        })
    edges = [
        {"source": r[0], "target": r[1], "score": float(r[2])}
        for r in _rows(gdb.execute(
            "MATCH (a:Session)-[r:SIMILAR_TO]->(b:Session) "
            "WHERE (a)-[:IN_WORKSPACE]->(:Workspace {path: $w}) AND (b)-[:IN_WORKSPACE]->(:Workspace {path: $w}) "
            "RETURN a.session_key, b.session_key, r.score", p,
        ))
        if r[0] in keys and r[1] in keys
    ]
    models = [
        {"model": r[0], "sessions": int(r[1])}
        for r in _rows(gdb.execute(
            "MATCH (s:Session)-[:IN_WORKSPACE]->(:Workspace {path: $w}) "
            "MATCH (s)-[:USED_MODEL]->(m:Model) RETURN m.name, count(s) ORDER BY count(s) DESC", p,
        ))
    ]
    tools = [
        {"tool": r[0], "calls": int(r[1]), "sessions": int(r[2])}
        for r in _rows(gdb.execute(
            "MATCH (s:Session)-[:IN_WORKSPACE]->(:Workspace {path: $w}) "
            "MATCH (s)-[:HAS_TURN]->(:Turn)-[:INVOKED]->(i:ToolInvocation) "
            f"RETURN i.tool_name, count(i), count(DISTINCT s) ORDER BY count(i) DESC LIMIT {TOP_TOOLS}", p,
        ))
    ]
    files = [
        {"path": r[0], "sessions": int(r[1]), "accesses": int(r[2])}
        for r in _rows(gdb.execute(
            "MATCH (s:Session)-[:IN_WORKSPACE]->(:Workspace {path: $w}) "
            "MATCH (s)-[:HAS_TURN]->(:Turn)-[:INVOKED]->(:ToolInvocation)-[a:ACCESSED_FILE]->(f:FileNode) "
            f"RETURN f.path, count(DISTINCT s), count(a) ORDER BY count(DISTINCT s) DESC, count(a) DESC LIMIT {TOP_FILES}", p,
        ))
    ]
    totals = {
        "sessions": _count(gdb, "MATCH (s:Session)-[:IN_WORKSPACE]->(:Workspace {path: $w}) RETURN count(s)", p),
        "tools": _count(gdb, "MATCH (s:Session)-[:IN_WORKSPACE]->(:Workspace {path: $w}) "
                             "MATCH (s)-[:HAS_TURN]->(:Turn)-[:INVOKED]->(i:ToolInvocation) RETURN count(DISTINCT i.tool_name)", p),
        "files": _count(gdb, "MATCH (s:Session)-[:IN_WORKSPACE]->(:Workspace {path: $w}) "
                             "MATCH (s)-[:HAS_TURN]->(:Turn)-[:INVOKED]->(:ToolInvocation)-[:ACCESSED_FILE]->(f:FileNode) "
                             "RETURN count(DISTINCT f.path)", p),
    }
    return {
        "kind": "project",
        "project_path": project_path,
        "sessions": sessions,
        "similar_edges": edges,
        "models": models,
        "tools": tools,
        "files": files,
        "totals": totals,
        "limits": {"sessions": PROJECT_SESSIONS, "tools": TOP_TOOLS, "files": TOP_FILES},
        "relationships": {
            "sessions": "Session -IN_WORKSPACE-> Workspace",
            "similar_edges": "Session -SIMILAR_TO-> Session within the project",
            "models": "Session -USED_MODEL-> Model",
            "tools": "aggregated ToolInvocations per tool across the project's sessions",
            "files": "FileNodes touched by the most of the project's sessions",
        },
    }


def project_paths(gdb: GraphDatabase) -> list[dict[str, Any]]:
    """Every workspace in the graph with its session count — the
    project picker."""
    return [
        {"path": r[0], "sessions": int(r[1])}
        for r in _rows(gdb.execute(
            "MATCH (s:Session)-[:IN_WORKSPACE]->(w:Workspace) RETURN w.path, count(s) ORDER BY count(s) DESC"
        ))
    ]
