# Tests for the Learn center registry + routes (#309, Studio Phase 3).

from __future__ import annotations

import importlib.util
import json
import unittest

from session_analytics.api import docs
from session_analytics.config import REPO_ROOT, load_map

_FASTAPI = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        docs.registry.cache_clear()
        self.idx = docs.index()
        self.slugs = {e["slug"] for s in self.idx["sections"] for e in s["entries"]}

    def test_every_explicit_path_exists(self) -> None:
        # A renamed doc must fail here, loudly, not vanish from the index.
        spec = load_map("learn-sections.json")
        for sec in spec["sections"]:
            for rel in sec.get("paths", []):
                with self.subTest(path=rel):
                    self.assertTrue((REPO_ROOT / rel).is_file(), rel)
        for intent in spec["intents"]:
            self.assertIn(intent["slug"], self.slugs, intent["id"])
        for key, target in spec["finding_links"].items():
            if key.startswith("_"):
                continue
            self.assertTrue(
                target.startswith("section:") or target in self.slugs, f"{key} → {target}"
            )
        for path in spec["titles"]:
            self.assertTrue((REPO_ROOT / path).is_file(), path)

    def test_sections_are_populated_and_denied_trees_absent(self) -> None:
        by_id = {s["id"]: s for s in self.idx["sections"]}
        self.assertGreaterEqual(len(by_id["claude-code"]["entries"]), 8)
        self.assertGreaterEqual(len(by_id["skills"]["entries"]), 20)
        self.assertGreaterEqual(len(by_id["agents"]["entries"]), 10)
        self.assertGreaterEqual(len(by_id["wiki"]["entries"]), 15)
        paths = [e["path"] for s in self.idx["sections"] for e in s["entries"]]
        for p in paths:
            self.assertFalse(p.startswith("claude_code/"), p)
            self.assertFalse(p.startswith("doc_internal/"), p)
            self.assertFalse(p.startswith("knowledge/wiki/schema/"), p)
            self.assertFalse(p.startswith("/"), f"absolute path in payload: {p}")

    def test_titles_come_from_the_right_source(self) -> None:
        by_path = {e["path"]: e for s in self.idx["sections"] for e in s["entries"]}
        # README link text wins for curated docs …
        self.assertEqual(by_path["adapters/claude-code/docs/hooks-guide.md"]["title"], "Hooks Guide")
        # … frontmatter for wiki/skills/agents …
        self.assertEqual(by_path["shared/skills/safety/SKILL.md"]["title"], "safety")
        self.assertTrue(by_path["shared/skills/safety/SKILL.md"]["description"])
        self.assertEqual(by_path["adapters/claude-code/.claude/agents/build.md"]["page_type"], "agent")
        # … the override for the README, whose first `# ` line is a shell comment.
        self.assertEqual(by_path["README.md"]["title"], "Code Copilot Team — README")
        # Generated files are flagged.
        self.assertTrue(by_path["docs/features.md"]["generated"])
        self.assertTrue(by_path["shared/capabilities/COMPATIBILITY.md"]["generated"])
        self.assertFalse(by_path["docs/developer-cookbook.md"]["generated"])

    def test_readme_html_heading_becomes_markdown_and_placeholders_survive(self) -> None:
        # The README's logo heading is raw HTML; the renderer prints raw
        # HTML as text ("<h1> <img src=…"). It is converted at the API.
        # Angle-bracket placeholders and fenced code are untouched — a
        # raw-HTML renderer would have eaten `<feature-id>`.
        body = docs.document(docs.slug_for("README.md"))["body"]
        self.assertNotIn("<h1", body)
        self.assertNotIn("<img", body)
        self.assertIn('![Code Copilot Team Logo](/docs/images/CCT_LOGO.png "width=250")', body)
        self.assertIn("\n# Code Copilot Team\n", body)
        sample = "see <feature-id> and <dgx-spark-ip>\n```\n<h1>kept</h1>\n```\na<br>b"
        out = docs.html_to_markdown(sample)
        self.assertIn("<feature-id> and <dgx-spark-ip>", out)
        self.assertIn("```\n<h1>kept</h1>\n```", out)
        self.assertTrue(out.endswith("a  \nb"))

    def test_document_by_slug_only(self) -> None:
        d = docs.document("adapters--claude-code--docs--hooks-guide")
        self.assertEqual(d["path"], "adapters/claude-code/docs/hooks-guide.md")
        self.assertIn("# Hooks Guide", d["body"])
        for bad in ("../.env", ".env", "README.md", "claude_code--docs--hooks-guide",
                    "adapters/claude-code/docs/hooks-guide.md"):
            with self.subTest(slug=bad):
                with self.assertRaises(docs.UnknownDocError):
                    docs.document(bad)

    def test_wiki_frontmatter_is_split_off(self) -> None:
        d = docs.document("knowledge--wiki--workflows--origin-alignment")
        self.assertEqual(d["frontmatter"].get("page_type"), "workflow")
        self.assertFalse(d["body"].startswith("---"))

    def test_images_by_bare_name_only(self) -> None:
        path, media = docs.image_file("CCT_LOGO.png")
        self.assertEqual(media, "image/png")
        self.assertEqual(path.parent, (REPO_ROOT / "docs" / "images").resolve())
        for bad in ("../.env", ".env", "x/y.png", "nope.png", "..", "logo.txt"):
            with self.subTest(name=bad):
                with self.assertRaises(docs.UnknownImageError):
                    docs.image_file(bad)


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class TestDocsRoutes(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        import tempfile
        dsn = "sqlite:///" + tempfile.mkdtemp() + "/t.db"
        self.client = TestClient(create_app(dsn), base_url="http://127.0.0.1:8765")

    def test_index_document_image_and_404s(self) -> None:
        r = self.client.get("/api/docs")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("sections", body)
        self.assertEqual(body["image_route"], "/api/docs/image/")
        self.assertNotIn("/Users/", json.dumps(body))
        r = self.client.get("/api/docs/adapters--claude-code--docs--hooks-guide")
        self.assertEqual(r.status_code, 200)
        self.assertIn("body", r.json())
        self.assertEqual(self.client.get("/api/docs/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/docs/..%2F.env").status_code, 404)
        r = self.client.get("/api/docs/image/CCT_LOGO.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/png")
        self.assertEqual(self.client.get("/api/docs/image/nope.png").status_code, 404)
        self.assertEqual(self.client.get("/api/docs/image/..%2F..%2F.env").status_code, 404)
