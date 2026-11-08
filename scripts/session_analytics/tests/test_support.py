from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from session_analytics import config as cfgmod
from session_analytics.tests.support import packaged_config

PACKAGED_JUDGE = ("ollama", "")
JUDGE_KEYS_CLEARED = {cfgmod.ENV_JUDGE_BACKEND: "", cfgmod.ENV_JUDGE_MODEL: ""}


class TestPackagedConfig(unittest.TestCase):
    def setUp(self) -> None:
        home = Path(tempfile.mkdtemp(prefix="cct-sa-user-config-"))
        self.addCleanup(shutil.rmtree, home, True)
        user_file = home / "session-analytics.json"
        user_file.write_text(
            json.dumps({"judge": {"default": {"backend": "openai", "model": "x"}}}),
            encoding="utf-8",
        )
        patcher = mock.patch.object(cfgmod, "_USER_CONFIG", user_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _judge(self) -> tuple[str, str]:
        return cfgmod.load_config().judge.resolve(None)

    def test_a_user_config_judge_leaks_past_the_env_file_and_env_patches(self) -> None:
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict(os.environ, JUDGE_KEYS_CLEARED):
            self.assertEqual(self._judge(), ("openai", "x"))

    def test_packaged_config_ignores_a_user_config_judge(self) -> None:
        with packaged_config(JUDGE_KEYS_CLEARED):
            self.assertEqual(self._judge(), PACKAGED_JUDGE)

    def test_packaged_config_ignores_every_local_source_at_once(self) -> None:
        local = {cfgmod.ENV_JUDGE_BACKEND: "openai", cfgmod.ENV_JUDGE_MODEL: "y"}
        with mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: dict(local)), \
             mock.patch.dict(os.environ, local):
            self.assertEqual(self._judge(), ("openai", "y"))
            with packaged_config(JUDGE_KEYS_CLEARED):
                self.assertEqual(self._judge(), PACKAGED_JUDGE)

    def test_packaged_config_restores_what_it_patched(self) -> None:
        before = (cfgmod._USER_CONFIG, cfgmod.parse_env_file, os.environ.get(cfgmod.ENV_JUDGE_BACKEND))
        with packaged_config({cfgmod.ENV_JUDGE_BACKEND: "openai"}):
            self.assertEqual(os.environ[cfgmod.ENV_JUDGE_BACKEND], "openai")
        after = (cfgmod._USER_CONFIG, cfgmod.parse_env_file, os.environ.get(cfgmod.ENV_JUDGE_BACKEND))
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
