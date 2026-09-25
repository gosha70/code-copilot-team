# The harness compare (#371 A4b): the closed filter, the facets, the
# aggregate's grouping and its refusals to invent figures.

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.api import dashboard
from session_analytics.ingest.pipeline import ingest
from session_analytics.judge.rubric import load_rubric
from session_analytics.mcp import tools
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

SHA_A = "a" * 40
SHA_B = "b" * 40
DIG_1 = "1" * 64
DIG_2 = "2" * 64


class TestHarnessClause(unittest.TestCase):
    """The dimension names a COLUMN, so it comes from the closed set and
    never from the caller."""

    def test_the_three_named_groups(self) -> None:
        sql, params = tools.harness_clause(C.HARNESS_GROUP_UNSTAMPED)
        self.assertEqual(params, [])
        for fact in C.HARNESS_FACTS:
            self.assertIn(f"{fact} IS NULL", sql)
        # No bound parameter: `IS TRUE` / `IS NOT TRUE` is the predicate,
        # because PostgreSQL refuses `boolean = integer`.
        mixed_sql, mixed_params = tools.harness_clause(C.HARNESS_GROUP_MIXED)
        self.assertEqual((mixed_sql, mixed_params), (f"{C.HARNESS_KEY_MIXED} IS TRUE", []))
        self.assertIn(tools._HARNESS_NOT_MIXED_SQL, sql)   # unstamped excludes mixed
        absent_sql, absent_params = tools.harness_clause(f"{C.HARNESS_GROUP_ABSENT}:cct_sha")
        self.assertIn("cct_sha IS NULL", absent_sql)
        self.assertIn("NOT (", absent_sql)          # stamped, just not on this dimension
        self.assertEqual(absent_params, [])

    def test_a_value_excludes_mixed_sessions(self) -> None:
        sql, params = tools.harness_clause("cli_version:2.1.5")
        self.assertEqual(params, ["2.1.5"])
        self.assertIn(tools._HARNESS_NOT_MIXED_SQL, sql)

    def test_only_the_closed_dimension_set_is_accepted(self) -> None:
        for bad in (
            "nope", "cli_version", "cli_version:", ":x", "",
            "project_path:/repo",                 # a real column, not a harness one
            "developer_id:me",
            f"{C.HARNESS_GROUP_ABSENT}:project_path",
            f"{C.HARNESS_GROUP_ABSENT}:",
        ):
            with self.assertRaises(tools.UnknownHarnessError, msg=bad):
                tools.harness_clause(bad)


