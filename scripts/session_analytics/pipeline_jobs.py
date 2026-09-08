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
STEP_CORRELATE = "correlate"
STEP_GRAPH = "graph"
STEP_EMBED = "embed"
STEP_SIMILAR = "similar"
STEP_JUDGE = "judge"
STEP_KPIS = "kpis"
#: correlate sits right after ingest: a benchmark-linked session is
#: never noise, so links must exist before the graph decides what to
#: leave out.
STEPS = (STEP_INGEST, STEP_CORRELATE, STEP_GRAPH, STEP_EMBED, STEP_SIMILAR, STEP_JUDGE, STEP_KPIS)

#: Steps that WRITE the Kùzu store. Kùzu is single-writer: status must
#: not open the store while one of these runs (it corrupted a build
#: once), and they must never run beside each other.
GRAPH_WRITING_STEPS = (STEP_GRAPH, STEP_SIMILAR)

#: The whole run, tracked as its own job so the UI can show one overall
#: state and so a page reload does not lose it.
STEP_ALL = "all"

#: Steps a "run everything" performs, IN ORDER. Order is the point: each
#: consumes what the previous produced, so firing them concurrently
#: would build a graph from a half-finished ingest — and, given Kùzu is
#: single-writer, could corrupt the store outright.
RUN_ALL_SEQUENCE = (STEP_INGEST, STEP_CORRELATE, STEP_GRAPH, STEP_EMBED, STEP_SIMILAR, STEP_KPIS)

STEP_TITLES = {
    STEP_INGEST: "Load sessions",
    STEP_CORRELATE: "Link benchmark runs",
    STEP_GRAPH: "Build knowledge graph",
    STEP_EMBED: "Embed sessions",
    STEP_SIMILAR: "Find similar sessions",
    STEP_JUDGE: "LLM judge",
    STEP_KPIS: "Compute KPIs",
}

