"""Executable validation for routing-scenario configs (E1 T1).

The JSON schema (``compare-config.schema.json``) documents the contract;
THIS module enforces it. ``compare.py`` refuses any config that carries
``scenario``/``arms`` (and refuses a mixed one with its own error), then
directs it here. The scenario driver (T4) will load configs through
:func:`load_scenario_config` only, so a shape this module rejects can
never execute.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

MEASURED_BASIS = "measured"

SCENARIO_HYBRID_ROUTING = "hybrid-routing"
_SCENARIOS = (SCENARIO_HYBRID_ROUTING,)

#: The closed arm vocabulary. Four are DERIVED from the outcome matrix;
#: only cct_router executes live.
ARM_KINDS = ("always_best", "always_cheapest", "oracle", "oracle_budget", "cct_router")
DERIVED_ARM_KINDS = ("always_best", "always_cheapest", "oracle", "oracle_budget")

#: FR-E1-3: a comparison without its complete control set is the
#: specific failure mode this increment exists to prevent, so the
#: parser refuses it at load time rather than letting the reporter
#: discover it later. Each mandatory kind appears exactly once;
#: oracle_budget is the only optional kind.
MANDATORY_ARM_KINDS = ("always_best", "always_cheapest", "oracle", "cct_router")

#: Closed key sets. The schema closes these objects
#: (additionalProperties: false); a parser that silently ignored
#: unknown keys would accept `trial_seedz` and run with default seeds —
#: fail-open. T4 trusts this parser, so it must be at least as strict
#: as the schema it enforces.
_TOP_LEVEL_KEYS = frozenset(
    {"benchmark", "scenario", "arms", "cost_basis", "trials", "trial_seeds",
     "event_stream", "budget_ceiling_usd", "task", "tier1_only_tasks",
     "delegate_tasks"}
)
_ARM_KEYS = frozenset({"kind", "name", "registry"})
_EVENT_KEYS = frozenset({"at_task_index", "outcome", "reset_at", "retry_after_sec"})

#: One declared basis per comparison; an unversioned "estimated" is
#: refused so two price tables are never compared against each other.
_COST_BASIS_RE = re.compile(r"^(measured|estimated@[A-Za-z0-9._-]+)$")

_EVENT_OUTCOMES = ("usage_limit", "quota_exhausted", "auth_failure", "server_error", "timeout", "success")


class ScenarioConfigError(ValueError):
    """Raised when a routing-scenario config is malformed."""


@dataclass(frozen=True)
class Arm:
    kind: str
    name: str
    registry: Optional[str] = None


@dataclass(frozen=True)
class InjectedEvent:
    at_task_index: int
    outcome: str
    reset_at: Optional[str] = None
    retry_after_sec: Optional[int] = None


@dataclass(frozen=True)
class ScenarioConfig:
    benchmark: str
    scenario: str
    arms: list[Arm]
    cost_basis: str = MEASURED_BASIS
    trials: int = 1
    trial_seeds: Optional[list[int]] = None
    event_stream: list[InjectedEvent] = field(default_factory=list)
    budget_ceiling_usd: Optional[float] = None
    task_filter: Optional[list[str]] = None
    #: The #109 Tier-1-only negative controls. The arc verifier
    #: requires these tasks' records to show Tier-2 REJECTED with the
    #: route reason — absence is not refusal.
    tier1_only_tasks: list[str] = field(default_factory=list)
    #: Tasks delegated as bounded Tier-2 packets — the arc's Tier-2 leg.
    delegate_tasks: list[str] = field(default_factory=list)
    #: The directory the config was loaded from — the base every
    #: relative path in the config resolves against, so a preset means
    #: the same thing regardless of the caller's working directory.
    source_dir: Optional[Path] = None


def load_scenario_config(path: Path) -> ScenarioConfig:
    """Load and validate a scenario config from disk."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScenarioConfigError(f"{path}: invalid JSON: {exc}") from exc
    return validate_scenario_config(
        raw, source=str(path), source_dir=Path(path).resolve().parent
    )


