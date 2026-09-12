# Tests for the auto-build run surface (#190 §12, auto-build-run-surface):
# the ledger reader, the verdict store, the API and the CLI renderers.
#
# Ledgers are written into a temporary root in the shapes the four real
# unattended runs of 2026-09-09 left behind: one landed with a PR, one
# terminated with a termination.json, one parked, one unreadable, and a
# copy carrying an attempt id already seen.

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from session_analytics import constants as C
from session_analytics.api import auto_build as AB
from session_analytics.config import AutoBuildConfig
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import RegistryResetTestCase

NOW = datetime(2026, 9, 9, 17, 0, 0, tzinfo=timezone.utc)
WINDOW = 900

LANDED_KEY = "47908-474720888"
TERMINATED_KEY = "83409-56971841"
PARKED_KEY = "11111-222222222"
LIVE_KEY = "33333-444444444"


def _state(key: str, **over) -> dict:
    base = {
        "schema_version": 1, "feature_id": "team-developer-aliases", "profile": "unattended",
        "attempt_id": key, "status": "done", "current_phase": 1,
        "branch": "feature/team-developer-aliases-run4", "branch_base_ref": "f75ebaa5a09eab39a98497f6ab827f241501b46b",
        "phases": {"1": {"title": "US1: aliases fold developer rows at read time", "status": "done",
                         "commits": ["fb0f089", "1701375"], "fix_sessions": 0}},
        "caps": {"max_phases": 2, "max_fix_sessions_per_phase": 2, "max_wall_clock_sec": 5400, "max_cost_usd": 10},
        "outcome": "landed", "disposition_reason": None,
        "totals": {"cost_usd": 5.2980335, "cost_estimated_usd": 2, "started_epoch": 1788970923},
        "escalations": [], "pr": {"number": 331, "url": "https://github.com/gosha70/code-copilot-team/pull/331"},
        "updated": "2026-09-09T16:31:46Z",
        "preflight": {"contract": {"verifiers": {"set": [{"fr": f"FR-{i}"} for i in range(1, 5)]}}},
    }
    base.update(over)
    return base


