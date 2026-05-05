# wiki_ingest.prompt — schema loading, BackendPrompt composition, BackendResponse validation.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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


def compose_prompt(
    source_path: Path,
    source_content: str,
    schema_files: dict[str, str],
    source_kind: str = "file",
) -> dict[str, Any]:
    """Compose a BackendPrompt dict from source content and loaded schema files."""
    system_instructions = (
        "You are acting as a wiki curator. "
        "Read the schema excerpts provided, apply the four-question gate to the source, "
        "and respond with exactly one JSON object matching the response schema. "
        "Emit nothing else on stdout — no prose, no markdown fences, just the JSON object."
    )
    return {
        "version": 1,
        "system_instructions": system_instructions,
        "task": "ingest",
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
# YAML frontmatter parser (no pyyaml; ports the awk trick from lint-wiki.sh)
# ---------------------------------------------------------------------------

def _parse_frontmatter(markdown: str) -> dict[str, Any]:
    """Extract and parse the YAML frontmatter from a markdown string.

    Raises ContractViolationError if the frontmatter block is missing or malformed.
    Returns a dict of scalar and simple-list values found in the frontmatter.
    """
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractViolationError(
            "draft_markdown.frontmatter: missing opening '---' on line 1"
        )
    # Find closing ---
    close_idx: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            close_idx = i
            break
    if close_idx is None:
        raise ContractViolationError(
            "draft_markdown.frontmatter: missing closing '---' for frontmatter block"
        )

    fm_lines = lines[1:close_idx]
    return _parse_simple_yaml(fm_lines)


def _parse_simple_yaml(lines: list[str]) -> dict[str, Any]:
    """Parse a minimal subset of YAML sufficient for wiki frontmatter.

    Handles:
    - scalar keys: ``key: value``
    - list keys: ``key:\\n  - item``
    - list items may themselves be dicts (multi-line): ``  - key: value\\n    key2: value2``
    """
    result: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        # Skip blank lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        # Top-level key
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", line)
        if m:
            key = m.group(1)
            rest = m.group(2).strip()
            if rest == "" or rest == "null":
                # Could be a list or a null scalar
                # Peek ahead for list items starting with "  - "
                items = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    # A new list item: starts with optional spaces then "- "
                    item_m = re.match(r"^(\s+)-\s+(.*)", next_line)
                    if item_m:
                        item_indent = len(item_m.group(1))
                        first_pair = item_m.group(2).strip()
                        # Collect this item's key-value pairs (multi-line dict item)
                        item_dict: dict[str, str] = {}
                        kv_m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", first_pair)
                        if kv_m:
                            item_dict[kv_m.group(1)] = _unquote(kv_m.group(2).strip())
                        else:
                            # Plain scalar item
                            items.append(_unquote(first_pair))
                            j += 1
                            continue
                        j += 1
                        # Collect continuation lines (indented more than the dash)
                        while j < len(lines):
                            cont = lines[j]
                            if not cont.strip():
                                j += 1
                                continue
                            cont_indent = len(cont) - len(cont.lstrip())
                            if cont_indent <= item_indent:
                                break
                            # Must not start a new list item
                            if re.match(r"^\s+-\s+", cont):
                                break
                            cont_kv = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", cont)
                            if cont_kv:
                                item_dict[cont_kv.group(1)] = _unquote(cont_kv.group(2).strip())
                            j += 1
                        items.append(item_dict)
                    elif next_line and not next_line.startswith(" ") and not next_line.startswith("\t"):
                        # Back at top level
                        break
                    else:
                        j += 1
                if items:
                    result[key] = items
                    i = j
                else:
                    result[key] = None
                    i = j
            else:
                result[key] = _unquote(rest)
                i += 1
        else:
            i += 1
    return result


def _unquote(s: str) -> str:
    """Strip surrounding quotes from a YAML scalar value.

    For single-quoted strings, also unescape doubled single quotes (`''` →
    `'`) per the YAML 1.2 single-quoted-flow-scalar rule.
    For double-quoted strings, surrounding quotes are stripped but no
    backslash-escape processing is attempted (this parser is intentionally
    minimal — wiki frontmatter rarely uses double-quoted scalars).
    """
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


# ---------------------------------------------------------------------------
# Sources normalisation for set-equality comparison
# ---------------------------------------------------------------------------

def _normalise_source(source: Any) -> frozenset[tuple[str, str]]:
    """Convert a source entry (dict) to a frozenset of (key, value) pairs for comparison."""
    if isinstance(source, dict):
        return frozenset((k, str(v)) for k, v in source.items())
    return frozenset({("raw", str(source))})


def _sources_equal(a: list[Any], b: list[Any]) -> bool:
    """Return True if two sources lists are set-equal (order-independent)."""
    set_a = {_normalise_source(s) for s in a}
    set_b = {_normalise_source(s) for s in b}
    return set_a == set_b


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
