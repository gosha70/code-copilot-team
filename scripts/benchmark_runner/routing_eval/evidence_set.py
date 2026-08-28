"""E1 evidence-set orchestration (routing-shadow T1, plan decision 2).

The ONE production entrypoint that produces and publishes the complete
evidence set E2 consumes: `publish_evidence_set` drives the hybrid
scenario (the router arm), the fixed-profile matrix sweep
(`run_profile_cell`), the control selections under the derived
authority context, and the comparison report — then publishes all
artifacts SET-atomically.

Two properties are load-bearing:

- **"Pinned" is mechanically true.** A matrix cell executes through
  the UNMODIFIED production supervisor under a STAGE-SPECIFIC derived
  registry containing exactly one profile's table entry (copied
  byte-for-byte from the declared full registry). Roles are not
  mutually exclusive, so a multi-profile derived registry could let
  the production selector pick a different profile than the pinned
  one; one profile per invocation removes the possibility, and the
  executed identity recorded in `started-N.json` is asserted against
  the declaration independently on every lifecycle leg.
- **A partial set is never discoverable.** Artifacts are staged in a
  hidden sibling directory on the destination filesystem, validated
  there with the same checks the consumer's loader runs (manifest
  written last), and published by one atomic rename to a
  content-derived set id. Byte-identical duplicates are an idempotent
  no-op; differing content at the same id refuses.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .injection import events_for_task, preset_digest
from .outcome_matrix import (
    Cell,
    Fingerprint,
    OutcomeMatrix,
    build_matrix,
    matrix_dumps,
    select_always_best,
    select_always_cheapest,
    select_oracle,
)
from .quality_fn import cell_quality, compute_mask
from .record_check import load_schema, validate
from .routing_quality import (
    _RC_RS,
    _rc_records,
    build_report,
    router_cells_from_records,
    selector_context_from_registry,
    write_report,
)
from .scenario import run_hybrid_scenario
from .supervisor_runner import SupervisorRunner, registry_digest_of

ARTIFACT_RUNS = "routing-runs.jsonl"
ARTIFACT_MATRIX = "outcome-matrix.json"
ARTIFACT_REPORT = "report.json"
ARTIFACT_MANIFEST = "manifest.json"
_STAGING_PREFIX = ".staging-"

#: The closed, SANITIZED failure vocabulary (routing-shadow decision
#: 4). Details never carry filesystem paths.
FAILURE_CODES = (
    "missing_artifact",
    "unreadable_artifact",
    "schema_invalid",
    "hash_mismatch",
    "fingerprint_mismatch",
    "path_escape",
)


class EvidenceSetError(RuntimeError):
    """The evidence set cannot be produced or published."""


class EvidenceSetInvalid(ValueError):
    """A staged or discovered set fails its binding validation.

    ``code`` is one of FAILURE_CODES; ``artifact`` names the artifact
    enum member; ``detail`` is sanitized (no filesystem paths).
    """

    def __init__(self, code: str, artifact: str, detail: str):
        assert code in FAILURE_CODES
        self.code = code
        self.artifact = artifact
        self.detail = detail
        super().__init__(f"{code} [{artifact}]: {detail}")


# ── registry derivation ────────────────────────────────────────────────
def _profile_declarations(registry_path: Path) -> Mapping[str, Mapping[str, Any]]:
    """Every profile's declared fields, via the production parser."""
    by_ctx: dict[str, dict[str, tuple[str, str]]] = {}
    for ctx, key, typ, value in _rc_records(Path(registry_path)):
        by_ctx.setdefault(ctx, {})[key] = (typ, value)
    declarations: dict[str, dict[str, Any]] = {}
    for ctx, keys in by_ctx.items():
        if not ctx.startswith("profiles."):
            continue
        profile_id = keys.get("id", ("", ""))[1]
        if not profile_id:
            continue
        entry: dict[str, Any] = {}
        for name in ("backend", "provider", "model", "capability_tier",
                     "tool_profile", "base_url_env"):
            if name in keys:
                entry[name] = keys[name][1]
        if "roles" in keys:
            entry["roles"] = tuple(
                r for r in keys["roles"][1].split(_RC_RS) if r
            )
        declarations[profile_id] = entry
    return declarations


