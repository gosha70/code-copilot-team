"""#457: no canary a redaction mode removes reaches the embedding provider."""

from __future__ import annotations

import unittest

from session_analytics.tests import canary as K
from session_analytics.tests.support import RegistryResetTestCase


class EmbeddingCanaries(K.FamilyCases, RegistryResetTestCase):
    capture = staticmethod(K.capture_embedding)
    reaches = {"embedding": {"user_prose", "user_fence", "assistant_fence", "preview_straddle"}}


if __name__ == "__main__":
    unittest.main()
