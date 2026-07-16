# session_analytics.cli — argparse subcommands + main() entrypoint.
#
# Subcommands (M1): list, ingest, doctor. Later milestones add graph (M2),
# analyze + kpis (M3), mcp (M4), serve (M6). Stable exit codes mirror the
# benchmark harness: 0 ok, 2 usage/unknown, 3 runtime, 8 not-implemented.

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Sequence

from . import constants as C
from .config import load_config
from .registry import UnknownAdapterError, list_adapter_ids

_log = logging.getLogger(__name__)


# ── parser ─────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="session-analytics",
        description=(
            "Copilot session analytics & process-mining pipeline. Ingests "
            "Claude Code (and Aider) sessions into PostgreSQL + an embedded "
            "Kùzu graph, runs an LLM-as-Judge heuristic pass, and serves a "
            "Studio UI. See specs/session-analytics/spec.md."
        ),
        epilog="Exit codes: 0 ok; 2 usage/unknown; 3 runtime; 8 not implemented.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging."
    )
    sub = parser.add_subparsers(dest="subcommand", required=True, metavar="<subcommand>")

    sub.add_parser("list", help="List registered copilot adapters.")

    p_setup = sub.add_parser("setup", help="Guided first-run configuration (writes .env).")
    p_setup.add_argument(
        "--non-interactive", action="store_true",
        help="Write defaults without prompting (CI/automation).",
    )
    p_setup.add_argument("--dsn", default=None, help="Preset the DSN (skips that prompt).")

    p_ing = sub.add_parser("ingest", help="Ingest sessions into the relational store.")
    p_ing.add_argument(
        "--copilot",
        action="append",
        default=None,
        help="Copilot id to ingest (repeatable). Default: all registered.",
    )
    p_ing.add_argument(
        "--root", type=Path, default=None, help="Override the source root (all copilots)."
    )
    p_ing.add_argument(
        "--dsn", default=None, help="Database DSN (else config / CCT_SA_DSN env)."
    )
    p_ing.add_argument(
        "--developer-id", default=C.DEFAULT_DEVELOPER_ID, help="E1 multi-tenant tag."
    )
    p_ing.add_argument(
        "--redact",
        choices=C.REDACTION_MODES,
        default=None,
        help="Redaction mode (default from config: code).",
    )
    grp = p_ing.add_mutually_exclusive_group()
    grp.add_argument(
        "--incremental",
        dest="full",
        action="store_false",
        help="Only ingest new/changed sessions (default).",
    )
    grp.add_argument(
        "--full",
        dest="full",
        action="store_true",
        help="Re-parse every session (idempotent).",
    )
    p_ing.set_defaults(full=False)
    p_ing.add_argument("--since-days", type=int, default=None, help=argparse.SUPPRESS)

    p_doc = sub.add_parser("doctor", help="Report store counts + source reachability.")
    p_doc.add_argument("--dsn", default=None, help="Database DSN (else config).")

    p_an = sub.add_parser("analyze", help="Run LLM-as-Judge over un-labeled turns.")
    p_an.add_argument("--dsn", default=None, help="Database DSN (else config).")
    p_an.add_argument(
        "--judge",
        default=None,
        help="Judge spec '<family>:<model>' (e.g. ollama:llama3, claude-code:sonnet). "
             "Default: from config (local ollama).",
    )
    p_an.add_argument("--workers", type=int, default=None, help="Parallel judge workers.")
    p_an.add_argument("--overwrite", action="store_true", help="Re-label already-labeled turns.")
    p_an.add_argument("--session-id", type=int, default=None, help="Limit to one session id.")
    p_an.add_argument("--limit", type=int, default=None, help="Max turns to label this run.")

    p_kpi = sub.add_parser("kpis", help="Compute session-level KPI rollups from labels.")
    p_kpi.add_argument("--dsn", default=None, help="Database DSN (else config).")
    p_kpi.add_argument("--session-id", type=int, default=None, help="Limit to one session id.")

    p_mcp = sub.add_parser("mcp", help="Run the MCP stdio server over the store.")
    p_mcp.add_argument("--dsn", default=None, help="Database DSN (else config).")

    p_serve = sub.add_parser("serve", help="Launch the FastAPI + Next.js Studio.")
    p_serve.add_argument("--dsn", default=None, help="Database DSN (else config).")
    p_serve.add_argument("--db-path", default=None, help="Kùzu graph dir (else config).")
    p_serve.add_argument("--api-port", type=int, default=8765)
    p_serve.add_argument("--ui-port", type=int, default=3000)
    p_serve.add_argument("--no-ui", action="store_true", help="Serve the API only.")

    p_graph = sub.add_parser("graph", help="Build the Kùzu knowledge graph from the store.")
    p_graph.add_argument("--dsn", default=None, help="Relational DSN (else config).")
    p_graph.add_argument("--db-path", default=None, help="Kùzu graph dir (else config).")
    p_graph.add_argument(
        "--rebuild", action="store_true", help="Drop + recreate all graph tables first."
    )
    p_graph.add_argument(
        "--session-id",
        action="append",
        type=int,
        default=None,
        help="Limit to specific relational session ids (repeatable).",
    )

    return parser


