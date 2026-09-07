# session_analytics.pipeline_jobs — run the analysis pipeline from the UI.
#
# The Analysis page used to LIST five commands and offer a button for
# exactly one of them, which left the other four as copy-paste homework
# and gave no way to see what had already run. This makes the pipeline a
# thing you operate: what state each step is in, run one, run them all,
# re-run a step whose inputs changed.
#
# STEPS RUN IN A BACKGROUND THREAD, and that is not optional: building
# the graph over a real corpus took 67 minutes on this machine. Doing
# that inside a request would hit every timeout between the browser and
# uvicorn and leave the user with no idea whether it was still going.
# The UI polls status instead.
#
# SINGLE-FLIGHT PER STEP. Starting `ingest` twice concurrently would have
# two writers on one store; a second request while a step is running is
# refused, not queued, so the caller is told plainly rather than silently
# having their click dropped.

from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any, Callable, Optional

from . import constants as C
from .config import load_config
from .judge.contracts import PARSE_OK
from .judge.rubric import load_rubric
from .relational.db import Database, apply_ddl
from .session_filter import keep_clause, noise_clause

_log = logging.getLogger(__name__)

#: Ordered, because that IS the pipeline: each step consumes what the
#: previous one produced.
STEP_INGEST = "ingest"
STEP_GRAPH = "graph"
STEP_JUDGE = "judge"
STEP_KPIS = "kpis"
STEPS = (STEP_INGEST, STEP_GRAPH, STEP_JUDGE, STEP_KPIS)

#: The whole run, tracked as its own job so the UI can show one overall
#: state and so a page reload does not lose it.
STEP_ALL = "all"

#: Steps a "run everything" performs, IN ORDER. Order is the point: each
#: consumes what the previous produced, so firing them concurrently
#: would build a graph from a half-finished ingest — and, given Kùzu is
#: single-writer, could corrupt the store outright.
RUN_ALL_SEQUENCE = (STEP_INGEST, STEP_GRAPH, STEP_KPIS)

STEP_TITLES = {
    STEP_INGEST: "Load sessions",
    STEP_GRAPH: "Build knowledge graph",
    STEP_JUDGE: "LLM judge",
    STEP_KPIS: "Compute KPIs",
}

STEP_BLURBS = {
    # The ingest blurb is completed at runtime with the ACTUAL source
    # roots — "read copilot transcripts" does not tell you which
    # transcripts, from where, and that is the first thing anyone wants
    # to check before pressing a button that writes to their store.
    STEP_INGEST: "Read copilot transcripts into the database.",
    STEP_GRAPH: "Build the Kùzu graph the Graph and Clusters tabs read.",
    STEP_JUDGE: "Label each turn with an LLM. Optional — everything else works without it.",
    STEP_KPIS: "Roll the labels up into per-session KPIs.",
}

_STATE_IDLE = "idle"
_STATE_RUNNING = "running"
_STATE_DONE = "done"
_STATE_FAILED = "failed"

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}

#: Last node count read when the store was NOT being written. Serves the
#: progress display during a build, so the UI never has a reason to open
#: the graph itself.
_last_graph_nodes = 0


def _remember_graph_nodes(n: int) -> None:
    global _last_graph_nodes
    _last_graph_nodes = n


class StepBusyError(RuntimeError):
    """Raised when a step is asked to start while already running."""


def job_state(step: str) -> dict[str, Any]:
    """Current state, with elapsed time WHILE RUNNING.

    Elapsed used to be filled in only on completion, so a step that takes
    an hour — the graph build over a real corpus does — reported "0s" the
    whole time and was indistinguishable from a hung one. A long job must
    show that it is still moving.
    """
    with _lock:
        job = dict(_jobs.get(step) or {"state": _STATE_IDLE})
    if job.get("state") == _STATE_RUNNING and job.get("started_at"):
        job["seconds"] = round(time.time() - job["started_at"], 1)
    job.pop("started_at", None)
    return job


def set_progress(step: str, progress: dict[str, Any]) -> None:
    """Attach a progress payload to a RUNNING step, for the UI to poll.

    The judge calls a model once per turn and a batch can take minutes;
    a step that only says "running…" the whole time is indistinguishable
    from a hung one. The runner reports after every turn (done/total,
    ok/failed, the last failure's reason) and the payload rides on the
    job so the status endpoint needs no other channel.
    """
    with _lock:
        job = _jobs.get(step)
        if job is not None and job.get("state") == _STATE_RUNNING:
            job["progress"] = dict(progress)


