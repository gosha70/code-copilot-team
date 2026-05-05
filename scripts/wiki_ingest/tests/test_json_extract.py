# tests/test_json_extract.py — focused tests for the JSON-extraction module.
#
# Covers the seven canonical cases from spec.md "JSON-extraction module" section,
# plus negative tests for failure paths.

import json
import unittest

from wiki_ingest.backends.json_extract import extract_json_object
from wiki_ingest.errors import ContractViolationError


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

_VALID_RESPONSE = {
    "version": 1,
    "disposition": "accept",
    "reason": "Passes gate.",
    "page_type": "incident",
    "slug": "test-slug",
    "title": "Test Slug",
    "draft_markdown": "---\npage_type: incident\n---\n\n# Test\n",
    "sources": [{"path": "foo.md", "sha": "abc"}],
}

_VALID_JSON = json.dumps(_VALID_RESPONSE)


# ---------------------------------------------------------------------------
# Case 1: Bare JSON object as entire stdout
# ---------------------------------------------------------------------------

class TestBareJsonObject(unittest.TestCase):
    def test_bare_json_object(self) -> None:
        """Case 1: stdout is a bare JSON object with no surrounding text."""
        result = extract_json_object(_VALID_JSON)
        self.assertEqual(result["disposition"], "accept")
        self.assertEqual(result["slug"], "test-slug")

    def test_bare_json_with_leading_newline(self) -> None:
        """Bare JSON with a leading newline is still extracted."""
        result = extract_json_object("\n" + _VALID_JSON)
        self.assertEqual(result["version"], 1)

    def test_bare_json_with_trailing_newline(self) -> None:
        """Bare JSON with a trailing newline is still extracted."""
        result = extract_json_object(_VALID_JSON + "\n")
        self.assertEqual(result["disposition"], "accept")


# ---------------------------------------------------------------------------
# Case 2: JSON inside ```json … ``` fence
# ---------------------------------------------------------------------------

class TestFencedJsonBlock(unittest.TestCase):
    def test_json_in_json_fence(self) -> None:
        """Case 2: JSON wrapped in a ```json … ``` fenced code block."""
        stdout = f"```json\n{_VALID_JSON}\n```"
        result = extract_json_object(stdout)
        self.assertEqual(result["slug"], "test-slug")

    def test_json_fence_with_surrounding_prose(self) -> None:
        """JSON inside ```json fence with prose before and after."""
        stdout = (
            "Here is the response:\n"
            f"```json\n{_VALID_JSON}\n```\n"
            "I hope that helps."
        )
        result = extract_json_object(stdout)
        self.assertEqual(result["disposition"], "accept")

    def test_json_fence_preferred_over_balanced_brace(self) -> None:
        """Fenced block is tried first; prose brace noise does not interfere."""
        # Embed a stray JSON-like fragment outside the fence
        stdout = (
            "Some context {not json} here.\n"
            f"```json\n{_VALID_JSON}\n```\n"
        )
        result = extract_json_object(stdout)
        self.assertEqual(result["version"], 1)


# ---------------------------------------------------------------------------
# Case 3: JSON inside ``` … ``` fence (no language tag)
# ---------------------------------------------------------------------------

class TestFencedNoLanguageBlock(unittest.TestCase):
    def test_json_in_plain_fence(self) -> None:
        """Case 3: JSON wrapped in a ``` (no language tag) fenced block."""
        stdout = f"```\n{_VALID_JSON}\n```"
        result = extract_json_object(stdout)
        self.assertEqual(result["slug"], "test-slug")

    def test_plain_fence_with_preamble(self) -> None:
        """Plain fence with preamble prose."""
        stdout = f"Response:\n```\n{_VALID_JSON}\n```"
        result = extract_json_object(stdout)
        self.assertEqual(result["disposition"], "accept")


# ---------------------------------------------------------------------------
# Case 4: JSON after a prose preamble
# ---------------------------------------------------------------------------

