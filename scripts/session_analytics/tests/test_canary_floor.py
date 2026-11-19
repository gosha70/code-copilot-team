"""#457 FR-006: the current-mode floor, with no re-ingest.

The corpus is ingested under ``none`` and under ``code``. Then the
configuration changes:

* tightened to ``metadata-only`` (per project, and globally): no canary
  reaches any off-machine path;
* the project opted out (``ingest: "off"``): nothing from the session
  reaches any path, not a canary, a marker, its native id or its project.
"""

from __future__ import annotations

import unittest

from session_analytics import constants as C
from session_analytics.tests import canary as K
from session_analytics.tests.support import RegistryResetTestCase

M = C.REDACT_METADATA_ONLY


class TheFloorAppliesWithoutReingest(RegistryResetTestCase):
    def ingest_then(self, ingested: str, *, archive: bool = True, **changed) -> dict[str, str]:
        dsn = self.sqlite_dsn()
        with K.corpus() as (source, project):
            with K.user_config(K.config_for(project, project_mode=ingested, archive=archive)):
                sid = K.ingest_corpus(dsn, source)
            with K.user_config(K.config_for(project, archive=archive, **changed)):
                return K.capture_all(dsn, sid)

    # With and without the trace archive: paths such as Ask's search read
    # archived text when it exists and previews otherwise.
    CASES = [(i, a) for i in (C.REDACT_NONE, C.REDACT_CODE) for a in (True, False)]

    def test_a_project_tightened_after_ingest_sends_no_canary(self):
        for ingested, archive in self.CASES:
            with self.subTest(ingested=ingested, archive=archive):
                K.assert_no_leak(self, self.ingest_then(ingested, archive=archive, project_mode=M), M)

    def test_a_global_mode_tightened_after_ingest_sends_no_canary(self):
        for ingested, archive in self.CASES:
            with self.subTest(ingested=ingested, archive=archive):
                K.assert_no_leak(self, self.ingest_then(ingested, archive=archive, global_mode=M), M)

    def test_an_opted_out_project_sends_nothing_from_its_sessions(self):
        for ingested in (C.REDACT_NONE, C.REDACT_CODE):
            with self.subTest(ingested=ingested):
                captured = self.ingest_then(ingested, project_mode=ingested, ingest_off=True)
                named = {
                    path: [w for w in ("sess-canary-001", "canaryproj", *K.CANARIES.values()) if w in text]
                    for path, text in captured.items()
                }
                self.assertEqual({p: w for p, w in named.items() if w}, {})
                # The judges were not called at all: analysis is refused and
                # the per-turn judge selects none of its turns.
                self.assertEqual(captured["per-turn judge"], "")
                self.assertEqual(captured["session analysis"], "")
                self.assertEqual(captured["embedding"], "")


if __name__ == "__main__":
    unittest.main()
