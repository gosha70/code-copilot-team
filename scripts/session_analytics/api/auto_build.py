# session_analytics.api.auto_build — the auto-build run surface (#190 §12).
#
# One read-only view over the ledgers scripts/auto-build-loop.sh writes
# (state.json, events.jsonl, termination.json, verification-results.json,
# phase-N/review/loop-summary.json), derived per request and stored
# nowhere; plus the one fact the ledger cannot write — the human
# verdict on the PR a run produced — kept in auto_build_verdict so it
# outlives the ledger directory.
#
# The outcome is the driver's word, verbatim: "landed", "terminated_policy",
# or nothing yet. Nothing here maps it onto pass/fail.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .. import constants as C
from ..config import REPO_ROOT, AutoBuildConfig
from ..mcp.tools import _parse_ts
from ..relational.db import Database, now_iso


@dataclass
class ScanResult:
    root: Path
    is_dir: bool
    runs: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    duplicates: int = 0


def resolve_root(cfg: AutoBuildConfig) -> Path:
    """The ledger root: absolute as given, otherwise under the repository."""
    root = Path(cfg.ledger_root)
    return root if root.is_absolute() else REPO_ROOT / root


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_events(path: Path) -> list[dict[str, Any]]:
    """events.jsonl in append order; a malformed line is dropped, not fatal."""
    out: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("event"):
                    out.append({"ts": row.get("ts"), "event": str(row["event"]), "detail": row.get("detail")})
    except OSError:
        pass
    return out


def _iso(epoch: Any) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _aware(value: Any) -> Optional[datetime]:
    parsed = _parse_ts(value)
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _phases(state: dict[str, Any], ledger: Path) -> list[dict[str, Any]]:
    """Per-phase facts from the state plus each phase's review summary."""
    out: list[dict[str, Any]] = []
    raw = state.get("phases") or {}
    if not isinstance(raw, dict):
        return out
    for key in sorted(raw, key=lambda k: _int(k) if _int(k) is not None else 0):
        entry = raw.get(key) or {}
        if not isinstance(entry, dict):
            continue
        summary = _read_json(ledger / f"{C.LEDGER_PHASE_DIR_PREFIX}{key}" / C.LEDGER_REVIEW_SUMMARY)
        rounds = review_verdict = None
        if isinstance(summary, dict):
            rounds = _int(summary.get("rounds_completed"))
            verdict = summary.get("verdict")
            review_verdict = str(verdict) if verdict else None
        commits = entry.get("commits") or []
        out.append({
            "n": _int(key),
            "title": entry.get("title"),
            "status": entry.get("status"),
            "rounds": rounds,
            "review_verdict": review_verdict,
            "fix_sessions": _int(entry.get("fix_sessions")) or 0,
            "commits": len(commits) if isinstance(commits, list) else 0,
        })
    return out


