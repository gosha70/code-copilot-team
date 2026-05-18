# tests/test_audit_lint.py — Phase-1 audit-format lint + .audit/ reader exclusion.

import json
import tempfile
import unittest
from pathlib import Path

from wiki_ingest.audit_lint import (
    INGEST_LOG_MARKER,
    validate_audit_dir,
)
from wiki_ingest.health_lint import _list_wiki_pages as health_pages
from wiki_ingest.wiki_state import _list_wiki_pages as state_pages

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "wiki_audit"
_HEX = "a" * 64


def _valid_record(**ov: object) -> dict:
    r = {
        "v": 1,
        "ts": "2026-05-17T14:03:22Z",
        "source_path": "specs/x/spec.md",
        "source_repo_relative": True,
        "source_sha": _HEX,
        "backend": "test",
        "disposition": "accept",
        "reason": "wiki-worthy: durable cross-session lesson.",
        "proposal_dir": "2026-05-17-x",
        "target_paths": ["concepts/a.md"],
        "page_types": ["concept"],
        "proposal_hash": _HEX,
    }
    r.update(ov)
    return r


def _write_audit(root: Path, lines: list) -> Path:
    audit = root / ".audit"
    audit.mkdir(parents=True)
    body = INGEST_LOG_MARKER + "\n\n" + "\n".join(
        json.dumps(x) if isinstance(x, dict) else x for x in lines
    ) + "\n"
    (audit / "ingest-log.md").write_text(body, encoding="utf-8")
    return audit


class TestAuditFixtures(unittest.TestCase):
    def test_valid_fixture_is_clean(self) -> None:
        self.assertEqual(validate_audit_dir(_FIXTURES / "valid"), [])

    def test_each_invalid_fixture_flags_its_defect(self) -> None:
        expected = {
            "invalid-missing-marker": "line 1 must be exactly",
            "invalid-malformed-json": "not valid JSON",
            "invalid-missing-key": "missing keys ['proposal_hash']",
            "invalid-bad-enum": "disposition 'maybe' not in",
            "invalid-reason-too-long": "reason is 241 codepoints",
            "invalid-malformed-ts": "is not ISO-8601 UTC",
        }
        for case, needle in expected.items():
            errs = validate_audit_dir(_FIXTURES / case)
            self.assertTrue(errs, f"{case}: expected a violation, got none")
            self.assertTrue(
                any(needle in e for e in errs),
                f"{case}: no violation matched {needle!r}; got {errs}",
            )

    def test_absent_audit_tree_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(validate_audit_dir(Path(td) / "nope"), [])


class TestAuditNestedConstraints(unittest.TestCase):
    def test_unsupported_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit = _write_audit(Path(td), [_valid_record(v=2)])
            errs = validate_audit_dir(audit)
            self.assertTrue(any("unsupported schema version" in e for e in errs))

    def test_array_items_must_be_strings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit = _write_audit(
                Path(td),
                [_valid_record(target_paths=[123], page_types=[False])],
            )
            errs = validate_audit_dir(audit)
            self.assertTrue(
                any("'target_paths' must be an array of strings" in e
                    for e in errs),
                errs,
            )

    def test_stray_top_level_entry_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit = _write_audit(Path(td), [_valid_record()])
            (audit / "notes.md").write_text("stray\n", encoding="utf-8")
            errs = validate_audit_dir(audit)
            self.assertTrue(
                any("unexpected entry under .audit/" in e for e in errs),
                errs,
            )

    def test_plan_json_as_directory_is_violation_not_exception(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit = _write_audit(Path(td), [_valid_record()])
            pdir = audit / "proposals" / "2026-05-17-x"
            pdir.mkdir(parents=True)
            (pdir / "plan.json").mkdir()  # a directory, not a file
            (pdir / "proposal.md").write_text("body\n", encoding="utf-8")
            errs = validate_audit_dir(audit)  # must not raise
            self.assertTrue(
                any("plan.json: must be a regular file" in e for e in errs),
                errs,
            )


class TestAuditReaderExclusion(unittest.TestCase):
    """`.audit/` must be invisible to the wiki-page readers."""

    def _wiki_with_audit(self, root: Path) -> Path:
        wiki = root / "knowledge" / "wiki"
        (wiki / "concepts").mkdir(parents=True)
        (wiki / "index.md").write_text("# index\n", encoding="utf-8")
        (wiki / "concepts" / "real.md").write_text(
            "# real page\n", encoding="utf-8"
        )
        adir = wiki / ".audit" / "proposals" / "2026-05-17-x"
        adir.mkdir(parents=True)
        (adir / "proposal.md").write_text("# archived\n", encoding="utf-8")
        (wiki / ".audit" / "ingest-log.md").write_text(
            INGEST_LOG_MARKER + "\n\n", encoding="utf-8"
        )
        return wiki

    def test_wiki_state_skips_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wiki = self._wiki_with_audit(Path(td))
            pages = state_pages(wiki)
            self.assertFalse(
                any(".audit" in p.parts for p in pages),
                [str(p) for p in pages],
            )

    def test_health_lint_skips_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wiki = self._wiki_with_audit(Path(td))
            pages = health_pages(wiki)
            self.assertFalse(
                any(".audit" in p.parts for p in pages),
                [str(p) for p in pages],
            )


if __name__ == "__main__":
    unittest.main()
