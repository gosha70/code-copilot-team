# wiki_ingest.proposal — IngestRequest, IngestProposal dataclasses + proposal-file renderer.

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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
