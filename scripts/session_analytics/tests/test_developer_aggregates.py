# Tests for the E1 per-developer rollup (#65).
#
# The fixtures here are SYNTHETIC and have to be. E1 is a multi-tenant
# feature and every real corpus available is single-developer — the
# owner's 132-session store has exactly one developer_id — so a
# multi-developer store can only be constructed, never observed. That
# also makes the single-developer case worth asserting explicitly: it is
# what the feature actually renders on real data today.

from __future__ import annotations

from session_analytics import constants as C
from session_analytics.api import dashboard
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import RegistryResetTestCase


class TestDeveloperAggregates(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.dsn = self.sqlite_dsn()
        self.db = Database.connect(self.dsn)
        apply_ddl(self.db)

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def _session(
        self,
        developer_id: str,
        session_id: str,
        *,
        project: str = "/repo/demo",
        turns: int = 0,
        tools: int = 0,
        errors: int = 0,
        started_at: str = "2026-09-01T00:00:00Z",
    ) -> int:
        return self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, project_path, "
            " developer_id, turn_count, tool_call_count, error_count, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (
                C.COPILOT_CLAUDE_CODE, session_id, project, developer_id,
                turns, tools, errors, started_at,
            ),
        )

    def _turn(
        self,
        session_ref: int,
        seq: int,
        cost: float | None,
        *,
        role: str = "assistant",
        model: str | None = "claude-x",
        tokens: int | None = 100,
        cache_tokens: int | None = None,
    ) -> None:
        # `model` is what makes a turn a PRICING CANDIDATE — that is the
        # rule `cost.compute_turn_cost` applies ("no model → NULL"), and
        # it is independent of which token fields are populated. A user
        # turn has no model, which is why it can never be in a coverage
        # denominator; a cache-only assistant turn HAS one and is.
        self.db.execute(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, cost_usd,"
            " model, tokens_output, cache_read_tokens) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_ref, seq, role, cost, model, tokens, cache_tokens),
        )

    def _agg(self) -> dict:
        self.db.commit()
        return dashboard.developer_aggregates(self.db)

    # ── the single-developer reality ───────────────────────────────────

    def test_empty_store_reports_no_developers(self) -> None:
        report = self._agg()
        self.assertEqual(report["developers"], [])
        self.assertEqual(report["developer_count"], 0)
        # Zero developers is "not a team view" too — the flag must not be
        # false just because the list is empty rather than singular.
        self.assertTrue(report["is_single_developer"])

    def test_single_developer_is_flagged_not_hidden(self) -> None:
        # What every real store looks like today. The row is still
        # returned; the flag exists so the UI can explain the view.
        self._session("i-am-goga", "s1", turns=10)
        report = self._agg()
        self.assertEqual(report["developer_count"], 1)
        self.assertTrue(report["is_single_developer"])
        self.assertEqual(report["developers"][0]["developer_id"], "i-am-goga")

    def test_default_id_counts_as_unattributed(self) -> None:
        # A team that never configured developer_id reads as one person;
        # that is a configuration fact worth surfacing, not a team of one.
        self._session(C.DEFAULT_DEVELOPER_ID, "s1")
        self._session(C.DEFAULT_DEVELOPER_ID, "s2")
        self._session("alice", "s3")
        report = self._agg()
        self.assertEqual(report["unattributed_sessions"], 2)
        self.assertFalse(report["is_single_developer"])

    # ── the multi-developer case, which only exists synthetically ──────

    def test_totals_are_per_developer(self) -> None:
        self._session("alice", "a1", turns=10, tools=3, errors=1)
        self._session("alice", "a2", turns=5, tools=2, errors=0)
        self._session("bob", "b1", turns=7, tools=1, errors=4)
        by_id = {d["developer_id"]: d for d in self._agg()["developers"]}
        self.assertEqual(by_id["alice"]["sessions"], 2)
        self.assertEqual(by_id["alice"]["turns"], 15)
        self.assertEqual(by_id["alice"]["tool_calls"], 5)
        self.assertEqual(by_id["alice"]["errors"], 1)
        self.assertEqual(by_id["bob"]["sessions"], 1)
        self.assertEqual(by_id["bob"]["errors"], 4)

    def test_distinct_projects_not_session_count(self) -> None:
        self._session("alice", "a1", project="/repo/one")
        self._session("alice", "a2", project="/repo/one")
        self._session("alice", "a3", project="/repo/two")
        self.assertEqual(self._agg()["developers"][0]["projects"], 2)

    def test_first_and_last_seen_span_the_sessions(self) -> None:
        self._session("alice", "a1", started_at="2026-08-01T00:00:00Z")
        self._session("alice", "a2", started_at="2026-09-01T00:00:00Z")
        self._session("alice", "a3", started_at="2026-08-15T00:00:00Z")
        dev = self._agg()["developers"][0]
        self.assertEqual(dev["first_seen"], "2026-08-01T00:00:00Z")
        self.assertEqual(dev["last_seen"], "2026-09-01T00:00:00Z")

    def test_cost_is_summed_per_developer_without_inflating_sessions(self) -> None:
        # Cost lives on turns, so a naive join would multiply the
        # session-level SUMs by the turn count. Alice has 2 sessions and
        # 3 priced turns; both numbers must stay themselves.
        a1 = self._session("alice", "a1", turns=2)
        a2 = self._session("alice", "a2", turns=1)
        b1 = self._session("bob", "b1", turns=1)
        self._turn(a1, 0, 1.5)
        self._turn(a1, 1, 2.0)
        self._turn(a2, 0, 0.5)
        self._turn(b1, 0, 10.0)
        by_id = {d["developer_id"]: d for d in self._agg()["developers"]}
        self.assertAlmostEqual(by_id["alice"]["cost_usd"], 4.0)
        self.assertEqual(by_id["alice"]["priced_turns"], 3)
        self.assertEqual(by_id["alice"]["sessions"], 2)
        self.assertEqual(by_id["alice"]["turns"], 3)
        self.assertAlmostEqual(by_id["bob"]["cost_usd"], 10.0)

    def test_unpriced_turns_are_unknown_cost_not_zero_cost(self) -> None:
        # NULL cost_usd means "not priced", which is not the same claim
        # as "free". Reporting 0.00 for a developer nothing is known
        # about hands someone a number they could budget against, so the
        # unknown stays None and priced_turns exposes the denominator.
        a1 = self._session("alice", "a1", turns=2)
        self._turn(a1, 0, None)
        self._turn(a1, 1, 3.0)
        self._session("bob", "b1", turns=1)   # no turns priced at all
        c1 = self._session("carol", "c1", turns=1)
        self._turn(c1, 0, None)               # a turn, but unpriced
        by_id = {d["developer_id"]: d for d in self._agg()["developers"]}

        self.assertAlmostEqual(by_id["alice"]["cost_usd"], 3.0)
        self.assertEqual(by_id["alice"]["priced_turns"], 1)

        self.assertIsNone(by_id["bob"]["cost_usd"])
        self.assertEqual(by_id["bob"]["priced_turns"], 0)

        # The distinction that matters: carol HAS a turn, it just has no
        # price. That is still unknown, not free.
        self.assertIsNone(by_id["carol"]["cost_usd"])
        self.assertEqual(by_id["carol"]["priced_turns"], 0)

    def test_coverage_denominator_excludes_turns_that_cannot_be_priced(self) -> None:
        # A model-less turn is not a pricing candidate — that is the rule
        # cost.compute_turn_cost applies. Counting them would report a
        # fully priced developer as permanently partial. Alice's two
        # model-bearing turns are both priced: 2/2, not 2/4.
        a1 = self._session("alice", "a1", turns=4)
        self._turn(a1, 0, None, role="user", model=None, tokens=None)
        self._turn(a1, 1, 1.0)
        self._turn(a1, 2, None, role="user", model=None, tokens=None)
        self._turn(a1, 3, 2.0)
        dev = self._agg()["developers"][0]
        self.assertEqual(dev["priced_turns"], 2)
        self.assertEqual(dev["priceable_turns"], 2)
        self.assertEqual(dev["turns"], 4)   # the turn count is NOT the denominator

    def test_genuinely_unpriced_eligible_turns_show_partial_coverage(self) -> None:
        # A turn whose MODEL has no price entry is still a candidate and
        # stays in the denominator — real missing coverage, not hidden by
        # the exclusion above. The model is what makes it eligible, so it
        # must be set here or this test pins the wrong rule.
        a1 = self._session("alice", "a1", turns=2)
        self._turn(a1, 0, 1.0, model="claude-priced")
        self._turn(a1, 1, None, model="claude-unpriced")
        dev = self._agg()["developers"][0]
        self.assertEqual(dev["priced_turns"], 1)
        self.assertEqual(dev["priceable_turns"], 2)

    def test_eligibility_follows_the_model_not_the_token_fields(self) -> None:
        # The two ways a token-presence proxy diverges from the contract.
        # Both are zero rows on the corpus this was built against, which
        # is exactly why the proxy survived a review pass — so they are
        # pinned here rather than left to the next dataset to discover.
        # TWO cache-only turns against ONE model-less token turn, so the
        # two rules disagree on the COUNT and not merely on which rows
        # they pick. With one of each the totals coincide at 1 while the
        # membership is exactly inverted, and the assertion would pass
        # against the rule it exists to reject.
        a1 = self._session("alice", "a1", turns=3)
        # Priceable: has a model, and only CACHE tokens. cost.py prices
        # cache_read/cache_write, so excluding these would undercount the
        # denominator — and, once priced, drive priced > priceable.
        self._turn(a1, 0, 0.25, tokens=None, cache_tokens=500)
        self._turn(a1, 1, 0.25, tokens=None, cache_tokens=700)
        # NOT priceable: carries tokens but has no model, so it can never
        # be priced no matter how many tokens it reports.
        self._turn(a1, 2, None, model=None, tokens=900)
        dev = self._agg()["developers"][0]
        self.assertEqual(dev["priceable_turns"], 2)   # token proxy would say 1
        self.assertEqual(dev["priced_turns"], 2)

    def test_priced_never_exceeds_priceable(self) -> None:
        # The invariant the proxy could break: a priced cache-only turn
        # counted in the numerator but not the denominator would render
        # as "1 / 0".
        a1 = self._session("alice", "a1", turns=3)
        self._turn(a1, 0, 0.25, tokens=None, cache_tokens=500)
        self._turn(a1, 1, 1.0)
        self._turn(a1, 2, None, role="user", model=None, tokens=None)
        dev = self._agg()["developers"][0]
        self.assertLessEqual(dev["priced_turns"], dev["priceable_turns"])
        self.assertEqual((dev["priced_turns"], dev["priceable_turns"]), (2, 2))

    # ── ordering: stable, and deliberately not a leaderboard ───────────

    def test_ordering_is_alphabetical_not_by_volume(self) -> None:
        # Sessions and turns measure copilot usage, not how well anyone
        # works. Ordering by volume would read as a ranking of people, so
        # the busiest developer must NOT be pulled to the top.
        self._session("zoe", "z1", turns=100)
        self._session("zoe", "z2", turns=100)
        self._session("alice", "a1", turns=1)
        ids = [d["developer_id"] for d in self._agg()["developers"]]
        self.assertEqual(ids, ["alice", "zoe"])

    # ── the registry ───────────────────────────────────────────────────

    def test_display_name_comes_from_the_registry_when_set(self) -> None:
        self.db.execute(
            "INSERT INTO developer (developer_id, display_name) VALUES (?, ?)",
            ("alice", "Alice Example"),
        )
        self._session("alice", "a1")
        self._session("bob", "b1")
        by_id = {d["developer_id"]: d for d in self._agg()["developers"]}
        self.assertEqual(by_id["alice"]["display_name"], "Alice Example")
        # No registry row, no invented name.
        self.assertIsNone(by_id["bob"]["display_name"])

    def test_registered_developer_with_no_sessions_is_named_separately(self) -> None:
        # Such a developer must not appear as a zero row among the
        # active ones — "registered but never ingested" is a different
        # statement from "worked zero sessions this period".
        self.db.execute(
            "INSERT INTO developer (developer_id, display_name) VALUES (?, ?)",
            ("carol", "Carol Example"),
        )
        self._session("alice", "a1")
        report = self._agg()
        self.assertEqual(
            [d["developer_id"] for d in report["developers"]], ["alice"]
        )
        self.assertEqual(report["registered_without_sessions"], ["carol"])