# ── handlers ───────────────────────────────────────────────────────────


def _cmd_list(args: argparse.Namespace) -> int:
    from .judge.registry import list_judge_ids

    print(json.dumps({"adapters": list_adapter_ids(), "judges": list_judge_ids()}, indent=2))
    return C.EXIT_OK


def _cmd_setup(args: argparse.Namespace) -> int:
    from .setup_cmd import run_setup

    overrides = {}
    if args.dsn:
        from .config import ENV_DSN
        overrides[ENV_DSN] = args.dsn
    run_setup(interactive=not args.non_interactive, overrides=overrides)
    return C.EXIT_OK


def _cmd_ingest(args: argparse.Namespace) -> int:
    from .ingest.pipeline import ingest
    from .setup_cmd import ensure_initialized

    if not ensure_initialized(args.dsn):
        return C.EXIT_USAGE
    cfg = load_config(dsn=args.dsn, redaction_mode=args.redact)
    if not cfg.dsn:
        print(
            "error: no DSN configured. Run setup, pass --dsn, or set CCT_SA_DSN. "
            "For a sqlite test run: --dsn sqlite:////tmp/sa.db",
            file=sys.stderr,
        )
        return C.EXIT_USAGE
    try:
        stats = ingest(
            dsn=cfg.dsn,
            copilots=args.copilot,
            root=args.root,
            developer_id=args.developer_id,
            redaction_mode=cfg.redaction_mode,
            full=args.full,
            pricing=cfg.pricing,
        )
    except UnknownAdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 — surface as runtime failure
        _log.exception("ingest failed")
        print(f"error: ingest failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    print(json.dumps(stats.as_dict(), indent=2))
    return C.EXIT_OK


def _cmd_doctor(args: argparse.Namespace) -> int:
    from .relational.db import Database, apply_ddl

    cfg = load_config(dsn=args.dsn)
    report: dict = {"sources": {}, "store": {}}
    for copilot, _ in cfg.sources.items():
        root = cfg.source_root(copilot)
        report["sources"][copilot] = {
            "root": str(root) if root else None,
            "exists": bool(root and root.exists()),
        }
    if cfg.dsn:
        try:
            db = Database.connect(cfg.dsn)
            apply_ddl(db)
            report["store"] = _store_counts(db)
            report["store"]["dsn_dialect"] = db.dialect
            db.close()
        except Exception as exc:  # noqa: BLE001
            report["store"] = {"error": str(exc)}
    else:
        report["store"] = {"error": "no DSN configured"}
    print(json.dumps(report, indent=2))
    return C.EXIT_OK


def _store_counts(db) -> dict:
    def count(table: str) -> int:
        row = db.query_one(f"SELECT COUNT(*) FROM {table}")
        return int(row[0]) if row else 0

    return {
        "sessions": count("copilot_session"),
        "turns": count("copilot_turn"),
        "tool_calls": count("copilot_tool_call"),
        "errors": count("copilot_error"),
        "labels": count("heuristic_label"),
    }


def _cmd_graph(args: argparse.Namespace) -> int:
    from .graph import query
    from .graph.builder import build
    from .graph.schema import GraphDatabase
    from .relational.db import Database

    cfg = load_config(dsn=args.dsn, kuzu_path=args.db_path)
    if not cfg.dsn:
        print("error: no relational DSN configured (see --dsn).", file=sys.stderr)
        return C.EXIT_USAGE
    try:
        rel = Database.connect(cfg.dsn)
        try:
            stats = build(
                rel,
                cfg.kuzu_path,
                session_ids=args.session_id,
                rebuild=args.rebuild,
            )
        finally:
            rel.close()
        gdb = GraphDatabase.connect(cfg.kuzu_path)
        try:
            counts = query.node_counts(gdb)
        finally:
            gdb.close()
    except ImportError as exc:
        print(
            f"error: the graph command needs the 'kuzu' package "
            f"(pip install kuzu): {exc}",
            file=sys.stderr,
        )
        return C.EXIT_RUNTIME
    except Exception as exc:  # noqa: BLE001
        _log.exception("graph build failed")
        print(f"error: graph build failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    print(json.dumps({"built": stats.as_dict(), "node_counts": counts}, indent=2))
    return C.EXIT_OK


def _parse_judge_spec(spec: str) -> tuple[str, str]:
    if ":" in spec:
        family, model = spec.split(":", 1)
        return family, model
    return spec, ""


def _cmd_analyze(args: argparse.Namespace) -> int:
    from .judge.registry import UnknownJudgeError, get_judge
    from .judge.rubric import load_rubric
    from .judge.runner import run_default_by_copilot, run_judge
    from .relational.db import Database, apply_ddl

    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print("error: no DSN configured (see --dsn or run setup).", file=sys.stderr)
        return C.EXIT_USAGE
    workers = args.workers if args.workers is not None else cfg.judge.workers
    rubric = load_rubric()
    try:
        db = Database.connect(cfg.dsn)
        try:
            apply_ddl(db)
            if args.judge:
                # Explicit --judge overrides for ALL turns.
                family, model = _parse_judge_spec(args.judge)
                judge = get_judge(family, model)
                stats = run_judge(
                    db, judge, rubric, workers=workers, overwrite=args.overwrite,
                    session_id=args.session_id, limit=args.limit,
                )
                result = {"judge": f"{family}:{model or '(default)'}", **stats.as_dict()}
            else:
                # Default: per-copilot routing from config (packaged default:
                # local Ollama for every copilot — nothing leaves the machine).
                result = {"by_copilot": run_default_by_copilot(
                    db, rubric, cfg, workers=workers, overwrite=args.overwrite,
                    session_id=args.session_id, limit=args.limit,
                )}
        finally:
            db.close()
    except UnknownJudgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    except Exception as exc:  # noqa: BLE001
        _log.exception("analyze failed")
        print(f"error: analyze failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    print(json.dumps(result, indent=2))
    return C.EXIT_OK


def _cmd_kpis(args: argparse.Namespace) -> int:
    from .judge.kpis import compute_kpis
    from .judge.rubric import load_rubric
    from .relational.db import Database, apply_ddl

    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print("error: no DSN configured (see --dsn).", file=sys.stderr)
        return C.EXIT_USAGE
    rubric = load_rubric()
    try:
        db = Database.connect(cfg.dsn)
        try:
            apply_ddl(db)
            stats = compute_kpis(db, rubric.name, session_id=args.session_id)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        _log.exception("kpis failed")
        print(f"error: kpis failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    print(json.dumps(stats.as_dict(), indent=2))
    return C.EXIT_OK


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp import server

    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print("error: no DSN configured (see --dsn).", file=sys.stderr)
        return C.EXIT_USAGE
    try:
        server.run(cfg.dsn)
    except ImportError as exc:
        print(
            f"error: the mcp command needs the 'mcp' package (pip install mcp): {exc}",
            file=sys.stderr,
        )
        return C.EXIT_RUNTIME
    except Exception as exc:  # noqa: BLE001
        _log.exception("mcp server failed")
        print(f"error: mcp server failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    return C.EXIT_OK


def _cmd_serve(args: argparse.Namespace) -> int:
    from .api.serve import serve

    try:
        return serve(
            dsn=args.dsn or "",
            kuzu_path=args.db_path or "",
            api_port=args.api_port,
            ui_port=args.ui_port,
            no_ui=args.no_ui,
        )
    except ImportError as exc:
        print(
            f"error: serve needs fastapi + uvicorn "
            f"(pip install -r scripts/session_analytics/requirements.txt): {exc}",
            file=sys.stderr,
        )
        return C.EXIT_RUNTIME


_HANDLERS = {
    "list": _cmd_list,
    "setup": _cmd_setup,
    "ingest": _cmd_ingest,
    "doctor": _cmd_doctor,
    "graph": _cmd_graph,
    "analyze": _cmd_analyze,
    "kpis": _cmd_kpis,
    "mcp": _cmd_mcp,
    "serve": _cmd_serve,
}


# ── entrypoint ─────────────────────────────────────────────────────────


def main(argv: Sequence[str]) -> int:
    from ._register import register_all

    register_all()

    parser = _build_parser()
    args = parser.parse_args(list(argv))
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    handler = _HANDLERS.get(args.subcommand)
    if handler is None:  # pragma: no cover — argparse enforces required choice
        parser.error(f"unknown subcommand: {args.subcommand}")
        return C.EXIT_USAGE
    return handler(args)
