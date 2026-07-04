# session_analytics.graph.schema — Kùzu connection wrapper + DDL apply.
#
# Kùzu is an embedded, single-writer graph DB (Python-bound). The wrapper
# lazily imports ``kuzu`` so the rest of the package — and the SQLite-backed
# unit suite — need not have it installed. The node/rel table DDL lives in
# config_data/ddl/kuzu/*.cypher (one statement per line).

from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Optional

_log = logging.getLogger(__name__)

_DDL_PACKAGE = "session_analytics.config_data"
_NODES_DDL = "ddl/kuzu/nodes.cypher"
_RELS_DDL = "ddl/kuzu/rels.cypher"


class GraphDatabase:
    """Thin wrapper over a Kùzu Database + Connection."""

    def __init__(self, db: Any, conn: Any, path: str) -> None:
        self._db = db
        self.conn = conn
        self.path = path

    @classmethod
    def connect(cls, path: str) -> "GraphDatabase":
        import kuzu  # lazy: only needed for real graph ops

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        db = kuzu.Database(path)
        conn = kuzu.Connection(db)
        return cls(db, conn, path)

    def execute(self, statement: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        if params:
            return self.conn.execute(statement, parameters=dict(params))
        return self.conn.execute(statement)

    def close(self) -> None:
        # Kùzu releases resources on GC; explicit drop of references helps
        # release the single-writer lock promptly.
        self.conn = None
        self._db = None


def _statements(text: str) -> list[str]:
    return [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("//")
    ]


def load_node_ddl() -> list[str]:
    text = resources.files(_DDL_PACKAGE).joinpath(_NODES_DDL).read_text(encoding="utf-8")
    return _statements(text)


def load_rel_ddl() -> list[str]:
    text = resources.files(_DDL_PACKAGE).joinpath(_RELS_DDL).read_text(encoding="utf-8")
    return _statements(text)


# Table names in dependency order (nodes first, then rels). Used to DROP in
# reverse order on --rebuild. Parsed from the DDL so they stay in sync.
def _table_name(stmt: str) -> str:
    # "CREATE NODE TABLE IF NOT EXISTS Session(...)" → "Session"
    parts = stmt.replace("IF NOT EXISTS", "").split("TABLE", 1)[1].strip()
    return parts.split("(", 1)[0].strip()


def apply_schema(gdb: GraphDatabase) -> None:
    """Create all node + rel tables if absent. Idempotent."""
    for stmt in load_node_ddl():
        gdb.execute(stmt)
    for stmt in load_rel_ddl():
        gdb.execute(stmt)


def reset_schema(gdb: GraphDatabase) -> None:
    """Drop all rel tables then node tables, then recreate. For --rebuild."""
    for stmt in reversed(load_rel_ddl()):
        gdb.execute(f"DROP TABLE IF EXISTS {_table_name(stmt)}")
    for stmt in reversed(load_node_ddl()):
        gdb.execute(f"DROP TABLE IF EXISTS {_table_name(stmt)}")
    apply_schema(gdb)