def resolve_registry_path(
    arm_registry: str, source_dir: Optional[Path]
) -> Path:
    """Resolve the cct_router arm's registry deterministically.

    ``~`` expands (the documented operator location); an absolute path
    stands as-is; a relative path resolves against the CONFIG's source
    directory — never the caller's cwd, which would let one preset bind
    different policies depending on where the command started.
    """
    candidate = Path(arm_registry).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    if source_dir is None:
        raise ScenarioConfigError(
            f"registry path {arm_registry!r} is relative but the config has "
            f"no source directory to resolve it against — load the config "
            f"from disk or name an absolute/operator path"
        )
    return (Path(source_dir) / candidate).resolve()


def validate_scenario_config(
    raw: Any, *, source: str = "<config>", source_dir: Optional[Path] = None
) -> ScenarioConfig:
    if not isinstance(raw, Mapping):
        raise ScenarioConfigError(f"{source}: top-level value must be a JSON object")

    # The axes are mutually exclusive, and this module owns one of them.
    if "candidates" in raw:
        raise ScenarioConfigError(
            f"{source}: declares 'candidates' alongside a scenario comparison — "
            f"the two comparison axes cannot share one config"
        )

    unknown = set(raw) - _TOP_LEVEL_KEYS - {"candidates"}
    if unknown:
        raise ScenarioConfigError(
            f"{source}: unknown top-level key(s) {sorted(unknown)} — the config "
            f"object is closed; a misspelled key silently ignored is fail-open"
        )

    benchmark = raw.get("benchmark")
    if not isinstance(benchmark, str) or not benchmark:
        raise ScenarioConfigError(f"{source}: 'benchmark' must be a non-empty string")

    scenario = raw.get("scenario")
    if scenario not in _SCENARIOS:
        raise ScenarioConfigError(
            f"{source}: 'scenario' must be one of {list(_SCENARIOS)}, got {scenario!r}"
        )

    arms = _validate_arms(raw.get("arms"), source)
    cost_basis = _validate_cost_basis(raw.get("cost_basis"), source)
    trials, trial_seeds = _validate_trials(raw, source)
    events = _validate_event_stream(raw.get("event_stream"), source)
    ceiling = _validate_ceiling(raw, arms, source)
    task_filter = _validate_task_filter(raw.get("task"), source)
    tier1_only = _validate_tier1_only(raw.get("tier1_only_tasks"), task_filter, source)
    delegate = _validate_delegate_tasks(
        raw.get("delegate_tasks"), task_filter, tier1_only, source
    )
    # Every event must land on a DECLARED task: an out-of-range index
    # would join the preset digest yet reach no execution and no
    # evidence — a phantom that silently weakens the scenario. And
    # provider events are the TIER-1 seam's vocabulary; the delegation
    # seam runs a bounded packet child, so an event scheduled onto a
    # delegated task is refused rather than dropped.
    if events and task_filter is None:
        raise ScenarioConfigError(
            f"{source}: 'event_stream' requires a declared 'task' list — an "
            f"event index has no meaning without the task sequence it points "
            f"into"
        )
    if task_filter:
        for e in events:
            if e.at_task_index >= len(task_filter):
                raise ScenarioConfigError(
                    f"{source}: event_stream index {e.at_task_index} is outside "
                    f"the declared task sequence (len {len(task_filter)}) — a "
                    f"phantom event would join the digest but reach nothing"
                )
            if task_filter[e.at_task_index] in delegate:
                raise ScenarioConfigError(
                    f"{source}: event_stream schedules '{e.outcome}' onto "
                    f"'{task_filter[e.at_task_index]}', which is a delegated "
                    f"task — provider events cannot be applied through the "
                    f"delegation seam"
                )

    return ScenarioConfig(
        benchmark=benchmark,
        scenario=scenario,
        arms=arms,
        cost_basis=cost_basis,
        trials=trials,
        trial_seeds=trial_seeds,
        event_stream=events,
        budget_ceiling_usd=ceiling,
        task_filter=task_filter,
        tier1_only_tasks=tier1_only,
        delegate_tasks=delegate,
        source_dir=source_dir,
    )


