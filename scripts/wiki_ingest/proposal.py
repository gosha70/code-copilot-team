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
