# benchmark_runner.cli — argparse subcommands and main() entrypoint.
#
# Subcommands:
#   list                 — print registered adapters and backends.
#   run                  — Phase 1+: run a benchmark against a backend.
#   report --run-dir     — Phase 1+: aggregate a run directory.
#   dogfood --backend    — Phase 4: Aider Polyglot vs leaderboard.
#
# Phase 0 implements:
#   - ``list`` (returns empty arrays cleanly when no adapter/backend
#     is registered);
#   - ``run`` and ``report`` and ``dogfood`` skeletons that error with
#     EXIT_NOT_IMPLEMENTED when invoked, after argument validation.
#
# Exit codes:
#   0 — successful invocation.
#   2 — usage error (argparse) or unknown adapter/backend.
#   8 — verb not yet implemented (Phase N stub).

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .registry import (
    UnknownAdapterError,
    UnknownBackendError,
    list_adapter_ids,
    list_backend_ids,
)


# Stable exit codes; documented in the bash wrapper and in spec.md.
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RUNTIME = 3
EXIT_NOT_IMPLEMENTED = 8


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="benchmark",
        description=(
            "CCT benchmark harness. Runs public coding benchmarks "
            "(Aider Polyglot, SWE-bench Verified, ...) and custom CCT "
            "fixtures under reproducible isolation, with deterministic "
            "scoring and SDD-aware run records. See "
            "specs/benchmark-harness/spec.md."
        ),
        epilog=(
            "Exit codes: 0 success; 2 usage error or unknown "
            "adapter/backend; 3 runtime failure during run/report; "
            "8 subcommand not yet implemented."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", required=True, metavar="<subcommand>")

    # ── list ──────────────────────────────────────────────────────────
    p_list = sub.add_parser(
        "list",
        help="List registered adapters and backends.",
    )
    p_list.add_argument(
        "--benchmark",
        help="If set, list tasks for the given benchmark adapter "
             "(Phase 1+; Phase 0 errors NOT_IMPLEMENTED).",
    )

    # ── run ───────────────────────────────────────────────────────────
    p_run = sub.add_parser(
        "run",
        help="Run a benchmark against a backend (Phase 1+).",
    )
    p_run.add_argument("--benchmark", required=True, help="Benchmark adapter id.")
    p_run.add_argument(
        "--backend",
        required=True,
        help="Backend family (e.g. 'claude-code', 'stub'). Backends are "
             "agentic copilot CLIs; provider routing is configured separately "
             "via the backend's own gateway env vars (e.g. ANTHROPIC_BASE_URL "
             "for claude-code). The harness records but does not set them.",
    )
    p_run.add_argument(
        "--model",
        default="",
        help="Model identifier passed to the backend (e.g. 'sonnet', 'opus', "
             "'claude-sonnet-4-6'). The stub backend takes no model.",
    )
    p_run.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of repetitions per task (default 1).",
    )
    p_run.add_argument(
        "--task",
        action="append",
        default=None,
        help="Limit to specific task ids (repeatable).",
    )
    p_run.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs"),
        help="Directory under which run records are written (default ./runs).",
    )

    # ── report ────────────────────────────────────────────────────────
    p_report = sub.add_parser(
        "report",
        help="Aggregate a run directory into a Markdown + JSON report (Phase 1+).",
    )
    p_report.add_argument("--run-dir", required=True, type=Path)

    # ── compare ───────────────────────────────────────────────────────
    p_compare = sub.add_parser(
        "compare",
        help=(
            "Run a benchmark against multiple LLMs sequentially and "
            "aggregate the report (one shared run-dir per invocation). "
            "See benchmarks/compare-config.example.json for the config "
            "shape and benchmarks/README.md § 'Quick start: compare "
            "multiple LLMs' for an end-to-end walkthrough."
        ),
    )
    p_compare.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a compare-config JSON file. Must list ≥2 candidates.",
    )
    p_compare.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs"),
        help="Directory under which the compare run-dir is created (default ./runs).",
    )
    p_compare.add_argument(
        "--no-report",
        action="store_true",
        help="Skip auto-emitting the aggregate report; you can run "
             "`./scripts/benchmark report --run-dir <path>` later.",
    )

    # ── dogfood ───────────────────────────────────────────────────────
    p_dogfood = sub.add_parser(
        "dogfood",
        help="Run Aider Polyglot dogfood subset for the chosen backend (Gate 1 liveness).",
    )
    p_dogfood.add_argument(
        "--backend",
        required=True,
        help="Backend family to dogfood (typically 'claude-code').",
    )
    p_dogfood.add_argument(
        "--model",
        default="",
        help="Model identifier (typically 'sonnet').",
    )
    p_dogfood.add_argument("--runs", type=int, default=1)
    p_dogfood.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs"),
        help="Directory under which run records are written (default ./runs).",
    )

    return parser


