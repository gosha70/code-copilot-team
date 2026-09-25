# Expectations and their evaluation (#371 A5).
#
# The ledgers this reads are written by scripts/auto-build-loop.sh into
# .cct/, which is GITIGNORED — the real ones exist only on a machine that
# has run the driver. So the shapes are reproduced as a fixture here and
# asserted everywhere, and the real-ledger check is a separate, guarded
# test that adds confidence locally without being the only coverage.

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics import expectations as E
from session_analytics.adapters import claude_code
from session_analytics.ingest.pipeline import ingest
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

REPO = Path(__file__).resolve().parents[3]


def _real_ledger_root() -> Path:
    """The .cct holding real ledgers, which is NOT in a worktree: it is
    gitignored, so it exists only in the checkout the driver ran in.
    Resolve the main checkout via git's common dir so this test runs
    where the artifacts are instead of silently skipping there."""
    import subprocess

    candidates = [REPO]
    try:
        common = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, timeout=10,
        )
        if common.returncode == 0 and common.stdout.strip():
            candidates.append(Path(common.stdout.strip()).parent)
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        if (candidate / ".cct" / "auto-build").is_dir():
            return candidate / ".cct"
    return REPO / ".cct"


REAL_LEDGER_ROOT = _real_ledger_root()
REAL_REPO = REAL_LEDGER_ROOT.parent

SHA_1 = "sha256:" + "1" * 64
SHA_2 = "sha256:" + "2" * 64


def _contract(*frs: str) -> dict:
    return {
        "verifiers": {
            "timeout_sec": 900,
            "set": [
                {"fr": fr, "statement_sha": SHA_1 if i == 0 else SHA_2,
                 "test": f"pytest -k {fr.lower()}", "metric": None}
                for i, fr in enumerate(frs)
            ],
        }
    }


class TestNormalizeState(unittest.TestCase):
    """The driver's `green` collapses in BOTH directions, so the raw
    value alone is not the answer (A5 review)."""

    def n(self, kind, green, waived, detail):
        return E.normalize_state(kind=kind, green=green, waived=waived, detail=detail)

    def test_waived_is_unknown_and_is_tested_before_green(self) -> None:
        # The driver writes a waived visual entry green:true; its own
        # comment is that a waived invocation is never indistinguishable
        # from full verification. Trusting green first would say `met`.
        self.assertEqual(self.n("visual", True, True, "pass"), C.EXPECTATION_UNKNOWN)
        self.assertEqual(self.n("visual", True, True, "skip"), C.EXPECTATION_UNKNOWN)

    def test_green_is_met(self) -> None:
        self.assertEqual(self.n("deterministic", True, None, "exit 0"), C.EXPECTATION_MET)
        self.assertEqual(self.n("visual", True, None, "pass"), C.EXPECTATION_MET)
        self.assertEqual(self.n("runtime_conformance", True, None, "pass"), C.EXPECTATION_MET)

    def test_only_known_negative_shapes_are_not_met(self) -> None:
        self.assertEqual(self.n("deterministic", False, None, "exit 1"), C.EXPECTATION_NOT_MET)
        self.assertEqual(self.n("deterministic", False, None, "exit 137"), C.EXPECTATION_NOT_MET)
        self.assertEqual(self.n("runtime_conformance", False, None, "fail"), C.EXPECTATION_NOT_MET)
        self.assertEqual(self.n("visual", False, None, "fail"), C.EXPECTATION_NOT_MET)

    def test_inconclusive_outcomes_are_unknown(self) -> None:
        self.assertEqual(
            self.n("deterministic", False, None, "hit its 900s bound"), C.EXPECTATION_UNKNOWN
        )
        self.assertEqual(
            self.n("deterministic", False, None, "could not be bounded or cleaned up"),
            C.EXPECTATION_UNKNOWN,
        )
        # `unreached` is how the harness answers a criterion it aborted
        # before judging; no policy turns an abort into verification.
        self.assertEqual(self.n("visual", False, None, "unreached"), C.EXPECTATION_UNKNOWN)

    def test_wording_drift_falls_back_to_unknown_never_to_failure(self) -> None:
        """The failure mode this inversion closes: a reword in
        auto-build-loop.sh must not turn "we could not tell" into "it
        failed"."""
        for drifted in (
            "exceeded its token budget",          # a future bound, worded anew
            "timed out after 900 seconds",        # the same fact, reworded
            "aborted: harness unavailable",
            "EXIT 1 (nonzero)",                   # not the exact shape
            "exit",                               # malformed
            "exit zero",
            "",
            None,
        ):
            self.assertEqual(
                self.n("deterministic", False, None, drifted),
                C.EXPECTATION_UNKNOWN,
                f"{drifted!r} must not be read as a failure",
            )
        # An unfamiliar verifier kind is conservative for the same reason.
        self.assertEqual(self.n("brand_new_kind", False, None, "fail"), C.EXPECTATION_UNKNOWN)

    def test_exit_zero_with_a_false_green_is_unknown_not_met(self) -> None:
        # Contradictory input: green says it failed, detail says exit 0.
        # Neither answer is established, so neither is asserted.
        self.assertEqual(self.n("deterministic", False, None, "exit 0"), C.EXPECTATION_UNKNOWN)


