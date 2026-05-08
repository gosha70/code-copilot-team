# tests/test_schemas.py — schema/fixture coherence.
#
# We don't ship a JSON Schema dependency in Phase 0; the schemas in
# benchmarks/schema/ are documentation-grade. These tests verify that
# the example fixtures satisfy the small subset of schema features the
# harness actually relies on at runtime: required keys, simple types,
# enums, and the null-vs-false / null-vs-zero distinctions.
#
# A future phase may add a real JSON Schema validator; until then this
# keeps fixtures and schemas from drifting.

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = REPO_ROOT / "benchmarks" / "schema"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schema"


def _load_json(p: Path) -> Mapping[str, Any]:
    with p.open() as f:
        return json.load(f)


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def _check_type(value: Any, type_decl: Any) -> bool:
    if isinstance(type_decl, list):
        return any(_check_type(value, t) for t in type_decl)
    if type_decl == "integer":
        # JSON Schema's "integer" excludes booleans even though bool is int in Python.
        return isinstance(value, int) and not isinstance(value, bool)
    py = _TYPE_MAP.get(type_decl)
    if py is None:
        return True  # Unknown type — let other checks catch it.
    return isinstance(value, py)


def _validate(payload: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Return a list of human-readable error messages; empty == ok."""
    errors: list[str] = []
    type_decl = schema.get("type")
    if type_decl is not None and not _check_type(payload, type_decl):
        errors.append(f"{path}: expected type {type_decl!r}, got {type(payload).__name__}")
        return errors  # downstream checks would compound the noise

    if "const" in schema and payload != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {payload!r}")

    if "enum" in schema and payload not in schema["enum"]:
        errors.append(f"{path}: {payload!r} not in enum {schema['enum']!r}")

    if isinstance(payload, dict) and isinstance(type_decl, str) and type_decl == "object":
        required = schema.get("required", [])
        for key in required:
            if key not in payload:
                errors.append(f"{path}: missing required key {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in payload:
                if key not in props:
                    errors.append(f"{path}: unexpected key {key!r} (additionalProperties: false)")
        for key, sub in props.items():
            if key in payload:
                errors.extend(_validate(payload[key], sub, f"{path}.{key}"))

    if isinstance(payload, list) and isinstance(type_decl, str) and type_decl == "array":
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(payload):
                errors.extend(_validate(item, item_schema, f"{path}[{i}]"))

    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        if "minimum" in schema and payload < schema["minimum"]:
            errors.append(f"{path}: {payload} < minimum {schema['minimum']}")

    return errors


# ── Tests ──────────────────────────────────────────────────────────────


class TestSchemaFixtureCoherence(unittest.TestCase):
    def test_score_fixture_matches_schema(self) -> None:
        schema = _load_json(SCHEMA_DIR / "score.schema.json")
        fixture = _load_json(FIXTURE_DIR / "example-score.json")
        errors = _validate(fixture, schema)
        self.assertEqual(errors, [], f"score fixture invalid: {errors}")

    def test_stats_fixture_matches_schema(self) -> None:
        schema = _load_json(SCHEMA_DIR / "stats.schema.json")
        fixture = _load_json(FIXTURE_DIR / "example-stats.json")
        errors = _validate(fixture, schema)
        self.assertEqual(errors, [], f"stats fixture invalid: {errors}")

    def test_run_record_fixture_matches_schema(self) -> None:
        schema = _load_json(SCHEMA_DIR / "run-record.schema.json")
        fixture = _load_json(FIXTURE_DIR / "example-run-record.json")
        errors = _validate(fixture, schema)
        self.assertEqual(errors, [], f"run-record fixture invalid: {errors}")


class TestSchemaInvariants(unittest.TestCase):
    """Sanity-check the schemas themselves enforce contract invariants."""

    def test_stats_cost_reporting_enabled_const_false(self) -> None:
        schema = _load_json(SCHEMA_DIR / "stats.schema.json")
        cost = schema["properties"]["cost_reporting"]["properties"]["enabled"]
        self.assertEqual(cost["const"], False, "stats schema must permanently fix cost_reporting.enabled to false")

    def test_score_lint_typecheck_nullable(self) -> None:
        schema = _load_json(SCHEMA_DIR / "score.schema.json")
        lint = schema["properties"]["scores"]["properties"]["lint_passed"]
        typecheck = schema["properties"]["scores"]["properties"]["typecheck_passed"]
        self.assertIn("null", lint["type"])
        self.assertIn("null", typecheck["type"])

    def test_stats_token_fields_nullable(self) -> None:
        schema = _load_json(SCHEMA_DIR / "stats.schema.json")
        for field in (
            "tokens_input",
            "tokens_output",
            "cache_read_tokens",
            "cache_write_tokens",
        ):
            t = schema["properties"][field]["type"]
            self.assertIn("null", t, f"{field} must be nullable to distinguish 'not reported' from 0")

    def test_run_record_isolation_tier_enum(self) -> None:
        schema = _load_json(SCHEMA_DIR / "run-record.schema.json")
        tier = schema["properties"]["isolation"]["properties"]["tier"]
        self.assertEqual(
            sorted(tier["enum"]),
            sorted(["worktree", "worktree+venv", "docker"]),
            "all three isolation tiers must be in the schema from day one",
        )

    def test_run_record_prompt_required(self) -> None:
        # spec.md § Success Criteria: 'Each run records: prompt, ...'
        # This is a Phase-0-locked invariant — the prompt block must be
        # required so Phase 1's runner cannot accidentally omit it.
        schema = _load_json(SCHEMA_DIR / "run-record.schema.json")
        self.assertIn("prompt", schema["required"])
        prompt = schema["properties"]["prompt"]
        self.assertEqual(sorted(prompt["required"]), ["path", "sha256"])
        self.assertEqual(
            prompt["properties"]["sha256"]["pattern"],
            "^[0-9a-f]{64}$",
            "prompt sha256 must be lowercase 64-char hex (sha256 hex digest)",
        )

    def test_run_record_effective_prompt_optional_nullable(self) -> None:
        schema = _load_json(SCHEMA_DIR / "run-record.schema.json")
        # effective_prompt is for backends that wrap (Claude Code system
        # prompt, adapter-added framing). Optional + nullable.
        self.assertNotIn("effective_prompt", schema["required"])
        eff = schema["properties"]["effective_prompt"]
        self.assertIn("null", eff["type"])
        self.assertIn("object", eff["type"])

    def test_run_record_model_output_path_nullable(self) -> None:
        schema = _load_json(SCHEMA_DIR / "run-record.schema.json")
        # model_output_path may be null for backends that only mutate
        # the worktree (no separate text response).
        mo = schema["properties"]["model_output_path"]
        self.assertIn("null", mo["type"])
        self.assertIn("string", mo["type"])

    def test_run_record_backend_block_required(self) -> None:
        # Locked-in invariant after the Phase 2c review: backends
        # exceptions used to disappear because run.py didn't serialize
        # backend_metadata anywhere, and a permissive schema let that
        # gap go unnoticed. Since the runner now always writes the
        # backend block, the schema requires it.
        schema = _load_json(SCHEMA_DIR / "run-record.schema.json")
        self.assertIn("backend", schema["required"])
        backend = schema["properties"]["backend"]
        self.assertEqual(sorted(backend["required"]), ["error", "metadata"])
        self.assertIn("null", backend["properties"]["error"]["type"])
        self.assertIn("string", backend["properties"]["error"]["type"])
        self.assertEqual(backend["properties"]["metadata"]["type"], "object")


# Sanity check on the validator itself — it should detect obvious mismatches.
class TestValidatorSelfCheck(unittest.TestCase):
    def test_missing_required_caught(self) -> None:
        schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "string"}}}
        errors = _validate({}, schema)
        self.assertTrue(any("missing required" in e for e in errors))

    def test_wrong_type_caught(self) -> None:
        schema = {"type": "string"}
        errors = _validate(42, schema)
        self.assertTrue(any("expected type" in e for e in errors))

    def test_const_mismatch_caught(self) -> None:
        schema = {"const": False}
        errors = _validate(True, schema)
        self.assertTrue(any("expected const" in e for e in errors))

    def test_enum_mismatch_caught(self) -> None:
        schema = {"enum": ["a", "b"]}
        errors = _validate("c", schema)
        self.assertTrue(any("not in enum" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
