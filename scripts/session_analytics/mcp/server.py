# session_analytics.mcp.server — FastMCP adapter over tools.py / resources.py.
#
# Lazily imports the `mcp` SDK so importing this module (and the unit suite)
# does not require it. Each tool/resource call opens a short-lived DB
# connection against the configured DSN — read-only, local.

from __future__ import annotations

from typing import Any, Optional

from ..config import load_config
from .. import constants as C
from ..relational.db import Database
from . import resources, tools

SERVER_NAME = "session-analytics"


def build_server(dsn: str, kuzu_path: str = ""):
    """Construct (but do not run) a FastMCP server bound to ``dsn``.

    ``kuzu_path`` is the CALLER'S resolved graph path (#287 T3): the
    ``similar_sessions`` and ``session_clusters`` tools read stored
    SIMILAR_TO edges from it, non-creating — an empty/absent path
    yields a prerequisite result, never a freshly created store.
    """
    from mcp.server.fastmcp import FastMCP  # lazy: only needed to serve

    server = FastMCP(SERVER_NAME)

    def _db() -> Database:
        return Database.connect(dsn)

    # ── tools ──────────────────────────────────────────────────────────
    @server.tool()
    def search_sessions(
        query: str = "", copilot: str = "", date_from: str = "",
        date_to: str = "", limit: int = 20, tag: str = "", developer: str = "",
        model: str = "", tool: str = "", min_cost: Optional[float] = None,
        max_cost: Optional[float] = None, label: str = "", harness: str = "",
    ) -> list[dict[str, Any]]:
        """Find sessions by keyword/workspace + optional filters (#371 A2):
        copilot; a date range (date_to names the whole day); tag (favorite,
        todo, analyzed); developer; model; tool (at least one call to it);
        min/max PRICED cost (a session with no priced turn matches neither);
        label (a packaged-rubric boolean true on at least one turn);
        harness (#371 A4b) as `mixed`, `unstamped`, `absent:<dimension>`
        or `<dimension>:<value>`."""
        db = _db()
        try:
            return tools.search_sessions(
                db, query or None, copilot=copilot or None,
                date_from=date_from or None, date_to=date_to or None, limit=limit,
                tag=tag or None, developer=developer or None, model=model or None,
                tool=tool or None, min_cost=min_cost, max_cost=max_cost, label=label or None,
                harness=harness or None,
            )
        finally:
            db.close()

    @server.tool()
    def list_expectations(feature_id: str = "", attempt_id: str = "", limit: int = 20) -> dict[str, Any]:
        """#371 A5: what each stored auto-build run was required to achieve
        (its spec's FRs, frozen at admission) and how it came out. Each
        expectation is met / not_met / unknown, or unevaluated when the run
        left no recoverable consolidated result. `rate` is met/evaluated
        and is null — never 0 — when nothing was evaluated."""
        from .. import expectations as exp

        db = _db()
        try:
            return {
                "runs": exp.list_runs(
                    db, feature_id=feature_id or None,
                    attempt_id=attempt_id or None, limit=max(1, min(int(limit), 200)),
                )
            }
        finally:
            db.close()

    @server.tool()
    def compare_harness_versions(by: str = "") -> dict[str, Any]:
        """#371 A4b: sessions grouped by one dimension of the harness they
        ran under (instructions_digest, cct_sha, cct_version, cli_version,
        providers_digest), with turns, errors, priced cost and the packaged
        rubric's quality and rates per group. `mixed`, `absent` and
        `unstamped` are named rows; judge figures are null, not zero,
        without labels."""
        from ..api import dashboard
        from ..config import load_config

        db = _db()
        try:
            return dashboard.harness_aggregates(
                db, noise=load_config().noise, by=by or C.HARNESS_DIMENSIONS[0]
            )
        finally:
            db.close()

    @server.tool()
    def get_session_details(session_id: int) -> dict[str, Any]:
        """Full turn/tool/error breakdown for one session."""
        db = _db()
        try:
            return tools.get_session_details(db, session_id)
        finally:
            db.close()

    @server.tool()
    def analyze_patterns(
        workspace: str = "", tool: str = "", error_type: str = ""
    ) -> dict[str, Any]:
        """Aggregate tool-usage + error patterns across sessions."""
        db = _db()
        try:
            return tools.analyze_patterns(
                db, workspace=workspace or None, tool=tool or None,
                error_type=error_type or None,
            )
        finally:
            db.close()

    @server.tool()
    def compare_approaches(task_description: str, limit: int = 10) -> list[dict[str, Any]]:
        """Find similar past sessions and report their KPI outcomes."""
        db = _db()
        try:
            return tools.compare_approaches(db, task_description, limit=limit)
        finally:
            db.close()

    @server.tool()
    def similar_sessions(session_id: int, limit: int = 10) -> dict[str, Any]:
        """Embedding-based neighbors for one session, from stored
        SIMILAR_TO edges (basis: "embedding"; snapshot of the last
        completed `similar` pass)."""
        db = _db()
        try:
            return tools.similar_sessions(
                db, kuzu_path, session_id, limit=limit)
        finally:
            db.close()

    @server.tool()
    def session_clusters(
        session_id: Optional[int] = None, limit: int = 10,
    ) -> dict[str, Any]:
        """Clusters of mutually-reachable similar sessions from stored
        SIMILAR_TO edges (basis: "embedding"). With session_id: that
        session's cluster, or an honest "unclustered". Without it:
        clusters largest first. Clusters are UNNAMED and transitive —
        membership does not assert all-pairs similarity."""
        db = _db()
        try:
            return tools.session_clusters(
                db, kuzu_path, session_id, limit=limit)
        finally:
            db.close()

    # ── resources ──────────────────────────────────────────────────────
    @server.resource("history://recent-errors")
    def recent_errors() -> dict[str, Any]:
        db = _db()
        try:
            return resources.recent_errors(db)
        finally:
            db.close()

    @server.resource("history://tool-stats")
    def tool_stats() -> dict[str, Any]:
        db = _db()
        try:
            return resources.tool_stats(db)
        finally:
            db.close()

    @server.resource("history://session-summary")
    def session_summary() -> dict[str, Any]:
        db = _db()
        try:
            return resources.session_summary(db)
        finally:
            db.close()

    return server


def run(dsn: str = "", kuzu_path: str = "") -> None:
    """Run the MCP server over stdio."""
    cfg = None
    resolved = dsn
    resolved_kuzu = kuzu_path
    if not resolved or not resolved_kuzu:
        cfg = load_config()
        resolved = resolved or cfg.dsn
        resolved_kuzu = resolved_kuzu or cfg.kuzu_path
    if not resolved:
        raise ValueError("no DSN configured for the MCP server (see --dsn).")
    server = build_server(resolved, resolved_kuzu)
    server.run()  # FastMCP defaults to stdio transport
