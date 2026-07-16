# session_analytics.watch — testable ingest-then-sleep polling loop core.
#
# `run_watch` is the pure loop behind the `watch` CLI subcommand (E6 polling
# slice, issue #89): each cycle calls `ingest_fn()` then `sleep_fn(interval)`
# (ingest first, so the first cycle is immediate — no upfront sleep). It takes
# no dependency on `ingest/pipeline.py`, the DB, or config — the CLI supplies
# the real `ingest()` closure, `time.sleep`, and a signal-driven `should_stop`;
# tests inject fakes (call counters, recording stubs) for a fully
# deterministic run with no real sleep/DB/signals.
#
# Sleep-count contract (FR-2/FR-7): with a bounded `iterations=N` and no
# `should_stop`, `sleep_fn` is called exactly N times (once after every
# cycle, including the last — bounded runs don't skip a trailing sleep).
# When `should_stop()` becomes true, the trailing sleep for that final cycle
# IS skipped: `should_stop` is checked again immediately after `ingest_fn()`
# returns, and if it is now true the loop stops before calling `sleep_fn`.
#
# Fail-fast first cycle (`fail_fast_first=True`): the VERY FIRST `ingest_fn()`
# call is NOT wrapped in the resilient try/except, so a setup/config error
# (unreachable DB, bad schema) on cycle 0 propagates out of `run_watch`
# instead of being logged-and-retried forever. Every subsequent cycle is
# resilient as usual — a transient failure mid-run never stops the loop.

from __future__ import annotations

import logging
import time

_log = logging.getLogger(__name__)


def run_watch(
    ingest_fn,
    interval,
    *,
    iterations=None,
    sleep_fn=time.sleep,
    should_stop=None,
    fail_fast_first=False,
) -> int:
    """Run an ingest-then-sleep loop; return the number of cycles run.

    Stop conditions, checked BEFORE each cycle: ``iterations`` is not
    ``None`` and that many cycles have already run, or ``should_stop()``
    returns ``True`` (only called when not ``None``).

    Each cycle: ``ingest_fn()`` is called first (wrapped in ``try/except
    Exception`` — FR-3: a single cycle's failure is logged and never stops
    the loop; ``BaseException`` such as ``KeyboardInterrupt``/``SystemExit``
    is never caught here). Then, unless ``should_stop`` just turned true,
    ``sleep_fn(interval)`` runs before the next cycle.

    When ``fail_fast_first`` is true, the first cycle's ``ingest_fn()`` is NOT
    wrapped, so a setup/config error aborts the whole watch instead of looping.
    """
    cycles = 0
    while True:
        if iterations is not None and cycles >= iterations:
            break
        if should_stop is not None and should_stop():
            break

        if fail_fast_first and cycles == 0:
            ingest_fn()  # first cycle is fatal: surface setup/config errors
        else:
            try:
                ingest_fn()
            except Exception:  # noqa: BLE001 — a per-cycle failure must not be fatal
                _log.exception("watch: ingest cycle failed")

        cycles += 1

        if should_stop is not None and should_stop():
            break
        sleep_fn(interval)

    return cycles
