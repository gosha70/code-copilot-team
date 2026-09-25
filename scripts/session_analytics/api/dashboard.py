# session_analytics.api.dashboard — dashboard aggregate queries (pure DB).
#
# JSON-ready aggregates for the Studio dashboard. No FastAPI dependency, so
# these are unit-tested directly against SQLite.

from __future__ import annotations

from typing import Any, Optional

from .. import constants as C
from ..config import NoiseConfig
from ..relational.db import Database
from ..session_filter import keep_clause, noise_clause


def kpis(db: Database, noise: Optional[NoiseConfig] = None) -> dict[str, Any]:
    """Headline counters + distributions for the dashboard.

    With ``noise`` given, every number is over the sessions worth
    counting (see session_filter) and ``totals.excluded_noise`` says how
    many were left out — the Sessions page's "Show excluded (n)" and the
    Analysis funnel print the same figure. Turn-level distributions
    (tool usage, sentiment) are joined to the session so they exclude the
    same rows; a probe's tool calls must not top the chart the probe's
    session was hidden from.
    """
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    noise_sql, noise_params = noise_clause(noise, "s") if noise else ("1=0", ())

    totals = db.query_one(
        f"""
        SELECT COUNT(*), COALESCE(SUM(turn_count),0), COALESCE(SUM(tool_call_count),0),
               COALESCE(SUM(error_count),0), COALESCE(AVG(duration_seconds),0)
        FROM copilot_session s WHERE {keep_sql}
        """,
        keep_params,
    ) or (0, 0, 0, 0, 0)
    excluded = db.query_one(
        f"SELECT COUNT(*) FROM copilot_session s WHERE {noise_sql}", noise_params
    ) or (0,)

    # E5: total cost + cost-per-session (primary cost KPI — D-outcome).
    # SUM ignores NULL cost_usd (unpriced turns) → total of what COULD be
    # priced. cost_per_session divides by sessions that HAVE at least one
    # priced turn (not all sessions): dividing a priced-only numerator by an
    # all-sessions denominator would understate the real per-session cost
    # whenever some sessions are unpriced. `priced_sessions` is exposed so the
    # denominator is transparent.
    total_cost_row = db.query_one(
        f"SELECT SUM(t.cost_usd) FROM copilot_turn t "
        f"JOIN copilot_session s ON s.id = t.session_id WHERE {keep_sql}",
        keep_params,
    ) or (None,)
    total_cost_usd = float(total_cost_row[0]) if total_cost_row[0] is not None else 0.0
    priced_row = db.query_one(
        f"SELECT COUNT(DISTINCT t.session_id) FROM copilot_turn t "
        f"JOIN copilot_session s ON s.id = t.session_id "
        f"WHERE t.cost_usd IS NOT NULL AND {keep_sql}",
        keep_params,
    ) or (0,)
    priced_sessions = int(priced_row[0] or 0)
    cost_per_session = (total_cost_usd / priced_sessions) if priced_sessions else 0.0

    by_copilot = [
        {"copilot": r[0], "sessions": int(r[1]), "errors": int(r[2] or 0)}
        for r in db.query(
            f"SELECT copilot, COUNT(*), COALESCE(SUM(error_count),0) "
            f"FROM copilot_session s WHERE {keep_sql} "
            f"GROUP BY copilot ORDER BY COUNT(*) DESC",
            keep_params,
        )
    ]

    by_day = [
        {"day": r[0], "sessions": int(r[1])}
        for r in db.query(
            # started_at is ISO TEXT; substr(…,1,10) is the date, portable.
            f"SELECT substr(started_at,1,10) AS day, COUNT(*) FROM copilot_session s "
            f"WHERE started_at IS NOT NULL AND {keep_sql} "
            f"GROUP BY day ORDER BY day DESC LIMIT 30",
            keep_params,
        )
    ]

    tool_usage = [
        {"tool": r[0], "count": int(r[1]), "errors": int(r[2] or 0)}
        for r in db.query(
            f"""
            SELECT tc.tool_name, COUNT(*),
                   SUM(CASE WHEN tr.is_error THEN 1 ELSE 0 END)
            FROM copilot_tool_call tc
            JOIN copilot_turn t ON t.id = tc.turn_id
            JOIN copilot_session s ON s.id = t.session_id
            LEFT JOIN copilot_tool_result tr ON tr.tool_call_id = tc.id
            WHERE {keep_sql}
            GROUP BY tc.tool_name ORDER BY COUNT(*) DESC LIMIT 25
            """,
            keep_params,
        )
    ]

    sentiment = [
        {"sentiment": r[0], "count": int(r[1])}
        for r in db.query(
            f"SELECT h.sentiment, COUNT(*) FROM heuristic_label h "
            f"JOIN copilot_turn t ON t.id = h.turn_id "
            f"JOIN copilot_session s ON s.id = t.session_id "
            f"WHERE h.sentiment IS NOT NULL AND {keep_sql} "
            f"GROUP BY h.sentiment ORDER BY COUNT(*) DESC",
            keep_params,
        )
    ]

    return {
        "totals": {
            "sessions": int(totals[0]),
            "turns": int(totals[1]),
            "tool_calls": int(totals[2]),
            "errors": int(totals[3]),
            "avg_duration_seconds": float(totals[4] or 0),
            "total_cost_usd": total_cost_usd,
            "cost_per_session": cost_per_session,
            "priced_sessions": priced_sessions,
            "excluded_noise": int(excluded[0] or 0),
        },
        "by_copilot": by_copilot,
        "by_day": by_day,
        "tool_usage": tool_usage,
        "sentiment_distribution": sentiment,
    }