class TestRollUp(unittest.TestCase):
    def test_precedence(self) -> None:
        met, not_met, unknown = C.EXPECTATION_MET, C.EXPECTATION_NOT_MET, C.EXPECTATION_UNKNOWN
        # met only when EVERY verifier is met — the driver's own rule.
        self.assertEqual(E.roll_up([met, met]), met)
        # a failure outranks an unknown …
        self.assertEqual(E.roll_up([unknown, not_met]), not_met)
        self.assertEqual(E.roll_up([met, not_met, unknown]), not_met)
        # … and an unknown outranks a met, so one unjudged verifier
        # cannot be rounded up into a pass.
        self.assertEqual(E.roll_up([met, unknown]), unknown)
        # No results at all is UNEVALUATED, which is not a state.
        self.assertIsNone(E.roll_up([]))


class TestStatementRecovery(unittest.TestCase):
    """The frozen contract carries `statement_sha` but no text; the
    working tree's text may have changed since admission."""

    def test_a_hash_match_is_accepted_and_recorded_as_recovered(self) -> None:
        statement = "the thing the system must do"
        sha = E.statement_sha("FR-1", statement)
        text, source = E.accept_statement("FR-1", statement, sha)
        self.assertEqual((text, source), (statement, C.STATEMENT_SOURCE_RECOVERED))

    def test_a_mismatch_is_unavailable_not_a_smaller_problem(self) -> None:
        # Text that does not hash to the admitted sha is not what was
        # admitted; storing it would present a later edit as history.
        text, source = E.accept_statement("FR-1", "edited after admission", SHA_1)
        self.assertEqual((text, source), (None, C.STATEMENT_SOURCE_UNAVAILABLE))

    def test_absent_text_is_unavailable(self) -> None:
        self.assertEqual(
            E.accept_statement("FR-1", None, SHA_1), (None, C.STATEMENT_SOURCE_UNAVAILABLE)
        )

    def test_recovery_returns_empty_without_a_base_ref_or_a_reachable_commit(self) -> None:
        self.assertEqual(E.recover_statements(REPO, "any", None), {})
        self.assertEqual(E.recover_statements(REPO, "any", "0" * 40), {})
        # A directory that is not a repository at all.
        self.assertEqual(
            E.recover_statements(Path(tempfile.mkdtemp()), "any", "HEAD"), {}
        )


class LedgerFixture(RegistryResetTestCase):
    """A ledger tree with the shape the real ones have: one run that
    reached the landing gate, and several that were terminated before
    it and therefore have no recoverable consolidated result."""

    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        apply_ddl(self.db)
        self.root = Path(tempfile.mkdtemp(prefix="cct-sa-ledgers-"))

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def write_run(
        self, sub, dirname, *, feature, attempt, frs=("FR-1", "FR-2"), status="done",
        results=True, init_ts="2026-01-01T00:00:00Z", base="f75ebaa", gate=True,
        sessions=(("sess-tiny-001", 1),), init_detail="profile=unattended branch=b base=f75ebaa",
    ):
        ledger = self.root / sub / dirname
        (ledger / "phase-1").mkdir(parents=True, exist_ok=True)
        contract = _contract(*frs)
        (ledger / "state.json").write_text(json.dumps({
            "schema_version": 1, "feature_id": feature, "attempt_id": attempt,
            "status": status, "outcome": "landed" if status == "done" else None,
            "branch_base_ref": base, "preflight": {"contract": contract},
        }))
        events = [{"ts": init_ts, "event": "init", "detail": init_detail}]
        if gate:
            events.append({"ts": "2026-01-01T01:00:00Z", "event": "verifier_gate",
                           "detail": f"all mapped verifiers green ({len(frs)} FR(s))"})
        (ledger / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n"
        )
        if results:
            (ledger / "verification-results.json").write_text(json.dumps({
                "schema_version": 1, "green": True,
                "frs": {fr: {"green": True, "verifiers": [{
                    "fr": fr, "kind": "deterministic", "verifier": f"pytest -k {fr}",
                    "statement_sha": SHA_1, "green": True, "detail": "exit 0",
                    "log": f".cct/conformance/{fr}.log"}]} for fr in frs},
            }))
        for sid, phase in sessions:
            (ledger / f"phase-{phase}").mkdir(parents=True, exist_ok=True)
            (ledger / f"phase-{phase}" / "build-result-1.json").write_text(json.dumps(
                [{"type": "system", "subtype": "init", "session_id": sid}]
            ))
        return ledger


