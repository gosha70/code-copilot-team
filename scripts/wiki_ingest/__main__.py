# wiki_ingest.__main__ — CLI entrypoint for the wiki ingest pipeline.
#
# Invoked indirectly via the ``scripts/wiki-ingest`` Bash wrapper, which
# sets ``PYTHONPATH=<repo>/scripts`` and ``exec``s ``python3 -m wiki_ingest``.
# The module-form invocation is required so relative imports inside the
# package resolve.
#
# Exit codes (stable across v1 — see knowledge/README.md "Running ingest"):
#   0 — successful run; proposal file written (accept or reject).
#   2 — backend not found (no resolver match, or named CLI not on PATH).
#   3 — backend invocation failed (non-zero exit, timeout, OS error).
#   4 — contract violation (backend response failed shape or semantic
#       cross-consistency validation).
#   5 — source file missing or unreadable.
#   6 — output directory write failure.

from __future__ import annotations

import argparse
import datetime
import sys
from dataclasses import replace
from pathlib import Path

from .backends import resolve_backend
from .errors import (
    BackendInvocationError,
    BackendNotFoundError,
    ContractViolationError,
    OutputWriteError,
    SourceMissingError,
)
from .ingestor import DefaultIngestor
from .proposal import IngestProposal, IngestRequest, render_proposal_file

_DEFAULT_OUTPUT_DIR = Path("doc_internal/proposals")


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the argparse parser. ``--help`` text is part of the public CLI surface."""
    parser = argparse.ArgumentParser(
        prog="wiki-ingest",
        description=(
            "Run the four-question gate against a source file and write a "
            "typed wiki-page proposal to doc_internal/proposals/. Human "
            "approval remains gating; the pipeline never writes to "
            "knowledge/wiki/."
        ),
        epilog=(
            "Exit codes: 0 success (accept or reject); "
            "2 backend not found; 3 backend invocation failed; "
            "4 contract violation; 5 source missing; "
            "6 output write failure."
        ),
    )
    parser.add_argument(
        "source",
        type=Path,
        help=(
            "Path to the source file (typically a merged spec, incident "
            "write-up, or other artifact eligible for promotion)."
        ),
    )
    parser.add_argument(
        "--backend",
        default=None,
        help=(
            "Backend name. One of: claude, codex, cursor, test. "
            "Defaults to WIKI_INGEST_BACKEND env var, then auto-detect "
            "(claude → codex → cursor)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run the gate but omit the draft body from the proposal "
            "file. Frontmatter still records gate_disposition and "
            "gate_reason so a curator can see what the gate decided "
            "without committing to the full draft."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            f"Override the output directory. Default: "
            f"<repo>/{_DEFAULT_OUTPUT_DIR}/."
        ),
    )
    return parser


def _resolve_repo_root() -> Path:
    """Return the repo root.

    ``__file__`` is ``<repo>/scripts/wiki_ingest/__main__.py``. Three
    ``.parent`` hops land on the repo root. This holds whether the
    package is invoked via ``python3 -m wiki_ingest`` or via the Bash
    entrypoint, because in both cases the package files live at the
    same on-disk location.
    """
    return Path(__file__).resolve().parent.parent.parent


def _backend_display_name(backend: object, cli_flag: str | None) -> str:
    """Best-effort name for the resolved backend, recorded in proposal frontmatter.

    Used for the proposal file's ``backend:`` field. Order of preference:

    1. The explicit ``--backend`` value (if the user named it, that's
       canonical).
    2. The backend instance's ``_cli_name`` attribute (set by
       ``CopilotCliBackend``).
    3. A class-name-derived fallback (e.g., ``TestBackend`` → ``test``).
    """
    if cli_flag:
        return cli_flag
    cli_name = getattr(backend, "_cli_name", None)
    if cli_name:
        return str(cli_name)
    cls_name = backend.__class__.__name__
    return cls_name.removesuffix("Backend").lower() or "unknown"


def _make_proposal_filename(proposal: IngestProposal) -> str:
    """Compose the proposal filename: ``<YYYY-MM-DD>-<slug>.md``.

    Reject proposals (and other slugless cases) fall back to
    ``unslugged-<disposition>`` so the filename is still informative.
    """
    today = datetime.date.today().isoformat()
    base = proposal.slug or f"unslugged-{proposal.disposition}"
    return f"{today}-{base}.md"


def _write_proposal_file(
    proposal: IngestProposal,
    request: IngestRequest,
    backend_name: str,
    output_dir: Path,
) -> Path:
    """Render and write the proposal file. Returns the absolute path written.

    Raises OutputWriteError on any filesystem failure; the CLI maps that
    to exit code 6.
    """
    proposal_path = output_dir / _make_proposal_filename(proposal)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        body = render_proposal_file(proposal, request, backend_name)
        proposal_path.write_text(body, encoding="utf-8")
    except OSError as exc:
        raise OutputWriteError(
            f"Could not write proposal file at {proposal_path}: {exc}"
        ) from exc
    return proposal_path.resolve()


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the exit code; never raises (errors are mapped)."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    # Source must exist before we even spin up a backend. The ingestor
    # also checks this; we check here too so unknown-source failures
    # do not pay the cost of backend resolution.
    source_path: Path = args.source
    if not source_path.exists():
        print(f"error: source file not found: {source_path}", file=sys.stderr)
        return SourceMissingError.exit_code

    # Resolve backend (--backend → WIKI_INGEST_BACKEND env → auto-detect).
    try:
        backend = resolve_backend(args.backend)
    except BackendNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return BackendNotFoundError.exit_code

    backend_name = _backend_display_name(backend, args.backend)
    repo_root = _resolve_repo_root()
    ingestor = DefaultIngestor(backend=backend, repo_root=repo_root)

    request = IngestRequest(
        source_path=source_path,
        source_kind="file",
        backend_name=backend_name,
    )

    try:
        proposal = ingestor.ingest(request)
    except SourceMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return SourceMissingError.exit_code
    except BackendNotFoundError as exc:
        # Reachable if a backend constructor lazily probes PATH and the
        # CLI vanishes between resolve_backend() and ingest(). Map the
        # same way as the eager-resolve path.
        print(f"error: {exc}", file=sys.stderr)
        return BackendNotFoundError.exit_code
    except BackendInvocationError as exc:
        print(f"error: backend invocation failed: {exc}", file=sys.stderr)
        return BackendInvocationError.exit_code
    except ContractViolationError as exc:
        print(f"error: contract violation: {exc}", file=sys.stderr)
        return ContractViolationError.exit_code

    # Dry-run is render-side: the backend has already produced a full
    # response (and we paid the cost), but the proposal file omits the
    # draft body. v1 chose the render-side semantics deliberately —
    # see specs/wiki-ingest-pipeline/spec.md "CLI surface". Backends do
    # NOT receive a dry-run hint in v1; revisit if real-LLM cost matters.
    if args.dry_run:
        proposal = replace(proposal, draft_markdown=None)

    output_dir: Path = args.output_dir or (repo_root / _DEFAULT_OUTPUT_DIR)
    try:
        proposal_path = _write_proposal_file(
            proposal, request, backend_name, output_dir
        )
    except OutputWriteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return OutputWriteError.exit_code

    # The spec says: print the absolute path of the proposal file on
    # both accept and reject. A reject is a successful pipeline outcome
    # (the gate did its job), so it still exits 0 with the path on stdout.
    print(str(proposal_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
