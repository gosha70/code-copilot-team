# tests/test_prompt.py — tests for schema loading, prompt composition, and response validation.

import json
import unittest
from pathlib import Path

from wiki_ingest.errors import ContractViolationError
from wiki_ingest.prompt import compose_prompt, load_schema_files, parse_response

# Locate the repo root relative to this test file:
# tests/ → wiki_ingest/ → scripts/ → repo root
_REPO_ROOT = Path(__file__).parent.parent.parent.parent


def _make_valid_accept_response(**overrides) -> dict:
    """Return a minimal valid accept BackendResponse dict."""
    sources = [{"path": "specs/foo/spec.md", "sha": "abc1234"}]
    slug = overrides.pop("slug", "git-lock-bypass")
    page_type = overrides.pop("page_type", "incident")
    title = overrides.pop("title", "Git Lock Bypass")
    sources = overrides.pop("sources", sources)
    fm_slug = overrides.pop("fm_slug", slug)
    fm_page_type = overrides.pop("fm_page_type", page_type)
    fm_title = overrides.pop("fm_title", title)
    fm_sources = overrides.pop("fm_sources", sources)

    fm_sources_yaml = "\n".join(
        f"  - path: {s['path']}\n    sha: {s['sha']}"
        for s in fm_sources
        if isinstance(s, dict) and "path" in s
    )
    draft = (
        f"---\n"
        f"page_type: {fm_page_type}\n"
        f"slug: {fm_slug}\n"
        f"title: {fm_title}\n"
        f"status: draft\n"
        f"last_reviewed: 2026-05-04\n"
        f"sources:\n"
        f"{fm_sources_yaml}\n"
        f"---\n\n# {fm_title}\n"
    )
    base = {
        "version": 1,
        "disposition": "accept",
        "reason": "Passes gate.",
        "page_type": page_type,
        "slug": slug,
        "title": title,
        "draft_markdown": draft,
        "sources": sources,
    }
    base.update(overrides)
    return base


def _make_valid_reject_response(**overrides) -> dict:
    """Return a minimal valid reject BackendResponse dict."""
    base = {
        "version": 1,
        "disposition": "reject",
        "reason": "Not reusable.",
        "page_type": None,
        "slug": None,
        "title": None,
        "draft_markdown": None,
        "sources": [],
    }
    base.update(overrides)
    return base


class TestSchemaFileLoading(unittest.TestCase):
    def test_loads_all_three_schema_files(self) -> None:
        schemas = load_schema_files(_REPO_ROOT)
        self.assertIn("ingest-rules", schemas)
        self.assertIn("page-types", schemas)
        self.assertIn("citation-rules", schemas)

    def test_schema_files_non_empty(self) -> None:
        schemas = load_schema_files(_REPO_ROOT)
        for name, content in schemas.items():
            self.assertGreater(len(content), 100, f"{name} schema is suspiciously short")

    def test_ingest_rules_contains_four_question_gate(self) -> None:
        schemas = load_schema_files(_REPO_ROOT)
        self.assertIn("four-question gate", schemas["ingest-rules"])

    def test_page_types_contains_incident(self) -> None:
        schemas = load_schema_files(_REPO_ROOT)
        self.assertIn("incident", schemas["page-types"])

    def test_citation_rules_contains_sources(self) -> None:
        schemas = load_schema_files(_REPO_ROOT)
        self.assertIn("sources", schemas["citation-rules"])


class TestBackendPromptComposition(unittest.TestCase):
    def setUp(self) -> None:
        self.schemas = load_schema_files(_REPO_ROOT)
        self.source_path = Path("some/file.md")
        self.source_content = "# Hello World\n\nSome content."

    def test_prompt_has_required_keys(self) -> None:
        prompt = compose_prompt(self.source_path, self.source_content, self.schemas)
        for key in ("version", "system_instructions", "task", "schema_excerpts",
                    "source", "response_schema"):
            self.assertIn(key, prompt)

    def test_prompt_version_is_1(self) -> None:
        prompt = compose_prompt(self.source_path, self.source_content, self.schemas)
        self.assertEqual(prompt["version"], 1)

    def test_prompt_task_is_ingest(self) -> None:
        prompt = compose_prompt(self.source_path, self.source_content, self.schemas)
        self.assertEqual(prompt["task"], "ingest")

    def test_prompt_source_content_included(self) -> None:
        prompt = compose_prompt(self.source_path, self.source_content, self.schemas)
        self.assertEqual(prompt["source"]["content"], self.source_content)

    def test_prompt_source_path_included(self) -> None:
        prompt = compose_prompt(self.source_path, self.source_content, self.schemas)
        self.assertEqual(prompt["source"]["path"], str(self.source_path))

    def test_prompt_schema_excerpts_populated(self) -> None:
        prompt = compose_prompt(self.source_path, self.source_content, self.schemas)
        excerpts = prompt["schema_excerpts"]
        self.assertTrue(excerpts["ingest_rules"])
        self.assertTrue(excerpts["page_types"])
        self.assertTrue(excerpts["citation_rules"])

    def test_prompt_response_schema_is_json_string(self) -> None:
        prompt = compose_prompt(self.source_path, self.source_content, self.schemas)
        # Must be parseable JSON
        parsed = json.loads(prompt["response_schema"])
        self.assertIn("type", parsed)


# ---------------------------------------------------------------------------
# Shape validation — negative tests
# ---------------------------------------------------------------------------