def cost_by_outcome(db: Database, noise: Optional[NoiseConfig] = None) -> dict[str, Any]:
    """Cost-per-outcome (E5, FR-4): cost aggregated by session ``phase`` and
    by the judge's ``sentiment`` label — the two "outcome" dimensions the
    schema actually has (there is no single outcome column; ``sentiment`` is
    the same per-turn judge dimension ``kpis().sentiment_distribution``
    already reports elsewhere in this module). Only turns with a non-NULL
    ``cost_usd`` contribute (unpriced turns are excluded, not zeroed). The
    field is ``by_sentiment`` (not "label") because it groups by sentiment.
    With ``noise`` given, the same sessions as ``kpis`` (#307)."""
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    by_phase = [
        {"phase": r[0] or "(none)", "cost_usd": float(r[1] or 0), "sessions": int(r[2])}
        for r in db.query(
            f"""
            SELECT s.phase, SUM(t.cost_usd), COUNT(DISTINCT s.id)
            FROM copilot_session s
            JOIN copilot_turn t ON t.session_id = s.id
            WHERE t.cost_usd IS NOT NULL AND {keep_sql}
            GROUP BY s.phase
            ORDER BY SUM(t.cost_usd) DESC
            """,
            keep_params,
        )
    ]
    # De-dupe to ONE sentiment per turn: heuristic_label is UNIQUE(turn_id,
    # rubric_name), so joining directly would count a turn's cost once per
    # rubric label. Pick a single sentiment per turn (first rubric_name) via a
    # correlated subquery so each priced turn's cost lands in exactly one
    # bucket — the by_sentiment totals then never exceed total_cost_usd.
    by_sentiment = [
        {"sentiment": r[0] or "(none)", "cost_usd": float(r[1] or 0), "turns": int(r[2])}
        for r in db.query(
            f"""
            SELECT tl.sentiment, SUM(tl.cost_usd), COUNT(*)
            FROM (
                SELECT t.id, t.cost_usd,
                    (SELECT h.sentiment FROM heuristic_label h
                     WHERE h.turn_id = t.id AND h.sentiment IS NOT NULL
                     ORDER BY h.rubric_name LIMIT 1) AS sentiment
                FROM copilot_turn t
                JOIN copilot_session s ON s.id = t.session_id
                WHERE t.cost_usd IS NOT NULL AND {keep_sql}
            ) tl
            WHERE tl.sentiment IS NOT NULL
            GROUP BY tl.sentiment
            ORDER BY SUM(tl.cost_usd) DESC
            """,
            keep_params,
        )
    ]
    return {"by_phase": by_phase, "by_sentiment": by_sentiment}


