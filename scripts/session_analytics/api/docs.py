# session_analytics.api.docs — the Learn center's document registry (#309).
#
# The Studio serves the repository's OWN markdown — setup guides, hooks,
# permissions, skills, agents, the wiki — so a finding on the session page
# can link to the page that explains the fix. The rule that makes that
# safe: the set of servable files is CLOSED. It is enumerated once from
# config_data/learn-sections.json (explicit paths + globs under named
# directories, minus deny prefixes), every entry is checked to resolve
# under the repo root, and a request is answered only by slug lookup in
# that registry. No route ever builds a path from user input.
#
# The same discipline as routing_evidence.serve_evidence_file: closed
# vocabulary, containment, never an absolute path in a payload.

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from ..config import REPO_ROOT, load_map

_SPEC_FILE = "learn-sections.json"
_SLUG_SEP = "--"
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_FENCE_RE = re.compile(r"^```.*?^```[ \t]*$", re.M | re.S)
_README_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


class UnknownDocError(KeyError):
    """The slug names nothing in the registry."""


class UnknownImageError(KeyError):
    """The image name is not one of the files in the image directory."""


@dataclass(frozen=True)
class DocEntry:
    slug: str
    path: str            # repo-relative, POSIX
    section: str
    kind: str            # doc | wiki | skill | agent
    title: str
    description: str
    page_type: Optional[str]
    generated: bool


@dataclass(frozen=True)
class Registry:
    sections: tuple[dict[str, Any], ...]     # {id, title, kind, entries: [DocEntry]}
    by_slug: dict[str, DocEntry]
    repo_url: str
    repo_branch: str
    intents: tuple[dict[str, Any], ...]
    finding_links: dict[str, str]
    image_dir: str


def slug_for(path: str) -> str:
    """`adapters/claude-code/docs/hooks-guide.md` → `adapters--claude-code--docs--hooks-guide`.
    One URL segment, reversible only through the registry."""
    stem = path[:-3] if path.endswith(".md") else path
    return stem.replace("/", _SLUG_SEP)