class TestGroupsPartitionTheStore(RegistryResetTestCase):
    """Every session lands in exactly ONE group, and each group's filter
    returns exactly its members (A4b review, P1 + P2)."""

    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.db = Database.connect(self.sqlite_dsn())
        from session_analytics.relational.db import apply_ddl

        apply_ddl(self.db)
        # The case that made mixed and unstamped overlap: the earliest
        # stamp carried no facts, a later one differed.
        self._add("s-null-mixed", mixed=1)
        self._add("s-unstamped", mixed=None)
        self._add("s-absent", mixed=0, cli="2.1.0")          # stamped, no cct_sha
        self._add("s-value", mixed=0, cli="2.1.0", sha=SHA_A)
        # A real version string that spells a group's name (P2).
        self._add("s-literal-mixed", mixed=0, cli=C.HARNESS_GROUP_MIXED)
        self._add("s-literal-unstamped", mixed=0, cli=C.HARNESS_GROUP_UNSTAMPED)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def _add(self, sid, *, mixed, cli=None, sha=None):
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, developer_id, "
            " turn_count, tool_call_count, error_count, started_at, cli_version, cct_sha, "
            " harness_mixed) VALUES ('claude-code', ?, '/p', 'local', 5, 1, 0, "
            " '2026-01-01T00:00:00Z', ?, ?, ?)",
            (sid, cli, sha, mixed),
        )

    def _filter(self, value):
        return sorted(r["session_id"] for r in tools.search_sessions(self.db, limit=50, harness=value))

    def test_a_mixed_session_with_no_facts_is_mixed_and_nothing_else(self) -> None:
        self.assertEqual(self._filter(C.HARNESS_GROUP_MIXED), ["s-null-mixed"])
        self.assertEqual(self._filter(C.HARNESS_GROUP_UNSTAMPED), ["s-unstamped"])
        rows = dashboard.harness_aggregates(self.db, by="cli_version")["rows"]
        kinds = {r["kind"]: r for r in rows}
        self.assertEqual(kinds[C.HARNESS_GROUP_MIXED]["sessions"], 1)
        self.assertEqual(kinds[C.HARNESS_GROUP_UNSTAMPED]["sessions"], 1)

    def test_every_session_is_in_exactly_one_row_and_each_row_link_round_trips(self) -> None:
        for by in C.HARNESS_DIMENSIONS:
            agg = dashboard.harness_aggregates(self.db, by=by)
            total = sum(r["sessions"] for r in agg["rows"])
            self.assertEqual(total, 6, f"{by}: every session in exactly one row")
            seen: set[str] = set()
            for row in agg["rows"]:
                value = (
                    f"{C.HARNESS_GROUP_ABSENT}:{by}" if row["kind"] == C.HARNESS_GROUP_ABSENT
                    else row["kind"] if row["is_group"]
                    else f"{by}:{row['value']}"
                )
                ids = self._filter(value)
                self.assertEqual(
                    len(ids), row["sessions"],
                    f"{by} row {row['kind']}/{row['value']} says {row['sessions']}, link returns {ids}",
                )
                self.assertFalse(seen & set(ids), f"{by}: {ids} counted twice")
                seen |= set(ids)
            self.assertEqual(len(seen), 6, f"{by}: the links cover every session once")

    def test_a_version_string_that_spells_a_group_stays_a_value(self) -> None:
        rows = dashboard.harness_aggregates(self.db, by="cli_version")["rows"]
        literal = [r for r in rows if r["value"] == C.HARNESS_GROUP_MIXED]
        self.assertEqual(len(literal), 1)
        self.assertFalse(literal[0]["is_group"])
        self.assertEqual(literal[0]["kind"], "value")
        self.assertEqual(literal[0]["sessions"], 1)
        self.assertEqual(self._filter(f"cli_version:{C.HARNESS_GROUP_MIXED}"), ["s-literal-mixed"])
        # …and the genuinely mixed session is still its own row.
        self.assertEqual(self._filter(C.HARNESS_GROUP_MIXED), ["s-null-mixed"])
        # A named group carries no value at all.
        for row in rows:
            if row["is_group"]:
                self.assertIsNone(row["value"], row["kind"])


class TestPostgresDialect(unittest.TestCase):
    """harness_mixed is BOOLEAN: `= 0` is valid SQLite and an error on
    PostgreSQL, and the facets run on EVERY sessions request (A4b review
    P1). The generated SQL must not compare it to an integer."""

    def test_no_boolean_to_integer_comparison_is_generated(self) -> None:
        import re

        generated = [tools.harness_clause(v)[0] for v in (
            C.HARNESS_GROUP_MIXED, C.HARNESS_GROUP_UNSTAMPED,
            f"{C.HARNESS_GROUP_ABSENT}:cct_sha", "cli_version:2.1.0",
        )]
        db = Database.connect(self.__class__._dsn)
        generated.append(tools._HARNESS_NOT_MIXED_SQL)
        for sql in generated:
            self.assertIsNone(
                re.search(rf"{C.HARNESS_KEY_MIXED}\s*(=|<>|!=)\s*\d", sql),
                f"compares a boolean with an integer: {sql}",
            )
        db.close()

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile
        from pathlib import Path

        cls._dsn = f"sqlite:///{Path(tempfile.mkdtemp()) / 'd.db'}"

    def test_the_facet_query_uses_the_cross_dialect_predicate(self) -> None:
        from session_analytics.relational.db import apply_ddl

        db = Database.connect(self.__class__._dsn)
        apply_ddl(db)
        seen: list[str] = []
        original = db.execute
        db.execute = lambda sql, params=(): (seen.append(" ".join(sql.split())), original(sql, params))[1]
        try:
            tools.session_facets(db)
        finally:
            db.execute = original
        harness_queries = [q for q in seen if C.HARNESS_KEY_MIXED in q]
        self.assertTrue(harness_queries)
        for q in harness_queries:
            self.assertIn("IS NOT TRUE", q)
            self.assertNotIn(f"{C.HARNESS_KEY_MIXED} = 0", q)
        db.close()