def effective_redaction_by_project(db: Database) -> dict[str, Any]:
    """FR-5: per-project "effective redaction mode" the project's already-
    ingested sessions were recorded with — read-only, derived purely by
    grouping ``copilot_session.redaction_mode`` by ``project_path`` (no new
    DB column, no migration). A project's mode can differ across ingests if
    the layered config changed between runs, so when a project's sessions
    don't all share one mode the effective mode is the literal string
    ``"mixed"`` (surfacing the ambiguity rather than silently picking one)."""
    rows = db.query(
        """
        SELECT project_path, redaction_mode, COUNT(*)
        FROM copilot_session
        WHERE project_path IS NOT NULL
        GROUP BY project_path, redaction_mode
        """
    )
    by_project: dict[str, dict[str, int]] = {}
    for project_path, redaction_mode, count in rows:
        modes = by_project.setdefault(project_path, {})
        modes[redaction_mode] = modes.get(redaction_mode, 0) + int(count)

    projects = []
    for project_path, modes in by_project.items():
        session_count = sum(modes.values())
        effective = next(iter(modes)) if len(modes) == 1 else "mixed"
        projects.append({
            "project_path": project_path,
            "session_count": session_count,
            "redaction_modes": modes,
            "effective_redaction_mode": effective,
        })
    projects.sort(key=lambda p: p["session_count"], reverse=True)
    return {"projects": projects}


def developer_aggregates(db: Database, noise: Optional[NoiseConfig] = None) -> dict[str, Any]:
    """E1 (#65): per-developer activity rollup for the team dashboard.

    Grouped on ``copilot_session.developer_id``, which the ingest already
    resolves (``--developer-id`` > env > config > git email local-part >
    ``constants.DEFAULT_DEVELOPER_ID``). No new column and no migration.

    Two things this deliberately does NOT do.

    It does not rank developers by volume as if that were performance.
    Sessions and turns measure how much a copilot was used, not how well
    anyone works, and a dashboard that sorts people by a productivity-
    shaped number invites exactly that reading. Rows are ordered by
    ``developer_id`` — stable and alphabetical, not a leaderboard.

    It does not report unknown cost as zero. ``cost_usd`` is None when a
    developer has no priced turns; only a real total is a number. Cost
    coverage is ``priced_turns`` out of ``priceable_turns`` — turns that
    were pricing candidates — never out of every turn.

    It does not hide the single-developer case. A store ingested on one
    machine has one row, and ``is_single_developer`` says so plainly so
    the UI can explain an empty-looking team view instead of implying
    the team is idle. ``unattributed_sessions`` counts sessions still on
    the default id, which is what an unconfigured ``developer_id`` looks
    like from here — a team that never set it reads as one person.
    """
    # Same sessions as kpis() (#307): a developer's probe runs are not
    # that developer's work.
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    rows = db.query(
        f"""
        SELECT developer_id,
               COUNT(*),
               COALESCE(SUM(turn_count), 0),
               COALESCE(SUM(tool_call_count), 0),
               COALESCE(SUM(error_count), 0),
               COUNT(DISTINCT project_path),
               MIN(started_at),
               MAX(started_at)
        FROM copilot_session s WHERE {keep_sql}
        GROUP BY developer_id
        ORDER BY developer_id
        """,
        keep_params,
    )
    # Cost lives on copilot_turn, so it is a separate grouped read rather
    # than a join that would multiply the session-level SUMs above.
    #
    # A developer with no priced turns gets None, NOT 0.0. NULL cost_usd
    # means "not priced" and rendering that as $0.00 would report unknown
    # cost as free — a number someone could budget against. `priced_turns`
    # is exposed for the same reason `kpis()` exposes `priced_sessions`:
    # the denominator behind a cost figure has to be visible.
    #
    # `priceable_turns` is the denominator, and it is NOT the turn count:
    # a turn with no model is not a pricing candidate, so counting every
    # turn would report a fully-priced developer as partial forever.
    #
    # The eligibility rule is HAVING A MODEL, taken from the pricing
    # contract itself — `cost.compute_turn_cost` returns NULL for
    # `not model` and prices everything else, including turns whose only
    # tokens are cache reads/writes. An earlier version used "has
    # input/output tokens" as a proxy. It agreed with this rule on every
    # row of the corpus at hand, which is exactly why the proxy survived
    # review once: a cache-only turn would be excluded though priceable,
    # a model-less turn carrying tokens counted though it can never be
    # priced, and the first of those can drive priced_turns above the
    # denominator.
    cost_by_dev: dict[str, tuple[Optional[float], int, int]] = {
        r[0]: (
            float(r[1]) if r[1] is not None else None,
            int(r[2] or 0),
            int(r[3] or 0),
        )
        for r in db.query(
            f"""
            SELECT s.developer_id,
                   SUM(t.cost_usd),
                   COUNT(t.cost_usd),
                   SUM(CASE WHEN t.model IS NOT NULL AND t.model <> ''
                            THEN 1 ELSE 0 END)
            FROM copilot_turn t
            JOIN copilot_session s ON s.id = t.session_id
            WHERE {keep_sql}
            GROUP BY s.developer_id
            """,
            keep_params,
        )
    }
    # Registered developers may have no sessions yet; the registry is the
    # source of display names, and a name is only shown if one was set.
    display_names = {
        r[0]: r[1]
        for r in db.query("SELECT developer_id, display_name FROM developer")
    }

    developers = [
        {
            "developer_id": r[0],
            "display_name": display_names.get(r[0]),
            "sessions": int(r[1]),
            "turns": int(r[2]),
            "tool_calls": int(r[3]),
            "errors": int(r[4]),
            "projects": int(r[5]),
            "first_seen": r[6],
            "last_seen": r[7],
            "cost_usd": cost_by_dev.get(r[0], (None, 0, 0))[0],
            "priced_turns": cost_by_dev.get(r[0], (None, 0, 0))[1],
            "priceable_turns": cost_by_dev.get(r[0], (None, 0, 0))[2],
        }
        for r in rows
    ]
    unattributed = next(
        (
            d["sessions"]
            for d in developers
            if d["developer_id"] == C.DEFAULT_DEVELOPER_ID
        ),
        0,
    )
    return {
        "developers": developers,
        "developer_count": len(developers),
        "is_single_developer": len(developers) <= 1,
        "unattributed_sessions": unattributed,
        "registered_without_sessions": sorted(
            set(display_names) - {d["developer_id"] for d in developers}
        ),
    }


