# session_analytics.graph.query — parameterized Kùzu query helpers.
#
# Shared by the CLI (post-build counts), the MCP server (M4), and the FastAPI
# layer (M6) so query logic lives in one place. All return plain Python lists
# / dicts (JSON-ready), never Kùzu result objects.

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from .schema import GraphDatabase, load_node_ddl

# Mutating Cypher/DDL keywords. Matched as whole tokens (\b … \b) so a keyword
# is caught regardless of the following character — ``CREATE(n)``,
# ``SET\nn.x=1``, ``DETACH DELETE n`` all trip it — while property/alias names
# that merely contain a keyword (``n.createdAt``, ``set_value``) do not, since
# the trailing word char defeats the \b boundary. Fail-closed: any match is
# rejected before the query reaches Kùzu.
_MUTATING_RE = re.compile(
    r"\b(create|merge|set|delete|remove|detach|drop|copy|alter|install|load)\b",
    re.IGNORECASE,
)


def assert_readonly(cypher: str) -> None:
    """Raise ValueError if ``cypher`` contains any mutating statement.

    Pure (no DB access) so it is unit-testable without Kùzu and reused by the
    FastAPI query route and the MCP layer.
    """
    m = _MUTATING_RE.search(cypher or "")
    if m:
        raise ValueError(
            f"read-only query may not contain the mutating keyword {m.group(1).lower()!r}"
        )

# Node labels parsed from the DDL so node_counts stays in sync with schema.
def _node_labels() -> list[str]:
    labels = []
    for stmt in load_node_ddl():
        # "CREATE NODE TABLE IF NOT EXISTS Session(...)" → "Session"
        labels.append(stmt.split("EXISTS", 1)[1].strip().split("(", 1)[0].strip())
    return labels


def _rows(result) -> list[list]:
    out: list[list] = []
    while result.has_next():
        out.append(list(result.get_next()))
    return out


def node_counts(gdb: GraphDatabase) -> dict[str, int]:
    """Count of every node label (for verification + the dashboard)."""
    counts: dict[str, int] = {}
    for label in _node_labels():
        res = gdb.execute(f"MATCH (n:{label}) RETURN count(n)")
        rows = _rows(res)
        counts[label] = int(rows[0][0]) if rows else 0
    return counts


def tool_failure_stats(gdb: GraphDatabase, limit: int = 25) -> list[dict[str, Any]]:
    """Tools ranked by invocation + error count ("which tools fail most?")."""
    res = gdb.execute(
        """
        MATCH (i:ToolInvocation)
        RETURN i.tool_name AS tool,
               count(i) AS invocations,
               sum(CASE WHEN i.is_error = true THEN 1 ELSE 0 END) AS errors
        ORDER BY errors DESC, invocations DESC
        LIMIT $lim
        """,
        {"lim": int(limit)},
    )
    return [
        {"tool": r[0], "invocations": int(r[1]), "errors": int(r[2])}
        for r in _rows(res)
    ]


def expand_node(
    gdb: GraphDatabase, label: str, key_field: str, key_value: str
) -> dict[str, Any]:
    """Return a node's immediate neighbors (for the graph explorer's
    double-click expansion). ``label``/``key_field`` are validated against the
    schema to keep the (necessarily interpolated) label/field out of reach of
    injection."""
    valid_labels = set(_node_labels())
    if label not in valid_labels:
        raise ValueError(f"unknown node label: {label!r}")
    if not key_field.isidentifier():
        raise ValueError(f"invalid key field: {key_field!r}")
    res = gdb.execute(
        f"MATCH (n:{label} {{{key_field}: $v}})-[r]-(m) "
        f"RETURN label(m) AS lbl, r, m LIMIT 200",
        {"v": key_value},
    )
    neighbors = []
    for row in _rows(res):
        neighbors.append({"label": row[0], "node": _node_props(row[2])})
    return {"label": label, key_field: key_value, "neighbors": neighbors}


def run_readonly(gdb: GraphDatabase, cypher: str, params: Optional[Mapping[str, Any]] = None) -> list[dict]:
    """Run a read-only Cypher query (the Query IDE). Rejects mutating
    statements so the freeform editor cannot alter the embedded graph."""
    assert_readonly(cypher)
    res = gdb.execute(cypher, dict(params) if params else None)
    cols = res.get_column_names() if hasattr(res, "get_column_names") else []
    out = []
    for row in _rows(res):
        out.append({cols[i] if i < len(cols) else str(i): _jsonable(v) for i, v in enumerate(row)})
    return out


def _node_props(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _jsonable(v) for k, v in node.items()}
    return _jsonable(node)


def _jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return str(v)
