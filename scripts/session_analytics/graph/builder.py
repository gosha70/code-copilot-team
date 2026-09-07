# session_analytics.graph.builder — relational rows → Kùzu knowledge graph.
#
# Two paths, one graph:
#
# * ``--rebuild`` (the pipeline's "Build knowledge graph" step) is BULK:
#   set-based SELECTs over the store are written to CSVs and loaded with
#   Kùzu's ``COPY <table> FROM``, nodes before rels. The per-row MERGE it
#   replaces issued ~271k statements and 90k SQL round-trips for a 90k-turn
#   store — 67 minutes and 9.2 GB (#311). COPY needs empty tables and
#   unique primary keys, both guaranteed here: the schema is reset first,
#   and keys are deduplicated before they are written.
# * incremental (``session_ids``) keeps MERGE, keyed on the same natural
#   keys (session_key = "<copilot>:<session_id>", turn_key, tool_key, file
#   path, …), so a single-session re-build converges without duplicates.
#   It reads a session's tool calls in one query, not one per turn.

from __future__ import annotations

import csv
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from ..config import NoiseConfig
from ..relational.db import Database
from ..session_filter import keep_clause
from . import schema
from .schema import GraphDatabase

_log = logging.getLogger(__name__)

#: How ErrorNode.error_type is capped (the MERGE path always did this).
_ERROR_TYPE_CHARS = 200


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
    noise: Optional[NoiseConfig] = None,
) -> GraphStats:
    """Build (or incrementally update) the Kùzu graph from ``rel``.

    ``session_ids`` limits the build to specific relational session ids
    (incremental); ``None`` builds every session. ``rebuild`` drops and
    recreates all tables first (ignores ``session_ids``) and takes the
    bulk path. ``noise`` (optional) leaves noise sessions out — the
    default is every session, parity with the graph as it was.
    """
    gdb = GraphDatabase.connect(graph_path)
    try:
        if rebuild:
            schema.reset_schema(gdb)
            return _build_bulk(rel, gdb, noise)
        schema.apply_schema(gdb)
        stats = GraphStats()
        for srow in _sessions(rel, session_ids, noise):
            _build_session(rel, gdb, srow, stats)
        return stats
    finally:
        gdb.close()


# ── shared ──────────────────────────────────────────────────────────────


def _sessions(rel: Database, session_ids, noise: Optional[NoiseConfig]):
    base = (
        "SELECT s.id, s.copilot, s.session_id, s.project_path, s.model, s.developer_id, "
        "s.started_at, s.turn_count, s.tool_call_count, s.error_count FROM copilot_session s"
    )
    conds: list[str] = []
    params: list[Any] = []
    if session_ids:
        conds.append("s.id IN (" + ",".join("?" for _ in session_ids) + ")")
        params += list(session_ids)
    if noise is not None:
        keep_sql, keep_params = keep_clause(noise, "s")
        conds.append(keep_sql)
        params += list(keep_params)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    return rel.query(f"{base}{where} ORDER BY s.id", tuple(params))


def _session_key(copilot: str, native_id: str) -> str:
    return f"{copilot}:{native_id}"


# ── bulk path (rebuild) ─────────────────────────────────────────────────


class _Csv:
    """One CSV per table, header first, every field quoted, quotes and
    backslashes backslash-escaped, newlines flattened to spaces. Keys are
    deduplicated at the writer (COPY aborts on a duplicate primary key),
    so a store with a repeated natural key still loads — the first row
    wins, as MERGE's first write did."""

    def __init__(self, directory: Path, table: str, columns: Sequence[str], key_index: Optional[int] = 0):
        self.table = table
        self.path = directory / f"{table}.csv"
        self._fh = open(self.path, "w", newline="", encoding="utf-8")
        self._w = csv.writer(
            self._fh, quoting=csv.QUOTE_ALL, escapechar="\\", doublequote=False,
            lineterminator="\n",
        )
        self._w.writerow(columns)
        self._key_index = key_index
        self._seen: set[Any] = set()
        self.rows = 0

    def write(self, row: Sequence[Any]) -> bool:
        if self._key_index is not None:
            key = row[self._key_index]
            if key in self._seen:
                return False
            self._seen.add(key)
        self._w.writerow([_cell(v) for v in row])
        self.rows += 1
        return True

    def close(self) -> None:
        self._fh.close()


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return v.replace("\r", " ").replace("\n", " ")
    return v