def benchmark_correlation(db: Database, noise: Optional[NoiseConfig] = None) -> dict[str, Any]:
    """E9 (#91): benchmark-linked vs organic session coverage.

    ``sessions_linked`` = sessions whose ``benchmark_run_dir`` was stamped by
    ``correlate`` (``COUNT(col)`` counts non-NULL only); ``sessions_unlinked``
    is the organic remainder; ``distinct_benchmark_attempts`` is how many
    distinct attempt directories are linked — named for what the column
    actually stores (the per-ATTEMPT dir, D-run-dir-granularity), NOT runs: a
    run with N attempts contributes up to N. Backend-only summary — no Studio
    UI in this slice."""
    # Same sessions as every other total (#307); a linked session is
    # never noise, so `sessions_linked` is unaffected by the filter.
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    row = db.query_one(
        f"""
        SELECT COUNT(*),
               COUNT({C.COL_BENCHMARK_RUN_DIR}),
               COUNT(DISTINCT {C.COL_BENCHMARK_RUN_DIR})
        FROM copilot_session s WHERE {keep_sql}
        """,
        keep_params,
    ) or (0, 0, 0)
    total = int(row[0] or 0)
    linked = int(row[1] or 0)
    return {
        "sessions_total": total,
        "sessions_linked": linked,
        "sessions_unlinked": total - linked,
        "distinct_benchmark_attempts": int(row[2] or 0),
    }


def benchmark_outcomes(db: Database) -> dict[str, Any]:
    """E9 outcomes (#92): compare sessions BY benchmark result.

    Grouped over ``benchmark_result`` by ``result`` (pass/fail/error/timeout;
    ``(none)`` for rows whose score carried no result). Per group: ``attempts``
    = all outcome rows; ``linked_sessions`` = DISTINCT sessions with a
    resolved ``session_ref``; ``total_cost_usd`` = Σ of those DISTINCT linked
    sessions' turn costs (D-aggregate-cost-source — NULL-safe like the E5
    KPIs: unpriced turns excluded, unlinked attempts contribute NO cost);
    ``avg_duration_seconds`` over distinct linked sessions only. Session-level
    figures aggregate through ``SELECT DISTINCT (result, session_ref)`` so a
    session referenced by MULTIPLE attempt rows (the tolerated
    duplicate-session_id case) contributes its cost/duration exactly ONCE per
    result bucket — never once per row (that fan-out would double-count)."""
    attempts_by = {
        r[0]: int(r[1])
        for r in db.query(
            f"SELECT result, COUNT(*) FROM {C.TBL_BENCHMARK_RESULT} GROUP BY result"
        )
    }
    # Distinct (result, session) pairs drive every session-level figure; the
    # per-session cost is pre-aggregated once (one grouped scan of
    # copilot_turn), not re-computed per benchmark_result row.
    session_by = {
        r[0]: (int(r[1]), float(r[2] or 0), float(r[3] or 0))
        for r in db.query(
            f"""
            SELECT dr.result, COUNT(*), SUM(sc.cost), AVG(s.duration_seconds)
            FROM (
                SELECT DISTINCT result, session_ref
                FROM {C.TBL_BENCHMARK_RESULT}
                WHERE session_ref IS NOT NULL
            ) dr
            JOIN copilot_session s ON s.id = dr.session_ref
            LEFT JOIN (
                SELECT session_id, SUM(cost_usd) AS cost
                FROM copilot_turn GROUP BY session_id
            ) sc ON sc.session_id = dr.session_ref
            GROUP BY dr.result
            """
        )
    }
    by_result = [
        {
            "result": result if result is not None else "(none)",
            "attempts": attempts,
            "linked_sessions": session_by.get(result, (0, 0.0, 0.0))[0],
            "total_cost_usd": session_by.get(result, (0, 0.0, 0.0))[1],
            "avg_duration_seconds": session_by.get(result, (0, 0.0, 0.0))[2],
        }
        for result, attempts in sorted(
            attempts_by.items(), key=lambda kv: kv[1], reverse=True
        )
    ]
    return {"by_result": by_result}


