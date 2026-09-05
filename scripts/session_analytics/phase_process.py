# session_analytics.phase_process — descriptive phase-process metrics (#301).
#
# Pure functions over a recorded phase timeline: no DB, no I/O, so the
# rules are unit-testable in isolation (the shape cost.py already uses).
#
# THIS MODULE DELIBERATELY PRODUCES NO CONFORMANCE SCORE. #65's E3 asks
# for conformance scoring and stays OPEN; this is groundwork, not that.
# The reason is structural, not stylistic: the Pi runtime's
# `transition()` returns before `saveState` when a gate fails, so the
# recorded history contains ONLY accepted transitions. Scoring it against
# the same policy would be 100% by construction — a confident number with
# nothing behind it. The gates are enforced at capture, which is exactly
# why nothing non-conformant survives to be measured.
#
# So this classifies and counts what happened. It never grades it.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

from . import constants as C

#: Position of each phase in the declared order (vocabulary + order only;
#: the legal-transition policy lives in the Pi runtime, not here).
PHASE_INDEX = {phase: i for i, phase in enumerate(C.CCT_PHASES)}

# Movement kinds. Named constants because they cross into the API payload
# and the UI, where a bare string would silently fork. These are
# DESCRIPTIVE labels — none of them means "violation".
FORWARD = "forward"      # moved later in the declared order
BACKWARD = "backward"    # moved earlier (rework, or a deliberate return)
SAME = "same"            # re-entered the same phase
UNKNOWN = "unknown"      # a phase outside the declared vocabulary


@dataclass(frozen=True)
class Entry:
    """One recorded phase occupancy: which phase, for which feature, when."""

    phase: str
    feature_id: Optional[str]
    at: str


@dataclass(frozen=True)
class Move:
    """One observed movement between consecutive entries."""

    from_phase: str
    to_phase: str
    kind: str
    at: str


@dataclass(frozen=True)
class Occupancy:
    """How long one phase was occupied, when that is knowable.

    ``seconds`` is None when it cannot be computed — an unparseable or
    absent timestamp, or the final entry, which has no successor to
    measure against. A missing duration is not a zero-length phase.
    """

    phase: str
    seconds: Optional[float]


@dataclass(frozen=True)
class ProcessMetrics:
    """Descriptive metrics for ONE feature's recorded timeline.

    ``review_observed`` is deliberately NOT named "reached review". The
    runtime keeps only the last 50 entries, so an absent review may have
    been evicted rather than never performed — an absence and a deletion
    are different claims and the field name must not conflate them.
    """

    moves: tuple[Move, ...]
    oscillations: int
    rework_cycles: int
    review_observed: bool
    phases_seen: tuple[str, ...]
    occupancy: tuple[Occupancy, ...]


def classify(prev: str, curr: str) -> str:
    """Describe the movement from ``prev`` to ``curr``. Never grades it."""
    if prev not in PHASE_INDEX or curr not in PHASE_INDEX:
        return UNKNOWN
    delta = PHASE_INDEX[curr] - PHASE_INDEX[prev]
    if delta > 0:
        return FORWARD
    if delta < 0:
        return BACKWARD
    return SAME


