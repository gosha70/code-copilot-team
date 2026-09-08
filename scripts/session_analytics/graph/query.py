# session_analytics.graph.query — parameterized Kùzu query helpers.
#
# Shared by the CLI (post-build counts), the MCP server (M4), and the FastAPI
# layer (M6) so query logic lives in one place. All return plain Python lists
# / dicts (JSON-ready), never Kùzu result objects.

from __future__ import annotations

import re
from decimal import Decimal
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


def similar_edge_count(gdb: GraphDatabase) -> int:
    """How many SIMILAR_TO edges the store holds — the Analysis page's
    "Find similar sessions" done-check. 0 when the table is absent."""
    try:
        rows = _rows(gdb.execute("MATCH ()-[r:SIMILAR_TO]->() RETURN count(r)"))
    except Exception:  # noqa: BLE001 — an unbuilt graph has no such table
        return 0
    return int(rows[0][0]) if rows else 0


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
    if isinstance(v, Decimal):
        # Kùzu sums come back as Decimal; a chart needs a number, not "58".
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return str(v)


# ── the query catalogue (config_data/graph-queries.json) ──────────────

_CATALOGUE_FILE = "graph-queries.json"
RENDER_KINDS = ("table", "bar", "graph")


def catalogue() -> list[dict[str, Any]]:
    """The catalogue entries, minus the Cypher (the Studio shows the
    question and the parameters; the API runs the query by id)."""
    from ..config import load_map

    return [
        {k: v for k, v in q.items() if k != "cypher"}
        for q in load_map(_CATALOGUE_FILE)["queries"]
    ]


def catalogue_entry(query_id: str) -> Optional[dict[str, Any]]:
    from ..config import load_map

    for q in load_map(_CATALOGUE_FILE)["queries"]:
        if q["id"] == query_id:
            return q
    return None


def _node_id(struct: dict) -> str:
    i = struct.get("_id") or {}
    return f"{i.get('table')}:{i.get('offset')}"


def _key_of(node: dict) -> str:
    for k in ("session_key", "path", "name", "developer_id", "turn_key", "tool_key", "error_key"):
        if node.get(k) is not None:
            return str(node[k])
    return _node_id(node)


def elements_from_rows(rows: list[dict]) -> dict[str, list[dict]]:
    """Kùzu nodes and relationships in result rows → canvas elements.

    A node struct carries ``_id`` and ``_label``; a relationship struct
    carries ``_src``/``_dst`` (node ids) and ``_label``. Nodes are keyed
    by their primary key value so the same thing drawn twice is one
    bubble; an edge whose ends are not in the rows is dropped."""
    nodes: dict[str, dict] = {}
    by_internal: dict[str, str] = {}
    edges: list[dict] = []
    rels: list[dict] = []
    for row in rows:
        for v in row.values():
            if not isinstance(v, dict) or "_label" not in v:
                continue
            if "_src" in v and "_dst" in v:
                rels.append(v)
                continue
            key = _key_of(v)
            nid = f"{v['_label']}:{key}"
            by_internal[_node_id(v)] = nid
            if nid not in nodes:
                props = {k: x for k, x in v.items() if not k.startswith("_") and x is not None}
                nodes[nid] = {"id": nid, "label": v["_label"], "key": key, "props": _jsonable(props)}
    for r in rels:
        src = by_internal.get(f"{(r.get('_src') or {}).get('table')}:{(r.get('_src') or {}).get('offset')}")
        dst = by_internal.get(f"{(r.get('_dst') or {}).get('table')}:{(r.get('_dst') or {}).get('offset')}")
        if src and dst:
            props = {k: x for k, x in r.items() if not k.startswith("_") and x is not None}
            edges.append({"source": src, "target": dst, "rel": r["_label"], "props": _jsonable(props)})
    return {"nodes": list(nodes.values()), "edges": edges}


def run_catalogue(gdb: GraphDatabase, query_id: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Run one catalogue query with its parameters bound (never
    interpolated). Missing required parameters are a ValueError."""
    entry = catalogue_entry(query_id)
    if entry is None:
        raise ValueError(f"unknown catalogue query: {query_id!r}")
    bound: dict[str, Any] = {}
    for spec in entry.get("params", []):
        value = params.get(spec["name"], "")
        if spec.get("required") and value in ("", None):
            raise ValueError(f"{entry['name']}: '{spec.get('label', spec['name'])}' is required")
        bound[spec["name"]] = "" if value is None else str(value)
    res = gdb.execute(entry["cypher"], bound or None)
    cols = res.get_column_names() if hasattr(res, "get_column_names") else []
    raw = [{cols[i] if i < len(cols) else str(i): v for i, v in enumerate(row)} for row in _rows(res)]
    render = entry.get("render", "table")
    out: dict[str, Any] = {
        "id": query_id, "name": entry["name"], "question": entry.get("question", ""),
        "render": render, "columns": cols, "params": bound,
    }
    if render == "graph":
        out["elements"] = elements_from_rows(raw)
        out["rows"] = []
    else:
        out["rows"] = [{k: _jsonable(v) for k, v in r.items()} for r in raw]
    return out