class TestIngestPass(LedgerFixture):
    def test_the_six_run_shape_one_gated_and_five_terminated(self) -> None:
        """The distribution the real ledgers have: only a run that
        reached the landing gate has results or an evaluated_at."""
        self.write_run("auto-build", "feat-a", feature="feat-a", attempt="a1")
        for i in range(5):
            self.write_run(
                "auto-build-archive", f"feat-a-run{i}", feature="feat-a",
                attempt=f"old{i}", status="terminated_policy", results=False, gate=False,
                init_ts=f"2025-12-0{i + 1}T00:00:00Z",
            )
        stats = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual((stats.runs_seen, stats.runs_stored, stats.runs_skipped), (6, 6, 0))
        self.assertEqual(stats.expectations_stored, 12)     # 6 runs × 2 FRs
        self.assertEqual(stats.results_stored, 2)           # only the gated run
        self.assertEqual(self.db.query_one(
            f"SELECT COUNT(*) FROM {C.TBL_EXPECTATION_RUN} WHERE evaluated_at IS NOT NULL")[0], 1)
        # 10 of 12 expectations are UNEVALUATED: no recoverable
        # consolidated result, which is not "no verifier ran".
        unevaluated = self.db.query_one(
            f"SELECT COUNT(*) FROM {C.TBL_EXPECTATION} e WHERE NOT EXISTS "
            f"(SELECT 1 FROM {C.TBL_EXPECTATION_RESULT} r WHERE r.expectation_ref = e.id)")[0]
        self.assertEqual(unevaluated, 10)

    def test_a_failed_run_has_no_evaluated_at(self) -> None:
        # verifier_gate is journalled only after an all-green gate.
        self.write_run("auto-build", "f", feature="f", attempt="a", gate=False)
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertIsNone(self.db.query_one(
            f"SELECT evaluated_at FROM {C.TBL_EXPECTATION_RUN}")[0])

    def test_idempotence(self) -> None:
        self.write_run("auto-build", "f", feature="f", attempt="a")
        first = E.ingest_runs(self.db, self.root, project_dir=REPO)
        second = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual(first.expectations_stored, 2)
        self.assertEqual((second.expectations_stored, second.results_stored,
                          second.sessions_recorded), (0, 0, 0))
        self.assertEqual(second.runs_stored, 1)
        for table, expected in ((C.TBL_EXPECTATION_RUN, 1), (C.TBL_EXPECTATION, 2),
                                (C.TBL_EXPECTATION_RESULT, 2), (C.TBL_EXPECTATION_SESSION, 1)):
            self.assertEqual(self.db.query_one(f"SELECT COUNT(*) FROM {table}")[0], expected, table)

    def test_an_attempt_collision_is_refused_not_merged(self) -> None:
        """Two real runs can share an attempt_id and, with an unchanged
        spec, a contract digest too — so only the run fingerprint tells
        them apart, and the first run's results must survive."""
        self.write_run("auto-build", "f", feature="f", attempt="same")
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        before = self.db.query("SELECT id, run_fingerprint FROM " + C.TBL_EXPECTATION_RUN)
        # A different run: same feature, same attempt id, same contract,
        # different init event.
        self.write_run("auto-build-archive", "f-again", feature="f", attempt="same",
                       init_ts="2026-06-06T06:06:06Z", results=False, gate=False)
        stats = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual(stats.runs_skipped, 1)
        self.assertTrue(any("different run_fingerprint" in s.reason for s in stats.skipped))
        self.assertEqual(self.db.query("SELECT id, run_fingerprint FROM " + C.TBL_EXPECTATION_RUN),
                         before, "the stored run must be untouched")
        self.assertEqual(self.db.query_one(
            f"SELECT COUNT(*) FROM {C.TBL_EXPECTATION_RESULT}")[0], 2)

    def test_a_ledger_without_an_identity_is_skipped_with_a_reason(self) -> None:
        for name, payload in (
            ("no-state", None),
            ("no-attempt", {"feature_id": "x", "preflight": {"contract": _contract("FR-1")}}),
            ("no-contract", {"feature_id": "x", "attempt_id": "a"}),
        ):
            d = self.root / "auto-build" / name
            d.mkdir(parents=True)
            if payload is not None:
                (d / "state.json").write_text(json.dumps(payload))
        # A ledger with an identity and a contract but no init event
        # cannot be fingerprinted, so it is skipped too.
        self.write_run("auto-build", "no-init", feature="ni", attempt="ni")
        (self.root / "auto-build" / "no-init" / "events.jsonl").write_text("")
        stats = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual((stats.runs_stored, stats.runs_skipped), (0, 4))
        reasons = " | ".join(s.reason for s in stats.skipped)
        for expected in ("no readable state.json", "no attempt_id", "no frozen contract", "init"):
            self.assertIn(expected, reasons)

    def test_an_unmatched_session_identity_is_persisted_and_resolved_later(self) -> None:
        """The row is keyed by the DISCOVERED identity, so a transcript
        ingested after the first scan is not lost — and coverage can
        tell "recorded but not in the store" from "none recorded"."""
        self.write_run("auto-build", "f", feature="f", attempt="a",
                       sessions=(("not-yet-ingested", 1),))
        stats = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual((stats.sessions_recorded, stats.sessions_unresolved,
                          stats.sessions_resolved), (1, 1, 0))
        row = self.db.query_one(
            f"SELECT session_id, session_ref FROM {C.TBL_EXPECTATION_SESSION}")
        self.assertEqual(row[0], "not-yet-ingested")
        self.assertIsNone(row[1], "an unmatched identity is recorded, not dropped")
        # The transcript arrives later.
        session_ref = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, "
            "turn_count, tool_call_count, error_count, started_at) "
            "VALUES (?, 'not-yet-ingested', '/p', 'local', 1, 0, 0, '2026-01-01T00:00:00Z') "
            "RETURNING id", (C.COPILOT_CLAUDE_CODE,))
        self.db.commit()
        second = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual(second.sessions_resolved, 1)
        self.assertEqual(self.db.query_one(
            f"SELECT session_ref FROM {C.TBL_EXPECTATION_SESSION}")[0], session_ref)
        self.assertEqual(self.db.query_one(
            f"SELECT COUNT(*) FROM {C.TBL_EXPECTATION_SESSION}")[0], 1, "resolved, not duplicated")

    def test_a_session_already_in_the_store_resolves_on_the_first_pass(self) -> None:
        self.write_run("auto-build", "f", feature="f", attempt="a")
        stats = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual((stats.sessions_resolved, stats.sessions_unresolved), (1, 0))
        self.assertIsNotNone(self.db.query_one(
            f"SELECT session_ref FROM {C.TBL_EXPECTATION_SESSION}")[0])

    def test_statements_are_unavailable_when_the_base_commit_is_unreachable(self) -> None:
        self.write_run("auto-build", "f", feature="f", attempt="a", base="0" * 40)
        stats = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual(stats.statements_recovered, 0)
        self.assertEqual(stats.statements_unavailable, 2)
        rows = self.db.query(
            f"SELECT statement, statement_source FROM {C.TBL_EXPECTATION}")
        for statement, source in rows:
            self.assertIsNone(statement, "current text must never be substituted")
            self.assertEqual(source, C.STATEMENT_SOURCE_UNAVAILABLE)


