# Tests for session_analytics.search_index (E10 Slice B, #65): tokenized,
# ranked trace search.
#
# The corpus here is SYNTHETIC on purpose. The gate that opened this slice
# was measured over a real 62k-turn archive, which is evidence but not a
# test — it lives on one machine and cannot be asserted in CI. Each
# document below reproduces one measured failure of the Slice A substring
# search in a form that runs anywhere.
#
# Two of these tests are privacy tests, not search tests: an index is a
# second view of archived trace text, so a policy purge must reach it and
# it must never hold a copy of its own.

from __future__ import annotations

import unittest

from session_analytics import archive as arch
from session_analytics import constants as C
from session_analytics import search_index as si
from session_analytics.relational.db import Database, apply_ddl

from session_analytics.tests.support import RegistryResetTestCase

# Documents chosen so that every assertion below fails under `LIKE '%q%'`.
_DOCS = (
    # Terms present, separated — the measured `cluster threshold` = 0 case.
    "raising the cluster size above the configured threshold value",
    # Reverse order, adjacent — proves order-independence, not adjacency.
    "the threshold cluster boundary was recomputed",
    # Stemming: `archiving` must reach a document that says `archive`.
    "we archive every opted-in trace document per turn",
    # A ranking control: two terms, so it outranks a one-term match.
    "cluster and threshold both appear here and cluster again",
    # Contains none of the query terms — must never be returned.
    "completely unrelated prose about breakfast",
)


class TestQueryTerms(unittest.TestCase):
    def test_operators_and_punctuation_are_not_syntax(self) -> None:
        # Free-typed text must never reach FTS5 MATCH or tsquery as
        # syntax; these are the inputs that would otherwise be operators.
        self.assertEqual(si.query_terms("cluster threshold"), ["cluster", "threshold"])
        self.assertEqual(si.query_terms("a OR b"), ["a", "OR", "b"])
        self.assertEqual(si.query_terms("%"), [])
        self.assertEqual(si.query_terms("***"), [])
        self.assertEqual(
            si.query_terms('"quoted" -minus ^caret'), ["quoted", "minus", "caret"]
        )