def _write_ledger(root: Path, sub: str, name: str, state: dict, *, events=(), extra=None) -> Path:
    ledger = root / sub / name
    ledger.mkdir(parents=True)
    (ledger / C.LEDGER_STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
    with (ledger / C.LEDGER_EVENTS_FILE).open("w", encoding="utf-8") as fh:
        for ts, event, detail in events:
            fh.write(json.dumps({"ts": ts, "event": event, "detail": detail}) + "\n")
        fh.write("not json\n")
    (ledger / "phases.tsv").write_text("1\tUS1: aliases fold developer rows at read time\t0\n", encoding="utf-8")
    for rel, content in (extra or {}).items():
        path = ledger / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return ledger


class _Ledgers(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="cct-ledgers-"))
        self.cfg = AutoBuildConfig(ledger_root=str(self.root), active_window_seconds=WINDOW)
        self.dsn = self.sqlite_dsn()
        self.db = Database.connect(self.dsn)
        apply_ddl(self.db)
        self.addCleanup(self.db.close)
        # Run 4: landed, PR, one review round PASS, verifiers green, three policy decisions.
        _write_ledger(
            self.root, C.AUTO_BUILD_LIVE_DIR, "team-developer-aliases", _state(LANDED_KEY),
            events=[
                ("2026-09-09T16:22:19Z", "init", "profile=unattended"),
                ("2026-09-09T16:22:21Z", "status", "building"),
                ("2026-09-09T16:30:51Z", "review_state_reset", "leftover review state set aside"),
                ("2026-09-09T16:31:41Z", "verifier_gate", "all mapped verifiers green (4 FR(s))"),
                ("2026-09-09T16:31:46Z", "merge_skipped", "merge.enabled=false"),
            ],
            extra={
                "phase-1/review/loop-summary.json": {"verdict": "PASS", "rounds_completed": 1},
                C.LEDGER_VERIFICATION_FILE: {"schema_version": 1, "frs": {
                    f"FR-{i}": {"green": True, "verifiers": []} for i in range(1, 5)}},
            },
        )
        # Run 1: terminated_policy on provider_unavailable, no PR, phase left "building".
        _write_ledger(
            self.root, C.AUTO_BUILD_ARCHIVE_DIR, "team-developer-aliases-run1",
            _state(TERMINATED_KEY, status="terminated_policy", outcome="terminated_policy",
                   disposition_reason="provider_unavailable", branch="feature/team-developer-aliases",
                   phases={"1": {"title": "US1", "status": "building", "commits": ["499d1e5"], "fix_sessions": 0}},
                   totals={"cost_usd": 4.758891, "cost_estimated_usd": 0, "started_epoch": 1788913318},
                   pr={"number": None, "url": None}, updated="2026-09-09T01:55:23Z"),
            events=[
                ("2026-09-09T01:55:23Z", "terminated_policy", "provider_unavailable: reviewer 'codex' failed"),
                ("2026-09-09T01:55:23Z", "artifact_skipped", "termination commit failed"),
            ],
            extra={
                C.LEDGER_TERMINATION_FILE: {"outcome": "terminated_policy", "reason": "provider_unavailable",
                                            "detail": "reviewer 'codex' failed (exit 1) in phase 1 round 1",
                                            "phase": 1, "created": "2026-09-09T01:55:23Z"},
                C.LEDGER_TRIAGE_FILE: "# Triage report\n",
            },
        )
        # An attended run that parked: outcome stays null, status parked,
        # and the reason lives in escalations/esc-N.json (the state lists
        # the ids), not in termination.json.
        _write_ledger(
            self.root, C.AUTO_BUILD_ARCHIVE_DIR, "other-feature-parked",
            _state(PARKED_KEY, feature_id="other-feature", profile="pr", status="parked", outcome=None,
                   escalations=["esc-1", "esc-2"], pr={"number": None, "url": None},
                   totals={"cost_usd": 1.0, "cost_estimated_usd": 0, "started_epoch": 1788900000},
                   updated="2026-09-08T22:00:00Z", preflight={}),
            events=[("2026-09-08T22:00:00Z", "parked", "test_failure")],
            extra={
                f"{C.LEDGER_ESCALATIONS_DIR}/esc-1.json": {"id": "esc-1", "reason": "review_breaker", "detail": "older, resolved",
                                                          "phase": 1, "resolved": True},
                f"{C.LEDGER_ESCALATIONS_DIR}/esc-2.json": {"id": "esc-2", "reason": "test_failure",
                                                          "detail": "test command exited 1 after 2 fix sessions",
                                                          "phase": 2, "resolved": False},
            },
        )
        # A copy of run 4 someone left in the archive: same attempt id.
        _write_ledger(self.root, C.AUTO_BUILD_ARCHIVE_DIR, "team-developer-aliases-copy", _state(LANDED_KEY))
        # A directory with no readable state.
        (self.root / C.AUTO_BUILD_ARCHIVE_DIR / "broken").mkdir()
        (self.root / C.AUTO_BUILD_ARCHIVE_DIR / "broken" / C.LEDGER_STATE_FILE).write_text("{", encoding="utf-8")
        # Something else under the root that is NOT a ledger subdirectory.
        (self.root / "review").mkdir()
        (self.root / "review" / C.LEDGER_STATE_FILE).write_text(json.dumps(_state("99999-1")), encoding="utf-8")


