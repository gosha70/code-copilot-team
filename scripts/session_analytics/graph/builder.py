# session_analytics.graph.builder — relational rows → Kùzu knowledge graph.
#
# Idempotent by construction: every node/rel is written with MERGE keyed on a
# natural key (session_key = "<copilot>:<session_id>", turn_key, tool_key,
# file path, …), so a rebuild or a single-session re-build converges without
# duplicates. ``--rebuild`` drops + recreates the tables first for a clean
# full repopulation.

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from ..relational.db import Database
from . import schema
from .schema import GraphDatabase

_log = logging.getLogger(__name__)


@dataclass
class GraphStats:
    sessions: int = 0
    turns: int = 0
    tools: int = 0
    files: int = 0
    errors: int = 0

    def as_dict(self) -> dict:
        return {
            "sessions": self.sessions,
            "turns": self.turns,
            "tools": self.tools,
            "files": self.files,
            "errors": self.errors,
        }


def build(
    rel: Database,
    graph_path: str,
    *,
    session_ids: Optional[Sequence[int]] = None,
    rebuild: bool = False,
) -> GraphStats:
    """Build (or incrementally update) the Kùzu graph from ``rel``.

    ``session_ids`` limits the build to specific relational session ids
    (incremental); ``None`` builds every session. ``rebuild`` drops and
    recreates all tables first (ignores ``session_ids``).
    """
    gdb = GraphDatabase.connect(graph_path)
    try:
        if rebuild:
            schema.reset_schema(gdb)
        else:
            schema.apply_schema(gdb)

        stats = GraphStats()
        for srow in _sessions(rel, None if rebuild else session_ids):
            _build_session(rel, gdb, srow, stats)
        return stats
    finally:
        gdb.close()


# ── relational reads ───────────────────────────────────────────────────


def _sessions(rel: Database, session_ids):
    base = (
        "SELECT id, copilot, session_id, project_path, model, developer_id, "
        "started_at, turn_count, tool_call_count, error_count FROM copilot_session"
    )
    if session_ids:
        ph = ",".join("?" for _ in session_ids)
        return rel.query(f"{base} WHERE id IN ({ph})", tuple(session_ids))
    return rel.query(base)


