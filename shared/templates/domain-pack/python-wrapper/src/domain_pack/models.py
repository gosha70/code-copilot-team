from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Term:
    language: str
    text: str
    part_of_speech: str = ""
    definition: str = ""


@dataclass(frozen=True)
class PackEntry:
    id: str
    terms: list[Term] = field(default_factory=list)


@dataclass(frozen=True)
class PackManifest:
    name: str
    version: str
    schema_version: int
    description: str
    content_format: str
    content_file: str
    licenses: dict[str, str]
    sources: list[dict[str, str]]
