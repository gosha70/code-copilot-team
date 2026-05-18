# wiki_ingest.proposal — Stage-1 IngestProposal + Phase-1 WikiPatchSet types.
#
# IngestRequest / IngestProposal are the v1 single-source proposal types
# (kept verbatim — every existing call site continues to work).
#
# WikiPatchSet / PageEdit are the multi-page Phase-1 types: a single ingest
# can now produce many edits in one patch-set, the curator reviews them as
# a unit, and ``wiki promote`` (Phase 2) applies the patch-set atomically.

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


# ── Stage 1 (v1 single-source) ──────────────────────────────


@dataclass(frozen=True)
class IngestRequest:
    """Describes a single ingest invocation."""
    source_path: Path
    source_kind: Literal["file", "issue", "url"]
    backend_name: str


@dataclass(frozen=True)
class IngestProposal:
    """The structured result returned by a backend after processing an IngestRequest."""
    disposition: Literal["accept", "reject"]
    reason: str
    page_type: str | None
    slug: str | None
    title: str | None
    draft_markdown: str | None
    sources: list[dict]


# ── Phase 1 (multi-page) ────────────────────────────────────


PageAction = Literal["create", "update", "append-log", "append-index"]


@dataclass(frozen=True)
class PageEdit:
    """One edit in a multi-page WikiPatchSet.

    Attributes
    ----------
    path : str
        Wiki-relative path. For ``create``/``update`` actions, the
        target file path under ``knowledge/wiki/`` (e.g.
        ``concepts/origin-alignment.md``). For ``append-log`` /
        ``append-index``, the conventional value is ``log.md`` /
        ``index.md`` respectively.
    action : PageAction
        - ``create``        — new file at ``path``; ``new_content`` is
                              the full markdown including frontmatter.
        - ``update``        — replace existing file at ``path`` with
                              ``new_content``.
        - ``append-log``    — append ``new_content`` (a one-line entry)
                              to the bottom of ``log.md``.
        - ``append-index``  — append ``new_content`` to the appropriate
                              section of ``index.md`` (the prompt
                              instructs the backend to format the entry
                              as a single bullet under the right section).
    new_content : str
        The full content for ``create``/``update``, or the entry-line
        text for ``append-*`` actions.
    rationale : str
        One-sentence justification for this edit, surfaced to the
        curator in the patch-set preview.
    """
    path: str
    action: PageAction
    new_content: str
    rationale: str


@dataclass(frozen=True)
class Citation:
    """One (page-path, fragment) citation produced by ``wiki query``."""
    page: str
    fragment: str


@dataclass(frozen=True)
class QueryAnswer:
    """The structured result of ``wiki query`` (Phase 3).

    Attributes
    ----------
    answer : str
        The synthesised answer text. May be empty if the wiki does
        not contain enough information; in that case ``citations``
        will typically contain only the index entry the reader
        followed.
    citations : list[Citation]
        (page-path, fragment) for every wiki page consulted in the
        answer. Pages not in this list were not opened.
    pages_loaded : list[str]
        Wiki-relative paths of pages loaded into the prompt. Useful
        for auditing index-first navigation. Logged to
        ``doc_internal/wiki-query-log.jsonl``.
    """
    answer: str
    citations: list[Citation]
    pages_loaded: list[str]


HealthFindingKind = Literal[
    "contradiction", "stale-claim", "weak-orphan", "missing-cross-link",
]
HealthFindingSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class HealthFinding:
    """One finding from the Phase-4 knowledge-health lint pass.

    Attributes
    ----------
    kind : HealthFindingKind
        Which check produced the finding.
    severity : HealthFindingSeverity
        ``warning`` is the default for advisory mode (exit 0 with
        stderr noise). ``error`` flips to non-zero exit when ``--strict``
        is set; without --strict, it's still surfaced but does not
        block.
    pages : list[str]
        Wiki-relative paths involved in the finding. For
        contradictions, typically two pages. For stale-claim,
        weak-orphan, missing-cross-link, usually one or more.
    description : str
        Human-readable description of the finding, with enough detail
        for the curator to either act on it or ignore it.
    """
    kind: HealthFindingKind
    severity: HealthFindingSeverity
    pages: list[str]
    description: str