@unittest.skipUnless(
    (REAL_LEDGER_ROOT / "auto-build").is_dir(),
    ".cct/ is gitignored: the real ledgers exist only on a machine that has run the driver",
)
class TestAgainstTheRealLedgers(RegistryResetTestCase):
    """Confidence against artifacts this code did not author. It cannot
    run in CI — .cct/ is not tracked — so TestIngestPass above carries
    the same assertions over a fixture."""

    def test_every_real_run_is_stored_and_every_statement_verifies(self) -> None:
        db = Database.connect(self.sqlite_dsn())
        apply_ddl(db)
        try:
            stats = E.ingest_runs(db, REAL_LEDGER_ROOT, project_dir=REAL_REPO)
            self.assertGreater(stats.runs_seen, 0)
            self.assertEqual(stats.runs_skipped, 0, [s.reason for s in stats.skipped])
            # Every admitted statement recovers from its base commit and
            # hashes to the sha frozen at admission.
            self.assertEqual(stats.statements_unavailable, 0)
            self.assertEqual(stats.statements_recovered, stats.expectations_stored)
            # Only a run that reached the landing gate has results.
            gated = db.query_one(
                f"SELECT COUNT(*) FROM {C.TBL_EXPECTATION_RUN} WHERE evaluated_at IS NOT NULL")[0]
            with_results = db.query_one(
                f"SELECT COUNT(DISTINCT e.run_ref) FROM {C.TBL_EXPECTATION} e "
                f"JOIN {C.TBL_EXPECTATION_RESULT} r ON r.expectation_ref = e.id")[0]
            self.assertEqual(gated, with_results)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()


