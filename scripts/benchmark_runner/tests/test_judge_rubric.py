# tests/test_judge_rubric.py — rubric loader tests.
#
# Exercises ``load_rubric`` against the real
# benchmarks/calibration/rubric-default-v1.md plus synthetic fixtures
# under tmpdir. Covers:
#   - the four v1 dimensions are extracted in the documented order;
#   - the prompt template can be ``.format()``'d with the five attempt
#     placeholders WITHOUT raising on the JSON-example block's literal
#     curly braces;
#   - the rendered output contains the per-dimension descriptions +
#     anchor sentences (the rubric_dimensions_block content);
#   - missing-section + malformed rubric files raise the documented
#     errors.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmark_runner.judge.rubric import (
    ATTEMPT_PLACEHOLDERS,
    DEFAULT_RUBRIC_DIR,
    RubricNotFoundError,
    RubricParseError,
    load_rubric,
)


_V1_DIMS = ("idiomaticity", "error_handling", "test_thoughtfulness", "security_hygiene")


class TestLoadRubricV1(unittest.TestCase):
    """Loads the canonical rubric-default-v1.md from disk."""

    def setUp(self) -> None:
        self.rubric = load_rubric("default-v1")

    def test_name(self) -> None:
        self.assertEqual(self.rubric.name, "default-v1")

    def test_dimensions_extracted_in_order(self) -> None:
        self.assertEqual(self.rubric.dimensions, _V1_DIMS)

    def test_template_formattable_without_raising(self) -> None:
        # THE central invariant: the loader must escape literal curly
        # braces in the JSON-example block so the judge can call
        # str.format() with only the five attempt placeholders.
        rendered = self.rubric.prompt_template.format(
            task_id="python/leap",
            benchmark_id="aider-polyglot",
            prompt="Implement leap.py",
            diff="diff --git a/leap.py ...\n",
            verify_output="1 passed\n",
        )
        # Substitutions made it through.
        self.assertIn("python/leap", rendered)
        self.assertIn("aider-polyglot", rendered)
        self.assertIn("Implement leap.py", rendered)
        self.assertIn("diff --git a/leap.py", rendered)
        self.assertIn("1 passed", rendered)

    def test_template_includes_dimension_descriptions(self) -> None:
        # rubric_dimensions_block content must be in the rendered prompt
        # so the judge LLM sees the anchor sentences.
        rendered = self.rubric.prompt_template.format(
            task_id="t", benchmark_id="b", prompt="p", diff="d", verify_output="v",
        )
        for dim in _V1_DIMS:
            # Each dimension's "### N. `<name>`" header is in the
            # rendered prompt.
            self.assertIn(f"`{dim}`", rendered)
        # 1-5 anchor sentences carry the pattern "**N — ".
        self.assertIn("**1 — ", rendered)
        self.assertIn("**5 — ", rendered)

    def test_template_preserves_literal_json_example(self) -> None:
        # The rubric's prompt template ends with a JSON example like
        # ``{"ratings": {"idiomaticity": {...}}}``. After loading +
        # formatting, those literal braces must still appear in the
        # rendered text (as ``{`` / ``}``, not ``{{`` / ``}}``).
        rendered = self.rubric.prompt_template.format(
            task_id="t", benchmark_id="b", prompt="p", diff="d", verify_output="v",
        )
        self.assertIn('"ratings"', rendered)
        # No leftover double-brace escaping in the rendered output.
        self.assertNotIn("{{", rendered)
        self.assertNotIn("}}", rendered)

    def test_attempt_placeholders_constant_matches_format_call(self) -> None:
        # ATTEMPT_PLACEHOLDERS is the documented set. Any addition or
        # rename has to update this test deliberately.
        self.assertEqual(
            set(ATTEMPT_PLACEHOLDERS),
            {"task_id", "benchmark_id", "prompt", "diff", "verify_output"},
        )


