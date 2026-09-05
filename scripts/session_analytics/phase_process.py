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

from dataclasses import dataclass
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
