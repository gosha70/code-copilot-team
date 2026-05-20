# benchmark_runner.judge.rubric — load a rubric from disk into a RubricSpec.
#
# The rubric file at ``benchmarks/calibration/rubric-<name>.md`` is the
# source of truth for prompt phrasing and dimension definitions
# ("rubric is data, not code"). This loader extracts:
#
#   - dimensions: from the ``### N. `<name>`` headers under the
#     ``## Dimensions`` section.
#   - prompt_template: from the fenced code block under the
#     ``## Prompt template`` section.
#   - rubric_dimensions_block: the verbatim content of the
#     ``## Dimensions`` + ``## When a dimension does not apply``
#     sections, pre-substituted into the prompt template so the
#     judge LLM sees the full rubric context.
#
# Curly-brace discipline. The prompt template's JSON-example block
# contains literal ``{`` / ``}`` that would crash ``str.format`` in
# the judge. The loader escapes every brace to ``{{`` / ``}}`` and
# then un-escapes the five known attempt-evidence placeholders
# (``{task_id}``, ``{benchmark_id}``, ``{prompt}``, ``{diff}``,
# ``{verify_output}``). The rendered ``{rubric_dimensions_block}``
# content is also pre-escaped before substitution so its content
# survives the judge's final ``.format`` call as literal text.

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .contracts import RubricSpec


DEFAULT_RUBRIC_DIR = Path(__file__).resolve().parents[3] / "benchmarks" / "calibration"

# Live placeholders the JUDGE substitutes per attempt. Everything else
# in the prompt template — including the JSON-example braces — is
# escaped to literal text by the loader. Order does not matter; each
# is un-escaped independently.
ATTEMPT_PLACEHOLDERS: tuple[str, ...] = (
    "task_id",
    "benchmark_id",
    "prompt",
    "diff",
    "verify_output",
)


# Heading shapes the loader recognizes. ``### 1. `idiomaticity``` —
# numbered heading with a backtick-delimited dimension name.
_DIMENSION_HEADER_RE = re.compile(r"^###\s+\d+\.\s+`([a-zA-Z_][a-zA-Z0-9_]*)`\s*$", re.MULTILINE)


class RubricNotFoundError(FileNotFoundError):
    pass


class RubricParseError(ValueError):
    """Rubric file present but missing a required section."""


def load_rubric(name: str, *, rubric_dir: Optional[Path] = None) -> RubricSpec:
    """Load ``benchmarks/calibration/rubric-<name>.md`` into a RubricSpec.

    Raises ``RubricNotFoundError`` if the file is absent;
    ``RubricParseError`` if the file is present but missing a
    required section (``## Dimensions``, at least one ``### N.``
    dimension header, or the ``## Prompt template`` code block).
    """
    base = rubric_dir or DEFAULT_RUBRIC_DIR
    path = base / f"rubric-{name}.md"
    if not path.exists():
        raise RubricNotFoundError(
            f"rubric-{name}.md not found under {base}; "
            f"expected the rubric file at {path}"
        )
    text = path.read_text(encoding="utf-8")
    dimensions = _extract_dimensions(text, path)
    raw_template = _extract_prompt_template(text, path)
    dimensions_block = _extract_dimensions_block(text, path)
    rendered = _render_template(raw_template, dimensions_block)
    return RubricSpec(name=name, dimensions=dimensions, prompt_template=rendered)


# ── Section extraction ────────────────────────────────────────────────


def _extract_dimensions(text: str, path: Path) -> tuple[str, ...]:
    """Return the ordered tuple of dimension names from the file.

    Reads the ``### N. `<dim>``` headers under the ``## Dimensions``
    section. Maintains the order in which dimensions appear in the
    file (left-to-right when scanning top-to-bottom).
    """
    dims_section = _section_text(text, "## Dimensions")
    if not dims_section:
        raise RubricParseError(
            f"rubric file {path} missing '## Dimensions' section"
        )
    names = tuple(m.group(1) for m in _DIMENSION_HEADER_RE.finditer(dims_section))
    if not names:
        raise RubricParseError(
            f"rubric file {path} has '## Dimensions' but no "
            f"recognized '### N. `<name>`' dimension headers"
        )
    return names


def _extract_prompt_template(text: str, path: Path) -> str:
    """Return the first fenced code block under '## Prompt template'."""
    tmpl_section = _section_text(text, "## Prompt template")
    if not tmpl_section:
        raise RubricParseError(
            f"rubric file {path} missing '## Prompt template' section"
        )
    # Match the first ``` ... ``` fence. Allow an optional language tag
    # on the opening fence (the rubric file uses a bare ```` ``` ````).
    fence = re.search(r"```[^\n]*\n(.*?)\n```", tmpl_section, re.DOTALL)
    if not fence:
        raise RubricParseError(
            f"rubric file {path} '## Prompt template' section missing "
            f"a ``` code block"
        )
    return fence.group(1)


def _extract_dimensions_block(text: str, path: Path) -> str:
    """Return the verbatim text rendered into ``{rubric_dimensions_block}``.

    For v1, that is the ``## Dimensions`` section's body plus the
    ``## When a dimension does not apply`` section's body, joined
    with a blank line. The judge LLM then sees the full per-dimension
    descriptions + the null-rule explanation in its prompt.
    """
    dims = _section_text(text, "## Dimensions")
    null_rule = _section_text(text, "## When a dimension does not apply")
    if not dims:
        # _extract_dimensions has already raised; defensive in case
        # callers re-order.
        raise RubricParseError(
            f"rubric file {path} missing '## Dimensions' section"
        )
    parts = [dims.strip()]
    if null_rule:
        parts.append(null_rule.strip())
    return "\n\n".join(parts)


def _section_text(text: str, header: str) -> str:
    """Return the body of a markdown section identified by its '## ' header.

    The body is everything from the header line through (exclusive)
    the next ``##``-level header at the same depth. The match is
    by header *prefix* — ``"## Prompt template"`` matches both
    ``## Prompt template`` and ``## Prompt template (sent to the
    judge LLM)``, so the rubric file can carry a subtitle after the
    header without breaking the loader. Returns ``""`` if the
    header prefix is not found.
    """
    pattern = re.compile(
        rf"^{re.escape(header)}\b[^\n]*\n(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        return ""
    return m.group(1)


# ── Template rendering ────────────────────────────────────────────────


def _escape_braces(text: str) -> str:
    """Escape every ``{`` to ``{{`` and ``}`` to ``}}`` for ``str.format``."""
    return text.replace("{", "{{").replace("}", "}}")


def _unescape_placeholder(template: str, name: str) -> str:
    """Turn ``{{<name>}}`` back into ``{<name>}`` so format() will substitute."""
    return template.replace("{{" + name + "}}", "{" + name + "}")


def _render_template(raw_template: str, dimensions_block: str) -> str:
    """Compose the final prompt template that the judge will ``.format``.

    Step 1: escape every brace in the raw template — protects the
    JSON-example block's literal braces from being misread as
    format placeholders.
    Step 2: un-escape the 5 attempt placeholders so the judge can
    substitute them per call.
    Step 3: substitute ``{rubric_dimensions_block}`` (also escaped
    in step 1) with the dimensions-block content, itself
    pre-escaped so its content survives the judge's
    ``.format`` call as literal text.
    """
    escaped = _escape_braces(raw_template)
    for name in ATTEMPT_PLACEHOLDERS:
        escaped = _unescape_placeholder(escaped, name)
    escaped_block = _escape_braces(dimensions_block)
    return escaped.replace("{{rubric_dimensions_block}}", escaped_block)