def label_distribution(
    db: Database, rubric_name: Optional[str] = None, noise: Optional[NoiseConfig] = None,
) -> dict[str, Any]:
    """Per-bool-label true-counts across labeled turns of the sessions
    worth counting (#307), for one rubric run — the packaged rubric's
    unless named (#313)."""
    from ..judge.rubric import load_rubric

    rubric = load_rubric()
    rubric_name = rubric_name or rubric.name
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    out = []
    for label in rubric.bool_labels:
        if not label.isidentifier():
            continue
        row = db.query_one(
            f"SELECT SUM(CASE WHEN h.{label} THEN 1 ELSE 0 END), COUNT(*) "
            f"FROM heuristic_label h "
            f"JOIN copilot_turn t ON t.id = h.turn_id "
            f"JOIN copilot_session s ON s.id = t.session_id "
            f"WHERE h.rubric_name = ? AND {keep_sql}",
            (rubric_name, *keep_params),
        )
        out.append({"label": label, "true": int((row[0] or 0)), "total": int((row[1] or 0))})
    return {"labels": out}


def latency(db: Database, noise: Optional[NoiseConfig] = None) -> dict[str, Any]:
    """Agent response time across the store (#307, Studio Phase 2).

    The gap before each ASSISTANT turn, read from copilot_turn.timestamp
    with the same rule the session page uses (mcp.tools.turn_latency:
    both neighbours stamped, never negative) — so the dashboard's median
    and a session's badges cannot disagree. Nearest-rank percentiles, and
    the measured-n beside every figure: a median over 12 turns is not a
    median over 12,000.
    """
    from ..mcp.tools import _parse_ts, _percentile, turn_latency

    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    rows = db.query(
        f"""
        SELECT t.session_id, s.copilot, t.role, t.timestamp
        FROM copilot_turn t
        JOIN copilot_session s ON s.id = t.session_id
        WHERE {keep_sql}
        ORDER BY t.session_id, t.sequence_num
        """,
        keep_params,
    )
    by_copilot: dict[str, list[float]] = {}
    sessions: set[int] = set()
    prev_session = None
    prev_ts = None
    for session_id, copilot, role, ts in rows:
        if session_id != prev_session:
            prev_session, prev_ts = session_id, None
        ts_dt = _parse_ts(ts)
        gap = turn_latency(prev_ts, ts_dt)
        prev_ts = ts_dt
        if gap is not None and role == C.ROLE_ASSISTANT:
            by_copilot.setdefault(str(copilot), []).append(gap)
            sessions.add(int(session_id))

    def summary(values: list[float]) -> dict[str, Any]:
        ordered = sorted(values)
        return {
            "measured_turns": len(ordered),
            "p50": _percentile(ordered, 0.5) if ordered else None,
            "p90": _percentile(ordered, 0.9) if ordered else None,
            "max": ordered[-1] if ordered else None,
        }

    everything = [v for vs in by_copilot.values() for v in vs]
    return {
        **summary(everything),
        "sessions": len(sessions),
        "by_copilot": [
            {"copilot": name, **summary(vals)}
            for name, vals in sorted(by_copilot.items(), key=lambda kv: -len(kv[1]))
        ],
        "basis": "seconds from the previous turn to each assistant turn; "
                 "turns without a timestamp on both sides are not measured",
    }


# ── harness compare (#371 A4b) ─────────────────────────────────────────


