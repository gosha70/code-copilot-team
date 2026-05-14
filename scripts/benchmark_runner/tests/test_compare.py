# tests/test_compare.py — multi-LLM compare driver.
#
# Hermetic: uses the stub adapter + stub backend (deterministic) and
# patches in a second stub backend variant ("stub2") so the compare
# config has the required >=2 candidates without needing claude-code
# auth or a real LLM. Verifies:
#
#   - Config parsing rejects every shape error (unknown key, < 2
#     candidates, duplicate name, bad env value, deprecated combined
#     backend:model form).
#   - Env patching applies overrides during the candidate's runs and
#     restores prior values (including deletion of keys we set new).
#   - The parent run-dir layout: manifest + per-candidate nested
#     run-dirs + candidate-runs.json + report.md.
#   - Manifest persists env *key names* only (no values).
#   - Report aggregator finds attempts from every candidate's nested
#     run-dir via rglob.

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from benchmark_runner import _register
from benchmark_runner.compare import (
    COMPARE_SCHEMA_VERSION,
    Candidate,
    CompareConfig,
    CompareConfigError,
    _patched_env,
    _validate,
    load_config,
    run_comparison,
)
from benchmark_runner.registry import register_backend


# Re-registered fresh per test so the stub adapter + stub backend are
# present without coupling to the production register_all().
def _fresh_registry() -> None:
    _register.unregister_all_for_tests()
    from benchmarks.adapters.stub.adapter import register as register_stub_adapter
    register_stub_adapter()
    from benchmark_runner.backends import stub as stub_backend
    register_backend(stub_backend.BACKEND_FAMILY, stub_backend.factory)
    # Second alias so a compare config can have ≥2 candidates that
    # both behave deterministically. Same factory, different family
    # name — gives the report two distinct group labels.
    register_backend("stub2", stub_backend.factory)


# ── Config validation ──────────────────────────────────────────────────


class ConfigValidationTest(unittest.TestCase):
    def _ok_raw(self) -> dict:
        return {
            "benchmark": "stub",
            "candidates": [
                {"backend": "stub"},
                {"backend": "stub2"},
            ],
        }

    def test_minimal_valid_config(self) -> None:
        cfg = _validate(self._ok_raw())
        self.assertEqual(cfg.benchmark, "stub")
        self.assertEqual(cfg.runs, 1)
        self.assertIsNone(cfg.task_filter)
        self.assertEqual(len(cfg.candidates), 2)
        # Default name = backend when model is empty.
        self.assertEqual(cfg.candidates[0].name, "stub")
        self.assertEqual(cfg.candidates[1].name, "stub2")

    def test_explicit_name_and_model(self) -> None:
        raw = self._ok_raw()
        raw["candidates"] = [
            {"name": "primary", "backend": "stub", "model": "v1"},
            {"name": "secondary", "backend": "stub", "model": "v2"},
        ]
        cfg = _validate(raw)
        self.assertEqual([c.name for c in cfg.candidates], ["primary", "secondary"])
        self.assertEqual([c.model for c in cfg.candidates], ["v1", "v2"])

    def test_default_name_is_backend_colon_model(self) -> None:
        raw = self._ok_raw()
        raw["candidates"] = [
            {"backend": "stub", "model": "v1"},
            {"backend": "stub", "model": "v2"},
        ]
        cfg = _validate(raw)
        self.assertEqual(cfg.candidates[0].name, "stub:v1")
        self.assertEqual(cfg.candidates[1].name, "stub:v2")

    def test_rejects_non_object(self) -> None:
        with self.assertRaisesRegex(CompareConfigError, "JSON object"):
            _validate(["not", "an", "object"])

    def test_rejects_missing_benchmark(self) -> None:
        with self.assertRaisesRegex(CompareConfigError, "benchmark"):
            _validate({"candidates": [{"backend": "stub"}, {"backend": "stub2"}]})

    def test_rejects_runs_zero(self) -> None:
        raw = self._ok_raw()
        raw["runs"] = 0
        with self.assertRaisesRegex(CompareConfigError, "positive integer"):
            _validate(raw)

    def test_rejects_runs_bool(self) -> None:
        # bool is a subclass of int in Python — guard against that.
        raw = self._ok_raw()
        raw["runs"] = True
        with self.assertRaisesRegex(CompareConfigError, "positive integer"):
            _validate(raw)

    def test_rejects_single_candidate(self) -> None:
        raw = self._ok_raw()
        raw["candidates"] = [{"backend": "stub"}]
        with self.assertRaisesRegex(CompareConfigError, "at least 2"):
            _validate(raw)

    def test_rejects_duplicate_names(self) -> None:
        raw = self._ok_raw()
        raw["candidates"] = [
            {"name": "x", "backend": "stub"},
            {"name": "x", "backend": "stub2"},
        ]
        with self.assertRaisesRegex(CompareConfigError, "reused"):
            _validate(raw)

    def test_rejects_combined_backend_model_form(self) -> None:
        raw = self._ok_raw()
        raw["candidates"][0]["backend"] = "claude-code:sonnet"
        with self.assertRaisesRegex(CompareConfigError, "deprecated"):
            _validate(raw)

    def test_rejects_non_string_env_value(self) -> None:
        raw = self._ok_raw()
        raw["candidates"][0]["env"] = {"ANTHROPIC_BASE_URL": 8000}
        with self.assertRaisesRegex(CompareConfigError, "string"):
            _validate(raw)

    def test_rejects_task_filter_with_non_strings(self) -> None:
        raw = self._ok_raw()
        raw["task"] = ["python/leap", 42]
        with self.assertRaisesRegex(CompareConfigError, "non-empty strings"):
            _validate(raw)

    def test_load_config_reads_from_disk(self) -> None:
        raw = self._ok_raw()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cfg.json"
            p.write_text(json.dumps(raw), encoding="utf-8")
            cfg = load_config(p)
            self.assertEqual(cfg.benchmark, "stub")

    def test_load_config_reports_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.json"
            p.write_text("{not json}", encoding="utf-8")
            with self.assertRaisesRegex(CompareConfigError, "invalid JSON"):
                load_config(p)


