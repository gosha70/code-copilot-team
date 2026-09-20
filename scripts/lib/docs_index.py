#!/usr/bin/env python3
"""The documentation index, rendered from the Learn registry.

One implementation of "what is each page called, and what is its first
sentence", for every surface that lists the docs: the README and landing-page
index (scripts/generate-readme-inserts.sh, block `docs-index`) and the
experimental llms.txt (scripts/generate-llms-txt.sh). The registry,
scripts/session_analytics/config_data/learn-sections.json, is the same
allowlist the Studio's Learn tab and the docs site read, so none of them can
disagree about what documentation exists.

Usage: docs_index.py <registry.json> <repo-dir> markdown|llms
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Set by main(); title_of and lead_of read them.
titles: dict = {}
repo = Path(".")

def title_of(rel: str) -> str:
    if rel in titles:
        return titles[rel]
    text = (repo / rel).read_text(encoding="utf-8") if (repo / rel).is_file() else ""
    for line in text.split("\n"):
        if line.startswith("# "):
            return re.sub(r"\s+", " ", line[2:]).strip()
    return Path(rel).stem.replace("-", " ").title()

def lead_of(rel: str) -> str:
    """First prose sentence of a page, or a note that it is generated.

    Three things are not prose and must be stepped over, each found the hard
    way: YAML frontmatter (a wiki page's first line is `page_type: overview`),
    fenced code (a shell comment inside a fence reads exactly like a markdown
    heading, and the README's first fence opens with `# 1. Clone the latest
    stable release`), and a multi-line HTML element whose text content is
    markup rather than prose (the README's <h1>).

    The paragraph is joined BEFORE the sentence is cut: markdown wraps prose
    at the source line, so cutting at the first line ends a description on
    "which" or "in two".
    """
    path = repo / rel
    if not path.is_file():
        return ""
    body = path.read_text(encoding="utf-8").split("\n")
    if any("GENERATED — do not edit" in line for line in body[:10]):
        return "generated from its sources; edit the source, not the page"

    start = 0
    if body and body[0].strip() == "---":
        for i in range(1, len(body)):
            if body[i].strip() == "---":
                start = i + 1
                break

    in_fence = in_comment = False
    open_tags = 0
    paragraph: list[str] = []
    for line in body[start:]:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if "<!--" in stripped:
            in_comment = "-->" not in stripped
            continue
        if in_comment:
            in_comment = "-->" not in stripped
            continue
        opened = len([t for t in re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)(?=[\s/>])[^>]*>", line)
                      if not re.search(rf"<{t}[^>]*/>", line)])
        closed = len(re.findall(r"</[a-zA-Z][a-zA-Z0-9]*>", line))
        was_open = open_tags
        open_tags = max(0, open_tags + opened - closed)
        if was_open or opened or closed:
            continue
        if not stripped:
            if paragraph:
                break          # the paragraph ended
            continue
        # A marker only counts as one in marker position: "**Learn** tab …" is
        # prose that happens to start with an asterisk, and cutting there ended
        # this page's own description at "the Studio's".
        if re.match(r"^([-*+]\s|#{1,6}\s|>|\||!\[|<|={3,}$|-{3,}$)", stripped):
            if paragraph:
                break          # prose ran into a list or a heading
            continue
        paragraph.append(stripped)

    if not paragraph:
        return ""
    text = re.sub(r"\s+", " ", " ".join(paragraph)).strip()
    # Split on sentence ends, not on every period: "e.g." and "3.11" are not
    # sentence boundaries.
    match = re.search(r"(?<=[.;])\s+(?=[A-Z(`\[])", text)
    sentence = text[:match.start()] if match else text
    return sentence.rstrip(".").strip()


def listed_sections(registry: dict) -> list[dict]:
    sections = [s for s in registry.get("sections", []) if s.get("paths")]
    if not sections:
        print("[ERROR] no path-listed sections in the Learn registry", file=sys.stderr)
        raise SystemExit(1)
    for section in sections:
        for rel in section["paths"]:
            if not (repo / rel).is_file():
                print(f"[ERROR] the Learn registry lists a file that does not exist: {rel}", file=sys.stderr)
                raise SystemExit(1)
    return sections


def render_markdown(registry: dict) -> str:
    """The `docs-index` block: links relative to docs/README.md."""
    out = []
    for section in listed_sections(registry):
        out.append(f"### {section['title']}")
        out.append("")
        for rel in section["paths"]:
            href = rel[len("docs/"):] if rel.startswith("docs/") else "../" + rel
            lead = lead_of(rel)
            out.append(f"- [{title_of(rel)}]({href})" + (f" — {lead}" if lead else ""))
        out.append("")
    return "\n".join(out).rstrip()


def render_llms(registry: dict) -> str:
    """llms.txt in the llmstxt.org shape: H1, a blockquote summary, then one
    H2 per section of `- [title](url): description` links to the raw Markdown.
    """
    raw = registry["repo_url"].replace("https://github.com/", "https://raw.githubusercontent.com/")
    raw = f"{raw}/{registry['repo_branch']}"
    out = [
        "# Code Copilot Team",
        "",
        f"> {lead_of('README.md')}.",
        "",
        "Experimental: llms.txt is a proposal (llmstxt.org), not a standard. This file is "
        "generated by scripts/generate-llms-txt.sh from the same registry as the documentation "
        f"index, and links to the Markdown on the `{registry['repo_branch']}` branch, which is "
        "ahead of the latest release.",
        "",
    ]
    for section in listed_sections(registry):
        out.append(f"## {section['title']}")
        out.append("")
        for rel in section["paths"]:
            lead = lead_of(rel)
            out.append(f"- [{title_of(rel)}]({raw}/{rel})" + (f": {lead}" if lead else ""))
        out.append("")
    return "\n".join(out).rstrip()


def main(argv: list[str]) -> int:
    global titles, repo
    if len(argv) != 4 or argv[3] not in ("markdown", "llms"):
        print(__doc__.strip().split("\n")[-1], file=sys.stderr)
        return 2
    registry = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    titles = registry.get("titles", {})
    repo = Path(argv[2])
    print(render_markdown(registry) if argv[3] == "markdown" else render_llms(registry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