# ── Subcommand handlers ────────────────────────────────────────────────


def _cmd_list(args: argparse.Namespace) -> int:
    if args.benchmark is not None:
        from .registry import get_adapter

        try:
            adapter = get_adapter(args.benchmark)
        except UnknownAdapterError as exc:
            print(f"benchmark: {exc}", file=sys.stderr)
            return EXIT_USAGE
        tasks = [
            {"task_id": t.task_id, "language": t.language}
            for t in adapter.list_tasks()
        ]
        print(json.dumps({"benchmark_id": args.benchmark, "tasks": tasks}, indent=2))
        return EXIT_OK

    payload = {
        "adapters": list_adapter_ids(),
        "backends": list_backend_ids(),
    }
    print(json.dumps(payload, indent=2))
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    from .registry import get_adapter, get_backend

    # Hint when the user passes the deprecated combined form
    # ``--backend foo:bar`` (matches the report's display label
    # convention but is NOT the CLI input format). Surface a
    # specific suggestion before the generic "unknown backend
    # family" message.
    if ":" in args.backend:
        family, _, model_in_backend = args.backend.partition(":")
        print(
            f"benchmark: --backend {args.backend!r} uses the deprecated "
            f"combined form. Use separate flags: "
            f"--backend {family!r} --model {model_in_backend!r}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        get_adapter(args.benchmark)
        get_backend(args.backend, args.model)
    except (UnknownAdapterError, UnknownBackendError) as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE

    from .run import EmptyAdapterError, run_benchmark

    try:
        run_dir = run_benchmark(
            args.benchmark,
            args.backend,
            args.model,
            runs=args.runs,
            runs_root=args.runs_root,
            task_filter=args.task,
        )
    except EmptyAdapterError as exc:
        # Distinct from "unknown task id" (KeyError) — no tasks at all.
        # Surfaced as USAGE so a missing fetch doesn't masquerade as a
        # successful benchmark run.
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyError as exc:  # unknown task ids
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except NotImplementedError as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    except Exception as exc:  # noqa: BLE001 — runtime failure path
        print(f"benchmark: run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    print(json.dumps({"run_dir": str(run_dir)}, indent=2))
    return EXIT_OK


def _cmd_report(args: argparse.Namespace) -> int:
    if not args.run_dir.exists():
        print(f"benchmark: run-dir not found: {args.run_dir}", file=sys.stderr)
        return EXIT_USAGE

    from .report import render_report

    try:
        report_path = render_report(args.run_dir)
    except FileNotFoundError as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001
        print(f"benchmark: report failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    print(json.dumps({"report_md": str(report_path)}, indent=2))
    return EXIT_OK


def _cmd_compare(args: argparse.Namespace) -> int:
    """Multi-LLM comparison driver.

    Reads a JSON compare-config, validates the adapter + each candidate's
    backend up front, then orchestrates sequential per-candidate runs
    under one shared parent run-dir and (by default) renders the
    aggregate report. Failure of any single candidate aborts the
    comparison and leaves prior candidates' run-dirs on disk for
    postmortem.
    """
    if not args.config.exists():
        print(f"benchmark: compare-config not found: {args.config}", file=sys.stderr)
        return EXIT_USAGE

    from .compare import CompareConfigError, load_config, run_comparison
    from .registry import get_adapter, get_backend
    from .run import EmptyAdapterError

    try:
        config = load_config(args.config)
    except CompareConfigError as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE

    # Validate every candidate up front so a typo in candidate[5] does
    # not waste the wall time of candidates[0..4].
    try:
        get_adapter(config.benchmark)
        for c in config.candidates:
            get_backend(c.backend, c.model)
    except (UnknownAdapterError, UnknownBackendError) as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE

    try:
        run_dir = run_comparison(
            config,
            runs_root=args.runs_root,
            emit_report=not args.no_report,
        )
    except EmptyAdapterError as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyError as exc:  # unknown task ids in config.task
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except NotImplementedError as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    except Exception as exc:  # noqa: BLE001 — runtime failure path
        print(f"benchmark: compare failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    payload: dict[str, str] = {"run_dir": str(run_dir)}
    if not args.no_report:
        payload["report_md"] = str(run_dir / "report.md")
    print(json.dumps(payload, indent=2))
    return EXIT_OK


def _cmd_dogfood(args: argparse.Namespace) -> int:
    """T4.3 — Gate 1 liveness: run the Polyglot adapter against the
    committed dogfood subset for the chosen backend, then aggregate.

    Gate 2 (verdict correctness via the rlmkit#38/#41 retrospective)
    is exercised separately against the ``cct-dogfood-rlmkit`` adapter
    via ``./scripts/benchmark run --benchmark cct-dogfood-rlmkit ...``.
    See spec.md § Dogfood gate for the two-gate structure.
    """
    from .registry import get_adapter, get_backend

    if ":" in args.backend:
        family, _, model_in_backend = args.backend.partition(":")
        print(
            f"benchmark: --backend {args.backend!r} uses the deprecated "
            f"combined form. Use separate flags: "
            f"--backend {family!r} --model {model_in_backend!r}",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        get_adapter("aider-polyglot")
        get_backend(args.backend, args.model)
    except (UnknownAdapterError, UnknownBackendError) as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE

    # Load the committed dogfood subset (12 task IDs, ≥1 per language).
    from benchmarks.adapters.aider_polyglot.adapter import load_dogfood_subset
    subset = load_dogfood_subset()
    if not subset:
        print(
            "benchmark: dogfood subset is empty — check "
            "benchmarks/adapters/aider_polyglot/dogfood-subset.txt",
            file=sys.stderr,
        )
        return EXIT_RUNTIME

    from .run import EmptyAdapterError, run_benchmark

    try:
        run_dir = run_benchmark(
            "aider-polyglot",
            args.backend,
            args.model,
            runs=args.runs,
            runs_root=args.runs_root,
            task_filter=subset,
        )
    except EmptyAdapterError as exc:
        # Polyglot cache absent. Tell the user how to fix it.
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyError as exc:
        # Some dogfood-subset task id doesn't resolve in the cache —
        # likely the subset references tasks not in the upstream pin.
        print(
            f"benchmark: {exc}\n"
            f"  hint: dogfood-subset.txt may reference task IDs missing "
            f"from the pinned upstream cache. Run "
            f"`python3 -m benchmarks.adapters.aider_polyglot.fetch` to "
            f"refresh, or update dogfood-subset.txt.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    except Exception as exc:  # noqa: BLE001
        print(
            f"benchmark: dogfood run failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_RUNTIME

    # Aggregate the just-completed run. With one (backend, model) group
    # in the run-dir, the verdicts section will be empty — Gate 1 is
    # liveness, not comparison.
    from .report import render_report
    try:
        report_path = render_report(run_dir)
    except Exception as exc:  # noqa: BLE001
        print(
            f"benchmark: dogfood report failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_RUNTIME

    print(json.dumps({
        "run_dir": str(run_dir),
        "report_md": str(report_path),
        "tasks_run": len(subset),
        "note": (
            "Gate 1 (liveness) only. Gate 2 (rlmkit#38/#41 retrospective "
            "verdict-correctness) is run via cct-dogfood-rlmkit; see "
            "specs/benchmark-harness/spec.md § Dogfood gate."
        ),
    }, indent=2))
    return EXIT_OK


_HANDLERS = {
    "list": _cmd_list,
    "run": _cmd_run,
    "report": _cmd_report,
    "compare": _cmd_compare,
    "dogfood": _cmd_dogfood,
}


def main(argv: Sequence[str]) -> int:
    # Register the shipped adapters and backends. Idempotent; the test
    # suite uses ``benchmark_runner._register.unregister_all_for_tests``
    # plus its own selective registration to avoid coupling tests to
    # the shipped set.
    from ._register import register_all
    register_all()

    parser = _build_parser()
    args = parser.parse_args(list(argv))
    handler = _HANDLERS[args.subcommand]
    return handler(args)