STEP_BLURBS = {
    # The ingest blurb is completed at runtime with the ACTUAL source
    # roots — "read copilot transcripts" does not tell you which
    # transcripts, from where, and that is the first thing anyone wants
    # to check before pressing a button that writes to their store.
    STEP_INGEST: "Read copilot transcripts into the database.",
    # Completed at runtime with the configured runs root, or the fact
    # that there is none (then Run all skips it and says so).
    STEP_CORRELATE: "Link the benchmark harness's run records to the sessions they produced, and store each attempt's pass/fail — what the Benchmark tab shows.",
    STEP_GRAPH: "Build the Kùzu graph the Graph tab explores — the same sessions the Sessions list shows (noise left out).",
    STEP_EMBED: "Turn each session into a vector with the embedding model configured under Settings → Embeddings, so sessions can be compared by meaning.",
    STEP_SIMILAR: "Link each session to its nearest neighbours in the graph — what the Similar tab on a session page shows.",
    STEP_JUDGE: "Label each turn with the judge configured under Settings → LLM-as-Judge.",
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
_last_similar_edges = 0


def _remember_graph_nodes(n: int, edges: int = 0) -> None:
    global _last_graph_nodes, _last_similar_edges
    _last_graph_nodes = n
    _last_similar_edges = edges


class StepSkipped(Exception):
    """A step that has nothing to do BY CONFIGURATION (no benchmark runs
    root set): it ends done with the reason as its message, so Run all
    carries on and the page says why nothing happened."""


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
    except StepSkipped as exc:
        final = {"state": _STATE_DONE, "message": f"skipped: {exc}", "skipped": True}
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


def _busy_reason(step: str) -> Optional[str]:
    """Why ``step`` may not start now: it is running, or another step
    that writes the same resource is. Kùzu is single-writer, so the
    graph build and the similarity pass exclude each other — a rebuild
    beside an embed→similar subset once had both writing. None = free."""
    if _running(step):
        return f"{step} is already running"
    if step in GRAPH_WRITING_STEPS:
        for other in GRAPH_WRITING_STEPS:
            if other != step and _running(other):
                return f"{other} is writing the graph; {step} must wait for it"
    return None


def _begin(step: str) -> None:
    """Mark ``step`` running — the ONE transition into that state, so
    every path (a single step, each step of a run-all) is refused while
    the step, or a run-all that will reach it, is already running. A
    run-all used to set the state unconditionally and could start a
    second judge beside a standalone one: duplicate model calls and two
    writers on the same rows. Caller holds ``_lock``."""
    reason = _busy_reason(step)
    if reason:
        raise StepBusyError(reason)
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


def start_all(
    runners: dict[str, Callable[[], str]], *, include_judge: bool, only: Optional[list[str]] = None,
) -> None:
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
    if only:
        # An ordered SUBSET (the Similar tab runs embed + similar): the
        # pipeline's order is kept whatever order the caller named.
        unknown = [s for s in only if s not in STEPS]
        if unknown:
            raise ValueError(f"unknown step(s): {', '.join(unknown)}")
        sequence = [s for s in STEPS if s in only]
    # Refused up front if any step it will run is running now — not
    # discovered mid-sequence after the earlier steps already ran.
    with _lock:
        for step in sequence:
            reason = _busy_reason(step) if step in runners else None
            if reason:
                raise StepBusyError(f"{reason}; wait for it before running these steps")

    def _sequence() -> str:
        done: list[str] = []
        for step in sequence:
            fn = runners.get(step)
            if fn is None:
                continue
            with _lock:
                # A single step started between run-all steps is not
                # overwritten: the sequence stops and says so.
                reason = _busy_reason(step)
                if reason:
                    raise StepBusyError(reason)
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


def benchmark_runs_root() -> dict[str, Any]:
    """The configured benchmark runs root and whether it can be read:
    {path, configured, is_dir}. One reader for the Analysis blurb, the
    Benchmark page and the step itself."""
    from pathlib import Path as _P

    path = load_config().benchmark_runs_root
    return {
        "path": path,
        "configured": bool(path),
        "is_dir": bool(path) and _P(path).is_dir(),
    }


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
        "kpis": 0, "graph_nodes": 0, "embedded": 0, "similar_edges": 0,
        "benchmark_linked": 0, "benchmark_results": 0,
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
            counts["benchmark_linked"] = int(
                (db.query_one(
                    f"SELECT COUNT(*) FROM copilot_session s WHERE s.{C.COL_BENCHMARK_RUN_DIR} IS NOT NULL"
                ) or (0,))[0] or 0
            )
            counts["benchmark_results"] = int(
                (db.query_one(f"SELECT COUNT(*) FROM {C.TBL_BENCHMARK_RESULT}") or (0,))[0] or 0
            )
            counts["kpis"] = int(
                (db.query_one("SELECT COUNT(*) FROM session_kpi") or (0,))[0] or 0
            )
            # Sessions the embed step has a vector for — over the SAME
            # sessions the funnel counts, so "57 embedded of 57" lines up.
            counts["embedded"] = int(
                (db.query_one(
                    f"SELECT COUNT(*) FROM copilot_session s WHERE {keep_sql} "
                    "AND s.session_embedding IS NOT NULL", keep_params,
                ) or (0,))[0] or 0
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
    if any(job_state(s).get("state") == _STATE_RUNNING for s in GRAPH_WRITING_STEPS):
        counts["graph_nodes"] = _last_graph_nodes
        counts["similar_edges"] = _last_similar_edges
    else:
        try:
            from .graph.schema import GraphDatabase
            from .graph import query as gq

            g = GraphDatabase.connect(kuzu_path)
            try:
                nodes = gq.node_counts(g)
                counts["graph_nodes"] = sum(int(v or 0) for v in nodes.values())
                counts["similar_edges"] = gq.similar_edge_count(g)
                graph_built = True
            finally:
                g.close()
            _remember_graph_nodes(counts["graph_nodes"], counts["similar_edges"])
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
        STEP_CORRELATE: counts["benchmark_linked"] > 0 or counts["benchmark_results"] > 0,
        STEP_GRAPH: graph_built and counts["graph_nodes"] > 0,
        STEP_EMBED: counts["embedded"] > 0,
        STEP_SIMILAR: graph_built and counts["similar_edges"] > 0,
        STEP_JUDGE: counts["labels"] > 0,
        STEP_KPIS: counts["kpis"] > 0,
    }
    runs_root = benchmark_runs_root()
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
                    + (
                        (f" Runs root: {runs_root['path']}" if runs_root["is_dir"]
                         else f" Runs root is not a directory: {runs_root['path']}")
                        if step == STEP_CORRELATE and runs_root["configured"]
                        else (" No runs root configured (Settings → Benchmarks); Run all skips this step."
                              if step == STEP_CORRELATE else "")
                    )
                ),
                "done": done[step],
                # Every step is part of the pipeline; the judge is not
                # marked "optional" — the owner's word: it confused.
                "optional": False,
                "job": job_state(step),
            }
            for step in STEPS
        ],
        "counts": counts,
        "store_reachable": store_reachable,
        "all": job_state(STEP_ALL),
    }
