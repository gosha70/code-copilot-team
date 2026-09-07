# Tests for the session-level analysis (#65 Phase 1) — no real LLM.

from __future__ import annotations

import json

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics import archive as arch
from session_analytics.config import ProjectIdRule, ProjectOverride
from session_analytics.ingest.pipeline import ingest
from session_analytics.judge import session_analysis as sa
from session_analytics.judge.contracts import (
    PARSE_BACKEND_ERROR,
    PARSE_INNER_UNPARSEABLE,
    PARSE_OK,
    JudgeAnswerTruncated,
    JudgeTransportError,
)
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase

_OPTED_IN = {"demo-project": ProjectOverride(trace_archive=True)}
_RULES = (ProjectIdRule(match="/repo/demo", id="demo-project"),)


class _CannedJudge:
    """Returns whatever text it was built with; records the prompt."""

    judge_id = "fake"
    _model = "fake-1"

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def rate_turn(self, ctx, rubric):  # pragma: no cover — protocol only
        raise NotImplementedError

    def complete(self, prompt: str, *, timeout: int = 120) -> str:
        self.prompts.append(prompt)
        return self.text


class _DownJudge(_CannedJudge):
    def complete(self, prompt: str, *, timeout: int = 120) -> str:
        raise JudgeTransportError("connection refused")


class _CutOffJudge(_CannedJudge):
    def complete(self, prompt: str, *, timeout: int = 120) -> str:
        raise JudgeAnswerTruncated(
            "fake hit its answer cap", partial='{"summary": "the start of a long',
        )


_TUNING_OK = json.dumps({
    "summary": "Mostly fine.",
    "findings": [
        {"category": "Hooks", "severity": "HIGH", "title": "No test hook",
         "evidence_turns": [1, 2, 999], "explanation": "e", "recommendation": "r",
         "config_change": {"file": ".claude/settings.json", "diff": "+hook"}},
        {"category": "made-up", "severity": "high", "title": "dropped", "evidence_turns": []},
    ],
})