@dataclass(frozen=True)
class IngestLogRecord:
    """One NDJSON line appended to knowledge/wiki/.audit/ingest-log.md.

    Patch-set-oriented: a single ``wiki ingest`` run may touch many pages
    of several types, and a reject is an empty ``edits`` list rather than
    a separate disposition field. Fields are final names per spec.md
    § Python interface (v: 1).
    """
    v: int                      # schema version (1)
    ts: str                     # ISO-8601 UTC, second precision, "Z"
    source_path: str            # as-used path (repo-rel or verbatim)
    source_repo_relative: bool  # False for --allow-out-of-repo sources
    source_sha: str             # sha256 hex of source file bytes
    backend: str
    disposition: str            # "accept" | "reject"
    reason: str                 # rationale, newline-collapsed, ≤ 240 cp
    proposal_dir: str | None    # basename of doc_internal/proposals/<name>/
    target_paths: list[str]     # sorted unique wiki-rel paths; [] on reject
    page_types: list[str]       # sorted unique page types; [] on reject
    proposal_hash: str | None   # sha256 of canonicalized payload, or None


@dataclass(frozen=True)
class WikiPatchSet:
    """A multi-page write plan emitted by Phase-1 ``wiki ingest``.

    Atomic unit of curator review and promotion. A single source can
    produce a patch-set that touches several existing pages, creates
    new pages, appends to the log, and updates the index — Karpathy's
    "one source touches 10–15 pages" pattern.

    Attributes
    ----------
    edits : list[PageEdit]
        Per-page edits. Order is significant only for ``append-*``
        actions (later appends see the earlier appends already in
        the log/index). ``create``/``update`` actions are
        order-independent.
    source_path : str
        The source ingested. Recorded for audit trail.
    backend : str
        Backend name that produced this patch-set.
    rationale : str
        One-paragraph patch-set-level rationale: why this source
        touches these pages, in the curator's terms.
    """
    edits: list[PageEdit]
    source_path: str
    backend: str
    rationale: str


# Promotable wiki page types — the only types valid as the target of a
# create or update edit. Root-only meta types (index, log, overview)
# cannot be (re)created via ingest; they are touched via append-index /
# append-log only. Mirrors prompt.py::_PROMOTABLE_PAGE_TYPES.
_PROMOTABLE_PAGE_TYPES: frozenset[str] = frozenset({
    "concept", "workflow", "incident", "decision",
    "playbook", "glossary", "open-question",
})


