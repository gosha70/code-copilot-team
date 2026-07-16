# Tests for E5 cost tracking: pricing math, unknown-model NULL+count,
# per-turn model capture + session fallback, session rollup + cost-per-
# outcome, and pricing-table currency/version validation.

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.adapters.claude_code import ClaudeCodeAdapter
from session_analytics.api import dashboard
from session_analytics.config import ModelRate, PricingConfig, _load_pricing, load_config
from session_analytics.cost import UnpricedStats, compute_turn_cost
from session_analytics.ingest.pipeline import ingest
from session_analytics.mcp import tools as mcp_tools
from session_analytics.relational.db import Database

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


def _rate(**overrides) -> ModelRate:
    base = dict(currency="USD", effective_date="2026-05-01",
                input=10.0, output=20.0, cache_read=1.0, cache_write=2.0)
    base.update(overrides)
    return ModelRate(**base)


# ── pure pricing math (cost.compute_turn_cost) ─────────────────────────


class TestPricingMath(unittest.TestCase):
    def test_pricing_math_includes_all_token_types(self) -> None:
        pricing = PricingConfig(models={"m": _rate()})
        result = compute_turn_cost(
            pricing, "m",
            tokens_input=1_000_000, tokens_output=500_000,
            cache_read_tokens=2_000_000, cache_write_tokens=100_000,
        )
        expected = (
            1_000_000 * 10.0 + 500_000 * 20.0 + 2_000_000 * 1.0 + 100_000 * 2.0
        ) / 1_000_000
        self.assertAlmostEqual(result.cost_usd, expected)
        self.assertEqual(result.price_version, "2026-05-01")

    def test_null_token_fields_treated_as_zero(self) -> None:
        pricing = PricingConfig(models={"m": _rate()})
        result = compute_turn_cost(
            pricing, "m",
            tokens_input=100, tokens_output=None,
            cache_read_tokens=None, cache_write_tokens=None,
        )
        self.assertAlmostEqual(result.cost_usd, 100 * 10.0 / 1_000_000)

    def test_no_pricing_configured_stays_null(self) -> None:
        result = compute_turn_cost(
            None, "m", tokens_input=10, tokens_output=10,
            cache_read_tokens=0, cache_write_tokens=0,
        )
        self.assertIsNone(result.cost_usd)
        self.assertIsNone(result.price_version)

    def test_unknown_model_stays_null_and_is_counted(self) -> None:
        pricing = PricingConfig(models={"known-model": _rate()})
        unpriced = UnpricedStats()
        r1 = compute_turn_cost(
            pricing, "unknown-model", tokens_input=10, tokens_output=10,
            cache_read_tokens=0, cache_write_tokens=0, unpriced=unpriced,
        )
        r2 = compute_turn_cost(
            pricing, "unknown-model", tokens_input=5, tokens_output=5,
            cache_read_tokens=0, cache_write_tokens=0, unpriced=unpriced,
        )
        self.assertIsNone(r1.cost_usd)
        self.assertIsNone(r2.cost_usd)
        self.assertEqual(unpriced.counts, {"unknown-model": 2})
        self.assertEqual(unpriced.total_turns, 2)

    def test_no_model_is_null_but_not_counted_as_unpriced(self) -> None:
        # A turn with no model at all (e.g. a user turn) is not a "known
        # model missing a price" — it is simply not a pricing candidate.
        pricing = PricingConfig(models={"known-model": _rate()})
        unpriced = UnpricedStats()
        result = compute_turn_cost(
            pricing, None, tokens_input=10, tokens_output=0,
            cache_read_tokens=0, cache_write_tokens=0, unpriced=unpriced,
        )
        self.assertIsNone(result.cost_usd)
        self.assertEqual(unpriced.counts, {})


# ── config: pricing table load + currency/version validation ──────────


