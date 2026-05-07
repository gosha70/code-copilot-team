# wiki_ingest.__main__ — verb-dispatching CLI entrypoint for the wiki pipeline.
#
# Phase 0 ships the four-verb skeleton (ingest|promote|query|lint) and the
# Stage-1 single-source proposal generator behind ``ingest --legacy-single-source``.
# Phases 1–4 implement the multi-page ingest, promote, query, and
# knowledge-health lint operations on top of the same package.
#
# Invoked indirectly via:
#   - ``scripts/wiki <verb> ...``           — primary entrypoint (Phase 0+)
#   - ``scripts/wiki-ingest <source> ...``  — backwards-compat alias for
#                                             ``wiki ingest --legacy-single-source``
#
# Both wrappers set ``PYTHONPATH=<repo>/scripts`` and ``exec``
# ``python3 -m wiki_ingest <verb> <args>``. Module-form invocation is
# required so relative imports inside the package resolve.
#
# Exit codes (stable across v1; new exit code 7 added in Phase 0):
#   0 — successful run; proposal file written (accept or reject), or
#       structural lint clean, etc.
#   2 — backend not found (no resolver match, or named CLI not on PATH).
#   3 — backend invocation failed (non-zero exit, timeout, OS error).
#   4 — contract violation (backend response failed shape or semantic
#       cross-consistency validation).
#   5 — source file missing or unreadable.
#   6 — output directory write failure.
#   7 — source path outside the repo (use --allow-out-of-repo to override).
#   8 — verb not yet implemented (Phase N stub).

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from .backends import resolve_backend
from .errors import (
    BackendInvocationError,
    BackendNotFoundError,
    ContractViolationError,
    OutputWriteError,
    PromoteApplyError,
    PromoteValidationError,
    SourceMissingError,
)
from .ingestor import DefaultIngestor
from .ingestor_multi import DefaultMultiIngestor, write_patch_set_dir
from .health_lint import lint_health
from .promoter import promote as run_promote
from .proposal import IngestProposal, IngestRequest, render_proposal_file
from .querier import DefaultQuerier

_DEFAULT_OUTPUT_DIR = Path("doc_internal/proposals")