def _validate_arms(raw_arms: Any, source: str) -> list[Arm]:
    if not isinstance(raw_arms, list) or not raw_arms:
        raise ScenarioConfigError(f"{source}: 'arms' must be a non-empty list")

    arms: list[Arm] = []
    seen_names: set[str] = set()
    seen_kinds: list[str] = []
    for i, a in enumerate(raw_arms):
        prefix = f"{source}: arms[{i}]"
        if not isinstance(a, Mapping):
            raise ScenarioConfigError(f"{prefix}: must be a JSON object")
        unknown = set(a) - _ARM_KEYS
        if unknown:
            raise ScenarioConfigError(
                f"{prefix}: unknown key(s) {sorted(unknown)} — arm objects are closed"
            )
        kind = a.get("kind")
        if kind not in ARM_KINDS:
            raise ScenarioConfigError(
                f"{prefix}.kind: must be one of {list(ARM_KINDS)}, got {kind!r}"
            )
        registry = a.get("registry")
        if registry is not None and (not isinstance(registry, str) or not registry):
            raise ScenarioConfigError(f"{prefix}.registry: must be a non-empty string")
        if kind == "cct_router" and registry is None:
            # The live arm has to say which registry it routes under —
            # its whole result is a function of that document.
            raise ScenarioConfigError(f"{prefix}: cct_router requires 'registry'")
        name = a.get("name", kind)
        if not isinstance(name, str) or not name:
            raise ScenarioConfigError(f"{prefix}.name: must be a non-empty string")
        if name in seen_names:
            raise ScenarioConfigError(f"{prefix}.name: duplicate arm name {name!r}")
        seen_names.add(name)
        seen_kinds.append(kind)
        arms.append(Arm(kind=kind, name=name, registry=registry))

    # FR-E1-3: the complete control set, each mandatory kind exactly once.
    for kind in MANDATORY_ARM_KINDS:
        count = seen_kinds.count(kind)
        if count != 1:
            raise ScenarioConfigError(
                f"{source}: arm kind '{kind}' must appear exactly once "
                f"(found {count}) — a router figure without its complete "
                f"control set is uninterpretable, so the parser refuses it"
            )
    if seen_kinds.count("oracle_budget") > 1:
        raise ScenarioConfigError(
            f"{source}: at most one oracle_budget arm is allowed"
        )
    return arms


def _validate_cost_basis(raw: Any, source: str) -> str:
    if raw is None:
        # One declared basis per comparison is normative (§Cost and
        # reporting contract); with none declared, every downstream
        # cost use would have to guess, which is exactly the mixing
        # this field exists to prevent.
        raise ScenarioConfigError(
            f"{source}: 'cost_basis' is required — 'measured' or "
            f"'estimated@<price-table-version>'"
        )
    if not isinstance(raw, str) or not _COST_BASIS_RE.match(raw):
        raise ScenarioConfigError(
            f"{source}: 'cost_basis' must be 'measured' or "
            f"'estimated@<price-table-version>', got {raw!r} — a bare "
            f"'estimated' would let two price tables be compared"
        )
    return raw


def _validate_trials(raw: Mapping[str, Any], source: str) -> tuple[int, Optional[list[int]]]:
    trials = raw.get("trials", 1)
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise ScenarioConfigError(f"{source}: 'trials' must be a positive integer")

    seeds = raw.get("trial_seeds")
    if seeds is None:
        return trials, None
    if not isinstance(seeds, list) or not all(
        isinstance(s, int) and not isinstance(s, bool) for s in seeds
    ):
        raise ScenarioConfigError(f"{source}: 'trial_seeds' must be a list of integers")
    if len(seeds) != trials:
        # Seeds are paired across arms per trial index; a length mismatch
        # means some trial has no seed or a seed pairs with nothing.
        raise ScenarioConfigError(
            f"{source}: 'trial_seeds' length ({len(seeds)}) must equal 'trials' ({trials})"
        )
    return trials, list(seeds)


