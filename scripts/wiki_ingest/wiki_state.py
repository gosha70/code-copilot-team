# wiki_ingest.wiki_state — load existing wiki state for the multi-page ingest prompt.
#
# Phase 1 of the rescoped wiki-ingest-pipeline. The Karpathy-pattern
# maintainer prompt is wiki-aware: it includes index.md, log.md, and a
# bounded candidate set of relevant existing pages so the LLM can produce
# a multi-page write plan that integrates with current state instead of
# generating an isolated proposal.
#
# Candidate selection is a deliberately simple lexical heuristic: token
# overlap between the source content and each wiki page's title +
# frontmatter slug. It runs in O(pages × source_tokens) Python and needs
# no embeddings or external dependencies. Trade-off: it will miss
# semantic matches with no shared vocabulary; the curator is the
# backstop. Phase N may add a smarter selector if dogfooding shows the
# heuristic is too narrow.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Maximum candidate pages to load into the prompt by default. The prompt
# size budget is the 32 KiB AGENTS-style limit; ten typical wiki pages
# (~1–2 KiB each) plus index.md + log.md + the source comfortably fit.
DEFAULT_MAX_CANDIDATES = 10

# Token regex: alphanumerics + hyphens, case-folded. Stop at any other
# character. This matches slug shapes and most identifier-like words.
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]*")

# Words too common to be useful for relevance scoring. The list is
# deliberately small — a real stopword list is overkill for the
# wiki-page corpus, which is technical prose with repeating jargon.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "this", "to", "was", "were", "which", "with",
})


@dataclass(frozen=True)
class WikiState:
    """Snapshot of the existing wiki passed into the multi-page ingest prompt.

    Attributes
    ----------
    index_md : str
        Verbatim contents of ``knowledge/wiki/index.md``. Empty string
        if the wiki has no index (a fresh-repo edge case).
    log_md : str
        Verbatim contents of ``knowledge/wiki/log.md``. Empty string
        if absent.
    candidate_pages : dict[str, str]
        Map from wiki-relative path (e.g. ``concepts/origin-alignment.md``)
        to the page's full markdown content. Selected by relevance
        against the ingest source. Order is not significant; the dict
        type is preserved for stable JSON serialisation in the
        BackendPrompt.
    """
    index_md: str
    log_md: str
    candidate_pages: dict[str, str] = field(default_factory=dict)


def _tokenise(text: str) -> set[str]:
    """Return a lowercase token-set for relevance scoring."""
    if not text:
        return set()
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if tok not in _STOPWORDS}


def _read_text_or_empty(path: Path) -> str:
    """Return the file contents, or '' if the file is missing/unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _list_wiki_pages(wiki_dir: Path) -> list[Path]:
    """Return all candidate wiki .md files (excludes schema/, scripts/, index, log, overview)."""
    if not wiki_dir.is_dir():
        return []
    excluded_dirs = {"schema", "scripts"}
    excluded_stems = {"index", "log", "overview"}
    pages: list[Path] = []
    for p in sorted(wiki_dir.rglob("*.md")):
        rel_parts = p.relative_to(wiki_dir).parts
        if rel_parts and rel_parts[0] in excluded_dirs:
            continue
        if p.stem in excluded_stems and p.parent == wiki_dir:
            continue
        pages.append(p)
    return pages


def _score_page_against_source(page_path: Path, source_tokens: set[str]) -> int:
    """Score a wiki page by token overlap with the source.

    Score = |source_tokens ∩ page_signal_tokens|, where page_signal_tokens
    is the union of the page's slug, the slugified path, and the first
    400 characters of body (typically title + lead paragraph).
    Returns 0 for unreadable pages.
    """
    if not source_tokens:
        return 0
    content = _read_text_or_empty(page_path)
    if not content:
        return 0
    # Slug: filename stem.
    signal = {page_path.stem.lower()}
    # Path tokens (e.g., concepts/origin-alignment → "concepts", "origin", "alignment").
    signal |= _tokenise(str(page_path).replace("/", " ").replace("-", " "))
    # First 400 chars usually cover title + lead paragraph.
    signal |= _tokenise(content[:400])
    return len(source_tokens & signal)


def load_wiki_state(
    repo_root: Path,
    source_path: Path,
    source_content: str,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> WikiState:
    """Load index/log + a relevance-ranked candidate page set.

    Parameters
    ----------
    repo_root : Path
        Repo root. ``knowledge/wiki/`` is resolved relative to this.
    source_path : Path
        The source file being ingested. Path tokens are added to the
        relevance signal so a source under ``specs/wiki-ingest-pipeline/``
        will rank wiki pages with "wiki" in their slug higher.
    source_content : str
        The full source content; tokens drive the relevance scoring.
    max_candidates : int
        Cap on candidate pages. Pages tied at the boundary score are
        cut deterministically by sorted path order.

    Returns
    -------
    WikiState
        index_md, log_md verbatim; candidate_pages keyed by
        wiki-relative path. Returns empty state for missing wiki.
    """
    wiki_dir = repo_root / "knowledge" / "wiki"
    index_md = _read_text_or_empty(wiki_dir / "index.md")
    log_md = _read_text_or_empty(wiki_dir / "log.md")

    source_tokens = _tokenise(source_content) | _tokenise(str(source_path))

    pages = _list_wiki_pages(wiki_dir)
    scored: list[tuple[int, Path]] = []
    for page in pages:
        score = _score_page_against_source(page, source_tokens)
        if score > 0:
            scored.append((score, page))

    # Sort by descending score, then by path for stability.
    scored.sort(key=lambda pair: (-pair[0], str(pair[1])))
    selected = scored[:max_candidates]

    candidate_pages: dict[str, str] = {}
    for _score, page in selected:
        rel = str(page.relative_to(wiki_dir))
        candidate_pages[rel] = _read_text_or_empty(page)

    return WikiState(
        index_md=index_md,
        log_md=log_md,
        candidate_pages=candidate_pages,
    )
