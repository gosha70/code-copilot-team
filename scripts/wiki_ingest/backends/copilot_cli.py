# wiki_ingest.backends.copilot_cli — subprocess backend for copilot CLIs.
#
# Invokes a copilot CLI (claude, codex, cursor) as a subprocess, renders the
# BackendPrompt as a plain-text prompt, and uses json_extract to pull the JSON
# response from free-form CLI output.
#
# CLI flag conventions (best-effort v1; may need refinement after real dogfooding):
#   claude:  claude -p "<prompt>"  — '-p' is the "print/non-interactive" flag
#   codex:   codex -p "<prompt>"   — same shape assumed; verify with real CLI
#   cursor:  cursor -p "<prompt>"  — same shape assumed; verify with real CLI
#
# NOTE: The flag shape for codex and cursor is v1 best-effort. Real-world CLI
# conventions may differ. This is the expected iteration risk per plan.md Phase 2
# stop point. When dogfooding surfaces a different flag shape, add a test case
# that pins the new shape before updating this module.

from __future__ import annotations

import subprocess
from typing import Any

from ..errors import BackendInvocationError, BackendNotFoundError
from .json_extract import extract_json_object

# Maximum stderr bytes to include in error messages.
_MAX_STDERR_BYTES = 2048


def _render_plain_text_prompt(backend_prompt: dict[str, Any]) -> str:
    """Render a BackendPrompt dict as a plain-text prompt suitable for CLI invocation.

    The rendered prompt:
    - Frames the task with system-instructions.
    - Includes schema excerpts in labelled sections.
    - Includes the source content.
    - Specifies the JSON response schema (in a ``text`` fence — never
      ``json`` — so an echo of the prompt does not collide with the
      extractor's preferred ``json`` fence).
    - Explicitly asks the CLI to wrap its JSON response in a ``json``
      fence and to use no other ``json`` fence in its output.

    **The ```json fence is reserved exclusively for the model's actual
    response.** Reference material (response schema, prompt-shape docs,
    etc.) MUST be emitted in a non-json fence — using ``json`` for
    reference text would let an echoing CLI's prompt-echo capture the
    schema before its real response, and the extractor (which prefers
    the first ```json block) would return the schema instead of the
    answer. See test_extracts_response_when_prompt_is_echoed_verbatim
    in test_json_extract.py for the regression that pins this rule.
    """
    system_instructions = backend_prompt.get("system_instructions", "")
    schema_excerpts = backend_prompt.get("schema_excerpts", {})
    source = backend_prompt.get("source", {})
    response_schema = backend_prompt.get("response_schema", "")

    lines: list[str] = []

    lines.append("=== SYSTEM INSTRUCTIONS ===")
    lines.append(system_instructions)
    lines.append("")

    lines.append("=== SCHEMA: INGEST RULES ===")
    lines.append(schema_excerpts.get("ingest_rules", ""))
    lines.append("")

    lines.append("=== SCHEMA: PAGE TYPES ===")
    lines.append(schema_excerpts.get("page_types", ""))
    lines.append("")

    lines.append("=== SCHEMA: CITATION RULES ===")
    lines.append(schema_excerpts.get("citation_rules", ""))
    lines.append("")

    lines.append("=== SOURCE CONTENT ===")
    lines.append(f"Path: {source.get('path', '')}")
    lines.append(f"Kind: {source.get('kind', 'file')}")
    lines.append("")
    lines.append(source.get("content", ""))
    lines.append("")

    lines.append("=== RESPONSE INSTRUCTIONS ===")
    lines.append(
        "Respond with exactly one JSON object matching the schema below. "
        "Wrap your JSON response in a ```json code fence so it can be "
        "extracted reliably. Do not use any other ```json fence in your "
        "output — that fence is reserved exclusively for your response. "
        "The reference schema below is shown in a ```text fence (which "
        "is not captured by the extractor)."
    )
    lines.append("")
    lines.append("Response schema (reference only — do NOT echo this "
                 "block back; emit your real response in a ```json fence):")
    lines.append("```text")
    lines.append(response_schema)
    lines.append("```")

    # No "FULL PROMPT REFERENCE" block: it would either need a ```json
    # fence (collision risk) or a ```text fence (redundant with the
    # labelled sections above). Drop entirely.

    return "\n".join(lines)


class CopilotCliBackend:
    """Subprocess backend that invokes a copilot CLI and extracts JSON from its output.

    Parameters
    ----------
    cli_name : str
        The CLI executable name (e.g. "claude", "codex", "cursor").
    timeout_seconds : int
        Subprocess timeout in seconds. Default 120. Test suite can lower this.
    """

    def __init__(self, cli_name: str, timeout_seconds: int = 120) -> None:
        self._cli_name = cli_name
        self._timeout_seconds = timeout_seconds

    def call(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """Invoke the CLI with the rendered prompt and return the parsed response dict.

        Raises
        ------
        BackendInvocationError
            If the CLI exits non-zero or times out.
        ContractViolationError
            If extract_json_object cannot find a parseable JSON object in stdout.
        """
        prompt_text = _render_plain_text_prompt(prompt)
        cmd = [self._cli_name, "-p", prompt_text]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stderr_snippet = ""
            if exc.stderr:
                raw = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace")
                stderr_snippet = raw[:_MAX_STDERR_BYTES]
            raise BackendInvocationError(
                f"Backend '{self._cli_name}' timed out after {self._timeout_seconds}s. "
                f"stderr (first {_MAX_STDERR_BYTES} bytes): {stderr_snippet!r}"
            ) from exc
        except FileNotFoundError as exc:
            # Missing CLI is a "not found" condition (exit 2), not an
            # "invocation" condition (exit 3). resolve_backend() preflights
            # with shutil.which so this branch is normally unreachable, but
            # keep the same error semantics as the resolver for any code
            # path that constructs CopilotCliBackend directly (e.g.,
            # contributor SDK adapters built against the same Backend
            # Protocol).
            raise BackendNotFoundError(
                f"Backend CLI '{self._cli_name}' not found on PATH. "
                "Use --backend test for fixture runs, or install the CLI."
            ) from exc

        if result.returncode != 0:
            stderr_snippet = result.stderr[:_MAX_STDERR_BYTES]
            raise BackendInvocationError(
                f"Backend '{self._cli_name}' exited with code {result.returncode}. "
                f"stderr (first {_MAX_STDERR_BYTES} bytes): {stderr_snippet!r}"
            )

        # extract_json_object raises ContractViolationError if no JSON found.
        return extract_json_object(result.stdout)
