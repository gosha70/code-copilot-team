# session_analytics.expectations — #371 A5: what a run was required to
# achieve, and how it came out.
#
# An unattended auto-build run is admitted only after
# `validate-spec.sh --unattended` proves every FR-N in spec.md maps to an
# executable verifier; the driver freezes each requirement's
# `statement_sha` into the ledger and records per-verifier outcomes at
# the landing gate. This module reads those artifacts so they outlive
# the ledger directory, which is archived and pruned.
#
# Four things here are load-bearing, and each exists because the ledger
# is thinner than it looks:
#
# * `run_fingerprint` — `attempt_id` is the driver's `$$-$RANDOM$RANDOM`,
#   so two runs of one feature can share it, and with an unchanged spec
#   they share a contract digest too. Only immutable per-run facts tell
#   them apart.
# * `recover_statements` — the frozen contract carries `statement_sha`
#   but NOT the requirement text. It is recovered from spec.md at the
#   run's `branch_base_ref` and accepted only on a hash match, because
#   the working tree may have changed since admission.
# * `normalize_state` — the driver's `green` collapses in both
#   directions: a bound that was hit reads false, and a WAIVED visual
#   entry reads true though it was never verified.
# * unevaluated — an expectation with no result row has no recoverable
#   consolidated result. That is not "no verifier ran": an unwaived
#   visual skip aborts the gate before anything is written.

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import constants as C
from .relational.db import now_iso

_log = logging.getLogger(__name__)

#: The repository this package ships in — the source of the ONE FR
#: parser. A ledger may belong to another project, so the spec text is
#: read from that project while the parser always comes from here.
_PACKAGE_REPO = Path(__file__).resolve().parents[2]
_VERIFICATION_LIB = _PACKAGE_REPO / "scripts" / "lib" / "verification-common.sh"

#: The ONLY shapes that mean "this requirement was really not met".
#: Everything else a driver might write — a bound that was hit, a run
#: that could not be bounded, `unreached`, a malformed detail, or any
#: future wording this code has never seen — normalizes to `unknown`.
#:
#: The default is deliberately conservative and the inversion matters:
#: matching "inconclusive" shapes and defaulting the rest to `not_met`
#: would mean a reword in `auto-build-loop.sh` silently turns "we could
#: not tell" into "it failed", reporting a failure that never happened.
#: Defaulting to `unknown` makes the same drift show up as missing
#: coverage instead, which is visible and harmless.
_NEGATIVE_CONFORMANCE_DETAIL = "fail"
#: The driver writes `exit $rc` where $rc is a shell exit status, so a
#: leading sign is not a shape it produces; anything else falls through
#: to `unknown` rather than being read as a failure.
_EXIT_DETAIL_RE = re.compile(r"^exit\s+(\d+)$")


@dataclass(frozen=True)
class LedgerRun:
    """One run's ledger, as far as A5 reads it."""

    feature_id: str
    attempt_id: str
    ledger_path: Path
    ledger_root: str
    branch_base_ref: Optional[str]
    status: Optional[str]
    outcome: Optional[str]
    contract: dict[str, Any]
    results: dict[str, Any]
    init_event: Optional[dict[str, Any]]
    evaluated_at: Optional[str]
    sessions: tuple[tuple[str, Optional[int]], ...] = ()


@dataclass
class SkipReason:
    """A ledger directory A5 declined to store, and why. Never silent."""

    path: str
    reason: str


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── fingerprints ───────────────────────────────────────────────────────


def contract_fingerprint(contract: dict[str, Any]) -> str:
    """A digest over the frozen contract's ordered ``(fr, statement_sha)``
    pairs: what this run was required to satisfy."""
    pairs = [
        f"{v.get('fr')}\t{v.get('statement_sha')}"
        for v in _verifier_set(contract)
    ]
    return _digest("\n".join(sorted(pairs)))


