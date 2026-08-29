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

from .injection import preset_digest
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
from .redaction import scrub_text, secret_values_from_registry
from .supervisor_runner import SupervisorRunner, registry_digest_of

ARTIFACT_RUNS = "routing-runs.jsonl"
ARTIFACT_MATRIX = "outcome-matrix.json"
ARTIFACT_REPORT = "report.json"
ARTIFACT_MANIFEST = "manifest.json"
#: routing-calibration decision 11 — the OPTIONAL labeled additions.
ARTIFACT_TASK_DESCRIPTORS = "task-descriptors.json"
ARTIFACT_PROFILE_POLICY = "profile-policy.json"
_STAGING_PREFIX = ".staging-"
_PUBLISHER_MARKER = ".publisher"
#: A stale staging directory is cleaned only when BOTH owner checks
#: pass: its recorded publisher process is confirmed dead AND it is
#: older than this window (crash leftovers, never in-flight work).
STALE_STAGING_MAX_AGE_SEC = 24 * 3600

#: The closed, SANITIZED failure vocabulary (routing-shadow decision
#: 4). Details never carry filesystem paths.
FAILURE_CODES = (
    "missing_artifact",
    "unreadable_artifact",
    "schema_invalid",
    "hash_mismatch",
    "fingerprint_mismatch",
    "path_escape",
    "reference_mismatch",
)


def evidence_references(
    records: "Sequence[Mapping[str, Any]]",
) -> tuple[str, ...]:
    """THE canonical evidence-reference set of a run artifact: every
    reference any record carries, from BOTH reference-bearing channels
    the run schema permits (``verifiers[].evidence_ref`` and
    ``repair_cycles[].evidence_ref``). Publication ships exactly this
    set and validation requires the manifest's ``evidence_files`` keys
    to equal it — a reference the manifest does not bind, or a manifest
    entry no record references, is a broken set, not a benign drift."""
    refs: set[str] = set()
    for record in records:
        for verifier in record.get("verifiers") or []:
            ref = verifier.get("evidence_ref")
            if ref is not None:
                refs.add(ref)
        for cycle in record.get("repair_cycles") or []:
            ref = cycle.get("evidence_ref")
            if ref is not None:
                refs.add(ref)
    return tuple(sorted(refs))


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
                     "tool_profile", "base_url", "base_url_env"):
            if name in keys:
                entry[name] = keys[name][1]
        if "roles" in keys:
            entry["roles"] = tuple(
                r for r in keys["roles"][1].split(_RC_RS) if r
            )
        declarations[profile_id] = entry
    return declarations


def derive_profile_policy(
    registry_path: Path, registry_digest: str
) -> dict:
    """routing-calibration decision 11: the executed registry's
    per-profile policy declarations, persisted with the set so tier
    resolution reads source-bound declarations, never a guess. A
    profile without a declared capability_tier refuses — a policy
    document that silently omitted a tier would make the downgrade
    baseline unresolvable later."""
    profiles: dict[str, dict] = {}
    for profile_id, entry in _profile_declarations(registry_path).items():
        tier = entry.get("capability_tier")
        if tier not in ("tier1", "tier2"):
            raise EvidenceSetError(
                f"profile {profile_id!r} declares no capability_tier — the "
                f"profile-policy artifact cannot omit the field the "
                f"false-downgrade baseline resolves from"
            )
        profiles[profile_id] = {
            "capability_tier": tier,
            "roles": sorted(entry.get("roles") or ()),
        }
    if not profiles:
        raise EvidenceSetError(
            "the registry declares no profiles — an empty profile-policy "
            "artifact binds nothing"
        )
    return {
        "schema_version": 1,
        "registry_digest": registry_digest,
        "profiles": profiles,
    }


