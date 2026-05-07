# wiki_ingest.prompt — schema loading, BackendPrompt composition, BackendResponse validation.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import yaml_lite
from .errors import ContractViolationError

# ---------------------------------------------------------------------------
# Schema paths (read at runtime, never embedded in source)
# ---------------------------------------------------------------------------

_SCHEMA_NAMES = ("ingest-rules", "page-types", "citation-rules")

# Directory-placement mapping (mirrors lint-wiki.sh expected_dir_for_type).
_PAGE_TYPE_TO_DIR: dict[str, str] = {
    "concept": "concepts",
    "workflow": "workflows",
    "incident": "incidents",
    "decision": "decisions",
    "playbook": "playbooks",
    "glossary": "glossary",
    "open-question": "open-questions",
    "index": ".",
    "log": ".",
    "overview": ".",
}

# Page types that may be the target of an ingest proposal. Excludes
# root-only meta pages (index, log, overview) — those are wiki structure,
# not promotable lessons.
_PROMOTABLE_PAGE_TYPES: frozenset[str] = frozenset({
    "concept", "workflow", "incident", "decision",
    "playbook", "glossary", "open-question",
})

_VALID_PAGE_TYPES = set(_PAGE_TYPE_TO_DIR.keys())

# Kebab-case: only lowercase letters, digits, hyphens; no leading/trailing hyphen.
_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _find_schema_dir(repo_root: Path) -> Path:
    """Return the schema directory, resolving from repo_root."""
    return repo_root / "knowledge" / "wiki" / "schema"


def load_schema_files(repo_root: Path) -> dict[str, str]:
    """Load ingest-rules, page-types, citation-rules from disk. Return {name: content}."""
    schema_dir = _find_schema_dir(repo_root)
    result: dict[str, str] = {}
    for name in _SCHEMA_NAMES:
        path = schema_dir / f"{name}.md"
        result[name] = path.read_text(encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# BackendPrompt composition
# ---------------------------------------------------------------------------

_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["version", "disposition", "reason", "page_type", "slug", "title",
                 "draft_markdown", "sources"],
    "properties": {
        "version": {"type": "integer", "const": 1},
        "disposition": {"type": "string", "enum": ["accept", "reject"]},
        "reason": {"type": "string"},
        "page_type": {"type": ["string", "null"]},
        "slug": {"type": ["string", "null"]},
        "title": {"type": ["string", "null"]},
        "draft_markdown": {"type": ["string", "null"]},
        "sources": {"type": "array"},
    },
}


_PATCH_SET_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["version", "rationale", "edits"],
    "properties": {
        "version": {"type": "integer", "const": 1},
        "rationale": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "action", "new_content", "rationale"],
                "properties": {
                    "path": {"type": "string"},
                    "action": {"enum": ["create", "update", "append-log", "append-index"]},
                    "new_content": {"type": "string"},
                    "rationale": {"type": "string"},
                },
            },
        },
    },
}


def compose_multi_prompt(
    source_path: Path,
    source_content: str,
    schema_files: dict[str, str],
    wiki_state: "Any",  # noqa: F821 — Phase-1 WikiState forward-ref via TYPE_CHECKING in caller
    source_kind: str = "file",
) -> dict[str, Any]:
    """Compose a wiki-aware BackendPrompt for multi-page ingest (Phase 1).

    Differs from compose_prompt (Stage 1) in that it loads the existing
    wiki state — index.md, log.md, and a candidate page set — into the
    prompt as the curator's working memory, and asks the backend to
    emit a WikiPatchSet (multi-page write plan) instead of a single
    IngestProposal.

    The instructions explicitly tell the backend to:
      - integrate with existing pages where applicable (update, not
        always create);
      - update index.md with a one-line entry under the right section
        whenever a page is created;
      - append a one-line dated entry to log.md;
      - one source can touch many pages — emit several edits if the
        source warrants it.
    """
    system_instructions = (
        "You are acting as the wiki curator. The wiki is a persistent, "
        "compounding artifact maintained over time. You have been given "
        "the existing wiki state below as your working memory. Your "
        "task is to produce a multi-page WIKI PATCH-SET that integrates "
        "the new source into the existing wiki: update existing pages "
        "where the source extends or refines them, create new pages "
        "only when no existing page covers the topic, append a one-line "
        "dated entry to log.md, and update index.md with a link to any "
        "new page. One source can touch several pages — emit edits for "
        "each. Apply the four-question gate to the source first; if the "
        "gate rejects, return an empty edits array with the reject "
        "reason in 'rationale'."
    )
    return {
        "version": 1,
        "system_instructions": system_instructions,
        "task": "ingest-multi",
        "schema_excerpts": {
            "ingest_rules": schema_files.get("ingest-rules", ""),
            "page_types": schema_files.get("page-types", ""),
            "citation_rules": schema_files.get("citation-rules", ""),
        },
        "source": {
            "kind": source_kind,
            "path": str(source_path),
            "content": source_content,
        },
        "wiki_state": {
            "index_md": getattr(wiki_state, "index_md", ""),
            "log_md": getattr(wiki_state, "log_md", ""),
            "candidate_pages": dict(getattr(wiki_state, "candidate_pages", {})),
        },
        "response_schema": json.dumps(_PATCH_SET_RESPONSE_SCHEMA),
    }