def _parse_at(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 stamp, or None. Never raises, never guesses."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _occupancy(entries: Sequence[Entry]) -> tuple[Occupancy, ...]:
    """Time spent in each entry's phase before the next one began.

    The LAST entry has no successor, so its duration is unknown rather
    than zero — it is the phase still in progress. Same for any pair
    whose stamps do not parse, or whose stamps run backwards (a clock
    change should not produce a negative elapsed time).
    """
    out: list[Occupancy] = []
    for i, entry in enumerate(entries):
        seconds: Optional[float] = None
        if i + 1 < len(entries):
            start, end = _parse_at(entry.at), _parse_at(entries[i + 1].at)
            if start is not None and end is not None:
                delta = (end - start).total_seconds()
                if delta >= 0:
                    seconds = delta
        out.append(Occupancy(phase=entry.phase, seconds=seconds))
    return tuple(out)


def _is_oscillation(a: Move, b: Move) -> bool:
    """Two consecutive moves that return to where they started.

    research -> plan -> research is churn worth counting; plan -> build
    -> review is not. Counting a single BACKWARD move as churn would
    include ordinary rework, which is already counted separately.
    """
    return a.from_phase == b.to_phase and a.to_phase == b.from_phase


def metrics_for(entries: Sequence[Entry]) -> ProcessMetrics:
    """Descriptive metrics over one feature's ordered entries."""
    moves = tuple(
        Move(prev.phase, curr.phase, classify(prev.phase, curr.phase), curr.at)
        for prev, curr in zip(entries, entries[1:])
    )
    oscillations = sum(
        1 for a, b in zip(moves, moves[1:]) if _is_oscillation(a, b)
    )
    # Rework: leaving review for an earlier phase. The runtime permits it
    # (review -> build is legitimate rework), so this counts occurrences,
    # it does not flag them.
    rework = sum(
        1 for m in moves if m.from_phase == C.PHASE_REVIEW and m.kind == BACKWARD
    )
    seen: list[str] = []
    for e in entries:
        if e.phase not in seen:
            seen.append(e.phase)
    return ProcessMetrics(
        moves=moves,
        oscillations=oscillations,
        rework_cycles=rework,
        review_observed=any(e.phase == C.PHASE_REVIEW for e in entries),
        phases_seen=tuple(seen),
        occupancy=_occupancy(entries),
    )


def entries_from_workflow_state(state: dict) -> list[Entry]:
    """Ordered entries from one parsed ``.cct/pi-workflow.json``.

    READS BOTH HALVES, and that is load-bearing. The runtime pushes an
    entry onto ``history`` when a phase is LEFT — each records the phase
    being exited — while the phase the work is in RIGHT NOW lives in the
    top-level ``phase``/``featureId``/``enteredAt``. Consuming only
    ``history`` silently drops the active phase, which is the one an
    operator is most likely to be asking about.

    Malformed entries are skipped rather than guessed at: a record with
    no phase is not evidence of a phase.
    """
    entries: list[Entry] = []
    history = state.get("history")
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            phase = item.get("phase")
            at = item.get("at")
            if isinstance(phase, str) and phase:
                feature = item.get("featureId")
                entries.append(
                    Entry(
                        phase=phase,
                        feature_id=feature if isinstance(feature, str) else None,
                        at=at if isinstance(at, str) else "",
                    )
                )
    current = state.get("phase")
    if isinstance(current, str) and current:
        feature = state.get("featureId")
        entered = state.get("enteredAt")
        entries.append(
            Entry(
                phase=current,
                feature_id=feature if isinstance(feature, str) else None,
                at=entered if isinstance(entered, str) else "",
            )
        )
    return entries


def history_may_be_truncated(state: dict) -> bool:
    """Whether the retained history is at the runtime's cap.

    At the cap, earlier entries have been evicted, so any "not observed"
    finding describes the RETAINED WINDOW and not the project's life.
    Callers must word absences accordingly.
    """
    history = state.get("history")
    return isinstance(history, list) and len(history) >= C.PI_WORKFLOW_HISTORY_CAP


def read_project_workflow(project_root: Path) -> Optional[dict]:
    """Parse one project's ``.cct/pi-workflow.json``, or None.

    A missing file is not an error — most projects have never run the Pi
    workflow. A corrupt one is also None rather than a crash, matching
    the runtime's own `catch → fresh state` posture; a report about
    process should not be the thing that fails on a bad byte.
    """
    path = project_root / Path(C.PI_WORKFLOW_REL)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def find_project_roots(base: Path) -> list[Path]:
    """Projects under ``base`` that carry a Pi workflow file.

    ``base`` may itself be a project or a parent of projects — the same
    two shapes ``PiAdapter._find_analytics_files`` accepts, so a root
    configured for ingestion works here without reconfiguration.
    """
    rel = Path(C.PI_WORKFLOW_REL)
    roots: list[Path] = []
    if (base / rel).is_file():
        roots.append(base)
    try:
        children = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        children = []
    roots.extend(child for child in children if (child / rel).is_file())
    return roots


def group_by_feature(
    entries: Iterable[Entry],
) -> dict[Optional[str], list[Entry]]:
    """Split a timeline by feature, preserving each feature's order.

    A feature is the thing that moves through phases; two features worked
    in parallel interleave in time, so a single timeline would show one
    feature's build followed by the other's research as a backward move
    nobody made.
    """
    grouped: dict[Optional[str], list[Entry]] = {}
    for entry in entries:
        grouped.setdefault(entry.feature_id, []).append(entry)
    return grouped


def report_for_roots(roots: Iterable[Path]) -> dict:
    """Assemble the descriptive report across Pi project roots.

    Every claim here is bounded by what the runtime retains. `truncated`
    is surfaced per project and summarised at the top level so a reader
    cannot mistake the RETAINED WINDOW for the project's whole life:
    with the history at its cap, an unobserved review may simply have
    been evicted. That is why the field is `review_observed` and the
    note says "not observed in the retained window".

    A root with no workflow file is reported as such rather than being
    silently dropped — "no Pi workflow history here" is an answer, and
    an empty report that looks healthy is not.
    """
    projects: list[dict] = []
    for root in roots:
        state = read_project_workflow(root)
        if state is None:
            projects.append({
                "project_path": str(root),
                "has_workflow_history": False,
                "features": [],
                "history_may_be_truncated": False,
            })
            continue
        truncated = history_may_be_truncated(state)
        entries = entries_from_workflow_state(state)
        features = []
        for feature_id, feature_entries in group_by_feature(entries).items():
            m = metrics_for(feature_entries)
            features.append({
                "feature_id": feature_id,
                "entries": len(feature_entries),
                "phases_seen": list(m.phases_seen),
                "moves": [
                    {"from": mv.from_phase, "to": mv.to_phase,
                     "kind": mv.kind, "at": mv.at}
                    for mv in m.moves
                ],
                "oscillations": m.oscillations,
                "rework_cycles": m.rework_cycles,
                "review_observed": m.review_observed,
                "occupancy_seconds": [
                    {"phase": o.phase, "seconds": o.seconds} for o in m.occupancy
                ],
            })
        features.sort(key=lambda f: (f["feature_id"] is None, f["feature_id"] or ""))
        projects.append({
            "project_path": str(root),
            "has_workflow_history": True,
            "features": features,
            "history_may_be_truncated": truncated,
        })

    with_history = [p for p in projects if p["has_workflow_history"]]
    return {
        "projects": projects,
        "projects_with_history": len(with_history),
        "retention_cap": C.PI_WORKFLOW_HISTORY_CAP,
        "any_history_may_be_truncated": any(
            p["history_may_be_truncated"] for p in projects
        ),
        # Wording is part of the contract, not decoration: an absence in
        # a capped window is not evidence that something never happened.
        "absence_note": (
            "Phases not listed were not observed in the retained window "
            f"(the runtime keeps the last {C.PI_WORKFLOW_HISTORY_CAP} "
            "transitions); this is not evidence they never occurred."
        ),
    }