class TestHarnessAttribution(LedgerFixture):
    """A4b at RUN grain (#371 A5 FR-13): a run counts in a harness row
    only when every session it discovered is linked AND all of them
    fall in that row. Anything else is excluded and counted at the top
    level, because an excluded run belongs to no row."""

    def _session(self, session_id: str, cli_version: str | None, *, mixed=0) -> int:
        ref = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, "
            "turn_count, tool_call_count, error_count, started_at, cli_version, harness_mixed) "
            "VALUES (?, ?, '/p', 'local', 12, 2, 0, '2026-02-02T00:00:00Z', ?, ?) RETURNING id",
            (C.COPILOT_CLAUDE_CODE, session_id, cli_version, mixed),
        )
        self.db.commit()
        return int(ref)

    def _aggregate(self):
        from session_analytics.api.dashboard import harness_aggregates

        return harness_aggregates(self.db, by="cli_version")

    def _row(self, agg, value):
        return next(r for r in agg["rows"] if r["value"] == value)

    def test_a_run_whose_sessions_agree_is_attributed_once(self) -> None:
        self._session("s-a", "2.1.1")
        self._session("s-b", "2.1.1")
        self.write_run("auto-build", "f", feature="f", attempt="a",
                       sessions=(("s-a", 1), ("s-b", 2)))
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        agg = self._aggregate()
        row = self._row(agg, "2.1.1")
        self.assertEqual(row["runs_with_expectations"], 1)
        self.assertEqual((row["expectations_met"], row["expectations_evaluated"]), (2, 2))
        self.assertEqual(row["expectation_rate"], 1.0)
        self.assertEqual(agg["runs_spanning_groups"], 0)
        self.assertEqual(agg["runs_with_unmatched_sessions"], 0)

    def test_a_run_with_zero_discovered_sessions_is_unattributable(self) -> None:
        """NOT vacuously attributable: "all its sessions agree" is
        trivially true of an empty set, which would otherwise drop a
        sessionless run into whichever row came first."""
        self._session("elsewhere", "2.1.1")
        self.write_run("auto-build", "f", feature="f", attempt="a", sessions=())
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        agg = self._aggregate()
        self.assertEqual(agg["runs_with_unmatched_sessions"], 1)
        self.assertEqual(agg["runs_spanning_groups"], 0)
        for row in agg["rows"]:
            self.assertEqual(row["runs_with_expectations"], 0, row["value"])
            self.assertEqual(row["expectations_evaluated"], 0, row["value"])
            self.assertIsNone(row["expectation_rate"], row["value"])

    def test_a_run_spanning_two_harness_rows_is_excluded_and_counted(self) -> None:
        self._session("s-old", "2.1.1")
        self._session("s-new", "2.9.9")
        self.write_run("auto-build", "f", feature="f", attempt="a",
                       sessions=(("s-old", 1), ("s-new", 2)))
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        agg = self._aggregate()
        self.assertEqual(agg["runs_spanning_groups"], 1)
        self.assertEqual(agg["runs_with_unmatched_sessions"], 0)
        # Counting it in both rows would duplicate one run's outcome.
        for value in ("2.1.1", "2.9.9"):
            self.assertEqual(self._row(agg, value)["runs_with_expectations"], 0)

    def test_a_run_with_an_unlinked_session_is_excluded_separately(self) -> None:
        self._session("s-known", "2.1.1")
        self.write_run("auto-build", "f", feature="f", attempt="a",
                       sessions=(("s-known", 1), ("never-ingested", 2)))
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        agg = self._aggregate()
        self.assertEqual(agg["runs_with_unmatched_sessions"], 1)
        self.assertEqual(agg["runs_spanning_groups"], 0)
        self.assertEqual(self._row(agg, "2.1.1")["runs_with_expectations"], 0)

    def test_session_coverage_counts_distinct_sessions_not_association_rows(self) -> None:
        """Repeated runs over the same session must not inflate a row's
        session coverage."""
        self._session("shared", "2.1.1")
        for i in range(3):
            self.write_run("auto-build", f"f{i}", feature=f"f{i}", attempt=f"a{i}",
                           sessions=(("shared", 1),), init_ts=f"2026-03-0{i + 1}T00:00:00Z")
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        row = self._row(self._aggregate(), "2.1.1")
        self.assertEqual(row["runs_with_expectations"], 3)
        self.assertEqual(
            self.db.query_one(f"SELECT COUNT(*) FROM {C.TBL_EXPECTATION_SESSION}")[0], 3,
            "three association rows exist",
        )
        self.assertEqual(row["sessions_with_expectations"], 1, "but only one distinct session")

    def test_unknown_and_unevaluated_are_in_neither_side_of_the_rate(self) -> None:
        self._session("s", "2.1.1")
        # One run that reached the gate, one that did not (unevaluated).
        self.write_run("auto-build", "gated", feature="gated", attempt="g",
                       sessions=(("s", 1),))
        self.write_run("auto-build", "ungated", feature="ungated", attempt="u",
                       sessions=(("s", 1),), results=False, gate=False,
                       init_ts="2026-04-04T00:00:00Z")
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        # Turn one stored result into an `unknown` the way a bound does.
        self.db.execute(
            f"UPDATE {C.TBL_EXPECTATION_RESULT} SET state = ?, green = 0, "
            "detail = 'hit its 900s bound' WHERE id = (SELECT MIN(id) FROM "
            f"{C.TBL_EXPECTATION_RESULT})", (C.EXPECTATION_UNKNOWN,))
        self.db.commit()
        row = self._row(self._aggregate(), "2.1.1")
        self.assertEqual(row["runs_with_expectations"], 2)
        self.assertEqual(row["expectations_unknown"], 1)
        self.assertEqual(row["expectations_unevaluated"], 2)   # the ungated run's two FRs
        self.assertEqual((row["expectations_met"], row["expectations_evaluated"]), (1, 1))
        # met/evaluated over met+not_met only: the unknown and the two
        # unevaluated are in neither the numerator nor the denominator.
        self.assertEqual(row["expectation_rate"], 1.0)

    def test_the_rate_is_null_never_zero_without_an_evaluated_expectation(self) -> None:
        self._session("s", "2.1.1")
        self.write_run("auto-build", "f", feature="f", attempt="a",
                       sessions=(("s", 1),), results=False, gate=False)
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        row = self._row(self._aggregate(), "2.1.1")
        self.assertEqual(row["runs_with_expectations"], 1)
        self.assertEqual(row["expectations_unevaluated"], 2)
        self.assertEqual(row["expectations_evaluated"], 0)
        self.assertIsNone(row["expectation_rate"], "0.0 would claim every expectation failed")

    def test_a_mixed_session_run_lands_in_the_mixed_row_not_a_version(self) -> None:
        self._session("s-mixed", "2.1.1", mixed=1)
        self.write_run("auto-build", "f", feature="f", attempt="a", sessions=(("s-mixed", 1),))
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        agg = self._aggregate()
        mixed = next(r for r in agg["rows"] if r["kind"] == C.HARNESS_GROUP_MIXED)
        self.assertEqual(mixed["runs_with_expectations"], 1)
        self.assertEqual(agg["runs_with_unmatched_sessions"], 0)


