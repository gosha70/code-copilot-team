# Tests for judge validation (#313): named runs, N/A as NULL, the
# only-labelled-by selector, agreement + kappa, the human-label loop.

from __future__ import annotations

import io
import unittest

from session_analytics import constants as C
from session_analytics.adapters import claude_code
from session_analytics.ingest.pipeline import ingest
from session_analytics.judge import agreement as agr
from session_analytics.judge import human_labels as hl
from session_analytics.judge.contracts import PARSE_OK, Rubric, TurnContext, TurnLabels
from session_analytics.judge.label_sources import UnknownLabelSourceError, parse_label_source
from session_analytics.judge.parse import parse_labels
from session_analytics.judge.rubric import load_rubric
from session_analytics.judge.runner import run_judge
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase


class _Judge:
    """Labels from the text; `flip` inverts user_corrects_agent so two runs
    can disagree on purpose; `na` returns None for a user-only label on
    assistant turns."""

    judge_id = "fake"

    def __init__(self, flip: bool = False) -> None:
        self.flip = flip

    def rate_turn(self, ctx: TurnContext, rubric: Rubric) -> TurnLabels:
        bools = {label: False for label in rubric.bool_labels}
        corrects = "fix" in (ctx.text or "").lower()
        bools["user_corrects_agent"] = (not corrects) if self.flip else corrects
        bools["user_gives_command"] = ctx.role == C.ROLE_USER
        if ctx.role != C.ROLE_USER:
            bools["user_asks_question"] = None       # not applicable
        bools["response_helpful"] = True
        return TurnLabels(
            bool_labels=bools, sentiment="NEUTRAL", interaction_quality=4,
            parse_status=PARSE_OK, judge_id=self.judge_id, judge_model="fake-1",
        )

    def complete(self, prompt: str, *, timeout: int = 120) -> str:  # pragma: no cover
        raise NotImplementedError


class TestUnits(unittest.TestCase):
    def test_named_rubric_is_the_same_rubric_under_another_name(self) -> None:
        base, named = load_rubric(), load_rubric("heuristic-v1-rerun")
        self.assertEqual(named.name, "heuristic-v1-rerun")
        self.assertEqual(named.bool_labels, base.bool_labels)
        self.assertEqual(named.prompt_template, base.prompt_template)
        self.assertIs(load_rubric(base.name), base)

    def test_prompt_asks_for_null_not_false_when_not_applicable(self) -> None:
        self.assertIn("should be null", load_rubric().prompt_template)
        self.assertNotIn("should be false", load_rubric().prompt_template)
        # And the parser carries null through as None.
        labels = parse_labels(
            '{"user_corrects_agent": null, "user_gives_command": true}',
            load_rubric(), judge_id="x", judge_model="y",
        )
        self.assertIsNone(labels.bool_labels["user_corrects_agent"])
        self.assertTrue(labels.bool_labels["user_gives_command"])

    def test_label_source_parsing(self) -> None:
        self.assertEqual(parse_label_source("heuristic-v1").spec, "rubric:heuristic-v1")
        self.assertEqual(parse_label_source("human:gosha").table, C.TBL_HUMAN_LABEL)
        for bad in ("", "human:", "robot:x"):
            with self.assertRaises(UnknownLabelSourceError):
                parse_label_source(bad)

    def test_sample_is_balanced_by_role(self) -> None:
        import random
        by_role = {"assistant": [("a", i) for i in range(90)], "user": [("u", i) for i in range(10)]}
        drawn = hl._balanced_draw(random.Random(1), by_role, 50)
        roles = [r[0] for r in drawn]
        # 10 user turns exist → all 10 taken; the rest are assistant.
        self.assertEqual((roles.count("u"), roles.count("a"), len(drawn)), (10, 40, 50))
        even = hl._balanced_draw(random.Random(1), by_role, 20)
        self.assertEqual(([r[0] for r in even].count("u"), len(even)), (10, 20))

    def test_kappa_on_a_known_table(self) -> None:
        # 20 agree-true, 5 agree-false, 3 a-only, 2 b-only:
        # p_o = 25/30 = .8333; p_a = 23/30, p_b = 22/30 → p_e = .6244;
        # κ = (.8333 − .6244) / (1 − .6244) = .556
        pairs = [(True, True)] * 20 + [(False, False)] * 5 + [(True, False)] * 3 + [(False, True)] * 2
        self.assertAlmostEqual(agr.cohen_kappa(pairs), 0.556, places=3)
        self.assertIsNone(agr.cohen_kappa([]))
        self.assertIsNone(agr.cohen_kappa([(True, True)] * 5))   # both constant: chance = 1


