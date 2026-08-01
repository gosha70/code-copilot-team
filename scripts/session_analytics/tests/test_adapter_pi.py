# Tests for the Pi analytics adapter (T11.1, FR-021/FR-026).
#
# Covers: discovery + load from .cct/worker-analytics.jsonl (+ pi-session.json),
# the synthetic is_sidechain turn model, the honest-absence contract (tokens /
# tool-calls / message-text / model / denials / review-rounds / compactions are
# None/absent, never fabricated), redaction through the EXISTING shared pipeline
# path (ingest.redaction.redact_text), and Studio-ingestion compatibility
# (registration + neutral RawSession accepted).

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from session_analytics import constants as C
from session_analytics.adapters.pi import ABSENT_FIELDS, PiAdapter
from session_analytics.ingest import redaction
from session_analytics.registry import get_adapter, _reset_for_tests
from session_analytics._register import register_all


def _write_project(root: Path, records, checkpoint=None):
    cct = root / ".cct"
    cct.mkdir(parents=True, exist_ok=True)
    with (cct / "worker-analytics.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    if checkpoint is not None:
        (cct / "pi-session.json").write_text(json.dumps(checkpoint), encoding="utf-8")
    return root


def _rec(worker, *, parent="sess-parent", verification="passed", child="ok", cost=0.01, at="2026-08-01T00:00:00Z", cid="corr-1"):
    return {
        "at": at,
        "correlationId": cid,
        "workerId": worker,
        "parentSessionId": parent,
        "childSessionId": f"child-{worker}",
        "depth": 1,
        "verification": verification,
        "childStatus": child,
        "costUsd": cost,
    }


class PiAdapterTest(unittest.TestCase):
    def test_discover_and_load_basic(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _write_project(
                Path(td) / "proj",
                [_rec("w1"), _rec("w2", verification="failed", child="ok")],
                checkpoint={"featureId": "F-42", "phase": "build"},
            )
            adapter = PiAdapter(default_root=Path(td))
            refs = adapter.discover(Path(td))
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0].copilot, "pi")
            self.assertEqual(refs[0].native_session_id, "sess-parent")

            rs = adapter.load(refs[0])
            self.assertEqual(rs.copilot, "pi")
            self.assertEqual(rs.native_session_id, "sess-parent")
            self.assertEqual(rs.phase, "build")
            self.assertEqual(rs.metadata["feature_id"], "F-42")
            self.assertEqual(rs.project_path, str(proj))
            self.assertEqual(len(rs.turns), 2)
            self.assertAlmostEqual(rs.metadata["cost_usd"], 0.02)
            self.assertEqual(rs.metadata["final_verdict"], "partial")

    def test_turns_are_sidechain_with_honest_absence(self):
        with tempfile.TemporaryDirectory() as td:
            _write_project(Path(td) / "proj", [_rec("w1")])
            adapter = PiAdapter(default_root=Path(td))
            rs = adapter.load(adapter.discover(Path(td))[0])
            t = rs.turns[0]
            self.assertTrue(t.is_sidechain, "worker turns are subagent branches")
            self.assertEqual(t.role, C.ROLE_ASSISTANT)
            # ABSENT (None/empty), never fabricated as 0 or synthetic content:
            self.assertIsNone(t.tokens_input)
            self.assertIsNone(t.tokens_output)
            self.assertIsNone(t.cache_read_tokens)
            self.assertIsNone(t.model)
            self.assertEqual(t.tool_calls, ())
            self.assertIsNone(rs.model)

    def test_absent_field_contract_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            _write_project(Path(td) / "proj", [_rec("w1")])
            adapter = PiAdapter(default_root=Path(td))
            rs = adapter.load(adapter.discover(Path(td))[0])
            for f in ("tokens", "tool_calls", "message_text", "model",
                      "permission_denials", "review_rounds", "compactions"):
                self.assertIn(f, rs.metadata["absent_fields"], f"{f} must be declared absent")
            self.assertEqual(set(rs.metadata["absent_fields"]), set(ABSENT_FIELDS))

    def test_distinct_parent_sessions_split_into_refs(self):
        with tempfile.TemporaryDirectory() as td:
            _write_project(Path(td) / "proj", [_rec("w1", parent="sess-a"), _rec("w2", parent="sess-b")])
            adapter = PiAdapter(default_root=Path(td))
            refs = adapter.discover(Path(td))
            self.assertEqual({r.native_session_id for r in refs}, {"sess-a", "sess-b"})
            for ref in refs:
                self.assertEqual(len(adapter.load(ref).turns), 1)

    def test_verdict_all_passed_and_all_failed(self):
        with tempfile.TemporaryDirectory() as td:
            _write_project(Path(td) / "p1", [_rec("w1"), _rec("w2")])
            adapter = PiAdapter(default_root=Path(td))
            rs = adapter.load(adapter.discover(Path(td) / "p1")[0])
            self.assertEqual(rs.metadata["final_verdict"], "all-passed")
        with tempfile.TemporaryDirectory() as td:
            _write_project(Path(td) / "p1", [_rec("w1", verification="failed"), _rec("w2", child="timeout")])
            adapter = PiAdapter(default_root=Path(td))
            rs = adapter.load(adapter.discover(Path(td) / "p1")[0])
            self.assertEqual(rs.metadata["final_verdict"], "all-failed")

    def test_redaction_flows_through_the_shared_pipeline_path(self):
        # The adapter emits synthetic prose text + NO tool_calls, so the
        # high-risk surfaces (code, tool input/output) are absent. Every turn's
        # text still flows the EXISTING shared redact_text path.
        with tempfile.TemporaryDirectory() as td:
            _write_project(Path(td) / "proj", [_rec("w1")])
            adapter = PiAdapter(default_root=Path(td))
            rs = adapter.load(adapter.discover(Path(td))[0])
            t = rs.turns[0]
            # metadata-only reduces content to a length+hash marker (no readable text)
            red = redaction.redact_text(t.text, C.REDACT_METADATA_ONLY)
            self.assertTrue(red.startswith("[redacted"))
            self.assertNotIn("worker w1", red)
            # no tool-call surface to leak
            self.assertEqual(t.tool_calls, ())

    def test_registered_for_studio_ingestion(self):
        _reset_for_tests()
        register_all()
        try:
            adapter = get_adapter("pi")  # resolved instance, ready for the pipeline
            self.assertIsNotNone(adapter)
            self.assertEqual(adapter.copilot_id, "pi")
        finally:
            _reset_for_tests()


if __name__ == "__main__":
    unittest.main()