#: The kind of an ordinary row: a real value of the chosen dimension,
#: as opposed to one of the named groups.
_KIND_VALUE = "value"


def _median(values: list[float]) -> Optional[float]:
    """The median, by the package's ONE percentile rule (nearest rank,
    never interpolated). Reused rather than reimplemented: a second copy
    of the rule is a second thing to keep in step, and the two would
    disagree on even samples the first time one was edited."""
    from ..predict import _percentile

    return _percentile(values, 0.5)


def _mean(values: list[float]) -> Optional[float]:
    """The mean, or None for an empty sample — never 0.0, which would
    report "no judgement" as "judged badly"."""
    return (sum(values) / len(values)) if values else None


def _weighted_mean(pairs: list[tuple[Optional[float], int]]) -> Optional[float]:
    """A rate over the TURNS it was measured on, not over sessions.

    A rate per session averaged equally lets a session with one labelled
    turn outvote one with ninety-nine: 1 rework turn and 99 clean ones
    would read 0.50 rather than 0.01. The spec defines these rates over
    labelled turns, so each session's rate is weighted by the turns that
    earned it. None (never 0.0) when nothing was labelled."""
    usable = [(rate, weight) for rate, weight in pairs if rate is not None and weight > 0]
    total = sum(weight for _, weight in usable)
    if not total:
        return None
    return sum(rate * weight for rate, weight in usable) / total