class TestUncappedInternalPath(LedgerFixture):
    """The aggregate is defined over EVERY stored run. A cap there would
    drop later runs out of the row totals and out of the exclusion
    counters alike, so the loss would not even read as missing
    coverage."""

    def test_the_aggregate_sees_runs_a_capped_call_would_hide(self) -> None:
        from session_analytics.api.dashboard import harness_aggregates

        self._sref = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, "
            "turn_count, tool_call_count, error_count, started_at, cli_version, harness_mixed) "
            "VALUES (?, 's-cap', '/p', 'local', 9, 1, 0, '2026-05-05T00:00:00Z', '2.4.4', 0) "
            "RETURNING id", (C.COPILOT_CLAUDE_CODE,))
        self.db.commit()
        runs = 5
        for i in range(runs):
            self.write_run("auto-build", f"f{i}", feature=f"f{i}", attempt=f"a{i}",
                           sessions=(("s-cap", 1),), init_ts=f"2026-05-0{i + 1}T00:00:00Z")
        E.ingest_runs(self.db, self.root, project_dir=REPO)

        # A capped call really does hide runs …
        self.assertEqual(len(E.list_runs(self.db, limit=2)), 2)
        # … while the uncapped one the aggregate uses sees them all.
        self.assertEqual(len(E.list_runs(self.db, limit=None)), runs)

        row = next(r for r in harness_aggregates(self.db, by="cli_version")["rows"]
                   if r["value"] == "2.4.4")
        self.assertEqual(row["runs_with_expectations"], runs,
                         "every stored run must reach the aggregate")
        self.assertEqual(row["expectations_evaluated"], runs * 2)