class TestRankedSearch(RegistryResetTestCase):
    """Behaviours the substring search could not deliver, on a real store."""

    def setUp(self) -> None:
        super().setUp()
        self.dsn = self.sqlite_dsn()
        db = Database.connect(self.dsn)
        try:
            apply_ddl(db)
            self.session_ref = db.insert_returning_id(
                "INSERT INTO copilot_session (copilot, session_id, project_path) "
                "VALUES (?, ?, ?) RETURNING id",
                ("claude_code", "sess-search", "/repo/demo"),
            )
            self._insert_docs(db, _DOCS)
            db.commit()
        finally:
            db.close()

    def _insert_docs(self, db: Database, docs, *, start: int = 0) -> None:
        for i, text in enumerate(docs, start=start):
            db.execute(
                f"INSERT INTO {C.TBL_TRACE_DOCUMENT} "
                f"(session_ref, sequence_num, source_kind, content, "
                f" redaction_mode) VALUES (?, ?, ?, ?, ?)",
                (
                    self.session_ref,
                    i,
                    C.SOURCE_KIND_COPILOT_TRANSCRIPT,
                    text,
                    C.REDACT_CODE,
                ),
            )

    def _search(self, query: str, **kw) -> list[dict]:
        db = Database.connect(self.dsn)
        try:
            return arch.search_traces(db, query, **kw)
        finally:
            db.close()

    def _snippets(self, query: str, **kw) -> list[str]:
        return [r["snippet"] for r in self._search(query, **kw)]

    def _index_kind(self) -> str:
        db = Database.connect(self.dsn)
        try:
            return si.detect_index(db)
        finally:
            db.close()

    # ── the gate ───────────────────────────────────────────────────────

    def test_terms_match_across_intervening_words(self) -> None:
        # THE measured failure: `cluster threshold` = 0 hits while both
        # words were individually common. Four words separate them here.
        hits = self._search("cluster threshold")
        self.assertGreater(len(hits), 0)
        self.assertTrue(all("breakfast" not in h["snippet"] for h in hits))

    def test_word_order_is_not_significant(self) -> None:
        forward = {h["sequence_num"] for h in self._search("cluster threshold")}
        reverse = {h["sequence_num"] for h in self._search("threshold cluster")}
        self.assertEqual(forward, reverse)
        self.assertGreater(len(forward), 1)  # both documents, not just one

    def test_stemming_relates_inflections(self) -> None:
        # `archiving` reached exactly one document out of 187 `archive`
        # hits on the real corpus. Both spellings must find this one.
        self.assertGreater(len(self._search("archiving")), 0)
        self.assertEqual(
            {h["sequence_num"] for h in self._search("archiving")},
            {h["sequence_num"] for h in self._search("archive")},
        )

    def test_results_are_ranked_best_first(self) -> None:
        # The document mentioning both terms twice must outrank the
        # single mentions. Under Slice A the order was (session_ref,
        # sequence_num) and this document — inserted LAST — came last.
        hits = self._search("cluster threshold")
        self.assertGreater(len(hits), 1)
        self.assertIn("cluster again", hits[0]["snippet"])

    def test_limit_is_a_ranked_top_n(self) -> None:
        top = self._search("cluster threshold", limit=1)
        self.assertEqual(len(top), 1)
        best = self._search("cluster threshold")[0]
        self.assertEqual(top[0]["sequence_num"], best["sequence_num"])

    def test_non_matching_document_is_never_returned(self) -> None:
        for query in ("cluster threshold", "archiving", "cluster"):
            self.assertTrue(
                all("breakfast" not in s for s in self._snippets(query)),
                f"unrelated document surfaced for {query!r}",
            )

    def test_punctuation_only_query_matches_nothing(self) -> None:
        # Slice A escaped `%` to a literal. Slice B has no LIKE pattern to
        # escape, so the guard is that a query with no terms returns
        # nothing rather than falling through to a bare wildcard.
        self.assertEqual(self._search("%"), [])
        self.assertEqual(self._search("***"), [])

    def test_snippet_anchors_on_a_matching_term(self) -> None:
        # The whole query is not present verbatim anywhere, so the Slice A
        # snippet would have shown the head of the document.
        long_doc = ("filler " * 200) + "cluster and threshold together"
        db = Database.connect(self.dsn)
        try:
            self._insert_docs(db, (long_doc,), start=len(_DOCS))
            db.commit()
        finally:
            db.close()
        hit = next(
            h for h in self._search("cluster threshold")
            if h["sequence_num"] == len(_DOCS)
        )
        self.assertIn("cluster", hit["snippet"])
        self.assertNotEqual(hit["snippet"][:6], "filler")

    def test_search_runs_no_ddl(self) -> None:
        # Searching must not build, probe or alter anything. Building per
        # query would drop and recreate a probe table on sqlite and take
        # an ACCESS EXCLUSIVE lock on postgres for every read — and a
        # serving role without ALTER would fail, swallow it, and answer
        # from the substring path with a good index sitting right there.
        db = Database.connect(self.dsn)
        try:
            before = db.query("SELECT name, sql FROM sqlite_master ORDER BY name")
            self.assertGreater(len(arch.search_traces(db, "cluster threshold")), 0)
            after = db.query("SELECT name, sql FROM sqlite_master ORDER BY name")
        finally:
            db.close()
        self.assertEqual(before, after)

    def test_detect_does_not_create_the_index(self) -> None:
        db = Database.connect(self.dsn)
        try:
            db.execute(f"DROP TABLE IF EXISTS {C.TBL_TRACE_DOCUMENT_FTS}")
            db.commit()
            self.assertEqual(si.detect_index(db), C.SEARCH_INDEX_NONE)
            still_absent = db.query_one(
                "SELECT 1 FROM sqlite_master WHERE name = ?",
                (C.TBL_TRACE_DOCUMENT_FTS,),
            )
        finally:
            db.close()
        self.assertIsNone(still_absent)

    # ── privacy: the index is a second view of trace text ──────────────

    def test_policy_purge_removes_text_from_the_index(self) -> None:
        # archive.py deletes trace rows when a project stops authorising
        # archiving. An FTS5 external-content table does not follow that
        # delete on its own, and text that stayed searchable after its row
        # was purged would be a privacy regression, not stale data.
        self.assertGreater(len(self._search("breakfast")), 0)
        db = Database.connect(self.dsn)
        try:
            db.execute(
                f"DELETE FROM {C.TBL_TRACE_DOCUMENT} WHERE session_ref = ?",
                (self.session_ref,),
            )
            db.commit()
        finally:
            db.close()
        for query in ("breakfast", "cluster threshold", "archiving"):
            self.assertEqual(self._search(query), [], f"{query!r} survived the purge")

    def test_index_holds_no_second_copy_of_trace_text(self) -> None:
        if self._index_kind() != C.SEARCH_INDEX_FTS5:
            self.skipTest("no FTS5 in this sqlite build")
        db = Database.connect(self.dsn)
        try:
            row = db.query_one(
                "SELECT sql FROM sqlite_master WHERE name = ?",
                (C.TBL_TRACE_DOCUMENT_FTS,),
            )
        finally:
            db.close()
        self.assertIsNotNone(row)
        # external content: postings only, rows read back through the
        # base table. Without this clause the index duplicates the text.
        self.assertIn(f"content='{C.TBL_TRACE_DOCUMENT}'", row[0])

    # ── upgrade path ───────────────────────────────────────────────────

    def test_rows_archived_before_the_index_existed_are_searchable(self) -> None:
        # apply_ddl creates what is absent and runs NO migration, so a
        # store written under Slice A arrives with rows and no index.
        # Dropping the index reproduces exactly that state.
        db = Database.connect(self.dsn)
        try:
            db.execute(f"DROP TABLE IF EXISTS {C.TBL_TRACE_DOCUMENT_FTS}")
            for suffix in si.FTS_TRIGGER_SUFFIXES:
                db.execute(
                    f"DROP TRIGGER IF EXISTS {C.TBL_TRACE_DOCUMENT_FTS}_{suffix}"
                )
            db.commit()
        finally:
            db.close()
        # Searching alone must NOT rebuild it — search runs no DDL.
        self.assertEqual(self._search("cluster threshold"), [])
        # The upgrade path is the one every CLI command already takes:
        # open, apply_ddl, search. No re-archive, no rebuild command.
        db = Database.connect(self.dsn)
        try:
            apply_ddl(db)
        finally:
            db.close()
        self.assertGreater(len(self._search("cluster threshold")), 0)