class HarnessStoreBase(RegistryResetTestCase):
    """The fixture session, plus hand-written sessions covering every
    group the compare reports."""

    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        # The fixture carries a cli_version (2.1.0) and nothing else.
        self.db.execute(
            "UPDATE copilot_session SET cct_sha = ?, instructions_digest = ?, harness_mixed = 0",
            (SHA_A, DIG_1),
        )
        self._add("s-b", SHA_B, DIG_2, mixed=0, turns=10, tools=4, errors=2)
        self._add("s-b2", SHA_B, DIG_2, mixed=0, turns=30, tools=6, errors=0)
        self._add("s-mixed", SHA_A, DIG_1, mixed=1, turns=20, tools=1, errors=1)
        self._add("s-absent", None, DIG_1, mixed=0, turns=40, tools=2, errors=0, cli="2.9.9")
        self._add("s-unstamped", None, None, mixed=None, turns=50, tools=3, errors=5, cli=None)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def _add(self, sid, sha, digest, *, mixed, turns, tools, errors, cli="2.1.0"):
        self.db.execute(
            "INSERT INTO copilot_session (copilot, session_id, project_path, model, "
            " developer_id, turn_count, tool_call_count, error_count, started_at, "
            " cli_version, cct_sha, instructions_digest, harness_mixed) "
            "VALUES ('claude-code', ?, '/p', 'm', 'local', ?, ?, ?, '2026-05-30T10:00:00Z', ?, ?, ?, ?)",
            (sid, turns, tools, errors, cli, sha, digest, mixed),
        )

    def _rows(self, by):
        # Keyed by the dimension value, or by the kind for a named group
        # (a group carries no value — a real value may spell its name).
        return {
            (r["value"] if not r["is_group"] else r["kind"]): r
            for r in dashboard.harness_aggregates(self.db, by=by)["rows"]
        }