def derive_task_descriptors(config: Any, preset: str) -> "dict | None":
    """routing-calibration decision 11: the per-task PRE-ROUTING
    descriptors, derived from the executed scenario configuration.
    Returns None when the config declares none (the set then carries no
    descriptor artifact and E3 treats it as unlabeled). Route classes
    derive STRUCTURALLY from the config's own membership declarations —
    tier1_only_tasks -> tier1_only, delegate_tasks -> tier2_preferred
    (the class the delegation seam records), else primary_only. The
    scenario's DECLARED trial count rides along as the corpus property
    the calibration feature vector reads — the observed per-trial
    record count is an execution OBSERVATION and is never a
    pre-routing feature."""
    declared = getattr(config, "task_descriptors", None)
    if not declared:
        return None
    tier1_only = set(getattr(config, "tier1_only_tasks", ()) or ())
    delegate = set(getattr(config, "delegate_tasks", ()) or ())
    descriptors = {}
    for task_id, entry in sorted(declared.items()):
        if task_id in tier1_only:
            route_class = "tier1_only"
        elif task_id in delegate:
            route_class = "tier2_preferred"
        else:
            route_class = "primary_only"
        descriptors[task_id] = {
            "task_class": entry["task_class"],
            "route_class": route_class,
            "file_scope": entry["file_scope"],
        }
    trials = int(getattr(config, "trials", 0) or 0)
    if trials < 1:
        raise EvidenceSetError(
            "the scenario declares no trial count — the descriptors "
            "artifact cannot omit the corpus property the calibration "
            "feature vector reads"
        )
    return {
        "schema_version": 1,
        "preset_digest": preset,
        "trials": trials,
        "descriptors": descriptors,
    }


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
def _endpoint_ref_of(declared: Mapping[str, Any]) -> str:
    """The declaration's endpoint reference in production's OWN closed
    normalization (rc_profile_tuple): url:<literal> | urlenv:<name> |
    none — base_url and base_url_env are BOTH part of the endpoint
    surface."""
    if declared.get("base_url"):
        return f"url:{declared['base_url']}"
    if declared.get("base_url_env"):
        return f"urlenv:{declared['base_url_env']}"
    return "none"


def _resolve_endpoint_ref(ref: "str | None") -> "str | None":
    """Resolve exactly as rt_launch_env does: a literal resolves to
    itself, an env reference to the variable's current value, none to
    None (no endpoint — the backend default)."""
    if not ref or ref == "none":
        return None
    if ref.startswith("url:"):
        return ref[len("url:"):] or None
    if ref.startswith("urlenv:"):
        return os.environ.get(ref[len("urlenv:"):]) or None
    return None


def _endpoint_identity(resolved: "str | None") -> "str | None":
    """A redacted but FULL-VALUE-SENSITIVE endpoint identity: the
    sanitized origin+path (userinfo/query/fragment never exposed) plus
    a sha256 of the complete resolved endpoint — so a query or
    userinfo change alters the identity without exposing it, and two
    deployments behind one host can never collide. None when nothing
    resolved (unverified, never assumed)."""
    if not resolved:
        return None
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    from urllib.parse import urlsplit

    parts = urlsplit(resolved)
    if not parts.scheme or not parts.hostname:
        return f"digest:{digest}"
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    return f"{parts.scheme}://{netloc}{parts.path or ''}#sha256:{digest}"