def _run(step: str, fn: Callable[[], str]) -> None:
    started = time.time()
    try:
        message = fn()
        final = {"state": _STATE_DONE, "message": message}
    except Exception as exc:  # noqa: BLE001 — a failed step must not kill the server
        # The full traceback goes to the log; the caller gets the
        # exception text, which is short enough to render and specific
        # enough to act on.
        final = {"state": _STATE_FAILED, "message": f"{type(exc).__name__}: {exc}"}
        traceback.print_exc()
    final["seconds"] = round(time.time() - started, 1)
    with _lock:
        # The last progress payload stays on the finished job, so the
        # counts a user watched do not vanish the moment the step ends.
        progress = (_jobs.get(step) or {}).get("progress")
        if progress is not None:
            final["progress"] = progress
        _jobs[step] = final


def _running(step: str) -> bool:
    return (_jobs.get(step) or {}).get("state") == _STATE_RUNNING


def _begin(step: str) -> None:
    """Mark ``step`` running — the ONE transition into that state, so
    every path (a single step, each step of a run-all) is refused while
    the step, or a run-all that will reach it, is already running. A
    run-all used to set the state unconditionally and could start a
    second judge beside a standalone one: duplicate model calls and two
    writers on the same rows. Caller holds ``_lock``."""
    if _running(step):
        raise StepBusyError(f"{step} is already running")
    if step != STEP_ALL and _running(STEP_ALL):
        raise StepBusyError(f"a run of all steps is in progress; {step} is part of it")
    _jobs[step] = {
        "state": _STATE_RUNNING,
        "message": "",
        "seconds": 0,
        "started_at": time.time(),
    }


def start(step: str, fn: Callable[[], str]) -> None:
    """Begin ``step`` in the background. Refuses if it is already running,
    or a run-all is."""
    with _lock:
        _begin(step)
    threading.Thread(target=_run, args=(step, fn), daemon=True).start()


def start_all(runners: dict[str, Callable[[], str]], *, include_judge: bool) -> None:
    """Run the pipeline end to end, one step at a time.

    SEQUENTIAL, not parallel. An earlier client-side version POSTed every
    step at once; each ran in its own thread, so the graph could start
    against an ingest still in flight. Running them here also means the
    sequence survives closing the page.

    The judge is OPT-IN. It calls a model for every turn and can cost
    real money, so a button labelled "run everything" must not trigger
    it by implication.
    """
    sequence = list(RUN_ALL_SEQUENCE)
    if include_judge:
        sequence.insert(sequence.index(STEP_KPIS), STEP_JUDGE)
    # Refused up front if any step it will run is running now — not
    # discovered mid-sequence after the earlier steps already ran.
    with _lock:
        for step in sequence:
            if step in runners and _running(step):
                raise StepBusyError(f"{step} is already running; wait for it before running all steps")

    def _sequence() -> str:
        done: list[str] = []
        for step in sequence:
            fn = runners.get(step)
            if fn is None:
                continue
            with _lock:
                # A single step started between run-all steps is not
                # overwritten: the sequence stops and says so.
                if _running(step):
                    raise StepBusyError(f"{step} is already running")
                _jobs[step] = {
                    "state": _STATE_RUNNING, "message": "", "seconds": 0,
                    "started_at": time.time(),
                }
            _run(step, fn)
            state = job_state(step)
            if state.get("state") == _STATE_FAILED:
                # Stop at the first failure: continuing would build the
                # next stage from inputs that were never produced.
                raise RuntimeError(
                    f"stopped at '{step}': {state.get('message', 'failed')}"
                )
            done.append(step)
        return f"completed {', '.join(done)}"

    start(STEP_ALL, _sequence)


# ── what has actually been done ────────────────────────────────────────


