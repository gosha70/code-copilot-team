# wiki_ingest.health_lint — Phase-4 knowledge-health lint.
#
# Four checks that go beyond the structural linter
# (knowledge/wiki/scripts/lint-wiki.sh, which validates frontmatter
# shape, slug uniqueness, intra-wiki link integrity, structural
# orphan-from-index). Knowledge-health checks the *meaning* of the
# wiki:
#
#   1. contradictions   — pairs of pages making conflicting claims
#                         about the same entity/decision (LLM-checked
#                         over candidate pairs)
#   2. stale claims     — pages whose cited path: sources have moved
#                         or no longer exist
#   3. weak orphans     — pages reachable from index.md via only one
#                         inbound edge (one hub away from disconnect)
#   4. missing cross-   — entities (page title slugs) appearing in N≥3
#      links             pages with fewer than 2 cross-links to the
#                        canonical page
#
# Default mode is advisory (exit 0 with warnings on stderr). --strict
# flips warnings to non-zero exit. --paths scopes the pass to specific
# pages.
#
# The contradictions check is the only LLM-dependent one. The test
# backend's task: lint-health response returns zero contradictions on
# clean fixtures so unit tests are deterministic.

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import BackendInvocationError
from .ingestor import Backend
from .proposal import HealthFinding
from .wiki_state import _read_text_or_empty
from . import yaml_lite


# Pattern for [text](path.md) intra-wiki links.
_MD_LINK_RE = re.compile(r"\]\(([^)]+\.md)(?:#[^)]*)?\)")


@dataclass(frozen=True)
class HealthLintResult:
    """Aggregated output of a knowledge-health pass."""
    findings: list[HealthFinding]
    pages_checked: int


def _list_wiki_pages(wiki_dir: Path) -> list[Path]:
    """All wiki .md files except those under schema/, scripts/."""
    if not wiki_dir.is_dir():
        return []
    excluded = {"schema", "scripts"}
    pages: list[Path] = []
    for p in sorted(wiki_dir.rglob("*.md")):
        rel_parts = p.relative_to(wiki_dir).parts
        if rel_parts and rel_parts[0] in excluded:
            continue
        pages.append(p)
    return pages


