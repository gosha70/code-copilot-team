# wiki_ingest.yaml_lite — minimal stdlib-only YAML frontmatter parser.
#
# Extracted from prompt.py in Phase 1 of the rescoped wiki-ingest-pipeline
# so all four operations (ingest, promote, query, lint) can share the
# parser without the import circularity that would arise if they each
# pulled from prompt.py.
#
# Handles only what wiki frontmatter actually uses:
#   - scalar keys: ``key: value``
#   - list keys: ``key:`` followed by ``  - item``
#   - list items as dicts: ``  - key: value`` followed by indented
#     continuation lines.
#   - Single-quoted, double-quoted, and unquoted scalar values.
#
# What it deliberately does NOT handle (unused in this codebase):
#   - block scalars (``key: |`` / ``key: >``)
#   - anchors / aliases / flow-style sequences and mappings
#   - schema validation
#
# If the wiki schema ever needs richer YAML, add pyyaml as a dep —
# don't grow this parser.

from __future__ import annotations

import re
from typing import Any

from .errors import ContractViolationError


def parse_frontmatter(markdown: str) -> dict[str, Any]:
    """Extract and parse the YAML frontmatter from a markdown string.

    Raises ContractViolationError if the frontmatter block is missing or malformed.
    Returns a dict of scalar and simple-list values found in the frontmatter.
    """
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractViolationError(
            "draft_markdown.frontmatter: missing opening '---' on line 1"
        )
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
    return parse_simple_yaml(fm_lines)


def parse_simple_yaml(lines: list[str]) -> dict[str, Any]:
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
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", line)
        if m:
            key = m.group(1)
            rest = m.group(2).strip()
            if rest == "" or rest == "null":
                items = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    item_m = re.match(r"^(\s+)-\s+(.*)", next_line)
                    if item_m:
                        item_indent = len(item_m.group(1))
                        first_pair = item_m.group(2).strip()
                        item_dict: dict[str, str] = {}
                        kv_m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", first_pair)
                        if kv_m:
                            item_dict[kv_m.group(1)] = unquote(kv_m.group(2).strip())
                        else:
                            items.append(unquote(first_pair))
                            j += 1
                            continue
                        j += 1
                        while j < len(lines):
                            cont = lines[j]
                            if not cont.strip():
                                j += 1
                                continue
                            cont_indent = len(cont) - len(cont.lstrip())
                            if cont_indent <= item_indent:
                                break
                            if re.match(r"^\s+-\s+", cont):
                                break
                            cont_kv = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", cont)
                            if cont_kv:
                                item_dict[cont_kv.group(1)] = unquote(cont_kv.group(2).strip())
                            j += 1
                        items.append(item_dict)
                    elif next_line and not next_line.startswith(" ") and not next_line.startswith("\t"):
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
                result[key] = unquote(rest)
                i += 1
        else:
            i += 1
    return result


def unquote(s: str) -> str:
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


def normalise_source(source: Any) -> frozenset[tuple[str, str]]:
    """Convert a source entry (dict) to a frozenset of (key, value) pairs for comparison."""
    if isinstance(source, dict):
        return frozenset((k, str(v)) for k, v in source.items())
    return frozenset({("raw", str(source))})


def sources_equal(a: list[Any], b: list[Any]) -> bool:
    """Return True if two sources lists are set-equal (order-independent)."""
    set_a = {normalise_source(s) for s in a}
    set_b = {normalise_source(s) for s in b}
    return set_a == set_b