def _build_session(rel: Database, gdb: GraphDatabase, srow, stats: GraphStats) -> None:
    (sid, copilot, native_id, project_path, model, developer_id,
     started_at, turn_count, tool_call_count, error_count) = srow
    session_key = f"{copilot}:{native_id}"

    # Dimension nodes + their session rels.
    gdb.execute("MERGE (c:Copilot {name: $n})", {"n": copilot})
    gdb.execute("MERGE (d:Developer {developer_id: $d})", {"d": developer_id or "local"})
    if model:
        gdb.execute("MERGE (m:Model {name: $n})", {"n": model})
    if project_path:
        gdb.execute("MERGE (w:Workspace {path: $p})", {"p": project_path})

    gdb.execute(
        """
        MERGE (s:Session {session_key: $k})
        SET s.copilot=$copilot, s.model=$model, s.project_path=$pp,
            s.started_at=$started, s.turn_count=$tc, s.tool_call_count=$tcc,
            s.error_count=$ec
        """,
        {
            "k": session_key, "copilot": copilot, "model": model or "",
            "pp": project_path or "", "started": started_at or "",
            "tc": int(turn_count or 0), "tcc": int(tool_call_count or 0),
            "ec": int(error_count or 0),
        },
    )
    _merge_rel(gdb, "Session", "session_key", session_key, "RAN_ON", "Copilot", "name", copilot)
    _merge_rel(gdb, "Session", "session_key", session_key, "BY_DEVELOPER", "Developer", "developer_id", developer_id or "local")
    if model:
        _merge_rel(gdb, "Session", "session_key", session_key, "USED_MODEL", "Model", "name", model)
    if project_path:
        _merge_rel(gdb, "Session", "session_key", session_key, "IN_WORKSPACE", "Workspace", "path", project_path)
    stats.sessions += 1

    # Turns.
    turns = rel.query(
        "SELECT id, sequence_num, role, is_sidechain, slash_command "
        "FROM copilot_turn WHERE session_id = ? ORDER BY sequence_num",
        (sid,),
    )
    tool_key_by_id: dict[int, str] = {}
    prev_turn_key: Optional[str] = None
    for trow in turns:
        turn_db_id, seq, role, is_sidechain, slash = trow
        turn_key = f"{session_key}#{seq}"
        gdb.execute(
            """
            MERGE (t:Turn {turn_key: $k})
            SET t.sequence_num=$seq, t.role=$role, t.is_sidechain=$side,
                t.slash_command=$slash
            """,
            {"k": turn_key, "seq": int(seq), "role": role,
             "side": bool(is_sidechain), "slash": slash or ""},
        )
        _merge_rel(gdb, "Session", "session_key", session_key, "HAS_TURN", "Turn", "turn_key", turn_key)
        if prev_turn_key is not None:
            _merge_rel(gdb, "Turn", "turn_key", prev_turn_key, "FOLLOWED_BY", "Turn", "turn_key", turn_key)
        prev_turn_key = turn_key
        stats.turns += 1

        # Tool invocations for this turn.
        tools = rel.query(
            """
            SELECT tc.id, tc.tool_name, tc.tool_name_raw, tc.sequence_num,
                   COALESCE(tr.is_error, 0)
            FROM copilot_tool_call tc
            LEFT JOIN copilot_tool_result tr ON tr.tool_call_id = tc.id
            WHERE tc.turn_id = ? ORDER BY tc.sequence_num
            """,
            (turn_db_id,),
        )
        for tc_id, tname, tname_raw, tseq, is_err in tools:
            tool_key = f"{turn_key}:{tseq}"
            tool_key_by_id[int(tc_id)] = tool_key
            gdb.execute(
                """
                MERGE (i:ToolInvocation {tool_key: $k})
                SET i.tool_name=$name, i.tool_name_raw=$raw, i.is_error=$err
                """,
                {"k": tool_key, "name": tname, "raw": tname_raw or "", "err": bool(is_err)},
            )
            _merge_rel(gdb, "Turn", "turn_key", turn_key, "INVOKED", "ToolInvocation", "tool_key", tool_key)
            stats.tools += 1

    # File accesses → ToolInvocation -[:ACCESSED_FILE]-> FileNode.
    for far in rel.query(
        "SELECT tool_call_id, file_path, access_type, language "
        "FROM copilot_file_access WHERE session_id = ?",
        (sid,),
    ):
        tc_id, path, access_type, language = far
        if not path:
            continue
        gdb.execute(
            "MERGE (f:FileNode {path: $p}) SET f.language=$lang",
            {"p": path, "lang": language or ""},
        )
        tk = tool_key_by_id.get(int(tc_id)) if tc_id is not None else None
        if tk:
            gdb.execute(
                """
                MATCH (i:ToolInvocation {tool_key: $tk}), (f:FileNode {path: $p})
                MERGE (i)-[r:ACCESSED_FILE]->(f) SET r.access_type=$at
                """,
                {"tk": tk, "p": path, "at": access_type or ""},
            )
        stats.files += 1

    # Errors → ToolInvocation -[:PRODUCED_ERROR]-> ErrorNode.
    for erow in rel.query(
        "SELECT id, tool_call_id, error_type, tool_name "
        "FROM copilot_error WHERE session_id = ?",
        (sid,),
    ):
        err_id, tc_id, error_type, tool_name = erow
        error_key = f"{session_key}!err:{err_id}"
        gdb.execute(
            """
            MERGE (e:ErrorNode {error_key: $k})
            SET e.error_type=$et, e.tool_name=$tn
            """,
            {"k": error_key, "et": (error_type or "")[:200], "tn": tool_name or ""},
        )
        tk = tool_key_by_id.get(int(tc_id)) if tc_id is not None else None
        if tk:
            _merge_rel(gdb, "ToolInvocation", "tool_key", tk, "PRODUCED_ERROR", "ErrorNode", "error_key", error_key)
        stats.errors += 1


def _merge_rel(
    gdb: GraphDatabase,
    from_label: str, from_key: str, from_val: str,
    rel: str,
    to_label: str, to_key: str, to_val: str,
) -> None:
    gdb.execute(
        f"MATCH (a:{from_label} {{{from_key}: $fv}}), (b:{to_label} {{{to_key}: $tv}}) "
        f"MERGE (a)-[:{rel}]->(b)",
        {"fv": from_val, "tv": to_val},
    )