def run_fingerprint(run: "LedgerRun") -> Optional[str]:
    """Identity for one RUN, not one contract.

    Two runs of the same feature can share `attempt_id` (it is
    `$$-$RANDOM$RANDOM`), and if neither the spec nor the verifiers
    changed they share a contract digest too — so comparing contracts
    alone would merge two real runs and overwrite the first's results.
    This digests facts that differ between two real runs in every case
    but one: the first `init` event's timestamp and detail (which
    carries profile, branch and base), the base commit, and the
    contract digest. NOT a guarantee of uniqueness — two runs that
    collide on `attempt_id`, start in the same second, branch from the
    same commit and carry an identical contract are indistinguishable
    here. That residual is accepted rather than solved; what this does
    guarantee is that a DIFFERING run is never silently merged.

    None when the ledger has no readable `init` event: the caller skips
    such a run rather than storing it under a weaker identity.
    """
    if not run.init_event:
        return None
    parts = (
        str(run.init_event.get("ts") or ""),
        str(run.init_event.get("detail") or ""),
        str(run.branch_base_ref or ""),
        contract_fingerprint(run.contract),
    )
    if not parts[0] and not parts[1]:
        return None
    return _digest("\u0000".join(parts))


def _verifier_set(contract: dict[str, Any]) -> list[dict[str, Any]]:
    entries = ((contract.get("verifiers") or {}).get("set"))
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


# ── reading a ledger ───────────────────────────────────────────────────


def read_ledger(ledger: Path, ledger_root: str) -> tuple[Optional[LedgerRun], Optional[SkipReason]]:
    """One run, or the reason it is not storable. Never raises."""
    state = _read_json(ledger / C.LEDGER_STATE_FILE)
    if not isinstance(state, dict):
        return None, SkipReason(str(ledger), f"no readable {C.LEDGER_STATE_FILE}")
    attempt_id = state.get("attempt_id")
    feature_id = state.get("feature_id") or ledger.name
    if not isinstance(attempt_id, str) or not attempt_id:
        return None, SkipReason(str(ledger), "no attempt_id")

    contract = ((state.get("preflight") or {}).get("contract")) or {}
    if not _verifier_set(contract):
        frozen = _read_json(ledger / C.LEDGER_FROZEN_CONTRACT_FILE)
        contract = frozen if isinstance(frozen, dict) else {}
    if not _verifier_set(contract):
        # A refused admission never created a ledger, so this is a run
        # that was never admitted against a contract: nothing to store.
        return None, SkipReason(str(ledger), "no frozen contract")

    events = _read_events(ledger)
    init_event = next((e for e in events if e.get("event") == C.LEDGER_EVENT_INIT), None)
    gate = next(
        (e for e in reversed(events) if e.get("event") == C.LEDGER_EVENT_VERIFIER_GATE), None
    )
    results = _read_json(ledger / C.LEDGER_VERIFICATION_FILE)
    return (
        LedgerRun(
            feature_id=str(feature_id),
            attempt_id=attempt_id,
            ledger_path=ledger,
            ledger_root=ledger_root,
            branch_base_ref=_opt_str(state.get("branch_base_ref")),
            status=_opt_str(state.get("status")),
            outcome=_opt_str(state.get("outcome")),
            contract=contract,
            results=results if isinstance(results, dict) else {},
            init_event=init_event,
            # Journalled ONLY after an all-green gate: a run with any
            # failing requirement legitimately has none. Never a proxy
            # for "was this evaluated", never defaulted to ingest time.
            evaluated_at=_opt_str(gate.get("ts")) if gate else None,
            sessions=tuple(_discover_sessions(ledger)),
        ),
        None,
    )


