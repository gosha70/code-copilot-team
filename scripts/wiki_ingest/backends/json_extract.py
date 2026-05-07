# wiki_ingest.backends.json_extract — isolated JSON-extraction module.
#
# Exposes one public function: extract_json_object(stdout: str) -> dict
#
# Extraction strategies (in order):
#   1. Fenced code block: ```json … ``` (or ``` … ``` with no language tag)
#   2. Balanced-brace scan: find the first balanced top-level {…} block

from __future__ import annotations

import json
import re

from ..errors import ContractViolationError

# Regex patterns for fenced code blocks
_FENCE_JSON_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL)
_FENCE_ANY_RE = re.compile(r"```\s*\n(.*?)```", re.DOTALL)

# Matches any fully-closed fenced region with any (possibly empty)
# language tag. Used by the balanced-brace fallback to mask out
# reference material the prompt put inside ```text``` (or any other
# non-json fence) so its braces are not mistaken for the response.
# Note this is broader than _FENCE_ANY_RE — that regex requires
# whitespace+newline immediately after the opening backticks (so
# ```text\n is not matched), whereas this one allows any non-newline
# language tag (text, python, bash, schema, …).
_FENCE_REGION_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)


def _try_parse_dict(text: str) -> dict | None:
    """Attempt to parse text as JSON. Return the dict on success, None otherwise.

    Returns None (not raises) if the text is not valid JSON or does not parse
    to a dict. Callers accumulate failures and raise at the end.
    """
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _extract_via_fence(stdout: str) -> dict | None:
    """Strategy 1: return the first parseable fenced JSON object.

    Prefer language-tagged ```json fences over plain ``` fences. Within each
    fence kind, continue past malformed or non-dict candidates until a
    parseable dict is found.
    """
    for pattern in (_FENCE_JSON_RE, _FENCE_ANY_RE):
        for match in pattern.finditer(stdout):
            candidate = match.group(1)
            result = _try_parse_dict(candidate)
            if result is not None:
                return result
    return None


def _strip_fenced_regions(stdout: str) -> str:
    """Replace fully-closed fenced regions with whitespace of the same length.

    Used by the balanced-brace fallback to mask out reference material
    the prompt put inside ```text``` (or any non-json fence) so its
    braces are not mistaken for the response. Whitespace replacement
    (rather than removal) preserves character positions in case any
    future caller wants original-stdout offsets.

    Unclosed fences are left as-is (fail-safe: do not silently swallow
    text after a malformed prompt).
    """
    def _to_whitespace(match: re.Match) -> str:
        return " " * len(match.group(0))
    return _FENCE_REGION_RE.sub(_to_whitespace, stdout)


def _extract_via_balanced_braces(stdout: str) -> dict | None:
    """Strategy 2: scan for the first balanced top-level {…} block.

    Tracks nesting depth and respects JSON string literals (with \" escape
    handling) so braces inside strings are not counted.

    **Skips fenced regions.** Reference material in ```text``` (or any
    non-json fence) is masked out before scanning, so a JSON-shaped
    schema in the prompt cannot shadow an unfenced response. The
    fence-first strategy in `_extract_via_fence` already handles
    ``json``-fenced responses; this fallback is only reached when no
    fence yielded a parseable dict, and at that point any remaining
    fenced content is by definition reference material (or a malformed
    response that already failed parse).
    """
    stdout = _strip_fenced_regions(stdout)
    n = len(stdout)
    i = 0
    while i < n:
        if stdout[i] != "{":
            i += 1
            continue
        # Found a potential start
        start = i
        depth = 0
        j = i
        while j < n:
            c = stdout[j]
            if c == '"':
                # Skip string literal
                j += 1
                while j < n:
                    sc = stdout[j]
                    if sc == "\\":
                        j += 2  # skip escaped character
                        continue
                    if sc == '"':
                        j += 1
                        break
                    j += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = stdout[start : j + 1]
                    result = _try_parse_dict(candidate)
                    if result is not None:
                        return result
                    # This balanced block didn't parse as a dict; skip past it
                    # and continue looking for the next one.
                    i = j + 1
                    break
            j += 1
        else:
            # Reached end of string without closing brace; no more blocks.
            break
        # If we didn't break due to finding a block (depth never hit 0), stop.
        if j >= n and depth != 0:
            break
    return None


def extract_json_object(stdout: str) -> dict:
    """Extract and return the first JSON object from free-form text.

    Extraction order:
      1. Fenced code block (```json … ``` or ``` … ```).
      2. Balanced-brace scan of the entire stdout.

    Raises ContractViolationError if no parseable JSON object is found.
    The error message always contains the phrase "no JSON object" and includes
    the first 500 characters of stdout for debugging.
    """
    result = _extract_via_fence(stdout)
    if result is not None:
        return result

    result = _extract_via_balanced_braces(stdout)
    if result is not None:
        return result

    truncated = stdout[:500]
    raise ContractViolationError(
        f"no JSON object found in backend stdout. "
        f"stdout (first 500 chars): {truncated!r}"
    )
