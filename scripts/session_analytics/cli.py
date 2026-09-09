# session_analytics.cli — argparse subcommands + main() entrypoint.
#
# Subcommands (M1): list, ingest, doctor. Later milestones add graph (M2),
# analyze + kpis (M3), mcp (M4), serve (M6). Stable exit codes mirror the
# benchmark harness: 0 ok, 2 usage/unknown, 3 runtime, 8 not-implemented.

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Sequence

from . import constants as C
from . import identity as IDENT
from .config import AnalyticsConfig, load_config
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

    p_start = sub.add_parser(
        "start",
        help="One command: install deps, configure, ingest, and open the Studio.",
    )
    p_start.add_argument("--api-port", type=int, default=8765)
    p_start.add_argument("--ui-port", type=int, default=3000)
    p_start.add_argument(
        "--no-open", action="store_true", help="Do not open a browser."
    )

    p_setup = sub.add_parser("setup", help="Guided first-run configuration (writes .env).")
    p_setup.add_argument(
        "--non-interactive", action="store_true",
        help="Write defaults without prompting (CI/automation).",
    )
    p_setup.add_argument("--db", "--dsn", dest="dsn", default=None, help="Preset the DSN (skips that prompt).")

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
        "--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB)."
    )
    p_ing.add_argument(
        "--developer-id",
        default=None,
        help=(
            "E1 multi-tenant tag (verbatim; pre-B1 stamps stay compatible). "
            "Default: derived (CCT_DEVELOPER_ID env/.env > config "
            "developer_id > git --global user.email local-part > 'local')."
        ),
    )
    p_ing.add_argument(
        "--redact",
        choices=C.REDACTION_MODES,
        default=None,
        help="Redaction mode (default from config: code).",
    )
    p_ing.add_argument(
        "--since", default=None, metavar="DATE",
        help="Only sessions modified on/after this date (YYYY-MM-DD or ISO datetime).",
    )
    p_ing.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="Only the newest N sessions (after --since).",
    )
    p_ing.add_argument(
        "--session-id", action="append", default=None, metavar="ID",
        help="Only this native session id (repeatable); --list prints the ids.",
    )
    p_ing.add_argument(
        "--list", action="store_true",
        help="Print what would be loaded under these filters (newest first, with "
             "sizes and loaded state) and exit without loading anything.",
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
        help=(
            "Re-parse every session (idempotent); re-stamps each session "
            "with the currently-derived developer id."
        ),
    )
    p_ing.set_defaults(full=False)
    p_ing.add_argument("--since-days", type=int, default=None, help=argparse.SUPPRESS)

    p_doc = sub.add_parser("doctor", help="Report store counts + source reachability.")
    p_doc.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")

    p_an = sub.add_parser("analyze", help="Run LLM-as-Judge over un-labeled turns.")
    p_an.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
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
    p_an.add_argument(
        "--rubric-name", default=None,
        help="Write labels under this rubric_name instead of the packaged one, so a "
             "second run coexists with the first and the two can be compared (#313).",
    )
    p_an.add_argument(
        "--only-labelled-by", default=None, metavar="SOURCE",
        help="Only turns already labelled by SOURCE — rubric:<name> or human:<labeler> — "
             "so this run covers the same turns and agreement can be measured.",
    )

    p_lab = sub.add_parser("labels", help="Judge validation: human-label sample, import, agreement (#313).")
    p_lab.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
    lab_sub = p_lab.add_subparsers(dest="labels_cmd", required=True)
    p_ls = lab_sub.add_parser("sample", help="Write a CSV of random turns for a person to label.")
    p_ls.add_argument("--n", type=int, default=50, help="How many turns (default 50).")
    p_ls.add_argument("--out", required=True, help="CSV path to write.")
    p_ls.add_argument("--seed", type=int, default=None, help="Random seed for a repeatable draw.")
    p_ls.add_argument(
        "--only-labelled-by", default=None, metavar="SOURCE",
        help="Draw from turns SOURCE (rubric:<name> or human:<labeler>) already labelled.",
    )
    p_li = lab_sub.add_parser("import", help="Read a filled-in sample CSV into human_label.")
    p_li.add_argument("csv", help="The filled-in CSV.")
    p_li.add_argument("--labeler", required=True, help="Who labelled it (any short name).")
    lab_sub.add_parser("runs", help="List rubric runs and human labelers that can be compared.")
    p_la = lab_sub.add_parser("agreement", help="Per-label agreement between two label sources.")
    p_la.add_argument("a", help="rubric:<name> (or bare name) | human:<labeler>")
    p_la.add_argument("b", help="rubric:<name> (or bare name) | human:<labeler>")

    p_emb = sub.add_parser(
        "embed",
        help="Compute session embeddings (E2 slice 1, #285) — an "
             "idempotent post-ingest pass writing the provenance "
             "envelope into copilot_session.session_embedding.",
    )
    p_emb.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
    p_emb.add_argument(
        "--backend", default=None,
        help="Embedding backend family (else config; packaged default: ollama).")
    p_emb.add_argument(
        "--model", default=None,
        help="Embedding model (else config). Ollama has NO default "
             "embedding model, so an empty model refuses with guidance.")
    p_emb.add_argument(
        "--base-url", default=None,
        help="Backend base URL (else config ollama_url).")
    p_emb.add_argument(
        "--input-cap", type=int, default=None,
        help="Composer character cap (else config input_cap_chars).")
    p_emb.add_argument(
        "--overwrite", action="store_true",
        help="Re-embed sessions that already carry an envelope. Without "
             "this, existing envelopes are never touched.")
    p_emb.add_argument("--session-id", type=int, default=None,
                       help="Limit to one session id.")
    p_emb.add_argument("--limit", type=int, default=None,
                       help="Max sessions to embed this run.")

    p_team = sub.add_parser(
        "team",
        help="The team store's status (#174): who is active, what they are "
             "on, cost per developer and project — the Studio's Team tab, "
             "in the terminal.",
    )
    p_team.add_argument("action", nargs="?", default="status", choices=["status", "alerts"],
                        help="status (default) or alerts — budget breaches and runaway sessions; "
                             "exits 1 when one is at or above --fail-on, for cron and CI.")
    p_team.add_argument("--db", "--dsn", dest="dsn", default=None,
                        help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
    p_team.add_argument("--window", type=int, default=None,
                        help="Seconds a heartbeat counts as active (else config team.active_window_seconds).")
    p_team.add_argument("--json", action="store_true", help="Print the payload as JSON.")
    p_team.add_argument("--fail-on", default=C.ALERT_BREACH, choices=list(C.ALERT_LEVELS),
                        help="alerts: the level that makes the exit code 1 (default breach).")

    p_sim = sub.add_parser(
        "similar",
        help="Populate SIMILAR_TO graph edges from stored session "
             "embeddings (E2 slice 2, #287) — strictly local; full "
             "reconciliation every run.",
    )
    p_sim.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
    p_sim.add_argument("--graph-path", "--db-path", dest="db_path", default=None,
                       help="Kùzu store file, or a directory to keep it in (else config kuzu_path).")
    p_sim.add_argument("--threshold", default=None,
                       help="Minimum cosine score for an edge (else config).")
    p_sim.add_argument("--top-k", default=None,
                       help="Neighbors kept per session (else config).")

    p_clu = sub.add_parser(
        "clusters",
        help="Group the stored SIMILAR_TO snapshot into clusters "
             "(E2 slice 3, #289) — read-only; computed on read, "
             "nothing materialized.",
    )
    p_clu.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
    p_clu.add_argument("--graph-path", "--db-path", dest="db_path", default=None,
                       help="Kùzu store file, or a directory to keep it in (else config kuzu_path).")

    p_kpi = sub.add_parser("kpis", help="Compute session-level KPI rollups from labels.")
    p_kpi.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
    p_kpi.add_argument("--session-id", type=int, default=None, help="Limit to one session id.")

    sub.add_parser(
        "calibrate",
        help=(
            "Run the routing held-out evaluation and persist its report "
            "(routing-calibration #266; the report three of the five "
            "gates read)."
        ),
    )

    p_mcp = sub.add_parser("mcp", help="Run the MCP stdio server over the store.")
    p_mcp.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")

    p_serve = sub.add_parser("serve", help="Launch the FastAPI + Next.js Studio.")
    p_serve.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
    p_serve.add_argument("--graph-path", "--db-path", dest="db_path", default=None, help="Kùzu store file, or a directory to keep it in (else config kuzu_path).")
    p_serve.add_argument("--api-port", type=int, default=8765)
    p_serve.add_argument("--ui-port", type=int, default=3000)
    p_serve.add_argument("--no-ui", action="store_true", help="Serve the API only.")

    p_graph = sub.add_parser("graph", help="Build the Kùzu knowledge graph from the store.")
    p_graph.add_argument("--db", "--dsn", dest="dsn", default=None, help="Relational DSN (else config).")
    p_graph.add_argument("--graph-path", "--db-path", dest="db_path", default=None, help="Kùzu store file, or a directory to keep it in (else config kuzu_path).")
    p_graph.add_argument(
        "--rebuild", action="store_true",
        help="Drop + recreate all graph tables first (bulk COPY FROM path).",
    )
    p_graph.add_argument(
        "--exclude-noise", action="store_true",
        help="Leave out sessions the sessions.noise rule excludes from the Studio "
             "(probe runs, temp dirs, too-short). Default: every session.",
    )
    p_graph.add_argument(
        "--session-id",
        action="append",
        type=int,
        default=None,
        help="Limit to specific relational session ids (repeatable).",
    )

    p_exp = sub.add_parser(
        "export", help="Export the relational store to CSV/Parquet (E7)."
    )
    p_exp.add_argument("--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB).")
    p_exp.add_argument(
        "--format",
        choices=C.EXPORT_FORMATS,
        default=C.EXPORT_FORMAT_CSV,
        help="Output format (default: csv). Parquet needs 'pyarrow' (pip install pyarrow).",
    )
    p_exp.add_argument(
        "--table",
        choices=C.EXPORT_TABLES,
        default=C.EXPORT_TABLE_SESSIONS,
        help="Table to export, or 'all' for one file per table (default: sessions).",
    )
    p_exp.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output path. A single CSV table defaults to stdout without --out. "
            "Parquet always requires --out (binary — never written to stdout). "
            "--table all requires --out to be a directory (one <table>.<ext> file each)."
        ),
    )

    p_cor = sub.add_parser(
        "correlate",
        help="Link benchmark run-record.json session_ids to analytics sessions (E9).",
    )
    p_cor.add_argument(
        "--runs-root",
        type=Path,
        required=True,
        help="Benchmark runs root to recursively scan for run-record.json files.",
    )
    p_cor.add_argument(
        "--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB)."
    )

    p_arch = sub.add_parser(
        "archive",
        help="Archive full REDACTED trace text for opted-in projects (E10).",
    )
    p_arch.add_argument(
        "--copilot", action="append", default=None,
        help="Copilot id to archive (repeatable). Default: all registered.",
    )
    p_arch.add_argument(
        "--root", type=Path, default=None,
        help="Override the source root (all copilots).",
    )
    p_arch.add_argument(
        "--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB)."
    )
    p_arch.add_argument(
        "--full", action="store_true",
        help="Re-archive every source (idempotent; default is incremental).",
    )

    p_srch = sub.add_parser(
        "search",
        help="Ranked full-text search over archived trace text (E10).",
    )
    p_srch.add_argument(
        "query",
        help="Words to search for. Case-insensitive and stemmed; terms may "
             "appear in any order, anywhere in a turn. Best matches first.",
    )
    p_srch.add_argument(
        "--limit", type=int, default=C.SEARCH_DEFAULT_LIMIT,
        help=f"Max results (default {C.SEARCH_DEFAULT_LIMIT}, cap {C.SEARCH_MAX_LIMIT}).",
    )
    p_srch.add_argument(
        "--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB)."
    )

    p_watch = sub.add_parser(
        "watch", help="Loop incremental ingest() every --interval seconds (E6)."
    )
    p_watch.add_argument(
        "--developer-id",
        default=None,
        help=(
            "E1 multi-tenant tag. Default: derived (CCT_DEVELOPER_ID env/.env > "
            "config developer_id > git --global user.email local-part > 'local')."
        ),
    )
    p_watch.add_argument(
        "--interval", type=int, default=15, help="Seconds between cycles (default: 15)."
    )
    p_watch.add_argument(
        "--db", "--dsn", dest="dsn", default=None, help="Database: sqlite:////abs/path.db or postgresql://… (else .env CCT_SA_DB)."
    )
    p_watch.add_argument(
        "--copilots",
        action="append",
        default=None,
        help="Copilot id to watch (repeatable). Default: all registered.",
    )

    return parser