def parse_patch_set_response(raw_stdout: str) -> dict[str, Any]:
    """Parse a backend's WikiPatchSet response (no semantic validation here).

    Per-edit semantic validation lives in ingestor_multi.DefaultMultiIngestor;
    set-level validation lives in proposal.validate_patch_set. This helper
    only confirms the response is a JSON object with the required shape
    so the orchestrator can build a WikiPatchSet from it.
    """
    try:
        data = json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        truncated = raw_stdout[:500]
        raise ContractViolationError(
            f"WikiPatchSet response is not valid JSON: {exc}\n"
            f"  stdout (first 500 chars): {truncated!r}"
        ) from exc
    if not isinstance(data, dict):
        raise ContractViolationError(
            f"WikiPatchSet response must be a JSON object, got {type(data).__name__}"
        )
    for required in ("version", "rationale", "edits"):
        if required not in data:
            raise ContractViolationError(
                f"WikiPatchSet response missing required key: {required!r}"
            )
    if data["version"] != 1:
        raise ContractViolationError(
            f"WikiPatchSet response version must be 1, got {data['version']!r}"
        )
    if not isinstance(data["edits"], list):
        raise ContractViolationError(
            f"WikiPatchSet.edits must be an array, got {type(data['edits']).__name__}"
        )
    return data


def compose_prompt(
    source_path: Path,
    source_content: str,
    schema_files: dict[str, str],
    source_kind: str = "file",
    task: str = "ingest",
) -> dict[str, Any]:
    """Compose a BackendPrompt dict from source content and loaded schema files.

    ``task`` is one of:
      - ``"ingest"``    — run the four-question gate AND draft the page body
                          (default).
      - ``"gate-only"`` — run the gate; on accept, set draft_markdown=null.
                          Used by ``--dry-run`` to skip body generation cost.
    The render layer in ``backends/copilot_cli.py`` adds a ``GATE-ONLY MODE``
    instruction when ``task == "gate-only"``; backends that ignore the hint
    still get the body stripped at the render side as a safety net.
    """
    system_instructions = (
        "You are acting as a wiki curator. "
        "Read the schema excerpts provided, apply the four-question gate to the source, "
        "and respond with exactly one JSON object matching the response schema. "
        "Emit nothing else on stdout — no prose, no markdown fences, just the JSON object."
    )
    return {
        "version": 1,
        "system_instructions": system_instructions,
        "task": task,
        "schema_excerpts": {
            "ingest_rules": schema_files.get("ingest-rules", ""),
            "page_types": schema_files.get("page-types", ""),
            "citation_rules": schema_files.get("citation-rules", ""),
        },
        "source": {
            "kind": source_kind,
            "path": str(source_path),
            "content": source_content,
        },
        "response_schema": json.dumps(_RESPONSE_SCHEMA),
    }


# ---------------------------------------------------------------------------
# YAML frontmatter parser (delegates to yaml_lite — extracted in Phase 1
# so all four operations can share without import cycles).
#
# These wrappers keep the historical _parse_frontmatter / _parse_simple_yaml /
# _unquote / _sources_equal names for any internal callers that used them.
# New code should import from yaml_lite directly.
# ---------------------------------------------------------------------------

def _parse_frontmatter(markdown: str) -> dict[str, Any]:
    """Delegates to yaml_lite.parse_frontmatter (Phase 1 extraction)."""
    return yaml_lite.parse_frontmatter(markdown)


def _parse_simple_yaml(lines: list[str]) -> dict[str, Any]:
    """Delegates to yaml_lite.parse_simple_yaml (Phase 1 extraction)."""
    return yaml_lite.parse_simple_yaml(lines)


def _unquote(s: str) -> str:
    """Delegates to yaml_lite.unquote (Phase 1 extraction)."""
    return yaml_lite.unquote(s)


def _normalise_source(source: Any) -> frozenset[tuple[str, str]]:
    """Delegates to yaml_lite.normalise_source (Phase 1 extraction)."""
    return yaml_lite.normalise_source(source)


def _sources_equal(a: list[Any], b: list[Any]) -> bool:
    """Delegates to yaml_lite.sources_equal (Phase 1 extraction)."""
    return yaml_lite.sources_equal(a, b)


# ---------------------------------------------------------------------------
# Layer 1: shape validation
# ---------------------------------------------------------------------------