def harness_aggregates(
    db: Database, noise: Optional[NoiseConfig] = None, by: str = C.HARNESS_DIMENSIONS[0],
) -> dict[str, Any]:
    """#371 A4b: sessions grouped by one dimension of the harness they
    ran under, so two harness versions can be put side by side.

    ``by`` is one of ``constants.HARNESS_DIMENSIONS`` — a CLOSED set,
    because the value names a column. Anything else raises ValueError.

    Four kinds of row, and none of them is dropped:

    * one per distinct value of ``by`` among stamped, unmixed sessions;
    * ``mixed`` — the harness changed while the session ran, so it
      belongs to neither version and is never counted under one;
    * ``absent`` — stamped, but this dimension was not recorded (a
      session carrying only the transcript's ``cli_version`` grouped by
      ``cct_sha``, say);
    * ``unstamped`` — no stamp at all: a session from before the hook
      was installed, a plugin-only session, Pi or Aider.

    It inherits ``developer_aggregates``' three refusals. It does not
    rank: rows are ordered by value, with the named groups last, because
    a table sorted by "best" invites reading a harness change as a
    verdict it has not earned. It does not report unknown cost as zero —
    ``cost_usd`` is None without a priced turn, and the coverage behind
    it is published. And it does not hide the degenerate case:
    ``single_group`` says when everything landed in one row, which is
    what a store has before a second harness version has ever run.

    Every judge-derived figure is None, never 0.0, when no session in
    the row carries a label from the packaged rubric; ``sessions_judged``
    is the denominator that earned it.
    """
    if by not in C.HARNESS_DIMENSIONS:
        raise ValueError(
            f"cannot group sessions by {by!r}; one of: {', '.join(C.HARNESS_DIMENSIONS)}"
        )
    keep_sql, keep_params = keep_clause(noise, "s") if noise else ("1=1", ())
    no_facts_sql = " AND ".join(f"s.{f} IS NULL" for f in C.HARNESS_FACTS)
    # The KIND of row a session belongs to, decided in SQL so the CASE
    # order is the definition, and kept SEPARATE from the dimension's
    # value. Two reasons the order and the separation are load-bearing:
    #
    # * MIXED FIRST. A session whose harness changed mid-run is evidence
    #   for no version, even when its earliest stamp carries no facts at
    #   all — testing "no facts" first put such a session in `unstamped`
    #   while `harness_clause` answered it for `mixed` too, so the groups
    #   overlapped and the row's own link disagreed with it.
    # * KIND, NOT THE STRING. A cli_version or cct_version is untrusted
    #   text that may legitimately BE "mixed" or "unstamped"; folding the
    #   kind into the value merged that real version into the named group
    #   and mislabelled the row.
    kind_sql = (
        f"CASE WHEN s.{C.HARNESS_KEY_MIXED} IS TRUE THEN '{C.HARNESS_GROUP_MIXED}' "
        f"WHEN {no_facts_sql} THEN '{C.HARNESS_GROUP_UNSTAMPED}' "
        f"WHEN s.{by} IS NULL THEN '{C.HARNESS_GROUP_ABSENT}' "
        f"ELSE '{_KIND_VALUE}' END"
    )
    sessions = db.query(
        f"""
        SELECT {kind_sql}, s.{by}, s.id, s.turn_count, s.tool_call_count,
               s.error_count, s.started_at
        FROM copilot_session s WHERE {keep_sql}
        """,
        keep_params,
    )
    # Cost per session: the same eligibility rule developer_aggregates
    # documents — priceable means HAVING A MODEL, which is the pricing
    # contract itself, not "has tokens".
    cost_by_session = {
        int(r[0]): (float(r[1]) if r[1] is not None else None, int(r[2] or 0), int(r[3] or 0))
        for r in db.query(
            f"""
            SELECT t.session_id, SUM(t.cost_usd), COUNT(t.cost_usd),
                   SUM(CASE WHEN t.model IS NOT NULL AND t.model <> '' THEN 1 ELSE 0 END)
            FROM copilot_turn t JOIN copilot_session s ON s.id = t.session_id
            WHERE {keep_sql} GROUP BY t.session_id
            """,
            keep_params,
        )
    }
    # The judge's per-session rollup under the PACKAGED rubric — its own
    # name (heuristic-v1), which is what the rows are stored under, never
    # a configuration key (the #371 A2 lesson).
    from ..judge.rubric import load_rubric

    kpi_by_session = {
        int(r[0]): (r[1], r[2], r[3], int(r[4] or 0))
        for r in db.query(
            f"""
            SELECT k.session_id, k.avg_interaction_quality, k.rework_rate,
                   k.correction_rate, k.labeled_turn_count
            FROM session_kpi k JOIN copilot_session s ON s.id = k.session_id
            WHERE {keep_sql} AND k.rubric_name = ?
            """,
            tuple(keep_params) + (load_rubric().name,),
        )
    }

    # Keyed by (kind, value): a named group has no value, and a real
    # value that spells "mixed" stays its own row.
    grouped: dict[tuple[str, Optional[str]], list[tuple]] = {}
    #: session id -> the row it belongs to, so an expectation's run can
    #: be attributed only when ALL of its sessions agree (#371 A5).
    group_of_session: dict[int, tuple[str, Optional[str]]] = {}
    for row in sessions:
        kind = str(row[0])
        key = (kind, str(row[1]) if kind == _KIND_VALUE else None)
        grouped.setdefault(key, []).append(row)
        group_of_session[int(row[2])] = key

    rows: list[dict[str, Any]] = []
    for (kind, value), members in grouped.items():
        ids = [int(m[2]) for m in members]
        costs = [cost_by_session.get(i, (None, 0, 0)) for i in ids]
        priced = [c[0] for c in costs if c[0] is not None]
        kpis = [kpi_by_session[i] for i in ids if i in kpi_by_session]
        judged = [k for k in kpis if k[3] > 0]
        turns = sum(int(m[3] or 0) for m in members)
        rows.append({
            "kind": kind,
            # None for a named group: the row is that group, not a value
            # that happens to be spelled like one.
            "value": value,
            "is_group": kind != _KIND_VALUE,
            "sessions": len(members),
            "turns": turns,
            "median_turns": _median([float(m[3] or 0) for m in members]),
            "median_tool_calls": _median([float(m[4] or 0) for m in members]),
            "errors": sum(int(m[5] or 0) for m in members),
            # Per 100 turns, like the session header; None when the row
            # has no turns to divide by rather than a spurious 0.
            "errors_per_100_turns": (
                (sum(int(m[5] or 0) for m in members) / turns * 100) if turns else None
            ),
            "cost_usd": sum(priced) if priced else None,
            "priced_turns": sum(c[1] for c in costs),
            "priceable_turns": sum(c[2] for c in costs),
            "first_seen": min((m[6] for m in members if m[6]), default=None),
            "last_seen": max((m[6] for m in members if m[6]), default=None),
            # Judge figures: None without labels, never zero. Quality is
            # the mean of the per-session means, as specified — a session
            # is one reading of how the work went. The two RATES are over
            # the labelled turns that produced them, so a one-turn
            # session cannot outvote a hundred-turn one.
            "avg_interaction_quality": _mean(
                [float(k[0]) for k in judged if k[0] is not None]
            ),
            "rework_rate": _weighted_mean([(k[1], k[3]) for k in judged]),
            "correction_rate": _weighted_mean([(k[2], k[3]) for k in judged]),
            "sessions_judged": len(judged),
            "labeled_turns": sum(k[3] for k in judged),
        })
    exclusions = _attach_expectations(db, rows, group_of_session)
    # Ordered by value, named groups last: stable, and not a leaderboard.
    rows.sort(key=lambda r: (r["is_group"], r["value"] or r["kind"]))
    value_rows = [r for r in rows if not r["is_group"]]
    return {
        "by": by,
        "dimensions": list(C.HARNESS_DIMENSIONS),
        "rows": rows,
        # Runs that belong to NO row. Top-level, not per row: reporting
        # an excluded run inside a row would contradict the exclusion.
        **exclusions,
        # One comparable value (or none) is not a comparison; say so
        # rather than letting a one-row table imply one.
        "single_group": len(value_rows) <= 1,
        "comparable_values": len(value_rows),
        "basis": (
            "sessions grouped by the harness stamp recorded when each session started; "
            "mixed, absent and unstamped are named rows, never folded into a version. "
            "Expectation figures are attributed at RUN grain: a run counts in a row only "
            "when every session it discovered is linked and all of them fall in that row"
        ),
    }


