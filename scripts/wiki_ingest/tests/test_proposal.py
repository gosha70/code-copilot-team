# tests/test_proposal.py — unit tests for IngestRequest, IngestProposal, render_proposal_file.

import unittest
from pathlib import Path

from wiki_ingest.proposal import IngestProposal, IngestRequest, render_proposal_file


class TestIngestRequest(unittest.TestCase):
    def test_frozen(self) -> None:
        req = IngestRequest(
            source_path=Path("some/file.md"),
            source_kind="file",
            backend_name="test",
        )
        with self.assertRaises(Exception):
            req.source_path = Path("other.md")  # type: ignore[misc]

    def test_fields(self) -> None:
        req = IngestRequest(
            source_path=Path("specs/foo/spec.md"),
            source_kind="file",
            backend_name="claude",
        )
        self.assertEqual(req.source_kind, "file")
        self.assertEqual(req.backend_name, "claude")


class TestIngestProposal(unittest.TestCase):
    def _make_accept(self) -> IngestProposal:
        return IngestProposal(
            disposition="accept",
            reason="Passes all four gate questions.",
            page_type="incident",
            slug="git-lock-bypass",
            title="Git Lock Bypass",
            draft_markdown="---\npage_type: incident\n---\n\n# Git Lock Bypass\n",
            sources=[{"path": "specs/foo/spec.md", "sha": "abc1234"}],
        )

    def _make_reject(self) -> IngestProposal:
        return IngestProposal(
            disposition="reject",
            reason="Content is session-specific; not reusable.",
            page_type=None,
            slug=None,
            title=None,
            draft_markdown=None,
            sources=[],
        )

    def test_accept_fields(self) -> None:
        p = self._make_accept()
        self.assertEqual(p.disposition, "accept")
        self.assertEqual(p.slug, "git-lock-bypass")
        self.assertIsNotNone(p.draft_markdown)

    def test_reject_fields(self) -> None:
        p = self._make_reject()
        self.assertEqual(p.disposition, "reject")
        self.assertIsNone(p.page_type)
        self.assertEqual(p.sources, [])

    def test_frozen(self) -> None:
        p = self._make_accept()
        with self.assertRaises(Exception):
            p.slug = "other"  # type: ignore[misc]


class TestRenderProposalFile(unittest.TestCase):
    def _make_accept_proposal(self) -> IngestProposal:
        return IngestProposal(
            disposition="accept",
            reason="Passes gate.",
            page_type="incident",
            slug="git-lock-bypass",
            title="Git Lock Bypass",
            draft_markdown="---\npage_type: incident\n---\n\n# Body\n",
            sources=[{"path": "specs/foo/spec.md", "sha": "abc1234"}],
        )

    def _make_reject_proposal(self) -> IngestProposal:
        return IngestProposal(
            disposition="reject",
            reason="Not reusable beyond this session.",
            page_type=None,
            slug=None,
            title=None,
            draft_markdown=None,
            sources=[],
        )

    def _make_request(self) -> IngestRequest:
        return IngestRequest(
            source_path=Path("some/source.md"),
            source_kind="file",
            backend_name="test",
        )

    def test_accept_frontmatter_keys(self) -> None:
        rendered = render_proposal_file(
            self._make_accept_proposal(), self._make_request(), "test"
        )
        # Constrained-value fields are plain scalars; free-form fields are
        # single-quoted (see _yaml_single_quote in proposal.py).
        self.assertIn("proposal_kind: accept", rendered)
        self.assertIn("gate_disposition: accept", rendered)
        self.assertIn("target_slug: 'git-lock-bypass'", rendered)
        self.assertIn("target_page_type: 'incident'", rendered)
        self.assertIn("ingestor_version: 1", rendered)
        self.assertIn("backend: 'test'", rendered)
        self.assertIn("source_path:", rendered)

    def test_accept_body_contains_draft(self) -> None:
        rendered = render_proposal_file(
            self._make_accept_proposal(), self._make_request(), "test"
        )
        self.assertIn("# Body", rendered)

    def test_reject_frontmatter_keys(self) -> None:
        rendered = render_proposal_file(
            self._make_reject_proposal(), self._make_request(), "test"
        )
        self.assertIn("proposal_kind: reject", rendered)
        self.assertIn("gate_disposition: reject", rendered)
        # Empty target_slug / target_page_type render as the empty quoted
        # scalar ('').
        self.assertIn("target_slug: ''", rendered)
        self.assertIn("target_page_type: ''", rendered)

    def test_reject_body_contains_reason(self) -> None:
        rendered = render_proposal_file(
            self._make_reject_proposal(), self._make_request(), "test"
        )
        self.assertIn("Not reusable beyond this session.", rendered)

    def test_frontmatter_starts_with_triple_dash(self) -> None:
        rendered = render_proposal_file(
            self._make_accept_proposal(), self._make_request(), "test"
        )
        self.assertTrue(rendered.startswith("---\n"))

    def test_proposal_date_present(self) -> None:
        rendered = render_proposal_file(
            self._make_accept_proposal(), self._make_request(), "test"
        )
        self.assertIn("proposal_date:", rendered)

    def test_reject_reason_with_colon_round_trips(self) -> None:
        """A reject reason containing a colon must round-trip through YAML safely.

        Without quoting, `gate_reason: Q4 failed: not new-contributor relevant`
        is ambiguous YAML — the second colon could be parsed as a nested key.
        Single-quoted scalars treat the value verbatim.
        """
        from wiki_ingest.prompt import _parse_frontmatter

        proposal = IngestProposal(
            disposition="reject",
            reason="Q4 failed: not new-contributor relevant",
            page_type=None,
            slug=None,
            title=None,
            draft_markdown=None,
            sources=[],
        )
        rendered = render_proposal_file(proposal, self._make_request(), "test")
        # The literal quoted form must appear in the output.
        self.assertIn(
            "gate_reason: 'Q4 failed: not new-contributor relevant'",
            rendered,
        )
        # Round-trip through the same YAML parser the rest of the pipeline uses.
        fm = _parse_frontmatter(rendered)
        self.assertEqual(
            fm.get("gate_reason"),
            "Q4 failed: not new-contributor relevant",
        )

    def test_reason_with_single_quote_escapes_correctly(self) -> None:
        """A reason containing a single quote must double the quote per YAML spec."""
        from wiki_ingest.prompt import _parse_frontmatter

        proposal = IngestProposal(
            disposition="reject",
            reason="Couldn't pass Q3: it's a duplicate",
            page_type=None,
            slug=None,
            title=None,
            draft_markdown=None,
            sources=[],
        )
        rendered = render_proposal_file(proposal, self._make_request(), "test")
        # Single quotes are escaped by doubling.
        self.assertIn("Couldn''t pass Q3", rendered)
        # Round-trip through the YAML parser.
        fm = _parse_frontmatter(rendered)
        self.assertEqual(fm.get("gate_reason"), "Couldn't pass Q3: it's a duplicate")


if __name__ == "__main__":
    unittest.main()