class TestSubstringFallback(RegistryResetTestCase):
    """FTS5 is a compile-time sqlite option; its absence must not fail."""

    def test_search_still_answers_without_an_index(self) -> None:
        dsn = self.sqlite_dsn()
        db = Database.connect(dsn)
        try:
            apply_ddl(db)
            ref = db.insert_returning_id(
                "INSERT INTO copilot_session (copilot, session_id, project_path) "
                "VALUES (?, ?, ?) RETURNING id",
                ("claude_code", "sess-fallback", "/repo/demo"),
            )
            db.execute(
                f"INSERT INTO {C.TBL_TRACE_DOCUMENT} "
                f"(session_ref, sequence_num, source_kind, content, redaction_mode) "
                f"VALUES (?, ?, ?, ?, ?)",
                (ref, 0, C.SOURCE_KIND_COPILOT_TRANSCRIPT, "contiguous phrase here",
                 C.REDACT_CODE),
            )
            db.commit()

            # Force the no-index state and prove ranked_rows declines it
            # rather than raising — that decline is what routes the caller
            # back to the Slice A path.
            self.assertIsNone(
                si.ranked_rows(db, C.SEARCH_INDEX_NONE, ["contiguous"], 10)
            )
            db.execute(f"DROP TABLE IF EXISTS {C.TBL_TRACE_DOCUMENT_FTS}")
            for suffix in si.FTS_TRIGGER_SUFFIXES:
                db.execute(
                    f"DROP TRIGGER IF EXISTS {C.TBL_TRACE_DOCUMENT_FTS}_{suffix}"
                )
            db.commit()
            results = arch.search_traces(db, "contiguous phrase")
            self.assertGreater(len(results), 0)
        finally:
            db.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