class TestAggregate(HarnessStoreBase):
    def test_grouping_names_every_kind_of_row(self) -> None:
        agg = dashboard.harness_aggregates(self.db, by="cct_sha")
        rows = self._rows("cct_sha")
        self.assertEqual(
            set(rows),
            {SHA_A, SHA_B, C.HARNESS_GROUP_MIXED, C.HARNESS_GROUP_ABSENT, C.HARNESS_GROUP_UNSTAMPED},
        )
        self.assertEqual(rows[SHA_A]["sessions"], 1)        # the fixture only; mixed is separate
        self.assertEqual(rows[SHA_B]["sessions"], 2)
        self.assertEqual(agg["comparable_values"], 2)
        self.assertFalse(agg["single_group"])
        # Named groups last, values ordered, never by size.
        self.assertEqual([r["is_group"] for r in agg["rows"]], [False, False, True, True, True])
        self.assertEqual([r["value"] for r in agg["rows"][:2]], sorted([SHA_A, SHA_B]))
        self.assertEqual([r["kind"] for r in agg["rows"][:2]], ["value", "value"])

    def test_a_mixed_session_is_counted_under_neither_version(self) -> None:
        rows = self._rows("cct_sha")
        self.assertEqual(rows[C.HARNESS_GROUP_MIXED]["sessions"], 1)
        self.assertNotIn("s-mixed", [SHA_A, SHA_B])
        # its turns are in the mixed row, not in SHA_A's
        self.assertEqual(rows[C.HARNESS_GROUP_MIXED]["turns"], 20)

    def test_absent_is_not_unstamped(self) -> None:
        rows = self._rows("cct_sha")
        self.assertEqual(rows[C.HARNESS_GROUP_ABSENT]["sessions"], 1)     # stamped by cli only
        self.assertEqual(rows[C.HARNESS_GROUP_UNSTAMPED]["sessions"], 1)  # no fact at all
        # Grouped by the dimension it DOES carry, it is an ordinary value.
        by_cli = self._rows("cli_version")
        self.assertIn("2.9.9", by_cli)
        self.assertFalse(by_cli["2.9.9"]["is_group"])

    def test_medians_and_error_rate(self) -> None:
        rows = self._rows("cct_sha")
        # Nearest rank, the package's one percentile rule: for an even
        # sample the median is the lower of the two middle values, not an
        # interpolated figure no session had.
        self.assertEqual(rows[SHA_B]["median_turns"], 10.0)
        self.assertEqual(rows[SHA_B]["median_tool_calls"], 4.0)
        self.assertEqual(rows[SHA_B]["turns"], 40)
        self.assertAlmostEqual(rows[SHA_B]["errors_per_100_turns"], 5.0)
        # A row with no turns cannot have a rate; it is None, not 0.
        self._add("s-empty", SHA_B, DIG_2, mixed=0, turns=0, tools=0, errors=0)
        self.db.execute("DELETE FROM copilot_session WHERE session_id IN ('s-b','s-b2')")
        self.db.commit()
        self.assertIsNone(self._rows("cct_sha")[SHA_B]["errors_per_100_turns"])

    def test_judge_figures_are_null_without_labels_and_real_with_them(self) -> None:
        rows = self._rows("cct_sha")
        for key in ("avg_interaction_quality", "rework_rate", "correction_rate"):
            self.assertIsNone(rows[SHA_B][key], key)
        self.assertEqual(rows[SHA_B]["sessions_judged"], 0)
        # Two judged sessions under the PACKAGED rubric's own name.
        ids = [
            int(r[0]) for r in self.db.query(
                "SELECT id FROM copilot_session WHERE session_id IN ('s-b','s-b2') ORDER BY session_id"
            )
        ]
        for sid, quality, rework in zip(ids, (4.0, 5.0), (0.2, 0.4)):
            self.db.execute(
                "INSERT INTO session_kpi (session_id, rubric_name, labeled_turn_count, "
                " rework_rate, correction_rate, avg_interaction_quality) VALUES (?, ?, 5, ?, 0.1, ?)",
                (sid, load_rubric().name, rework, quality),
            )
        # A row under a DIFFERENT rubric must not count.
        self.db.execute(
            "INSERT INTO session_kpi (session_id, rubric_name, labeled_turn_count, "
            " avg_interaction_quality) VALUES (?, 'some-other-rubric', 9, 1.0)",
            (ids[0],),
        )
        self.db.commit()
        row = self._rows("cct_sha")[SHA_B]
        self.assertEqual(row["sessions_judged"], 2)
        self.assertEqual(row["labeled_turns"], 10)
        self.assertAlmostEqual(row["avg_interaction_quality"], 4.5)
        self.assertAlmostEqual(row["rework_rate"], 0.3)

    def test_rates_are_weighted_by_labelled_turns_quality_is_not(self) -> None:
        """A rate is over the turns it was measured on: 1 rework turn
        beside 99 clean ones is 0.01, not 0.50 (A4b review P1). Quality
        stays the mean of per-session means, as specified."""
        ids = [
            int(r[0]) for r in self.db.query(
                "SELECT id FROM copilot_session WHERE session_id IN ('s-b','s-b2') ORDER BY session_id"
            )
        ]
        for sid, turns, rework, quality in ((ids[0], 1, 1.0, 5.0), (ids[1], 99, 0.0, 1.0)):
            self.db.execute(
                "INSERT INTO session_kpi (session_id, rubric_name, labeled_turn_count, "
                " rework_rate, correction_rate, avg_interaction_quality) VALUES (?, ?, ?, ?, ?, ?)",
                (sid, load_rubric().name, turns, rework, rework, quality),
            )
        self.db.commit()
        row = self._rows("cct_sha")[SHA_B]
        self.assertAlmostEqual(row["rework_rate"], 0.01)
        self.assertAlmostEqual(row["correction_rate"], 0.01)
        self.assertEqual(row["labeled_turns"], 100)
        # Quality is per session, so the small session counts as much.
        self.assertAlmostEqual(row["avg_interaction_quality"], 3.0)

    def test_a_session_with_labels_but_zero_labeled_turns_is_not_judged(self) -> None:
        sid = int(self.db.query_one("SELECT id FROM copilot_session WHERE session_id='s-b'")[0])
        self.db.execute(
            "INSERT INTO session_kpi (session_id, rubric_name, labeled_turn_count, "
            " avg_interaction_quality) VALUES (?, ?, 0, 3.0)",
            (sid, load_rubric().name),
        )
        self.db.commit()
        row = self._rows("cct_sha")[SHA_B]
        self.assertEqual(row["sessions_judged"], 0)
        self.assertIsNone(row["avg_interaction_quality"])

    def test_unknown_dimension_is_refused(self) -> None:
        for bad in ("project_path", "developer_id", "", "harness_mixed"):
            with self.assertRaises(ValueError, msg=bad):
                dashboard.harness_aggregates(self.db, by=bad)

    def test_single_group_is_named(self) -> None:
        self.db.execute("DELETE FROM copilot_session WHERE session_id IN ('s-b','s-b2')")
        self.db.commit()
        agg = dashboard.harness_aggregates(self.db, by="cct_sha")
        self.assertTrue(agg["single_group"])
        self.assertEqual(agg["comparable_values"], 1)


    def test_the_median_is_the_package_s_one_percentile_rule(self) -> None:
        from session_analytics.predict import _percentile

        for sample in ([1.0], [1.0, 9.0], [1.0, 5.0, 9.0], [1.0, 2.0, 3.0, 4.0]):
            self.assertEqual(dashboard._median(sample), _percentile(sample, 0.5), sample)
        self.assertIsNone(dashboard._median([]))