def _observed_leg_identity(
    runner: SupervisorRunner,
    feature: str,
    exec_worktree: "Path | None",
    profile_id: str,
    declared: Mapping[str, Any],
) -> Mapping[str, Any]:
    """The per-leg identity, EXECUTION-PROVEN from durable evidence and
    asserted against the pinned declaration — all seven fields:

    - requested identity (profile id, backend, provider, requested
      model, tool profile) from the leg's persisted started-N.json —
      the record the supervisor writes BEFORE launch;
    - effective model from the SAME attempt's durable result-N.json,
      tri-state exactly as production records it (null = UNVERIFIED,
      never assumed equal to requested; the supervisor itself refuses
      a mismatch);
    - the sanitized RESOLVED endpoint from the actual launch
      environment (the value behind the declared base_url_env — same
      env name, different resolved endpoint IS a different execution).
    """
    rt_dir = runner._rt_dir(feature, exec_worktree)
    # delegate legs namespace their attempt records under
    # delegate-<packet-digest>/ inside the rt dir — search recursively
    # and take the newest record: each observation runs immediately
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
    started_path = started[-1]
    doc = json.loads(started_path.read_text(encoding="utf-8"))
    profile = doc.get("profile") or {}
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
    attempt = int(re.sub(r"[^0-9]", "", started_path.stem) or 0)
    result_path = started_path.with_name(f"result-{attempt}.json")
    # FAIL-CLOSED: production writes a durable result record for every
    # attempt (success, failure, and policy termination alike). A
    # missing or unparseable result after a successful invocation is
    # destroyed evidence, NOT the tri-state unverified null — an
    # explicit result without an effective model is.
    if not result_path.is_file():
        raise EvidenceSetError(
            f"leg for {feature} has no durable result record for its "
            f"final attempt — the effective-model evidence is absent, "
            f"not unverified; the cell is not evidence"
        )
    try:
        result_doc = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise EvidenceSetError(
            f"leg for {feature} has a corrupt result record — destroyed "
            f"evidence is never converted into the unverified state"
        ) from None
    effective = (result_doc.get("result") or {}).get("effective_model")
    if effective is not None and effective != declared.get("model"):
        raise EvidenceSetError(
            f"leg for {feature} reports effective model {effective!r} but "
            f"the pinned declaration is {declared.get('model')!r} — an "
            f"identity violation is never folded into evidence"
        )
    # the endpoint authority is the PERSISTED profile's endpoint_ref —
    # the exact reference rt_launch_env resolved (url:<literal> |
    # urlenv:<name> | none) — resolved the same way and reduced to the
    # redacted full-value-sensitive identity
    endpoint_ref = profile.get("endpoint_ref") or _endpoint_ref_of(declared)
    return {
        "profile_id": profile_id,
        "backend": profile.get("backend") or declared.get("backend"),
        "provider": profile.get("provider") or declared.get("provider"),
        "requested_model": profile.get("model") or declared.get("model"),
        "effective_model": effective,
        "tool_profile": (profile.get("tool_profile")
                         or declared.get("tool_profile")),
        "endpoint": _endpoint_identity(_resolve_endpoint_ref(endpoint_ref)),
    }