def validate_page_edit_semantics(
    edit: "PageEdit",
    repo_root: Path,
) -> list[str]:
    """Per-edit semantic validation.

    Mirrors the v1 two-layer validation pattern (shape + semantic
    cross-consistency) at the per-edit grain so multi-page ingest
    can't slip frontmatter mismatches through under the cover of the
    set-level check.

    For ``create`` and ``update`` actions, parses the new_content's
    YAML frontmatter and asserts:
      - frontmatter is well-formed;
      - page_type, slug, title are present;
      - frontmatter slug equals the filename stem;
      - page_type is a promotable type (not index/log/overview);
      - sources is a non-empty list (per citation-rules.md);
      - the path lives under the directory matching page_type
        (concepts/ for concept, etc.).

    For ``update`` specifically, additionally asserts the target file
    actually exists under ``knowledge/wiki/<path>`` (otherwise the
    edit is an unintended create masquerading as an update).

    For ``append-log`` and ``append-index``, frontmatter parsing is
    skipped (the new_content is a single bullet line, not a full
    page). The append targets are already enforced by
    validate_patch_set.

    Returns a list of error strings; empty list means valid.
    """
    # Avoid circular import
    from . import yaml_lite
    from .errors import ContractViolationError

    errors: list[str] = []

    if edit.action in ("append-log", "append-index"):
        if not edit.new_content.strip():
            errors.append(f"{edit.path}: append content is empty")
        return errors

    # create / update: parse frontmatter from new_content
    try:
        fm = yaml_lite.parse_frontmatter(edit.new_content)
    except ContractViolationError as exc:
        errors.append(f"{edit.path}: frontmatter parse failed: {exc}")
        return errors

    fm_page_type = fm.get("page_type")
    fm_slug = fm.get("slug")
    fm_title = fm.get("title")

    if not fm_page_type:
        errors.append(f"{edit.path}: frontmatter missing 'page_type'")
    if not fm_slug:
        errors.append(f"{edit.path}: frontmatter missing 'slug'")
    if not fm_title:
        errors.append(f"{edit.path}: frontmatter missing 'title'")

    # slug == filename stem
    expected_stem = Path(edit.path).stem
    if fm_slug and fm_slug != expected_stem:
        # Special case: <dir>/index.md → slug equals parent dir name
        # (per the wiki linter). Glossary index in particular.
        parent = Path(edit.path).parent.name
        if expected_stem == "index" and parent and fm_slug == parent:
            pass
        else:
            errors.append(
                f"{edit.path}: frontmatter slug {fm_slug!r} should be "
                f"{expected_stem!r} (filename stem rule)"
            )

    # page_type must be promotable (not index/log/overview)
    if fm_page_type and fm_page_type not in _PROMOTABLE_PAGE_TYPES:
        valid = ", ".join(sorted(_PROMOTABLE_PAGE_TYPES))
        errors.append(
            f"{edit.path}: frontmatter page_type {fm_page_type!r} is not "
            f"promotable for create/update; must be one of: {valid}. "
            f"Root-only types (index, log, overview) are touched via "
            f"append-index / append-log."
        )

    # page_type matches directory placement
    page_type_to_dir = {
        "concept": "concepts",
        "workflow": "workflows",
        "incident": "incidents",
        "decision": "decisions",
        "playbook": "playbooks",
        "glossary": "glossary",
        "open-question": "open-questions",
    }
    if fm_page_type and fm_page_type in page_type_to_dir:
        expected_dir = page_type_to_dir[fm_page_type]
        actual_dir = Path(edit.path).parent.as_posix() or "."
        if actual_dir != expected_dir:
            errors.append(
                f"{edit.path}: page_type {fm_page_type!r} should live "
                f"under {expected_dir}/ but path is in {actual_dir}/"
            )

    # sources must be non-empty (per citation-rules.md — every page
    # except index.md and log.md must declare its sources)
    sources = fm.get("sources") or []
    if not isinstance(sources, list) or not sources:
        errors.append(
            f"{edit.path}: frontmatter 'sources:' must be a non-empty "
            f"list (citation-rules.md: 'A wiki page without sources is "
            f"a rumor.')"
        )

    # update target must exist on disk; create target must NOT exist
    # (otherwise create would clobber an existing page — the curator
    # would have to catch this at promote time, but it's cheap to catch
    # at validate time and lets the backend pick the right action).
    if edit.action == "update":
        target = repo_root / "knowledge" / "wiki" / edit.path
        if not target.exists():
            errors.append(
                f"{edit.path}: update target does not exist at "
                f"{target.relative_to(repo_root)}; use action 'create' "
                f"for new pages"
            )
    elif edit.action == "create":
        target = repo_root / "knowledge" / "wiki" / edit.path
        if target.exists():
            errors.append(
                f"{edit.path}: create target already exists at "
                f"{target.relative_to(repo_root)}; use action 'update' "
                f"to modify an existing page"
            )

    return errors