class TestShapeValidationNegative(unittest.TestCase):
    def test_malformed_json_raises(self) -> None:
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response("not json at all {")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_json_array_raises(self) -> None:
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps([1, 2, 3]))
        self.assertIn("JSON object", str(ctx.exception))

    def test_missing_required_key_raises(self) -> None:
        data = _make_valid_accept_response()
        del data["disposition"]
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        self.assertIn("disposition", str(ctx.exception))

    def test_wrong_version_raises(self) -> None:
        data = _make_valid_accept_response()
        data["version"] = 99
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        self.assertIn("version", str(ctx.exception))

    def test_unknown_disposition_raises(self) -> None:
        data = _make_valid_accept_response()
        data["disposition"] = "maybe"
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        self.assertIn("disposition", str(ctx.exception))

    def test_reason_wrong_type_raises(self) -> None:
        data = _make_valid_accept_response()
        data["reason"] = 42
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        self.assertIn("reason", str(ctx.exception))

    def test_sources_wrong_type_raises(self) -> None:
        data = _make_valid_accept_response()
        data["sources"] = "not-a-list"
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        self.assertIn("sources", str(ctx.exception))

    def test_valid_accept_passes(self) -> None:
        data = _make_valid_accept_response()
        result = parse_response(json.dumps(data))
        self.assertEqual(result["disposition"], "accept")

    def test_valid_reject_passes(self) -> None:
        data = _make_valid_reject_response()
        result = parse_response(json.dumps(data))
        self.assertEqual(result["disposition"], "reject")


# ---------------------------------------------------------------------------
# Semantic validation — one negative test per rule
# ---------------------------------------------------------------------------

class TestSemanticValidationNegative(unittest.TestCase):
    def test_page_type_mismatch(self) -> None:
        """Frontmatter page_type differs from structured page_type."""
        data = _make_valid_accept_response(fm_page_type="concept")
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("page_type", msg)
        self.assertIn("concept", msg)
        self.assertIn("incident", msg)

    def test_slug_mismatch(self) -> None:
        """Frontmatter slug differs from structured slug."""
        data = _make_valid_accept_response(fm_slug="different-slug")
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("slug", msg)
        self.assertIn("different-slug", msg)

    def test_title_mismatch(self) -> None:
        """Frontmatter title differs from structured title."""
        data = _make_valid_accept_response(fm_title="Different Title")
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("title", msg)
        self.assertIn("Different Title", msg)

    def test_sources_set_inequality(self) -> None:
        """Frontmatter sources do not match structured sources."""
        extra_sources = [{"path": "other/file.md", "sha": "deadbeef"}]
        data = _make_valid_accept_response(fm_sources=extra_sources)
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("sources", msg)
        self.assertIn("set inequality", msg)

    def test_non_kebab_case_slug(self) -> None:
        """Structured slug contains uppercase letters (not kebab-case)."""
        data = _make_valid_accept_response(slug="GitLockBypass", fm_slug="GitLockBypass")
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("kebab-case", msg)

    def test_placement_violation_glossary_slug_wrong_type(self) -> None:
        """Slug 'glossary' with page_type 'concept' violates placement rule."""
        sources = [{"path": "specs/foo/spec.md", "sha": "abc1234"}]
        data = _make_valid_accept_response(
            slug="glossary",
            page_type="concept",
            fm_slug="glossary",
            fm_page_type="concept",
            sources=sources,
            fm_sources=sources,
        )
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("glossary", msg)
        self.assertIn("directory-placement", msg)

    def test_root_only_page_type_index_rejected(self) -> None:
        """page_type 'index' is root-only and cannot be a proposal target."""
        sources = [{"path": "specs/foo/spec.md", "sha": "abc1234"}]
        data = _make_valid_accept_response(
            slug="my-index",
            page_type="index",
            fm_slug="my-index",
            fm_page_type="index",
            sources=sources,
            fm_sources=sources,
        )
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("index", msg)
        self.assertIn("promotable", msg.lower())

    def test_root_only_page_type_overview_rejected(self) -> None:
        """page_type 'overview' is root-only and cannot be a proposal target."""
        sources = [{"path": "specs/foo/spec.md", "sha": "abc1234"}]
        data = _make_valid_accept_response(
            slug="my-overview",
            page_type="overview",
            fm_slug="my-overview",
            fm_page_type="overview",
            sources=sources,
            fm_sources=sources,
        )
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("overview", msg)
        self.assertIn("promotable", msg.lower())

    def test_root_only_page_type_log_rejected(self) -> None:
        """page_type 'log' is root-only and cannot be a proposal target."""
        sources = [{"path": "specs/foo/spec.md", "sha": "abc1234"}]
        data = _make_valid_accept_response(
            slug="my-log",
            page_type="log",
            fm_slug="my-log",
            fm_page_type="log",
            sources=sources,
            fm_sources=sources,
        )
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("log", msg)
        self.assertIn("promotable", msg.lower())

    def test_empty_sources_on_accept(self) -> None:
        """Accept disposition with empty sources list raises."""
        # Build draft_markdown with empty sources block to match
        slug = "git-lock-bypass"
        page_type = "incident"
        title = "Git Lock Bypass"
        draft = (
            f"---\n"
            f"page_type: {page_type}\n"
            f"slug: {slug}\n"
            f"title: {title}\n"
            f"status: draft\n"
            f"last_reviewed: 2026-05-04\n"
            f"sources:\n"
            f"---\n\n# {title}\n"
        )
        data = {
            "version": 1,
            "disposition": "accept",
            "reason": "Passes.",
            "page_type": page_type,
            "slug": slug,
            "title": title,
            "draft_markdown": draft,
            "sources": [],
        }
        with self.assertRaises(ContractViolationError) as ctx:
            parse_response(json.dumps(data))
        msg = str(ctx.exception)
        self.assertIn("sources", msg)
        self.assertIn("non-empty", msg)


if __name__ == "__main__":
    unittest.main()
