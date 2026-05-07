# wiki_ingest.ingestor_multi — Phase-1 multi-page ingest orchestrator.
#
# Stage 1's DefaultIngestor (in ingestor.py) reads ONE source and
# returns ONE IngestProposal. Phase 1's DefaultMultiIngestor reads ONE
# source PLUS the existing wiki state and returns a WikiPatchSet — a
# multi-page write plan that updates index.md, log.md, and the relevant
# existing/new pages.
#
# Pipeline:
#   1. Read source (raises SourceMissingError if missing).
#   2. Load WikiState (index.md + log.md + candidate pages).
#   3. compose_multi_prompt(source, wiki_state, schema files).
#   4. Backend invocation.
#   5. parse_patch_set_response (shape check).
#   6. Build WikiPatchSet.
#   7. validate_patch_set (set-level invariants).
#   8. Return WikiPatchSet — caller writes the proposals dir on disk.

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .errors import BackendInvocationError, ContractViolationError, SourceMissingError
from .ingestor import Backend
from .prompt import (
    compose_multi_prompt,
    load_schema_files,
    parse_patch_set_response,
)
from .proposal import (
    IngestRequest,
    PageEdit,
    WikiPatchSet,
    validate_page_edit_semantics,
    validate_patch_set,
)
from .wiki_state import load_wiki_state


@runtime_checkable
class MultiIngestor(Protocol):
    """Public protocol: takes an IngestRequest, returns a WikiPatchSet."""

    def ingest_multi(self, request: IngestRequest) -> WikiPatchSet: ...


class DefaultMultiIngestor:
    """Default multi-page ingestor: source + wiki state → WikiPatchSet."""

    def __init__(self, backend: Backend, repo_root: Path) -> None:
        self._backend = backend
        self._repo_root = repo_root

    def ingest_multi(self, request: IngestRequest) -> WikiPatchSet:
        # 1. Read source.
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

        # 2. Load wiki state. Empty state on a fresh repo is fine —
        #    the backend will treat missing pages as creates.
        wiki_state = load_wiki_state(
            repo_root=self._repo_root,
            source_path=source_path,
            source_content=source_content,
        )

        # 3. Compose prompt.
        schema_files = load_schema_files(self._repo_root)
        prompt_dict = compose_multi_prompt(
            source_path=source_path,
            source_content=source_content,
            schema_files=schema_files,
            wiki_state=wiki_state,
            source_kind=request.source_kind,
        )
        # WIKI_INGEST_TASK env override (parity with Stage-1 ingestor).
        # Multi-page gate-only is meaningful too: the backend can return
        # an empty edits list with rationale "gate rejected" without
        # drafting any pages.
        env_task = os.environ.get("WIKI_INGEST_TASK")
        if env_task:
            prompt_dict["task"] = env_task

        # 4. Backend.
        try:
            response = self._backend.call(prompt_dict)
        except BackendInvocationError:
            raise
        except Exception as exc:
            raise BackendInvocationError(
                f"Backend {request.backend_name!r} raised an unexpected error: {exc}"
            ) from exc

        # 5. Shape check.
        if isinstance(response, str):
            validated = parse_patch_set_response(response)
        else:
            validated = parse_patch_set_response(json.dumps(response))

        # 6. Build WikiPatchSet.
        edits: list[PageEdit] = []
        for raw_edit in validated["edits"]:
            if not isinstance(raw_edit, dict):
                raise ContractViolationError(
                    "WikiPatchSet.edits[*] must be objects, "
                    f"got {type(raw_edit).__name__}"
                )
            for required in ("path", "action", "new_content", "rationale"):
                if required not in raw_edit:
                    raise ContractViolationError(
                        f"WikiPatchSet.edits[*] missing required key: {required!r}"
                    )
            edits.append(
                PageEdit(
                    path=str(raw_edit["path"]),
                    action=raw_edit["action"],
                    new_content=str(raw_edit["new_content"]),
                    rationale=str(raw_edit["rationale"]),
                )
            )

        patch = WikiPatchSet(
            edits=edits,
            source_path=str(source_path),
            backend=request.backend_name,
            rationale=str(validated.get("rationale", "")),
        )

        # 7a. Per-edit semantic validation. Mirrors v1 two-layer
        #     validation at the per-edit grain so frontmatter mismatches,
        #     missing sources, root-only page types as create targets,
        #     and updates to non-existent pages all fail fast — before
        #     the curator sees a patch-set that would later fail the
        #     wiki linter at promote time.
        if patch.edits:
            per_edit_errors: list[str] = []
            for edit in patch.edits:
                per_edit_errors.extend(
                    validate_page_edit_semantics(edit, self._repo_root)
                )
            if per_edit_errors:
                raise ContractViolationError(
                    "WikiPatchSet failed per-edit semantic validation:\n  - "
                    + "\n  - ".join(per_edit_errors)
                )

        # 7b. Set-level validation.
        # Empty edits is OK (gate reject); only fail if non-empty edits
        # have invariant violations.
        if patch.edits:
            errors = validate_patch_set(patch)
            if errors:
                raise ContractViolationError(
                    "WikiPatchSet failed set-level validation:\n  - "
                    + "\n  - ".join(errors)
                )

        return patch


def write_patch_set_dir(
    patch: WikiPatchSet,
    output_dir: Path,
) -> Path:
    """Write a WikiPatchSet to disk under output_dir.

    Layout:
        <output_dir>/
            plan.json                    — full patch-set as JSON
            preview/<edit.path>.md       — one preview file per edit

    Returns the absolute path of <output_dir>.
    Raises OSError if the filesystem operations fail; the caller maps
    to OutputWriteError exit code 6.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_dir = output_dir / "preview"
    preview_dir.mkdir(exist_ok=True)

    plan = {
        "version": 1,
        "source_path": patch.source_path,
        "backend": patch.backend,
        "rationale": patch.rationale,
        "edits": [
            {
                "path": e.path,
                "action": e.action,
                "rationale": e.rationale,
                # new_content is stored in the preview file; the plan.json
                # stays small + grep-friendly. Curator reads the preview
                # to see the full content.
                "preview": f"preview/{e.path}",
            }
            for e in patch.edits
        ],
    }
    (output_dir / "plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    for edit in patch.edits:
        # preview/<path>.md — replicate the wiki's directory shape so the
        # curator can diff against the live wiki later.
        preview_path = preview_dir / edit.path
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(edit.new_content, encoding="utf-8")
    return output_dir.resolve()