def validate_patch_set(patch: WikiPatchSet) -> list[str]:
    """Return a list of validation errors (empty list = valid).

    Patch-set-level invariants (per-page validation is run separately
    by the multi-ingestor; this only catches set-level issues):
      - At least one edit.
      - No two ``create`` actions write to the same path (the apply
        step would clobber).
      - All ``append-log`` entries target ``log.md``.
      - All ``append-index`` entries target ``index.md`` or a nested
        ``index.md`` under a sub-directory (e.g. ``glossary/index.md``).
      - ``create``/``update`` paths must be relative (no leading ``/``,
        no ``..``).
    """
    errors: list[str] = []

    if not patch.edits:
        errors.append("WikiPatchSet must contain at least one edit")
        return errors

    create_paths: set[str] = set()
    for i, edit in enumerate(patch.edits):
        prefix = f"edits[{i}] (action={edit.action!r}, path={edit.path!r})"

        if not edit.path:
            errors.append(f"{prefix}: empty path")
            continue
        if edit.path.startswith("/") or ".." in edit.path.split("/"):
            errors.append(f"{prefix}: path must be relative and not contain '..'")
            continue

        if edit.action == "create":
            if edit.path in create_paths:
                errors.append(f"{prefix}: duplicate create for path; an earlier edit already creates this file")
            create_paths.add(edit.path)
        elif edit.action == "append-log":
            if not (edit.path == "log.md" or edit.path.endswith("/log.md")):
                errors.append(f"{prefix}: append-log targets must be log.md")
        elif edit.action == "append-index":
            if not (edit.path == "index.md" or edit.path.endswith("/index.md")):
                errors.append(f"{prefix}: append-index targets must be index.md or <dir>/index.md")
        elif edit.action != "update":
            errors.append(f"{prefix}: unknown action")

        if not edit.new_content:
            errors.append(f"{prefix}: new_content must be non-empty")

    return errors


def _yaml_single_quote(value: str) -> str:
    """Single-quote a YAML scalar, escaping internal single quotes per spec.

    Single-quoted YAML treats every character literally except the single
    quote itself, which is escaped by doubling. This makes it safe for any
    free-form text that might contain colons, hash marks, leading whitespace,
    or other characters that would change the meaning of a plain scalar.
    """
    return "'" + value.replace("'", "''") + "'"


def render_proposal_file(
    proposal: IngestProposal,
    request: IngestRequest,
    backend_name: str,
) -> str:
    """Return the full markdown body for the proposal file (frontmatter + body).

    Free-form fields (`source_path`, `backend`, `gate_reason`, `target_slug`,
    `target_page_type`) are emitted as single-quoted YAML scalars so that
    values containing colons, leading whitespace, or other YAML-significant
    characters round-trip safely. Constrained fields (`proposal_kind`,
    `proposal_date`, `ingestor_version`, `gate_disposition`) are plain
    scalars — their value sets are bounded and never need quoting.
    """
    today = datetime.date.today().isoformat()
    target_slug = proposal.slug or ""
    target_page_type = proposal.page_type or ""

    frontmatter_lines = [
        "---",
        f"proposal_kind: {proposal.disposition}",
        f"proposal_date: {today}",
        f"source_path: {_yaml_single_quote(str(request.source_path))}",
        f"backend: {_yaml_single_quote(backend_name)}",
        "ingestor_version: 1",
        f"gate_disposition: {proposal.disposition}",
        f"gate_reason: {_yaml_single_quote(proposal.reason)}",
        f"target_slug: {_yaml_single_quote(target_slug)}",
        f"target_page_type: {_yaml_single_quote(target_page_type)}",
        "---",
    ]
    frontmatter = "\n".join(frontmatter_lines)

    if proposal.disposition == "accept" and proposal.draft_markdown:
        body = proposal.draft_markdown
    else:
        body = proposal.reason

    return f"{frontmatter}\n\n{body}\n"