# ── handlers ───────────────────────────────────────────────────────────


def _cmd_list(args: argparse.Namespace) -> int:
    from .judge.registry import list_judge_ids

    print(json.dumps({"adapters": list_adapter_ids(), "judges": list_judge_ids()}, indent=2))
    return C.EXIT_OK


def _cmd_start(args: argparse.Namespace) -> int:
    from .quickstart import run_start

    return run_start(
        api_port=args.api_port,
        ui_port=args.ui_port,
        open_browser=not args.no_open,
    )


def _cmd_setup(args: argparse.Namespace) -> int:
    from .setup_cmd import run_setup

    overrides = {}
    if args.dsn:
        from .config import ENV_DB
        overrides[ENV_DB] = args.dsn
    run_setup(interactive=not args.non_interactive, overrides=overrides)
    return C.EXIT_OK


def _derived_developer_id(args: argparse.Namespace, cfg: AnalyticsConfig) -> str:
    """Slice B1 (#187): flag > env/.env > config > git-global-email > "local".

    Env and config inputs come from the loader's resolved fields, so the
    package's documented layering (real env > repo .env > config files)
    applies — never an os.environ bypass here.
    """
    flag_value = getattr(args, "developer_id", None)
    derived = IDENT.derive_developer_id(
        cli_value=flag_value,
        env_value=cfg.developer_id_env,
        config_value=cfg.developer_id_cfg,
    )
    if flag_value is not None and derived.source != IDENT.SOURCE_FLAG:
        # An explicit user instruction was unusable — never drop it silently.
        _log.warning(
            "--developer-id %r is unusable after sanitation; using '%s' "
            "(source: %s) instead",
            flag_value,
            derived.id,
            derived.source,
        )
    elif derived.source != IDENT.SOURCE_FLAG:
        _log.info("developer_id '%s' (source: %s)", derived.id, derived.source)
    return derived.id


