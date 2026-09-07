# session_analytics.session_filter — the query-time noise predicate (#307).
#
# Probe runs in temp dirs and two-turn smoke sessions are real rows in the
# store, and on a developer's machine they outnumber real work on the
# first screen. They are excluded from LISTS and AGGREGATES here, at query
# time — never at ingest — so the thresholds in sessions.noise can change
# without a re-ingest, and so session-by-id, trace search and the judge
# (which are asked about ONE session on purpose) always see everything.
#
# One predicate, built once, applied everywhere a number is shown: the
# Sessions list, the dashboard KPIs, the effort estimate and the pipeline
# funnel. A page that applies its own version of "noise" would report a
# different count from the page beside it.

from __future__ import annotations

from typing import Any

from . import constants as C
from .config import NoiseConfig

_LIKE_ESCAPE = "\\"


def _like_pattern(fragment: str) -> str:
    """A LIKE pattern matching ``fragment`` anywhere, with the LIKE
    metacharacters in the fragment escaped so ``_`` means underscore."""
    escaped = (
        fragment.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def noise_clause(cfg: NoiseConfig, alias: str = "copilot_session") -> tuple[str, tuple[Any, ...]]:
    """SQL that is TRUE for a noise session, with its parameters.

    ``alias`` is the table alias of ``copilot_session`` in the caller's
    query. Unknown values are not evidence: a NULL duration or a NULL
    project path never makes a session noise. With every threshold off
    the clause is ``1=0`` (nothing is noise).
    """
    parts: list[str] = []
    params: list[Any] = []
    if cfg.min_turns > 0:
        parts.append(f"{alias}.turn_count < ?")
        params.append(cfg.min_turns)
    if cfg.min_duration_seconds > 0:
        parts.append(
            f"({alias}.duration_seconds IS NOT NULL AND {alias}.duration_seconds < ?)"
        )
        params.append(cfg.min_duration_seconds)
    for fragment in cfg.path_patterns:
        # COALESCE: a NULL path must compare as "no match", not as SQL
        # NULL — a NULL inside the OR poisons NOT(...) and the session
        # would be neither kept nor counted as noise.
        parts.append(
            f"COALESCE({alias}.project_path, '') LIKE ? ESCAPE '{_LIKE_ESCAPE}'"
        )
        params.append(_like_pattern(fragment))
    if not parts:
        return "1=0", ()
    # A session the benchmark correlator linked to an attempt was run on
    # purpose, however short or wherever it ran (attempt dirs ARE temp
    # dirs); it is never noise.
    return (
        f"({alias}.{C.COL_BENCHMARK_RUN_DIR} IS NULL AND (" + " OR ".join(parts) + "))",
        tuple(params),
    )


def keep_clause(cfg: NoiseConfig, alias: str = "copilot_session") -> tuple[str, tuple[Any, ...]]:
    """SQL that is TRUE for a session worth counting: NOT noise."""
    sql, params = noise_clause(cfg, alias)
    if sql == "1=0":
        return "1=1", ()
    return f"NOT {sql}", params