def _intra_wiki_links_from(page: Path, wiki_dir: Path) -> list[str]:
    """Return wiki-relative .md targets linked from ``page``."""
    out: list[str] = []
    try:
        text = page.read_text(encoding="utf-8")
    except OSError:
        return out
    page_dir = page.parent
    for m in _MD_LINK_RE.finditer(text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        # Resolve relative to the page's directory.
        resolved = (page_dir / target).resolve()
        try:
            rel = resolved.relative_to(wiki_dir.resolve())
        except ValueError:
            # Escape link (e.g. ../../../shared/...). Not intra-wiki.
            continue
        out.append(rel.as_posix())
    return out


def _check_stale_claims(
    wiki_dir: Path,
    repo_root: Path,
) -> list[HealthFinding]:
    """For each page's frontmatter sources entries, check that
    ``path:`` references resolve. Missing paths → stale-claim
    warning.

    Does NOT verify ``sha:`` against git (that would require shelling
    out and is left to a future check). Does NOT HEAD-fetch URLs
    (network-dependent; out of scope for the deterministic in-process
    pass).
    """
    findings: list[HealthFinding] = []
    for page in _list_wiki_pages(wiki_dir):
        content = _read_text_or_empty(page)
        if not content:
            continue
        try:
            fm = yaml_lite.parse_frontmatter(content)
        except Exception:
            continue
        sources = fm.get("sources") or []
        if not isinstance(sources, list):
            continue
        rel = page.relative_to(wiki_dir).as_posix()
        for src in sources:
            if not isinstance(src, dict):
                continue
            cited_path = src.get("path")
            if not cited_path:
                continue
            target = repo_root / cited_path
            if not target.exists():
                findings.append(HealthFinding(
                    kind="stale-claim",
                    severity="warning",
                    pages=[rel],
                    description=(
                        f"page cites missing source path: {cited_path!r} "
                        f"(no file at {target.relative_to(repo_root)} — "
                        f"file may have been renamed, moved, or deleted)"
                    ),
                ))
    return findings


def _check_weak_orphans(wiki_dir: Path) -> list[HealthFinding]:
    """A wiki page reachable from index.md via only ONE inbound edge
    is one hub-disconnect away from full orphanhood. Flag it as a
    weak orphan so the curator can add a second cross-link.

    Counts inbound edges per page across the whole wiki (not just
    from index.md). index.md and log.md are exempt (they are the
    hub primitives, not destinations).
    """
    findings: list[HealthFinding] = []
    pages = _list_wiki_pages(wiki_dir)
    inbound: dict[str, set[str]] = defaultdict(set)

    for src in pages:
        src_rel = src.relative_to(wiki_dir).as_posix()
        for tgt_rel in _intra_wiki_links_from(src, wiki_dir):
            inbound[tgt_rel].add(src_rel)

    for page in pages:
        rel = page.relative_to(wiki_dir).as_posix()
        if rel in ("index.md", "log.md", "overview.md"):
            continue
        edges = inbound.get(rel, set())
        if len(edges) == 1:
            (only_hub,) = edges
            findings.append(HealthFinding(
                kind="weak-orphan",
                severity="warning",
                pages=[rel],
                description=(
                    f"page reachable via a single inbound link from "
                    f"{only_hub!r}; if that hub changes, this page "
                    f"becomes a structural orphan. Add a second "
                    f"cross-link from a related page."
                ),
            ))
    return findings


def _entity_mentions(text: str, candidates: list[str]) -> set[str]:
    """Return the subset of ``candidates`` that appear as whole-word
    matches in ``text`` (case-insensitive)."""
    seen: set[str] = set()
    if not text or not candidates:
        return seen
    lower = text.lower()
    for slug in candidates:
        # Match the slug as a hyphenated identifier OR the slug with
        # hyphens replaced by spaces (e.g. "origin alignment").
        if slug.lower() in lower:
            seen.add(slug)
        spaced = slug.replace("-", " ").lower()
        if spaced != slug.lower() and spaced in lower:
            seen.add(slug)
    return seen


def _check_missing_cross_links(wiki_dir: Path) -> list[HealthFinding]:
    """Entities (page title slugs) that appear in N≥3 pages with
    fewer than 2 cross-links to the canonical page are flagged.

    Heuristic: take the set of title slugs across the wiki as the
    entity vocabulary. For each slug, count pages whose body (NOT
    frontmatter) mentions the slug; count pages that link to the
    canonical page. If mentions ≥ 3 and links ≤ 1, flag.
    """
    findings: list[HealthFinding] = []
    pages = _list_wiki_pages(wiki_dir)

    # Build slug → canonical-page map.
    slug_to_page: dict[str, str] = {}
    for page in pages:
        rel = page.relative_to(wiki_dir).as_posix()
        slug = Path(rel).stem
        # Skip index/log/overview (not entities).
        if slug in ("index", "log", "overview"):
            continue
        slug_to_page[slug] = rel

    # For each page, collect mentions and outbound links.
    page_mentions: dict[str, set[str]] = {}    # page → set of slugs mentioned in body
    page_links: dict[str, set[str]] = {}       # page → set of pages linked TO
    for page in pages:
        rel = page.relative_to(wiki_dir).as_posix()
        content = _read_text_or_empty(page)
        # Strip frontmatter for the mention scan.
        body = content
        if content.startswith("---"):
            close_idx = content.find("\n---", 3)
            if close_idx != -1:
                body = content[close_idx + 4:]
        page_mentions[rel] = _entity_mentions(body, list(slug_to_page.keys()))
        page_links[rel] = set(_intra_wiki_links_from(page, wiki_dir))

    # index/log/overview are hubs by design — every page is linked
    # from them, every entity mention is incidental. Exclude from
    # both mention and link counts so the heuristic flags missing
    # CROSS-links between content pages, not the trivially-present
    # index link.
    HUB = {"index.md", "log.md", "overview.md"}

    for slug, canonical_rel in slug_to_page.items():
        mention_pages = {
            p for p, mentions in page_mentions.items()
            if slug in mentions and p != canonical_rel and p not in HUB
        }
        link_pages = {
            p for p, links in page_links.items()
            if canonical_rel in links and p != canonical_rel and p not in HUB
        }
        if len(mention_pages) >= 3 and len(link_pages) < 2:
            unlinked = sorted(mention_pages - link_pages)
            findings.append(HealthFinding(
                kind="missing-cross-link",
                severity="warning",
                pages=[canonical_rel] + unlinked,
                description=(
                    f"entity {slug!r} (canonical page {canonical_rel}) "
                    f"is mentioned in {len(mention_pages)} other "
                    f"pages but only cross-linked from "
                    f"{len(link_pages)}; consider adding cross-links "
                    f"from: {', '.join(unlinked[:5])}"
                    + (" …" if len(unlinked) > 5 else "")
                ),
            ))
    return findings


def _check_contradictions(
    wiki_dir: Path,
    backend: Backend | None,
) -> list[HealthFinding]:
    """LLM-checked contradiction pass.

    Generates candidate page pairs (pages sharing a source path or a
    cross-link edge), sends each pair to the backend with a "do these
    contradict?" prompt, collects positive findings.

    When ``backend`` is None, the check is a no-op (returns []) — used
    by tests that don't want to set up a backend, and by the CLI when
    the user opts out of LLM calls (future ``--no-llm-checks`` flag).
    """
    if backend is None:
        return []

    findings: list[HealthFinding] = []
    pages = _list_wiki_pages(wiki_dir)
    pairs = _candidate_pairs(pages, wiki_dir)
    for left, right in pairs:
        prompt = _compose_contradiction_prompt(left, right, wiki_dir)
        try:
            response = backend.call(prompt)
        except BackendInvocationError:
            # A failed contradiction check shouldn't block the whole
            # health pass — log nothing, move on.
            continue
        if isinstance(response, dict):
            data = response
        else:
            try:
                data = json.loads(response)
            except json.JSONDecodeError:
                continue
        if data.get("contradicts") is True:
            findings.append(HealthFinding(
                kind="contradiction",
                severity="warning",
                pages=[
                    left.relative_to(wiki_dir).as_posix(),
                    right.relative_to(wiki_dir).as_posix(),
                ],
                description=(
                    str(data.get("description", "(no description)"))
                ),
            ))
    return findings


def _candidate_pairs(
    pages: list[Path],
    wiki_dir: Path,
) -> list[tuple[Path, Path]]:
    """Generate (left, right) page pairs likely to contradict.

    Heuristic: two pages are candidates if they share at least one
    cited source path (frontmatter sources[].path) or one of them
    links to the other. This reduces O(N^2) page pairs to a
    manageable subset.
    """
    sources_per_page: dict[Path, set[str]] = {}
    for page in pages:
        text = _read_text_or_empty(page)
        if not text:
            sources_per_page[page] = set()
            continue
        try:
            fm = yaml_lite.parse_frontmatter(text)
        except Exception:
            sources_per_page[page] = set()
            continue
        srcs: set[str] = set()
        for s in fm.get("sources") or []:
            if isinstance(s, dict) and s.get("path"):
                srcs.add(str(s["path"]))
        sources_per_page[page] = srcs

    links_per_page: dict[Path, set[str]] = {
        p: set(_intra_wiki_links_from(p, wiki_dir)) for p in pages
    }

    pairs: list[tuple[Path, Path]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for i, left in enumerate(pages):
        for right in pages[i + 1:]:
            key = (
                left.relative_to(wiki_dir).as_posix(),
                right.relative_to(wiki_dir).as_posix(),
            )
            if key in seen_pairs:
                continue
            shared_sources = sources_per_page[left] & sources_per_page[right]
            link_lr = right.relative_to(wiki_dir).as_posix() in links_per_page[left]
            link_rl = left.relative_to(wiki_dir).as_posix() in links_per_page[right]
            if shared_sources or link_lr or link_rl:
                pairs.append((left, right))
                seen_pairs.add(key)
    return pairs


def _compose_contradiction_prompt(
    left: Path,
    right: Path,
    wiki_dir: Path,
) -> dict[str, Any]:
    """A minimal prompt asking the backend whether two pages
    contradict on a shared topic. Response shape:
    {version: 1, contradicts: bool, description: str}.
    """
    left_rel = left.relative_to(wiki_dir).as_posix()
    right_rel = right.relative_to(wiki_dir).as_posix()
    schema = {
        "type": "object",
        "required": ["version", "contradicts", "description"],
        "properties": {
            "version": {"type": "integer", "const": 1},
            "contradicts": {"type": "boolean"},
            "description": {"type": "string"},
        },
    }
    return {
        "version": 1,
        "system_instructions": (
            "Read the two wiki pages. They share a source or a link, "
            "so they may discuss the same topic. Decide whether they "
            "make conflicting claims that a curator should reconcile. "
            "Return one JSON object with keys: contradicts (bool), "
            "description (one-sentence reconciliation hint). False is "
            "the default; only set true on a substantive disagreement."
        ),
        "task": "lint-health",
        "schema_excerpts": {
            "ingest_rules": "",
            "page_types": "",
            "citation_rules": "",
        },
        "source": {
            "kind": "page-pair",
            "path": f"{left_rel} <-> {right_rel}",
            "content": f"=== {left_rel} ===\n" + _read_text_or_empty(left)
                       + f"\n=== {right_rel} ===\n" + _read_text_or_empty(right),
        },
        "wiki_state": {},
        "response_schema": json.dumps(schema),
    }


def lint_health(
    repo_root: Path,
    paths: list[str] | None = None,
    backend: Backend | None = None,
) -> HealthLintResult:
    """Run all four knowledge-health checks against the wiki.

    Parameters
    ----------
    repo_root : Path
        Repo root; ``knowledge/wiki/`` resolved relative to it.
    paths : list[str] | None
        If provided, scope checks to these wiki-relative paths.
        Currently honored only by stale-claims; the graph-based
        checks (orphans, cross-links) need the whole wiki to compute
        edge counts. A future iteration could rescope them.
    backend : Backend | None
        When provided, runs the LLM-dependent contradictions check.
        When None, contradictions are skipped (clean exit on local
        runs without a configured backend).
    """
    wiki_dir = repo_root / "knowledge" / "wiki"
    pages = _list_wiki_pages(wiki_dir)

    findings: list[HealthFinding] = []
    findings.extend(_check_stale_claims(wiki_dir, repo_root))
    findings.extend(_check_weak_orphans(wiki_dir))
    findings.extend(_check_missing_cross_links(wiki_dir))
    findings.extend(_check_contradictions(wiki_dir, backend))

    if paths:
        scoped = set(paths)
        findings = [f for f in findings if any(p in scoped for p in f.pages)]

    return HealthLintResult(
        findings=findings,
        pages_checked=len(pages),
    )