def _build_bulk(rel: Database, gdb: GraphDatabase, noise: Optional[NoiseConfig]) -> GraphStats:
    stats = GraphStats()
    with tempfile.TemporaryDirectory(prefix="cct-sa-graph-") as tmp:
        d = Path(tmp)
        # Node tables, in nodes.cypher order (Agent has no writer: the
        # MERGE path never created one either).
        copilots = _Csv(d, "Copilot", ["name"])
        developers = _Csv(d, "Developer", ["developer_id"])
        workspaces = _Csv(d, "Workspace", ["path"])
        models = _Csv(d, "Model", ["name"])
        sessions = _Csv(d, "Session", [
            "session_key", "copilot", "model", "project_path", "started_at",
            "turn_count", "tool_call_count", "error_count",
        ])
        turns = _Csv(d, "Turn", ["turn_key", "sequence_num", "role", "is_sidechain", "slash_command"])
        tools = _Csv(d, "ToolInvocation", ["tool_key", "tool_name", "tool_name_raw", "is_error"])
        files = _Csv(d, "FileNode", ["path", "language"])
        errors = _Csv(d, "ErrorNode", ["error_key", "error_type", "tool_name"])
        # Rel tables: (from, to[, prop]); multi-edges are allowed, so the
        # dedupe key is the whole row.
        ran_on = _Csv(d, "RAN_ON", ["from", "to"], key_index=None)
        by_dev = _Csv(d, "BY_DEVELOPER", ["from", "to"], key_index=None)
        used_model = _Csv(d, "USED_MODEL", ["from", "to"], key_index=None)
        in_ws = _Csv(d, "IN_WORKSPACE", ["from", "to"], key_index=None)
        has_turn = _Csv(d, "HAS_TURN", ["from", "to"], key_index=None)
        followed = _Csv(d, "FOLLOWED_BY", ["from", "to"], key_index=None)
        invoked = _Csv(d, "INVOKED", ["from", "to"], key_index=None)
        accessed = _Csv(d, "ACCESSED_FILE", ["from", "to", "access_type"], key_index=None)
        produced = _Csv(d, "PRODUCED_ERROR", ["from", "to"], key_index=None)
        all_csvs = [
            copilots, developers, workspaces, models, sessions, turns, tools, files, errors,
            ran_on, by_dev, used_model, in_ws, has_turn, followed, invoked, accessed, produced,
        ]
        try:
            # Sessions + dimensions.
            key_by_sid: dict[int, str] = {}
            for (sid, copilot, native_id, project_path, model, developer_id,
                 started_at, turn_count, tool_call_count, error_count) in _sessions(rel, None, noise):
                skey = _session_key(copilot, native_id)
                if not sessions.write([
                    skey, copilot, model or "", project_path or "", started_at or "",
                    int(turn_count or 0), int(tool_call_count or 0), int(error_count or 0),
                ]):
                    continue
                key_by_sid[int(sid)] = skey
                dev = developer_id or "local"
                copilots.write([copilot])
                developers.write([dev])
                ran_on.write([skey, copilot])
                by_dev.write([skey, dev])
                if model:
                    models.write([model])
                    used_model.write([skey, model])
                if project_path:
                    workspaces.write([project_path])
                    in_ws.write([skey, project_path])
                stats.sessions += 1

            # Turns, in (session, sequence) order so FOLLOWED_BY is the
            # previous row of the same session.
            prev_sid, prev_key = None, None
            for sid, seq, role, is_sidechain, slash in rel.query(
                "SELECT session_id, sequence_num, role, is_sidechain, slash_command "
                "FROM copilot_turn ORDER BY session_id, sequence_num"
            ):
                skey = key_by_sid.get(int(sid))
                if skey is None:
                    continue
                tkey = f"{skey}#{int(seq)}"
                if not turns.write([tkey, int(seq), role, bool(is_sidechain), slash or ""]):
                    continue
                has_turn.write([skey, tkey])
                if prev_sid == sid and prev_key is not None:
                    followed.write([prev_key, tkey])
                prev_sid, prev_key = sid, tkey
                stats.turns += 1

            # Tool invocations: one row per call; a call with several
            # results is an error if any result was (aggregated in SQL,
            # so a key is complete when it is written).
            tool_key_by_id: dict[int, str] = {}
            for tc_id, sid, tseq, tname, traw, tcseq, is_err in rel.query(
                """
                SELECT tc.id, t.session_id, t.sequence_num, tc.tool_name, tc.tool_name_raw,
                       tc.sequence_num,
                       MAX(CASE WHEN tr.is_error THEN 1 ELSE 0 END)
                FROM copilot_tool_call tc
                JOIN copilot_turn t ON t.id = tc.turn_id
                LEFT JOIN copilot_tool_result tr ON tr.tool_call_id = tc.id
                GROUP BY tc.id, t.session_id, t.sequence_num, tc.tool_name, tc.tool_name_raw,
                         tc.sequence_num
                ORDER BY t.session_id, t.sequence_num, tc.sequence_num
                """
            ):
                skey = key_by_sid.get(int(sid))
                if skey is None:
                    continue
                tkey = f"{skey}#{int(tseq)}"
                tool_key = f"{tkey}:{tcseq}"
                if tools.write([tool_key, tname, traw or "", bool(is_err)]):
                    tool_key_by_id[int(tc_id)] = tool_key
                    invoked.write([tkey, tool_key])
                    stats.tools += 1

            # File accesses.
            for tc_id, path, access_type, language, sid in rel.query(
                "SELECT tool_call_id, file_path, access_type, language, session_id "
                "FROM copilot_file_access"
            ):
                if not path or int(sid) not in key_by_sid:
                    continue
                files.write([path, language or ""])
                tk = tool_key_by_id.get(int(tc_id)) if tc_id is not None else None
                if tk:
                    accessed.write([tk, path, access_type or ""])
                stats.files += 1

            # Errors.
            for err_id, tc_id, error_type, tool_name, sid in rel.query(
                "SELECT id, tool_call_id, error_type, tool_name, session_id FROM copilot_error"
            ):
                skey = key_by_sid.get(int(sid))
                if skey is None:
                    continue
                ekey = f"{skey}!err:{err_id}"
                if not errors.write([ekey, (error_type or "")[:_ERROR_TYPE_CHARS], tool_name or ""]):
                    continue
                tk = tool_key_by_id.get(int(tc_id)) if tc_id is not None else None
                if tk:
                    produced.write([tk, ekey])
                stats.errors += 1
        finally:
            for c in all_csvs:
                c.close()

        for c in all_csvs:
            if c.rows:
                gdb.copy_from(c.table, str(c.path))
                _log.info("graph: loaded %d rows into %s", c.rows, c.table)
    return stats


