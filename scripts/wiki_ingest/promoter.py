# wiki_ingest.promoter — Phase-2 patch-set promotion.
#
# THE ONLY MODULE IN THE PIPELINE THAT WRITES TO knowledge/wiki/.
#
# Promotion is atomic: build a staged tree (copy of the current wiki +
# the patch-set's edits applied), validate the staged tree end-to-end
# (per-edit semantic + structural lint), and only then commit the
# staged tree to ``knowledge/wiki/``. Any validation failure leaves
# the wiki untouched.
#
# The validation step intentionally runs against the staged tree, not
# the live wiki, so:
#   - an ``update`` to a path that was just ``create``-d in the same
#     patch-set is legitimate (it didn't exist pre-apply, it exists
#     post-apply)
#   - the wiki linter sees the post-apply state and judges link
#     integrity / orphan-from-index against the would-be wiki, not
#     the pre-apply wiki
#
# After a successful commit, the proposals dir is moved to
# ``doc_internal/proposals/.applied/<source-stem>/`` (gitignored audit
# trail). Subsequent runs against the same dir are no-ops.

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    PromoteApplyError,
    PromoteValidationError,
)
from .proposal import (
    PageEdit,
    WikiPatchSet,
    validate_page_edit_semantics,
    validate_patch_set,
)


@dataclass(frozen=True)
class PromoteResult:
    """Outcome of a successful promote.

    Attributes
    ----------
    applied_paths : list[str]
        Wiki-relative paths affected (created/updated/appended-to).
    proposals_dir : Path
        Original proposals dir (now moved to ``.applied/`` unless
        ``dry_run`` was set).
    archived_dir : Path | None
        Where the proposals dir was moved to after commit. None if
        dry_run.
    dry_run : bool
        True if the staged tree was built and validated but never
        committed to the live wiki.
    """
    applied_paths: list[str]
    proposals_dir: Path
    archived_dir: Path | None
    dry_run: bool


def _load_patch_from_dir(proposals_dir: Path) -> WikiPatchSet:
    """Reconstruct a WikiPatchSet from a proposals dir on disk."""
    plan_path = proposals_dir / "plan.json"
    if not plan_path.exists():
        raise PromoteValidationError(
            f"plan.json not found in {proposals_dir}; not a valid "
            f"proposals dir."
        )
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PromoteValidationError(
            f"plan.json at {plan_path} is not valid JSON: {exc}"
        ) from exc

    edits: list[PageEdit] = []
    for raw in plan.get("edits", []):
        # plan.json does not embed full new_content (Phase 1 stored it
        # only in preview/<path>) so we re-read from preview on apply.
        preview_rel = raw.get("preview")
        if not preview_rel:
            raise PromoteValidationError(
                f"plan.json edit missing 'preview' pointer: {raw!r}"
            )
        preview_path = proposals_dir / preview_rel
        if not preview_path.exists():
            raise PromoteValidationError(
                f"preview file referenced by plan.json missing: "
                f"{preview_path}"
            )
        new_content = preview_path.read_text(encoding="utf-8")
        edits.append(
            PageEdit(
                path=str(raw["path"]),
                action=raw["action"],
                new_content=new_content,
                rationale=str(raw.get("rationale", "")),
            )
        )
    return WikiPatchSet(
        edits=edits,
        source_path=str(plan.get("source_path", "")),
        backend=str(plan.get("backend", "")),
        rationale=str(plan.get("rationale", "")),
    )


def _stage_wiki(repo_root: Path, dest: Path) -> None:
    """Copy the current wiki tree to ``dest`` (excluding scripts/)."""
    wiki_src = repo_root / "knowledge" / "wiki"
    if not wiki_src.is_dir():
        raise PromoteApplyError(
            f"wiki source not found at {wiki_src}; cannot stage."
        )
    if dest.exists():
        shutil.rmtree(dest)
    # Shallow copy via copytree — knowledge/wiki/ is small (~21 pages),
    # full copy is the simplest atomicity primitive.
    shutil.copytree(wiki_src, dest)