class TestStatementDurability(LedgerFixture):
    """A recovered statement is the durable record this table exists to
    keep: it must survive the base commit going away.

    The fixture uses a spec that really is committed at a real base —
    `specs/team-developer-aliases/spec.md` at the commit that run
    branched from — because recovery is only meaningful against a
    reachable commit."""

    BASE = "f75ebaa5a09eab39a98497f6ab827f241501b46b"
    FEATURE = "team-developer-aliases"

    def _real_fr(self):
        text = subprocess.run(
            ["git", "-C", str(REPO), "show", f"{self.BASE}:specs/{self.FEATURE}/spec.md"],
            capture_output=True, text=True,
        )
        self.assertEqual(text.returncode, 0, "the base commit must be reachable")
        parsed = subprocess.run(
            ["bash", "-c",
             f"source {REPO}/scripts/lib/verification-common.sh && vc_extract_frs /dev/stdin"],
            input=text.stdout, capture_output=True, text=True,
        )
        fr, _, statement = parsed.stdout.splitlines()[0].partition("\t")
        return fr, statement

    def _write(self, *, base, attempt):
        fr, statement = self._real_fr()
        ledger = self.write_run("auto-build", self.FEATURE, feature=self.FEATURE,
                                attempt=attempt, frs=(fr,), base=base)
        state = json.loads((ledger / "state.json").read_text())
        state["preflight"]["contract"]["verifiers"]["set"][0]["statement_sha"] = \
            E.statement_sha(fr, statement)
        (ledger / "state.json").write_text(json.dumps(state))
        return ledger, state

    def _stored(self):
        return self.db.query_one(
            f"SELECT statement, statement_source FROM {C.TBL_EXPECTATION}")

    def test_a_later_unavailable_recovery_never_erases_a_recovered_statement(self) -> None:
        """The LEDGER is unchanged — only recovery fails. That is what
        a garbage-collected base commit, a wrong --project-dir or a
        missing parser all look like. (Editing `branch_base_ref` would
        instead change the run fingerprint, and the pass would correctly
        refuse it as a different run.)"""
        self._write(base=self.BASE, attempt="dur")
        first = E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.assertEqual(first.statements_recovered, 1, "pass 1 must recover the text")
        stored = self._stored()
        self.assertEqual(stored[1], C.STATEMENT_SOURCE_RECOVERED)
        self.assertIsNotNone(stored[0])

        # Pass 2 from a directory that is not the project: recovery
        # cannot succeed, and the stored text must survive it.
        elsewhere = Path(tempfile.mkdtemp(prefix="cct-sa-not-a-repo-"))
        second = E.ingest_runs(self.db, self.root, project_dir=elsewhere)
        self.assertEqual(self._stored(), stored,
                         "the recovered statement must be byte-identical after a failed rescan")
        self.assertEqual(second.statements_unavailable, 0)
        self.assertEqual(second.statements_recovered, 1, "still held, not lost")

    def test_an_unavailable_statement_is_promoted_when_recovery_later_succeeds(self) -> None:
        self._write(base=self.BASE, attempt="promote")
        elsewhere = Path(tempfile.mkdtemp(prefix="cct-sa-not-a-repo-"))
        E.ingest_runs(self.db, self.root, project_dir=elsewhere)
        self.assertEqual(self._stored()[1], C.STATEMENT_SOURCE_UNAVAILABLE)
        # The same ledger, now scanned from the real project.
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        row = self._stored()
        self.assertEqual(row[1], C.STATEMENT_SOURCE_RECOVERED)
        self.assertIsNotNone(row[0])


def _tool_payload(result):
    """The object a FastMCP tool returned, whichever shape the SDK hands
    back (structured content, or a JSON text block)."""
    if isinstance(result, tuple):
        result = result[1] if len(result) > 1 and isinstance(result[1], (list, dict)) else result[0]
    if isinstance(result, dict) and "result" in result:
        return result["result"]
    if isinstance(result, list) and result and hasattr(result[0], "text"):
        return json.loads(result[0].text)
    return result