# Exit codes new in Phase 0.
EXIT_PATH_OUT_OF_REPO = 7
EXIT_NOT_IMPLEMENTED = 8


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the verb-dispatching parser. ``--help`` text is the public CLI surface."""
    parser = argparse.ArgumentParser(
        prog="wiki",
        description=(
            "Karpathy-pattern LLM Wiki maintainer. Four verbs: "
            "ingest|promote|query|lint. See specs/wiki-ingest-pipeline/ "
            "for the full spec; ``./scripts/wiki <verb> --help`` for "
            "per-verb help."
        ),
        epilog=(
            "Exit codes (stable across v1): "
            "0 success; 2 backend not found; 3 backend invocation failed; "
            "4 contract violation; 5 source missing; 6 output write failure; "
            "7 source out of repo; 8 verb not yet implemented (Phase N stub)."
        ),
    )
    sub = parser.add_subparsers(dest="verb", required=True, metavar="<verb>")

    # ── ingest ─────────────────────────────────────────────────
    p_ingest = sub.add_parser(
        "ingest",
        help="Run the ingest gate against a source file. "
             "Phase 0: requires --legacy-single-source for the v1 path; "
             "multi-page ingest lands in Phase 1.",
    )
    p_ingest.add_argument(
        "source",
        type=Path,
        help="Path to the source file to ingest.",
    )
    p_ingest.add_argument(
        "--legacy-single-source",
        action="store_true",
        help="Run the v1 single-source proposal generator. Required in "
             "Phase 0 (multi-page ingest is Phase 1).",
    )
    p_ingest.add_argument(
        "--backend",
        default=None,
        help="Backend name. One of: claude, codex, cursor, test. "
             "Defaults to WIKI_INGEST_BACKEND env var, then auto-detect.",
    )
    p_ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Real dry-run: passes task=gate-only to the backend so it "
             "skips drafting the body. Saves model tokens and latency. "
             "Render also strips any body the backend returns as a safety "
             "net for non-honoring stubs.",
    )
    p_ingest.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Override the output directory. Default: <repo>/{_DEFAULT_OUTPUT_DIR}/.",
    )
    p_ingest.add_argument(
        "--debug-unsafe-output",
        action="store_true",
        help="Disable stderr redaction in error messages. Default: "
             "redacted (sha256 fingerprint only). Use only for local "
             "debugging — backend stderr can echo source content.",
    )
    p_ingest.add_argument(
        "--allow-out-of-repo",
        action="store_true",
        help="Allow source paths outside the repository tree. Default: "
             "refuse (exit 7). Use only when ingesting external artifacts "
             "deliberately.",
    )

    # ── promote ────────────────────────────────────────────────
    p_promote = sub.add_parser(
        "promote",
        help="Apply a proposal patch-set to knowledge/wiki/ atomically. "
             "The ONLY code path that writes to knowledge/wiki/.",
    )
    p_promote.add_argument(
        "proposal_dir",
        type=Path,
        help="Path to a doc_internal/proposals/<date>-<slug>/ directory "
             "produced by `./scripts/wiki ingest`.",
    )
    p_promote.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and validate the staged tree but do not commit to "
             "knowledge/wiki/ and do not move the proposals dir to "
             ".applied/. Exits 0 on a clean stage.",
    )

    # ── query ──────────────────────────────────────────────────
    p_query = sub.add_parser(
        "query",
        help="Answer a question by reading the wiki, index-first.",
    )
    p_query.add_argument(
        "question",
        help="The question to answer against the wiki.",
    )
    p_query.add_argument(
        "--file-back",
        action="store_true",
        help="In addition to printing the answer, run a multi-page "
             "ingest over a synthetic source built from the question + "
             "answer, producing a patch-set under doc_internal/proposals/. "
             "The curator reviews and runs `wiki promote` to land it.",
    )
    p_query.add_argument(
        "--backend",
        default=None,
        help="Backend name (claude / codex / cursor / test). Defaults "
             "to WIKI_INGEST_BACKEND env var, then auto-detect.",
    )
    p_query.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Max number of wiki pages to load into the query prompt. "
             "Default 5 (DEFAULT_MAX_QUERY_PAGES).",
    )
    p_query.add_argument(
        "--debug-unsafe-output",
        action="store_true",
        help="Disable stderr redaction in error messages (see ingest).",
    )
    p_query.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="When --file-back: override the proposals directory.",
    )

    # ── lint ───────────────────────────────────────────────────
    p_lint = sub.add_parser(
        "lint",
        help="Run wiki linters. Default: structural (delegates to "
             "knowledge/wiki/scripts/lint-wiki.sh). --health adds "
             "the knowledge-health pass (contradictions, stale claims, "
             "weak orphans, missing cross-links).",
    )
    p_lint.add_argument(
        "--health",
        action="store_true",
        help="Run knowledge-health checks on top of the structural "
             "linter. Default mode is advisory (exit 0 with stderr "
             "warnings); --strict flips to non-zero exit on findings.",
    )
    p_lint.add_argument(
        "--strict",
        action="store_true",
        help="With --health: any finding causes non-zero exit.",
    )
    p_lint.add_argument(
        "--paths",
        nargs="*",
        default=None,
        help="With --health: scope to specific wiki-relative paths.",
    )
    p_lint.add_argument(
        "--backend",
        default=None,
        help="With --health: backend for the LLM-dependent "
             "contradiction check. When omitted, contradictions are "
             "skipped (the other three checks run without a backend).",
    )

    return parser


def _resolve_repo_root() -> Path:
    """Return the repo root.

    ``__file__`` is ``<repo>/scripts/wiki_ingest/__main__.py``. Three
    ``.parent`` hops land on the repo root. This holds whether the
    package is invoked via ``python3 -m wiki_ingest`` or via the Bash
    entrypoints, because in both cases the package files live at the
    same on-disk location.
    """
    return Path(__file__).resolve().parent.parent.parent


def _backend_display_name(backend: object, cli_flag: str | None) -> str:
    """Best-effort name for the resolved backend, recorded in proposal frontmatter."""
    if cli_flag:
        return cli_flag
    cli_name = getattr(backend, "_cli_name", None)
    if cli_name:
        return str(cli_name)
    cls_name = backend.__class__.__name__
    return cls_name.removesuffix("Backend").lower() or "unknown"


def _make_proposal_filename(proposal: IngestProposal) -> str:
    """Compose the proposal filename: ``<YYYY-MM-DD>-<slug>.md``."""
    today = datetime.date.today().isoformat()
    base = proposal.slug or f"unslugged-{proposal.disposition}"
    return f"{today}-{base}.md"


def _write_proposal_file(
    proposal: IngestProposal,
    request: IngestRequest,
    backend_name: str,
    output_dir: Path,
) -> Path:
    """Render and write the proposal file. Returns the absolute path written."""
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


def _path_within_repo(source: Path, repo_root: Path) -> bool:
    """True if ``source`` resolves to a path inside ``repo_root``."""
    try:
        source.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


# ── Verb implementations ──────────────────────────────────────


def _do_ingest(args: argparse.Namespace) -> int:
    """Route to legacy single-source ingest or Phase-1 multi-page ingest.

    --legacy-single-source preserves the v1 IngestProposal flow.
    Without the flag, Phase-1 DefaultMultiIngestor produces a
    WikiPatchSet under doc_internal/proposals/<date>-<slug>/.
    """
    if not args.legacy_single_source:
        return _do_ingest_multi(args)

    repo_root = _resolve_repo_root()

    # Source must exist; check before paying backend resolution cost.
    source_path: Path = args.source
    if not source_path.exists():
        print(f"error: source file not found: {source_path}", file=sys.stderr)
        return SourceMissingError.exit_code

    # Repo-root path confinement (T0.7). The default refuses external paths;
    # --allow-out-of-repo is the explicit opt-in.
    if not args.allow_out_of_repo and not _path_within_repo(source_path, repo_root):
        print(
            f"error: source path is outside the repository tree: {source_path}\n"
            f"  Repo root: {repo_root}\n"
            f"  Pass --allow-out-of-repo to override (only when ingesting "
            f"external artifacts deliberately).",
            file=sys.stderr,
        )
        return EXIT_PATH_OUT_OF_REPO

    # Resolve backend (--backend → WIKI_INGEST_BACKEND env → auto-detect).
    try:
        backend = resolve_backend(args.backend)
    except BackendNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return BackendNotFoundError.exit_code

    # Stderr redaction default (T0.5). The backend has its own redact_output
    # parameter; flip it on this instance.
    if args.debug_unsafe_output and hasattr(backend, "_redact_output"):
        backend._redact_output = False

    backend_name = _backend_display_name(backend, args.backend)
    ingestor = DefaultIngestor(backend=backend, repo_root=repo_root)

    request = IngestRequest(
        source_path=source_path,
        source_kind="file",
        backend_name=backend_name,
    )

    # Pass dry-run intent through to the prompt (T0.6 — real --dry-run).
    # The compose_prompt path picks up task="gate-only" via os.environ; the
    # render side still strips the body as a safety net for stubs that ignore
    # the task hint. This keeps the v1 stub behavior intact while letting
    # real LLM backends save tokens.
    env_backup = os.environ.get("WIKI_INGEST_TASK")
    if args.dry_run:
        os.environ["WIKI_INGEST_TASK"] = "gate-only"
    try:
        proposal = ingestor.ingest(request)
    except SourceMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return SourceMissingError.exit_code
    except BackendNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return BackendNotFoundError.exit_code
    except BackendInvocationError as exc:
        print(f"error: backend invocation failed: {exc}", file=sys.stderr)
        return BackendInvocationError.exit_code
    except ContractViolationError as exc:
        print(f"error: contract violation: {exc}", file=sys.stderr)
        return ContractViolationError.exit_code
    finally:
        if env_backup is None:
            os.environ.pop("WIKI_INGEST_TASK", None)
        else:
            os.environ["WIKI_INGEST_TASK"] = env_backup

    # Render-side body strip is the safety net: stubs that ignore the
    # gate-only task still produce body text; we drop it here so the
    # proposal file matches the dry-run contract.
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

    print(str(proposal_path))
    return 0


def _do_ingest_multi(args: argparse.Namespace) -> int:
    """Phase-1 multi-page ingest: source → WikiPatchSet → proposals/<date>-<slug>/."""
    repo_root = _resolve_repo_root()

    source_path: Path = args.source
    if not source_path.exists():
        print(f"error: source file not found: {source_path}", file=sys.stderr)
        return SourceMissingError.exit_code

    if not args.allow_out_of_repo and not _path_within_repo(source_path, repo_root):
        print(
            f"error: source path is outside the repository tree: {source_path}\n"
            f"  Repo root: {repo_root}\n"
            f"  Pass --allow-out-of-repo to override.",
            file=sys.stderr,
        )
        return EXIT_PATH_OUT_OF_REPO

    try:
        backend = resolve_backend(args.backend)
    except BackendNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return BackendNotFoundError.exit_code

    if args.debug_unsafe_output and hasattr(backend, "_redact_output"):
        backend._redact_output = False

    backend_name = _backend_display_name(backend, args.backend)
    multi = DefaultMultiIngestor(backend=backend, repo_root=repo_root)

    request = IngestRequest(
        source_path=source_path,
        source_kind="file",
        backend_name=backend_name,
    )

    env_backup = os.environ.get("WIKI_INGEST_TASK")
    if args.dry_run:
        os.environ["WIKI_INGEST_TASK"] = "gate-only"
    try:
        patch = multi.ingest_multi(request)
    except SourceMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return SourceMissingError.exit_code
    except BackendNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return BackendNotFoundError.exit_code
    except BackendInvocationError as exc:
        print(f"error: backend invocation failed: {exc}", file=sys.stderr)
        return BackendInvocationError.exit_code
    except ContractViolationError as exc:
        print(f"error: contract violation: {exc}", file=sys.stderr)
        return ContractViolationError.exit_code
    finally:
        if env_backup is None:
            os.environ.pop("WIKI_INGEST_TASK", None)
        else:
            os.environ["WIKI_INGEST_TASK"] = env_backup

    # Output dir: doc_internal/proposals/<date>-<source-stem>/
    today = datetime.date.today().isoformat()
    source_stem = source_path.stem or "source"
    proposal_root: Path = args.output_dir or (repo_root / _DEFAULT_OUTPUT_DIR)
    output_dir = proposal_root / f"{today}-{source_stem}"

    try:
        written = write_patch_set_dir(patch, output_dir)
    except OSError as exc:
        print(
            f"error: could not write patch-set dir at {output_dir}: {exc}",
            file=sys.stderr,
        )
        return OutputWriteError.exit_code

    if not patch.edits:
        # Gate rejected the source; surface the rationale.
        print(f"{written}  (gate rejected, 0 edits)")
        print(f"  rationale: {patch.rationale}", file=sys.stderr)
        return 0
    print(str(written))
    return 0


def _do_promote(args: argparse.Namespace) -> int:
    """Phase 2: atomic patch-set application — the only writer to knowledge/wiki/."""
    repo_root = _resolve_repo_root()
    proposals_dir: Path = args.proposal_dir
    if not proposals_dir.exists():
        print(
            f"error: proposals dir not found: {proposals_dir}",
            file=sys.stderr,
        )
        return SourceMissingError.exit_code

    try:
        result = run_promote(
            proposals_dir=proposals_dir,
            repo_root=repo_root,
            dry_run=args.dry_run,
        )
    except PromoteValidationError as exc:
        print(f"error: promote validation failed:\n{exc}", file=sys.stderr)
        return PromoteValidationError.exit_code
    except PromoteApplyError as exc:
        print(f"error: promote apply failed:\n{exc}", file=sys.stderr)
        return PromoteApplyError.exit_code

    if result.dry_run:
        print(
            f"dry-run: staged tree validated; would apply "
            f"{len(result.applied_paths)} edit(s); wiki tree unchanged."
        )
        for p in result.applied_paths:
            print(f"  + {p}")
        return 0

    if not result.applied_paths:
        print(
            f"no-op: {proposals_dir.name} already applied "
            f"(no changes to write)."
        )
        return 0

    print(
        f"applied {len(result.applied_paths)} edit(s) from "
        f"{proposals_dir.name}; archived to {result.archived_dir}."
    )
    for p in result.applied_paths:
        print(f"  + knowledge/wiki/{p}")
    return 0


def _do_query(args: argparse.Namespace) -> int:
    """Phase 3: index-first query against the wiki."""
    repo_root = _resolve_repo_root()
    try:
        backend = resolve_backend(args.backend)
    except BackendNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return BackendNotFoundError.exit_code

    if args.debug_unsafe_output and hasattr(backend, "_redact_output"):
        backend._redact_output = False

    querier_kwargs: dict[str, object] = {
        "backend": backend,
        "repo_root": repo_root,
    }
    if args.max_pages is not None:
        querier_kwargs["max_pages"] = args.max_pages
    querier = DefaultQuerier(**querier_kwargs)  # type: ignore[arg-type]

    try:
        if args.file_back:
            answer, patch = querier.query_with_file_back(args.question)
        else:
            answer = querier.query(args.question)
            patch = None
    except SourceMissingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return SourceMissingError.exit_code
    except BackendInvocationError as exc:
        print(f"error: backend invocation failed: {exc}", file=sys.stderr)
        return BackendInvocationError.exit_code
    except ContractViolationError as exc:
        print(f"error: contract violation: {exc}", file=sys.stderr)
        return ContractViolationError.exit_code

    if answer.answer:
        print(answer.answer)
    else:
        print("(no answer — wiki does not contain enough information)")

    print("\n--- citations ---", file=sys.stderr)
    for c in answer.citations:
        print(f"  - {c.page}: {c.fragment}", file=sys.stderr)
    print(
        f"--- pages loaded: {len(answer.pages_loaded)} ---", file=sys.stderr,
    )
    for p in answer.pages_loaded:
        print(f"  + {p}", file=sys.stderr)

    if args.file_back and patch is not None:
        if not patch.edits:
            print(
                "(--file-back: empty patch-set; nothing to file back)",
                file=sys.stderr,
            )
            return 0
        # Write the patch-set out so the curator can promote it.
        from .ingestor_multi import write_patch_set_dir
        today = datetime.date.today().isoformat()
        slug = "query-fileback"
        proposal_root: Path = args.output_dir or (repo_root / _DEFAULT_OUTPUT_DIR)
        out = proposal_root / f"{today}-{slug}"
        try:
            written = write_patch_set_dir(patch, out)
        except OSError as exc:
            print(f"error: could not write file-back dir: {exc}", file=sys.stderr)
            return OutputWriteError.exit_code
        print(f"--- file-back patch-set: {written}", file=sys.stderr)
    return 0


def _do_lint(args: argparse.Namespace) -> int:
    """Wiki linters.

    Default: structural lint via knowledge/wiki/scripts/lint-wiki.sh.
    --health: structural + knowledge-health (contradictions,
    stale-claims, weak-orphans, missing-cross-links).
    """
    repo_root = _resolve_repo_root()
    linter = repo_root / "knowledge" / "wiki" / "scripts" / "lint-wiki.sh"
    if not linter.exists():
        print(
            f"error: structural linter not found at {linter}",
            file=sys.stderr,
        )
        return BackendNotFoundError.exit_code

    structural_rc = subprocess.call(["bash", str(linter)])
    if not args.health:
        return structural_rc

    # Knowledge-health pass.
    backend = None
    if args.backend:
        try:
            backend = resolve_backend(args.backend)
        except BackendNotFoundError as exc:
            print(
                f"error: --health backend resolution failed: {exc}",
                file=sys.stderr,
            )
            return BackendNotFoundError.exit_code

    result = lint_health(
        repo_root=repo_root,
        paths=args.paths,
        backend=backend,
    )
    if not result.findings:
        print(
            f"\nknowledge-health: clean ({result.pages_checked} pages "
            f"checked, 0 findings)."
        )
        return structural_rc

    # Print findings on stderr so the structural linter's stdout
    # remains the canonical output.
    print(
        f"\nknowledge-health: {len(result.findings)} finding(s) "
        f"across {result.pages_checked} pages",
        file=sys.stderr,
    )
    for f in result.findings:
        loc = ", ".join(f.pages)
        print(
            f"  [{f.kind} / {f.severity}] {loc}: {f.description}",
            file=sys.stderr,
        )

    if args.strict:
        return 1 if structural_rc == 0 else structural_rc
    return structural_rc


_VERBS = ("ingest", "promote", "query", "lint")


def _inject_legacy_v1_prefix(argv: list[str]) -> list[str]:
    """Backwards-compat shim for direct ``python3 -m wiki_ingest <source>`` callers.

    Phase 0 introduced verb dispatch. Pre-Phase-0 callers (and the e2e
    test suite) invoke ``python3 -m wiki_ingest <source> [--backend ...]``
    without any verb. Detect that shape — first non-flag arg is not a
    known verb — and inject ``ingest --legacy-single-source`` so the v1
    behavior is preserved at the Python entrypoint as well as at the
    ``scripts/wiki-ingest`` shell wrapper.
    """
    if not argv:
        return argv
    # Top-level help/version: pass straight through so the parser shows
    # the verb-dispatching parser's epilog (with stable exit codes).
    if "-h" in argv or "--help" in argv:
        # If a verb is already present, let it through — the per-verb
        # help is what the user asked for.
        for token in argv:
            if token in _VERBS:
                return argv
        return argv
    # Walk past leading flags to find the first positional arg.
    first_positional: str | None = None
    for token in argv:
        if token.startswith("-"):
            continue
        first_positional = token
        break
    if first_positional in _VERBS:
        return argv
    # No verb in argv → legacy v1 invocation. Inject the prefix.
    return ["ingest", "--legacy-single-source", *argv]


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the exit code; never raises (errors are mapped)."""
    if argv is None:
        argv = sys.argv[1:]
    argv = _inject_legacy_v1_prefix(list(argv))

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "ingest": _do_ingest,
        "promote": _do_promote,
        "query": _do_query,
        "lint": _do_lint,
    }
    handler = dispatch.get(args.verb)
    if handler is None:
        parser.error(f"unknown verb: {args.verb}")
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