def aggregate_profile_identity(
    profile_id: str,
    observations: Sequence[Mapping[str, Any]],
    declared: Mapping[str, Any],
) -> Mapping[str, Any]:
    """ONE compatible execution identity per profile, from every
    executed leg's observation — or refusal. The requested-side fields
    and the endpoint must agree exactly across all legs; the effective
    model is the common non-null observation (null overall when NO leg
    verified it — never the requested model by assumption); conflicting
    non-null effective models refuse. A profile with no executed cells
    gets its declared requested-side identity with effective_model
    null (unverified) and the currently-resolved sanitized endpoint."""
    if not observations:
        return {
            "profile_id": profile_id,
            "backend": declared.get("backend"),
            "provider": declared.get("provider"),
            "requested_model": declared.get("model"),
            "effective_model": None,
            "tool_profile": declared.get("tool_profile"),
            "endpoint": _endpoint_identity(
                _resolve_endpoint_ref(_endpoint_ref_of(declared))
            ),
        }
    first = observations[0]
    for field_name in ("backend", "provider", "requested_model",
                       "tool_profile", "endpoint"):
        values = {o.get(field_name) for o in observations}
        if len(values) != 1:
            raise EvidenceSetError(
                f"profile {profile_id!r} executed under {len(values)} "
                f"different {field_name} identities {sorted(map(repr, values))} "
                f"— one profile, one execution identity, or no matrix"
            )
    # CONSERVATIVE effective-model aggregation: a non-null value is
    # emitted only when EVERY executed observation verified the same
    # model. One explicitly-unverified leg makes the whole profile
    # unverified (null) — a mixed [null, "m"] history is NOT the same
    # execution certainty as ["m", "m"], and the fingerprint exists to
    # make reuse exact. Conflicting non-null values still refuse.
    effective_values = [o.get("effective_model") for o in observations]
    non_null = set(effective_values) - {None}
    if len(non_null) > 1:
        raise EvidenceSetInvalid(
            "fingerprint_mismatch", ARTIFACT_MATRIX,
            "conflicting verified effective models for one profile",
        )
    all_verified = bool(non_null) and None not in effective_values
    return {
        "profile_id": profile_id,
        "backend": first.get("backend"),
        "provider": first.get("provider"),
        "requested_model": first.get("requested_model"),
        "effective_model": non_null.pop() if all_verified else None,
        "tool_profile": first.get("tool_profile"),
        "endpoint": first.get("endpoint"),
    }


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
    identity_sink: "list | None" = None,
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
        observed = _observed_leg_identity(
            runner, feature, exec_wt, profile_id, declared
        )
        if identity_sink is not None:
            identity_sink.append((profile_id, observed))
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
        recon_observed = _observed_leg_identity(
            recon_runner, feature, exec_wt, reconciler_id, reconciler_decl
        )
        if identity_sink is not None:
            identity_sink.append((reconciler_id, recon_observed))
        records = [first, second]
    else:
        records = list(
            runner.run_task(task, trial, seed, list(events), harness_cmd)
        )
        observed = _observed_leg_identity(
            runner, feature, exec_wt, profile_id, declared
        )
        if identity_sink is not None:
            identity_sink.append((profile_id, observed))
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
    try:
        runs_text = raw[ARTIFACT_RUNS].decode("utf-8")
    except UnicodeDecodeError:
        raise EvidenceSetInvalid(
            "schema_invalid", ARTIFACT_RUNS,
            "artifact is not valid UTF-8",
        ) from None
    for i, line in enumerate(runs_text.splitlines()):
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

    # evidence-reference binding: the manifest's evidence_files keys
    # equal EXACTLY the canonical reference set of the records — an
    # unbound record reference (unverifiable serving) and an orphan
    # manifest entry (unreferenced payload) both refuse the set
    if tuple(sorted(manifest["evidence_files"])) != evidence_references(records):
        raise EvidenceSetInvalid(
            "reference_mismatch", ARTIFACT_MANIFEST,
            "the manifest's evidence files disagree with the references "
            "the run records carry",
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

    # routing-calibration decision 11: the OPTIONAL labeled additions.
    # Absent manifest keys mean a pre-addition (or descriptor-less) set
    # — valid, loaded with None. A PRESENT key binds fully: file exists,
    # hash matches, schema validates, digests agree with the manifest
    # fingerprint, and coverage is exact (descriptor tasks within the
    # matrix tasks; every executed profile in the policy).
    task_descriptors_doc = None
    profile_policy_doc = None
    if "task_descriptors_sha256" in hashes:
        task_descriptors_doc = _optional_artifact(
            root, ARTIFACT_TASK_DESCRIPTORS, "task-descriptors",
            hashes["task_descriptors_sha256"],
        )
        if task_descriptors_doc["preset_digest"] != m_fp.get("preset_digest"):
            raise EvidenceSetInvalid(
                "fingerprint_mismatch", ARTIFACT_TASK_DESCRIPTORS,
                "descriptor preset digest disagrees with the manifest "
                "fingerprint",
            )
        matrix_tasks = set(matrix_doc.get("tasks") or ())
        unknown = sorted(
            set(task_descriptors_doc["descriptors"]) - matrix_tasks
        )
        if unknown:
            raise EvidenceSetInvalid(
                "reference_mismatch", ARTIFACT_TASK_DESCRIPTORS,
                "descriptors name task(s) outside the outcome matrix",
            )
    if "profile_policy_sha256" in hashes:
        profile_policy_doc = _optional_artifact(
            root, ARTIFACT_PROFILE_POLICY, "profile-policy",
            hashes["profile_policy_sha256"],
        )
        if profile_policy_doc["registry_digest"] != m_fp.get("registry_digest"):
            raise EvidenceSetInvalid(
                "fingerprint_mismatch", ARTIFACT_PROFILE_POLICY,
                "policy registry digest disagrees with the manifest "
                "fingerprint",
            )
        executed = {
            e.get("profile_id")
            for e in m_fp.get("execution_identity") or ()
        }
        missing = sorted(executed - set(profile_policy_doc["profiles"]))
        if missing:
            raise EvidenceSetInvalid(
                "reference_mismatch", ARTIFACT_PROFILE_POLICY,
                "an executed profile is absent from the profile policy",
            )

    return {
        "set_id": set_id_of(raw[ARTIFACT_MANIFEST]),
        "manifest": manifest,
        "report": report,
        "matrix": matrix_doc,
        "records": records,
        "task_descriptors": task_descriptors_doc,
        "profile_policy": profile_policy_doc,
    }


def _optional_artifact(
    root: Path, name: str, schema_name: str, expected_hash: str
) -> dict:
    p = root / name
    if not p.is_file():
        raise EvidenceSetInvalid("missing_artifact", name,
                                 "manifest-bound artifact absent")
    try:
        data = p.read_bytes()
    except OSError:
        raise EvidenceSetInvalid("unreadable_artifact", name,
                                 "artifact could not be read") from None
    if "sha256:" + hashlib.sha256(data).hexdigest() != expected_hash:
        raise EvidenceSetInvalid(
            "hash_mismatch", name,
            "manifest hash does not match the artifact bytes",
        )
    try:
        doc = json.loads(data.decode("utf-8"))
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

    # (b) the matrix sweep with the fixed-profile executor.
    # The execution identity is EXECUTION-PROVEN: observed per leg from
    # the durable started/result records and the resolved launch
    # environment, aggregated per profile AFTER the sweep — so the
    # provisional fingerprint used during cell construction is replaced
    # by the observed one before anything is published. Effective model
    # is never assumed equal to requested; a moved endpoint behind the
    # same env name IS a different execution.
    tasks = list(config.task_filter or [])
    delegate_tasks = frozenset(config.delegate_tasks or [])
    identity_sink: list = []
    provisional_identity = tuple(
        {
            "profile_id": pid,
            "backend": decl.get("backend"),
            "provider": decl.get("provider"),
            "requested_model": decl.get("model"),
            "effective_model": None,
            "tool_profile": decl.get("tool_profile"),
            "endpoint": _endpoint_identity(
                _resolve_endpoint_ref(_endpoint_ref_of(decl))
            ),
        }
        for pid, decl in sorted(declarations.items())
    )
    provisional_fp = Fingerprint(
        registry_digest=registry_digest_of(registry_path),
        preset_digest=pdg,
        execution_identity=provisional_identity,
        task_set_revision=task_set_revision,
        toolchain_digest=toolchain_digest,
    )
    sweep_dir = work / "sweep"

    def execute(task: str, profile: str, trial: int, seed: int) -> Cell:
        # router-arc shaping events are ROUTER-ARM-ONLY (the E1
        # contract correction accepted in the T1 review): a pinned
        # single-profile cell has no failover path, and the sweep
        # measures profile capability under an availability-neutral
        # baseline, not outage response. The event stream stays in
        # preset_digest, so changing the scenario still invalidates
        # reuse.
        task_events: list = []
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
            identity_sink=identity_sink,
        )

    matrix = build_matrix(
        provisional_fp,
        tasks,
        list(declarations),
        list(config.trial_seeds or []),
        config.cost_basis,
        ctx.eligible,
        execute,
    )
    # aggregate the observed identities: every executed leg for one
    # profile must present ONE compatible execution identity, or no
    # matrix is published at all
    by_profile: dict[str, list] = {pid: [] for pid in declarations}
    for pid, observed in identity_sink:
        by_profile.setdefault(pid, []).append(observed)
    observed_identity = tuple(
        aggregate_profile_identity(pid, by_profile.get(pid, ()),
                                   declarations.get(pid, {}))
        for pid in sorted(declarations)
    )
    fingerprint = dataclasses.replace(
        provisional_fp, execution_identity=observed_identity
    )
    matrix = dataclasses.replace(matrix, fingerprint=fingerprint)

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
    secrets = (
        runner._secret_values()
        if hasattr(runner, "_secret_values")
        else secret_values_from_registry(registry_path)
    )
    return _publish(
        output_root,
        runs_path=artifact.artifact_path,
        evidence_root=router_ledger,
        records=list(artifact.records),
        matrix=matrix,
        report=report,
        fingerprint=fingerprint,
        secret_values=secrets,
        task_descriptors=derive_task_descriptors(config, pdg),
        profile_policy=derive_profile_policy(
            registry_path, fingerprint.registry_digest
        ),
    )