def _profile_block(registry_text: str, profile_id: str) -> str:
    """The `[[profiles]]` block declaring ``profile_id``, byte-for-byte
    (header excluded, trailing blank lines trimmed)."""
    lines = registry_text.split("\n")
    blocks: list[tuple[int, int]] = []
    start = None
    for i, line in enumerate(lines + ["[[profiles]]"]):
        if line.strip().startswith("["):
            if start is not None:
                blocks.append((start, i))
                start = None
            if line.strip() == "[[profiles]]":
                start = i + 1
    id_re = re.compile(r'^\s*id\s*=\s*"?' + re.escape(profile_id) + r'"?\s*$')
    for lo, hi in blocks:
        if any(id_re.match(l) for l in lines[lo:hi]):
            block = "\n".join(lines[lo:hi]).rstrip("\n")
            return block + "\n"
    raise EvidenceSetError(
        f"profile {profile_id!r} is not declared by the registry — a cell "
        f"cannot pin an undeclared profile"
    )


def derive_single_profile_registry(
    full_registry: Path,
    profile_id: str,
    out_path: Path,
    *,
    tier: str,
) -> Path:
    """A STAGE-SPECIFIC derived registry: exactly one profile —
    ``profile_id``'s table entry copied byte-for-byte from the
    declared full registry — with route classes admitting exactly its
    tier. The production validator must accept the result."""
    text = Path(full_registry).read_text(encoding="utf-8")
    block = _profile_block(text, profile_id)
    content = (
        "schema_version = 1\n"
        "[policy]\n"
        "enabled = true\n"
        "[route_classes.tier1_only]\n"
        f'tier_order = ["{tier}"]\n'
        "[route_classes.tier2_preferred]\n"
        f'tier_order = ["{tier}"]\n'
        "[[profiles]]\n"
        f"{block}"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    # the production validator is the acceptance gate for the derived
    # registry too — a derivation it rejects never launches anything
    _rc_records(out_path)
    return out_path


# ── the fixed-profile executor ─────────────────────────────────────────
def _assert_leg_identity(
    runner: SupervisorRunner,
    feature: str,
    exec_worktree: "Path | None",
    profile_id: str,
    declared: Mapping[str, Any],
) -> None:
    """The per-leg parity assertion: the profile identity persisted in
    the leg's latest started-N.json must BE the pinned declaration."""
    rt_dir = runner._rt_dir(feature, exec_worktree)
    # delegate legs namespace their attempt records under
    # delegate-<packet-digest>/ inside the rt dir — search recursively
    # and take the newest record: each assertion runs immediately
    # after its own leg, so the newest started record IS that leg's.
    started = sorted(
        rt_dir.rglob("started-*.json"),
        key=lambda p: (p.stat().st_mtime,
                       int(re.sub(r"[^0-9]", "", p.stem) or 0)),
    )
    if not started:
        raise EvidenceSetError(
            f"leg for {feature} persisted no started record — the executed "
            f"identity cannot be verified, so the cell is not evidence"
        )
    profile = json.loads(started[-1].read_text(encoding="utf-8")).get(
        "profile"
    ) or {}
    checks = {
        "id": profile_id,
        "backend": declared.get("backend"),
        "provider": declared.get("provider"),
        "model": declared.get("model"),
        "tool_profile": declared.get("tool_profile"),
    }
    for field_name, expected in checks.items():
        actual = profile.get(field_name)
        if expected is not None and actual != expected:
            raise EvidenceSetError(
                f"leg for {feature} executed profile field "
                f"{field_name}={actual!r}, declared {expected!r} — the "
                f"pinned cell did not execute its declaration"
            )


def _to_sweep_record(record: Mapping[str, Any], profile_id: str) -> dict:
    sweep = dict(record)
    sweep["mode"] = "profile_sweep"
    sweep["profile_id"] = profile_id
    return sweep


def run_profile_cell(
    *,
    repo_root: Path,
    registry_path: Path,
    declarations: Mapping[str, Mapping[str, Any]],
    task: str,
    profile_id: str,
    trial: int,
    seed: int,
    events: Sequence[Any],
    workdir: Path,
    baseline_worktree: Path,
    preset_digest_value: str,
    task_set_revision: str,
    toolchain_digest: str,
    benchmark_id: "str | None",
    delegate_tasks: frozenset,
    reconciler_id: "str | None" = None,
    harness_cmd: "str | None" = None,
    delegate_harness_cmd: "str | None" = None,
    reconcile_harness_cmd: "str | None" = None,
) -> Cell:
    """ONE fixed-profile matrix cell through the unmodified production
    supervisor, per plan decision 2. Ordinary tasks run the `build`
    lifecycle; delegate-class tasks run the full delegation lifecycle
    with the pinned profile as builder (its own one-profile registry)
    and ``reconciler_id`` reconciling under a SECOND one-profile
    registry — stage-specific, so "pinned" is mechanically true. The
    resulting records reduce through the SAME lifecycle fold the
    router arm uses, to exactly one cell."""
    declared = declarations.get(profile_id)
    if not declared:
        raise EvidenceSetError(f"profile {profile_id!r} is undeclared")
    safe = re.sub(r"[^A-Za-z0-9_-]", "-", f"{task}-{profile_id}-t{trial}")
    cell_dir = workdir / f"cell-{safe}"
    if cell_dir.exists():
        raise EvidenceSetError(
            f"cell context cell-{safe} already exists — refusing a possibly "
            f"contaminated cell"
        )
    cell_dir.mkdir(parents=True)
    builder_registry = derive_single_profile_registry(
        registry_path, profile_id, cell_dir / "builder-registry.toml",
        tier=declared.get("capability_tier", "tier1"),
    )
    base_runner = SupervisorRunner(
        repo_root=repo_root,
        registry_path=builder_registry,
        worktree=baseline_worktree,
        state_path=cell_dir / "state.json",
        ledger_root=cell_dir / "ledger",
        preset_digest=preset_digest_value,
        task_set_revision=task_set_revision,
        toolchain_digest=toolchain_digest,
        benchmark_id=benchmark_id,
    )
    # the SAME clean-context machinery the router arm's trials use:
    # fresh cloned worktree, own state and ledger, pre-existing
    # contexts refused
    runner = base_runner.for_trial(trial)
    feature = runner._feature_id(task, trial)
    exec_wt = (
        runner.ledger_root / "task-worktrees" / feature / "worktree"
        if benchmark_id is not None
        else None
    )
    if task in delegate_tasks:
        if not reconciler_id:
            raise EvidenceSetError(
                f"delegate-class cell for {task!r} needs a declared "
                f"reconciler — none was given"
            )
        reconciler_decl = declarations.get(reconciler_id)
        if not reconciler_decl:
            raise EvidenceSetError(
                f"reconciler {reconciler_id!r} is undeclared"
            )
        first = runner.delegate_task(task, trial, seed, delegate_harness_cmd)
        _assert_leg_identity(runner, feature, exec_wt, profile_id, declared)
        reconciler_registry = derive_single_profile_registry(
            registry_path, reconciler_id,
            cell_dir / "reconciler-registry.toml",
            tier=reconciler_decl.get("capability_tier", "tier1"),
        )
        recon_runner = dataclasses.replace(
            runner, registry_path=reconciler_registry
        )
        second = recon_runner.reconcile_task(
            task, trial, seed, reconcile_harness_cmd
        )
        _assert_leg_identity(
            recon_runner, feature, exec_wt, reconciler_id, reconciler_decl
        )
        records = [first, second]
    else:
        records = list(
            runner.run_task(task, trial, seed, list(events), harness_cmd)
        )
        _assert_leg_identity(runner, feature, exec_wt, profile_id, declared)
    sweep_records = [_to_sweep_record(r, profile_id) for r in records]
    (cell,) = router_cells_from_records(sweep_records)
    return dataclasses.replace(cell, profile_id=profile_id, seed=seed)


# ── manifest + validation (the loader's own checks) ────────────────────
def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint_doc(fp: Fingerprint) -> dict:
    return {
        "registry_digest": fp.registry_digest,
        "preset_digest": fp.preset_digest,
        "execution_identity": [dict(e) for e in fp.execution_identity],
        "task_set_revision": fp.task_set_revision,
        "toolchain_digest": fp.toolchain_digest,
    }


def set_id_of(manifest_bytes: bytes) -> str:
    """The evidence-set id: sha256 hex over the manifest's canonical
    bytes — ALWAYS recomputed, never trusted from a directory name."""
    return hashlib.sha256(manifest_bytes).hexdigest()


def _relative_ok(ref: str) -> bool:
    if not ref or os.path.isabs(ref):
        return False
    return ".." not in Path(ref).parts


def validate_evidence_set(root: Path) -> Mapping[str, Any]:
    """The binding validation of routing-shadow decision 4 — the SAME
    checks run in staging before publication and by the consumer's
    loader on discovery. Raises EvidenceSetInvalid with a sanitized
    closed code; returns {set_id, manifest, report, matrix, records}.

    Every artifact's bytes are read ONCE; hashes and parses use the
    same bytes (no TOCTOU window)."""
    root = Path(root)
    raw: dict[str, bytes] = {}
    for name in (ARTIFACT_MANIFEST, ARTIFACT_RUNS, ARTIFACT_MATRIX,
                 ARTIFACT_REPORT):
        p = root / name
        if not p.is_file():
            raise EvidenceSetInvalid("missing_artifact", name,
                                     "artifact absent from the set")
        try:
            raw[name] = p.read_bytes()
        except OSError:
            raise EvidenceSetInvalid("unreadable_artifact", name,
                                     "artifact could not be read") from None

    def _parse(name: str, schema_name: str):
        try:
            doc = json.loads(raw[name].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EvidenceSetInvalid("schema_invalid", name,
                                     "artifact is not valid JSON") from None
        errors = validate(doc, load_schema(schema_name))
        if errors:
            raise EvidenceSetInvalid(
                "schema_invalid", name,
                f"{len(errors)} schema violation(s); first: "
                f"{_sanitize(errors[0])}",
            )
        return doc

    manifest = _parse(ARTIFACT_MANIFEST, "evidence-manifest")
    report = _parse(ARTIFACT_REPORT, "report")
    matrix_doc = _parse(ARTIFACT_MATRIX, "outcome-matrix")

    records = []
    runs_schema = load_schema("routing-run")
    for i, line in enumerate(raw[ARTIFACT_RUNS].decode("utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            raise EvidenceSetInvalid(
                "schema_invalid", ARTIFACT_RUNS,
                f"record {i} is not valid JSON",
            ) from None
        errors = validate(record, runs_schema)
        if errors:
            raise EvidenceSetInvalid(
                "schema_invalid", ARTIFACT_RUNS,
                f"record {i}: {_sanitize(errors[0])}",
            )
        records.append(record)

    # manifest hash bindings — the identity's substance
    hashes = manifest["artifacts"]
    for name, key in ((ARTIFACT_RUNS, "routing_runs_sha256"),
                      (ARTIFACT_MATRIX, "outcome_matrix_sha256"),
                      (ARTIFACT_REPORT, "report_sha256")):
        actual = "sha256:" + hashlib.sha256(raw[name]).hexdigest()
        if actual != hashes[key]:
            raise EvidenceSetInvalid(
                "hash_mismatch", name,
                "manifest hash does not match the artifact bytes",
            )

    # fingerprint bindings, pairwise and exact
    m_fp = manifest["fingerprint"]
    r_fp = report["fingerprint"]
    x_fp = matrix_doc["fingerprint"]
    if m_fp != r_fp or m_fp != x_fp:
        raise EvidenceSetInvalid(
            "fingerprint_mismatch", ARTIFACT_MANIFEST,
            "manifest, report, and matrix fingerprints disagree — "
            "fabricated fingerprint metadata over genuine bytes is still "
            "a mismatch",
        )
    shared = ("registry_digest", "preset_digest", "task_set_revision",
              "toolchain_digest")
    for i, record in enumerate(records):
        for component in shared:
            if record.get(component) != m_fp.get(component):
                raise EvidenceSetInvalid(
                    "fingerprint_mismatch", ARTIFACT_RUNS,
                    f"record {i} disagrees with the manifest on {component}",
                )
    # the report's own source bindings — redundant cross-check
    src = report["source_artifacts"]
    if (src["routing_runs_sha256"] != hashes["routing_runs_sha256"]
            or src["outcome_matrix_sha256"] != hashes["outcome_matrix_sha256"]):
        raise EvidenceSetInvalid(
            "hash_mismatch", ARTIFACT_REPORT,
            "the report's source bindings disagree with the manifest",
        )

    # evidence-file bindings: relative, contained, hash-verified
    for ref, expected in manifest["evidence_files"].items():
        if not _relative_ok(ref):
            raise EvidenceSetInvalid(
                "path_escape", ARTIFACT_MANIFEST,
                "an evidence reference is absolute or escapes the set root",
            )
        target = (root / ref)
        try:
            resolved = target.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            raise EvidenceSetInvalid(
                "path_escape", ARTIFACT_MANIFEST,
                "an evidence reference resolves outside the set root",
            ) from None
        if not resolved.is_file():
            raise EvidenceSetInvalid(
                "missing_artifact", ARTIFACT_MANIFEST,
                "a referenced evidence file is absent",
            )
        if _sha256_file(resolved) != expected:
            raise EvidenceSetInvalid(
                "hash_mismatch", ARTIFACT_MANIFEST,
                "a referenced evidence file does not match its manifest hash",
            )

    return {
        "set_id": set_id_of(raw[ARTIFACT_MANIFEST]),
        "manifest": manifest,
        "report": report,
        "matrix": matrix_doc,
        "records": records,
    }


def _sanitize(text: str) -> str:
    """Strip anything path-shaped from validator output before it can
    reach a served detail."""
    return re.sub(r"(/[^\s'\"]+)+", "<path>", str(text))[:200]


# ── the orchestration entrypoint ───────────────────────────────────────
@dataclass(frozen=True)
class PublishedEvidenceSet:
    set_id: str
    path: Path
    #: True when a byte-identical set already existed (idempotent no-op).
    existed: bool


def publish_evidence_set(
    config: Any,
    registry_path: "Path | str",
    output_root: "Path | str",
    *,
    repo_root: Path,
    baseline_worktree: Path,
    benchmark_id: "str | None",
    preferred_profile: str,
    tier2_profiles: frozenset,
    task_set_revision: str,
    toolchain_digest: str,
    workdir: "Path | None" = None,
    reconciler_id: "str | None" = None,
    ordinary_harness_cmd: "str | None" = None,
    delegate_harness_cmd: "str | None" = None,
    reconcile_harness_cmd: "str | None" = None,
    sweep_harness_cmd: "str | None" = None,
    sweep_delegate_harness_cmd: "str | None" = None,
    sweep_reconcile_harness_cmd: "str | None" = None,
    max_tick_pumps: int = 8,
) -> PublishedEvidenceSet:
    """Produce and publish ONE complete evidence set from ONE validated
    run context (plan decision 2). See the module docstring for the
    two load-bearing properties."""
    registry_path = Path(registry_path)
    output_root = Path(output_root)
    work = Path(workdir) if workdir else Path(
        tempfile.mkdtemp(prefix="evidence-work.")
    )
    work.mkdir(parents=True, exist_ok=True)
    pdg = preset_digest(config)
    declarations = _profile_declarations(registry_path)
    ctx = selector_context_from_registry(registry_path, config)
    reconciler = reconciler_id or preferred_profile

    # (a) the router arm — the hybrid scenario through the production
    # supervisor; run_hybrid_scenario publishes routing-runs.jsonl and
    # the referenced evidence files under the runner's ledger root.
    router_ledger = work / "router-ledger"
    runner = SupervisorRunner(
        repo_root=repo_root,
        registry_path=registry_path,
        worktree=baseline_worktree,
        state_path=work / "router-state.json",
        ledger_root=router_ledger,
        preset_digest=pdg,
        task_set_revision=task_set_revision,
        toolchain_digest=toolchain_digest,
        benchmark_id=benchmark_id,
    )
    artifact = run_hybrid_scenario(
        config,
        runner,
        preferred_profile=preferred_profile,
        tier2_profiles=tier2_profiles,
        ordinary_harness_cmd=ordinary_harness_cmd,
        delegate_harness_cmd=delegate_harness_cmd,
        reconcile_harness_cmd=reconcile_harness_cmd,
        max_tick_pumps=max_tick_pumps,
    )

    # (b) the matrix sweep with the fixed-profile executor
    tasks = list(config.task_filter or [])
    delegate_tasks = frozenset(config.delegate_tasks or [])
    identity = tuple(
        {
            "profile_id": pid,
            "backend": decl.get("backend"),
            "provider": decl.get("provider"),
            "requested_model": decl.get("model"),
            "effective_model": decl.get("model"),
            "tool_profile": decl.get("tool_profile"),
            # the sanitized endpoint: the env-var NAME the registry
            # declares, never a URL value
            "endpoint": decl.get("base_url_env"),
        }
        for pid, decl in sorted(declarations.items())
    )
    fingerprint = Fingerprint(
        registry_digest=registry_digest_of(registry_path),
        preset_digest=pdg,
        execution_identity=identity,
        task_set_revision=task_set_revision,
        toolchain_digest=toolchain_digest,
    )
    sweep_dir = work / "sweep"

    def execute(task: str, profile: str, trial: int, seed: int) -> Cell:
        task_events = (
            [] if task in delegate_tasks
            else events_for_task(list(config.event_stream), tasks.index(task))
        )
        return run_profile_cell(
            repo_root=repo_root,
            registry_path=registry_path,
            declarations=declarations,
            task=task,
            profile_id=profile,
            trial=trial,
            seed=seed,
            events=task_events,
            workdir=sweep_dir,
            baseline_worktree=baseline_worktree,
            preset_digest_value=pdg,
            task_set_revision=task_set_revision,
            toolchain_digest=toolchain_digest,
            benchmark_id=benchmark_id,
            delegate_tasks=delegate_tasks,
            reconciler_id=reconciler,
            harness_cmd=sweep_harness_cmd,
            delegate_harness_cmd=sweep_delegate_harness_cmd,
            reconcile_harness_cmd=sweep_reconcile_harness_cmd,
        )

    matrix = build_matrix(
        fingerprint,
        tasks,
        list(declarations),
        list(config.trial_seeds or []),
        config.cost_basis,
        ctx.eligible,
        execute,
    )

    # (c) the control selections under the derived authority context
    selections = {
        "always_best": select_always_best(
            matrix, ctx.profile_meta, eligible=ctx.eligible
        ),
        "always_cheapest": select_always_cheapest(
            matrix, eligible=ctx.eligible
        ),
    }
    mask = compute_mask(matrix)
    selections["oracle"] = select_oracle(
        matrix, lambda c: cell_quality(c, mask), eligible=ctx.eligible
    )
    if ctx.oracle_budget_ceiling_usd is not None:
        selections["oracle_budget"] = select_oracle(
            matrix,
            lambda c: cell_quality(c, mask),
            ctx.oracle_budget_ceiling_usd,
            eligible=ctx.eligible,
        )

    # (d) the report
    report = build_report(
        matrix,
        selections,
        list(artifact.records),
        expected_preset_digest=pdg,
        registry_path=registry_path,
        config=config,
    )

    # (e) SET-ATOMIC publication
    return _publish(
        output_root,
        runs_path=artifact.artifact_path,
        evidence_root=router_ledger,
        records=list(artifact.records),
        matrix=matrix,
        report=report,
        fingerprint=fingerprint,
    )


def _publish(
    output_root: Path,
    *,
    runs_path: Path,
    evidence_root: Path,
    records: Sequence[Mapping[str, Any]],
    matrix: OutcomeMatrix,
    report: Mapping[str, Any],
    fingerprint: Fingerprint,
) -> PublishedEvidenceSet:
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=output_root)
    )
    try:
        # runs artifact + the evidence files its records reference,
        # copied byte-for-byte with their set-relative paths preserved
        shutil.copyfile(runs_path, staging / ARTIFACT_RUNS)
        evidence_files: dict[str, str] = {}
        published = json.loads(
            "[" + ",".join(
                (staging / ARTIFACT_RUNS)
                .read_text(encoding="utf-8")
                .splitlines()
            ) + "]"
        )
        for record in published:
            for verifier in record.get("verifiers") or []:
                ref = verifier.get("evidence_ref")
                if not isinstance(ref, str) or not _relative_ok(ref):
                    raise EvidenceSetError(
                        "a published record carries a non-relative evidence "
                        "reference — the runs artifact is not set-portable"
                    )
                if ref in evidence_files:
                    continue
                src = evidence_root / ref
                dst = staging / ref
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                evidence_files[ref] = _sha256_file(dst)

        (staging / ARTIFACT_MATRIX).write_text(
            matrix_dumps(matrix), encoding="utf-8"
        )
        source_artifacts = {
            "routing_runs_sha256": _sha256_file(staging / ARTIFACT_RUNS),
            "outcome_matrix_sha256": _sha256_file(staging / ARTIFACT_MATRIX),
        }
        write_report(
            report, staging / ARTIFACT_REPORT,
            source_artifacts=source_artifacts,
        )
        manifest = {
            "schema_version": 1,
            "fingerprint": _fingerprint_doc(fingerprint),
            "artifacts": {
                **source_artifacts,
                "report_sha256": _sha256_file(staging / ARTIFACT_REPORT),
            },
            "evidence_files": evidence_files,
        }
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        # the manifest is written LAST; its bytes are the identity
        (staging / ARTIFACT_MANIFEST).write_bytes(manifest_bytes)

        # in-staging validation: the consumer's own loader checks
        validated = validate_evidence_set(staging)
        set_id = validated["set_id"]

        target = output_root / set_id
        if target.exists():
            if _dirs_byte_identical(staging, target):
                shutil.rmtree(staging)
                return PublishedEvidenceSet(set_id, target, existed=True)
            raise EvidenceSetError(
                f"evidence set {set_id} already exists with DIFFERING "
                f"content — refusing to overwrite; this indicates a "
                f"corrupted or tampered prior publication"
            )
        os.rename(staging, target)
        return PublishedEvidenceSet(set_id, target, existed=False)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _dirs_byte_identical(a: Path, b: Path) -> bool:
    files_a = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    if files_a != files_b:
        return False
    return all((a / f).read_bytes() == (b / f).read_bytes() for f in files_a)


def discover_evidence_sets(root: Path) -> list[Path]:
    """Set directories under one evidence root. Hidden entries —
    including in-flight `.staging-*` — are structurally excluded."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
