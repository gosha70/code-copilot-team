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

import json
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


#: Ollama listing calls: /api/tags is instant, /api/show can take
#: seconds while Ollama loads a model into memory.
_OLLAMA_LIST_TIMEOUT = 5
#: Capabilities per (base url, model name, digest). A digest names an
#: immutable model, so its capabilities never change; the cache lives
#: as long as the process.
_ollama_caps_cache: dict[tuple[str, str, str], Optional[list[str]]] = {}


def _ollama_capabilities(
    base: str, served: list[tuple[str, str]],
) -> dict[str, Optional[list[str]]]:
    """``{name: capabilities}`` for the served models, from ``/api/show``
    — concurrently, cached per digest, and None (unknown) when a model's
    show fails or carries no capabilities field."""
    import json as _json
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    def show(name: str) -> Optional[list[str]]:
        req = urllib.request.Request(
            f"{base}/api/show",
            data=_json.dumps({"model": name}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_OLLAMA_LIST_TIMEOUT) as resp:
                shown = _json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — one model's show failing must not empty the list
            return None
        caps = shown.get("capabilities") if isinstance(shown, dict) else None
        return caps if isinstance(caps, list) else None

    result: dict[str, Optional[list[str]]] = {}
    pending = [(n, d) for n, d in served if (base, n, d) not in _ollama_caps_cache or not d]
    for n, d in served:
        if (base, n, d) in _ollama_caps_cache and d:
            result[n] = _ollama_caps_cache[(base, n, d)]
    if pending:
        with ThreadPoolExecutor(max_workers=min(8, len(pending))) as pool:
            for (n, d), caps in zip(pending, pool.map(lambda nd: show(nd[0]), pending)):
                result[n] = caps
                # Only a KNOWN answer is worth remembering: an unknown
                # (timeout, old server) is asked again next time.
                if d and caps is not None:
                    _ollama_caps_cache[(base, n, d)] = caps
    return result


def create_app(dsn: str, kuzu_path: str = "", ui_port: int = C.DEFAULT_UI_PORT):
    from typing import Awaitable, Callable

    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    from starlette.responses import JSONResponse, Response, StreamingResponse

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
        # #313: a named run coexists with the packaged one; only_labelled_by
        # (rubric:<name> | human:<labeler>) makes it cover the same turns.
        rubric_name: Optional[str] = None
        only_labelled_by: Optional[str] = None

    class SessionAnalysisRequest(BaseModel):
        judge: Optional[str] = None   # "family:model"; default = configured judge
        force: bool = False           # re-run even when a parsed result exists

    class TestConnRequest(BaseModel):
        dsn: Optional[str] = None

    class AskRequest(BaseModel):
        question: str
        # Prior exchanges, client-held: [{question, answer}]. No server
        # state — a reload starts a fresh conversation.
        history: list[dict[str, str]] = []

    class LoadSelection(BaseModel):
        """Which discovered sessions "Load sessions" reads. Every field
        blank = everything, as before. ``since`` is YYYY-MM-DD or ISO."""
        copilots: Optional[list[str]] = None
        since: Optional[str] = None
        limit: Optional[int] = None
        session_ids: Optional[list[str]] = None

    class JudgeOptions(BaseModel):
        """How the judge step runs. ``judge`` blank = the judge configured
        in Settings (the normal case); set it only for a one-off run,
        e.g. to compare two judges over the same turns (#313)."""
        judge: Optional[str] = None
        workers: Optional[int] = None
        limit: Optional[int] = 50
        rubric_name: Optional[str] = None
        only_labelled_by: Optional[str] = None

    class PipelineRun(BaseModel):
        """Per-step options for run/<step> and run-all; both optional.
        ``steps`` on run-all runs that ordered subset (the Similar tab
        runs embed + similar)."""
        load: Optional[LoadSelection] = None
        judge: Optional[JudgeOptions] = None
        steps: Optional[list[str]] = None

    class ConfigUpdate(BaseModel):
        values: dict

    class TagUpdate(BaseModel):
        """One hand-set tag on one session: on or off."""
        on: bool

    # ── health + settings ──────────────────────────────────────────────
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok"}

    # ── config (reads + writes the SAME repo-root .env the CLI uses) ────
    @app.get("/api/config")
    def get_config() -> dict[str, Any]:
        from .. import constants as C
        from ..config import (
            ENV_DB,
            ENV_DSN_LEGACY,
            ENV_KEYS,
            SECRET_ENV_KEYS,
            is_initialized,
            parse_env_file,
        )
        from ..embedding.registry import list_embedding_ids
        from ..judge.registry import list_judge_ids

        env = parse_env_file()
        # A .env written before the rename carries CCT_SA_DSN; show it
        # under the new name (Save writes the new name and drops the old).
        legacy_db_key = ENV_DSN_LEGACY in env and ENV_DB not in env
        if legacy_db_key:
            env[ENV_DB] = env[ENV_DSN_LEGACY]
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

        # READINESS IS A CAPABILITY, NOT A FILE. `is_initialized()` only
        # asks whether a .env exists, so a perfectly working install
        # started with `--db` on the command line was reported as "not
        # configured" while the very same page showed a healthy store
        # and 132 sessions. Report what the app can actually DO, and let
        # the UI say precisely which part is missing.
        store_ok, sessions = False, 0
        try:
            _probe = db()
            try:
                apply_ddl(_probe)
                row = _probe.query_one("SELECT COUNT(*) FROM copilot_session")
                sessions = int((row or (0,))[0] or 0)
                store_ok = True
            finally:
                _probe.close()
        except Exception:  # noqa: BLE001 — unreachable store == not ready
            store_ok = False

        return {
            # THE STORE THIS APP IS ACTUALLY USING, which is not always
            # what .env says: a --db on the command line overrides it,
            # and the Settings page was showing the .env value beside a
            # session count read from the other store. A settings screen
            # that cannot be reconciled with the dashboard is worse than
            # no settings screen.
            "effective_dsn": dsn,
            "dsn_overridden": bool(dsn and dsn != (load_config().dsn or "")),
            # The .env still uses the pre-rename key CCT_SA_DSN; the page
            # says so and the next Save rewrites it as CCT_SA_DB.
            "legacy_db_key": legacy_db_key,
            # True when the tool can actually be used: a reachable store
            # holding data. `.env` is reported separately below because
            # it is a convenience (it saves repeating --db), not a
            # precondition.
            "configured": store_ok and sessions > 0,
            "readiness": {
                "store_reachable": store_ok,
                "sessions": sessions,
                "env_file_present": is_initialized(),
            },
            "fields": fields,
            "judge_default": f"{_b}:{_m or '(default model)'}",
            "judge_backends": list_judge_ids(),
            "embedding_backends": list_embedding_ids(),
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

    @app.get("/api/judge/models")
    def judge_models() -> dict[str, Any]:
        """The models the CONFIGURED judge backend actually serves.

        Settings offers this list on its Model field. A name typed from
        memory that the server does not have 404s on every call: 50
        turns written as backend_error and "labelled 50 turns" on the
        page. Ollama answers at /api/tags; an OpenAI-compatible server
        (vLLM, LM Studio, a DGX box) at <base_url>/models. The
        claude-code backend has no list to read. The URLs are the SAVED
        configuration — save first, then the list follows the new URL.
        """
        import json as _json
        import urllib.request

        cfg = load_config()
        conf = _configured_judge(cfg)
        backend = conf["backend"]
        out: dict[str, Any] = {"configured": conf, "backend": backend, "models": [], "reachable": False, "url": ""}
        if backend == "ollama":
            base = (cfg.judge.ollama_url or "http://localhost:11434").rstrip("/")
            list_url, pick = f"{base}/api/tags", lambda d: [m.get("name") for m in d.get("models", []) if isinstance(m, dict)]
        elif backend == "openai":
            from ..judge.openai_judge import normalize_base_url

            base = normalize_base_url(cfg.judge.base_url)
            if not base:
                out["error"] = "no base URL configured"
                return out
            list_url, pick = f"{base}/models", lambda d: [m.get("id") for m in d.get("data", []) if isinstance(m, dict)]
        else:
            # claude-code and any other backend: no catalogue to read.
            return out
        out["url"] = base
        req = urllib.request.Request(list_url)
        if backend == "openai" and cfg.judge.api_key:
            req.add_header("Authorization", f"Bearer {cfg.judge.api_key}")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            out.update({"reachable": True, "models": sorted(n for n in pick(data) if n)})
        except Exception as exc:  # noqa: BLE001 — unreachable is an ANSWER
            # The class name says what kind of failure it was (refused,
            # timed out, bad body); the message text is logged, not
            # returned — it can carry resolved hosts and errno detail
            # (CodeQL py/stack-trace-exposure).
            _log.info("%s model list unavailable at %s: %s", backend, base, exc)
            out["error"] = type(exc).__name__
            out["list_url"] = list_url
        return out

    @app.post("/api/judge/test")
    def judge_test() -> dict[str, Any]:
        """One small completion with the SAVED judge, so a person can see
        "answered in 1.2 s" or the exact refusal before running a batch.
        The answer text is returned; the failure reason is the backend's
        own (a wrong model name, a wrong URL, thinking that ate the
        budget) — never a bare status code."""
        import time as _time

        from ..judge.contracts import JudgeTransportError
        from ..judge.registry import UnknownJudgeError, get_judge

        cfg = load_config()
        conf = _configured_judge(cfg)
        backend, model = cfg.judge.resolve(None)
        started = _time.time()
        try:
            judge = get_judge(backend, model)
            # The judges force JSON output (that is what the rubric needs),
            # so the probe asks for JSON too.
            answer = judge.complete('Reply with exactly this JSON and nothing else: {"ok": true}', timeout=60)
        except (UnknownJudgeError, ValueError) as exc:
            return {"ok": False, "judge": conf["spec"], "error": str(exc)}
        except JudgeTransportError as exc:
            return {"ok": False, "judge": conf["spec"], "error": str(exc),
                    "seconds": round(_time.time() - started, 1)}
        except Exception as exc:  # noqa: BLE001 — the reason is the answer here
            _log.warning("judge test failed: %s", exc)
            return {"ok": False, "judge": conf["spec"], "error": f"{type(exc).__name__}: {exc}"[:300],
                    "seconds": round(_time.time() - started, 1)}
        return {
            "ok": True, "judge": conf["spec"], "seconds": round(_time.time() - started, 1),
            "answer": (answer or "").strip()[:200],
        }

    def _configured_judge(cfg) -> dict[str, Any]:
        """The judge a run with no explicit choice will use, and where
        that came from — so the Analysis page can show "Settings:
        ollama:qwen3.6:27b" rather than a label that guesses."""
        from ..judge.registry import get_judge

        def _spec(backend: str, model: str) -> str:
            # A blank model means the backend's own default; name it.
            if not model:
                try:
                    model = getattr(get_judge(backend, ""), "_model", "") or ""
                except Exception:  # noqa: BLE001 — an unknown backend still gets reported
                    model = ""
            return f"{backend}:{model}" if model else backend

        j = cfg.judge
        if j.override is not None:
            backend, model = j.override
            return {"spec": _spec(backend, model), "backend": backend, "model": model,
                    "source": "settings", "by_copilot": {}}
        backend, model = j.default
        return {
            "spec": _spec(backend, model), "backend": backend, "model": model,
            "source": "packaged default",
            "by_copilot": {c: _spec(b, m) for c, (b, m) in j.by_copilot.items()
                           if (b, m) != (backend, model)},
        }

    # ── pipeline (Analysis tab: run the steps, not just list them) ─────
    @app.get("/api/pipeline/status")
    def pipeline_status() -> dict[str, Any]:
        from .. import pipeline_jobs as pj

        # Use the DSN THIS APP WAS BUILT WITH, not a fresh load_config():
        # create_app already receives the resolved value, so re-reading
        # config here silently ignored a --db override and reported on a
        # different store than every other endpoint.
        return pj.status(dsn, kuzu_path or load_config().kuzu_path)

    def _load_selection(sel: Optional["LoadSelection"]):
        """Request → IngestSelection; a bad ``since`` is a 400, not a
        failed background job the user reads about later."""
        from ..ingest.selection import IngestSelection, parse_since

        if sel is None:
            return None, IngestSelection()
        try:
            since = parse_since(sel.since) if sel.since else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return sel.copilots or None, IngestSelection(
            since=since,
            limit=sel.limit if sel.limit and sel.limit > 0 else None,
            session_ids=frozenset(sel.session_ids or ()),
        )

    @app.get("/api/pipeline/sessions")
    def pipeline_sessions(
        copilot: Optional[str] = None, since: Optional[str] = None, limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """What "Load sessions" would read under these filters — newest
        first, with sizes and whether each is already loaded — so the
        user picks BEFORE gigabytes of transcripts are parsed."""
        from .._register import register_all
        from ..ingest.pipeline import discover_sessions

        register_all()
        copilots, selection = _load_selection(
            LoadSelection(copilots=[copilot] if copilot else None, since=since, limit=limit)
        )
        try:
            return discover_sessions(dsn=dsn, copilots=copilots, selection=selection)
        except Exception as exc:  # noqa: BLE001 — an unreadable root or store is a 503, not a crash
            _log.warning("discover sessions failed: %s", exc)
            raise HTTPException(status_code=503, detail=f"could not list sessions: {exc}") from None

    def _pipeline_runners(opts: Optional["PipelineRun"] = None):
        """One definition of what each step DOES, shared by both the
        single-step and run-all endpoints, so they cannot drift."""
        from .. import pipeline_jobs as pj
        from ..judge.registry import UnknownJudgeError, get_judge

        store = dsn
        graph_path = kuzu_path or load_config().kuzu_path
        copilots, selection = _load_selection(opts.load if opts else None)
        judge_opts = (opts.judge if opts else None) or JudgeOptions()
        # A judge that does not exist is a 400 NOW, not a failed job later.
        if judge_opts.judge:
            family, model = (judge_opts.judge.split(":", 1) + [""])[:2]
            try:
                get_judge(family, model)
            except UnknownJudgeError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None

        def _judge() -> str:
            from ..judge.runner import JudgeStats, run_default_by_copilot, run_judge
            from ..judge.rubric import load_rubric
            from ..relational.db import Database as _DB

            cfg = load_config()
            rubric = load_rubric(judge_opts.rubric_name)
            stats = JudgeStats()

            def _progress(st: JudgeStats) -> None:
                pj.set_progress(pj.STEP_JUDGE, st.as_dict())

            conn = _DB.connect(store)
            try:
                kw = dict(
                    workers=judge_opts.workers or cfg.judge.workers, limit=judge_opts.limit,
                    only_labelled_by=judge_opts.only_labelled_by, progress=_progress, stats=stats,
                )
                if judge_opts.judge:
                    family, model = (judge_opts.judge.split(":", 1) + [""])[:2]
                    run_judge(conn, get_judge(family, model), rubric, **kw)
                else:
                    run_default_by_copilot(conn, rubric, cfg, **kw)
            finally:
                conn.close()
            # The message is the verdict a person reads after the run:
            # what was labelled, what failed, and the last reason why.
            if stats.total == 0:
                return "nothing to judge: every turn with text is already labelled"
            msg = f"labelled {stats.parse_ok} of {stats.total} turns with {stats.judge or 'the configured judge'}"
            if stats.parse_failed:
                msg += f"; {stats.parse_failed} failed"
                if stats.last_error:
                    msg += f" (last: {stats.last_error})"
            return msg

        def _ingest() -> str:
            from .._register import register_all
            from ..ingest.pipeline import ingest

            register_all()
            st = ingest(dsn=store, copilots=copilots, full=False, selection=selection)
            msg = f"ingested {st.sessions_ingested} sessions"
            if st.sessions_skipped:
                msg += f", {st.sessions_skipped} already up to date"
            if st.sessions_not_selected:
                msg += f", {st.sessions_not_selected} outside the selection"
            return msg

        def _correlate() -> str:
            from pathlib import Path as _P

            from .. import correlate as cor
            from ..relational.db import Database as _DB

            root = pj.benchmark_runs_root()
            if not root["configured"]:
                # Skipped BY CONFIGURATION, not failed: most stores have
                # no benchmark runs, and Run all must not stop for that.
                raise pj.StepSkipped("no benchmark runs root configured (Settings → Benchmarks)")
            stats = cor.CorrelationStats()
            rel = _DB.connect(store)
            try:
                # The live counters are the step's progress while it
                # scans, and the final counters its outcome — the same
                # numbers the CLI prints.
                cor.run(
                    rel, _P(root["path"]), stats=stats,
                    progress=lambda st: pj.set_progress(pj.STEP_CORRELATE, st.as_dict()),
                )
            finally:
                pj.set_progress(pj.STEP_CORRELATE, stats.as_dict())
                rel.close()
            return (
                f"scanned {stats.scanned} run records: linked {stats.linked} sessions, "
                f"{stats.unmatched} unmatched, {stats.scores_ingested} outcomes stored"
                + (f", {stats.skipped_run_records} unreadable" if stats.skipped_run_records else "")
            )

        def _graph() -> str:
            from ..graph.builder import build
            from ..relational.db import Database as _DB

            # The same sessions every other page shows: noise (probe
            # runs, two-turn tests) stays out, or the graph's answers
            # disagree with the Sessions list and the Dashboard.
            rel = _DB.connect(store)
            try:
                st = build(rel, graph_path, rebuild=True, noise=load_config().noise)
            finally:
                rel.close()
            return f"graph rebuilt ({st})"

        def _embed() -> str:
            from ..embedding.runner import EmbedStats, run_embed
            from ..relational.db import Database as _DB

            cfg = load_config()
            if not cfg.embedding.model:
                # Fail NOW with the fix, not after the probe explains it.
                raise RuntimeError(
                    "no embedding model is set — choose one under Settings → Embeddings "
                    "(e.g. nomic-embed-text, after `ollama pull nomic-embed-text`)"
                )

            def _progress(st: EmbedStats) -> None:
                pj.set_progress(pj.STEP_EMBED, st.as_dict())

            conn = _DB.connect(store)
            try:
                st = run_embed(conn, cfg.embedding, progress=_progress)
            finally:
                conn.close()
            msg = f"embedded {st.embedded} of {st.total} sessions"
            if st.skipped_existing:
                msg += f", {st.skipped_existing} already embedded"
            if st.unembeddable:
                msg += f", {st.unembeddable} with no text"
            if st.failed:
                msg += f", {st.failed} failed" + (f" (last: {st.last_error})" if st.last_error else "")
            # A pass in which every attempt failed is a FAILED step: the
            # backend is not working, and "done" would hide the reason
            # (the Similar tab shows a done step as the prerequisite
            # again, with nothing about why).
            if st.failed and st.embedded == 0:
                raise RuntimeError(
                    f"no session could be embedded ({st.failed} failed"
                    + (f"; last: {st.last_error}" if st.last_error else "")
                    + ") — check the embedding model under Settings → Embeddings"
                )
            return msg

        def _similar() -> str:
            from ..embedding.similar_runner import GraphNotReadyError, KuzuEdgeStore, run_similar
            from ..graph.schema import GraphDatabase
            from ..relational.db import Database as _DB

            cfg = load_config()
            conn = _DB.connect(store)
            try:
                gdb = GraphDatabase.connect(graph_path)
                try:
                    st = run_similar(conn, cfg.similarity, KuzuEdgeStore(gdb))
                except GraphNotReadyError as exc:
                    raise RuntimeError(f"the graph is not built yet — run Build knowledge graph first ({exc})") from None
                finally:
                    gdb.close()
            finally:
                conn.close()
            spaces = sum(st.sessions_per_space.values())
            msg = f"{st.written_edges} similarity links over {spaces} embedded sessions"
            if st.retired_edges:
                msg += f", {st.retired_edges} stale links removed"
            if st.no_envelope:
                msg += f", {st.no_envelope} sessions not embedded yet"
            return msg

        def _kpis() -> str:
            from ..judge.kpis import compute_kpis
            from ..judge.rubric import load_rubric
            from ..relational.db import Database as _DB

            db_ = _DB.connect(store)
            try:
                st = compute_kpis(db_, load_rubric().name)
            finally:
                db_.close()
            return f"kpis computed ({st})"

        return {
            pj.STEP_INGEST: _ingest,
            pj.STEP_CORRELATE: _correlate,
            pj.STEP_GRAPH: _graph,
            pj.STEP_EMBED: _embed,
            pj.STEP_SIMILAR: _similar,
            pj.STEP_JUDGE: _judge,
            pj.STEP_KPIS: _kpis,
        }

    @app.post("/api/pipeline/run/{step}")
    def pipeline_run(step: str, opts: Optional[PipelineRun] = None) -> dict[str, Any]:
        from .. import pipeline_jobs as pj

        runners = _pipeline_runners(opts)
        if step not in runners:
            raise HTTPException(status_code=404, detail=f"unknown step: {step}")
        try:
            pj.start(step, runners[step])
        except pj.StepBusyError as exc:
            # 409, not 500: asking twice is a normal thing a user does,
            # and the honest answer is "already running", not an error.
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return {"step": step, "started": True}

    @app.post("/api/pipeline/run-all")
    def pipeline_run_all(
        include_judge: bool = False, opts: Optional[PipelineRun] = None,
    ) -> dict[str, Any]:
        """Run every step in order, as one background sequence.

        Sequential by construction — see pipeline_jobs.start_all. The
        judge is excluded unless explicitly asked for, because it calls
        a model per turn and can cost real money.
        """
        from .. import pipeline_jobs as pj

        try:
            pj.start_all(
                _pipeline_runners(opts), include_judge=include_judge,
                only=(opts.steps if opts else None),
            )
        except pj.StepBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {"started": True, "include_judge": include_judge, "steps": opts.steps if opts else None}

    # ── filesystem browse (settings path pickers) ──────────────────────
    # A browser CANNOT read a real path: <input type="file"> deliberately
    # hides it, so a picker has to be served from here. This is therefore
    # a deliberate, and deliberately NARROW, capability:
    #
    #   * READ-ONLY, and only names + is_dir. No file contents, ever.
    #   * Entry-capped, so a huge directory cannot be used to hang the UI.
    #   * Permission errors are reported as an empty listing, not raised —
    #     an unreadable folder is a normal thing to click on.
    #
    # It is acceptable only because this API binds 127.0.0.1 and is
    # already behind the Host + Origin guards above; it must never be
    # exposed on a routable interface.
    @app.get("/api/fs/browse")
    def fs_browse(path: str = "", only_dirs: bool = False) -> dict[str, Any]:
        from pathlib import Path as _P

        base = _P(path).expanduser() if path else _P.home()
        try:
            base = base.resolve()
        except OSError:
            base = _P.home()
        if not base.is_dir():
            base = base.parent if base.parent.is_dir() else _P.home()

        entries: list[dict[str, Any]] = []
        try:
            for child in sorted(
                base.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())
            ):
                if child.name.startswith(".") and child.name not in (".cct",):
                    continue          # hidden clutter, but keep ~/.cct
                is_dir = child.is_dir()
                if only_dirs and not is_dir:
                    continue
                if not is_dir and child.suffix.lower() not in (".db", ".sqlite",
                                                               ".sqlite3"):
                    continue          # only stores are selectable
                entries.append({"name": child.name, "is_dir": is_dir})
                if len(entries) >= C.FS_BROWSE_MAX_ENTRIES:
                    break
        except (OSError, PermissionError):
            entries = []              # unreadable folder is not an error

        return {
            "path": str(base),
            "parent": str(base.parent) if base.parent != base else None,
            "entries": entries,
            "truncated": len(entries) >= C.FS_BROWSE_MAX_ENTRIES,
            # Places a store is actually likely to be, so the common case
            # is one click rather than a walk from /.
            "shortcuts": [
                p for p in (str(_P.home()), str(_P.home() / ".cct"))
                if _P(p).is_dir()
            ],
        }

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
            return dashboard.kpis(conn, noise=load_config().noise)
        finally:
            conn.close()

    @app.get("/api/dashboard/latency")
    def dashboard_latency() -> dict[str, Any]:
        """Agent response time across the store (#307): median / p90 of
        the gap before each assistant turn, over sessions worth counting,
        with the measured-n so a median over 12 turns is not read as
        one over 12,000."""
        conn = db()
        try:
            return dashboard.latency(conn, noise=load_config().noise)
        finally:
            conn.close()

    @app.get("/api/dashboard/labels")
    def dashboard_labels() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.label_distribution(conn, noise=load_config().noise)
        finally:
            conn.close()

    @app.get("/api/dashboard/developers")
    def dashboard_developers() -> dict[str, Any]:
        # E1 (#65): per-developer rollup. Read-only, no ranking — see
        # dashboard.developer_aggregates for why it is ordered by id.
        conn = db()
        try:
            return dashboard.developer_aggregates(conn, noise=load_config().noise)
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
    @app.get("/api/labels/correlation")
    def labels_correlation() -> dict[str, Any]:
        # E10 label correlation (#65): per-label figures over turns that
        # have BOTH a judge label and archived trace text. Coverage is
        # part of the payload — a correlation over a handful of rows is
        # not a finding, and the caller must be able to see that.
        from .. import correlate_labels as cl

        conn = db()
        try:
            return cl.correlations(conn)
        finally:
            conn.close()

    @app.get("/api/labels/{label}/traces")
    def labels_traces(label: str, limit: int = C.SEARCH_DEFAULT_LIMIT) -> dict[str, Any]:
        # Read what was actually said on the turns a label fired on.
        from .. import correlate_labels as cl

        conn = db()
        try:
            return {"label": label, "traces": cl.traces_for_label(conn, label, limit=limit)}
        except ValueError:
            # Unknown label — a 404 rather than a 500: the rubric is the
            # closed vocabulary and the caller asked outside it.
            raise HTTPException(status_code=404, detail="unknown label") from None
        finally:
            conn.close()

    @app.get("/api/predict/effort")
    def predict_effort(project_path: str = "") -> dict[str, Any]:
        # E4 (#65): base-rate effort estimate, not a fitted model. Every
        # figure carries its sample size and is withheld below the floor.
        from .. import predict

        conn = db()
        try:
            return predict.effort_estimate(
                conn, project_path or None, noise=load_config().noise
            )
        finally:
            conn.close()

    @app.get("/api/predict/outcome")
    def predict_outcome() -> dict[str, Any]:
        # E4 (#65): historical pass rate over recorded benchmark
        # attempts — the only ground-truth outcome this store holds.
        from .. import predict

        conn = db()
        try:
            return predict.outcome_prediction(conn)
        finally:
            conn.close()

    @app.get("/api/dashboard/cost")
    def dashboard_cost() -> dict[str, Any]:
        conn = db()
        try:
            return dashboard.cost_by_outcome(conn, noise=load_config().noise)
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

    # ── Team (#174): the shared store's status ──────────────────────────
    @app.get("/api/team/status")
    def team_status(window: Optional[int] = None) -> dict[str, Any]:
        """Who is active (a heartbeat within the window), what they are
        on, and cost per developer / project / time window. Read-only;
        the store's dialect says whether it is shared."""
        from . import alerts as alerts_mod
        from . import team as team_mod

        cfg = load_config()
        seconds = cfg.team.active_window_seconds if window is None else int(window)
        if seconds <= 0:
            raise HTTPException(status_code=400, detail="window must be a positive number of seconds")
        conn = db()
        try:
            status = team_mod.team_status(conn, noise=cfg.noise, active_window_seconds=seconds)
            # Alerts ride on the status so the tab is one fetch; they are
            # derived from the same rows, never stored.
            status["alerts"] = alerts_mod.all_alerts(
                conn, status, budgets=cfg.team.budgets, runaway=cfg.team.runaway, noise=cfg.noise,
            )
            return status
        finally:
            conn.close()

    @app.get("/api/team/alerts")
    def team_alerts() -> dict[str, Any]:
        """Budget and runaway alerts alone (the cron/CI shape)."""
        from . import alerts as alerts_mod
        from . import team as team_mod

        cfg = load_config()
        conn = db()
        try:
            status = team_mod.team_status(conn, noise=cfg.noise, active_window_seconds=cfg.team.active_window_seconds)
            return alerts_mod.all_alerts(
                conn, status, budgets=cfg.team.budgets, runaway=cfg.team.runaway, noise=cfg.noise,
            )
        finally:
            conn.close()

    # ── Ask: a question in words, answered from the store ───────────────
    def _ask_context(conn: Database):
        from ..ask.tools import AskContext

        cfg = load_config()
        return AskContext(db=conn, kuzu_path=kuzu_path or cfg.kuzu_path, noise=cfg.noise)

    @app.get("/api/ask")
    def ask_info() -> dict[str, Any]:
        """What the Ask page opens with: the judge that will answer (the
        one in Settings — there is no other), example questions, and
        the store facts the model is told."""
        from ..ask import loop as ask_loop
        from ..ask import tools as ask_tools

        spec = ask_loop.load_spec()
        conn = db()
        try:
            facts = ask_tools.store_facts(_ask_context(conn))
        finally:
            conn.close()
        facts.pop("graph_questions", None)
        return {
            "judge": _configured_judge(load_config()),
            "examples": list(spec.examples),
            "tools": [{"name": t["name"], "purpose": t["purpose"]} for t in spec.tools],
            "max_steps": spec.max_steps,
            "facts": facts,
        }

    @app.post("/api/ask")
    def ask(req: AskRequest):
        """Stream the answer as NDJSON events: ``judge`` first, then one
        ``step`` and one ``result`` per lookup, then ``answer`` or
        ``error``. Every lookup is read-only. The judge is the one in
        Settings; a 27B model needs seconds to a minute per step, so the
        page shows each step as it happens instead of one spinner."""
        from ..ask import loop as ask_loop
        from ..judge.registry import UnknownJudgeError, get_judge

        question = (req.question or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="empty question")
        cfg = load_config()
        conf = _configured_judge(cfg)
        backend, model = cfg.judge.resolve(None)
        try:
            judge = get_judge(backend, model)
        except UnknownJudgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        def events():
            yield json.dumps({"event": ask_loop.EVENT_JUDGE, "judge": conf["spec"],
                              "source": conf["source"]}) + "\n"
            conn = db()
            try:
                for ev in ask_loop.ask(_ask_context(conn), judge, question, req.history):
                    yield json.dumps(ev, ensure_ascii=False, default=str) + "\n"
            except Exception as exc:  # noqa: BLE001 — the stream must end with a reason
                _log.exception("ask failed")
                yield json.dumps({"event": ask_loop.EVENT_ERROR,
                                  "error": f"{type(exc).__name__}: {exc}"[:300]}) + "\n"
            finally:
                conn.close()

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.get("/api/dashboard/benchmark")
    def dashboard_benchmark() -> dict[str, Any]:
        conn = db()
        try:
            # E9: correlation coverage (#91) + by-result outcomes (#92) in
            # one payload; both stay independently unit-testable pure fns.
            from .. import pipeline_jobs as pj

            return {
                **dashboard.benchmark_correlation(conn, noise=load_config().noise),
                **dashboard.benchmark_outcomes(conn),
                # Where runs would be read from, so the page can say
                # "set it in Settings" or offer the step, without a
                # second call.
                "runs_root": pj.benchmark_runs_root(),
                "link_job": pj.job_state(pj.STEP_CORRELATE),
            }
        finally:
            conn.close()

    # ── sessions ───────────────────────────────────────────────────────
    @app.get("/api/sessions")
    def sessions(
        query: str = "", copilot: str = "", limit: int = 50, include_noise: bool = False,
        sort: str = mcp_tools.SESSION_SORT_DEFAULT, order: str = "desc",
    ) -> dict[str, Any]:
        """The list, noise excluded by default (#307); ``excluded_noise``
        is how many the same filters would add with include_noise=1, so
        the page's toggle can say "Show excluded (n)". ``sort``/``order``
        are the grid's column headers; the limit applies after ordering."""
        if order not in ("asc", "desc"):
            raise HTTPException(status_code=400, detail="order must be asc or desc")
        noise = load_config().noise
        conn = db()
        try:
            try:
                rows = mcp_tools.search_sessions(
                    conn, query or None, copilot=copilot or None, limit=limit,
                    noise=noise, include_noise=include_noise,
                    sort=sort, descending=(order == "desc"),
                )
            except mcp_tools.UnknownSortError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from None
            return {
                "sessions": rows,
                "sort": sort,
                "order": order,
                "excluded_noise": mcp_tools.count_noise_sessions(
                    conn, noise, query or None, copilot=copilot or None,
                ),
                "include_noise": include_noise,
            }
        finally:
            conn.close()

    @app.put("/api/sessions/{session_id}/tags/{flag}")
    def session_tag(session_id: int, flag: str, req: TagUpdate) -> dict[str, Any]:
        """Set or clear a hand-set tag (favorite, todo); returns the
        session's tags. "analyzed" is derived from the analyses and
        cannot be set — a 400 says so."""
        conn = db()
        try:
            return {"id": session_id, "tags": mcp_tools.set_session_flag(conn, session_id, flag, req.on)}
        except ValueError as exc:
            raise HTTPException(status_code=404 if "no session" in str(exc) else 400, detail=str(exc)) from None
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

    # ── session-level analysis (#65 Phase 1) ───────────────────────────
    def _analysis_judge(conn: Database, session_id: int, spec: str):
        """The judge for one session: an explicit ``family:model`` if the
        caller gave one, else the configured judge for the session's
        copilot — the same resolution the per-turn judge uses."""
        from ..judge.registry import UnknownJudgeError, get_judge

        # Existence first, whatever the judge spec: an explicit judge must
        # not skip the check and let a paid backend be invoked for a
        # session that is not there.
        row = conn.query_one(
            "SELECT copilot FROM copilot_session WHERE id = ?", (session_id,)
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"session {session_id} not found")
        if spec:
            family, model = (spec.split(":", 1) + [""])[:2]
        else:
            family, model = load_config().judge.resolve(str(row[0]))
        try:
            judge = get_judge(family, model)
        except UnknownJudgeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # Name the model the judge will ACTUALLY call (a blank configured
        # model means the backend's own default), so the page can say
        # "Generate with ollama:llama3" — and the user can see when that
        # model is not the one they have installed.
        actual = getattr(judge, "_model_label", None) or getattr(judge, "_model", "") or model
        return judge, f"{family}:{actual or '(default)'}"

    @app.get("/api/sessions/{session_id}/analysis")
    def session_analysis(session_id: int) -> dict[str, Any]:
        from ..judge import session_analysis as sa

        conn = db()
        try:
            _judge, label = _analysis_judge(conn, session_id, "")
            archived = conn.query_one(
                f"SELECT COUNT(*) FROM {C.TBL_TRACE_DOCUMENT} "
                "WHERE session_ref = ? AND source_kind = ?",
                (session_id, C.SOURCE_KIND_COPILOT_TRANSCRIPT),
            )
            turns = conn.query_one(
                "SELECT COUNT(*) FROM copilot_turn WHERE session_id = ?", (session_id,)
            )
            return {
                "judge": label,
                "archive": {
                    "archived_turns": int((archived or (0,))[0] or 0),
                    "turns": int((turns or (0,))[0] or 0),
                },
                "kinds": sa.all_analyses(conn, session_id),
                "titles": sa.load_spec().titles,
            }
        finally:
            conn.close()

    @app.post("/api/sessions/{session_id}/analysis/{kind}")
    def run_session_analysis(
        session_id: int, kind: str, req: Optional[SessionAnalysisRequest] = None
    ) -> dict[str, Any]:
        """Run one analysis SYNCHRONOUSLY. One request, one spinner: the
        pipeline job table is single-slot per step and would serialise
        unrelated sessions behind each other. A run is one model call,
        so the request is as long as the model takes (minutes at most)."""
        from ..judge import session_analysis as sa
        from ..judge.contracts import JudgeTransportError

        req = req or SessionAnalysisRequest()
        if kind not in C.ANALYSIS_KINDS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown analysis kind {kind!r}; known: {', '.join(C.ANALYSIS_KINDS)}",
            )
        conn = db()
        try:
            judge, label = _analysis_judge(conn, session_id, req.judge or "")
            try:
                row = sa.analyze_session(
                    conn, session_id, kind, judge=judge, force=req.force,
                )
            except JudgeTransportError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": f"the judge ({label}) did not answer: {exc}",
                        "prerequisite": "judge",
                        "guidance": (
                            "Check the LLM-as-Judge settings — is the backend "
                            "running and the model pulled? — then run it again."
                        ),
                    },
                )
            except (RuntimeError, ValueError) as exc:
                # ClaudeCliNotFoundError / MissingBaseUrlError: a configuration
                # gap, told in the same prerequisite shape.
                raise HTTPException(
                    status_code=503,
                    detail={"error": str(exc), "prerequisite": "judge", "guidance": str(exc)},
                )
            return {"judge": label, **row}
        finally:
            conn.close()

    # ── Learn center (#309): the repo's own docs, from a closed allowlist ─
    @app.get("/api/docs")
    def docs_index() -> dict[str, Any]:
        from . import docs as learn

        return learn.index()

    @app.get("/api/docs/image/{name}")
    def docs_image(name: str):
        from starlette.responses import FileResponse

        from . import docs as learn

        try:
            path, media = learn.image_file(name)
        except learn.UnknownImageError:
            raise HTTPException(status_code=404, detail="unknown image") from None
        return FileResponse(path, media_type=media)

    @app.get("/api/docs/{slug}")
    def docs_document(slug: str) -> dict[str, Any]:
        from . import docs as learn

        try:
            return learn.document(slug)
        except learn.UnknownDocError:
            raise HTTPException(status_code=404, detail="unknown document") from None

    @app.get("/api/resources/recent-errors")
    def recent_errors() -> dict[str, Any]:
        conn = db()
        try:
            return mcp_resources.recent_errors(conn, noise=load_config().noise)
        finally:
            conn.close()

    # ── graph (lazy Kùzu) ──────────────────────────────────────────────
    def _graph():
        """The Graph page's opener: READ-ONLY and NON-CREATING. Every
        route here reads; a create-capable open (the old choice) made a
        GET on an absent path create an empty store and its parent
        directory. An absent or unbuilt store raises RuntimeError, which
        the routes turn into the 503 prerequisite."""
        from ..graph.schema import GraphDatabase

        path = kuzu_path or load_config().kuzu_path
        return GraphDatabase.connect_read_only(path)

    @app.get("/api/graph/node-counts")
    def graph_node_counts() -> dict[str, Any]:
        from ..graph import query as gq

        try:
            g = _graph()
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "The kuzu package is not installed.",
                    "prerequisite": "kuzu",
                    "guidance": "Re-run setup, or `pip install kuzu` in the venv.",
                },
            ) from None
        except RuntimeError as exc:
            # An unopenable store (path is a directory, file corrupt,
            # locked by a build) used to escape as an unhandled 500 —
            # which carries no CORS headers, so the browser reported
            # "failed to fetch" and the page blamed the API (F10).
            _log.warning("graph store could not be opened: %s", exc)
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "The graph store at the configured kuzu path could not be opened.",
                    "prerequisite": "graph",
                    "guidance": "Check CCT_SA_KUZU_PATH under Settings (a corrupt store file "
                                "can be deleted), then rebuild from the Analysis tab.",
                },
            ) from None
        try:
            return {"node_counts": gq.node_counts(g), "tool_failures": gq.tool_failure_stats(g)}
        except Exception as exc:  # noqa: BLE001
            # A NEVER-BUILT graph is not an error, and it is NOT the same
            # as kuzu being missing. kuzu happily opens an empty store,
            # so the first query fails with "Table Copilot does not
            # exist" — which surfaced to the user as a 500 and a banner
            # blaming a package that was installed all along.
            if "does not exist" in str(exc):
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "The knowledge graph has not been built yet.",
                        "prerequisite": "graph",
                        "guidance": "Build it from the Analysis tab, or run `session-analytics graph --rebuild`.",
                    },
                ) from None
            raise _internal_error(exc, "graph node counts") from None
        finally:
            g.close()

    # ── neighbourhoods: a session or a project and what it is connected
    #    to; the drill-ins behind a tool and a file; the catalogue ──────
    class CatalogueRun(BaseModel):
        params: Optional[dict] = None

    def _with_graph(fn):
        """Run ``fn(gdb)`` on the graph store; 503 when kuzu is absent or
        the store cannot be opened, in the shape the Studio explains."""
        try:
            g = _graph()
        except ImportError:
            raise HTTPException(status_code=503, detail={"error": "The kuzu package is not installed.",
                                                         "prerequisite": "kuzu", "guidance": "Re-run setup."})
        except RuntimeError as exc:
            _log.warning("graph store could not be opened: %s", exc)
            raise HTTPException(status_code=503, detail={
                "error": "The graph store at the configured kuzu path could not be opened.",
                "prerequisite": "graph",
                "guidance": "Run Build knowledge graph on the Analysis page.",
            }) from None
        try:
            return fn(g)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception as exc:  # noqa: BLE001 — an unbuilt graph has no tables
            if "does not exist" in str(exc) or "Binder exception" in str(exc):
                raise HTTPException(status_code=503, detail={
                    "error": "The graph has not been built yet.",
                    "prerequisite": "graph",
                    "guidance": "Run Build knowledge graph on the Analysis page.",
                }) from None
            raise _internal_error(exc, "graph") from None
        finally:
            g.close()

    @app.get("/api/graph/projects")
    def graph_projects() -> dict[str, Any]:
        from ..graph import neighbourhood as nb

        return {"projects": _with_graph(lambda g: nb.project_paths(g))}

    @app.get("/api/graph/session/{session_id}")
    def graph_session(session_id: int) -> dict[str, Any]:
        from ..graph import neighbourhood as nb

        conn = db()
        try:
            out = _with_graph(lambda g: nb.session_neighbourhood(g, conn, session_id))
        finally:
            conn.close()
        if out is None:
            raise HTTPException(status_code=404, detail=f"no session {session_id}")
        return out

    @app.get("/api/graph/session/{session_id}/tool/{tool}")
    def graph_session_tool(session_id: int, tool: str) -> dict[str, Any]:
        from ..graph import neighbourhood as nb

        conn = db()
        try:
            out = _with_graph(lambda g: nb.tool_turns(g, conn, session_id, tool))
        finally:
            conn.close()
        if out is None:
            raise HTTPException(status_code=404, detail=f"no session {session_id}")
        return out

    @app.get("/api/graph/file")
    def graph_file(path: str) -> dict[str, Any]:
        from ..graph import neighbourhood as nb

        conn = db()
        try:
            return _with_graph(lambda g: nb.file_sessions(g, conn, path))
        finally:
            conn.close()

    @app.get("/api/graph/project")
    def graph_project(path: str) -> dict[str, Any]:
        from ..graph import neighbourhood as nb

        conn = db()
        try:
            return _with_graph(lambda g: nb.project_neighbourhood(g, conn, path))
        finally:
            conn.close()

    @app.get("/api/graph/catalogue")
    def graph_catalogue() -> dict[str, Any]:
        from ..graph import query as gq

        return {"queries": gq.catalogue()}

    @app.post("/api/graph/catalogue/{query_id}")
    def graph_catalogue_run(query_id: str, req: Optional[CatalogueRun] = None) -> dict[str, Any]:
        from ..graph import query as gq

        params = (req.params if req and req.params else {})
        return _with_graph(lambda g: gq.run_catalogue(g, query_id, params))

    @app.post("/api/graph/query")
    def graph_query(q: CypherQuery) -> dict[str, Any]:
        from ..graph import query as gq

        return {"rows": _with_graph(lambda g: gq.run_readonly(g, q.cypher, q.params))}

    @app.get("/api/graph/expand")
    def graph_expand(label: str, key_field: str, key_value: str) -> dict[str, Any]:
        from ..graph import query as gq

        return _with_graph(lambda g: gq.expand_node(g, label, key_field, key_value))

    # ── analyze (judge) ────────────────────────────────────────────────
    @app.post("/api/analyze")
    def analyze(req: AnalyzeRequest) -> dict[str, Any]:
        from ..judge.registry import UnknownJudgeError, get_judge
        from ..judge.rubric import load_rubric
        from ..judge.runner import run_default_by_copilot, run_judge

        from ..judge.label_sources import UnknownLabelSourceError

        cfg = load_config()
        rubric = load_rubric(req.rubric_name)
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
                    only_labelled_by=req.only_labelled_by,
                )
                return {
                    "judge": f"{family}:{model or '(default)'}",
                    "rubric_name": rubric.name, **stats.as_dict(),
                }
            return {
                "rubric_name": rubric.name,
                "by_copilot": run_default_by_copilot(
                    conn, rubric, cfg, workers=workers,
                    session_id=req.session_id, limit=req.limit,
                    only_labelled_by=req.only_labelled_by,
                ),
            }
        except UnknownLabelSourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            conn.close()

    # ── embeddings (the Similar tab's prerequisite) ───────────────────
    def _configured_embedding(cfg) -> dict[str, Any]:
        e = cfg.embedding
        return {"backend": e.backend, "model": e.model, "spec": f"{e.backend}:{e.model}" if e.model else e.backend,
                "model_set": bool(e.model)}

    @app.get("/api/embed/models")
    def embed_models() -> dict[str, Any]:
        """The models the embedding backend serves (Ollama lists every
        model; embedding ones are e.g. nomic-embed-text), from the SAVED
        configuration, plus what is configured now."""
        import json as _json
        import urllib.request

        cfg = load_config()
        out: dict[str, Any] = {"configured": _configured_embedding(cfg), "backend": cfg.embedding.backend,
                               "models": [], "reachable": False, "url": ""}
        if cfg.embedding.backend != "ollama":
            return out
        base = (cfg.embedding.ollama_url or "http://localhost:11434").rstrip("/")
        out["url"] = base
        from ..embedding.ollama_embed import CAPABILITY_EMBEDDING

        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=_OLLAMA_LIST_TIMEOUT) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            served = sorted(
                (str(m.get("name")), str(m.get("digest") or ""))
                for m in data.get("models", []) if isinstance(m, dict) and m.get("name")
            )
            # Only models Ollama itself says can embed (/api/show
            # capabilities): a chat model in this list is a refused
            # pass later, with an error that reads like a server flag.
            # The lookups run concurrently and are remembered per
            # digest, so the list is one round trip after the first —
            # a slow Ollama (loading a model) must not leave the page
            # without its dropdown.
            caps_by_name = _ollama_capabilities(base, served)
            embedding: list[str] = []
            chat: list[str] = []
            for name, _digest in served:
                caps = caps_by_name.get(name)
                # ABSENT is unknown (an older Ollama reports none):
                # only a present list can say "cannot embed".
                if caps is None or CAPABILITY_EMBEDDING in caps:
                    embedding.append(name)
                else:
                    chat.append(name)
            out.update({"reachable": True, "models": embedding, "not_embedding": chat})
        except Exception as exc:  # noqa: BLE001 — unreachable is an answer
            _log.info("embedding model list unavailable at %s: %s", base, exc)
            out["error"] = type(exc).__name__
        return out

    @app.post("/api/embed/test")
    def embed_test() -> dict[str, Any]:
        """Embed one short string with the SAVED embedding settings:
        the model that answered, the vector size and the time, or the
        backend's own reason."""
        import time as _time

        from ..embedding.registry import get_embedding

        cfg = load_config()
        conf = _configured_embedding(cfg)
        started = _time.time()
        try:
            backend = get_embedding(cfg.embedding.backend, cfg.embedding.model, base_url=cfg.embedding.ollama_url)
            backend.probe()
            result = backend.embed("The quick brown fox jumps over the lazy dog.")
        except Exception as exc:  # noqa: BLE001 — the reason is the answer
            _log.warning("embedding test failed: %s", exc)
            return {"ok": False, "embedding": conf["spec"], "error": str(exc)[:300],
                    "seconds": round(_time.time() - started, 1)}
        return {"ok": True, "embedding": conf["spec"], "model": getattr(result, "resolved_model", cfg.embedding.model),
                "dimensions": len(result.vector), "seconds": round(_time.time() - started, 1)}

    # ── judge validation (#313) ────────────────────────────────────────
    @app.get("/api/judge/runs")
    def judge_runs() -> dict[str, Any]:
        from ..judge import agreement as agr

        conn = db()
        try:
            return agr.label_runs(conn)
        finally:
            conn.close()

    @app.get("/api/judge/agreement")
    def judge_agreement(a: str, b: str) -> dict[str, Any]:
        from ..judge import agreement as agr
        from ..judge.label_sources import UnknownLabelSourceError

        conn = db()
        try:
            return agr.agreement(conn, a, b)
        except UnknownLabelSourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
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