class TestPricingConfigValidation(unittest.TestCase):
    def test_no_pricing_block_returns_empty(self) -> None:
        self.assertEqual(_load_pricing({}).models, {})

    def test_single_currency_parses(self) -> None:
        data = {"pricing": {"models": {
            "m1": {"currency": "USD", "effective_date": "2026-01-01",
                   "input": 1.0, "output": 2.0, "cache_read": 0.1, "cache_write": 0.2},
        }}}
        pricing = _load_pricing(data)
        self.assertEqual(pricing.models["m1"].currency, "USD")
        self.assertEqual(pricing.models["m1"].effective_date, "2026-01-01")
        self.assertEqual(pricing.rate_for("m1").output, 2.0)
        self.assertIsNone(pricing.rate_for("missing"))

    def test_mixed_currency_rejected(self) -> None:
        data = {"pricing": {"models": {
            "m1": {"currency": "USD", "effective_date": "v",
                   "input": 1, "output": 1, "cache_read": 1, "cache_write": 1},
            "m2": {"currency": "EUR", "effective_date": "v",
                   "input": 1, "output": 1, "cache_read": 1, "cache_write": 1},
        }}}
        with self.assertRaises(ValueError):
            _load_pricing(data)

    def test_missing_currency_rejected(self) -> None:
        data = {"pricing": {"models": {
            "m1": {"effective_date": "v", "input": 1, "output": 1,
                   "cache_read": 1, "cache_write": 1},
        }}}
        with self.assertRaises(ValueError):
            _load_pricing(data)

    def test_missing_effective_date_rejected(self) -> None:
        # effective_date is the price version stamped per turn; a blank one
        # would break audit/reproducibility, so it must be rejected at load.
        data = {"pricing": {"models": {
            "m1": {"currency": "USD", "input": 1, "output": 1,
                   "cache_read": 1, "cache_write": 1},
        }}}
        with self.assertRaises(ValueError):
            _load_pricing(data)

    def test_missing_rate_value_rejected(self) -> None:
        # A missing rate key must NOT silently price that token type at 0
        # (which would understate cost with no error) — reject at load.
        data = {"pricing": {"models": {
            "m1": {"currency": "USD", "effective_date": "v",
                   "input": 1, "output": 1, "cache_read": 1},  # cache_write missing
        }}}
        with self.assertRaises(ValueError):
            _load_pricing(data)

    def test_non_numeric_rate_rejected(self) -> None:
        data = {"pricing": {"models": {
            "m1": {"currency": "USD", "effective_date": "v", "input": "free",
                   "output": 1, "cache_read": 1, "cache_write": 1},
        }}}
        with self.assertRaises(ValueError):
            _load_pricing(data)

    def test_packaged_defaults_have_a_starting_single_currency_rate_set(self) -> None:
        # The real defaults.json must load without raising, and must ship
        # the documented starting Claude rate set.
        cfg = load_config()
        for model in ("claude-opus-4-8", "claude-sonnet-4-8", "claude-haiku-4-8"):
            self.assertIn(model, cfg.pricing.models)
            self.assertEqual(cfg.pricing.models[model].currency, "USD")


# ── adapter: per-turn model capture with session fallback ─────────────


