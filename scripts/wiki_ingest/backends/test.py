# wiki_ingest.backends.test — deterministic test backend (no LLM, no subprocess).

from __future__ import annotations

import re
from typing import Any


def _extract_h1(content: str) -> str:
    """Return the first H1 heading text from a markdown string, or a fallback."""
    for line in content.splitlines():
        m = re.match(r"^#\s+(.+)", line)
        if m:
            return m.group(1).strip()
    return "Untitled"


def _to_kebab(title: str) -> str:
    """Convert a title string to a kebab-case slug."""
    # Lowercase, replace non-alphanumeric runs with hyphens, strip leading/trailing.
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "untitled"


class TestBackend:
    """Deterministic in-process backend for unit and integration tests.

    Rules:
    - page_type is always "incident".
    - slug is derived from the source H1 (kebab-case).
    - title is the source H1 verbatim.
    - sources is a single fixed entry (the source path).
    - draft_markdown is constructed to satisfy ALL semantic-validation rules so
      the test backend round-trips clean through parse_response().
    - disposition is always "accept".

    This backend must NOT be selected by auto-detect; use --backend test explicitly.
    """

    def call(self, prompt: dict[str, Any]) -> dict[str, Any]:
        source = prompt.get("source", {})
        content = source.get("content", "")
        source_path = source.get("path", "unknown-source.md")

        h1 = _extract_h1(content)
        slug = _to_kebab(h1)
        page_type = "incident"
        title = h1
        today = "2026-05-04"

        sources = [{"path": source_path, "sha": "abc1234"}]

        # Build a draft_markdown that passes semantic validation:
        #   - frontmatter page_type, slug, title, sources match the structured fields exactly.
        #   - page_type == "incident" → directory is incidents/ (validated at lint time).
        sources_yaml = "\n".join(
            f"  - path: {s['path']}\n    sha: {s['sha']}"
            for s in sources
        )
        draft_markdown = (
            f"---\n"
            f"page_type: {page_type}\n"
            f"slug: {slug}\n"
            f"title: {title}\n"
            f"status: draft\n"
            f"last_reviewed: {today}\n"
            f"sources:\n"
            f"{sources_yaml}\n"
            f"---\n"
            f"\n"
            f"# {title}\n"
            f"\n"
            f"## What happened\n"
            f"\n"
            f"(Test backend placeholder — replace with real content.)\n"
            f"\n"
            f"## Why it happened\n"
            f"\n"
            f"(Root cause placeholder.)\n"
            f"\n"
            f"## What we changed\n"
            f"\n"
            f"(Remediation placeholder.)\n"
            f"\n"
            f"## How to recognize a recurrence\n"
            f"\n"
            f"(Recurrence signals placeholder.)\n"
        )

        return {
            "version": 1,
            "disposition": "accept",
            "reason": "Test backend always accepts; deterministic output for CI.",
            "page_type": page_type,
            "slug": slug,
            "title": title,
            "draft_markdown": draft_markdown,
            "sources": sources,
        }
