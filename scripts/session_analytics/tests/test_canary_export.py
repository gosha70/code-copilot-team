"""#487: no canary a redaction mode removes reaches an export.

Export writes what the store holds, so these cases mirror the off-machine
families: under ``none`` the corpus reaches the turn previews and the
archived trace text (the positive control), and a store ingested under a
redacting mode exports no canary that mode removes. The floor for a project
opted out or tightened after ingest is in ``test_canary_floor``, which
captures export through ``capture_all``.
"""

from __future__ import annotations

import unittest

from session_analytics.tests import canary as K
from session_analytics.tests.support import RegistryResetTestCase

_TURN_TEXT = {"user_prose", "user_fence", "assistant_fence", "assistant_prose", "preview_straddle"}


class ExportCanaries(K.FamilyCases, RegistryResetTestCase):
    capture = staticmethod(K.capture_export)
    reaches = {"export turns": _TURN_TEXT, "export trace_documents": _TURN_TEXT}


if __name__ == "__main__":
    unittest.main()