class TestLoadRubricErrors(unittest.TestCase):
    """Synthetic rubric files in a tmpdir cover the failure modes."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-rubric-test-")
        self.tmpdir = Path(self._tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_rubric(self, name: str, body: str) -> None:
        (self.tmpdir / f"rubric-{name}.md").write_text(body, encoding="utf-8")

    def test_missing_file_raises_not_found(self) -> None:
        with self.assertRaises(RubricNotFoundError):
            load_rubric("does-not-exist", rubric_dir=self.tmpdir)

    def test_missing_dimensions_section_raises_parse_error(self) -> None:
        self._write_rubric(
            "broken-1",
            "# Rubric\n\n## Prompt template\n\n```\nuse {task_id}\n```\n",
        )
        with self.assertRaisesRegex(RubricParseError, "Dimensions"):
            load_rubric("broken-1", rubric_dir=self.tmpdir)

    def test_dimensions_section_without_headers_raises(self) -> None:
        # Header present, but no '### N. `<dim>`' inside.
        self._write_rubric(
            "broken-2",
            "## Dimensions\n\nSome prose but no recognised headers.\n\n"
            "## Prompt template\n\n```\nuse {task_id}\n```\n",
        )
        with self.assertRaisesRegex(RubricParseError, "dimension headers"):
            load_rubric("broken-2", rubric_dir=self.tmpdir)

    def test_missing_prompt_template_section_raises(self) -> None:
        self._write_rubric(
            "broken-3",
            "## Dimensions\n\n### 1. `idiomaticity`\n\ndescription\n",
        )
        with self.assertRaisesRegex(RubricParseError, "Prompt template"):
            load_rubric("broken-3", rubric_dir=self.tmpdir)

    def test_prompt_template_without_code_block_raises(self) -> None:
        self._write_rubric(
            "broken-4",
            "## Dimensions\n\n### 1. `idiomaticity`\n\ndescription\n\n"
            "## Prompt template\n\nNo fenced block here, just prose.\n",
        )
        with self.assertRaisesRegex(RubricParseError, "code block"):
            load_rubric("broken-4", rubric_dir=self.tmpdir)


class TestSyntheticRubricRoundtrip(unittest.TestCase):
    """A minimal rubric written to tmpdir exercises the escape logic."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cct-rubric-test-")
        self.tmpdir = Path(self._tmp)
        body = (
            "# Mini rubric\n"
            "\n"
            "## Dimensions\n"
            "\n"
            "### 1. `style`\n"
            "Code style notes.\n"
            "\n"
            "### 2. `safety`\n"
            "Safety notes.\n"
            "\n"
            "## When a dimension does not apply\n"
            "\n"
            "Null is reserved for structural inapplicability.\n"
            "\n"
            "## Prompt template\n"
            "\n"
            "```\n"
            "Task: {task_id} ({benchmark_id})\n"
            "PROMPT: {prompt}\n"
            "DIFF: {diff}\n"
            "VERIFY: {verify_output}\n"
            "Dimensions:\n"
            "{rubric_dimensions_block}\n"
            "Output JSON:\n"
            '{\n'
            '  "ratings": {"style": {"rating": 1, "explanation": "..."}}\n'
            '}\n'
            "```\n"
        )
        (self.tmpdir / "rubric-mini.md").write_text(body, encoding="utf-8")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_two_dimensions_in_order(self) -> None:
        r = load_rubric("mini", rubric_dir=self.tmpdir)
        self.assertEqual(r.dimensions, ("style", "safety"))

    def test_format_produces_literal_json_example(self) -> None:
        r = load_rubric("mini", rubric_dir=self.tmpdir)
        rendered = r.prompt_template.format(
            task_id="t/x",
            benchmark_id="bench-1",
            prompt="do-the-thing",
            diff="diff text",
            verify_output="ok",
        )
        # Substitutions present.
        self.assertIn("t/x", rendered)
        self.assertIn("bench-1", rendered)
        self.assertIn("do-the-thing", rendered)
        # Literal JSON example survived as plain text with single braces.
        self.assertIn('"ratings"', rendered)
        self.assertIn('{\n  "ratings"', rendered)
        # The dimensions block content was inlined.
        self.assertIn("`style`", rendered)
        self.assertIn("`safety`", rendered)
        self.assertIn("Code style notes", rendered)
        # And the "When a dimension does not apply" prose, too.
        self.assertIn("structural inapplicability", rendered)

    def test_format_with_extra_curlies_in_substitutions_is_safe(self) -> None:
        # A diff containing literal `{`/`}` must survive str.format
        # — the loader's escaping is for the TEMPLATE, not the
        # substituted values. (Values pass through .format unchanged
        # because format doesn't interpret braces in arguments.)
        r = load_rubric("mini", rubric_dir=self.tmpdir)
        diff = 'sample = {"key": "value"}\n'
        rendered = r.prompt_template.format(
            task_id="t", benchmark_id="b", prompt="p",
            diff=diff,
            verify_output="v",
        )
        self.assertIn('{"key": "value"}', rendered)


class TestDefaultRubricDirIsRepoCalibration(unittest.TestCase):
    """The default rubric_dir points at benchmarks/calibration/."""

    def test_default_dir_exists(self) -> None:
        self.assertTrue(
            DEFAULT_RUBRIC_DIR.exists(),
            f"default rubric dir not found: {DEFAULT_RUBRIC_DIR}",
        )
        self.assertEqual(DEFAULT_RUBRIC_DIR.name, "calibration")
        self.assertEqual(DEFAULT_RUBRIC_DIR.parent.name, "benchmarks")


if __name__ == "__main__":
    unittest.main()
