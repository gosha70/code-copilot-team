"""#457: no canary a redaction mode removes reaches the per-turn judge or
session analysis (transcript, steering excerpts, facts and harness stamp)."""

from __future__ import annotations

import unittest

from session_analytics.tests import canary as K
from session_analytics.tests.support import RegistryResetTestCase


class JudgeCanaries(K.FamilyCases, RegistryResetTestCase):
    capture = staticmethod(K.capture_judge)
    reaches = {
        "per-turn judge": {"user_prose", "user_fence", "assistant_fence", "preview_straddle"},
        "session analysis": {
            "user_prose", "user_fence", "assistant_fence", "preview_straddle",
            "agents_prose", "agents_fence", "claude_fence", "steering_straddle",
        },
    }


if __name__ == "__main__":
    unittest.main()