class TestFilterAndFacets(HarnessStoreBase):
    def _ids(self, **kw):
        return sorted(r["session_id"] for r in tools.search_sessions(self.db, limit=50, **kw))

    def test_every_group_selects_exactly_its_sessions(self) -> None:
        self.assertEqual(self._ids(harness=C.HARNESS_GROUP_MIXED), ["s-mixed"])
        self.assertEqual(self._ids(harness=C.HARNESS_GROUP_UNSTAMPED), ["s-unstamped"])
        self.assertEqual(self._ids(harness=f"{C.HARNESS_GROUP_ABSENT}:cct_sha"), ["s-absent"])
        self.assertEqual(self._ids(harness=f"cct_sha:{SHA_B}"), ["s-b", "s-b2"])
        # The mixed session carries SHA_A but is not returned under it.
        self.assertNotIn("s-mixed", self._ids(harness=f"cct_sha:{SHA_A}"))

    def test_the_facets_offer_only_values_the_filter_can_return(self) -> None:
        facets = tools.session_facets(self.db)
        self.assertEqual(set(facets["harness"]), set(C.HARNESS_DIMENSIONS))
        for dimension, values in facets["harness"].items():
            for value in values:
                self.assertTrue(
                    self._ids(harness=f"{dimension}:{value}"),
                    f"{dimension}:{value} is offered but returns nothing",
                )
        # SHA_A is carried by the fixture (unmixed) and by s-mixed; it is
        # offered because an unmixed session has it.
        self.assertIn(SHA_A, facets["harness"]["cct_sha"])

    def test_a_value_only_a_mixed_session_carries_is_not_offered(self) -> None:
        self._add("s-only-mixed", "c" * 40, DIG_1, mixed=1, turns=5, tools=0, errors=0)
        self.db.commit()
        facets = tools.session_facets(self.db)
        self.assertNotIn("c" * 40, facets["harness"]["cct_sha"])
        self.assertEqual(self._ids(harness=f"cct_sha:{'c' * 40}"), [])


if __name__ == "__main__":
    unittest.main()
