"""#457: no canary a redaction mode removes reaches an MCP client, through
any tool or resource of the real server."""

from __future__ import annotations

import unittest

from session_analytics.tests import canary as K
from session_analytics.tests.support import RegistryResetTestCase


@unittest.skipUnless(K.HAS_MCP, "mcp SDK not installed; MCP canaries skipped (covered in CI)")
class McpCanaries(K.FamilyCases, RegistryResetTestCase):
    capture = staticmethod(K.capture_mcp)
    reaches = {
        "mcp get_session_details": {"user_prose", "user_fence", "tool_input", "error_message", "preview_straddle"},
        "mcp history://recent-errors": {"error_message"},
    }


if __name__ == "__main__":
    unittest.main()