class TestJsonAfterProsePreamble(unittest.TestCase):
    def test_json_after_preamble(self) -> None:
        """Case 4: JSON appears after an explanatory prose preamble."""
        stdout = f"Here's my analysis:\n\n{_VALID_JSON}"
        result = extract_json_object(stdout)
        self.assertEqual(result["version"], 1)

    def test_json_after_multiline_preamble(self) -> None:
        """Multi-sentence preamble before the JSON object."""
        stdout = (
            "I reviewed the source file.\n"
            "It appears to be an incident description.\n"
            "Here is the structured response:\n"
            + _VALID_JSON
        )
        result = extract_json_object(stdout)
        self.assertEqual(result["slug"], "test-slug")


# ---------------------------------------------------------------------------
# Case 5: JSON before a prose afterword
# ---------------------------------------------------------------------------

class TestJsonBeforeProsAfterword(unittest.TestCase):
    def test_json_before_afterword(self) -> None:
        """Case 5: JSON appears before a trailing prose afterword."""
        stdout = f"{_VALID_JSON} I hope this is helpful."
        result = extract_json_object(stdout)
        self.assertEqual(result["disposition"], "accept")

    def test_json_before_multiline_afterword(self) -> None:
        """JSON followed by multiple lines of prose."""
        stdout = (
            _VALID_JSON
            + "\n\nPlease let me know if you need any changes.\n"
            + "Happy to revise the draft."
        )
        result = extract_json_object(stdout)
        self.assertEqual(result["version"], 1)


# ---------------------------------------------------------------------------
# Case 6: Multiple JSON-looking blocks — extractor returns the first one
# ---------------------------------------------------------------------------

class TestMultipleJsonBlocks(unittest.TestCase):
    def test_fenced_block_first_returns_first_fence(self) -> None:
        """Case 6: When multiple fenced blocks are present, the first parseable one wins.

        The fenced-block-first strategy means the extractor picks the first
        ```json fence that parses to a dict. This is intentional — if the CLI
        echoes back the prompt in a fence followed by the response in another
        fence, the prompt-echo fence will be returned. Document this behaviour
        so callers can craft prompts that avoid echoing the BackendPrompt in a
        ```json fence.
        """
        first_object = {"version": 1, "tag": "first"}
        second_object = {"version": 1, "tag": "second"}
        stdout = (
            f"```json\n{json.dumps(first_object)}\n```\n"
            f"```json\n{json.dumps(second_object)}\n```\n"
        )
        result = extract_json_object(stdout)
        self.assertEqual(result["tag"], "first")

    def test_multiple_prose_objects_returns_first(self) -> None:
        """Multiple bare JSON blocks in prose — balanced-brace scan picks the first."""
        first = {"version": 1, "tag": "first"}
        second = {"version": 1, "tag": "second"}
        stdout = (
            "First response: "
            + json.dumps(first)
            + " second response: "
            + json.dumps(second)
        )
        result = extract_json_object(stdout)
        self.assertEqual(result["tag"], "first")

    def test_prompt_echoed_back_then_response(self) -> None:
        """Prompt echoed in a ``` fence (no json tag), then real response in a ```json fence.

        The ```json fence wins over the plain ``` fence because the extractor
        tries ```json first.
        """
        prompt_echo = {"kind": "prompt-echo", "data": "some prompt content"}
        real_response = {"version": 1, "tag": "real-response"}
        stdout = (
            f"```\n{json.dumps(prompt_echo)}\n```\n"
            f"```json\n{json.dumps(real_response)}\n```\n"
        )
        result = extract_json_object(stdout)
        # ```json pattern is tried first, so we get the real response
        self.assertEqual(result["tag"], "real-response")


# ---------------------------------------------------------------------------
# Case 7: Nested objects in prose followed by the actual response object
# ---------------------------------------------------------------------------

class TestNestedObjectsInProse(unittest.TestCase):
    def test_nested_object_in_explanation_then_response(self) -> None:
        """Case 7: Prose explanation contains nested JSON-like fragments; actual response follows.

        The balanced-brace scanner finds the FIRST balanced top-level block.
        If the explanation fragment is a valid JSON dict, it will be returned
        before the real response. To avoid this, wrap the real response in a
        ```json fence (which is tried first).
        """
        # Use a ```json fence for the real response to ensure it wins.
        explanation_fragment = '{"nested": {"key": "value"}}'
        real_response_json = json.dumps(_VALID_RESPONSE)
        stdout = (
            f"The schema requires {explanation_fragment} as a sub-field.\n"
            f"Here is the full response:\n"
            f"```json\n{real_response_json}\n```\n"
        )
        result = extract_json_object(stdout)
        self.assertEqual(result["slug"], "test-slug")

    def test_nested_objects_balanced_brace_scan(self) -> None:
        """Without fences, nested objects in prose are scanned correctly.

        The balanced-brace scanner correctly handles nested braces. The first
        fully-balanced top-level block is returned.
        """
        # First balanced block in stdout is a simple dict
        first = {"found": "yes", "nested": {"inner": "value"}}
        stdout = "Some explanation: " + json.dumps(first) + " more text."
        result = extract_json_object(stdout)
        self.assertEqual(result["found"], "yes")
        self.assertEqual(result["nested"]["inner"], "value")