def _cmd_ingest(args: argparse.Namespace) -> int:
    from .ingest.pipeline import ingest
    from .ingest.selection import IngestSelection, parse_since
    from .setup_cmd import ensure_initialized

    if not ensure_initialized(args.dsn):
        return C.EXIT_USAGE
    try:
        selection = IngestSelection(
            since=parse_since(args.since) if args.since else None,
            limit=args.limit,
            session_ids=frozenset(args.session_id or ()),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print(
            "error: no database configured. Run setup, pass --db, or set CCT_SA_DB. "
            "For a sqlite test run: --db sqlite:////tmp/sa.db",
            file=sys.stderr,
        )
        return C.EXIT_USAGE
    if args.list:
        from .ingest.pipeline import discover_sessions

        try:
            print(json.dumps(discover_sessions(
                dsn=cfg.dsn, copilots=args.copilot, root=args.root, selection=selection,
            ), indent=2))
        except UnknownAdapterError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return C.EXIT_USAGE
        return C.EXIT_OK
    try:
        stats = ingest(
            dsn=cfg.dsn,
            copilots=args.copilot,
            root=args.root,
            developer_id=_derived_developer_id(args, cfg),
            redaction_mode=cfg.redaction_mode,
            full=args.full,
            pricing=cfg.pricing,
            cli_redaction_override=args.redact,
            projects=cfg.projects,
            project_id_rules=cfg.project_id_rules,
            selection=selection,
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
        report["store"] = {"error": "no database configured"}
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
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
        return C.EXIT_USAGE
    try:
        rel = Database.connect(cfg.dsn)
        try:
            stats = build(
                rel,
                cfg.kuzu_path,
                session_ids=args.session_id,
                rebuild=args.rebuild,
                noise=cfg.noise if args.exclude_noise else None,
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


def _cmd_export(args: argparse.Namespace) -> int:
    from . import export as exp
    from .relational.db import Database, apply_ddl

    # ── validate the output semantics BEFORE touching the DB (FR-1, FR-5) ──
    if args.format == C.EXPORT_FORMAT_PARQUET and args.out is None:
        print(
            "error: --format parquet always requires --out "
            "(binary output cannot be written to stdout).",
            file=sys.stderr,
        )
        return C.EXIT_USAGE
    if args.table == C.EXPORT_TABLE_ALL and args.out is None:
        print(
            "error: --table all requires --out <dir> (writes one file per table).",
            file=sys.stderr,
        )
        return C.EXIT_USAGE
    if args.table == C.EXPORT_TABLE_ALL and args.out.exists() and not args.out.is_dir():
        print(
            f"error: --out must be a directory for --table all, got a file: {args.out}",
            file=sys.stderr,
        )
        return C.EXIT_USAGE
    if args.table != C.EXPORT_TABLE_ALL and args.out is not None and args.out.is_dir():
        print(
            f"error: --out must be a file path for --table {args.table}, "
            f"got a directory: {args.out}",
            file=sys.stderr,
        )
        return C.EXIT_USAGE

    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
        return C.EXIT_USAGE

    try:
        db = Database.connect(cfg.dsn)
        try:
            apply_ddl(db)
            if args.table == C.EXPORT_TABLE_ALL:
                args.out.mkdir(parents=True, exist_ok=True)
                for table in C.EXPORT_DATA_TABLES:
                    dest = args.out / f"{table}.{args.format}"
                    _export_one(exp, db, table, args.format, dest)
            elif args.out is not None:
                args.out.parent.mkdir(parents=True, exist_ok=True)
                _export_one(exp, db, args.table, args.format, args.out)
            else:
                exp.write_csv(db, args.table, sys.stdout)
        finally:
            db.close()
    except ImportError as exc:
        # Parquet's pyarrow is optional (FR-4): a usage error + install hint,
        # never a traceback.
        print(
            f"error: Parquet export needs the 'pyarrow' package "
            f"(pip install pyarrow): {exc}",
            file=sys.stderr,
        )
        return C.EXIT_USAGE
    except Exception as exc:  # noqa: BLE001
        _log.exception("export failed")
        print(f"error: export failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    return C.EXIT_OK


def _export_one(exp, db, table: str, fmt: str, dest: Path) -> None:
    if fmt == C.EXPORT_FORMAT_PARQUET:
        exp.write_parquet(db, table, dest)
    else:
        with open(dest, "w", newline="", encoding="utf-8") as fp:
            exp.write_csv(db, table, fp)


def _cmd_correlate(args: argparse.Namespace) -> int:
    from . import correlate as cor
    from .relational.db import Database, apply_ddl
    from .setup_cmd import ensure_initialized

    # Validate the runs-root BEFORE any DB work (FR-1): it must be an existing
    # DIRECTORY — a plain file would rglob to nothing and masquerade as an
    # all-zero success.
    if not args.runs_root.is_dir():
        print(
            f"error: --runs-root is not a directory: {args.runs_root}",
            file=sys.stderr,
        )
        return C.EXIT_USAGE

    if not ensure_initialized(args.dsn):
        return C.EXIT_USAGE
    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print(
            "error: no database configured. Run setup, pass --db, or set CCT_SA_DB. "
            "For a sqlite test run: --db sqlite:////tmp/sa.db",
            file=sys.stderr,
        )
        return C.EXIT_USAGE

    # Pre-created and passed in so a mid-run exception still has the partial
    # counters to report (FR-4) — correlate.run mutates it in place.
    stats = cor.CorrelationStats()
    try:
        db = Database.connect(cfg.dsn)
        try:
            apply_ddl(db)
            # FR-4: ONE commit per scan, inside correlate.run — the same
            # function the Analysis page's "Link benchmark runs" step calls.
            cor.run(db, args.runs_root, stats=stats)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        # FR-4: the partial counters gathered before the failure are still
        # reported (same JSON shape, stderr — stdout stays success-only).
        # Printed BEFORE the log call so the summary block leads stderr
        # deterministically (the logging traceback would otherwise interleave
        # ahead of it). The counters describe PROCESSED work only — the
        # single post-scan commit never ran, so the transaction rolled back;
        # the wording must never read like the success summary.
        print(json.dumps(stats.as_dict(), indent=2), file=sys.stderr)
        print(
            "note: counters above are PROCESSED-only — the scan failed before "
            "its single commit, the transaction was rolled back, and NO rows "
            "or links from this run were persisted. Re-run after fixing the "
            "error below.",
            file=sys.stderr,
        )
        print(f"error: correlate failed: {exc}", file=sys.stderr)
        _log.exception("correlate failed")
        return C.EXIT_RUNTIME

    # GUARDRAIL: coverage gaps must be explicit, distinct, clearly-labeled
    # lines — never collapsed into just a "linked N" summary. as_dict()
    # serializes EVERY counter, so a future field can't silently vanish here.
    print(json.dumps(stats.as_dict(), indent=2))
    return C.EXIT_OK


def _cmd_watch(args: argparse.Namespace) -> int:
    import threading

    from .ingest.pipeline import ingest
    from .setup_cmd import ensure_initialized
    from .watch import run_watch

    # Interval bounds: reject < 1s up front. 0 would busy-loop ingest with no
    # delay; a negative value would raise from the sleep mid-run.
    if args.interval < 1:
        print(
            f"error: --interval must be >= 1 second (got {args.interval}).",
            file=sys.stderr,
        )
        return C.EXIT_USAGE

    if not ensure_initialized(args.dsn):
        return C.EXIT_USAGE
    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print(
            "error: no database configured. Run setup, pass --db, or set CCT_SA_DB. "
            "For a sqlite test run: --db sqlite:////tmp/sa.db",
            file=sys.stderr,
        )
        return C.EXIT_USAGE

    # Per-cycle IngestStats are logged at INFO; the root logger is WARNING
    # unless -v, so raise this logger to INFO so `watch` shows progress by
    # default (otherwise a healthy watch prints nothing and looks frozen).
    _log.setLevel(logging.INFO)

    watch_developer_id = _derived_developer_id(args, cfg)

    def ingest_fn() -> None:
        stats = ingest(
            dsn=cfg.dsn,
            copilots=args.copilots,
            developer_id=watch_developer_id,
            redaction_mode=cfg.redaction_mode,
            pricing=cfg.pricing,
            cli_redaction_override=None,
            projects=cfg.projects,
            project_id_rules=cfg.project_id_rules,
            full=False,
        )
        _log.info(
            "watch cycle: %d ingested, %d skipped, %d opted out",
            stats.sessions_ingested,
            stats.sessions_skipped,
            stats.sessions_opted_out,
        )

    # A threading.Event is the stop signal: the handler sets it, `event.wait`
    # is the inter-cycle sleep (returns IMMEDIATELY when set, so Ctrl+C is
    # prompt — unlike time.sleep, which PEP 475 resumes for its full duration
    # after a non-raising handler), and `is_set` is the loop's stop check.
    stop = threading.Event()

    def _handle_signal(signum, frame) -> None:
        stop.set()

    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    try:
        # fail_fast_first: an unreachable DB / bad config surfaces on the first
        # cycle as a non-zero exit instead of looping forever.
        run_watch(
            ingest_fn,
            args.interval,
            iterations=None,
            sleep_fn=stop.wait,
            should_stop=stop.is_set,
            fail_fast_first=True,
        )
    except Exception:
        _log.exception("watch: initial ingest failed — check DSN / config")
        return C.EXIT_RUNTIME
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)
    return C.EXIT_OK


def _cmd_archive(args: argparse.Namespace) -> int:
    from . import archive as arch
    from .setup_cmd import ensure_initialized

    if not ensure_initialized(args.dsn):
        return C.EXIT_USAGE
    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print(
            "error: no database configured. Run setup, pass --db, or set CCT_SA_DB.",
            file=sys.stderr,
        )
        return C.EXIT_USAGE

    # Pre-created so a mid-run failure still has partial counters to report
    # (the settled #92 convention) — archive() mutates it in place.
    stats = arch.ArchiveStats()
    try:
        arch.archive(
            dsn=cfg.dsn,
            copilots=args.copilot,
            root=args.root,
            redaction_mode=cfg.redaction_mode,
            full=args.full,
            projects=cfg.projects,
            project_id_rules=cfg.project_id_rules,
            stats=stats,
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps(stats.as_dict(), indent=2), file=sys.stderr)
        print(
            "note: counters above are PROCESSED-only — the run failed before "
            "its single commit, the transaction was rolled back, and NO rows "
            "were persisted. Re-run after fixing the error below.",
            file=sys.stderr,
        )
        print(f"error: archive failed: {exc}", file=sys.stderr)
        _log.exception("archive failed")
        return C.EXIT_RUNTIME

    print(json.dumps(stats.as_dict(), indent=2))
    return C.EXIT_OK


def _cmd_search(args: argparse.Namespace) -> int:
    from . import archive as arch
    from .relational.db import Database, apply_ddl
    from .setup_cmd import ensure_initialized

    if not args.query.strip():
        print("error: empty search query.", file=sys.stderr)
        return C.EXIT_USAGE
    if not ensure_initialized(args.dsn):
        return C.EXIT_USAGE
    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print(
            "error: no database configured. Run setup, pass --db, or set CCT_SA_DB.",
            file=sys.stderr,
        )
        return C.EXIT_USAGE

    try:
        db = Database.connect(cfg.dsn)
        try:
            apply_ddl(db)
            results = arch.search_traces(db, args.query, limit=args.limit)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        print(f"error: search failed: {exc}", file=sys.stderr)
        _log.exception("search failed")
        return C.EXIT_RUNTIME

    print(json.dumps({"query": args.query, "results": results}, indent=2))
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
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
        return C.EXIT_USAGE
    workers = args.workers if args.workers is not None else cfg.judge.workers
    rubric = load_rubric(args.rubric_name)
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
                    only_labelled_by=args.only_labelled_by,
                )
                result = {"judge": f"{family}:{model or '(default)'}", **stats.as_dict()}
            else:
                # Default: per-copilot routing from config (packaged default:
                # local Ollama for every copilot — nothing leaves the machine).
                result = {"by_copilot": run_default_by_copilot(
                    db, rubric, cfg, workers=workers, overwrite=args.overwrite,
                    session_id=args.session_id, limit=args.limit,
                    only_labelled_by=args.only_labelled_by,
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
    result["rubric_name"] = rubric.name
    print(json.dumps(result, indent=2))
    return C.EXIT_OK


def _cmd_labels(args: argparse.Namespace) -> int:
    from .judge import agreement as agr
    from .judge import human_labels as hl
    from .judge.label_sources import UnknownLabelSourceError
    from .relational.db import Database, apply_ddl

    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
        return C.EXIT_USAGE
    try:
        db = Database.connect(cfg.dsn)
        try:
            apply_ddl(db)
            if args.labels_cmd == "sample":
                with open(args.out, "w", newline="", encoding="utf-8") as fp:
                    n = hl.write_sample(
                        db, fp, n=args.n, seed=args.seed, only_labelled_by=args.only_labelled_by
                    )
                result = {"written": n, "out": args.out, "columns": hl.sample_columns()}
            elif args.labels_cmd == "import":
                with open(args.csv, newline="", encoding="utf-8") as fp:
                    result = hl.import_labels(db, fp, labeler=args.labeler)
            elif args.labels_cmd == "runs":
                result = agr.label_runs(db)
            else:
                result = agr.agreement(db, args.a, args.b)
        finally:
            db.close()
    except (UnknownLabelSourceError, hl.HumanLabelImportError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    print(json.dumps(result, indent=2))
    return C.EXIT_OK


def _cmd_embed(args: argparse.Namespace) -> int:
    from .embedding.runner import run_embed
    from .relational.db import Database, apply_ddl

    # CLI flags become the embedding block of extra_overrides — the
    # highest layer of the proven FR-8 precedence. Only keys the user
    # actually passed are included (PRESENCE semantics: --model "" is a
    # value, absence is not).
    cli_embed: dict = {}
    if args.backend is not None:
        cli_embed[C.CFG_EMBEDDING_BACKEND] = args.backend
    if args.model is not None:
        cli_embed[C.CFG_EMBEDDING_MODEL] = args.model
    if args.base_url is not None:
        cli_embed[C.CFG_OLLAMA_URL] = args.base_url
    if args.input_cap is not None:
        cli_embed[C.CFG_EMBEDDING_INPUT_CAP] = args.input_cap

    cfg = load_config(
        dsn=args.dsn,
        extra_overrides={C.CFG_EMBEDDING: cli_embed} if cli_embed else None,
    )
    if not cfg.dsn:
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
        return C.EXIT_USAGE
    try:
        db = Database.connect(cfg.dsn)
        try:
            apply_ddl(db)
            stats = run_embed(
                db, cfg.embedding,
                overwrite=args.overwrite,
                session_id=args.session_id,
                limit=args.limit,
            )
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — a refused pass (probe,
        #                       config) is a runtime error, reported
        #                       plainly with zero writes performed.
        _log.exception("embed failed")
        print(f"error: embed failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    result = {
        "backend": cfg.embedding.backend,
        "configured_model": cfg.embedding.model or "(unset)",
        **stats.as_dict(),
    }
    print(json.dumps(result, indent=2))
    # failed > 0 is a nonzero exit: silent partial success would let a
    # cron-driven pass rot without anyone noticing.
    return C.EXIT_RUNTIME if stats.failed > 0 else C.EXIT_OK


def _cmd_team(args: argparse.Namespace) -> int:
    from .api import team as team_mod
    from .relational.db import Database, apply_ddl

    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
        return C.EXIT_USAGE
    window = cfg.team.active_window_seconds if args.window is None else args.window
    if window <= 0:
        print("error: --window must be a positive number of seconds.", file=sys.stderr)
        return C.EXIT_USAGE
    db = Database.connect(cfg.dsn)
    try:
        apply_ddl(db)
        status = team_mod.team_status(
            db, noise=cfg.noise, active_window_seconds=window, aliases=cfg.team.aliases)
        if args.action == "alerts":
            from .api import alerts as alerts_mod

            report = alerts_mod.all_alerts(
                db, status, budgets=cfg.team.budgets, runaway=cfg.team.runaway, noise=cfg.noise,
            )
    finally:
        db.close()
    if args.action == "alerts":
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            for line in alerts_mod.render_alerts(report):
                print(line)
        worst = alerts_mod.worst_level(report["alerts"])
        # The exit code IS the alarm: a cron job or a pipeline step
        # fails on it. 1, not a usage/runtime code — nothing went wrong.
        return 1 if worst and alerts_mod.at_or_above(worst, args.fail_on) else C.EXIT_OK
    if args.json:
        print(json.dumps(status, indent=2))
        return C.EXIT_OK
    for line in team_mod.render_status(status):
        print(line)
    return C.EXIT_OK


def _cmd_similar(args: argparse.Namespace) -> int:
    from .embedding.similar_runner import (
        GraphNotReadyError, KuzuEdgeStore, run_similar)
    from .graph.schema import GraphDatabase
    from .relational.db import Database

    cli_sim: dict = {}
    if args.threshold is not None:
        cli_sim[C.CFG_SIMILARITY_THRESHOLD] = args.threshold
    if args.top_k is not None:
        cli_sim[C.CFG_SIMILARITY_TOP_K] = args.top_k
    try:
        cfg = load_config(
            dsn=args.dsn, kuzu_path=args.db_path,
            extra_overrides={C.CFG_SIMILARITY: cli_sim} if cli_sim else None,
        )
    except ValueError as exc:
        # a refused knob (nan threshold, fractional top_k, …) is a
        # usage error with a named setting — never a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    if not cfg.dsn:
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
        return C.EXIT_USAGE
    # ABSENT graph: checked BEFORE connect, because GraphDatabase
    # .connect mkdirs and creates — `similar` must never create the
    # store it reconciles (that is `graph`'s job).
    from pathlib import Path as _Path

    if not _Path(cfg.kuzu_path).exists():
        print(
            f"error: graph database absent at {cfg.kuzu_path} — run "
            f"'./scripts/session-analytics graph' first",
            file=sys.stderr)
        return C.EXIT_USAGE
    try:
        db = Database.connect(cfg.dsn)
        try:
            gdb = GraphDatabase.connect(cfg.kuzu_path)
            try:
                stats = run_similar(db, cfg.similarity, KuzuEdgeStore(gdb))
            finally:
                gdb.close()
        finally:
            db.close()
    except GraphNotReadyError as exc:
        # exists but uninitialized: a prerequisite, with guidance.
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    except Exception as exc:  # noqa: BLE001 — a torn pass rolled back;
        #                       the previous edge set stands.
        _log.exception("similar failed")
        print(f"error: similar failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    print(json.dumps(stats.as_dict(), indent=2))
    # invalid stored envelopes are a failed-class condition: something
    # wrote garbage where validated envelopes belong. Surface loudly.
    return C.EXIT_RUNTIME if stats.excluded_invalid else C.EXIT_OK


def _cmd_clusters(args: argparse.Namespace) -> int:
    """Group the stored SIMILAR_TO snapshot into clusters (#289 FR-E).

    READ-ONLY end to end: the absent-path check runs BEFORE any open,
    and the open itself is `connect_read_only`, so this command can
    never create the store it reads — that is `graph`'s job. No DSN is
    required, because nothing here touches the relational store.
    """
    from .embedding.cluster_reader import KuzuGraphSnapshot, run_clusters
    from .embedding.similar_runner import GraphNotReadyError
    from .graph.schema import GraphDatabase

    try:
        cfg = load_config(dsn=args.dsn, kuzu_path=args.db_path)
    except ValueError as exc:
        # a refused knob (nan threshold, fractional top_k, …) is a
        # usage error with a named setting — never a traceback. The
        # graph is not opened at all: configuration is refused first.
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    # ABSENT graph: refused BEFORE connect, with zero filesystem
    # creation. `clusters` must never create the store it reads.
    from pathlib import Path as _Path

    if not cfg.kuzu_path or not _Path(cfg.kuzu_path).exists():
        print(
            f"error: graph database absent at "
            f"{cfg.kuzu_path or '(unset)'} — run "
            f"'./scripts/session-analytics graph' first",
            file=sys.stderr)
        return C.EXIT_USAGE
    try:
        # The exists() check alone is a TOCTOU: a path that disappears
        # between check and open must be REFUSED, never recreated —
        # read_only=True raises rather than touching the filesystem.
        try:
            gdb = GraphDatabase.connect_read_only(cfg.kuzu_path)
        except RuntimeError:
            print(
                f"error: graph database absent or unopenable at "
                f"{cfg.kuzu_path} — run "
                f"'./scripts/session-analytics graph' first",
                file=sys.stderr)
            return C.EXIT_USAGE
        try:
            report = run_clusters(KuzuGraphSnapshot(gdb))
        finally:
            gdb.close()
    except GraphNotReadyError as exc:
        # exists but uninitialized: a prerequisite, with guidance.
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    except ImportError as exc:
        print(
            f"error: the clusters command needs the 'kuzu' package "
            f"(pip install kuzu): {exc}",
            file=sys.stderr,
        )
        return C.EXIT_RUNTIME
    except Exception as exc:  # noqa: BLE001 — a read failure is reported,
        #                      never a traceback; nothing was written.
        _log.exception("clusters failed")
        print(f"error: clusters failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    print(json.dumps(report.as_dict(), indent=2))
    # Zero clusters is a RESULT, not a failure: a ready graph whose
    # stored edges group nothing is healthy and exits 0.
    return C.EXIT_OK


def _cmd_kpis(args: argparse.Namespace) -> int:
    from .judge.kpis import compute_kpis
    from .judge.rubric import load_rubric
    from .relational.db import Database, apply_ddl

    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
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


def _cmd_calibrate(args: argparse.Namespace) -> int:
    """Produce the held-out evaluation report the calibration gates
    read. Shadow-only, like everything in this arc: it writes ONE
    analytics-owned artifact and changes no routing decision."""
    from .routing_calibration import CalibrationError, run_evaluation

    try:
        # load_config belongs INSIDE the handled block: a malformed
        # override (e.g. CCT_SA_CALIBRATION_K=not-an-integer) raises
        # ValueError here, and that is a usage condition with a
        # message that already names the offending key — never a
        # traceback.
        cfg = load_config()
        summary = run_evaluation(cfg)
    except (CalibrationError, ValueError) as exc:
        # a configuration or corpus condition, not a crash — the
        # message names what to fix
        print(f"error: {exc}", file=sys.stderr)
        return C.EXIT_USAGE
    except Exception as exc:  # noqa: BLE001
        _log.exception("calibrate failed")
        print(f"error: calibrate failed: {exc}", file=sys.stderr)
        return C.EXIT_RUNTIME
    print(json.dumps(summary, indent=2, sort_keys=True))
    return C.EXIT_OK


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp import server

    cfg = load_config(dsn=args.dsn)
    if not cfg.dsn:
        print("error: no database configured (see --db or run setup).", file=sys.stderr)
        return C.EXIT_USAGE
    try:
        server.run(cfg.dsn, cfg.kuzu_path)
    except ImportError as exc:
        print(
            f"error: the mcp command needs the 'mcp' package "
            f"(pip install 'mcp>=1.0,<2' — the server targets the v1 "
            f"FastMCP surface): {exc}",
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
    "start": _cmd_start,
    "setup": _cmd_setup,
    "ingest": _cmd_ingest,
    "doctor": _cmd_doctor,
    "graph": _cmd_graph,
    "analyze": _cmd_analyze,
    "labels": _cmd_labels,
    "team": _cmd_team,
    "embed": _cmd_embed,
    "similar": _cmd_similar,
    "clusters": _cmd_clusters,
    "kpis": _cmd_kpis,
    "calibrate": _cmd_calibrate,
    "mcp": _cmd_mcp,
    "serve": _cmd_serve,
    "export": _cmd_export,
    "correlate": _cmd_correlate,
    "archive": _cmd_archive,
    "search": _cmd_search,
    "watch": _cmd_watch,
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