def _validate_shape(raw: Any) -> dict[str, Any]:
    """Validate that raw is a dict with the expected shape. Raises ContractViolationError."""
    if not isinstance(raw, dict):
        raise ContractViolationError(
            f"BackendResponse must be a JSON object, got {type(raw).__name__}"
        )

    required_keys = ["version", "disposition", "reason", "page_type", "slug",
                     "title", "draft_markdown", "sources"]
    for key in required_keys:
        if key not in raw:
            raise ContractViolationError(
                f"BackendResponse missing required key: '{key}'"
            )

    if raw["version"] != 1:
        raise ContractViolationError(
            f"BackendResponse.version must be 1, got {raw['version']!r}"
        )

    if raw["disposition"] not in ("accept", "reject"):
        raise ContractViolationError(
            f"BackendResponse.disposition must be 'accept' or 'reject', "
            f"got {raw['disposition']!r}"
        )

    if not isinstance(raw["reason"], str):
        raise ContractViolationError(
            f"BackendResponse.reason must be a string, got {type(raw['reason']).__name__}"
        )

    for nullable_str_key in ("page_type", "slug", "title", "draft_markdown"):
        val = raw[nullable_str_key]
        if val is not None and not isinstance(val, str):
            raise ContractViolationError(
                f"BackendResponse.{nullable_str_key} must be a string or null, "
                f"got {type(val).__name__}"
            )

    if not isinstance(raw["sources"], list):
        raise ContractViolationError(
            f"BackendResponse.sources must be an array, got {type(raw['sources']).__name__}"
        )

    return raw


# ---------------------------------------------------------------------------
# Layer 2: semantic cross-consistency validation
# ---------------------------------------------------------------------------

def _validate_semantics(raw: dict[str, Any]) -> None:
    """Validate cross-consistency when disposition == 'accept'. Raises ContractViolationError."""
    page_type: str | None = raw["page_type"]
    slug: str | None = raw["slug"]
    title: str | None = raw["title"]
    draft_markdown: str | None = raw["draft_markdown"]
    sources: list = raw["sources"]

    # sources must be non-empty on accept
    if not sources:
        raise ContractViolationError(
            "semantic rule violation: structured 'sources' must be non-empty on accept disposition"
        )

    # draft_markdown must exist and have a valid frontmatter block
    if not draft_markdown:
        raise ContractViolationError(
            "semantic rule violation: 'draft_markdown' must be non-null and non-empty on accept"
        )

    fm = _parse_frontmatter(draft_markdown)

    # page_type cross-consistency
    fm_page_type = fm.get("page_type")
    if fm_page_type != page_type:
        raise ContractViolationError(
            f"semantic rule violation: draft_markdown.frontmatter.page_type "
            f"({fm_page_type!r}) ≠ structured page_type ({page_type!r})"
        )

    # slug cross-consistency
    fm_slug = fm.get("slug")
    if fm_slug != slug:
        raise ContractViolationError(
            f"semantic rule violation: draft_markdown.frontmatter.slug "
            f"({fm_slug!r}) ≠ structured slug ({slug!r})"
        )

    # title cross-consistency
    fm_title = fm.get("title")
    if fm_title != title:
        raise ContractViolationError(
            f"semantic rule violation: draft_markdown.frontmatter.title "
            f"({fm_title!r}) ≠ structured title ({title!r})"
        )

    # sources set-equality
    fm_sources = fm.get("sources") or []
    if not _sources_equal(fm_sources, sources):
        raise ContractViolationError(
            "semantic rule violation: draft_markdown.frontmatter.sources "
            "do not match structured sources (set inequality)"
        )

    # slug must be kebab-case
    if slug is None or not _KEBAB_RE.match(slug):
        raise ContractViolationError(
            f"semantic rule violation: structured slug {slug!r} is not kebab-case "
            "(must match ^[a-z0-9]+(?:-[a-z0-9]+)*$)"
        )

    # page_type must be a *promotable* wiki page type. Root-only meta types
    # (index, log, overview) cannot be the target of an ingest proposal —
    # those are wiki structure, not lessons.
    if page_type not in _PROMOTABLE_PAGE_TYPES:
        promotable = ", ".join(sorted(_PROMOTABLE_PAGE_TYPES))
        raise ContractViolationError(
            f"semantic rule violation: page_type {page_type!r} is not a "
            f"promotable wiki page type. Ingest proposals must target one of: "
            f"{promotable}. Root-only types (index, log, overview) cannot be "
            f"the target of an ingest proposal."
        )

    # Special directory-placement case: the slug "glossary" is reserved for
    # glossary/index.md (per knowledge/wiki/schema/page-types.md slug rule)
    # and must pair with page_type: glossary.
    if slug == "glossary" and page_type != "glossary":
        raise ContractViolationError(
            f"semantic rule violation: slug 'glossary' with page_type {page_type!r} "
            "violates the directory-placement rule (glossary/index.md → page_type: glossary)"
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_response(raw_stdout: str) -> dict[str, Any]:
    """Parse and validate a BackendResponse from raw stdout. Returns the validated dict.

    Raises ContractViolationError on any shape or semantic failure.
    """
    try:
        data = json.loads(raw_stdout)
    except json.JSONDecodeError as exc:
        truncated = raw_stdout[:500]
        raise ContractViolationError(
            f"BackendResponse is not valid JSON: {exc}\n"
            f"  stdout (first 500 chars): {truncated!r}"
        ) from exc

    _validate_shape(data)

    if data["disposition"] == "accept":
        _validate_semantics(data)

    return data
