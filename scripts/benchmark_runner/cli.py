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
            "adapter/backend; 8 subcommand not yet implemented."
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
        help="Backend spec (e.g. 'claude-code:sonnet', 'vllm:llama-3.1-70b', 'stub').",
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

    # ── dogfood ───────────────────────────────────────────────────────
    p_dogfood = sub.add_parser(
        "dogfood",
        help="Run Aider Polyglot dogfood subset and compare to leaderboard (Phase 4).",
    )
    p_dogfood.add_argument(
        "--backend",
        required=True,
        help="Backend spec to dogfood (typically 'claude-code:sonnet').",
    )
    p_dogfood.add_argument("--runs", type=int, default=1)

    return parser


# ── Subcommand handlers ────────────────────────────────────────────────


def _cmd_list(args: argparse.Namespace) -> int:
    if args.benchmark is not None:
        # Phase 1+: list adapter tasks. Phase 0 stubs out.
        print(
            f"benchmark: listing tasks for an adapter is Phase 1+ (got --benchmark "
            f"{args.benchmark!r}); see specs/benchmark-harness/plan.md.",
            file=sys.stderr,
        )
        return EXIT_NOT_IMPLEMENTED

    payload = {
        "adapters": list_adapter_ids(),
        "backends": list_backend_ids(),
    }
    print(json.dumps(payload, indent=2))
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    # Phase 0 reports unknown adapter/backend cleanly even though the
    # registries are empty — the user gets a discoverable error path
    # before Phase 1 lands the real orchestration.
    try:
        from .registry import get_adapter, get_backend  # local: keeps import-time clean

        get_adapter(args.benchmark)
        get_backend(args.backend)
    except (UnknownAdapterError, UnknownBackendError) as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"benchmark: run orchestration lands in Phase 1 "
        f"(--benchmark {args.benchmark!r} --backend {args.backend!r} "
        f"--runs {args.runs}); see specs/benchmark-harness/plan.md.",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


def _cmd_report(args: argparse.Namespace) -> int:
    if not args.run_dir.exists():
        print(f"benchmark: run-dir not found: {args.run_dir}", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"benchmark: report aggregation lands in Phase 1 "
        f"(--run-dir {args.run_dir}); see specs/benchmark-harness/plan.md.",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


def _cmd_dogfood(args: argparse.Namespace) -> int:
    print(
        f"benchmark: dogfood subcommand lands in Phase 4 "
        f"(--backend {args.backend!r} --runs {args.runs}); "
        f"see specs/benchmark-harness/plan.md.",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


_HANDLERS = {
    "list": _cmd_list,
    "run": _cmd_run,
    "report": _cmd_report,
    "dogfood": _cmd_dogfood,
}


def main(argv: Sequence[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv))
    handler = _HANDLERS[args.subcommand]
    return handler(args)