def _contained(root: Path, rel: str) -> Optional[Path]:
    """The absolute file for a repo-relative path, or None when it escapes
    the root or does not exist. resolve() follows symlinks, so a link
    out of the tree is caught too."""
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    """A flat `key: value` frontmatter block and the body after it. Only
    what titles need; no YAML parser, no nested values."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t", "-")):
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[m.end():]


def _clean_title(raw: str) -> str:
    # `# **🎛️ Claude Code Setup Cookbook**` → `Claude Code Setup Cookbook`;
    # `# \`knowledge/\` — Project Knowledge Layer` → `knowledge/ — Project Knowledge Layer`
    t = raw.replace("**", "").replace("`", "").strip()
    t = re.sub(r"^[^\w(\[/.]+", "", t)   # leading emoji / symbols
    return t.strip() or raw.strip()


def _first_h1(body: str) -> Optional[str]:
    """The first H1 OUTSIDE fenced code — a shell comment in a code block
    is not a heading (the README's first `# ` line is one)."""
    m = _H1_RE.search(_FENCE_RE.sub("", body))
    return m.group(1) if m else None


def _readme_titles(root: Path, spec: dict[str, Any]) -> dict[str, str]:
    """path → curated link text from the README's documentation index."""
    readme = _contained(root, "README.md")
    if readme is None:
        return {}
    text = readme.read_text(encoding="utf-8")
    heading = str(spec.get("readme_index_heading", "## Documentation"))
    start = text.find(heading)
    if start < 0:
        return {}
    end = text.find("\n## ", start + len(heading))
    block = text[start:end if end > 0 else None]
    return {path: title for title, path in _README_LINK_RE.findall(block)}


def _describe(
    path: str, kind: str, text: str, curated: dict[str, str], overrides: dict[str, str], marker: str,
) -> tuple[str, str, Optional[str], bool]:
    meta, body = _frontmatter(text)
    generated = marker in "\n".join(text.splitlines()[:5])
    if kind in ("wiki", "skill", "agent"):
        title = meta.get("title") or meta.get("name") or ""
        description = meta.get("description", "")
        page_type = meta.get("page_type") or kind
    else:
        title = overrides.get(path) or curated.get(path, "")
        description = ""
        page_type = None
    if not title:
        h1 = _first_h1(body)
        title = _clean_title(h1) if h1 else Path(path).stem
    return title, description, page_type, generated


def _denied(rel: str, deny: tuple[str, ...]) -> bool:
    return any(rel.startswith(prefix) for prefix in deny)


@lru_cache(maxsize=1)
def registry(root: Optional[Path] = None) -> Registry:
    """Enumerate the allowlist once. Missing files are skipped (a renamed
    doc must not 500 the whole index); the test suite asserts every
    explicit path exists so a rename is caught there instead."""
    root = (root or REPO_ROOT).resolve()
    spec = load_map(_SPEC_FILE)
    deny = tuple(str(p) for p in spec.get("deny_prefixes", []))
    marker = str(spec.get("generated_marker", ""))
    curated = _readme_titles(root, spec)
    overrides = {str(k): str(v) for k, v in spec.get("titles", {}).items()}

    sections: list[dict[str, Any]] = []
    by_slug: dict[str, DocEntry] = {}
    for sec in spec["sections"]:
        kind = str(sec["kind"])
        rels: list[str] = list(sec.get("paths", []))
        for pattern in sec.get("globs", []):
            rels.extend(
                sorted(p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file())
            )
        entries: list[DocEntry] = []
        for rel in rels:
            if _denied(rel, deny):
                continue
            absolute = _contained(root, rel)
            if absolute is None:
                continue
            text = absolute.read_text(encoding="utf-8", errors="replace")
            title, description, page_type, generated = _describe(
                rel, kind, text, curated, overrides, marker
            )
            entry = DocEntry(
                slug=slug_for(rel), path=rel, section=str(sec["id"]), kind=kind,
                title=title, description=description, page_type=page_type,
                generated=generated,
            )
            if entry.slug in by_slug:
                continue
            by_slug[entry.slug] = entry
            entries.append(entry)
        sections.append({"id": sec["id"], "title": sec["title"], "kind": kind, "entries": entries})

    finding_links = {
        k: str(v) for k, v in spec.get("finding_links", {}).items() if not k.startswith("_")
    }
    return Registry(
        sections=tuple(sections),
        by_slug=by_slug,
        repo_url=str(spec.get("repo_url", "")),
        repo_branch=str(spec.get("repo_branch", "master")),
        intents=tuple(spec.get("intents", [])),
        finding_links=finding_links,
        image_dir=str(spec.get("image_dir", "docs/images")),
    )


def _entry_payload(e: DocEntry) -> dict[str, Any]:
    return {
        "slug": e.slug, "path": e.path, "section": e.section, "kind": e.kind,
        "title": e.title, "description": e.description, "page_type": e.page_type,
        "generated": e.generated,
    }


def index() -> dict[str, Any]:
    """`GET /api/docs`: sections with their entries, the intent cards, the
    finding → slug map, and what a client needs to rewrite links."""
    reg = registry()
    return {
        "sections": [
            {"id": s["id"], "title": s["title"], "kind": s["kind"],
             "entries": [_entry_payload(e) for e in s["entries"]]}
            for s in reg.sections
        ],
        "intents": list(reg.intents),
        "finding_links": dict(reg.finding_links),
        "repo_url": reg.repo_url,
        "repo_branch": reg.repo_branch,
        "image_route": "/api/docs/image/",
    }


def document(slug: str) -> dict[str, Any]:
    """`GET /api/docs/{slug}`: the entry plus its markdown body. The slug
    is looked up, never turned into a path."""
    reg = registry()
    entry = reg.by_slug.get(slug)
    if entry is None:
        raise UnknownDocError(slug)
    absolute = _contained(REPO_ROOT.resolve(), entry.path)
    if absolute is None:
        raise UnknownDocError(slug)
    text = absolute.read_text(encoding="utf-8", errors="replace")
    meta, body = _frontmatter(text)
    return {**_entry_payload(entry), "frontmatter": meta, "body": html_to_markdown(body)}


# The renderer shows raw HTML as text — deliberately: a raw-HTML pass
# would swallow the angle-bracket placeholders the guides are full of
# (`<feature-id>`, `<dgx-spark-ip>`). The real HTML in the corpus is a
# handful of GitHub-README constructs, converted here to markdown.
_FENCE = re.compile(r"```.*?```", re.S)
_H1_HTML = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_IMG_HTML = re.compile(r"<img\b([^>]*?)/?>", re.S | re.I)
_BR_HTML = re.compile(r"<br\s*/?>", re.I)
_ATTR = re.compile(r'([a-zA-Z-]+)\s*=\s*"([^"]*)"')


#: An <img width="250"> keeps its width as the image title, which the
#: Studio's image renderer reads (markdown images have no size syntax).
IMG_WIDTH_TITLE = "width="


def _img_md(tag_attrs: str) -> str:
    attrs = dict(_ATTR.findall(tag_attrs))
    src = attrs.get("src", "")
    if not src:
        return ""
    width = attrs.get("width", "").strip()
    title = f' "{IMG_WIDTH_TITLE}{width}"' if width.isdigit() else ""
    return f"![{attrs.get('alt', '')}]({src}{title})"


def html_to_markdown(body: str) -> str:
    """``<h1><img …/> Title</h1>`` → the image, then ``# Title``; a bare
    ``<img>`` → ``![alt](src)``; ``<br>`` → a line break. Fenced code is
    left untouched, and unknown tags are left as they are."""
    out: list[str] = []
    pos = 0
    for m in _FENCE.finditer(body):
        out.append(_convert_prose(body[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_convert_prose(body[pos:]))
    return "".join(out)


def _convert_prose(text: str) -> str:
    def h1(m: re.Match) -> str:
        inner = m.group(1)
        images = [_img_md(a) for a in _IMG_HTML.findall(inner)]
        title = " ".join(_IMG_HTML.sub("", inner).split())
        lead = "\n\n".join(i for i in images if i)
        return (lead + "\n\n" if lead else "") + f"# {title}"

    text = _H1_HTML.sub(h1, text)
    text = _IMG_HTML.sub(lambda m: _img_md(m.group(1)), text)
    return _BR_HTML.sub("  \n", text)


def image_file(name: str) -> tuple[Path, str]:
    """`GET /api/docs/image/{name}`: a file in the image directory, by bare
    name only — no separators, no dotfiles — with its media type."""
    reg = registry()
    if not _IMAGE_NAME_RE.match(name):
        raise UnknownImageError(name)
    media = _IMAGE_TYPES.get(Path(name).suffix.lower())
    if media is None:
        raise UnknownImageError(name)
    absolute = _contained(REPO_ROOT.resolve(), f"{reg.image_dir}/{name}")
    if absolute is None:
        raise UnknownImageError(name)
    return absolute, media