class TestSessionAnalysis(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        apply_ddl(self.db)
        self.session_id = int(self.db.query_one("SELECT id FROM copilot_session")[0])

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def _archive(self) -> None:
        arch.archive(
            dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT,
            projects=_OPTED_IN, project_id_rules=_RULES, full=True,
        )

    def test_transcript_from_previews_then_archive(self) -> None:
        t = sa.build_transcript(self.db, self.session_id, max_chars=60000, per_turn_cap=1500)
        self.assertEqual(t.source, C.TRANSCRIPT_SOURCE_PREVIEW)
        self.assertEqual(t.archived_turns, 0)
        self.assertGreater(len(t.turns), 0)
        self.assertFalse(t.truncated)
        self._archive()
        t2 = sa.build_transcript(self.db, self.session_id, max_chars=60000, per_turn_cap=1500)
        self.assertEqual(t2.source, C.TRANSCRIPT_SOURCE_ARCHIVE)
        self.assertEqual(t2.archived_turns, len(t2.turns))
        rendered = sa.render_transcript(t2.turns)
        self.assertIn(f"#{t2.turns[0].sequence_num} {t2.turns[0].role}", rendered)

    def test_transcript_truncates_middle_and_says_so(self) -> None:
        t = sa.build_transcript(self.db, self.session_id, max_chars=200, per_turn_cap=1500)
        self.assertTrue(t.truncated)
        # The cap is the judge's context: it holds exactly, and the text
        # handed over IS the rendering that was measured.
        self.assertLessEqual(t.chars, 200)
        self.assertEqual(t.chars, len(t.text))
        self.assertTrue(any(t_.role == "system" and "omitted" in t_.text for t_ in t.turns)
                        or "truncated" in t.text)
        # Facts stay session-wide: every turn is still known, and the
        # judge's view is a subset of them plus the marker.
        kept = {x.sequence_num for x in t.turns if x.role != "system"}
        self.assertLess(len(kept), len(t.all_turns))
        self.assertTrue(kept <= {x.sequence_num for x in t.all_turns})

    def test_transcript_cap_holds_for_tiny_sessions(self) -> None:
        # One or two turns cannot be elided (nothing in the middle), so the
        # cap must cut the text itself rather than be bypassed.
        gone = "SELECT id FROM copilot_turn WHERE session_id = ? AND sequence_num > 1"
        self.db.execute(
            "DELETE FROM copilot_tool_result WHERE tool_call_id IN "
            f"(SELECT id FROM copilot_tool_call WHERE turn_id IN ({gone}))",
            (self.session_id,),
        )
        for dependent in ("copilot_file_access", "copilot_error", "heuristic_label",
                          "copilot_tool_call"):
            self.db.execute(
                f"DELETE FROM {dependent} WHERE turn_id IN ({gone})", (self.session_id,)
            )
        self.db.execute(
            "DELETE FROM copilot_turn WHERE session_id = ? AND sequence_num > 1",
            (self.session_id,),
        )
        self.db.execute(
            "UPDATE copilot_turn SET content_preview = ? WHERE session_id = ?",
            ("x" * 100, self.session_id),
        )
        self.db.commit()
        t = sa.build_transcript(self.db, self.session_id, max_chars=50, per_turn_cap=1500)
        self.assertEqual(len(t.turns), 2)
        self.assertTrue(t.truncated)
        self.assertLessEqual(len(t.text), 50)
        self.assertIn("truncated", t.text)

    def test_facts_and_latency_are_session_wide_and_adjacency_safe(self) -> None:
        seqs = [
            r[0] for r in self.db.query(
                "SELECT sequence_num FROM copilot_turn WHERE session_id = ? ORDER BY sequence_num",
                (self.session_id,),
            )
        ]
        # 00:00, NULL, 00:02, then the clock goes BACK: no gap may be
        # derived across the gap or from the backwards step.
        stamps = ["2026-01-01T00:00:00+00:00", None, "2026-01-01T00:02:00+00:00",
                  "2026-01-01T00:01:00+00:00"]
        for seq, ts in zip(seqs, stamps):
            self.db.execute(
                "UPDATE copilot_turn SET timestamp = ? WHERE session_id = ? AND sequence_num = ?",
                (ts, self.session_id, seq),
            )
        self.db.commit()
        t = sa.build_transcript(self.db, self.session_id, max_chars=60000, per_turn_cap=1500)
        self.assertEqual([x.latency_seconds for x in t.turns[:4]], [None, None, None, None])
        # Facts come from ALL turns even when the judge sees an elided few.
        small = sa.build_transcript(self.db, self.session_id, max_chars=200, per_turn_cap=1500)
        facts = sa.session_facts(self.db, self.session_id, small)
        full_tools = {name for x in small.all_turns for name in x.tools}
        for name in full_tools:
            self.assertIn(name, facts)

    def test_analysis_persists_coerces_and_reuses(self) -> None:
        judge = _CannedJudge(_TUNING_OK)
        row = sa.analyze_session(self.db, self.session_id, C.ANALYSIS_KIND_TUNING, judge=judge)
        self.assertEqual(row["parse_status"], PARSE_OK)
        self.assertEqual(row["judge_id"], "fake")
        self.assertEqual(row["judge_model"], "fake-1")
        self.assertEqual(row["prompt_version"], sa.load_spec().version)
        self.assertEqual(row["transcript_source"], C.TRANSCRIPT_SOURCE_PREVIEW)
        findings = row["result"]["findings"]
        self.assertEqual(len(findings), 1)                      # unknown category dropped
        self.assertEqual(findings[0]["category"], "hooks")      # normalised
        self.assertEqual(findings[0]["severity"], "high")
        self.assertEqual(findings[0]["evidence_turns"], [1, 2])  # 999 does not exist
        self.assertEqual(row["result"]["dropped_items"], 1)      # and the page can say so
        # The prompt carried the facts and the transcript.
        self.assertIn("copilot: claude-code", judge.prompts[0])
        self.assertIn("#1 ", judge.prompts[0])
        # Second call without force reuses the stored row: no new prompt.
        sa.analyze_session(self.db, self.session_id, C.ANALYSIS_KIND_TUNING, judge=judge)
        self.assertEqual(len(judge.prompts), 1)
        sa.analyze_session(self.db, self.session_id, C.ANALYSIS_KIND_TUNING, judge=judge, force=True)
        self.assertEqual(len(judge.prompts), 2)
        n = self.db.query_one(f"SELECT COUNT(*) FROM {C.TBL_SESSION_ANALYSIS}")[0]
        self.assertEqual(n, 1)

    def test_items_are_normalised_to_the_page_contract(self) -> None:
        # Valid enums but no evidence_turns / explanation / config_change:
        # the page dereferences every one of those, so each is present in
        # its promised type. A finding with no title is dropped and counted.
        text = json.dumps({
            "summary": "s",
            "findings": [
                {"category": "hooks", "severity": "low", "title": "bare"},
                {"category": "hooks", "severity": "low", "title": "odd shapes",
                 "evidence_turns": "1,2", "config_change": {"file": "CLAUDE.md"},
                 "explanation": None},
                {"category": "hooks", "severity": "low"},
            ],
        })
        row = sa.analyze_session(
            self.db, self.session_id, C.ANALYSIS_KIND_TUNING, judge=_CannedJudge(text),
        )
        self.assertEqual(row["parse_status"], PARSE_OK)
        findings = row["result"]["findings"]
        self.assertEqual([f["title"] for f in findings], ["bare", "odd shapes"])
        for f in findings:
            self.assertEqual(f["evidence_turns"], [])
            self.assertIsInstance(f["explanation"], str)
            self.assertIsInstance(f["recommendation"], str)
            self.assertIsNone(f["config_change"])
        self.assertEqual(row["result"]["dropped_items"], 1)

        text = json.dumps({
            "summary": "s",
            "inefficiencies": [
                {"title": "loop", "lever": "hook", "wasted_turns": "3", "starter": "x"},
            ],
        })
        row = sa.analyze_session(
            self.db, self.session_id, C.ANALYSIS_KIND_EFFICIENCY,
            judge=_CannedJudge(text), force=True,
        )
        item = row["result"]["inefficiencies"][0]
        self.assertEqual(item["lever"], "HOOK")
        self.assertEqual(item["evidence_turns"], [])
        self.assertIsNone(item["wasted_turns"])
        self.assertIsNone(item["wasted_seconds"])
        self.assertIsNone(item["starter"])

    def test_coaching_drops_empty_rows_and_repeats(self) -> None:
        # Seen from a 3B model: eight rows quoting the same turn, most with
        # no issue named. One row per quoted prompt, and only rows that
        # actually coach.
        text = json.dumps({
            "summary": "s", "overall_score": 3,
            "prompts": [
                {"turn": 1, "original": "do it", "issue": "vague", "improved": "do X in Y"},
                {"turn": 1, "original": "do it", "issue": "vague again", "improved": "do X"},
                {"turn": 2, "original": "fix", "issue": "", "improved": "fix Z"},
                {"turn": 2, "original": "fix", "issue": "no target", "improved": ""},
                {"turn": 3, "original": "ok", "issue": "terse", "improved": "confirm and go"},
            ],
            "patterns": ["", "terse follow-ups"],
        })
        row = sa.analyze_session(
            self.db, self.session_id, C.ANALYSIS_KIND_COACHING, judge=_CannedJudge(text),
        )
        self.assertEqual(row["parse_status"], PARSE_OK)
        prompts = row["result"]["prompts"]
        self.assertEqual([p["turn"] for p in prompts], [1, 3])
        self.assertEqual(prompts[0]["issue"], "vague")
        self.assertEqual(row["result"]["patterns"], ["terse follow-ups"])
        self.assertEqual(row["result"]["dropped_items"], 3)

    def test_parse_failure_is_stored_not_raised(self) -> None:
        row = sa.analyze_session(
            self.db, self.session_id, C.ANALYSIS_KIND_COACHING, judge=_CannedJudge("no json here"),
        )
        self.assertEqual(row["parse_status"], PARSE_INNER_UNPARSEABLE)
        self.assertIsNone(row["result"])
        self.assertIn("no json", row["error"])
        # A failed row is retried without force.
        judge = _CannedJudge(json.dumps({"summary": "s", "overall_score": 4, "prompts": []}))
        row2 = sa.analyze_session(self.db, self.session_id, C.ANALYSIS_KIND_COACHING, judge=judge)
        self.assertEqual(row2["parse_status"], PARSE_OK)
        self.assertEqual(row2["result"]["overall_score"], 4)

    def test_missing_keys_recorded(self) -> None:
        row = sa.analyze_session(
            self.db, self.session_id, C.ANALYSIS_KIND_EFFICIENCY,
            judge=_CannedJudge(json.dumps({"summary": "only"})),
        )
        self.assertEqual(row["parse_status"], C.ANALYSIS_PARSE_MISSING_KEYS)
        self.assertIn("inefficiencies", row["error"])

    def test_transport_error_raises_and_is_recorded(self) -> None:
        with self.assertRaises(JudgeTransportError):
            sa.analyze_session(
                self.db, self.session_id, C.ANALYSIS_KIND_TUNING, judge=_DownJudge(""),
            )
        row = sa.get_analysis(self.db, self.session_id, C.ANALYSIS_KIND_TUNING)
        self.assertEqual(row["parse_status"], PARSE_BACKEND_ERROR)

    def test_failed_rerun_keeps_the_earlier_result(self) -> None:
        # A parsed result exists; a forced re-run hits a down backend and
        # then an unparseable answer. Neither replaces the stored result;
        # each is reported in its own return, flagged kept_previous.
        sa.analyze_session(
            self.db, self.session_id, C.ANALYSIS_KIND_TUNING, judge=_CannedJudge(_TUNING_OK),
        )
        with self.assertRaises(JudgeTransportError):
            sa.analyze_session(
                self.db, self.session_id, C.ANALYSIS_KIND_TUNING,
                judge=_DownJudge(""), force=True,
            )
        row = sa.analyze_session(
            self.db, self.session_id, C.ANALYSIS_KIND_TUNING,
            judge=_CannedJudge("garbage"), force=True,
        )
        self.assertEqual(row["parse_status"], PARSE_INNER_UNPARSEABLE)
        self.assertTrue(row["kept_previous"])
        stored = sa.get_analysis(self.db, self.session_id, C.ANALYSIS_KIND_TUNING)
        self.assertEqual(stored["parse_status"], PARSE_OK)
        self.assertEqual(len(stored["result"]["findings"]), 1)

    def test_truncated_answer_is_stored_with_its_head(self) -> None:
        # The model answered but hit its output cap: a stored result with
        # the reason and the head of what came back — not a raise, not
        # "unparseable".
        row = sa.analyze_session(
            self.db, self.session_id, C.ANALYSIS_KIND_COACHING,
            judge=_CutOffJudge(""),
        )
        self.assertEqual(row["parse_status"], C.ANALYSIS_PARSE_ANSWER_TRUNCATED)
        self.assertIn("answer cap", row["error"])
        self.assertIn('{"summary": "the start', row["error"])

    def test_unknown_kind(self) -> None:
        with self.assertRaises(sa.UnknownAnalysisKindError):
            sa.analyze_session(self.db, self.session_id, "vibes", judge=_CannedJudge("{}"))

    def test_all_analyses_shape(self) -> None:
        d = sa.all_analyses(self.db, self.session_id)
        self.assertEqual(set(d), set(C.ANALYSIS_KINDS))
        self.assertTrue(all(v is None for v in d.values()))