# ---------------------------------------------------------------------------
# Negative: no JSON found at all
# ---------------------------------------------------------------------------

class TestNoJsonFound(unittest.TestCase):
    def test_no_json_raises(self) -> None:
        """Empty or plain-text stdout raises ContractViolationError."""
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object("No JSON here at all.")
        self.assertIn("no JSON object", str(ctx.exception))

    def test_empty_string_raises(self) -> None:
        """Empty stdout raises ContractViolationError."""
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object("")
        self.assertIn("no JSON object", str(ctx.exception))

    def test_only_prose_raises(self) -> None:
        """Stdout with only prose text raises ContractViolationError."""
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object("I processed the file but cannot produce a response.")
        self.assertIn("no JSON object", str(ctx.exception))

    def test_error_message_includes_stdout_snippet(self) -> None:
        """Error message includes the first 500 chars of stdout for debugging."""
        text = "abcde " * 50  # 300 chars
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object(text)
        # The truncated snippet should appear in the message
        self.assertIn("abcde", str(ctx.exception))


# ---------------------------------------------------------------------------
# Negative: malformed JSON (looks parseable but is not)
# ---------------------------------------------------------------------------

class TestMalformedJson(unittest.TestCase):
    def test_unclosed_string_in_fence_raises(self) -> None:
        """JSON with unclosed string in a ```json fence raises ContractViolationError."""
        malformed = '{"version": 1, "bad_key": "unclosed string}'
        stdout = f"```json\n{malformed}\n```"
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object(stdout)
        self.assertIn("no JSON object", str(ctx.exception))

    def test_unclosed_brace_raises(self) -> None:
        """JSON with unclosed brace (not balanced) raises ContractViolationError."""
        malformed = '{"version": 1, "key": "value"'
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object(malformed)
        self.assertIn("no JSON object", str(ctx.exception))

    def test_malformed_inside_plain_fence_falls_through(self) -> None:
        """Malformed JSON in a ``` fence causes fallback to balanced-brace scan.

        If both strategies fail, ContractViolationError is raised.
        """
        malformed = '{"key": bad-value}'
        stdout = f"```\n{malformed}\n```"
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object(stdout)
        self.assertIn("no JSON object", str(ctx.exception))


# ---------------------------------------------------------------------------
# Negative: extracted text parses to a non-dict
# ---------------------------------------------------------------------------

class TestNonDictJson(unittest.TestCase):
    def test_json_array_in_fence_falls_through(self) -> None:
        """A JSON array in a ```json fence is not a dict; falls through to balanced-brace scan."""
        array_json = "[1, 2, 3]"
        stdout = f"```json\n{array_json}\n```"
        # No dict found anywhere
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object(stdout)
        self.assertIn("no JSON object", str(ctx.exception))

    def test_json_string_in_fence_falls_through(self) -> None:
        """A JSON string in a ```json fence is not a dict; raises ContractViolationError."""
        stdout = '```json\n"just a string"\n```'
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object(stdout)
        self.assertIn("no JSON object", str(ctx.exception))

    def test_json_number_in_fence_falls_through(self) -> None:
        """A bare JSON number is not a dict; raises ContractViolationError."""
        stdout = "```json\n42\n```"
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object(stdout)
        self.assertIn("no JSON object", str(ctx.exception))

    def test_json_null_in_fence_falls_through(self) -> None:
        """A JSON null is not a dict; raises ContractViolationError."""
        stdout = "```json\nnull\n```"
        with self.assertRaises(ContractViolationError) as ctx:
            extract_json_object(stdout)
        self.assertIn("no JSON object", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