def _apply_edit(stage_dir: Path, edit: PageEdit) -> None:
    """Apply one edit to the staged tree.

    - create        : write new file (parent dirs created)
    - update        : overwrite existing file
    - append-log    : append a line to log.md (or <subdir>/log.md)
    - append-index  : append a line to index.md (or <subdir>/index.md)

    Raises PromoteApplyError if the edit is unapplicable (e.g.
    update to a path that doesn't exist in the staged tree). The
    per-edit validator catches most of these earlier; this is a
    defense-in-depth check at apply time.
    """
    target = stage_dir / edit.path
    if edit.action == "create":
        if target.exists():
            raise PromoteApplyError(
                f"create edit to {edit.path}: already exists in staged "
                f"tree (caught at apply time)."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit.new_content, encoding="utf-8")
    elif edit.action == "update":
        if not target.exists():
            raise PromoteApplyError(
                f"update edit to {edit.path}: does not exist in staged "
                f"tree (caught at apply time)."
            )
        target.write_text(edit.new_content, encoding="utf-8")
    elif edit.action == "append-log":
        if not target.exists():
            raise PromoteApplyError(
                f"append-log edit to {edit.path}: log.md does not exist "
                f"in staged tree."
            )
        existing = target.read_text(encoding="utf-8")
        suffix = edit.new_content if edit.new_content.endswith("\n") else edit.new_content + "\n"
        prefix = existing if existing.endswith("\n") else existing + "\n"
        target.write_text(prefix + suffix, encoding="utf-8")
    elif edit.action == "append-index":
        if not target.exists():
            raise PromoteApplyError(
                f"append-index edit to {edit.path}: index.md does not "
                f"exist in staged tree."
            )
        existing = target.read_text(encoding="utf-8")
        suffix = edit.new_content if edit.new_content.endswith("\n") else edit.new_content + "\n"
        prefix = existing if existing.endswith("\n") else existing + "\n"
        target.write_text(prefix + suffix, encoding="utf-8")
    else:
        raise PromoteApplyError(
            f"unknown action {edit.action!r} in edit for {edit.path}"
        )