class TestRunsAndAgreement(RegistryResetTestCase):
    def setUp(self) -> None:
        super().setUp()
        claude_code.register()
        self.dsn = self.sqlite_dsn()
        ingest(dsn=self.dsn, copilots=[C.COPILOT_CLAUDE_CODE], root=CLAUDE_CODE_ROOT, full=True)
        self.db = Database.connect(self.dsn)
        apply_ddl(self.db)

    def tearDown(self) -> None:
        self.db.close()
        super().tearDown()

    def _count(self, rubric_name: str) -> int:
        return int(self.db.query_one(
            "SELECT COUNT(*) FROM heuristic_label WHERE rubric_name = ?", (rubric_name,)
        )[0])

    def test_named_runs_coexist_and_overwrite_is_scoped(self) -> None:
        # The fixture has 6 turns, 4 with text: the judge is asked about
        # those 4 only — an empty tool-result turn has nothing to judge.
        first = run_judge(self.db, _Judge(), load_rubric())
        second = run_judge(self.db, _Judge(flip=True), load_rubric("rerun"), only_labelled_by="heuristic-v1")
        self.assertEqual((first.labeled, second.labeled), (4, 4))
        self.assertEqual((self._count("heuristic-v1"), self._count("rerun")), (4, 4))
        # N/A landed as NULL, not false.
        nulls = int(self.db.query_one(
            "SELECT COUNT(*) FROM heuristic_label WHERE user_asks_question IS NULL", ()
        )[0])
        self.assertGreater(nulls, 0)
        # Overwriting the rerun leaves the first run's rows untouched.
        before = self.db.query("SELECT turn_id, user_corrects_agent FROM heuristic_label WHERE rubric_name = ? ORDER BY turn_id", ("heuristic-v1",))
        run_judge(self.db, _Judge(), load_rubric("rerun"), overwrite=True)
        after = self.db.query("SELECT turn_id, user_corrects_agent FROM heuristic_label WHERE rubric_name = ? ORDER BY turn_id", ("heuristic-v1",))
        self.assertEqual(before, after)
        self.assertEqual(self._count("rerun"), 4)

    def test_agreement_between_two_runs(self) -> None:
        run_judge(self.db, _Judge(), load_rubric())
        run_judge(self.db, _Judge(flip=True), load_rubric("rerun"), only_labelled_by="heuristic-v1")
        rep = agr.agreement(self.db, "heuristic-v1", "rubric:rerun")
        self.assertEqual(rep["turns_shared"], 4)
        by = {l["label"]: l for l in rep["labels"]}
        # The flipped label disagrees on every pair; the rest agree fully.
        self.assertEqual(by["user_corrects_agent"]["agreement"], 0.0)
        self.assertEqual(by["user_gives_command"]["agreement"], 1.0)
        # N/A pairs are excluded from n: user_asks_question only counts user turns.
        user_turns = int(self.db.query_one(
            "SELECT COUNT(*) FROM copilot_turn WHERE role = ? AND content_preview <> ''", (C.ROLE_USER,)
        )[0])
        self.assertEqual(by["user_asks_question"]["n"], user_turns)
        self.assertFalse(by["user_gives_command"]["sufficient"])   # 6 < MIN_PAIRS
        self.assertEqual(rep["sentiment"]["exact"], 1.0)
        self.assertEqual(rep["interaction_quality"]["within_1"], 1.0)
        runs = agr.label_runs(self.db)
        self.assertEqual([r["name"] for r in runs["rubrics"]], ["heuristic-v1", "rerun"])

    def test_sample_import_agreement_loop(self) -> None:
        run_judge(self.db, _Judge(), load_rubric())
        # Sample the judged turns; the CSV shows the same preview text the
        # judge saw and blank label columns.
        buf = io.StringIO()
        n = hl.write_sample(self.db, buf, n=50, seed=1, only_labelled_by="heuristic-v1")
        # Two fixture turns are tool results with no text: a person cannot
        # label what they cannot read, so the sample skips them.
        with_text = int(self.db.query_one(
            "SELECT COUNT(*) FROM copilot_turn WHERE content_preview IS NOT NULL AND content_preview <> ''"
        )[0])
        self.assertEqual(n, with_text)
        self.assertEqual(n, 4)
        lines = buf.getvalue().splitlines()
        header = lines[0].split(",")
        self.assertEqual(header[:2], ["session_ref", "sequence_num"])
        self.assertIn("text", header)
        self.assertIn("user_corrects_agent", header)
        # A person fills it in: agree with the judge except on one row,
        # leaves one row blank.
        import csv
        rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
        for i, row in enumerate(rows):
            if i == 0:
                continue                       # left blank → not imported
            row["user_gives_command"] = "yes" if row["role"] == C.ROLE_USER else "no"
            row["user_corrects_agent"] = "no" if i != 1 else "yes"
            row["sentiment"] = "neutral"
            row["interaction_quality"] = "5"
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
        result = hl.import_labels(self.db, io.StringIO(out.getvalue()), labeler="tester")
        self.assertEqual((result["written"], result["left_blank"]), (3, 1))
        rep = agr.agreement(self.db, "heuristic-v1", "human:tester")
        self.assertEqual(rep["turns_shared"], 3)
        by = {l["label"]: l for l in rep["labels"]}
        self.assertEqual(by["user_gives_command"]["agreement"], 1.0)
        self.assertEqual(rep["interaction_quality"]["within_1"], 1.0)   # 4 vs 5
        self.assertEqual(rep["interaction_quality"]["exact"], 0.0)
        # Re-importing overwrites, never duplicates.
        hl.import_labels(self.db, io.StringIO(out.getvalue()), labeler="tester")
        self.assertEqual(agr.label_runs(self.db)["humans"][0]["turns"], 3)
        # Clearing every answer on a row that was imported before WITHDRAWS
        # it: the old label must not keep counting toward agreement.
        cleared = list(csv.DictReader(io.StringIO(out.getvalue())))
        for c in cleared[1:]:
            for col in header[7:]:
                c[col] = ""
        out2 = io.StringIO()
        w2 = csv.DictWriter(out2, fieldnames=header)
        w2.writeheader()
        w2.writerows(cleared)
        result = hl.import_labels(self.db, io.StringIO(out2.getvalue()), labeler="tester")
        self.assertEqual((result["written"], result["withdrawn"], result["left_blank"]), (0, 3, 1))
        self.assertEqual(agr.label_runs(self.db)["humans"], [])
        self.assertEqual(agr.agreement(self.db, "heuristic-v1", "human:tester")["turns_shared"], 0)
        # Restore for the bad-cell check below.
        hl.import_labels(self.db, io.StringIO(out.getvalue()), labeler="tester")
        # Bad cells refuse loudly.
        bad = out.getvalue().replace(",yes,", ",maybe,", 1)
        with self.assertRaises(hl.HumanLabelImportError):
            hl.import_labels(self.db, io.StringIO(bad), labeler="tester")