def status(dsn: str, kuzu_path: str) -> dict[str, Any]:
    """Per-step completion, derived from the data — not from a flag.

    Whether a step has run is a QUESTION ABOUT THE STORE, so it is
    answered by looking: a recorded "we ran ingest" boolean would drift
    the moment anyone used the CLI, which is the normal way half of this
    pipeline gets driven.
    """
    counts = {
        "sessions": 0, "excluded_noise": 0, "labels": 0, "label_failures": 0,
        "kpis": 0, "graph_nodes": 0,
    }
    # Zero counts from a store that did not answer are not a measurement.
    # The flag lets a page say "not reachable" instead of "0 sessions".
    store_reachable = False
    try:
        db = Database.connect(dsn)
        try:
            apply_ddl(db)
            # `sessions` is the count worth showing — the same figure the
            # Dashboard and the Sessions page use — and `excluded_noise`
            # is what the funnel's first cell says was left out (#307).
            noise = load_config().noise
            keep_sql, keep_params = keep_clause(noise, "s")
            noise_sql, noise_params = noise_clause(noise, "s")
            counts["sessions"] = int(
                (db.query_one(
                    f"SELECT COUNT(*) FROM copilot_session s WHERE {keep_sql}", keep_params
                ) or (0,))[0] or 0
            )
            counts["excluded_noise"] = int(
                (db.query_one(
                    f"SELECT COUNT(*) FROM copilot_session s WHERE {noise_sql}", noise_params
                ) or (0,))[0] or 0
            )
            # COUNT ONLY LABELS THAT PARSED. A row whose parse_status is
            # an error carries all-NULL labels — it is a record that the
            # judge was ATTEMPTED, not that anything was labelled.
            # Counting rows made 50 backend failures look like 50
            # labelled turns and put a green check on the step.
            # The packaged rubric's run only (#313): a validation re-run
            # under another name must not double the funnel's count.
            rubric_name = load_rubric().name
            counts["labels"] = int(
                (
                    db.query_one(
                        f"SELECT COUNT(*) FROM {C.TBL_HEURISTIC_LABEL} "
                        f"WHERE parse_status = ? AND rubric_name = ?",
                        (PARSE_OK, rubric_name),
                    )
                    or (0,)
                )[0]
                or 0
            )
            counts["label_failures"] = int(
                (
                    db.query_one(
                        f"SELECT COUNT(*) FROM {C.TBL_HEURISTIC_LABEL} "
                        f"WHERE parse_status <> ? AND rubric_name = ?",
                        (PARSE_OK, rubric_name),
                    )
                    or (0,)
                )[0]
                or 0
            )
            counts["kpis"] = int(
                (db.query_one("SELECT COUNT(*) FROM session_kpi") or (0,))[0] or 0
            )
            store_reachable = True
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — an unreachable store means "nothing done"
        _log.warning("pipeline status: store not reachable: %s", exc)

    # NEVER OPEN THE GRAPH WHILE IT IS BEING BUILT. Kùzu is
    # single-writer, and this function is polled every couple of seconds
    # by the UI — so a "harmless" progress read opened a second
    # connection against a store mid-rebuild and CORRUPTED it, losing an
    # hour of build. Monitoring must not touch what it is monitoring.
    graph_built = False
    if job_state(STEP_GRAPH).get("state") == _STATE_RUNNING:
        counts["graph_nodes"] = _last_graph_nodes
    else:
        try:
            from .graph.schema import GraphDatabase
            from .graph import query as gq

            g = GraphDatabase.connect(kuzu_path)
            try:
                nodes = gq.node_counts(g)
                counts["graph_nodes"] = sum(int(v or 0) for v in nodes.values())
                graph_built = True
            finally:
                g.close()
            _remember_graph_nodes(counts["graph_nodes"])
        except Exception:  # noqa: BLE001 — absent, unbuilt or unreadable
            graph_built = False

    # Where ingest would actually read from, resolved the same way the
    # ingest itself resolves it.
    sources: list[str] = []
    try:
        from ._register import register_all
        from .registry import list_adapter_ids
        from pathlib import Path as _P

        register_all()
        cfg = load_config()
        for copilot in list_adapter_ids():
            root = cfg.source_root(copilot)
            if root and _P(root).expanduser().is_dir():
                sources.append(f"{copilot}: {root}")
    except Exception:  # noqa: BLE001 — detection must never break status
        sources = []

    done = {
        # "Done" means the user has something to look at. A store holding
        # only noise (a probe run, a demo row) shows "Re-run load sessions"
        # to someone who has loaded nothing — the step is not done until
        # a session worth counting is in.
        STEP_INGEST: counts["sessions"] > 0,
        STEP_GRAPH: graph_built and counts["graph_nodes"] > 0,
        STEP_JUDGE: counts["labels"] > 0,
        STEP_KPIS: counts["kpis"] > 0,
    }
    return {
        "steps": [
            {
                "id": step,
                "title": STEP_TITLES[step],
                "blurb": (
                    STEP_BLURBS[step]
                    + (
                        " Reading from — " + "; ".join(sources)
                        if step == STEP_INGEST and sources
                        else ""
                    )
                    + (
                        " No copilot session folders found."
                        if step == STEP_INGEST and not sources
                        else ""
                    )
                ),
                "done": done[step],
                "optional": step == STEP_JUDGE,
                "job": job_state(step),
            }
            for step in STEPS
        ],
        "counts": counts,
        "store_reachable": store_reachable,
        "all": job_state(STEP_ALL),
    }