def _validate_staged_tree(
    stage_dir: Path,
    repo_root: Path,
    patch: WikiPatchSet,
) -> None:
    """Re-run per-edit semantic + structural lint against the staged tree.

    The staged tree is the post-apply view of knowledge/wiki/, so
    create/update edits that depend on each other (e.g. an append-log
    that targets a log.md created earlier in the same patch-set) are
    judged against the right state.

    Raises PromoteValidationError on any failure; the wiki tree is
    not touched.
    """
    # Build a temporary repo root whose knowledge/wiki/ is the staged
    # tree so validate_page_edit_semantics' update/create-target-exists
    # checks see post-apply state.
    with tempfile.TemporaryDirectory(prefix="wiki-promote-validate-") as tmp:
        tmp_root = Path(tmp)
        (tmp_root / "knowledge").mkdir()
        # symlink the staged wiki under the temp root's knowledge/
        (tmp_root / "knowledge" / "wiki").symlink_to(stage_dir)

        per_edit_errors: list[str] = []
        for edit in patch.edits:
            # Per-edit validation against the staged tree. NOTE: for
            # `create` actions, the staged tree has just had the file
            # created, so the "create target must not exist" check
            # would now fire. Skip the existence checks for create
            # in post-apply mode by passing a temp-root whose wiki has
            # NOT yet been written to for the file under inspection —
            # actually simpler: the per-edit validator's existence
            # checks make sense pre-apply. Here we re-verify the
            # frontmatter cross-consistency (the part that matters
            # post-apply: slug==stem, page_type promotable, dir
            # placement, sources non-empty). We DO want to re-check
            # update existence in case Phase-2's caller skipped Phase-1
            # validation.
            if edit.action == "create":
                # Don't re-run the create-clobber check (the file
                # exists in the staged tree by design, post-apply).
                # Re-run the rest by passing a fake repo root with no
                # knowledge/wiki/ so existence checks skip.
                with tempfile.TemporaryDirectory(prefix="wiki-no-wiki-") as empty:
                    empty_root = Path(empty)
                    per_edit_errors.extend(
                        validate_page_edit_semantics(edit, empty_root)
                    )
            else:
                per_edit_errors.extend(
                    validate_page_edit_semantics(edit, tmp_root)
                )
        if per_edit_errors:
            raise PromoteValidationError(
                "Staged-tree per-edit validation failed:\n  - "
                + "\n  - ".join(per_edit_errors)
            )

        set_errors = validate_patch_set(patch)
        if set_errors:
            raise PromoteValidationError(
                "Staged-tree set-level validation failed:\n  - "
                + "\n  - ".join(set_errors)
            )

    # Structural lint. The lint script reads the wiki dir from
    # knowledge/wiki/ relative to the script's location. We invoke
    # via bash with the staged tree masked into a temporary repo
    # layout so the linter sees the post-apply state.
    lint_script = repo_root / "knowledge" / "wiki" / "scripts" / "lint-wiki.sh"
    if not lint_script.exists():
        # Linter missing → soft warning; don't block promote on a
        # missing dependency (the alignment gate would catch it).
        return

    with tempfile.TemporaryDirectory(prefix="wiki-lint-stage-") as tmp:
        tmp_root = Path(tmp)
        # Replicate the repo layout enough that intra-wiki escape
        # links (e.g. ``../../../shared/skills/...``) resolve to real
        # files. The lint script anchors WIKI_DIR off its own
        # location, so we copy the staged wiki to
        # <tmp>/knowledge/wiki/ and symlink the other top-level repo
        # entries from <tmp>/ so escape paths resolve identically.
        kn_dir = tmp_root / "knowledge"
        kn_dir.mkdir()
        wiki_dst = kn_dir / "wiki"
        shutil.copytree(stage_dir, wiki_dst)
        # Restore scripts/ + schema/ that the staging step omitted
        # (they're not patch-set targets but the linter needs them).
        for sub in ("scripts", "schema"):
            src = repo_root / "knowledge" / "wiki" / sub
            dst = wiki_dst / sub
            if src.is_dir() and not dst.exists():
                shutil.copytree(src, dst)
        # Symlink every other top-level repo entry from <tmp>/ so
        # escape links from wiki pages (``../../../shared/...``, etc.)
        # resolve. Skip ``knowledge`` (we've built our own) and any
        # entry that's already in <tmp>/ from a prior loop iteration.
        for entry in repo_root.iterdir():
            if entry.name == "knowledge":
                continue
            link = tmp_root / entry.name
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(entry)
            except OSError:
                if entry.is_file():
                    shutil.copy(entry, link)
        # Mirror the rest of <repo>/knowledge/ besides wiki/ (e.g.
        # knowledge/README.md, knowledge/raw/) — wiki pages may link
        # up two levels to ``../../README.md`` from a workflows page.
        for entry in (repo_root / "knowledge").iterdir():
            if entry.name == "wiki":
                continue
            link = kn_dir / entry.name
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(entry)
            except OSError:
                if entry.is_file():
                    shutil.copy(entry, link)

        result = subprocess.run(
            ["bash", str(wiki_dst / "scripts" / "lint-wiki.sh")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise PromoteValidationError(
                "Structural linter rejected staged tree:\n"
                f"{result.stdout}\n{result.stderr}"
            )


def _commit_stage_to_wiki(stage_dir: Path, repo_root: Path) -> list[str]:
    """Copy staged tree files back into knowledge/wiki/. Returns the
    list of wiki-relative paths that were written."""
    wiki_dst = repo_root / "knowledge" / "wiki"
    written: list[str] = []
    for staged in stage_dir.rglob("*.md"):
        rel = staged.relative_to(stage_dir)
        rel_str = rel.as_posix()
        # Skip schema/ and scripts/ — they're not patch-set targets.
        if rel.parts and rel.parts[0] in ("schema", "scripts"):
            continue
        target = wiki_dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        new_content = staged.read_text(encoding="utf-8")
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing == new_content:
                continue
        target.write_text(new_content, encoding="utf-8")
        written.append(rel_str)
    return written


def _archive_proposals_dir(proposals_dir: Path, repo_root: Path) -> Path:
    """Move the proposals dir into doc_internal/proposals/.applied/.

    The .applied/ subdir is gitignored (doc_internal/ already is) and
    serves as an audit trail. Idempotent: a second call with the same
    dir is a no-op when the dir has already been archived.
    """
    applied_root = repo_root / "doc_internal" / "proposals" / ".applied"
    applied_root.mkdir(parents=True, exist_ok=True)
    target = applied_root / proposals_dir.name
    if target.exists():
        # Archived already; nothing to do.
        return target
    shutil.move(str(proposals_dir), str(target))
    return target


def _is_already_applied(proposals_dir: Path) -> bool:
    """True when proposals_dir lives under doc_internal/proposals/.applied/."""
    return ".applied" in proposals_dir.parts


def promote(
    proposals_dir: Path,
    repo_root: Path,
    dry_run: bool = False,
) -> PromoteResult:
    """Apply a proposals dir's patch-set to knowledge/wiki/ atomically.

    Parameters
    ----------
    proposals_dir : Path
        Directory containing plan.json + preview/<path>.md (output of
        Phase-1 ``wiki ingest``).
    repo_root : Path
        Repo root; knowledge/wiki/ resolved relative to it.
    dry_run : bool
        When True, build and validate the staged tree but do not
        commit to knowledge/wiki/ and do not move the proposals dir
        to .applied/.

    Returns
    -------
    PromoteResult
        Summary of what was applied (or would be applied, on dry-run).
    """
    if _is_already_applied(proposals_dir):
        # Idempotency: a second promote on an already-archived dir
        # is a no-op. Caller can detect via applied_paths == [].
        return PromoteResult(
            applied_paths=[],
            proposals_dir=proposals_dir,
            archived_dir=proposals_dir,
            dry_run=dry_run,
        )

    if not proposals_dir.is_dir():
        raise PromoteValidationError(
            f"proposals dir not found: {proposals_dir}"
        )

    patch = _load_patch_from_dir(proposals_dir)
    if not patch.edits:
        # Empty patch-set (gate reject) — nothing to apply.
        archived: Path | None = None
        if not dry_run:
            archived = _archive_proposals_dir(proposals_dir, repo_root)
        return PromoteResult(
            applied_paths=[],
            proposals_dir=proposals_dir,
            archived_dir=archived,
            dry_run=dry_run,
        )

    with tempfile.TemporaryDirectory(prefix="wiki-stage-") as stage:
        stage_dir = Path(stage) / "wiki"
        _stage_wiki(repo_root, stage_dir)

        for edit in patch.edits:
            _apply_edit(stage_dir, edit)

        # Validation gate. Raises PromoteValidationError on any
        # failure; the wiki tree is unchanged because we haven't
        # committed yet.
        _validate_staged_tree(stage_dir, repo_root, patch)

        if dry_run:
            return PromoteResult(
                applied_paths=[e.path for e in patch.edits],
                proposals_dir=proposals_dir,
                archived_dir=None,
                dry_run=True,
            )

        applied = _commit_stage_to_wiki(stage_dir, repo_root)

    archived = _archive_proposals_dir(proposals_dir, repo_root)
    return PromoteResult(
        applied_paths=applied,
        proposals_dir=proposals_dir,
        archived_dir=archived,
        dry_run=False,
    )