def _publisher_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _clean_stale_staging(
    output_root: Path, max_age_sec: float = STALE_STAGING_MAX_AGE_SEC
) -> None:
    """The owner-checked cleanup of crash-leftover staging
    directories: removed ONLY when the recorded publisher pid is
    confirmed dead AND the directory is older than the age window. An
    in-flight publisher (alive pid, or too young to judge) is never
    touched; discovery never sees staging either way."""
    import time

    if not output_root.is_dir():
        return
    now = time.time()
    for entry in output_root.iterdir():
        if not entry.is_dir() or not entry.name.startswith(_STAGING_PREFIX):
            continue
        try:
            age = now - entry.stat().st_mtime
        except OSError:
            continue
        if age < max_age_sec:
            continue
        marker = entry / _PUBLISHER_MARKER
        try:
            pid = int(marker.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            # ownership cannot be established — the contract is
            # "recorded publisher pid CONFIRMED DEAD"; an unprovable
            # owner is never confirmed anything, so never deleted
            continue
        if _publisher_alive(pid):
            continue
        shutil.rmtree(entry, ignore_errors=True)


def _publish(
    output_root: Path,
    *,
    runs_path: Path,
    evidence_root: Path,
    records: Sequence[Mapping[str, Any]],
    matrix: OutcomeMatrix,
    report: Mapping[str, Any],
    fingerprint: Fingerprint,
    secret_values: Sequence[str],
    task_descriptors: "Mapping[str, Any] | None" = None,
    profile_policy: "Mapping[str, Any] | None" = None,
) -> PublishedEvidenceSet:
    output_root.mkdir(parents=True, exist_ok=True)
    _clean_stale_staging(output_root)
    staging = Path(
        tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=output_root)
    )
    (staging / _PUBLISHER_MARKER).write_text(
        str(os.getpid()), encoding="utf-8"
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
        # ONE canonical reference set — every reference-bearing channel
        # the run schema permits — so the manifest binds exactly what
        # the records reference (validation requires the equality).
        for ref in evidence_references(published):
            if not isinstance(ref, str) or not _relative_ok(ref):
                raise EvidenceSetError(
                    "a published record carries a non-relative evidence "
                    "reference — the runs artifact is not set-portable"
                )
            src = (evidence_root / ref).resolve()
            try:
                src.relative_to(Path(evidence_root).resolve())
            except ValueError:
                raise EvidenceSetError(
                    f"evidence file {ref!r} resolves outside the evidence "
                    f"root — a relative reference (or a symlink under it) "
                    f"can never import an external file into a set"
                ) from None
            dst = staging / ref
            dst.parent.mkdir(parents=True, exist_ok=True)
            # VERIFIED dangerous bytes are still dangerous bytes:
            # hash verification proves integrity, not redaction.
            # Evidence files pass through the SAME write-time
            # scrub as every other published string (dynamic
            # literal secrets + path collapse) and the manifest
            # hashes the SCRUBBED bytes — so the API's
            # hash-verified serving can never faithfully deliver
            # a secret or a sensitive absolute path.
            try:
                text = src.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise EvidenceSetError(
                    f"evidence file {ref!r} is not valid UTF-8 text — "
                    f"an unscrubabble file never ships with a set"
                ) from None
            dst.write_text(
                scrub_text(text, secret_values=secret_values),
                encoding="utf-8",
            )
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
        # routing-calibration decision 11: the optional labeled
        # additions — canonical JSON, hashed into the manifest so the
        # binding validation covers them like every other artifact.
        optional_artifacts: dict[str, str] = {}
        for doc, name, key in (
            (task_descriptors, ARTIFACT_TASK_DESCRIPTORS,
             "task_descriptors_sha256"),
            (profile_policy, ARTIFACT_PROFILE_POLICY,
             "profile_policy_sha256"),
        ):
            if doc is None:
                continue
            (staging / name).write_text(
                json.dumps(doc, sort_keys=True, separators=(",", ":"))
                + "\n",
                encoding="utf-8",
            )
            optional_artifacts[key] = _sha256_file(staging / name)

        manifest = {
            "schema_version": 1,
            "fingerprint": _fingerprint_doc(fingerprint),
            "artifacts": {
                **source_artifacts,
                "report_sha256": _sha256_file(staging / ARTIFACT_REPORT),
                **optional_artifacts,
            },
            "evidence_files": evidence_files,
        }
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        # the publisher marker is staging machinery, never set content
        (staging / _PUBLISHER_MARKER).unlink(missing_ok=True)
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
