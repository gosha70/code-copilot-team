# Tests for the guided first-run setup (non-interactive path).

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from session_analytics import config as cfgmod
from session_analytics import setup_cmd


class TestSetup(unittest.TestCase):
    def test_non_interactive_writes_defaults(self) -> None:
        env = Path(tempfile.mkdtemp()) / ".env"
        values = setup_cmd.run_setup(interactive=False, env_path=env)

        self.assertTrue(env.is_file())
        parsed = cfgmod.parse_env_file(env)
        # Default store = local SQLite under ~/.cct.
        self.assertEqual(parsed[cfgmod.ENV_DSN], setup_cmd.DEFAULT_DSN)
        self.assertTrue(parsed[cfgmod.ENV_DSN].startswith("sqlite:///"))
        self.assertEqual(parsed[cfgmod.ENV_REDACTION], "code")
        # Blank judge backend == use the local-only default (Ollama).
        self.assertEqual(values[cfgmod.ENV_JUDGE_BACKEND], "")

    def test_override_dsn(self) -> None:
        env = Path(tempfile.mkdtemp()) / ".env"
        setup_cmd.run_setup(
            interactive=False,
            overrides={cfgmod.ENV_DSN: "postgresql://u:p@h:5432/db"},
            env_path=env,
        )
        self.assertEqual(cfgmod.parse_env_file(env)[cfgmod.ENV_DSN], "postgresql://u:p@h:5432/db")


if __name__ == "__main__":
    unittest.main()
