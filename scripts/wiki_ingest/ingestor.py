# wiki_ingest.ingestor — WikiIngestor Protocol + DefaultIngestor implementation.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .errors import BackendInvocationError, SourceMissingError
from .prompt import compose_prompt, load_schema_files, parse_response
from .proposal import IngestProposal, IngestRequest


@runtime_checkable
class Backend(Protocol):
    """A backend callable that accepts a BackendPrompt dict and returns a BackendResponse dict."""

    def call(self, prompt: dict[str, Any]) -> dict[str, Any]: ...


@runtime_checkable
class WikiIngestor(Protocol):
    """Public protocol: takes an IngestRequest, returns an IngestProposal."""

    def ingest(self, request: IngestRequest) -> IngestProposal: ...


class DefaultIngestor:
    """Wires prompt composition → backend → response validation → IngestProposal construction."""

    def __init__(self, backend: Backend, repo_root: Path) -> None:
        self._backend = backend
        self._repo_root = repo_root

    def ingest(self, request: IngestRequest) -> IngestProposal:
        # 1. Read source
        source_path = Path(request.source_path)
        if not source_path.exists():
            raise SourceMissingError(
                f"Source file not found or unreadable: {source_path}"
            )
        try:
            source_content = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SourceMissingError(
                f"Cannot read source file {source_path}: {exc}"
            ) from exc

        # 2. Load schema files and compose prompt
        schema_files = load_schema_files(self._repo_root)
        prompt_dict = compose_prompt(
            source_path=source_path,
            source_content=source_content,
            schema_files=schema_files,
            source_kind=request.source_kind,
        )

        # 3. Invoke backend
        try:
            response_dict = self._backend.call(prompt_dict)
        except BackendInvocationError:
            raise
        except Exception as exc:
            raise BackendInvocationError(
                f"Backend {request.backend_name!r} raised an unexpected error: {exc}"
            ) from exc

        # 4. If the backend returned a raw string (subprocess backends may do this),
        #    parse it; otherwise validate the dict directly.
        if isinstance(response_dict, str):
            validated = parse_response(response_dict)
        else:
            # Re-serialise and re-parse to run full two-layer validation.
            validated = parse_response(json.dumps(response_dict))

        # 5. Build IngestProposal
        return IngestProposal(
            disposition=validated["disposition"],
            reason=validated["reason"],
            page_type=validated.get("page_type"),
            slug=validated.get("slug"),
            title=validated.get("title"),
            draft_markdown=validated.get("draft_markdown"),
            sources=validated.get("sources", []),
        )
