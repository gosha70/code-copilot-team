from __future__ import annotations

from domain_pack import entries, manifest, version


def test_manifest_has_required_fields() -> None:
    m = manifest()
    assert m.name
    assert m.version
    assert m.schema_version == 1
    assert m.content_format == "tbx-3.0"
    assert "data" in m.licenses
    assert "code" in m.licenses


def test_entries_load_from_sample_content() -> None:
    items = entries()
    assert items, "expected at least one term entry"
    first = items[0]
    assert first.id
    assert first.terms


def test_version_matches_manifest() -> None:
    assert version() == manifest().version