class TestPerTurnModelAttribution(RegistryResetTestCase):
    def test_model_captured_per_message_with_session_fallback(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-model-test-"))
        proj = tmp / "project-hash"
        proj.mkdir()
        jsonl = proj / "mix-session.jsonl"
        lines = [
            '{"type":"user","sessionId":"sess-mix-001","cwd":"/repo","parentUuid":null,'
            '"isSidechain":false,"uuid":"u1","timestamp":"2026-06-01T10:00:00.000Z",'
            '"message":{"role":"user","content":"hi"}}',
            '{"type":"assistant","sessionId":"sess-mix-001","parentUuid":"u1",'
            '"isSidechain":false,"uuid":"a1","timestamp":"2026-06-01T10:00:01.000Z",'
            '"message":{"role":"assistant","model":"claude-opus-4-8",'
            '"usage":{"input_tokens":10,"output_tokens":5},'
            '"content":[{"type":"text","text":"first"}]}}',
            '{"type":"assistant","sessionId":"sess-mix-001","parentUuid":"a1",'
            '"isSidechain":false,"uuid":"a2","timestamp":"2026-06-01T10:00:02.000Z",'
            '"message":{"role":"assistant",'
            '"usage":{"input_tokens":11,"output_tokens":6},'
            '"content":[{"type":"text","text":"no model on this message"}]}}',
            '{"type":"assistant","sessionId":"sess-mix-001","parentUuid":"a2",'
            '"isSidechain":false,"uuid":"a3","timestamp":"2026-06-01T10:00:03.000Z",'
            '"message":{"role":"assistant","model":"claude-sonnet-4-8",'
            '"usage":{"input_tokens":12,"output_tokens":7},'
            '"content":[{"type":"text","text":"switched model"}]}}',
        ]
        jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")

        adapter = ClaudeCodeAdapter()
        refs = adapter.discover(tmp)
        self.assertEqual(len(refs), 1)
        session = adapter.load(refs[0])

        # Session-level model: first non-empty model found (unchanged behavior).
        self.assertEqual(session.model, "claude-opus-4-8")

        assistant_turns = [t for t in session.turns if t.role == C.ROLE_ASSISTANT]
        self.assertEqual(len(assistant_turns), 3)
        self.assertEqual(assistant_turns[0].model, "claude-opus-4-8")
        # Message has no model of its own → falls back to the session model.
        self.assertEqual(assistant_turns[1].model, "claude-opus-4-8")
        # A later message with its OWN model wins over the fallback (handles
        # a mid-session /model switch — FR-2).
        self.assertEqual(assistant_turns[2].model, "claude-sonnet-4-8")

        # User turns never carry a model in Claude Code transcripts.
        user_turns = [t for t in session.turns if t.role == C.ROLE_USER]
        self.assertTrue(all(t.model is None for t in user_turns))


# ── ingest → store: cost computed at ingest, unpriced counted, regression ──


class TestNoPricingRegression(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def test_no_pricing_kwarg_leaves_cost_null(self) -> None:
        dsn = self.sqlite_dsn()
        ingest(dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        db = Database.connect(dsn)
        try:
            rows = db.query("SELECT cost_usd, cost_price_version FROM copilot_turn")
            self.assertTrue(rows)
            self.assertTrue(all(r[0] is None and r[1] is None for r in rows))
        finally:
            db.close()


class TestIngestUnpricedReporting(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()

    def test_unknown_model_counted_across_ingest(self) -> None:
        dsn = self.sqlite_dsn()
        # The fixture's turns are all "claude-opus-4-8"; price a DIFFERENT
        # model so every assistant turn is unpriced.
        pricing = PricingConfig(models={"some-other-model": _rate()})
        stats = ingest(
            dsn=dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            full=True, pricing=pricing,
        )
        self.assertEqual(stats.unpriced_models, {"claude-opus-4-8": 3})
        db = Database.connect(dsn)
        try:
            rows = db.query(
                "SELECT cost_usd FROM copilot_turn WHERE model = 'claude-opus-4-8'"
            )
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r[0] is None for r in rows))
        finally:
            db.close()


class TestCostRollups(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.pricing = PricingConfig(models={"claude-opus-4-8": _rate(
            input=15.0, output=75.0, cache_read=1.5, cache_write=18.75,
        )})
        self.dsn = self.sqlite_dsn()
        ingest(
            dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            full=True, pricing=self.pricing,
        )
        self.db = Database.connect(self.dsn)

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def test_assistant_turn_costs_computed_and_versioned(self) -> None:
        rows = self.db.query(
            "SELECT tokens_input, tokens_output, cache_read_tokens, "
            "cache_write_tokens, cost_usd, cost_price_version, model "
            "FROM copilot_turn WHERE role = 'assistant' ORDER BY sequence_num"
        )
        self.assertEqual(len(rows), 3)
        for tin, tout, cread, cwrite, cost, version, model in rows:
            expected = (
                (tin or 0) * 15.0 + (tout or 0) * 75.0
                + (cread or 0) * 1.5 + (cwrite or 0) * 18.75
            ) / 1_000_000
            self.assertAlmostEqual(cost, expected, places=8)
            self.assertEqual(version, "2026-05-01")
            self.assertEqual(model, "claude-opus-4-8")

        user_costs = self.db.query("SELECT cost_usd FROM copilot_turn WHERE role = 'user'")
        self.assertTrue(all(r[0] is None for r in user_costs))

    def test_session_rollup_equals_sum_of_turn_costs(self) -> None:
        total = self.db.query_one("SELECT SUM(cost_usd) FROM copilot_turn")[0]
        self.assertIsNotNone(total)

        sessions = mcp_tools.search_sessions(self.db)
        self.assertEqual(len(sessions), 1)
        self.assertAlmostEqual(sessions[0]["cost_usd"], total, places=8)

        detail = mcp_tools.get_session_details(self.db, sessions[0]["id"])
        self.assertAlmostEqual(detail["cost_usd"], total, places=8)

    def test_dashboard_total_cost_and_cost_per_session(self) -> None:
        total = self.db.query_one("SELECT SUM(cost_usd) FROM copilot_turn")[0]
        k = dashboard.kpis(self.db)
        self.assertAlmostEqual(k["totals"]["total_cost_usd"], total, places=8)
        # One session in the fixture → cost-per-session == total.
        self.assertAlmostEqual(k["totals"]["cost_per_session"], total, places=8)

    def test_cost_by_outcome_by_phase_and_heuristic_label(self) -> None:
        from session_analytics.judge.contracts import PARSE_OK, TurnLabels
        from session_analytics.judge.rubric import load_rubric
        from session_analytics.judge.runner import run_judge

        class _FakeJudge:
            judge_id = "fake"

            def rate_turn(self, ctx, rubric):
                bools = {label: False for label in rubric.bool_labels}
                return TurnLabels(
                    bool_labels=bools, sentiment="POSITIVE", interaction_quality=5,
                    parse_status=PARSE_OK, judge_id=self.judge_id, judge_model="fake-1",
                )

        rubric = load_rubric()
        run_judge(self.db, _FakeJudge(), rubric)

        total = self.db.query_one("SELECT SUM(cost_usd) FROM copilot_turn")[0]
        result = dashboard.cost_by_outcome(self.db)

        # The fixture never sets a session phase → the single "(none)" bucket
        # carries the whole session's cost.
        self.assertEqual(len(result["by_phase"]), 1)
        self.assertEqual(result["by_phase"][0]["phase"], "(none)")
        self.assertAlmostEqual(result["by_phase"][0]["cost_usd"], total, places=6)

        # Every turn (including the 3 uncosted user turns) got POSITIVE from
        # the fake judge; only the 3 priced assistant turns contribute cost.
        pos = next(
            r for r in result["by_sentiment"] if r["sentiment"] == "POSITIVE"
        )
        self.assertAlmostEqual(pos["cost_usd"], total, places=6)

    def test_cost_by_sentiment_dedupes_across_rubrics(self) -> None:
        # heuristic_label is UNIQUE(turn_id, rubric_name): a turn labeled under
        # a second rubric must NOT have its cost counted twice in by_sentiment.
        from session_analytics.judge.contracts import PARSE_OK, TurnLabels
        from session_analytics.judge.rubric import load_rubric
        from session_analytics.judge.runner import run_judge

        class _FakeJudge:
            judge_id = "fake"

            def rate_turn(self, ctx, rubric):
                bools = {label: False for label in rubric.bool_labels}
                return TurnLabels(
                    bool_labels=bools, sentiment="POSITIVE", interaction_quality=5,
                    parse_status=PARSE_OK, judge_id=self.judge_id, judge_model="fake-1",
                )

        run_judge(self.db, _FakeJudge(), load_rubric())
        total = self.db.query_one("SELECT SUM(cost_usd) FROM copilot_turn")[0]

        # Duplicate one priced turn's label under a SECOND rubric_name.
        tid = self.db.query_one(
            "SELECT id FROM copilot_turn WHERE cost_usd IS NOT NULL LIMIT 1"
        )[0]
        self.db.execute(
            "INSERT INTO heuristic_label (turn_id, rubric_name, sentiment) "
            "VALUES (?, ?, ?)",
            (tid, "second-rubric", "POSITIVE"),
        )
        self.db.commit()

        result = dashboard.cost_by_outcome(self.db)
        pos = next(r for r in result["by_sentiment"] if r["sentiment"] == "POSITIVE")
        # De-duped: still the single session total, NOT inflated by the 2nd label.
        self.assertAlmostEqual(pos["cost_usd"], total, places=6)

    def test_cost_per_session_divides_by_priced_sessions(self) -> None:
        # A session with no priced turns must not dilute cost_per_session:
        # the denominator is sessions-with-a-priced-turn, not all sessions.
        total = self.db.query_one("SELECT SUM(cost_usd) FROM copilot_turn")[0]
        sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count) "
            "VALUES (?, ?, ?) RETURNING id",
            ("claude-code", "unpriced-extra", 1),
        )
        self.db.execute(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, "
            "content_length) VALUES (?, ?, ?, ?)",
            (sid, 0, "assistant", 0),
        )
        self.db.commit()

        k = dashboard.kpis(self.db)
        self.assertEqual(k["totals"]["priced_sessions"], 1)
        self.assertAlmostEqual(k["totals"]["cost_per_session"], total, places=8)


if __name__ == "__main__":
    unittest.main()