def _attach_expectations(
    db: Database, rows: list[dict[str, Any]], group_of_session: dict[int, tuple[str, Optional[str]]]
) -> dict[str, int]:
    """#371 A5: expectation outcomes per harness row, at RUN grain.

    A run is the unit that was evaluated — one verifier gate, one set of
    results — so it is the unit that counts. Attributing per session
    would copy one run's single outcome into every version its sessions
    touched.

    A run is attributable to a row only when BOTH hold:

    * every session the ingest pass discovered for it is linked
      (`session_ref` is not NULL) and falls in the population being
      grouped; and
    * all of those sessions fall in the SAME row.

    Two boundary cases are decided here rather than left to emerge:

    * A run with ZERO discovered sessions is unattributable, not
      vacuously attributable. "All its sessions agree" is trivially
      true of an empty set, which would otherwise place a sessionless
      run in whichever row happened to be considered first.
    * `sessions_with_expectations` counts DISTINCT resolved sessions,
      not association rows, so a session that appears in several runs
      cannot inflate a row's session coverage.

    Every judge-style discipline of this module carries over: `unknown`
    and `unevaluated` expectations are in NEITHER side of the rate, and
    the rate is None — never 0.0 — when nothing was evaluated.
    """
    from .. import expectations as exp

    for row in rows:
        row.update({
            "expectations_met": 0, "expectations_evaluated": 0,
            "expectations_unknown": 0, "expectations_unevaluated": 0,
            "runs_with_expectations": 0, "sessions_with_expectations": 0,
            "expectation_rate": None,
        })
    by_key = {(r["kind"], r["value"]): r for r in rows}
    # Distinct sessions per row, so repeated runs cannot inflate coverage.
    row_sessions: dict[tuple[str, Optional[str]], set[int]] = {k: set() for k in by_key}
    spanning = unmatched = 0

    # EVERY stored run: this aggregate is defined over all of them, and
    # a cap would drop later runs out of the row totals and out of the
    # exclusion counters alike — an omission that looks like nothing.
    for run in exp.list_runs(db, limit=None):
        links = run.get("sessions") or []
        refs = [s.get("session_ref") for s in links]
        placed = {group_of_session.get(ref) for ref in refs if ref is not None}
        if (
            not links                       # no session recorded at all
            or any(ref is None for ref in refs)   # discovered but not ingested
            or None in placed               # ingested but outside this population
        ):
            unmatched += 1
            continue
        if len(placed) != 1:
            spanning += 1
            continue
        key = placed.pop()
        row = by_key.get(key)
        if row is None:
            unmatched += 1
            continue
        row["runs_with_expectations"] += 1
        row["expectations_met"] += run["expectations_met"]
        row["expectations_evaluated"] += run["expectations_evaluated"]
        row["expectations_unknown"] += run["expectations_unknown"]
        row["expectations_unevaluated"] += run["expectations_unevaluated"]
        row_sessions[key].update(ref for ref in refs if ref is not None)

    for key, row in by_key.items():
        row["sessions_with_expectations"] = len(row_sessions[key])
        evaluated = row["expectations_evaluated"]
        # Exactly met / evaluated, over `met` and `not_met` only.
        row["expectation_rate"] = (row["expectations_met"] / evaluated) if evaluated else None
    return {"runs_spanning_groups": spanning, "runs_with_unmatched_sessions": unmatched}
