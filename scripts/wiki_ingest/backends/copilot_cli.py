# wiki_ingest.backends.copilot_cli — subprocess backend for copilot CLIs.
#
# Invokes a copilot CLI (claude, codex, cursor) as a subprocess, renders the
# BackendPrompt as a plain-text prompt, and uses json_extract to pull the JSON
# response from free-form CLI output.
#
# Adapter mappings (verified against vendor docs as of 2026-05; fix any that
# drift in a separate change with a pinning test):
#   claude  → ``claude -p "<prompt>"``     (Anthropic Claude Code CLI)
#   codex   → ``codex exec "<prompt>"``    (OpenAI Codex CLI; non-interactive)
#   cursor  → ``cursor-agent -p "<prompt>"`` (Cursor agent CLI)
#
# The user-facing backend name (cursor) is decoupled from the on-disk binary
# (cursor-agent) so callers can keep saying ``--backend cursor`` even after
# the cursor team renamed the headless binary.
#
# Privacy: by default, error messages do NOT include raw stderr from the
# backend (it can echo source content or model output). They include a
# redacted summary (byte count + sha256 hex prefix). Pass redact_output=False
# to recover the unredacted form (only for local debugging).

from __future__ import annotations

import hashlib
import subprocess
from typing import Any

from ..errors import BackendInvocationError, BackendNotFoundError
from .json_extract import extract_json_object

# Maximum stderr bytes to fingerprint when redacting.
_MAX_STDERR_BYTES = 2048

# User-facing backend name → on-disk binary name. Names not in this map fall
# back to using the user-facing name as the binary (used by stub-backend.sh
# in tests, and by contributor CLIs that don't need remapping).
CLI_BINARY_MAP: dict[str, str] = {
    "claude": "claude",
    "codex": "codex",
    "cursor": "cursor-agent",
}

# User-facing backend name → invocation args inserted between the binary and
# the prompt text. Defaults to ``["-p"]`` for any unmapped name.
_CLI_INVOCATION_MAP: dict[str, list[str]] = {
    "claude": ["-p"],
    "codex": ["exec"],
    "cursor": ["-p"],
}


def cli_binary_for(name: str) -> str:
    """Return the on-disk binary name for a user-facing backend name."""
    return CLI_BINARY_MAP.get(name, name)


def _redact_stderr(stderr: str) -> str:
    """Return a privacy-safe fingerprint of stderr instead of the raw bytes.

    The fingerprint includes the byte count and a sha256 hex prefix so two
    identical errors yield identical fingerprints (useful for log dedup),
    without leaking source content the backend may have echoed back.
    """
    if not stderr:
        return "<no stderr>"
    encoded = stderr.encode("utf-8", errors="replace")
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"<redacted: {len(encoded)} bytes, sha256={digest}; rerun with --debug-unsafe-output to see raw text>"


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
    - When ``backend_prompt["task"] == "gate-only"``, instructs the
      backend to skip drafting the body (resolution-A real --dry-run).

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
    wiki_state = backend_prompt.get("wiki_state", {})
    response_schema = backend_prompt.get("response_schema", "")
    task = backend_prompt.get("task", "ingest")

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

    # Phase-1 multi-page ingest: render the existing wiki state so the
    # backend can integrate with it. compose_multi_prompt populates this
    # block; compose_prompt (Stage-1 single-source) does not, so the
    # block is omitted unless wiki_state has any non-empty content. A
    # bug fix landed here after a reviewer caught that the multi-page
    # prompt dict carried wiki_state but the renderer dropped it on the
    # floor — Phase 1 was wiki-aware in test backends only until this
    # block was added.
    if wiki_state and (
        wiki_state.get("index_md")
        or wiki_state.get("log_md")
        or wiki_state.get("candidate_pages")
    ):
        lines.append("=== EXISTING WIKI STATE ===")
        lines.append(
            "The following is the current wiki state, loaded as your "
            "working memory. Integrate the new source with what is "
            "already here: prefer updating an existing page over "
            "creating a duplicate; append a one-line dated entry to "
            "log.md; add a link from the appropriate section of "
            "index.md whenever you create a new page."
        )
        lines.append("")
        index_md = wiki_state.get("index_md", "")
        if index_md:
            lines.append("--- knowledge/wiki/index.md ---")
            lines.append(index_md)
            lines.append("")
        log_md = wiki_state.get("log_md", "")
        if log_md:
            lines.append("--- knowledge/wiki/log.md ---")
            lines.append(log_md)
            lines.append("")
        candidate_pages = wiki_state.get("candidate_pages", {}) or {}
        if candidate_pages:
            lines.append(
                "--- candidate pages (relevance-ranked subset of the wiki, "
                "selected by lexical overlap with the source) ---"
            )
            for rel_path, page_content in candidate_pages.items():
                lines.append(f"--- knowledge/wiki/{rel_path} ---")
                lines.append(page_content)
                lines.append("")
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
    if task == "gate-only":
        lines.append("")
        lines.append(
            "GATE-ONLY MODE: do not draft the page body. Apply the "
            "four-question gate and return disposition + reason ONLY. "
            "Set draft_markdown to null on accept; the curator will "
            "rerun without --dry-run to obtain the body if the gate "
            "passes. This saves model tokens and latency."
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
        The user-facing backend name (``claude``, ``codex``, ``cursor``)
        OR an explicit binary path (e.g., a stub script in tests). When
        the name matches an entry in :data:`CLI_BINARY_MAP`, the on-disk
        binary and invocation args are looked up there; otherwise the
        name is used verbatim with ``-p`` as the only invocation arg.
    timeout_seconds : int
        Subprocess timeout in seconds. Default 120. Test suite can lower this.
    redact_output : bool
        When True (default), error messages substitute a hashed
        fingerprint for raw stderr — the backend may echo source content
        and the raw text is unsafe to log. When False, raw stderr is
        included (for local debugging via ``--debug-unsafe-output``).
    """

    def __init__(
        self,
        cli_name: str,
        timeout_seconds: int = 120,
        redact_output: bool = True,
    ) -> None:
        self._cli_name = cli_name
        self._timeout_seconds = timeout_seconds
        self._redact_output = redact_output

    def _build_command(self, prompt_text: str) -> list[str]:
        """Construct argv for the subprocess: [binary, *invocation, prompt]."""
        binary = cli_binary_for(self._cli_name)
        invocation = _CLI_INVOCATION_MAP.get(self._cli_name, ["-p"])
        return [binary, *invocation, prompt_text]

    def _format_stderr(self, stderr: str | bytes | None) -> str:
        """Return either a redacted fingerprint or a truncated raw snippet."""
        if stderr is None:
            return "<no stderr>"
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        if self._redact_output:
            return _redact_stderr(stderr[:_MAX_STDERR_BYTES * 4])
        return repr(stderr[:_MAX_STDERR_BYTES])

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
        cmd = self._build_command(prompt_text)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise BackendInvocationError(
                f"Backend '{self._cli_name}' timed out after {self._timeout_seconds}s. "
                f"stderr: {self._format_stderr(exc.stderr)}"
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
                f"Backend CLI '{cli_binary_for(self._cli_name)}' not found on PATH. "
                "Use --backend test for fixture runs, or install the CLI."
            ) from exc

        if result.returncode != 0:
            raise BackendInvocationError(
                f"Backend '{self._cli_name}' exited with code {result.returncode}. "
                f"stderr: {self._format_stderr(result.stderr)}"
            )

        # extract_json_object raises ContractViolationError if no JSON found.
        return extract_json_object(result.stdout)