class TestReadSurfaceContract(LedgerFixture):
    """FR-12/FR-14: the HTTP and MCP surfaces must expose and FORWARD
    every parameter. A2 shipped an MCP wrapper that silently dropped its
    filters at exactly this boundary."""

    def setUp(self) -> None:
        super().setUp()
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, "
            "turn_count, tool_call_count, error_count, started_at, cli_version, harness_mixed) "
            "VALUES (?, 'sess-tiny-001-x', '/p', 'local', 3, 0, 0, "
            "'2026-07-07T00:00:00Z', '2.0.0', 0)", (C.COPILOT_CLAUDE_CODE,))
        self.db.commit()
        # One gated run and one that never reached the landing gate.
        self.write_run("auto-build", "alpha", feature="alpha", attempt="a1")
        self.write_run("auto-build", "beta", feature="beta", attempt="b1",
                       results=False, gate=False, init_ts="2026-07-02T00:00:00Z")
        E.ingest_runs(self.db, self.root, project_dir=REPO)
        self.db.close()

    def _client(self):
        from fastapi.testclient import TestClient

        from session_analytics._register import unregister_all_for_tests
        from session_analytics.api.server import create_app

        # create_app runs register_all itself; the fixture already
        # registered the adapter, so clear the registry first.
        unregister_all_for_tests()
        # #103: an allowlisted Host — TestClient defaults to `testserver`,
        # which the Host guard correctly rejects.
        return TestClient(create_app(self.dsn), base_url="http://127.0.0.1:8765")

    def test_http_filters_limit_and_null_not_zero(self) -> None:
        if importlib.util.find_spec("fastapi") is None:
            self.skipTest("fastapi not installed")
        c = self._client()
        body = c.get("/api/expectations").json()
        self.assertEqual(len(body["runs"]), 2)
        # feature_id narrows …
        alpha = c.get("/api/expectations", params={"feature_id": "alpha"}).json()["runs"]
        self.assertEqual([r["feature_id"] for r in alpha], ["alpha"])
        # … attempt_id narrows …
        beta = c.get("/api/expectations", params={"attempt_id": "b1"}).json()["runs"]
        self.assertEqual([r["attempt_id"] for r in beta], ["b1"])
        # … an unknown value is empty, not everything.
        self.assertEqual(
            c.get("/api/expectations", params={"feature_id": "nope"}).json()["runs"], [])
        # … and limit actually limits.
        self.assertEqual(len(c.get("/api/expectations", params={"limit": 1}).json()["runs"]), 1)
        # The gated run has a rate; the ungated one is null, NEVER 0.
        rate_by_feature = {r["feature_id"]: r["rate"] for r in body["runs"]}
        self.assertEqual(rate_by_feature["alpha"], 1.0)
        self.assertIsNone(rate_by_feature["beta"], "0.0 would claim every expectation failed")
        ungated = next(r for r in body["runs"] if r["feature_id"] == "beta")
        self.assertEqual(ungated["expectations_unevaluated"], 2)
        self.assertEqual(ungated["expectations_evaluated"], 0)
        self.assertIsNone(ungated["evaluated_at"], "no verifier_gate event on a failed run")
        # The statement and its provenance reach the client.
        gated = next(r for r in body["runs"] if r["feature_id"] == "alpha")
        self.assertIn(gated["expectations"][0]["statement_source"], C.STATEMENT_SOURCES)
        self.assertEqual(gated["expectations"][0]["state"], C.EXPECTATION_MET)

    def test_mcp_wrapper_exposes_and_forwards_every_parameter(self) -> None:
        import asyncio

        try:
            from session_analytics.mcp.server import build_server

            server = build_server(self.dsn)
        except ImportError:
            self.skipTest("mcp SDK not installed")
        tool = next(
            t for t in asyncio.run(server.list_tools()) if t.name == "list_expectations"
        )
        props = set(tool.inputSchema.get("properties", {}))
        for name in ("feature_id", "attempt_id", "limit"):
            self.assertIn(name, props, f"{name} missing from the registered MCP schema")
        # And each one reaches the query.
        every = _tool_payload(asyncio.run(server.call_tool("list_expectations", {})))
        self.assertEqual(len(every["runs"]), 2)
        one = _tool_payload(
            asyncio.run(server.call_tool("list_expectations", {"feature_id": "alpha"})))
        self.assertEqual([r["feature_id"] for r in one["runs"]], ["alpha"])
        capped = _tool_payload(asyncio.run(server.call_tool("list_expectations", {"limit": 1})))
        self.assertEqual(len(capped["runs"]), 1)
        missing = _tool_payload(
            asyncio.run(server.call_tool("list_expectations", {"attempt_id": "nope"})))
        self.assertEqual(missing["runs"], [])

    def test_run_detail_is_enriched_live_and_none_for_a_never_ingested_run(self) -> None:
        from session_analytics.api import auto_build as ab
        from session_analytics.config import AutoBuildConfig
        from session_analytics.relational.db import Database

        db = Database.connect(self.dsn)
        cfg = AutoBuildConfig(ledger_root=str(self.root), active_window_seconds=3600)
        try:
            detail = ab.run_detail(db, cfg, "a1")
            self.assertIsNotNone(detail)
            self.assertIsNotNone(detail["expectations"], "a stored run must be enriched")
            self.assertEqual(detail["expectations"]["expectations_met"], 2)
            self.assertEqual(
                detail["expectations"]["expectations"][0]["state"], C.EXPECTATION_MET)
            # A run whose ledger exists but which was never ingested:
            # `expectations` is None, and that means exactly that.
            self.write_run("auto-build", "gamma", feature="gamma", attempt="g1",
                           init_ts="2026-07-03T00:00:00Z")
            self.assertIsNone(ab.run_detail(db, cfg, "g1")["expectations"])
        finally:
            db.close()