# ── incremental path (MERGE) ────────────────────────────────────────────


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

    # Turns, and every tool call of the session in ONE query (the old
    # per-turn SELECT was the N+1 that made a 90k-turn build a 90k
    # round-trip affair).
    turns = rel.query(
        "SELECT id, sequence_num, role, is_sidechain, slash_command "
        "FROM copilot_turn WHERE session_id = ? ORDER BY sequence_num",
        (sid,),
    )
    tools_by_turn: dict[int, list[tuple]] = {}
    for row in rel.query(
        """
        SELECT tc.turn_id, tc.id, tc.tool_name, tc.tool_name_raw, tc.sequence_num,
               MAX(CASE WHEN tr.is_error THEN 1 ELSE 0 END)
        FROM copilot_tool_call tc
        JOIN copilot_turn t ON t.id = tc.turn_id
        LEFT JOIN copilot_tool_result tr ON tr.tool_call_id = tc.id
        WHERE t.session_id = ?
        GROUP BY tc.turn_id, tc.id, tc.tool_name, tc.tool_name_raw, tc.sequence_num
        ORDER BY tc.turn_id, tc.sequence_num
        """,
        (sid,),
    ):
        tools_by_turn.setdefault(int(row[0]), []).append(tuple(row[1:]))
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
        for tc_id, tname, tname_raw, tseq, is_err in tools_by_turn.get(int(turn_db_id), []):
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
            {"k": error_key, "et": (error_type or "")[:_ERROR_TYPE_CHARS], "tn": tool_name or ""},
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
