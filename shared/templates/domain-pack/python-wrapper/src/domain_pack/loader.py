"""Loader API for the domain pack.

Mirrors com.example.domainpack.PackLoader. Reads content from packaged
resources via importlib.resources — never from arbitrary filesystem paths.
"""

from __future__ import annotations

from importlib import resources
from xml.etree import ElementTree as ET

import yaml

from .models import PackEntry, PackManifest, Term

_RESOURCE_PKG = "domain_pack.data"
_TBX_NS = "{urn:iso:std:iso:30042:ed-2}"


def manifest() -> PackManifest:
    text = resources.files(_RESOURCE_PKG).joinpath("manifest.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    return PackManifest(
        name=raw["name"],
        version=raw["version"],
        schema_version=int(raw.get("schema_version", 0)),
        description=raw.get("description", ""),
        content_format=raw["content_format"],
        content_file=raw["content_file"],
        licenses=dict(raw.get("licenses", {})),
        sources=list(raw.get("sources", [])),
    )


def entries() -> list[PackEntry]:
    m = manifest()
    if m.content_format != "tbx-3.0":
        raise RuntimeError(f"Unsupported content_format: {m.content_format}")
    text = resources.files(_RESOURCE_PKG).joinpath(m.content_file).read_text(encoding="utf-8")
    return _parse_tbx(text)


def version() -> str:
    return manifest().version


def _parse_tbx(text: str) -> list[PackEntry]:
    root = ET.fromstring(text)
    out: list[PackEntry] = []
    for term_entry in root.iter(f"{_TBX_NS}termEntry"):
        entry_id = term_entry.attrib.get("id", "")
        terms: list[Term] = []
        for lang_set in term_entry.findall(f"{_TBX_NS}langSet"):
            lang = lang_set.attrib.get(
                "{http://www.w3.org/XML/1998/namespace}lang", ""
            )
            for tig in lang_set.findall(f"{_TBX_NS}tig"):
                term_el = tig.find(f"{_TBX_NS}term")
                pos = ""
                definition = ""
                for note in tig.findall(f"{_TBX_NS}termNote"):
                    if note.attrib.get("type") == "partOfSpeech":
                        pos = (note.text or "").strip()
                for descrip in tig.findall(f"{_TBX_NS}descrip"):
                    if descrip.attrib.get("type") == "definition":
                        definition = (descrip.text or "").strip()
                terms.append(
                    Term(
                        language=lang,
                        text=(term_el.text or "").strip() if term_el is not None else "",
                        part_of_speech=pos,
                        definition=definition,
                    )
                )
        out.append(PackEntry(id=entry_id, terms=terms))
    return out