def _planned_phases(ledger: Path) -> Optional[int]:
    """phases.tsv is the plan the driver wrote (n, title, milestone flag)."""
    try:
        with (ledger / "phases.tsv").open(encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return None


def _verifiers(state: dict[str, Any], ledger: Path) -> dict[str, Any]:
    contract = ((state.get("preflight") or {}).get("contract") or {})
    verifier_set = ((contract.get("verifiers") or {}).get("set"))
    if verifier_set is None:
        frozen = _read_json(ledger / "frozen-contract.json")
        if isinstance(frozen, dict):
            verifier_set = ((frozen.get("verifiers") or {}).get("set"))
    admission_mapped = len(verifier_set) if isinstance(verifier_set, list) else None
    results = None
    raw = _read_json(ledger / C.LEDGER_VERIFICATION_FILE)
    if isinstance(raw, dict) and isinstance(raw.get("frs"), dict):
        frs = [{"fr": fr, "green": bool((entry or {}).get("green"))} for fr, entry in sorted(raw["frs"].items())]
        results = {"green": sum(1 for f in frs if f["green"]), "total": len(frs), "frs": frs}
    return {"admission_mapped": admission_mapped, "results": results}


def read_run(ledger: Path, root: Path, *, now: datetime, active_window_seconds: int) -> Optional[dict[str, Any]]:
    """One run record from one ledger directory, or None when its
    state.json is unreadable or names no attempt."""
    state = _read_json(ledger / C.LEDGER_STATE_FILE)
    if not isinstance(state, dict) or not state.get("attempt_id"):
        return None
    events = _read_events(ledger / C.LEDGER_EVENTS_FILE)
    termination = _read_json(ledger / C.LEDGER_TERMINATION_FILE)
    if not isinstance(termination, dict):
        termination = {}
    status = str(state.get("status") or "")
    updated = _aware(state.get("updated"))
    totals = state.get("totals") or {}
    caps = state.get("caps") or {}
    started = _aware(_iso(totals.get("started_epoch")))
    live = (
        status not in C.LEDGER_TERMINAL_STATUSES
        and updated is not None
        and (now - updated).total_seconds() <= active_window_seconds
    )
    end = now if live else updated
    elapsed = int((end - started).total_seconds()) if (started and end and end >= started) else None
    outcome = state.get("outcome")
    reason = state.get("disposition_reason") or termination.get("reason")
    pr = state.get("pr") or {}
    phases = _phases(state, ledger)
    return {
        "key": str(state["attempt_id"]),
        "feature_id": state.get("feature_id"),
        "profile": state.get("profile"),
        "branch": state.get("branch"),
        "base_ref": (str(state.get("branch_base_ref") or "")[:12] or None),
        "status": status or None,
        "outcome": str(outcome) if outcome else None,
        "disposition": {
            "reason": str(reason) if reason else None,
            "detail": termination.get("detail"),
            "phase": _int(termination.get("phase")),
        },
        "live": live,
        "started_at": started.isoformat().replace("+00:00", "Z") if started else None,
        "updated_at": state.get("updated"),
        "elapsed_sec": elapsed,
        "caps": {
            "phases": _int(caps.get("max_phases")),
            "fix_sessions_per_phase": _int(caps.get("max_fix_sessions_per_phase")),
            "wall_clock_sec": _int(caps.get("max_wall_clock_sec")),
            "cost_usd": _float(caps.get("max_cost_usd")),
        },
        "cost": {
            "metered_usd": _float(totals.get("cost_usd")) or 0.0,
            "estimated_usd": _float(totals.get("cost_estimated_usd")) or 0.0,
        },
        "phases": {
            "planned": _planned_phases(ledger),
            "done": sum(1 for p in phases if p["status"] == "done"),
            "current": _int(state.get("current_phase")),
            "items": phases,
        },
        "verifiers": _verifiers(state, ledger),
        "policy_decisions": [e for e in events if e["event"] in C.POLICY_EVENTS],
        "escalations": len(state.get("escalations") or []),
        "scores": None,
        "pr": {"number": _int(pr.get("number")), "url": pr.get("url") or None},
        "ledger": ledger.relative_to(root).as_posix(),
        "verdict": None,
    }


def scan_runs(root: Path, *, now: datetime, active_window_seconds: int) -> ScanResult:
    """Every run under the two fixed subdirectories of the root, newest
    first. A directory without a readable state is listed under skipped;
    a second directory carrying an attempt id already seen is counted."""
    result = ScanResult(root=root, is_dir=root.is_dir())
    if not result.is_dir:
        return result
    seen: set[str] = set()
    for sub in C.AUTO_BUILD_SUBDIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for ledger in sorted(p for p in base.iterdir() if p.is_dir()):
            run = read_run(ledger, root, now=now, active_window_seconds=active_window_seconds)
            if run is None:
                result.skipped.append({
                    "ledger": ledger.relative_to(root).as_posix(),
                    "reason": f"no readable {C.LEDGER_STATE_FILE} with an attempt_id",
                })
                continue
            if run["key"] in seen:
                result.duplicates += 1
                continue
            seen.add(run["key"])
            result.runs.append(run)
    result.runs.sort(key=lambda r: r["started_at"] or "", reverse=True)
    return result


# ── verdicts ───────────────────────────────────────────────────────────

def _verdict_rows(db: Database) -> dict[str, dict[str, Any]]:
    rows = db.query(f"SELECT run_key, feature_id, verdict, note, set_at FROM {C.TBL_AUTO_BUILD_VERDICT}")
    return {
        str(r[0]): {"verdict": r[2], "note": r[3], "set_at": r[4], "feature_id": r[1]}
        for r in rows
    }


def _attach_verdicts(runs: list[dict[str, Any]], verdicts: dict[str, dict[str, Any]]) -> int:
    """Join verdicts onto runs; returns how many verdicts have no ledger."""
    keys = set()
    for run in runs:
        keys.add(run["key"])
        row = verdicts.get(run["key"])
        run["verdict"] = (
            {"verdict": row["verdict"], "note": row["note"], "set_at": row["set_at"]} if row else None
        )
    return sum(1 for k in verdicts if k not in keys)


def list_runs(db: Database, cfg: AutoBuildConfig, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The FR-5 list payload."""
    now = now or datetime.now(timezone.utc)
    scan = scan_runs(resolve_root(cfg), now=now, active_window_seconds=cfg.active_window_seconds)
    orphaned = _attach_verdicts(scan.runs, _verdict_rows(db))
    by_outcome: dict[str, int] = {}
    no_outcome = 0
    by_verdict: dict[str, int] = {v: 0 for v in C.VERDICTS}
    unlabelled = 0
    for run in scan.runs:
        if run["outcome"]:
            by_outcome[run["outcome"]] = by_outcome.get(run["outcome"], 0) + 1
        else:
            no_outcome += 1
        if run["verdict"]:
            by_verdict[run["verdict"]["verdict"]] = by_verdict.get(run["verdict"]["verdict"], 0) + 1
        else:
            unlabelled += 1
    return {
        "root": {
            "path": cfg.ledger_root,
            "is_dir": scan.is_dir,
            "subdirs": list(C.AUTO_BUILD_SUBDIRS),
        },
        "active_window_seconds": cfg.active_window_seconds,
        "runs": scan.runs,
        "summary": {
            "total": len(scan.runs),
            "live": sum(1 for r in scan.runs if r["live"]),
            "by_outcome": by_outcome,
            "no_outcome": no_outcome,
            "by_verdict": by_verdict,
            "unlabelled": unlabelled,
        },
        "skipped": scan.skipped,
        "duplicates": scan.duplicates,
        "verdicts_without_ledger": orphaned,
        "verdicts": list(C.VERDICTS),
    }


def _find_run(db: Database, cfg: AutoBuildConfig, key: str, now: datetime) -> Optional[dict[str, Any]]:
    scan = scan_runs(resolve_root(cfg), now=now, active_window_seconds=cfg.active_window_seconds)
    for run in scan.runs:
        if run["key"] == key:
            _attach_verdicts([run], _verdict_rows(db))
            return run
    return None


def run_detail(db: Database, cfg: AutoBuildConfig, key: str, *, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """The record plus every ledger event and the triage report text."""
    now = now or datetime.now(timezone.utc)
    run = _find_run(db, cfg, key, now)
    if run is None:
        return None
    ledger = resolve_root(cfg) / run["ledger"]
    run["events"] = _read_events(ledger / C.LEDGER_EVENTS_FILE)
    try:
        run["triage_report"] = (ledger / C.LEDGER_TRIAGE_FILE).read_text(encoding="utf-8")
    except OSError:
        run["triage_report"] = None
    return run


def set_verdict(
    db: Database, cfg: AutoBuildConfig, key: str, verdict: str, note: Optional[str], *, now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Record the human verdict on a run's PR; returns the run.
    LookupError for a key no ledger carries, ValueError for a verdict
    outside the three."""
    if verdict not in C.VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}; one of: {', '.join(C.VERDICTS)}")
    note = (note or "").strip() or None
    if note and len(note) > C.VERDICT_NOTE_MAX_CHARS:
        raise ValueError(f"note longer than {C.VERDICT_NOTE_MAX_CHARS} characters")
    now = now or datetime.now(timezone.utc)
    run = _find_run(db, cfg, key, now)
    if run is None:
        raise LookupError(f"no auto-build run {key!r} under the ledger root")
    stamp = now_iso()
    if db.query_one(f"SELECT 1 FROM {C.TBL_AUTO_BUILD_VERDICT} WHERE run_key = ?", (key,)) is None:
        db.execute(
            f"INSERT INTO {C.TBL_AUTO_BUILD_VERDICT} (run_key, feature_id, verdict, note, set_at) VALUES (?, ?, ?, ?, ?)",
            (key, run["feature_id"], verdict, note, stamp),
        )
    else:
        db.execute(
            f"UPDATE {C.TBL_AUTO_BUILD_VERDICT} SET feature_id = ?, verdict = ?, note = ?, set_at = ? WHERE run_key = ?",
            (run["feature_id"], verdict, note, stamp, key),
        )
    db.commit()
    run["verdict"] = {"verdict": verdict, "note": note, "set_at": stamp}
    return run


def clear_verdict(db: Database, cfg: AutoBuildConfig, key: str, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Remove the verdict; returns the run. LookupError for an unknown key."""
    now = now or datetime.now(timezone.utc)
    run = _find_run(db, cfg, key, now)
    if run is None:
        raise LookupError(f"no auto-build run {key!r} under the ledger root")
    db.execute(f"DELETE FROM {C.TBL_AUTO_BUILD_VERDICT} WHERE run_key = ?", (key,))
    db.commit()
    run["verdict"] = None
    return run


# ── terminal rendering (CLI) ───────────────────────────────────────────

def _usd(value: Optional[float]) -> str:
    return "—" if value is None else f"${value:.2f}"


def _cost_line(run: dict[str, Any]) -> str:
    cost, cap = run["cost"], run["caps"]["cost_usd"]
    line = f"metered {_usd(cost['metered_usd'])}"
    if cost["estimated_usd"]:
        line += f" + estimated {_usd(cost['estimated_usd'])}"
    return line + (f" of cap {_usd(cap)}" if cap is not None else " (no cap recorded)")


def _verifier_line(run: dict[str, Any]) -> str:
    ver = run["verifiers"]
    mapped = ver["admission_mapped"]
    head = f"{mapped} requirement(s) mapped at admission" if mapped is not None else "no admission contract"
    res = ver["results"]
    if res is None:
        return head + "; verifiers not run"
    return head + f"; {res['green']} of {res['total']} green"


def render_list(payload: dict[str, Any]) -> list[str]:
    root = payload["root"]
    lines = [f"Auto-build runs under {root['path']} ({', '.join(root['subdirs'])})"]
    if not root["is_dir"]:
        lines.append("  the ledger root is not a directory: nothing has run here, or the root is set elsewhere")
        return lines
    s = payload["summary"]
    parts = [f"{k}: {v}" for k, v in sorted(s["by_outcome"].items())]
    parts.append(f"no outcome yet: {s['no_outcome']}")
    lines.append(f"  {s['total']} run(s) — " + ", ".join(parts) + f"; live: {s['live']}")
    for run in payload["runs"]:
        verdict = run["verdict"]["verdict"] if run["verdict"] else "no verdict"
        lines.append(
            f"  {run['key']}  {run['feature_id']}  {run['profile']}  "
            f"outcome={run['outcome'] or 'none'}  status={run['status']}"
            + (f"  reason={run['disposition']['reason']}" if run["disposition"]["reason"] else "")
            + f"  {_cost_line(run)}  verdict={verdict}"
        )
    if payload["skipped"]:
        lines.append(f"  skipped {len(payload['skipped'])} director(ies) without a readable state")
    if payload["verdicts_without_ledger"]:
        lines.append(f"  {payload['verdicts_without_ledger']} verdict(s) whose ledger is gone")
    return lines


def render_run(run: dict[str, Any]) -> list[str]:
    d = run["disposition"]
    lines = [
        f"Run {run['key']} — {run['feature_id']} ({run['profile']}) on {run['branch']} from {run['base_ref']}",
        f"  ledger: {run['ledger']}",
        f"  status: {run['status']}; outcome: {run['outcome'] or 'none yet'}" + (
            f"; reason: {d['reason']}" if d["reason"] else ""),
    ]
    if d["detail"]:
        lines.append(f"  detail: {d['detail']}")
    lines.append(f"  started: {run['started_at']}; last update: {run['updated_at']}; "
                 f"elapsed: {run['elapsed_sec']}s of cap {run['caps']['wall_clock_sec']}s" + ("; live" if run["live"] else ""))
    lines.append(f"  cost: {_cost_line(run)}")
    ph = run["phases"]
    lines.append(f"  phases: {ph['done']} done of {ph['planned']} planned (cap {run['caps']['phases']})")
    for p in ph["items"]:
        rounds = f"{p['rounds']} round(s), review {p['review_verdict']}" if p["rounds"] is not None else "no review yet"
        lines.append(f"    phase {p['n']}: {p['title']} — {p['status']}; {rounds}; "
                     f"{p['fix_sessions']} fix session(s); {p['commits']} commit(s)")
    lines.append(f"  verifiers: {_verifier_line(run)}")
    if run["policy_decisions"]:
        lines.append(f"  policy decisions ({len(run['policy_decisions'])}):")
        for e in run["policy_decisions"]:
            lines.append(f"    {e['ts']}  {e['event']}: {e['detail']}")
    else:
        lines.append("  policy decisions: none")
    lines.append("  scores: none recorded")
    if run["pr"]["number"]:
        lines.append(f"  PR #{run['pr']['number']}: {run['pr']['url']}")
    v = run["verdict"]
    lines.append(f"  verdict: {v['verdict']} ({v['set_at']})" + (f" — {v['note']}" if v["note"] else "") if v else "  verdict: none")
    return lines