def _validate_event_stream(raw: Any, source: str) -> list[InjectedEvent]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ScenarioConfigError(f"{source}: 'event_stream' must be a list")
    events: list[InjectedEvent] = []
    for i, e in enumerate(raw):
        prefix = f"{source}: event_stream[{i}]"
        if not isinstance(e, Mapping):
            raise ScenarioConfigError(f"{prefix}: must be a JSON object")
        unknown = set(e) - _EVENT_KEYS
        if unknown:
            raise ScenarioConfigError(
                f"{prefix}: unknown key(s) {sorted(unknown)} — event objects are closed"
            )
        idx = e.get("at_task_index")
        if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0:
            raise ScenarioConfigError(f"{prefix}.at_task_index: must be an integer >= 0")
        outcome = e.get("outcome")
        if outcome not in _EVENT_OUTCOMES:
            raise ScenarioConfigError(
                f"{prefix}.outcome: must be one of {list(_EVENT_OUTCOMES)}, got {outcome!r}"
            )
        reset_at = e.get("reset_at")
        if reset_at is not None and (not isinstance(reset_at, str) or not reset_at):
            raise ScenarioConfigError(f"{prefix}.reset_at: must be a non-empty string or null")
        retry = e.get("retry_after_sec")
        if retry is not None and (
            not isinstance(retry, int) or isinstance(retry, bool) or retry < 0
        ):
            raise ScenarioConfigError(f"{prefix}.retry_after_sec: must be an integer >= 0 or null")
        events.append(
            InjectedEvent(
                at_task_index=idx, outcome=outcome, reset_at=reset_at, retry_after_sec=retry
            )
        )
    return events


def _validate_ceiling(raw: Mapping[str, Any], arms: list[Arm], source: str) -> Optional[float]:
    ceiling = raw.get("budget_ceiling_usd")
    has_budget_arm = any(a.kind == "oracle_budget" for a in arms)
    if ceiling is None:
        if has_budget_arm:
            raise ScenarioConfigError(
                f"{source}: an oracle_budget arm requires 'budget_ceiling_usd' — "
                f"the ceiling is per-cell and must be declared, never implied"
            )
        return None
    if (
        isinstance(ceiling, bool)
        or not isinstance(ceiling, (int, float))
        or not math.isfinite(float(ceiling))
        or ceiling < 0
    ):
        raise ScenarioConfigError(
            f"{source}: 'budget_ceiling_usd' must be a finite number >= 0"
        )
    if not has_budget_arm:
        raise ScenarioConfigError(
            f"{source}: 'budget_ceiling_usd' is set but no oracle_budget arm is "
            f"declared — a ceiling nothing enforces is never accepted as inert "
            f"configuration"
        )
    return float(ceiling)


def _validate_tier1_only(
    raw: Any, task_filter: Optional[list[str]], source: str
) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(t, str) and t for t in raw):
        raise ScenarioConfigError(
            f"{source}: 'tier1_only_tasks' must be a list of non-empty strings"
        )
    if len(set(raw)) != len(raw):
        raise ScenarioConfigError(f"{source}: 'tier1_only_tasks' contains duplicates")
    if task_filter is not None:
        stray = [t for t in raw if t not in task_filter]
        if stray:
            raise ScenarioConfigError(
                f"{source}: 'tier1_only_tasks' {stray} are not in 'task' — a "
                f"negative control that never runs proves nothing"
            )
    return list(raw)


def _validate_delegate_tasks(
    raw: Any, task_filter: Optional[list[str]], tier1_only: list[str], source: str
) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(t, str) and t for t in raw):
        raise ScenarioConfigError(
            f"{source}: 'delegate_tasks' must be a list of non-empty strings"
        )
    if len(set(raw)) != len(raw):
        raise ScenarioConfigError(f"{source}: 'delegate_tasks' contains duplicates")
    if task_filter is not None:
        stray = [t for t in raw if t not in task_filter]
        if stray:
            raise ScenarioConfigError(
                f"{source}: 'delegate_tasks' {stray} are not in 'task'"
            )
    overlap = [t for t in raw if t in tier1_only]
    if overlap:
        raise ScenarioConfigError(
            f"{source}: {overlap} cannot be both delegate_tasks and "
            f"tier1_only_tasks — a negative control that delegates proves the "
            f"opposite of what it controls for"
        )
    return list(raw)


def _validate_task_filter(raw: Any, source: str) -> Optional[list[str]]:
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(t, str) and t for t in raw):
        raise ScenarioConfigError(f"{source}: 'task' must be a list of non-empty strings")
    return list(raw)
