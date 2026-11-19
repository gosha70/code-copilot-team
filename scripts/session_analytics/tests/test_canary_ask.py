"""#457: no canary a redaction mode removes reaches the Ask model, through
the store facts or any tool's result."""

from __future__ import annotations

import unittest

from session_analytics.tests import canary as K
from session_analytics.tests.support import RegistryResetTestCase


class AskCanaries(K.FamilyCases, RegistryResetTestCase):
    capture = staticmethod(K.capture_ask)
    reaches = {
        "ask search_text": {"user_prose", "user_fence", "assistant_fence", "preview_straddle"},
        "ask session_turns": {"assistant_prose", "assistant_fence"},
        "ask session_summary": {"error_message"},
    }


if __name__ == "__main__":
    unittest.main()
