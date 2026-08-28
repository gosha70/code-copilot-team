"""The hybrid routing scenario: arc verification and the driver (E1 T4).

The #109 §12 arc: preferred Tier-1 build → injected usage-limit → next
Tier-1 profile → bounded Tier-2 task → preferred-profile recovery →
Tier-1 reconciliation.

The owner's pinned rule governs everything here: **leg completeness is
proven from durable routing-run evidence and state transitions, never
from a driver-maintained visited-legs list.** Three consequences,
hardened by the owner's counterexamples:

- **One ordered witness per trial.** Each declared trial must prove
  the full chain ``initial preferred < failover < Tier-2 provisional <
  recovery selection < reconciliation`` in strictly increasing record
  order. Evidence from different trials never combines into one
  apparent success, and a reordered record sequence never verifies.
- **Structured vocabulary, not prose.** Failover is proven by the
  candidate's closed circuit ``state`` (cooldown), refusal by the
  decision's closed ``route_class`` (tier1_only) — never by substring
  matching, where "rate" inside "accurate" proves things.
- **Identity binds the evidence.** Records must carry the expected
  preset/registry identity and the cct_router mode, and the
  provisional→reconciled join matches BOTH ``packet_id`` and
  ``packet_digest`` — increment C's complete work identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from pathlib import Path

from .injection import events_for_task, preset_digest
from .record_check import load_schema, validate
from .redaction import secret_values_from_registry, write_run_records
from .scenario_config import ScenarioConfig

#: The closed leg vocabulary, in the arc's proof order.
ARC_LEGS = (
    "initial_preferred",
    "failover",
    "tier2_provisional",
    "recovery_selection",
    "reconciliation",
    "tier1_only_refusal",
)

#: The closed circuit states that prove the preferred profile was
#: UNAVAILABLE PENDING RECOVERY at the failover boundary: cooling, or
#: expired-and-awaiting-canary (increment D makes probe_due/probing
#: non-selectable exactly like cooldown). Structured states only.
_UNAVAILABLE_STATE_RE = re.compile(r"^(pool:)?(cooldown|probe_due|probing)$")

_ROUTE_CLASS_TIER1_ONLY = "tier1_only"


class ArcIncomplete(AssertionError):
    """The durable evidence does not prove the complete arc."""


class RecordInvalid(ValueError):
    """A record is not bound to the run's identity or required shape.

    Identity failures REFUSE verification rather than failing a leg: a
    record from another preset, registry, or execution mode is not
    weak evidence — it is not evidence for this run at all.
    """


@dataclass(frozen=True)
class LegProof:
    leg: str
    satisfied: bool
    #: Global indices into the record sequence — addressable evidence.
    evidence: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class TrialReport:
    trial: int
    legs: tuple[LegProof, ...]

    @property
    def complete(self) -> bool:
        return all(l.satisfied for l in self.legs)

    def missing(self) -> list[LegProof]:
        return [l for l in self.legs if not l.satisfied]


@dataclass(frozen=True)
class ArcReport:
    trials: tuple[TrialReport, ...]

    @property
    def complete(self) -> bool:
        return bool(self.trials) and all(t.complete for t in self.trials)

    def missing(self) -> list[tuple[int, LegProof]]:
        return [(t.trial, l) for t in self.trials for l in t.missing()]


def _independent(tier2: Mapping[str, Any], rc: Mapping[str, Any]) -> bool:
    """Increment C's reviewer-independence predicate, mirrored exactly:
    missing identity is unevaluable (never independent); provider
    equality is the primary collision; model equality is the
    conservative secondary collision even across distinct providers."""
    bprov, bmodel = tier2.get("builder_provider"), tier2.get("builder_model")
    rprov, rmodel = rc.get("reconciler_provider"), rc.get("reconciler_model")
    if not (bprov and bmodel and rprov and rmodel):
        return False
    if rprov == bprov:
        return False
    if rmodel == bmodel:
        return False
    return True


def _decisions(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list(record.get("routing_decisions") or [])


def _is_ordinary(record: Mapping[str, Any]) -> bool:
    return record.get("reconciliation") is None


def _check_identity(
    records: Sequence[Mapping[str, Any]],
    expected_preset_digest: Optional[str],
    expected_registry_digest: Optional[str],
) -> None:
    # The FULL persisted contract, enforced at runtime: a record the
    # routing-run schema rejects is not weak evidence, it is not
    # evidence. Test-only schema validation protects nothing in
    # production; this does.
    schema = load_schema("routing-run")
    for i, r in enumerate(records):
        errors = validate(r, schema)
        if errors:
            raise RecordInvalid(
                f"record {i} violates routing-run.schema.json: {errors[:5]}"
            )
    registry_digests = set()
    for i, r in enumerate(records):
        for key in ("task_id", "trial", "mode", "routing_decisions",
                    "preset_digest", "registry_digest"):
            if key not in r:
                raise RecordInvalid(f"record {i} is missing {key!r}")
        if r["mode"] != "cct_router":
            raise RecordInvalid(
                f"record {i} has mode {r['mode']!r} — only live cct_router "
                f"records are arc evidence; matrix-sweep cells prove no arc"
            )
        if not isinstance(r["trial"], int) or isinstance(r["trial"], bool):
            raise RecordInvalid(f"record {i} trial is not an integer")
        if expected_preset_digest is not None and r["preset_digest"] != expected_preset_digest:
            raise RecordInvalid(
                f"record {i} carries preset digest {r['preset_digest']!r}, "
                f"expected {expected_preset_digest!r} — evidence from another "
                f"preset is not evidence for this run"
            )
        registry_digests.add(r["registry_digest"])
    if expected_registry_digest is not None:
        stray = registry_digests - {expected_registry_digest}
        if stray:
            raise RecordInvalid(f"records carry foreign registry digests {sorted(stray)}")
    elif len(registry_digests) > 1:
        raise RecordInvalid(
            f"records mix registry digests {sorted(registry_digests)} — one "
            f"run routes under one registry"
        )


def _verify_trial(
    trial: int,
    indexed: list[tuple[int, Mapping[str, Any]]],
    *,
    preferred_profile: str,
    tier2_profiles: frozenset[str],
    tier1_only_tasks: Sequence[str],
) -> TrialReport:
    legs: list[LegProof] = []

    def _leg(name: str, idx: Optional[int] | tuple, ok_reason: str, fail_reason: str):
        ok = idx is not None and idx != ()
        evidence = idx if isinstance(idx, tuple) else ((idx,) if ok else ())
        legs.append(LegProof(name, ok, evidence, ok_reason if ok else fail_reason))

    # 1. initial preferred: an ORDINARY decision selecting the preferred
    # profile — the arc starts on it, or there is nothing to fail over from.
    initial: Optional[int] = None
    for pos, (gi, r) in enumerate(indexed):
        if _is_ordinary(r) and any(
            d.get("selected") == preferred_profile for d in _decisions(r)
        ):
            initial = pos
            break
    _leg(
        "initial_preferred",
        indexed[initial][0] if initial is not None else None,
        "an ordinary decision initially selected the preferred profile",
        f"no ordinary decision selects '{preferred_profile}' before the failover",
    )

    # 2. failover AFTER the initial selection: preferred rejected in the
    # closed cooldown state, another profile selected.
    failover: Optional[int] = None
    if initial is not None:
        for pos in range(initial + 1, len(indexed)):
            _gi, r = indexed[pos]
            for d in _decisions(r):
                rejected = any(
                    c.get("id") == preferred_profile
                    and c.get("verdict") == "rejected"
                    and _UNAVAILABLE_STATE_RE.match(c.get("state") or "")
                    for c in d.get("considered") or []
                )
                if rejected and d.get("selected") not in (None, preferred_profile):
                    failover = pos
                    break
            if failover is not None:
                break
    _leg(
        "failover",
        indexed[failover][0] if failover is not None else None,
        "after the initial selection, the preferred profile was rejected in a "
        "closed unavailable-pending-recovery state and another profile was "
        "selected",
        "no post-initial decision rejects the preferred profile in a closed "
        "unavailability STATE (cooldown/probe_due/probing) while selecting "
        "another — prose reasons prove nothing",
    )

    # 3-5. provisional -> recovery -> reconciliation, one ordered chain
    # joined on the COMPLETE packet identity.
    prov = rec = recon = None
    if failover is not None:
        for p_pos in range(failover + 1, len(indexed)):
            _gi, pr = indexed[p_pos]
            tier2 = pr.get("tier2") or {}
            pid, pdig = tier2.get("packet_id"), tier2.get("packet_digest")
            if not (tier2.get("delegated") and pid and pdig):
                continue
            # The EXECUTING tier is part of the proof: delegated + a
            # packet join without the builder's tier would let
            # contradictory evidence pass.
            if tier2.get("builder_tier") != "tier2":
                continue
            if tier2.get("builder_id") not in tier2_profiles:
                continue
            if not any(
                d.get("provisional_outcome") == "verified_provisional"
                for d in _decisions(pr)
            ):
                continue
            for r_pos in range(p_pos + 1, len(indexed)):
                _gi2, rr = indexed[r_pos]
                if not (_is_ordinary(rr) and any(
                    d.get("selected") == preferred_profile for d in _decisions(rr)
                )):
                    continue
                for c_pos in range(r_pos + 1, len(indexed)):
                    _gi3, cr = indexed[c_pos]
                    rc = cr.get("reconciliation")
                    if (
                        rc
                        and rc.get("outcome") == "reconciled"
                        and rc.get("packet_id") == pid
                        and rc.get("packet_digest") == pdig
                        # #109: TIER-1 reconciliation, by identity —
                        # and INDEPENDENT, by increment C's frozen
                        # fail-closed predicate, verified from the
                        # records rather than trusted from the
                        # implementation under evaluation: builder and
                        # reconciler identities must BOTH be known
                        # (unevaluable is never successful), providers
                        # must differ (primary collision), and models
                        # must differ (conservative secondary, even
                        # across distinct providers).
                        and rc.get("reconciler_tier") == "tier1"
                        and rc.get("reconciler_id")
                        and _independent(tier2, rc)
                    ):
                        prov, rec, recon = p_pos, r_pos, c_pos
                        break
                if prov is not None:
                    break
            if prov is not None:
                break
    _leg(
        "tier2_provisional",
        indexed[prov][0] if prov is not None else None,
        "a delegated record after the failover carries the packet identity, a "
        "tier2 builder, and verified_provisional",
        "no ordered witness: no post-failover delegated record with complete "
        "packet identity, a TIER-2 builder identity, and verified_provisional "
        "that a later recovery and tier-1 reconciliation complete",
    )
    _leg(
        "recovery_selection",
        indexed[rec][0] if rec is not None else None,
        "after the provisional work, an ordinary decision selected the "
        "preferred profile at a task boundary",
        "no ordinary decision after the provisional work SELECTS the preferred "
        "profile — a passing probe alone proves availability, not selection",
    )
    _leg(
        "reconciliation",
        (indexed[prov][0], indexed[recon][0]) if recon is not None else (),
        "the SAME packet (id and digest) that became verified_provisional was "
        "reconciled after the recovery by an identified, INDEPENDENT tier1 "
        "reconciler (distinct provider and model, both identities known)",
        "no reconciliation record after the recovery joins the provisional "
        "packet on BOTH packet_id and packet_digest with an identified tier1 "
        "reconciler whose independence is established — unknown identities, a "
        "shared provider, or a shared model are never a successful witness",
    )

    # 6. tier1-only refusal: structural route_class + rejected tier2
    # candidate, per declared control task, within this trial.
    refusal_evidence: list[int] = []
    refusal_failures: list[str] = []
    for task in tier1_only_tasks:
        task_records = [(gi, r) for gi, r in indexed if r.get("task_id") == task]
        if not task_records:
            refusal_failures.append(f"task '{task}' has no records in trial {trial}")
            continue
        # A NEGATIVE STREAM INVARIANT, not merely an existential
        # witness: the control is the experiment's control, so ANY
        # Tier-2 execution evidence anywhere in the task's records
        # contaminates it — a later valid refusal proves nothing about
        # what already ran.
        contaminated = None
        for gi, r in task_records:
            tier2 = r.get("tier2") or {}
            if tier2.get("delegated") or tier2.get("builder_tier") == "tier2":
                contaminated = (gi, "a Tier-2 delegation/provisional record")
                break
            for d in _decisions(r):
                if d.get("selected") in tier2_profiles:
                    contaminated = (gi, f"a decision selecting Tier-2 '{d.get('selected')}'")
                    break
                if d.get("provisional_outcome") == "verified_provisional":
                    contaminated = (gi, "a verified_provisional outcome")
                    break
            if contaminated:
                break
        if contaminated:
            refusal_failures.append(
                f"task '{task}' is a CONTAMINATED control: record "
                f"{contaminated[0]} carries {contaminated[1]} — a control that "
                f"executed Tier-2 invalidates the comparison regardless of any "
                f"refusal it also shows"
            )
            continue
        proven = False
        for gi, r in task_records:
            for d in _decisions(r):
                if d.get("route_class") != _ROUTE_CLASS_TIER1_ONLY:
                    continue
                if any(
                    c.get("id") in tier2_profiles and c.get("verdict") == "rejected"
                    for c in d.get("considered") or []
                ):
                    refusal_evidence.append(gi)
                    proven = True
                    break
            if proven:
                break
        if not proven:
            refusal_failures.append(
                f"task '{task}' never shows route_class tier1_only rejecting a "
                f"Tier-2 candidate — it may merely have ENDED UP on Tier-1"
            )
    legs.append(
        LegProof(
            "tier1_only_refusal",
            not refusal_failures and bool(tier1_only_tasks),
            tuple(refusal_evidence),
            "every negative control shows route_class tier1_only with the "
            "Tier-2 candidate rejected"
            if tier1_only_tasks and not refusal_failures
            else ("; ".join(refusal_failures) or "no tier1_only negative controls declared"),
        )
    )
    return TrialReport(trial, tuple(legs))


def verify_arc(
    records: Sequence[Mapping[str, Any]],
    *,
    preferred_profile: str,
    tier2_profiles: frozenset[str] | set[str],
    tier1_only_tasks: Sequence[str],
    expected_trials: int,
    expected_preset_digest: Optional[str] = None,
    expected_registry_digest: Optional[str] = None,
) -> ArcReport:
    """Prove every leg of the arc, per declared trial, in order.

    ``records`` is the execution-ordered sequence of routing-run
    records. Identity is checked first (RecordInvalid); then EVERY
    declared trial must independently carry the ordered witness.
    """
    _check_identity(records, expected_preset_digest, expected_registry_digest)

    by_trial: dict[int, list[tuple[int, Mapping[str, Any]]]] = {}
    for i, r in enumerate(records):
        by_trial.setdefault(r["trial"], []).append((i, r))

    undeclared = sorted(t for t in by_trial if t not in range(expected_trials))
    if undeclared:
        raise RecordInvalid(f"records carry undeclared trial indices {undeclared}")

    reports = []
    tier2_frozen = frozenset(tier2_profiles)
    for trial in range(expected_trials):
        indexed = by_trial.get(trial, [])
        if not indexed:
            reports.append(
                TrialReport(
                    trial,
                    tuple(
                        LegProof(leg, False, (), f"trial {trial} has no records")
                        for leg in ARC_LEGS
                    ),
                )
            )
            continue
        reports.append(
            _verify_trial(
                trial,
                indexed,
                preferred_profile=preferred_profile,
                tier2_profiles=tier2_frozen,
                tier1_only_tasks=tier1_only_tasks,
            )
        )
    return ArcReport(tuple(reports))


def run_hybrid_scenario(
    config: ScenarioConfig,
    runner,
    *,
    preferred_profile: str,
    tier2_profiles: frozenset[str] | set[str],
    delegate_harness_cmd: Optional[str] = None,
    reconcile_harness_cmd: Optional[str] = None,
    ordinary_harness_cmd: Optional[str] = None,
    max_tick_pumps: int = 8,
) -> "ScenarioArtifact":
    """THE production orchestration entrypoint for the hybrid preset.

    Walks the preset's declared task order and drives the #109 §12 arc
    through the production runner (SupervisorRunner or an equivalent
    protocol): ordinary tasks through ``run_task``, ``delegate_tasks``
    through the real --delegate flow, then — at the first task boundary
    AFTER the trial's delegated work, which is exactly where §12 places
    recovery — pumps ``cct routing tick`` until no probe is due, and
    finally reconciles every pending packet through the real
    --reconcile flow. Nothing here marks legs visited: the artifact's
    proof is verify_arc over the harvested records, bound to this
    preset's digest and to the registry digest computed FROM the
    registry file the runner executed under.
    """
    if getattr(runner, "preset_digest", None) != preset_digest(config):
        raise RecordInvalid(
            "the runner's preset digest does not match this config — the "
            "records it stamps would claim a different preset"
        )
    if getattr(runner, "benchmark_id", None) != config.benchmark:
        raise RecordInvalid(
            f"the config declares benchmark {config.benchmark!r} but the "
            f"runner executes {getattr(runner, 'benchmark_id', None)!r} — the "
            f"declared workload must be the one measured"
        )
    # The cct_router arm NAMES the registry this scenario routes under;
    # the runner must execute exactly that document. Without this
    # check, a config naming registry A with a runner using registry B
    # would honestly hash B — and silently measure the wrong policy.
    from pathlib import Path as _Path

    from .scenario_config import resolve_registry_path

    arm_registry = next(
        (a.registry for a in config.arms if a.kind == "cct_router"), None
    )
    if arm_registry is None or (
        resolve_registry_path(arm_registry, config.source_dir)
        != _Path(runner.registry_path).resolve()
    ):
        raise RecordInvalid(
            f"the cct_router arm names registry {arm_registry!r} but the "
            f"runner executes under {str(runner.registry_path)!r} — the "
            f"configured policy must be the one measured"
        )
    from .supervisor_runner import registry_digest_of

    expected_registry = registry_digest_of(runner.registry_path)
    tasks = config.task_filter or []
    seeds = config.trial_seeds or list(range(1, config.trials + 1))
    records: list[Mapping[str, Any]] = []
    for trial, seed in enumerate(seeds):
        # A CLEAN context per trial: same starting conditions for every
        # trial, no circuit-state or worktree contamination across them.
        trial_runner = runner.for_trial(trial)
        pending: list[str] = []
        pumped = False
        for task_index, task in enumerate(tasks):
            scheduled = events_for_task(config.event_stream, task_index)
            if task in config.delegate_tasks:
                if scheduled:
                    raise RecordInvalid(
                        f"events scheduled onto delegated task {task!r} — "
                        f"config validation should have refused this preset"
                    )
                records.append(
                    trial_runner.delegate_task(task, trial, seed, delegate_harness_cmd)
                )
                pending.append(task)
                continue
            if pending and not pumped:
                # Recovery at the task boundary AFTER the Tier-2 leg:
                # drain due probes (bounded, no sleeping — due-ness is
                # event-driven via the provider's reset instant).
                for _ in range(max_tick_pumps):
                    out = trial_runner.tick_probe()
                    if "0 due profile(s) processed" in out:
                        break
                pumped = True
            records.extend(
                trial_runner.run_task(
                    task, trial, seed, scheduled, harness_cmd=ordinary_harness_cmd
                )
            )
        if pending and not pumped:
            for _ in range(max_tick_pumps):
                out = trial_runner.tick_probe()
                if "0 due profile(s) processed" in out:
                    break
        for task in pending:
            records.append(
                trial_runner.reconcile_task(task, trial, seed, reconcile_harness_cmd)
            )
    arc = verify_arc(
        records,
        preferred_profile=preferred_profile,
        tier2_profiles=frozenset(tier2_profiles),
        tier1_only_tasks=config.tier1_only_tasks,
        expected_trials=len(seeds),
        expected_preset_digest=preset_digest(config),
        expected_registry_digest=expected_registry,
    )
    if not arc.complete:
        missing = "; ".join(f"trial {t}: {l.leg} ({l.reason})" for t, l in arc.missing())
        raise ArcIncomplete(
            f"the durable records do not prove the complete arc — {missing}"
        )
    # FR-E1-9: the artifact is PUBLISHED through the one redacting
    # persistence gate as part of the production entrypoint itself —
    # publication is never an opt-in a caller can forget, and the raw
    # in-memory records reach disk no other way. The secret set is
    # resolved INTERNALLY from the executed registry (the runner's
    # resolver when it has one; the registry's credential_env
    # references otherwise), so the artifact's redaction guarantee
    # does not depend on any caller remembering to pass it.
    if hasattr(runner, "_secret_values"):
        secrets = runner._secret_values()
    else:
        secrets = secret_values_from_registry(runner.registry_path)
    artifact_path = write_run_records(
        records,
        Path(runner.ledger_root) / "routing-runs.jsonl",
        evidence_root=Path(runner.ledger_root),
        secret_values=secrets,
    )
    return ScenarioArtifact(
        preset_digest=preset_digest(config),
        records=tuple(records),
        arc=arc,
        artifact_path=artifact_path,
    )


@dataclass(frozen=True)
class ScenarioArtifact:
    preset_digest: str
    records: tuple[Mapping[str, Any], ...]
    arc: ArcReport
    #: The published, redacted durable artifact. Set by the production
    #: entrypoint (run_hybrid_scenario); None only for the generic
    #: run_scenario test driver, which owns no ledger to publish into.
    artifact_path: "Path | None" = None


def run_scenario(
    config: ScenarioConfig,
    run_task: Callable[[str, int, int, list], Sequence[Mapping[str, Any]]],
    *,
    preferred_profile: str,
    tier2_profiles: frozenset[str] | set[str],
    expected_registry_digest: Optional[str] = None,
) -> ScenarioArtifact:
    """Drive the arc and verify it from what was durably recorded.

    ``run_task(task, trial, seed, events)`` executes one task under the
    live router with that task's scheduled events (``events_for_task``
    is the boundary) and returns the routing-run records it durably
    wrote. The production implementation is
    ``supervisor_runner.SupervisorRunner`` — it shells to the real
    cooldown supervisor through the T2 replay seams and harvests the
    records from its durable outputs; tests may stub it, but the
    verification path is identical either way.

    The artifact's arc report comes from ``verify_arc`` over the
    returned records ONLY, per declared trial, bound to this preset's
    digest. If any trial's arc is incomplete the scenario FAILS — a
    partial arc is never reported as a run.
    """
    tasks = config.task_filter or []
    seeds = config.trial_seeds or list(range(1, config.trials + 1))
    digest = preset_digest(config)
    records: list[Mapping[str, Any]] = []
    for trial, seed in enumerate(seeds):
        for task_index, task in enumerate(tasks):
            scheduled = events_for_task(config.event_stream, task_index)
            expected_events = [
                {"at_task_index": e.at_task_index, "outcome": e.outcome,
                 "reset_at": e.reset_at, "retry_after_sec": e.retry_after_sec}
                for e in scheduled
            ]
            returned = run_task(task, trial, seed, scheduled)
            # BIND every returned record to THIS invocation: one
            # callback returning the whole cross-task arc during t0
            # must never make the later invocations no-ops.
            for r in returned:
                claimed = (r.get("task_id"), r.get("trial"), r.get("trial_seed"))
                if claimed != (task, trial, seed):
                    raise RecordInvalid(
                        f"run_task({task!r}, trial {trial}, seed {seed}) returned "
                        f"a record claiming {claimed} — records must be bound to "
                        f"the invocation that produced them"
                    )
                if list(r.get("injected_events") or []) != expected_events:
                    raise RecordInvalid(
                        f"run_task({task!r}, trial {trial}) returned a record "
                        f"whose injected_events do not match the events "
                        f"scheduled for this task — event provenance must be "
                        f"recorded exactly"
                    )
            records.extend(returned)
    arc = verify_arc(
        records,
        preferred_profile=preferred_profile,
        tier2_profiles=frozenset(tier2_profiles),
        tier1_only_tasks=config.tier1_only_tasks,
        expected_trials=len(seeds),
        expected_preset_digest=digest,
        expected_registry_digest=expected_registry_digest,
    )
    if not arc.complete:
        missing = "; ".join(
            f"trial {t}: {l.leg} ({l.reason})" for t, l in arc.missing()
        )
        raise ArcIncomplete(
            f"the durable records do not prove the complete arc — {missing}"
        )
    return ScenarioArtifact(
        preset_digest=digest,
        records=tuple(records),
        arc=arc,
    )