def _read_events(ledger: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with (ledger / C.LEDGER_EVENTS_FILE).open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        return []
    return out


def _discover_sessions(ledger: Path) -> list[tuple[str, Optional[int]]]:
    """Every session id the ledger's phase results recorded, with the
    phase directory it was found under (provenance, never a key).

    The id is the driver's own — the `system`/`init` event of a
    `build-result-*.json` — not a guess from timing or project."""
    found: dict[str, Optional[int]] = {}
    for phase_dir in sorted(ledger.glob(f"{C.LEDGER_PHASE_DIR_PREFIX}*")):
        if not phase_dir.is_dir():
            continue
        try:
            phase_num: Optional[int] = int(phase_dir.name[len(C.LEDGER_PHASE_DIR_PREFIX):])
        except ValueError:
            phase_num = None
        for result in sorted(phase_dir.glob(C.LEDGER_BUILD_RESULT_GLOB)):
            payload = _read_json(result)
            events = payload if isinstance(payload, list) else [payload]
            for event in events:
                if not isinstance(event, dict):
                    continue
                sid = event.get("session_id")
                if isinstance(sid, str) and sid and sid not in found:
                    found[sid] = phase_num
    return list(found.items())


def _opt_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


# ── the admitted statement ─────────────────────────────────────────────


def recover_statements(
    project_dir: Path, feature_id: str, branch_base_ref: Optional[str]
) -> dict[str, str]:
    """``{FR-N: statement}`` as spec.md read at ``branch_base_ref``.

    The frozen contract carries no statement text, and the working
    tree's may have changed since admission — presenting that as what
    was admitted is the history-rewriting admission exists to prevent.
    So the text is read at the run's base commit and the caller accepts
    an entry ONLY when its recomputed hash equals the frozen
    `statement_sha` (see `accept_statement`).

    The parser is `vc_extract_frs` from this package's own repository —
    the one extractor admission itself used, never a second
    implementation that could disagree with it. An unreachable commit,
    an absent file, a missing bash or a missing library all yield an
    empty mapping, and every statement is then recorded as unavailable.
    """
    if not branch_base_ref or not _VERIFICATION_LIB.is_file():
        return {}
    try:
        spec = subprocess.run(
            ["git", "-C", str(project_dir), "show",
             f"{branch_base_ref}:specs/{feature_id}/spec.md"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if spec.returncode != 0 or not spec.stdout:
        return {}
    try:
        parsed = subprocess.run(
            ["bash", "-c",
             f'source {_shell_quote(str(_VERIFICATION_LIB))} && vc_extract_frs /dev/stdin'],
            input=spec.stdout, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if parsed.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in parsed.stdout.splitlines():
        fr, _, statement = line.partition("\t")
        if fr and statement:
            out[fr] = statement
    return out


def statement_sha(fr: str, statement: str) -> str:
    """The admission primitive: sha256 over ``"FR-N: <statement>"``.
    Reimplemented here only as the hash of a string the bash library
    already normalized — the NORMALIZATION is never duplicated."""
    return _digest(f"{fr}: {statement}")


def accept_statement(fr: str, statement: Optional[str], frozen_sha: str) -> tuple[Optional[str], str]:
    """``(statement, source)``: the text only when it hashes to the sha
    frozen at admission, else ``(None, 'unavailable')``. A mismatch is
    not a smaller problem than an absence — it means the recovered text
    is not what was admitted."""
    if statement is None:
        return None, C.STATEMENT_SOURCE_UNAVAILABLE
    if statement_sha(fr, statement) != frozen_sha:
        return None, C.STATEMENT_SOURCE_UNAVAILABLE
    return statement[: C.EXPECTATION_STATEMENT_MAX_CHARS], C.STATEMENT_SOURCE_RECOVERED


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


# ── normalization ──────────────────────────────────────────────────────


def normalize_state(
    *, kind: str, green: Optional[bool], waived: Optional[bool], detail: Optional[str]
) -> str:
    """One verifier's outcome as ``met`` / ``not_met`` / ``unknown``.

    Reads exactly three raw fields, in this order, and the order is the
    definition:

    1. ``waived`` — WAIVED IS TESTED BEFORE ``green``. The driver writes
       a waived visual entry ``green: true``, while its own comment is
       that a waived invocation is never indistinguishable from full
       verification. Waived means *not verified*, so it is ``unknown``;
       trusting ``green`` first would report it as ``met``.
    2. ``green`` true — ``met``.
    3. Otherwise ``not_met`` ONLY for a shape known to mean a real
       negative: a deterministic ``exit <nonzero>``, or a conformance or
       visual verdict of ``fail``. Everything else is ``unknown`` — a
       bound that was hit, a run that could not be bounded, a visual
       ``unreached``, a missing or malformed ``detail``, an unfamiliar
       verifier kind, and any wording a future driver invents.

    The conservative default is the point. The exit code is not stored,
    so step 3 reads prose; if this matched "inconclusive" wording and
    defaulted the rest to ``not_met``, a reword in ``auto-build-loop.sh``
    would silently report requirements as failed that were never
    judged. Defaulting to ``unknown`` turns the same drift into visible
    missing coverage instead. The raw ``green`` and ``detail`` are
    stored beside the state so the derivation stays auditable.

    An expectation with no result row at all is UNEVALUATED, which this
    function never returns: the absence of rows is the fact.
    """
    if waived:
        return C.EXPECTATION_UNKNOWN
    if green:
        return C.EXPECTATION_MET
    text = (detail or "").strip().lower()
    if kind == C.VERIFIER_KIND_DETERMINISTIC:
        match = _EXIT_DETAIL_RE.match(text)
        if match and int(match.group(1)) != 0:
            return C.EXPECTATION_NOT_MET
    elif kind in (C.VERIFIER_KIND_CONFORMANCE, C.VERIFIER_KIND_VISUAL):
        if text == _NEGATIVE_CONFORMANCE_DETAIL:
            return C.EXPECTATION_NOT_MET
    return C.EXPECTATION_UNKNOWN


def roll_up(states: list[str]) -> Optional[str]:
    """One expectation's state from its verifiers'.

    ``met`` only when every verifier is ``met`` — the driver's own rule
    (an FR is green iff all its verifiers are). ``not_met`` when any is;
    ``unknown`` when results exist and none failed but at least one
    established nothing. ``None`` means UNEVALUATED: no recoverable
    consolidated result, which is not the same as a verifier that ran
    and told us nothing.
    """
    if not states:
        return None
    if any(s == C.EXPECTATION_NOT_MET for s in states):
        return C.EXPECTATION_NOT_MET
    if any(s == C.EXPECTATION_UNKNOWN for s in states):
        return C.EXPECTATION_UNKNOWN
    return C.EXPECTATION_MET


# ── the results file ───────────────────────────────────────────────────


@dataclass
class ResultRow:
    kind: str
    verifier: Optional[str]
    green: Optional[bool]
    waived: Optional[bool]
    state: str
    detail: Optional[str]
    evidence: Optional[str]
    log_path: Optional[str]


def results_for(run: LedgerRun, fr: str) -> list[ResultRow]:
    """Every recorded verifier outcome for one requirement; empty when
    the run has no recoverable consolidated result for it."""
    entry = (run.results.get("frs") or {}).get(fr) if isinstance(run.results, dict) else None
    verifiers = (entry or {}).get("verifiers") if isinstance(entry, dict) else None
    if not isinstance(verifiers, list):
        return []
    rows: list[ResultRow] = []
    for raw in verifiers:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        green = raw.get("green")
        waived = raw.get("waived")
        detail = raw.get("detail")
        rows.append(
            ResultRow(
                kind=kind,
                verifier=_cap(raw.get("verifier"), C.EXPECTATION_VERIFIER_MAX_CHARS),
                green=bool(green) if isinstance(green, bool) else None,
                waived=bool(waived) if isinstance(waived, bool) else None,
                state=normalize_state(
                    kind=kind,
                    green=green if isinstance(green, bool) else None,
                    waived=bool(waived) if isinstance(waived, bool) else None,
                    detail=detail if isinstance(detail, str) else None,
                ),
                detail=_cap(detail, C.EXPECTATION_DETAIL_MAX_CHARS),
                evidence=_cap(raw.get("evidence"), C.EXPECTATION_EVIDENCE_MAX_CHARS),
                log_path=_cap(raw.get("log"), 1000),
            )
        )
    return rows


def _cap(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    return value[:limit]


# ── the pass ───────────────────────────────────────────────────────────


@dataclass
class IngestStats:
    """What one pass did, reported in full — a skipped run is never
    silent, and an unresolved session is a counted fact, not a gap."""

    runs_seen: int = 0
    runs_stored: int = 0
    runs_skipped: int = 0
    expectations_stored: int = 0
    results_stored: int = 0
    statements_recovered: int = 0
    statements_unavailable: int = 0
    sessions_recorded: int = 0
    sessions_resolved: int = 0
    sessions_unresolved: int = 0
    skipped: list[SkipReason] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k != "skipped"}
        out["skipped"] = [{"path": s.path, "reason": s.reason} for s in self.skipped]
        return out


def ingest_runs(db, ledger_root: Path, *, project_dir: Optional[Path] = None) -> IngestStats:
    """Store every storable run under ``ledger_root``'s two subdirs.

    Idempotent on the natural keys. Three things it refuses to do:
    store a run whose identity it cannot establish (no `attempt_id`, no
    frozen contract, no `init` event); overwrite a stored run whose
    `run_fingerprint` differs from the one on disk (an `attempt_id`
    collision — reported, never merged); and invent a session link for
    a transcript the store does not hold (the row is written with a
    NULL `session_ref`, which a later pass resolves).
    """
    stats = IngestStats()
    project = project_dir or ledger_root.parent
    for sub in C.AUTO_BUILD_SUBDIRS:
        base = ledger_root / sub
        if not base.is_dir():
            continue
        for ledger in sorted(p for p in base.iterdir() if p.is_dir()):
            stats.runs_seen += 1
            run, skip = read_ledger(ledger, sub)
            if run is None:
                stats.runs_skipped += 1
                stats.skipped.append(skip)
                continue
            fingerprint = run_fingerprint(run)
            if fingerprint is None:
                stats.runs_skipped += 1
                stats.skipped.append(
                    SkipReason(str(ledger), f"no readable {C.LEDGER_EVENT_INIT} event")
                )
                continue
            if not _store_run(db, run, fingerprint, project, stats):
                stats.runs_skipped += 1
                continue
            stats.runs_stored += 1
    db.commit()
    return stats


def _store_run(db, run: LedgerRun, fingerprint: str, project: Path, stats: IngestStats) -> bool:
    existing = db.query_one(
        f"SELECT id, run_fingerprint FROM {C.TBL_EXPECTATION_RUN} "
        "WHERE feature_id = ? AND attempt_id = ?",
        (run.feature_id, run.attempt_id),
    )
    if existing is not None and existing[1] != fingerprint:
        # Two different runs answering to one attempt_id. Storing the
        # second over the first would destroy its results silently.
        stats.skipped.append(
            SkipReason(
                str(run.ledger_path),
                f"attempt_id {run.attempt_id!r} already stored for {run.feature_id!r} "
                "with a different run_fingerprint; refusing to overwrite",
            )
        )
        return False

    now = now_iso()
    contract_fp = contract_fingerprint(run.contract)
    if existing is None:
        run_ref = db.insert_returning_id(
            f"""
            INSERT INTO {C.TBL_EXPECTATION_RUN}
                (feature_id, attempt_id, run_fingerprint, contract_fingerprint,
                 branch_base_ref, ledger_path, ledger_root, status, outcome,
                 evaluated_at, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (run.feature_id, run.attempt_id, fingerprint, contract_fp,
             run.branch_base_ref, str(run.ledger_path), run.ledger_root,
             run.status, run.outcome, run.evaluated_at, now),
        )
    else:
        run_ref = int(existing[0])
        # The ledger is the source of truth for a run that is still
        # moving: status, outcome and the gate time may have advanced.
        db.execute(
            f"UPDATE {C.TBL_EXPECTATION_RUN} SET status = ?, outcome = ?, "
            "evaluated_at = ?, ledger_path = ?, ledger_root = ? WHERE id = ?",
            (run.status, run.outcome, run.evaluated_at, str(run.ledger_path),
             run.ledger_root, run_ref),
        )

    statements = recover_statements(project, run.feature_id, run.branch_base_ref)
    for verifier in _verifier_set(run.contract):
        fr = verifier.get("fr")
        frozen_sha = verifier.get("statement_sha")
        if not isinstance(fr, str) or not isinstance(frozen_sha, str):
            continue
        text, source = accept_statement(fr, statements.get(fr), frozen_sha)
        if source == C.STATEMENT_SOURCE_RECOVERED:
            stats.statements_recovered += 1
        else:
            stats.statements_unavailable += 1
        row = db.query_one(
            f"SELECT id, statement, statement_source FROM {C.TBL_EXPECTATION} "
            "WHERE run_ref = ? AND fr = ?", (run_ref, fr)
        )
        rows = results_for(run, fr)
        if row is None:
            exp_ref = db.insert_returning_id(
                f"""
                INSERT INTO {C.TBL_EXPECTATION}
                    (run_ref, fr, statement_sha, statement, statement_source, verifier_count)
                VALUES (?, ?, ?, ?, ?, ?) RETURNING id
                """,
                (run_ref, fr, frozen_sha, text, source, len(rows)),
            )
            stats.expectations_stored += 1
        else:
            exp_ref = int(row[0])
            # A RECOVERED statement is never demoted to unavailable. The
            # base commit can be garbage-collected, the pass can be run
            # with the wrong --project-dir, or the parser can go missing;
            # any of those makes a later recovery fail, and overwriting
            # with NULL would erase the durable record this table exists
            # to keep. Only unavailable → recovered, or one verified
            # recovery replaced by another.
            if source == C.STATEMENT_SOURCE_UNAVAILABLE and \
                    row[2] == C.STATEMENT_SOURCE_RECOVERED:
                text, source = row[1], C.STATEMENT_SOURCE_RECOVERED
                stats.statements_unavailable -= 1
                stats.statements_recovered += 1
            db.execute(
                f"UPDATE {C.TBL_EXPECTATION} SET statement = ?, statement_source = ?, "
                "verifier_count = ? WHERE id = ?",
                (text, source, len(rows), exp_ref),
            )
        stats.results_stored += _store_results(db, exp_ref, rows, now)
    stats.sessions_recorded += _store_sessions(db, run_ref, run, now, stats)
    return True


def _store_results(db, exp_ref: int, rows: list[ResultRow], now: str) -> int:
    """Upsert this expectation's verifier outcomes, and REMOVE any row
    beyond the current count.

    Results are keyed by position, so a later pass that sees fewer
    verifiers would otherwise leave the surplus behind — and `roll_up`
    reads every stored row, so one stale `not_met` turns a requirement
    that is now met into a failure. Deleting the tail keeps the stored
    outcomes equal to the ledger's, which is the only thing they are
    allowed to be.
    """
    db.execute(
        f"DELETE FROM {C.TBL_EXPECTATION_RESULT} "
        "WHERE expectation_ref = ? AND verifier_ordinal >= ?",
        (exp_ref, len(rows)),
    )
    stored = 0
    for ordinal, row in enumerate(rows):
        present = db.query_one(
            f"SELECT id FROM {C.TBL_EXPECTATION_RESULT} "
            "WHERE expectation_ref = ? AND verifier_ordinal = ?",
            (exp_ref, ordinal),
        )
        values = (row.kind, row.verifier, row.green, row.waived, row.state,
                  row.detail, row.evidence, row.log_path)
        if present is None:
            db.execute(
                f"""
                INSERT INTO {C.TBL_EXPECTATION_RESULT}
                    (expectation_ref, verifier_ordinal, kind, verifier, green, waived,
                     state, detail, evidence, log_path, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (exp_ref, ordinal) + values + (now,),
            )
            stored += 1
        else:
            db.execute(
                f"UPDATE {C.TBL_EXPECTATION_RESULT} SET kind = ?, verifier = ?, green = ?, "
                "waived = ?, state = ?, detail = ?, evidence = ?, log_path = ? WHERE id = ?",
                values + (int(present[0]),),
            )
    return stored


def _store_sessions(db, run_ref: int, run: LedgerRun, now: str, stats: IngestStats) -> int:
    """One row per session id the ledger recorded, keyed by the
    DISCOVERED identity. `session_ref` is resolved when the store holds
    that transcript and left NULL when it does not — a later pass
    resolves it, and coverage can tell "recorded but not ingested" from
    "no session recorded"."""
    recorded = 0
    for session_id, phase_num in run.sessions:
        match = db.query_one(
            "SELECT id FROM copilot_session WHERE copilot = ? AND session_id = ?",
            (C.COPILOT_CLAUDE_CODE, session_id),
        )
        session_ref = int(match[0]) if match else None
        if session_ref is None:
            stats.sessions_unresolved += 1
        else:
            stats.sessions_resolved += 1
        present = db.query_one(
            f"SELECT id, session_ref FROM {C.TBL_EXPECTATION_SESSION} "
            "WHERE run_ref = ? AND copilot = ? AND session_id = ?",
            (run_ref, C.COPILOT_CLAUDE_CODE, session_id),
        )
        if present is None:
            db.execute(
                f"""
                INSERT INTO {C.TBL_EXPECTATION_SESSION}
                    (run_ref, copilot, session_id, session_ref, phase_num, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_ref, C.COPILOT_CLAUDE_CODE, session_id, session_ref, phase_num, now),
            )
            recorded += 1
        elif present[1] is None and session_ref is not None:
            # The transcript was ingested after the first scan: resolve
            # it now rather than leaving the association half-made.
            db.execute(
                f"UPDATE {C.TBL_EXPECTATION_SESSION} SET session_ref = ? WHERE id = ?",
                (session_ref, int(present[0])),
            )
    return recorded





# ── reading ────────────────────────────────────────────────────────────


def list_runs(
    db, *, feature_id: Optional[str] = None, attempt_id: Optional[str] = None,
    limit: Optional[int] = 50,
) -> list[dict[str, Any]]:
    """Stored runs with their expectations, results and coverage.

    Every figure a caller needs to judge how much of a run was actually
    established is here: `unknown` and `unevaluated` are counted
    separately and are in neither side of `rate`, which is exactly
    `met / evaluated` and None when nothing was evaluated (never 0.0).

    ``limit=None`` returns EVERY stored run, with no SQL ``LIMIT``. An
    aggregate defined over all runs must ask for all of them: a cap
    there would drop later runs out of the row totals AND out of the
    exclusion counters, so the omission would not even show up as
    missing coverage. The HTTP and MCP surfaces keep an explicit,
    bounded limit — they page for a reader, not for a total.
    """
    where, params = [], []
    if feature_id:
        where.append("feature_id = ?")
        params.append(feature_id)
    if attempt_id:
        where.append("attempt_id = ?")
        params.append(attempt_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(int(limit))
    rows = db.query(
        f"SELECT id, feature_id, attempt_id, run_fingerprint, contract_fingerprint, "
        f"branch_base_ref, ledger_path, ledger_root, status, outcome, evaluated_at, "
        f"ingested_at FROM {C.TBL_EXPECTATION_RUN}{clause} "
        f"ORDER BY COALESCE(evaluated_at, ingested_at) DESC, id DESC{limit_sql}",
        tuple(params),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        run_ref = int(r[0])
        expectations = _expectations_for_run(db, run_ref)
        out.append({
            "feature_id": r[1], "attempt_id": r[2],
            "run_fingerprint": r[3], "contract_fingerprint": r[4],
            "branch_base_ref": r[5], "ledger_path": r[6], "ledger_root": r[7],
            "status": r[8], "outcome": r[9],
            "evaluated_at": r[10], "ingested_at": r[11],
            "expectations": expectations,
            "sessions": _sessions_for_run(db, run_ref),
            **summarize(expectations),
        })
    return out


def _expectations_for_run(db, run_ref: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in db.query(
        f"SELECT id, fr, statement_sha, statement, statement_source, verifier_count "
        f"FROM {C.TBL_EXPECTATION} WHERE run_ref = ? ORDER BY fr", (run_ref,)
    ):
        results = [
            {"kind": r[0], "verifier": r[1],
             "green": None if r[2] is None else bool(r[2]),
             "waived": None if r[3] is None else bool(r[3]),
             "state": r[4], "detail": r[5], "evidence": r[6], "log_path": r[7]}
            for r in db.query(
                f"SELECT kind, verifier, green, waived, state, detail, evidence, log_path "
                f"FROM {C.TBL_EXPECTATION_RESULT} WHERE expectation_ref = ? "
                "ORDER BY verifier_ordinal", (int(e[0]),)
            )
        ]
        out.append({
            "fr": e[1], "statement_sha": e[2], "statement": e[3],
            "statement_source": e[4], "verifier_count": int(e[5] or 0),
            # None = UNEVALUATED: no recoverable consolidated result.
            "state": roll_up([r["state"] for r in results]),
            "results": results,
        })
    return out


def _sessions_for_run(db, run_ref: int) -> list[dict[str, Any]]:
    return [
        {"copilot": r[0], "session_id": r[1],
         "session_ref": None if r[2] is None else int(r[2]),
         "phase_num": None if r[3] is None else int(r[3])}
        for r in db.query(
            f"SELECT copilot, session_id, session_ref, phase_num "
            f"FROM {C.TBL_EXPECTATION_SESSION} WHERE run_ref = ? ORDER BY phase_num, session_id",
            (run_ref,),
        )
    ]


def summarize(expectations: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts and the rate for one run's expectations.

    `rate` is exactly met / evaluated over the states `met` and
    `not_met`; `unknown` and `unevaluated` are in NEITHER side and are
    reported beside it, so the gap between what was required and what
    was established stays visible. None — never 0.0 — when nothing was
    evaluated."""
    states = [e["state"] for e in expectations]
    met = sum(1 for s in states if s == C.EXPECTATION_MET)
    not_met = sum(1 for s in states if s == C.EXPECTATION_NOT_MET)
    unknown = sum(1 for s in states if s == C.EXPECTATION_UNKNOWN)
    unevaluated = sum(1 for s in states if s is None)
    evaluated = met + not_met
    return {
        "expectations_total": len(states),
        "expectations_met": met,
        "expectations_not_met": not_met,
        "expectations_evaluated": evaluated,
        "expectations_unknown": unknown,
        "expectations_unevaluated": unevaluated,
        "rate": (met / evaluated) if evaluated else None,
    }
