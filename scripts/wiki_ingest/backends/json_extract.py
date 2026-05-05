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
    """Strategy 1: find a ```json … ``` or ``` … ``` block and parse it."""
    # Prefer the language-tagged form first.
    for pattern in (_FENCE_JSON_RE, _FENCE_ANY_RE):
        match = pattern.search(stdout)
        if match:
            candidate = match.group(1)
            result = _try_parse_dict(candidate)
            if result is not None:
                return result
    return None


def _extract_via_balanced_braces(stdout: str) -> dict | None:
    """Strategy 2: scan for the first balanced top-level {…} block.

    Tracks nesting depth and respects JSON string literals (with \" escape
    handling) so braces inside strings are not counted.
    """
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
