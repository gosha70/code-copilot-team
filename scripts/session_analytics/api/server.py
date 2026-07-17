# session_analytics.api.server — FastAPI app for the Studio.
#
# Binds 127.0.0.1 only (privacy AC). All reads go through here so query logic
# lives in one place (shared with the CLI + MCP server). Graph routes lazily
# touch Kùzu and return 503 if the optional package is absent.
#
# NOTE: this module deliberately does NOT use ``from __future__ import
# annotations``. FastAPI must see each route's Pydantic body model as a real
# class; stringified annotations are resolved against module globals (where
# the create_app-local models are invisible) and silently demoted to query
# params → 422.

import logging
from typing import Any, Optional

from ..config import load_config
from ..relational.db import Database
from . import dashboard
from ..mcp import resources as mcp_resources
from ..mcp import tools as mcp_tools

_log = logging.getLogger(__name__)


def create_app(dsn: str, kuzu_path: str = ""):
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    # Ensure adapters + judges are registered regardless of how the app was
    # constructed (idempotent — no-op if the CLI already registered).
    from .._register import register_all
    register_all()

    app = FastAPI(title="session-analytics Studio API", version="1.0")
    # The Studio dev server runs on localhost:3000; allow it (local only).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def db() -> Database:
        return Database.connect(dsn)

    # ── models ─────────────────────────────────────────────────────────
    class CypherQuery(BaseModel):
        cypher: str
        params: Optional[dict] = None

    class AnalyzeRequest(BaseModel):
        judge: Optional[str] = None
        workers: Optional[int] = None
        limit: Optional[int] = 50
        session_id: Optional[int] = None

    class TestConnRequest(BaseModel):
        dsn: Optional[str] = None

    class ConfigUpdate(BaseModel):
        values: dict

    # ── health + settings ──────────────────────────────────────────────
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    # ── config (reads + writes the SAME repo-root .env the CLI uses) ────
    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        from .. import constants as C
        from ..config import ENV_KEYS, SECRET_ENV_KEYS, is_initialized, parse_env_file
        from ..judge.registry import list_judge_ids

        env = parse_env_file()
        fields = []
        for key in ENV_KEYS:
            secret = key in SECRET_ENV_KEYS
            raw = env.get(key, "")
            fields.append({
                "key": key,
                "value": "" if secret else raw,   # never send secrets to the browser
                "secret": secret,
                "has_value": bool(raw),
            })
        cfg = load_config()
        _b, _m = cfg.judge.resolve(None)
        return {
            "configured": is_initialized(),
            "fields": fields,
            "judge_default": f"{_b}:{_m or '(default model)'}",
            "judge_backends": list_judge_ids(),
            "redaction_modes": list(C.REDACTION_MODES),
        }

    @app.put("/api/config")
    def put_config(req: ConfigUpdate) -> dict[str, Any]:
        from ..config import SECRET_ENV_KEYS, write_env_file

        # Preserve an existing secret if the field came back blank (the GET
        # masks it, so a blank means "unchanged", not "clear").
        updates = {
            k: v for k, v in req.values.items()
            if not (k in SECRET_ENV_KEYS and (v is None or v == ""))
        }
        write_env_file(updates)
        return {"ok": True}

    @app.get("/api/settings")
    def settings() -> dict[str, Any]:
        cfg = load_config()
        # Never leak the raw DSN; report dialect + redaction + sources only.
        dialect = "sqlite" if dsn.startswith("sqlite://") else "postgres"
        return {
            "dsn_dialect": dialect,
            "kuzu_path": kuzu_path or cfg.kuzu_path,
            "redaction_mode": cfg.redaction_mode,
            "sources": dict(cfg.sources),
            "judge": {"backend": cfg.judge.backend, "model": cfg.judge.model},
        }

    @app.post("/api/settings/test-connection")
    def test_connection(req: TestConnRequest) -> dict[str, Any]:
        from .db_test import probe

        return probe(req.dsn or dsn)

    @app.get("/api/settings/projects")
    def settings_projects() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.effective_redaction_by_project(conn)
        finally:
            conn.close()

    # ── dashboard ──────────────────────────────────────────────────────
    @app.get("/api/dashboard/kpis")
    def dashboard_kpis() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.kpis(conn)
        finally:
            conn.close()

    @app.get("/api/dashboard/labels")
    def dashboard_labels() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.label_distribution(conn)
        finally:
            conn.close()

    @app.get("/api/dashboard/cost")
    def dashboard_cost() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.cost_by_outcome(conn)
        finally:
            conn.close()

    @app.get("/api/dashboard/benchmark")
    def dashboard_benchmark() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.benchmark_correlation(conn)
        finally:
            conn.close()

    # ── sessions ───────────────────────────────────────────────────────
    @app.get("/api/sessions")
    def sessions(query: str = "", copilot: str = "", limit: int = 50) -> dict[str, Any]:
        conn = db()
        try:
            return {"sessions": mcp_tools.search_sessions(
                conn, query or None, copilot=copilot or None, limit=limit)}
        finally:
            conn.close()

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: int) -> dict[str, Any]:
        conn = db()
        try:
            detail = mcp_tools.get_session_details(conn, session_id)
            if "error" in detail:
                raise HTTPException(status_code=404, detail=detail["error"])
            return detail
        finally:
            conn.close()

    @app.get("/api/resources/recent-errors")
    def recent_errors() -> dict[str, Any]:
        conn = db()
        try:
            return mcp_resources.recent_errors(conn)
        finally:
            conn.close()

    # ── graph (lazy Kùzu) ──────────────────────────────────────────────
    def _graph():
        from ..graph.schema import GraphDatabase

        path = kuzu_path or load_config().kuzu_path
        return GraphDatabase.connect(path)

    @app.get("/api/graph/node-counts")
    def graph_node_counts() -> dict[str, Any]:
        from ..graph import query as gq

        try:
            g = _graph()
        except ImportError:
            raise HTTPException(status_code=503, detail="kuzu not installed")
        try:
            return {"node_counts": gq.node_counts(g), "tool_failures": gq.tool_failure_stats(g)}
        finally:
            g.close()

    @app.post("/api/graph/query")
    def graph_query(q: CypherQuery) -> dict[str, Any]:
        from ..graph import query as gq

        try:
            g = _graph()
        except ImportError:
            raise HTTPException(status_code=503, detail="kuzu not installed")
        try:
            return {"rows": gq.run_readonly(g, q.cypher, q.params)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            g.close()

    @app.get("/api/graph/expand")
    def graph_expand(label: str, key_field: str, key_value: str) -> dict[str, Any]:
        from ..graph import query as gq

        try:
            g = _graph()
        except ImportError:
            raise HTTPException(status_code=503, detail="kuzu not installed")
        try:
            return gq.expand_node(g, label, key_field, key_value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            g.close()

    # ── analyze (judge) ────────────────────────────────────────────────
    @app.post("/api/analyze")
    def analyze(req: AnalyzeRequest) -> dict[str, Any]:
        from ..judge.registry import UnknownJudgeError, get_judge
        from ..judge.rubric import load_rubric
        from ..judge.runner import run_default_by_copilot, run_judge

        cfg = load_config()
        rubric = load_rubric()
        workers = req.workers or cfg.judge.workers
        conn = db()
        try:
            if req.judge:
                family, model = (req.judge.split(":", 1) + [""])[:2]
                try:
                    judge = get_judge(family, model)
                except UnknownJudgeError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
                stats = run_judge(
                    conn, judge, rubric, workers=workers,
                    session_id=req.session_id, limit=req.limit,
                )
                return {"judge": f"{family}:{model or '(default)'}", **stats.as_dict()}
            return {"by_copilot": run_default_by_copilot(
                conn, rubric, cfg, workers=workers,
                session_id=req.session_id, limit=req.limit,
            )}
        finally:
            conn.close()

    return app