class TestReader(_Ledgers):
    def test_fr2_one_record_per_readable_ledger_newest_first(self) -> None:
        scan = AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW)
        self.assertEqual([r["key"] for r in scan.runs], [LANDED_KEY, TERMINATED_KEY, PARKED_KEY])
        self.assertEqual(scan.duplicates, 1)
        self.assertEqual([s["ledger"] for s in scan.skipped], ["auto-build-archive/broken"])
        self.assertEqual(scan.runs[0]["ledger"], "auto-build/team-developer-aliases")
        self.assertEqual(scan.runs[1]["ledger"], "auto-build-archive/team-developer-aliases-run1")

    def test_fr2_landed_run_facts(self) -> None:
        run = AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs[0]
        self.assertEqual(run["outcome"], "landed")
        self.assertEqual(run["status"], "done")
        self.assertFalse(run["live"])
        self.assertEqual(run["disposition"], {"reason": None, "detail": None, "phase": None})
        self.assertEqual(run["started_at"], "2026-09-09T16:22:03Z")
        self.assertEqual(run["elapsed_sec"], 583)
        self.assertEqual(run["cost"], {"metered_usd": 5.2980335, "estimated_usd": 2.0})
        self.assertEqual(run["caps"]["cost_usd"], 10.0)
        self.assertEqual(run["caps"]["wall_clock_sec"], 5400)
        self.assertEqual(run["phases"]["planned"], 1)
        self.assertEqual(run["phases"]["done"], 1)
        phase = run["phases"]["items"][0]
        self.assertEqual((phase["rounds"], phase["review_verdict"], phase["commits"]), (1, "PASS", 2))
        self.assertEqual(run["verifiers"]["admission_mapped"], 4)
        self.assertEqual(run["verifiers"]["results"]["green"], 4)
        self.assertEqual(run["verifiers"]["results"]["total"], 4)
        self.assertEqual([e["event"] for e in run["policy_decisions"]],
                         ["review_state_reset", "verifier_gate", "merge_skipped"])
        self.assertEqual(run["pr"], {"number": 331, "url": "https://github.com/gosha70/code-copilot-team/pull/331"})
        self.assertIsNone(run["scores"])
        self.assertEqual(run["base_ref"], "f75ebaa5a09e")

    def test_fr2_terminated_run_takes_reason_and_detail_from_termination_json(self) -> None:
        run = AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs[1]
        self.assertEqual(run["outcome"], "terminated_policy")
        self.assertEqual(run["disposition"]["reason"], "provider_unavailable")
        self.assertEqual(run["disposition"]["detail"], "reviewer 'codex' failed (exit 1) in phase 1 round 1")
        self.assertEqual(run["disposition"]["phase"], 1)
        self.assertIsNone(run["verifiers"]["results"])
        self.assertEqual(run["verifiers"]["admission_mapped"], 4)
        self.assertEqual(run["phases"]["done"], 0)
        self.assertIsNone(run["phases"]["items"][0]["rounds"])
        self.assertEqual(run["pr"], {"number": None, "url": None})
        self.assertEqual(run["elapsed_sec"], 5605)

    def test_fr2_parked_run_has_no_outcome_and_takes_its_disposition_from_the_newest_escalation(self) -> None:
        run = AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs[2]
        self.assertIsNone(run["outcome"])
        self.assertEqual(run["status"], "parked")
        self.assertFalse(run["live"])
        self.assertTrue(run["concluded"])
        self.assertEqual(run["escalations"], 2)
        self.assertEqual(run["disposition"], {
            "reason": "test_failure", "detail": "test command exited 1 after 2 fix sessions", "phase": 2})
        self.assertIsNone(run["verifiers"]["admission_mapped"])

    def test_fr2_a_park_whose_escalation_file_is_missing_still_reads(self) -> None:
        _write_ledger(self.root, C.AUTO_BUILD_LIVE_DIR, "parked-no-file",
                      _state("55555-1", status="parked", outcome=None, escalations=["esc-1"]))
        run = {r["key"]: r for r in AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs}["55555-1"]
        self.assertEqual(run["disposition"], {"reason": None, "detail": None, "phase": None})
        self.assertEqual(run["escalations"], 1)

    def test_fr2_live_rule_is_status_plus_recent_state_write(self) -> None:
        recent = (NOW - timedelta(seconds=WINDOW - 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_ledger(self.root, C.AUTO_BUILD_LIVE_DIR, "live-feature",
                      _state(LIVE_KEY, feature_id="live-feature", status="building", outcome=None,
                             updated=recent, totals={"cost_usd": 0.5, "cost_estimated_usd": 0,
                                                     "started_epoch": int((NOW - timedelta(minutes=20)).timestamp())}))
        runs = {r["key"]: r for r in AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs}
        self.assertTrue(runs[LIVE_KEY]["live"])
        self.assertFalse(runs[LIVE_KEY]["concluded"])
        self.assertEqual(runs[LIVE_KEY]["elapsed_sec"], 1200)
        # A build phase longer than the window: the state is stale, so the
        # run is not live — but it is not concluded either, its clock is
        # still running, and the page keeps polling it (FR-8).
        later = NOW + timedelta(seconds=WINDOW + 5)
        stale = {r["key"]: r for r in AB.scan_runs(self.root, now=later, active_window_seconds=WINDOW).runs}[LIVE_KEY]
        self.assertFalse(stale["live"])
        self.assertFalse(stale["concluded"])
        self.assertEqual(stale["elapsed_sec"], 1200 + WINDOW + 5)
        self.assertTrue(all(r["concluded"] for k, r in runs.items() if k != LIVE_KEY))

    def test_fr1_only_the_two_fixed_subdirectories_are_read(self) -> None:
        keys = [r["key"] for r in AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs]
        self.assertNotIn("99999-1", keys)

    def test_fr1_missing_root_is_a_state_not_an_error(self) -> None:
        scan = AB.scan_runs(self.root / "nowhere", now=NOW, active_window_seconds=WINDOW)
        self.assertFalse(scan.is_dir)
        self.assertEqual(scan.runs, [])

    def test_fr1_relative_root_resolves_under_the_repository(self) -> None:
        from session_analytics.config import REPO_ROOT

        self.assertEqual(AB.resolve_root(AutoBuildConfig(".cct", 900)), REPO_ROOT / ".cct")
        self.assertEqual(AB.resolve_root(self.cfg), self.root)


class TestListAndVerdicts(_Ledgers):
    def test_fr3_summary_counts_outcomes_verbatim_and_no_outcome_separately(self) -> None:
        payload = AB.list_runs(self.db, self.cfg, now=NOW)
        self.assertEqual(payload["summary"]["by_outcome"], {"landed": 1, "terminated_policy": 1})
        self.assertEqual(payload["summary"]["no_outcome"], 1)
        self.assertEqual(payload["summary"]["total"], 3)
        self.assertEqual(payload["summary"]["unlabelled"], 3)
        self.assertEqual(payload["root"]["subdirs"], ["auto-build", "auto-build-archive"])
        self.assertEqual(payload["duplicates"], 1)
        self.assertEqual(payload["verdicts"], list(C.VERDICTS))
        text = json.dumps(payload).lower()
        self.assertNotIn('"pass"', text.replace('"review_verdict": "pass"', ""))
        self.assertNotIn('"fail"', text)

    def test_fr4_set_change_and_clear_a_verdict(self) -> None:
        run = AB.set_verdict(self.db, self.cfg, LANDED_KEY, C.VERDICT_MERGED_WITH_FIXES, "  human review asked for fixes ", now=NOW)
        self.assertEqual(run["verdict"]["verdict"], "merged_with_fixes")
        self.assertEqual(run["verdict"]["note"], "human review asked for fixes")
        listed = {r["key"]: r for r in AB.list_runs(self.db, self.cfg, now=NOW)["runs"]}
        self.assertEqual(listed[LANDED_KEY]["verdict"]["verdict"], "merged_with_fixes")
        self.assertIsNone(listed[TERMINATED_KEY]["verdict"])
        summary = AB.list_runs(self.db, self.cfg, now=NOW)["summary"]
        self.assertEqual(summary["by_verdict"]["merged_with_fixes"], 1)
        self.assertEqual(summary["unlabelled"], 2)
        run = AB.set_verdict(self.db, self.cfg, LANDED_KEY, C.VERDICT_REJECTED, None, now=NOW)
        self.assertEqual(run["verdict"]["verdict"], "rejected")
        self.assertIsNone(run["verdict"]["note"])
        self.assertEqual(self.db.query_one(f"SELECT COUNT(*) FROM {C.TBL_AUTO_BUILD_VERDICT}")[0], 1)
        run = AB.clear_verdict(self.db, self.cfg, LANDED_KEY, now=NOW)
        self.assertIsNone(run["verdict"])
        self.assertEqual(self.db.query_one(f"SELECT COUNT(*) FROM {C.TBL_AUTO_BUILD_VERDICT}")[0], 0)

    def test_fr4_unknown_key_and_unknown_verdict_refuse(self) -> None:
        with self.assertRaises(LookupError):
            AB.set_verdict(self.db, self.cfg, "no-such-run", C.VERDICT_REJECTED, None, now=NOW)
        with self.assertRaises(LookupError):
            AB.clear_verdict(self.db, self.cfg, "no-such-run", now=NOW)
        with self.assertRaises(ValueError) as ctx:
            AB.set_verdict(self.db, self.cfg, LANDED_KEY, "approved", None, now=NOW)
        for verdict in C.VERDICTS:
            self.assertIn(verdict, str(ctx.exception))
        with self.assertRaises(ValueError):
            AB.set_verdict(self.db, self.cfg, LANDED_KEY, C.VERDICT_REJECTED, "x" * (C.VERDICT_NOTE_MAX_CHARS + 1), now=NOW)

    def test_fr4_verdict_outlives_its_ledger(self) -> None:
        import shutil

        AB.set_verdict(self.db, self.cfg, TERMINATED_KEY, C.VERDICT_REJECTED, "never opened a PR", now=NOW)
        shutil.rmtree(self.root / C.AUTO_BUILD_ARCHIVE_DIR / "team-developer-aliases-run1")
        payload = AB.list_runs(self.db, self.cfg, now=NOW)
        self.assertEqual(payload["verdicts_without_ledger"], 1)
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(self.db.query_one(f"SELECT COUNT(*) FROM {C.TBL_AUTO_BUILD_VERDICT}")[0], 1)

    def test_fr5_detail_carries_events_and_triage(self) -> None:
        run = AB.run_detail(self.db, self.cfg, TERMINATED_KEY, now=NOW)
        self.assertEqual([e["event"] for e in run["events"]], ["terminated_policy", "artifact_skipped"])
        self.assertEqual(run["triage_report"], "# Triage report\n")
        landed = AB.run_detail(self.db, self.cfg, LANDED_KEY, now=NOW)
        self.assertEqual(len(landed["events"]), 5)
        self.assertIsNone(landed["triage_report"])
        self.assertIsNone(AB.run_detail(self.db, self.cfg, "no-such-run", now=NOW))

    def test_fr6_renderers_say_outcome_verbatim_and_split_estimated_cost(self) -> None:
        payload = AB.list_runs(self.db, self.cfg, now=NOW)
        text = "\n".join(AB.render_list(payload))
        self.assertIn("landed: 1, terminated_policy: 1, no outcome yet: 1", text)
        self.assertIn("metered $5.30 + estimated $2.00 of cap $10.00", text)
        self.assertIn("skipped 1 director", text)
        run = "\n".join(AB.render_run(payload["runs"][1]))
        self.assertIn("outcome: terminated_policy; reason: provider_unavailable", run)
        self.assertIn("verifiers not run", run)
        self.assertIn("scores: none recorded", run)
        parked = "\n".join(AB.render_run(payload["runs"][2]))
        self.assertIn("outcome: none yet", parked)
        missing = "\n".join(AB.render_list(AB.list_runs(
            self.db, AutoBuildConfig(str(self.root / "nowhere"), WINDOW), now=NOW)))
        self.assertIn("not a directory", missing)


class TestAttemptHistory(_Ledgers):
    """runs-attempt-history: the probe, the fallbacks and the
    terminations a run already survived (FR-1..FR-5)."""

    RESUMED_KEY = "77777-888888888"

    def _resumed(self, **extra) -> dict:
        """A run that terminated, was resumed and landed: the driver kept
        the first termination under a dated name (#190 D2)."""
        files = {
            C.LEDGER_PROBE_FILE: {
                "probe": True, "requested_provider": "codex", "provider": "deepseek",
                "provider_type": "cli", "fingerprint": "x", "exit_code": 0, "verdict": "PASS",
                "parseable": True, "duration_sec": 17, "invocation_cost_usd": 0.1234,
                "error": None, "output_tail": "…",
            },
            "termination-1788900000.json": {
                "outcome": "terminated_policy", "reason": "provider_unavailable",
                "detail": "gating reviewer 'codex' answered the readiness probe with no parseable verdict",
                "phase": 1, "created": "2026-09-09T02:00:00Z", "history": None,
            },
            "phase-1/review/findings-round-1.json": {
                "round": 1, "verdict": "FAIL", "reviewer_provider": "codex", "findings": [],
            },
            "phase-1/review/findings-round-2.json": {
                "round": 2, "verdict": "PASS", "reviewer_provider": "deepseek", "findings": [],
                "fallback": {"from": "codex", "error": "timed out after 900s", "invocation_cost_usd": None},
            },
        }
        files.update(extra)
        self._written = getattr(self, "_written", 0) + 1
        _write_ledger(
            self.root, C.AUTO_BUILD_LIVE_DIR, f"resumed-{self._written}",
            _state(self.RESUMED_KEY, feature_id="resumed-feature"), extra=files,
        )
        return {r["key"]: r for r in AB.scan_runs(
            self.root, now=NOW, active_window_seconds=WINDOW).runs}[self.RESUMED_KEY]

    def test_hist_fr1_probe_is_read_from_the_ledger(self) -> None:
        run = self._resumed()
        self.assertEqual(run["probe"], {
            "provider": "deepseek", "requested_provider": "codex", "verdict": "PASS",
            "parseable": True, "duration_sec": 17, "invocation_cost_usd": 0.1234, "error": None,
        })

    def test_hist_fr1_an_absent_or_unreadable_probe_is_null(self) -> None:
        runs = {r["key"]: r for r in AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs}
        self.assertIsNone(runs[LANDED_KEY]["probe"])
        broken = self._resumed(**{C.LEDGER_PROBE_FILE: "{not json"})
        self.assertIsNone(broken["probe"])

    def test_hist_fr1_a_probe_that_answered_nothing_keeps_who_was_asked(self) -> None:
        run = self._resumed(**{C.LEDGER_PROBE_FILE: {
            "probe": True, "requested_provider": "codex", "provider": None, "verdict": None,
            "parseable": False, "duration_sec": 0, "invocation_cost_usd": None,
            "error": "no provider in the chain for codex passed its healthcheck",
        }})
        self.assertEqual(run["probe"]["requested_provider"], "codex")
        self.assertIsNone(run["probe"]["provider"])
        self.assertIsNone(run["probe"]["verdict"])
        self.assertFalse(run["probe"]["parseable"])
        self.assertIn("healthcheck", run["probe"]["error"])

    def test_hist_fr2_earlier_terminations_are_listed_oldest_first(self) -> None:
        run = self._resumed(**{"termination-1788910000.json": {
            "outcome": "terminated_policy", "reason": "review_breaker", "detail": "3 rounds without a PASS",
            "phase": 2, "created": "2026-09-09T05:00:00Z",
        }})
        self.assertEqual(
            [(e["reason"], e["created"], e["phase"], e["file"]) for e in run["earlier_terminations"]],
            [("provider_unavailable", "2026-09-09T02:00:00Z", 1, "termination-1788900000.json"),
             ("review_breaker", "2026-09-09T05:00:00Z", 2, "termination-1788910000.json")])
        self.assertIn("readiness probe", run["earlier_terminations"][0]["detail"])

    def test_hist_fr2_no_kept_termination_is_an_empty_list(self) -> None:
        runs = {r["key"]: r for r in AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs}
        self.assertEqual(runs[LANDED_KEY]["earlier_terminations"], [])
        self.assertEqual(runs[TERMINATED_KEY]["earlier_terminations"], [])

    def test_hist_fr2_the_current_disposition_is_unchanged(self) -> None:
        """termination.json is still the disposition; the dated files are
        history beside it, and never become the reason."""
        run = self._resumed(**{C.LEDGER_TERMINATION_FILE: {
            "outcome": "terminated_policy", "reason": "cost_cap", "detail": "spent $10.20 of $10.00",
            "phase": 2, "created": "2026-09-09T06:00:00Z",
        }})
        self.assertEqual(run["disposition"]["reason"], "cost_cap")
        self.assertEqual(len(run["earlier_terminations"]), 1)
        self.assertEqual(run["earlier_terminations"][0]["reason"], "provider_unavailable")
        # And the park path is untouched: its reason still comes from the escalation.
        parked = {r["key"]: r for r in AB.scan_runs(
            self.root, now=NOW, active_window_seconds=WINDOW).runs}[PARKED_KEY]
        self.assertEqual(parked["disposition"]["reason"], "test_failure")
        self.assertEqual(parked["earlier_terminations"], [])

    def test_hist_fr3_the_newest_round_of_each_phase_carries_the_fallback(self) -> None:
        run = self._resumed()
        self.assertEqual(run["fallbacks"], [{
            "phase": 1, "round": 2, "from": "codex",
            "error": "timed out after 900s", "to": "deepseek",
        }])

    def test_hist_fr3_a_newest_round_without_a_fallback_lists_nothing(self) -> None:
        # Round 3 gated by one reviewer: the round-2 fallback is history,
        # not what the phase ended on.
        run = self._resumed(**{"phase-1/review/findings-round-3.json": {
            "round": 3, "verdict": "PASS", "reviewer_provider": "deepseek", "findings": [],
        }})
        self.assertEqual(run["fallbacks"], [])
        runs = {r["key"]: r for r in AB.scan_runs(self.root, now=NOW, active_window_seconds=WINDOW).runs}
        # No findings file at all, and no review directory at all.
        self.assertEqual(runs[LANDED_KEY]["fallbacks"], [])
        self.assertEqual(runs[TERMINATED_KEY]["fallbacks"], [])

    def test_hist_fr4_render_run_says_probe_terminations_and_fallbacks(self) -> None:
        run = self._resumed()
        text = "\n".join(AB.render_run(run))
        self.assertIn("probe: deepseek answered PASS in 17s, $0.12", text)
        self.assertIn("earlier termination: provider_unavailable at 2026-09-09T02:00:00Z (phase 1)", text)
        self.assertIn("termination-1788900000.json", text)
        self.assertIn("fallback in phase 1 round 2: codex produced no review "
                      "(timed out after 900s); deepseek gated the round", text)

    def test_hist_fr4_a_run_without_any_of_the_three_says_so(self) -> None:
        payload = AB.list_runs(self.db, self.cfg, now=NOW)
        landed = "\n".join(AB.render_run({r["key"]: r for r in payload["runs"]}[LANDED_KEY]))
        self.assertIn("probe: none recorded", landed)
        self.assertNotIn("earlier termination", landed)
        self.assertNotIn("fallback in phase", landed)

    def test_hist_fr4_an_unanswered_probe_still_renders_who_was_asked(self) -> None:
        run = self._resumed(**{C.LEDGER_PROBE_FILE: {
            "probe": True, "requested_provider": "codex", "provider": None, "verdict": None,
            "parseable": False, "duration_sec": 0, "invocation_cost_usd": None,
            "error": "no provider in the chain for codex passed its healthcheck",
        }})
        self.assertIn("probe: codex answered no parseable verdict in 0s, unmetered — "
                      "no provider in the chain for codex passed its healthcheck",
                      "\n".join(AB.render_run(run)))
        # A probe record without a duration says nothing about time
        # rather than "0s" (DeepSeek's review of the build commit).
        run["probe"]["duration_sec"] = None
        self.assertIn("probe: codex answered no parseable verdict, unmetered — ", "\n".join(AB.render_run(run)))

    def test_hist_fr4_render_list_marks_a_run_resumed_after_a_termination(self) -> None:
        self._resumed()
        text = "\n".join(AB.render_list(AB.list_runs(self.db, self.cfg, now=NOW)))
        self.assertIn("resumed after 1 termination", text)
        self.assertNotIn("resumed after 1 terminations", text)
        # Only the resumed run's line carries it.
        marked = [line for line in text.splitlines() if "resumed after" in line]
        self.assertEqual(len(marked), 1)
        self.assertIn(self.RESUMED_KEY, marked[0])

    def test_hist_fr5_the_record_carries_the_three_fields_the_helpers_read(self) -> None:
        """studio/lib/runsView.ts reads run.probe, run.earlier_terminations
        and run.fallbacks; the states script asserts the helpers, this
        asserts the API gives them the fields they read (FR-6)."""
        run = self._resumed()
        for field in ("probe", "earlier_terminations", "fallbacks"):
            self.assertIn(field, run)
        self.assertEqual(sorted(run["probe"]), sorted(
            ["provider", "requested_provider", "verdict", "parseable",
             "duration_sec", "invocation_cost_usd", "error"]))
        self.assertEqual(sorted(run["earlier_terminations"][0]),
                         sorted(["reason", "detail", "phase", "created", "file"]))
        self.assertEqual(sorted(run["fallbacks"][0]),
                         sorted(["phase", "round", "from", "error", "to"]))
        detail = AB.run_detail(self.db, self.cfg, self.RESUMED_KEY, now=NOW)
        self.assertEqual(detail["probe"]["verdict"], "PASS")
        self.assertEqual(len(detail["earlier_terminations"]), 1)
        self.assertEqual(len(detail["fallbacks"]), 1)


class TestApi(_Ledgers):
    def _client(self):
        import importlib.util
        from unittest import mock

        if importlib.util.find_spec("fastapi") is None or importlib.util.find_spec("httpx") is None:
            self.skipTest("fastapi/httpx not installed; API test skipped (covered in CI)")
        from fastapi.testclient import TestClient

        from session_analytics import config as cfgmod
        from session_analytics._register import register_all
        from session_analytics.api.server import create_app

        register_all()
        patches = [
            mock.patch.object(cfgmod, "_USER_CONFIG", Path("/nonexistent/session-analytics.json")),
            mock.patch.object(cfgmod, "parse_env_file", return_value={}),
            mock.patch.dict("os.environ", {cfgmod.ENV_AUTO_BUILD_ROOT: str(self.root)}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return TestClient(create_app(self.dsn), base_url="http://127.0.0.1:8765")

    def test_fr5_routes(self) -> None:
        client = self._client()
        body = client.get("/api/runs").json()
        self.assertEqual(body["summary"]["by_outcome"], {"landed": 1, "terminated_policy": 1})
        self.assertEqual(body["root"]["path"], str(self.root))
        self.assertTrue(body["root"]["is_dir"])
        detail = client.get(f"/api/runs/{TERMINATED_KEY}").json()
        self.assertEqual(detail["disposition"]["reason"], "provider_unavailable")
        self.assertIn("events", detail)
        self.assertEqual(client.get("/api/runs/no-such-run").status_code, 404)
        put = client.put(f"/api/runs/{LANDED_KEY}/verdict", json={"verdict": "merged_with_fixes", "note": "fixed FR-3"})
        self.assertEqual(put.status_code, 200)
        self.assertEqual(put.json()["verdict"]["verdict"], "merged_with_fixes")
        bad = client.put(f"/api/runs/{LANDED_KEY}/verdict", json={"verdict": "approved"})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("merged_unmodified", bad.json()["detail"])
        self.assertEqual(client.put("/api/runs/no-such-run/verdict", json={"verdict": "rejected"}).status_code, 404)
        cleared = client.delete(f"/api/runs/{LANDED_KEY}/verdict")
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["verdict"])
        self.assertEqual(client.delete("/api/runs/no-such-run/verdict").status_code, 404)


if __name__ == "__main__":
    unittest.main()