# ── Env patching ───────────────────────────────────────────────────────


class PatchedEnvTest(unittest.TestCase):
    def test_applies_and_restores_new_keys(self) -> None:
        key = "CCT_COMPARE_TEST_NEW_KEY"
        self.assertNotIn(key, os.environ)
        with _patched_env({key: "value1"}):
            self.assertEqual(os.environ[key], "value1")
        self.assertNotIn(key, os.environ)

    def test_applies_and_restores_existing_keys(self) -> None:
        key = "CCT_COMPARE_TEST_EXISTING"
        with mock.patch.dict(os.environ, {key: "original"}):
            with _patched_env({key: "overridden"}):
                self.assertEqual(os.environ[key], "overridden")
            self.assertEqual(os.environ[key], "original")

    def test_restores_on_exception(self) -> None:
        key = "CCT_COMPARE_TEST_EXCEPTION"
        self.assertNotIn(key, os.environ)
        with self.assertRaises(RuntimeError):
            with _patched_env({key: "set-during-error"}):
                raise RuntimeError("simulated")
        self.assertNotIn(key, os.environ, "env must be restored even on exception")


# ── End-to-end orchestration ───────────────────────────────────────────


class RunComparisonE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        _fresh_registry()
        self.addCleanup(_register.unregister_all_for_tests)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runs_root = Path(self._tmp.name) / "runs"

    def _build_config(self) -> CompareConfig:
        return CompareConfig(
            benchmark="stub",
            runs=1,
            task_filter=None,
            candidates=[
                Candidate(name="alpha", backend="stub", model="", env={}),
                Candidate(name="beta", backend="stub2", model="", env={}),
            ],
        )

    def test_creates_parent_run_dir_with_expected_layout(self) -> None:
        run_dir = run_comparison(
            self._build_config(),
            runs_root=self.runs_root,
            timestamp="20260101T000000Z",
            emit_report=False,
        )
        self.assertTrue(run_dir.is_dir())
        # Counter suffix `-001` comes from allocate_unique_dir;
        # see test_back_to_back_compares_get_incrementing_suffixes
        # for the collision-handling regression.
        self.assertEqual(run_dir.name, "20260101T000000Z-compare-stub-001")
        self.assertTrue((run_dir / "compare-manifest.json").is_file())
        self.assertTrue((run_dir / "candidate-runs.json").is_file())

    def test_back_to_back_compares_get_incrementing_suffixes(self) -> None:
        # Reviewer-flagged regression (P2): two compare invocations
        # within the same UTC-second under the same runs_root previously
        # collided on FileExistsError because mkdir(exist_ok=False) ran
        # without the counter-suffix allocator that run.py uses.
        cfg = self._build_config()
        a = run_comparison(cfg, runs_root=self.runs_root,
                           timestamp="20260101T000099Z", emit_report=False)
        b = run_comparison(cfg, runs_root=self.runs_root,
                           timestamp="20260101T000099Z", emit_report=False)
        self.assertEqual(a.name, "20260101T000099Z-compare-stub-001")
        self.assertEqual(b.name, "20260101T000099Z-compare-stub-002")
        self.assertNotEqual(a, b)

    def test_manifest_records_schema_and_candidate_metadata(self) -> None:
        run_dir = run_comparison(
            self._build_config(),
            runs_root=self.runs_root,
            timestamp="20260101T000001Z",
            emit_report=False,
        )
        manifest = json.loads((run_dir / "compare-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], COMPARE_SCHEMA_VERSION)
        self.assertEqual(manifest["benchmark"], "stub")
        self.assertEqual(len(manifest["candidates"]), 2)
        self.assertEqual(manifest["candidates"][0]["name"], "alpha")
        self.assertEqual(manifest["candidates"][1]["backend"], "stub2")

    def test_manifest_redacts_env_values(self) -> None:
        cfg = CompareConfig(
            benchmark="stub",
            runs=1,
            task_filter=None,
            candidates=[
                Candidate(
                    name="alpha", backend="stub", model="",
                    env={"ANTHROPIC_AUTH_TOKEN": "sk-ant-leaked-secret"},
                ),
                Candidate(name="beta", backend="stub2", model="", env={}),
            ],
        )
        run_dir = run_comparison(cfg, runs_root=self.runs_root, timestamp="20260101T000002Z", emit_report=False)
        text = (run_dir / "compare-manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-ant-leaked-secret", text, "env values must NEVER be persisted")
        manifest = json.loads(text)
        self.assertEqual(manifest["candidates"][0]["env_keys"], ["ANTHROPIC_AUTH_TOKEN"])

    def test_each_candidate_produces_a_nested_run_dir(self) -> None:
        run_dir = run_comparison(
            self._build_config(),
            runs_root=self.runs_root,
            timestamp="20260101T000003Z",
            emit_report=False,
        )
        # Each candidate's run_benchmark call produces one timestamped
        # nested dir of the form <ts>-stub-stub/.
        nested = [p for p in run_dir.iterdir() if p.is_dir()]
        self.assertEqual(len(nested), 2, f"expected 2 nested run-dirs, got: {nested}")
        # Each nested dir should contain at least one score.json
        # (proof that run_benchmark actually executed there).
        for d in nested:
            scores = list(d.rglob("score.json"))
            self.assertTrue(scores, f"no score.json under {d}")

    def test_candidate_runs_json_maps_names_to_relative_run_dirs(self) -> None:
        run_dir = run_comparison(
            self._build_config(),
            runs_root=self.runs_root,
            timestamp="20260101T000004Z",
            emit_report=False,
        )
        payload = json.loads((run_dir / "candidate-runs.json").read_text(encoding="utf-8"))
        names = [c["name"] for c in payload["candidates"]]
        self.assertEqual(names, ["alpha", "beta"])
        for c in payload["candidates"]:
            self.assertTrue((run_dir / c["run_dir"]).is_dir())

    def test_same_backend_and_model_different_candidates_get_distinct_groups(self) -> None:
        # Reviewer-flagged regression (P1): two candidates with identical
        # (backend, model) but distinct names + distinct env routing
        # used to collapse into one report group, masking any per-
        # provider difference. The v2 report schema includes candidate
        # name in the group key so the comparison stays apples-to-
        # apples — the labels in the report come from the unique
        # candidate names enforced at config validation time.
        #
        # Both candidates use family ``stub`` with model `""`; before
        # the v2 fix they grouped to the same key. After the fix the
        # candidate_name discriminates.
        cfg = CompareConfig(
            benchmark="stub", runs=1, task_filter=None,
            candidates=[
                Candidate(name="anthropic-direct", backend="stub", model="",
                          env={"CCT_FAKE_ROUTE": "direct"}),
                Candidate(name="openrouter-proxy", backend="stub2", model="",
                          env={"CCT_FAKE_ROUTE": "proxy"}),
            ],
        )
        run_dir = run_comparison(
            cfg, runs_root=self.runs_root,
            timestamp="20260101T000010Z", emit_report=True,
        )
        payload = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        labels = sorted(payload["groups"].keys())
        self.assertEqual(labels, ["anthropic-direct", "openrouter-proxy"])
        # The candidate_name field carries through so external consumers
        # can correlate report labels with compare-manifest entries.
        for label, group in payload["groups"].items():
            self.assertEqual(group["candidate_name"], label)
        # Two distinct groups => one pairwise verdict block emitted.
        self.assertIsNotNone(payload["verdicts"])
        self.assertEqual(len(payload["verdicts"]["pairwise"]), 1)
        pair = payload["verdicts"]["pairwise"][0]
        self.assertEqual(sorted([pair["a"], pair["b"]]),
                         ["anthropic-direct", "openrouter-proxy"])

    def test_plain_run_dir_preserves_v1_grouping_behaviour(self) -> None:
        # Backwards-compat regression: a non-compare run-dir (no
        # candidate-runs.json) must still group by (backend_id, model)
        # alone, producing the same labels v1 emitted. Otherwise the
        # v2 bump would break every existing report consumer (the
        # dogfood subcommand, archived run-dirs, anything downstream).
        from benchmark_runner.run import run_benchmark
        from benchmark_runner.report import render_report
        single_run_dir = run_benchmark(
            "stub", "stub", "", runs=1, runs_root=self.runs_root,
        )
        # No candidate-runs.json => plain layout.
        self.assertFalse((single_run_dir / "candidate-runs.json").exists())
        render_report(single_run_dir)
        payload = json.loads((single_run_dir / "report.json").read_text(encoding="utf-8"))
        # v1 label format preserved: "stub" (no model => bare backend id).
        self.assertEqual(list(payload["groups"].keys()), ["stub"])
        self.assertEqual(payload["groups"]["stub"]["candidate_name"], "")

    def test_emit_report_writes_aggregate_markdown(self) -> None:
        # The report aggregator groups by (backend_id, model) where
        # backend_id is the backend instance's own attribute, not the
        # registry lookup key. Registering the same stub class under
        # two aliases would collapse them into one group; differentiate
        # via the model field instead — which is also how a real
        # multi-LLM compare config works (each LLM has a distinct model
        # identifier even when the copilot backend is the same).
        cfg = CompareConfig(
            benchmark="stub", runs=1, task_filter=None,
            candidates=[
                Candidate(name="model-a", backend="stub", model="model-a", env={}),
                Candidate(name="model-b", backend="stub", model="model-b", env={}),
            ],
        )
        run_dir = run_comparison(
            cfg, runs_root=self.runs_root,
            timestamp="20260101T000005Z", emit_report=True,
        )
        self.assertTrue((run_dir / "report.md").is_file())
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        # Both groups present, labelled by (backend, model).
        self.assertIn("model-a", report)
        self.assertIn("model-b", report)

    def test_env_overrides_visible_during_runs_and_restored_after(self) -> None:
        # Verify the env patching is *in effect* during the per-candidate
        # run_benchmark call. The recording factory wraps the stub
        # backend's run() to capture os.environ["CCT_COMPARE_PROBE"]
        # at attempt-execution time. Observations are appended to a
        # single list (in candidate declaration order) rather than
        # keyed by backend_id — both candidates use the same stub
        # backend instance and would collide on backend_id.
        observed: list[str | None] = []

        from benchmark_runner.backends import stub as stub_backend
        original_factory = stub_backend.factory

        def recording_factory(model: str):  # noqa: ANN202 — test-local
            backend = original_factory(model)
            original_run = backend.run

            def wrapped_run(prompt, ctx):  # noqa: ANN202
                observed.append(os.environ.get("CCT_COMPARE_PROBE"))
                return original_run(prompt, ctx)

            backend.run = wrapped_run  # type: ignore[method-assign]
            return backend

        # Clear the registry so we can install the recording factory
        # under both family names (the registry refuses re-registration
        # of an existing family — see registry.register_backend).
        _register.unregister_all_for_tests()
        from benchmarks.adapters.stub.adapter import register as register_stub_adapter
        register_stub_adapter()
        register_backend("stub", recording_factory)
        register_backend("stub2", recording_factory)

        cfg = CompareConfig(
            benchmark="stub", runs=1, task_filter=None,
            candidates=[
                Candidate(name="alpha", backend="stub", model="",
                          env={"CCT_COMPARE_PROBE": "alpha-value"}),
                Candidate(name="beta", backend="stub2", model="",
                          env={"CCT_COMPARE_PROBE": "beta-value"}),
            ],
        )
        self.assertNotIn("CCT_COMPARE_PROBE", os.environ)
        run_comparison(cfg, runs_root=self.runs_root,
                       timestamp="20260101T000006Z", emit_report=False)

        # Each candidate saw its own env value at run time, in
        # declaration order (alpha first, then beta).
        self.assertEqual(observed, ["alpha-value", "beta-value"])
        # Env restored after the compare returns — no leak into the test process.
        self.assertNotIn("CCT_COMPARE_PROBE", os.environ)


if __name__ == "__main__":
    unittest.main()
