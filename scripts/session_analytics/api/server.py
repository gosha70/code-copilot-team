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

from .. import archive as arch
from .. import constants as C
from ..config import load_config
from ..relational.db import (
    DIALECT_POSTGRES,
    DIALECT_SQLITE,
    Database,
    apply_ddl,
    is_sqlite_dsn,
)
from . import dashboard
from ..mcp import resources as mcp_resources
from ..mcp import tools as mcp_tools

_log = logging.getLogger(__name__)


def studio_origins(ui_port: int = C.DEFAULT_UI_PORT) -> tuple[str, ...]:
    """Browser origins the Studio can actually be served from (#103).

    Derived from the REAL ``--ui-port`` rather than hardcoded, so running the
    Studio on a non-default port is not silently broken by CORS and the
    Origin guard.
    """
    return tuple(f"http://{host}:{ui_port}" for host in C.STUDIO_ORIGIN_HOSTS)


def create_app(dsn: str, kuzu_path: str = "", ui_port: int = C.DEFAULT_UI_PORT):
    from typing import Awaitable, Callable

    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from starlette.responses import JSONResponse, Response

    # Ensure adapters + judges are registered regardless of how the app was
    # constructed (idempotent — no-op if the CLI already registered).
    from .._register import register_all
    register_all()

    app = FastAPI(title="session-analytics Studio API", version="1.0")
    allowed_origins = studio_origins(ui_port)
    # The Studio runs on localhost:<ui_port>; allow it (local only). The same
    # tuple feeds the Origin guard below, so the two cannot drift.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── request admission (#103) ───────────────────────────────────────
    # Starlette applies the LAST-added middleware outermost, so the Origin
    # guard is registered first and TrustedHost second: Host is validated
    # before anything else runs.
    @app.middleware("http")
    async def _origin_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Reject cross-origin state-changing requests from unknown origins.

        Allowed: the Studio's origins, and the API's OWN origin — the latter
        so FastAPI's built-in /docs (Swagger "Try it out") keeps working;
        browsers send Origin on same-origin non-GET requests too. Trusting
        own-origin is safe because the Host it is compared against has
        already passed TrustedHostMiddleware, and page script cannot forge
        either header.

        Absent Origin is ALLOWED by design: TestClient, curl and scripted
        callers never send one, and requiring it would break every
        non-browser client. The honest limit — this does not stop a local
        non-browser process, which already has code execution and is
        outside the threat model. The rebinding threat is browser-borne and
        is caught by the Host check.
        """
        if request.method not in C.ORIGIN_SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in allowed_origins:
                own_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
                if origin != own_origin:
                    # Constant message, API-standard JSON shape (matches
                    # HTTPException); never echo the offending value.
                    return JSONResponse(
                        {"detail": C.MSG_ORIGIN_NOT_ALLOWED}, status_code=403
                    )
        return await call_next(request)

    # Load-bearing control against DNS rebinding. Registered last → runs
    # first. Rejects with 400 before any handler (see constants for the
    # IPv6 caveat).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=C.API_ALLOWED_HOSTS)

    def _internal_error(exc: BaseException, where: str) -> "HTTPException":
        """THE one place an unexpected route failure becomes a response.

        A route that lets an exception escape hands the caller a stack
        trace (CodeQL py/stack-trace-exposure) — the same leak the probe's
        closed error set exists to prevent, where a driver message carried
        hosts, IPs and usernames. The exception is LOGGED in full; the
        response carries only a constant.

        Returned rather than raised so the call site reads
        ``raise _internal_error(...) from None`` — ``from None`` is what
        suppresses the chained traceback.
        """
        _log.exception("unhandled error in %s", where, exc_info=exc)
        return HTTPException(status_code=500, detail=C.MSG_INTERNAL_ERROR)

    def db() -> Database:
        return Database.connect(dsn)

    # Schema readiness (E9 outcomes, #92): every CLI command runs apply_ddl,
    # but the serve path opens bare per-request connections — an upgraded
    # (pre-#92) DB would 500 on endpoints touching the new benchmark_result
    # table. Apply the idempotent DDL once at app creation; a briefly
    # unreachable DB is logged, not fatal (matching the old startup behavior —
    # requests surface connection errors as before).
    try:
        _conn = db()
        try:
            apply_ddl(_conn)
        finally:
            _conn.close()
    except Exception as exc:  # noqa: BLE001
        _log.warning("startup apply_ddl skipped (db unreachable?): %s", exc)

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
        dialect = DIALECT_SQLITE if is_sqlite_dsn(dsn) else DIALECT_POSTGRES
        from ..routing_evidence import routing_evidence_settings

        return {
            "dsn_dialect": dialect,
            "kuzu_path": kuzu_path or cfg.kuzu_path,
            "redaction_mode": cfg.redaction_mode,
            "sources": dict(cfg.sources),
            "judge": {"backend": cfg.judge.backend, "model": cfg.judge.model},
            # routing-shadow (#261): SANITIZED — never the raw roots
            "routing_evidence": routing_evidence_settings(cfg),
        }

    @app.post("/api/settings/test-connection")
    def test_connection(req: TestConnRequest) -> dict[str, Any]:
        from .db_test import probe

        # Caller-supplied DSN and the configured ones stay SEPARATE so the
        # host allowlist can distinguish them (#101). BOTH the saved config
        # and the startup DSN count as configured: they diverge the moment
        # the operator saves a new one, and testing the just-saved database
        # must not require a restart (nor must a --dsn override stop being
        # testable).
        return probe(req.dsn or dsn, configured_dsns=(load_config().dsn, dsn))

    @app.get("/api/settings/projects")
    def settings_projects() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.effective_redaction_by_project(conn)
        finally:
            conn.close()

    # ── routing evidence (routing-shadow #261, shadow-mode only) ───────
    # Sets are addressed by opaque id; invalid sets surface with their
    # closed sanitized state; no payload carries a filesystem path.
    def _routing_entries(config=None):
        from ..routing_evidence import load_evidence_sets

        cfg = config if config is not None else load_config()
        return load_evidence_sets(cfg.routing_evidence_roots)

    def _routing_set_or_404(set_id: str, entries=None):
        from ..routing_evidence import find_evidence_set

        if entries is None:
            entries = _routing_entries()
        loaded = find_evidence_set(entries, set_id)
        if loaded is None:
            raise HTTPException(status_code=404,
                                detail="unknown evidence set")
        return loaded

    @app.get("/api/routing/evidence")
    def routing_evidence_index() -> dict[str, Any]:
        from ..routing_evidence import evidence_index

        return dict(evidence_index(_routing_entries()))

    @app.get("/api/routing/evidence/{set_id}")
    def routing_evidence_detail(set_id: str) -> dict[str, Any]:
        from ..routing_evidence import evidence_detail

        return dict(evidence_detail(_routing_set_or_404(set_id)))

    @app.get("/api/routing/evidence/{set_id}/recommendations")
    def routing_recommendations(set_id: str) -> dict[str, Any]:
        from ..routing_evidence import recommendations_payload

        return dict(recommendations_payload(_routing_set_or_404(set_id)))

    @app.get("/api/routing/evidence/{set_id}/artifact/{artifact}")
    def routing_artifact(set_id: str, artifact: str) -> dict[str, Any]:
        from ..routing_evidence import (
            EvidenceFileUnavailable,
            serve_artifact,
        )

        try:
            return dict(serve_artifact(_routing_set_or_404(set_id), artifact))
        except EvidenceFileUnavailable as exc:
            raise HTTPException(status_code=404, detail=exc.code) from None

    @app.get("/api/routing/evidence/{set_id}/evidence-file")
    def routing_evidence_file(set_id: str, ref: str) -> dict[str, Any]:
        from ..routing_evidence import (
            EvidenceFileUnavailable,
            serve_evidence_file,
        )

        try:
            return dict(serve_evidence_file(_routing_set_or_404(set_id), ref))
        except EvidenceFileUnavailable as exc:
            raise HTTPException(status_code=404, detail=exc.code) from None

    # ── routing calibration (routing-calibration #266, shadow-only) ────
    # Read-only over the SAME entries the E2 surface loads; no payload
    # carries the calibration root or the policy-source path, and no
    # gate result is ever acted upon here.
    # Each calibration route reads the corpus and the configuration
    # ONCE and derives everything from that one snapshot: a payload
    # composed from two independent reads could describe two different
    # states of the world.
    @app.get("/api/routing/calibration")
    def routing_calibration() -> dict[str, Any]:
        from ..routing_calibration import calibration_payload

        try:
            cfg = load_config()
            return dict(calibration_payload(_routing_entries(cfg), cfg))
        except HTTPException:
            raise                       # deliberate, already curated
        except Exception as exc:        # noqa: BLE001
            raise _internal_error(exc, "routing calibration") from None

    @app.get("/api/routing/calibration/evaluation")
    def routing_calibration_evaluation() -> dict[str, Any]:
        from ..routing_calibration import evaluation_payload

        try:
            cfg = load_config()
            return dict(evaluation_payload(_routing_entries(cfg), cfg))
        except HTTPException:
            raise                       # deliberate, already curated
        except Exception as exc:        # noqa: BLE001
            raise _internal_error(exc, "routing calibration evaluation") from None

    @app.get("/api/routing/evidence/{set_id}/knn")
    def routing_knn(set_id: str) -> dict[str, Any]:
        from ..routing_calibration import knn_payload

        # ONE corpus snapshot for both the existence check and the
        # derivation: two independent loads could straddle a change to
        # the roots, letting a set pass the 404 check and then return
        # an empty report — and it would pay the (complete) loading
        # cost twice.
        try:
            cfg = load_config()
            entries = _routing_entries(cfg)
            _routing_set_or_404(set_id, entries)
            return dict(knn_payload(entries, set_id, cfg))
        except HTTPException:
            raise                       # the 404 above must survive
        except Exception as exc:        # noqa: BLE001
            raise _internal_error(exc, "routing knn") from None

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

    @app.get("/api/dashboard/developers")
    def dashboard_developers() -> dict[str, Any]:
        # E1 (#65): per-developer rollup. Read-only, no ranking — see
        # dashboard.developer_aggregates for why it is ordered by id.
        conn = db()
        try:
            return dashboard.developer_aggregates(conn)
        finally:
            conn.close()

    @app.get("/api/dashboard/phase-process")
    def dashboard_phase_process() -> dict[str, Any]:
        # #301: DESCRIPTIVE metrics over the Pi runtime's recorded
        # workflow history. No score — E3 (#65) stays open, because the
        # recorded history cannot contain a violation (the runtime
        # refuses invalid transitions before persisting them).
        #
        # Reads the filesystem, not the DB: the history lives in each
        # project's .cct/pi-workflow.json and is not ingested.
        from .. import phase_process as pp
        from pathlib import Path

        try:
            cfg = load_config()
            base = cfg.source_root(C.COPILOT_PI)
            if base is None or not Path(base).exists():
                return {
                    "projects": [],
                    "projects_with_history": 0,
                    "retention_cap": C.PI_WORKFLOW_HISTORY_CAP,
                    "any_history_may_be_truncated": False,
                    "source_root_configured": base is not None,
                    "absence_note": (
                        "No Pi source root is configured or present, so no "
                        "workflow history could be read."
                    ),
                }
            report = dict(pp.report_for_roots(pp.find_project_roots(Path(base))))
            report["source_root_configured"] = True
            return report
        except Exception as exc:  # noqa: BLE001
            raise _internal_error(exc, "phase process") from None

    @app.get("/api/dashboard/cost")
    def dashboard_cost() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.cost_by_outcome(conn)
        finally:
            conn.close()

    @app.get("/api/search")
    def search(q: str = "", limit: int = C.SEARCH_DEFAULT_LIMIT) -> dict[str, Any]:
        # E10 Slice B (#65): tokenized, ranked search over archived
        # (redacted) trace text; `limit` is a top-N. Degrades to Slice A
        # substring ordering when the store has no usable index.
        if not q.strip():
            raise HTTPException(status_code=400, detail="empty search query")
        conn = db()
        try:
            return {"query": q, "results": arch.search_traces(conn, q, limit=limit)}
        finally:
            conn.close()

    @app.get("/api/dashboard/benchmark")
    def dashboard_benchmark() -> dict[str, Any]:
        conn = db()
        try:
            # E9: correlation coverage (#91) + by-result outcomes (#92) in
            # one payload; both stay independently unit-testable pure fns.
            return {
                **dashboard.benchmark_correlation(conn),
                **dashboard.benchmark_outcomes(conn),
            }
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

    # ── similarity + clustering, READ-ONLY (#293 FR-B) ─────────────────
    # Deliberately NOT reusing `_graph()` above: that opens with
    # `GraphDatabase.connect`, which CREATES the store. These endpoints
    # inherit #289's discipline — an absent path is refused before any
    # open, the open itself is non-creating, and a path that disappears
    # between the two is refused rather than repaired.

    def _prerequisite(detail: dict) -> "HTTPException":
        """A prerequisite answer, in the SAME shape the MCP tools use.

        503 rather than 200: the service cannot answer yet. The body is
        the tool's own {error, prerequisite, guidance} dict, ANNOTATED
        with a `state` discriminator, so a client can tell absent from
        unopenable from unbuilt (#293 FR-C) without parsing prose.

        Annotating is not reshaping. D2 forbids pruning or renaming what
        the reader produced; adding what this endpoint authoritatively
        knows is the opposite — each raise site below knows exactly
        which state it is in, and encoding that only into English would
        force the client to reconstruct it with a substring match.
        """
        return HTTPException(status_code=503, detail=detail)

    @app.get("/api/clusters")
    def clusters() -> dict[str, Any]:
        """Clusters over the stored SIMILAR_TO snapshot (#289 FR-E).

        Wraps `run_clusters` and returns its report VERBATIM — the
        limitations block, both provenance labels and `basis` included.
        Nothing is reshaped, renamed or pruned here: FR-E requires those
        displayed, and a reshaping layer is where they get lost.
        """
        from pathlib import Path as _Path

        from ..embedding.cluster_reader import KuzuGraphSnapshot, run_clusters
        from ..embedding.similar_runner import GraphNotReadyError
        from ..graph.schema import GraphDatabase

        path = kuzu_path or load_config().kuzu_path
        if not path or not _Path(path).exists():
            raise _prerequisite({
                "error": f"graph database absent at {path or '(unset)'}",
                "prerequisite": "graph",
                "state": "absent",
                "guidance": "run './scripts/session-analytics graph' first",
            })
        try:
            gdb = GraphDatabase.connect_read_only(path)
        except ImportError:
            raise HTTPException(status_code=503, detail="kuzu not installed")
        except RuntimeError:
            # the exists() check alone is a TOCTOU; refuse, never repair
            raise _prerequisite({
                "error": f"graph database absent or unopenable at {path}",
                "prerequisite": "graph",
                "state": "unopenable",
                "guidance": "run './scripts/session-analytics graph' first",
            })
        try:
            report = run_clusters(KuzuGraphSnapshot(gdb))
        except GraphNotReadyError:
            raise _prerequisite({
                "error": "graph store holds no Session table",
                "prerequisite": "graph",
                "state": "unbuilt",
                "guidance": "run './scripts/session-analytics graph' first",
            })
        finally:
            gdb.close()
        # Zero clusters is a RESULT, not an error (#289 FR-E): 200.
        return report.as_dict()

    @app.get("/api/sessions/{session_id}/similar")
    def session_similar(
        session_id: int,
        limit: int = Query(10, ge=1, le=C.SIMILAR_MAX_LIMIT),
    ) -> dict[str, Any]:
        """Stored neighbours for one session (#287 FR-F), verbatim.

        `limit` is range-guarded HERE, at the endpoint signature, rather
        than inside `similar_sessions`. FastAPI already rejects a
        non-integer from the annotation (422); what was unguarded was
        RANGE — `similar_sessions` has no range check, so -1, 0 and 1e9
        all reached the query. Constraining at the signature guards this
        new public surface without altering an existing tool contract,
        and FastAPI answers 422, the right code for client input error.
        """
        from ..mcp import tools as mcp_tools

        path = kuzu_path or load_config().kuzu_path
        conn = db()
        try:
            result = mcp_tools.similar_sessions(
                conn, path, session_id, limit=limit)
        finally:
            conn.close()
        if "prerequisite" in result:
            raise _prerequisite(result)
        # Map the KNOWN error explicitly. `"error" in result` is not a
        # synonym for "not found": it is the tool's error CHANNEL, and
        # collapsing every condition it can carry into 404 is the mirror
        # of the FR-C failure this slice exists to prevent — N
        # conditions, one code. Anything unrecognised is a 500, which is
        # honest, rather than a confident wrong answer.
        if "error" in result:
            if "not found" in str(result.get("error", "")):
                raise HTTPException(status_code=404, detail=result)
            raise HTTPException(status_code=500, detail=result)
        return result

    return app
