"""Every ingest entry point applies the configuration (#473).

Studio's pipeline ingest step and quickstart's first-run ingest called
ingest() with its defaults: code-mode redaction, no per-project overrides,
no project-id rules, no pricing. So a store configured metadata-only got
prose previews, and a project configured ``ingest: "off"`` was ingested.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from session_analytics import config as cfgmod
from session_analytics import constants as C
from session_analytics.config import ENV_NOISE_MIN_DURATION, ENV_SOURCE_PREFIX, load_config
from session_analytics.ingest.pipeline import configured_options
from session_analytics.relational.db import Database
from session_analytics.tests.support import CLAUDE_CODE_ROOT, RegistryResetTestCase, packaged_config

_FASTAPI = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)

# The fixture session's cwd is /repo/demo.
METADATA_ONLY = {C.CFG_REDACTION: C.REDACT_METADATA_ONLY}
DEMO_OPTED_OUT = {
    C.CFG_PROJECTS: {"demo-project": {C.CFG_PROJECT_INGEST: C.INGEST_OFF}},
    C.CFG_PROJECT_IDS: [{C.CFG_PROJECT_ID_MATCH: "/repo/demo", C.CFG_PROJECT_ID_ID: "demo-project"}],
}


@contextmanager
def user_config(data: dict):
    """The packaged defaults plus ``data`` as the user's config file, with the
    fixture as the Claude Code source and no CCT_SA_* from the real env."""
    path = Path(tempfile.mkdtemp(prefix="cct-sa-cfg-")) / "session-analytics.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    env = {ENV_SOURCE_PREFIX + "CLAUDE_CODE": str(CLAUDE_CODE_ROOT), ENV_NOISE_MIN_DURATION: "0"}
    with packaged_config(env), mock.patch.object(cfgmod, "_USER_CONFIG", path):
        yield


def stored(dsn: str) -> tuple[list, list]:
    db = Database.connect(dsn)
    try:
        modes = [r[0] for r in db.query("SELECT redaction_mode FROM copilot_session")]
        previews = [r[0] for r in db.query("SELECT content_preview FROM copilot_turn") if r[0]]
        return modes, previews
    finally:
        db.close()


class ConfiguredOptions(unittest.TestCase):
    def test_carries_every_configured_ingest_setting(self):
        with user_config({**METADATA_ONLY, **DEMO_OPTED_OUT}):
            cfg = load_config()
            opts = configured_options(cfg, developer_id="dev-1")
        self.assertEqual(opts["redaction_mode"], C.REDACT_METADATA_ONLY)
        self.assertEqual(opts["projects"]["demo-project"].ingest, C.INGEST_OFF)
        self.assertEqual(opts["project_id_rules"][0].id, "demo-project")
        self.assertIs(opts["pricing"], cfg.pricing)
        self.assertEqual(opts["developer_id"], "dev-1")


class QuickstartIngest(RegistryResetTestCase):
    def test_the_first_run_ingest_passes_the_configuration(self):
        from session_analytics import quickstart

        dsn = self.sqlite_dsn()
        with user_config({**METADATA_ONLY, **DEMO_OPTED_OUT}), \
             mock.patch("session_analytics.ingest.pipeline.ingest") as fake:
            quickstart.ensure_store(dsn)
        kwargs = fake.call_args.kwargs
        self.assertEqual(kwargs["redaction_mode"], C.REDACT_METADATA_ONLY)
        self.assertEqual(kwargs["projects"]["demo-project"].ingest, C.INGEST_OFF)
        self.assertEqual(kwargs["project_id_rules"][0].match, "/repo/demo")
        self.assertIsNotNone(kwargs["pricing"])


@unittest.skipUnless(_FASTAPI, "fastapi/httpx not installed; API tests skipped (covered in CI)")
class StudioIngestStep(RegistryResetTestCase):
    def run_ingest_step(self, dsn: str) -> str:
        from fastapi.testclient import TestClient

        from session_analytics.api.server import create_app

        client = TestClient(create_app(dsn), base_url="http://127.0.0.1:8765")
        r = client.post("/api/pipeline/run/ingest", json={"load": {"copilots": ["claude-code"]}})
        self.assertEqual(r.status_code, 200, r.text)
        for _ in range(200):
            job = client.get("/api/pipeline/status").json()["steps"][0]["job"]
            if job["state"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["state"], "done", job)
        return job["message"]

    def test_a_metadata_only_store_gets_no_prose(self):
        dsn = self.sqlite_dsn()
        with user_config(METADATA_ONLY):
            self.assertIn("ingested 1 sessions", self.run_ingest_step(dsn))
        modes, previews = stored(dsn)
        self.assertEqual(modes, [C.REDACT_METADATA_ONLY])
        self.assertTrue(previews)
        for p in previews:
            self.assertTrue(p.startswith("[redacted"), p)

    def test_a_project_configured_ingest_off_is_not_ingested(self):
        dsn = self.sqlite_dsn()
        with user_config(DEMO_OPTED_OUT):
            self.assertIn("ingested 0 sessions", self.run_ingest_step(dsn))
        self.assertEqual(stored(dsn), ([], []))


if __name__ == "__main__":
    unittest.main()
