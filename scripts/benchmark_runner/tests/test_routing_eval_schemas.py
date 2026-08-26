# tests/test_routing_eval_schemas.py — routing-eval (E1 of #109) T1 contracts.
#
# test_schemas.py's hand validator deliberately covers only the subset
# the harness relies on — and that subset excludes $ref, oneOf, not,
# pattern, and length constraints, which is exactly what E1's contracts
# are made of. Reusing it here produced tests that PASSED without
# proving rejection (a mixed candidates+arms config validated cleanly).
# So this module ships its own validator for that larger subset and
# proves the negatives: what the contract says must be rejected, IS.
#
# The other load-bearing suite here is TestMetricContractCoverage.
# plan.md's § Metric contract says a metric not in the table is not
# reported; the converse also has to hold, or the table is decoration.
# It walks every row and asserts its raw-evidence field exists in a
# schema, so a metric can never be promised by the plan and be
# unimplementable in the record.

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = REPO_ROOT / "benchmarks" / "schema"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "schema"


def _load_json(p: Path) -> Any:
    with p.open(encoding="utf-8") as f:
        return json.load(f)


# ── validator: the subset E1's schemas actually use ────────────────────

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
    if type_decl in ("integer", "number"):
        if isinstance(value, bool):
            return False
        return isinstance(value, _TYPE_MAP[type_decl])
    py = _TYPE_MAP.get(type_decl)
    return True if py is None else isinstance(value, py)


def _resolve_ref(ref: str, root: Mapping[str, Any]) -> Mapping[str, Any]:
    assert ref.startswith("#/"), f"only intra-document refs supported: {ref}"
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(payload: Any, schema: Mapping[str, Any], root: Mapping[str, Any] | None = None, path: str = "$") -> list[str]:
    """Errors for the schema subset E1 uses; empty list == valid.

    Covers: type, required, properties, additionalProperties (false or
    a subschema), items, enum, const, pattern, minLength, minItems,
    minProperties, minimum, $ref, oneOf (exactly one branch), anyOf
    (at least one branch), and not.
    """
    root = root if root is not None else schema
    errors: list[str] = []

    if "$ref" in schema:
        return validate(payload, _resolve_ref(schema["$ref"], root), root, path)

    type_decl = schema.get("type")
    if type_decl is not None and not _check_type(payload, type_decl):
        return [f"{path}: expected type {type_decl!r}, got {type(payload).__name__}"]

    if "const" in schema and payload != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {payload!r}")
    if "enum" in schema and payload not in schema["enum"]:
        errors.append(f"{path}: {payload!r} not in enum {schema['enum']!r}")

    if isinstance(payload, str):
        if "pattern" in schema and not re.search(schema["pattern"], payload):
            errors.append(f"{path}: {payload!r} does not match pattern {schema['pattern']!r}")
        if "minLength" in schema and len(payload) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")

    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        if "minimum" in schema and payload < schema["minimum"]:
            errors.append(f"{path}: {payload} below minimum {schema['minimum']}")

    if isinstance(payload, list):
        if "minItems" in schema and len(payload) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for i, element in enumerate(payload):
                errors.extend(validate(element, items, root, f"{path}[{i}]"))

    if isinstance(payload, dict):
        if "minProperties" in schema and len(payload) < schema["minProperties"]:
            errors.append(f"{path}: fewer than minProperties {schema['minProperties']}")
        for req in schema.get("required", []):
            if req not in payload:
                errors.append(f"{path}: missing required {req!r}")
        props = schema.get("properties", {})
        additional = schema.get("additionalProperties")
        for key, value in payload.items():
            if key in props:
                errors.extend(validate(value, props[key], root, f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}: unexpected property {key!r}")
            elif isinstance(additional, Mapping):
                errors.extend(validate(value, additional, root, f"{path}.{key}"))

    if "not" in schema and not validate(payload, schema["not"], root, path):
        errors.append(f"{path}: matches forbidden subschema")

    if "anyOf" in schema:
        if not any(not validate(payload, branch, root, path) for branch in schema["anyOf"]):
            errors.append(f"{path}: matched no anyOf branch")

    if "oneOf" in schema:
        matches = sum(1 for branch in schema["oneOf"] if not validate(payload, branch, root, path))
        if matches != 1:
            errors.append(f"{path}: matched {matches} oneOf branches, need exactly 1")

    return errors


def _schema(name: str) -> Mapping[str, Any]:
    return _load_json(SCHEMA_DIR / f"{name}.schema.json")


class TestValidatorSelfCheck(unittest.TestCase):
    """The validator must itself catch what these tests rely on."""

    def test_oneof_requires_exactly_one_branch(self) -> None:
        schema = {"oneOf": [{"required": ["a"]}, {"required": ["b"]}]}
        self.assertEqual(validate({"a": 1}, schema), [])
        self.assertTrue(validate({"a": 1, "b": 2}, schema))
        self.assertTrue(validate({}, schema))

    def test_not_required_is_enforced(self) -> None:
        schema = {"not": {"required": ["x"]}}
        self.assertEqual(validate({}, schema), [])
        self.assertTrue(validate({"x": 1}, schema))

    def test_ref_resolves_into_defs(self) -> None:
        schema = {"$ref": "#/$defs/thing", "$defs": {"thing": {"type": "string"}}}
        self.assertEqual(validate("ok", schema), [])
        self.assertTrue(validate(7, schema))

    def test_anyof_and_additional_properties_schema(self) -> None:
        any_schema = {"not": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}}
        self.assertEqual(validate({"c": 1}, any_schema), [])
        self.assertTrue(validate({"a": 1}, any_schema))
        self.assertTrue(validate({"b": 1}, any_schema))
        ap_schema = {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {"type": "object", "required": ["reason"]},
        }
        self.assertTrue(validate({}, ap_schema))
        self.assertTrue(validate({"x": {}}, ap_schema))
        self.assertEqual(validate({"x": {"reason": "r"}}, ap_schema), [])

    def test_pattern_and_lengths(self) -> None:
        self.assertTrue(validate("estimated", {"pattern": "^(measured|estimated@.+)$"}))
        self.assertTrue(validate("", {"type": "string", "minLength": 1}))
        self.assertTrue(validate([], {"type": "array", "minItems": 1}))


class TestRoutingEvalFixtureCoherence(unittest.TestCase):
    def test_routing_run_fixture_matches_schema(self) -> None:
        errors = validate(_load_json(FIXTURE_DIR / "example-routing-run.json"), _schema("routing-run"))
        self.assertEqual(errors, [], f"routing-run fixture invalid: {errors}")

    def test_outcome_matrix_fixture_matches_schema(self) -> None:
        errors = validate(_load_json(FIXTURE_DIR / "example-outcome-matrix.json"), _schema("outcome-matrix"))
        self.assertEqual(errors, [], f"outcome-matrix fixture invalid: {errors}")


class TestCompareConfigRejection(unittest.TestCase):
    """The mutual exclusion is proven by rejection, not by prose."""

    def setUp(self) -> None:
        self.schema = _schema("compare-config")
        self.full_arms = [
            {"kind": "always_best"},
            {"kind": "always_cheapest"},
            {"kind": "oracle"},
            {"kind": "cct_router", "registry": "routing.toml"},
        ]
        self.scenario_only = {
            "benchmark": "stub",
            "scenario": "hybrid-routing",
            "cost_basis": "measured",
            "arms": self.full_arms,
        }
        self.candidates_only = {
            "benchmark": "stub",
            "candidates": [{"backend": "a"}, {"backend": "b"}],
        }

    def test_both_pure_shapes_validate(self) -> None:
        self.assertEqual(validate(self.scenario_only, self.schema), [])
        self.assertEqual(validate(self.candidates_only, self.schema), [])

    def test_mixed_config_is_rejected_by_schema(self) -> None:
        mixed = dict(self.candidates_only)
        mixed.update({"scenario": "hybrid-routing", "arms": self.scenario_only["arms"]})
        self.assertTrue(validate(mixed, self.schema), "mixed candidates+arms validated")

    def test_arms_without_scenario_is_rejected(self) -> None:
        broken = {"benchmark": "stub", "arms": self.scenario_only["arms"]}
        self.assertTrue(validate(broken, self.schema))

    def test_unknown_arm_kind_is_rejected(self) -> None:
        bad = dict(self.scenario_only)
        bad["arms"] = [{"kind": "coin_flip"}]
        self.assertTrue(validate(bad, self.schema))

    def test_bare_estimated_cost_basis_is_rejected(self) -> None:
        bad = dict(self.scenario_only)
        bad["cost_basis"] = "estimated"
        self.assertTrue(validate(bad, self.schema))
        ok = dict(self.scenario_only)
        ok["cost_basis"] = "estimated@price-table-v1"
        self.assertEqual(validate(ok, self.schema), [])

    def test_mixed_config_is_refused_by_the_executable_parser(self) -> None:
        # The schema documents; compare.py enforces. Both must refuse.
        from benchmark_runner.compare import CompareConfigError, _validate as compare_validate

        mixed = dict(self.candidates_only)
        mixed["arms"] = self.scenario_only["arms"]
        with self.assertRaisesRegex(CompareConfigError, "both 'candidates' and 'arms'"):
            compare_validate(mixed)

    def test_scenario_config_is_not_silently_run_as_candidates(self) -> None:
        from benchmark_runner.compare import CompareConfigError, _validate as compare_validate

        with self.assertRaisesRegex(CompareConfigError, "routing-scenario config"):
            compare_validate(dict(self.scenario_only))

    def test_scenario_parser_accepts_the_valid_shape(self) -> None:
        from benchmark_runner.routing_eval.scenario_config import validate_scenario_config

        cfg = validate_scenario_config(self.scenario_only)
        self.assertEqual(
            sorted(a.kind for a in cfg.arms),
            ["always_best", "always_cheapest", "cct_router", "oracle"],
        )
        self.assertEqual(cfg.cost_basis, "measured")

    def test_scenario_parser_rejects_mixed_and_broken_shapes(self) -> None:
        from benchmark_runner.routing_eval.scenario_config import (
            ScenarioConfigError,
            validate_scenario_config,
        )

        no_router = [a for a in self.full_arms if a["kind"] != "cct_router"]
        cases = {
            "mixed": {**self.scenario_only, "candidates": [{"backend": "a"}]},
            "unknown kind": {
                **self.scenario_only,
                "arms": no_router + [{"kind": "coin_flip"}],
            },
            "router without registry": {
                **self.scenario_only,
                "arms": no_router + [{"kind": "cct_router"}],
            },
            "bare estimated basis": {**self.scenario_only, "cost_basis": "estimated"},
            "seed/trial mismatch": {**self.scenario_only, "trials": 3, "trial_seeds": [1, 2]},
            "budget arm without ceiling": {
                **self.scenario_only,
                "arms": self.full_arms + [{"kind": "oracle_budget"}],
            },
            "ceiling without budget arm": {**self.scenario_only, "budget_ceiling_usd": 1.0},
            "bad event outcome": {
                **self.scenario_only,
                "event_stream": [{"at_task_index": 0, "outcome": "gremlins"}],
            },
        }
        for label, payload in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ScenarioConfigError):
                    validate_scenario_config(payload)

    def test_scenario_parser_requires_the_complete_control_set(self) -> None:
        # FR-E1-3: each mandatory kind exactly once. A missing control
        # arm or a duplicated one is refused at load time, not
        # discovered by the reporter.
        from benchmark_runner.routing_eval.scenario_config import (
            ScenarioConfigError,
            validate_scenario_config,
        )

        for missing in ("always_best", "always_cheapest", "oracle", "cct_router"):
            with self.subTest(missing=missing):
                arms = [a for a in self.full_arms if a["kind"] != missing]
                with self.assertRaisesRegex(ScenarioConfigError, "exactly once"):
                    validate_scenario_config({**self.scenario_only, "arms": arms})
        with self.subTest(case="duplicate oracle"):
            dup = self.full_arms + [{"kind": "oracle", "name": "oracle-2"}]
            with self.assertRaisesRegex(ScenarioConfigError, "exactly once"):
                validate_scenario_config({**self.scenario_only, "arms": dup})

    def test_scenario_parser_requires_a_cost_basis(self) -> None:
        from benchmark_runner.routing_eval.scenario_config import (
            ScenarioConfigError,
            validate_scenario_config,
        )

        payload = dict(self.scenario_only)
        del payload["cost_basis"]
        with self.assertRaisesRegex(ScenarioConfigError, "cost_basis"):
            validate_scenario_config(payload)

    def test_scenario_parser_is_closed_over_keys(self) -> None:
        # Misspelled keys silently ignored are fail-open: trial_seedz
        # would run with default seeds while looking configured.
        from benchmark_runner.routing_eval.scenario_config import (
            ScenarioConfigError,
            validate_scenario_config,
        )

        no_router = [a for a in self.full_arms if a["kind"] != "cct_router"]
        cases = {
            "top-level typo": {**self.scenario_only, "trial_seedz": [1]},
            "arm typo": {
                **self.scenario_only,
                "arms": no_router + [{"kind": "cct_router", "regsitry": "r"}],
            },
            "event typo": {
                **self.scenario_only,
                "event_stream": [{"at_task_index": 0, "outcoem": "usage_limit"}],
            },
        }
        for label, payload in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ScenarioConfigError):
                    validate_scenario_config(payload)

    def test_scenario_parser_rejects_non_finite_ceiling(self) -> None:
        from benchmark_runner.routing_eval.scenario_config import (
            ScenarioConfigError,
            validate_scenario_config,
        )

        arms = self.full_arms + [{"kind": "oracle_budget"}]
        for bad in (float("nan"), float("inf"), True, -1.0):
            with self.subTest(ceiling=bad):
                with self.assertRaises(ScenarioConfigError):
                    validate_scenario_config(
                        {**self.scenario_only, "arms": arms, "budget_ceiling_usd": bad}
                    )

    def test_incomplete_arm_set_fails_the_schema_floor(self) -> None:
        payload = dict(self.scenario_only)
        payload["arms"] = [{"kind": "cct_router", "registry": "r"}]
        self.assertTrue(validate(payload, self.schema))

    def test_each_axis_forbids_the_others_fields_in_schema(self) -> None:
        cases = {
            "scenario without cost_basis": {
                k: v for k, v in self.scenario_only.items() if k != "cost_basis"
            },
            "candidates with cost_basis": {**self.candidates_only, "cost_basis": "measured"},
            "candidates with trial_seeds": {**self.candidates_only, "trial_seeds": [1]},
            "scenario with runs": {**self.scenario_only, "runs": 3},
            "scenario with attempt_timeout": {
                **self.scenario_only,
                "attempt_timeout_seconds": 60,
            },
        }
        for label, payload in cases.items():
            with self.subTest(case=label):
                self.assertTrue(
                    validate(payload, self.schema), f"{label} validated but must not"
                )

    def test_candidate_parser_rejects_stray_scenario_fields(self) -> None:
        # Even without 'scenario'/'arms', a candidate config carrying
        # scenario-only keys is refused — never silently ignored.
        from benchmark_runner.compare import CompareConfigError, _validate as compare_validate

        for key, value in (
            ("cost_basis", "measured"),
            ("trial_seeds", [1, 2]),
            ("event_stream", []),
            ("budget_ceiling_usd", 1.0),
        ):
            with self.subTest(key=key):
                payload = {**self.candidates_only, key: value}
                with self.assertRaisesRegex(CompareConfigError, "scenario-only"):
                    compare_validate(payload)

    # Pre-existing violation, PINNED not fixed: cross-language-mini.json
    # has shipped with a single candidate since dfc85c7, violating the
    # schema's own minItems:2. The old test validator never checked
    # minItems, so it went unnoticed. Fixing a shipped preset is outside
    # E1's scope; this pin makes the exception visible and will fail the
    # day the preset is repaired, prompting removal of the pin.
    _KNOWN_PRESET_VIOLATIONS = {
        "cross-language-mini.json": ["$.candidates: fewer than minItems 2"],
    }

    def test_existing_candidate_presets_still_validate(self) -> None:
        preset_dir = REPO_ROOT / "benchmarks" / "presets"
        presets = sorted(preset_dir.glob("*.json"))
        self.assertTrue(presets, "no presets found to regression-check")
        for preset in presets:
            with self.subTest(preset=preset.name):
                payload = _load_json(preset)
                errors = validate(payload, self.schema)
                expected = self._KNOWN_PRESET_VIOLATIONS.get(preset.name, [])
                self.assertEqual(errors, expected, f"{preset.name} regressed: {errors}")


class TestRoutingRunRejection(unittest.TestCase):
    """Raw executions and derived report arms are distinct by schema."""

    def setUp(self) -> None:
        self.schema = _schema("routing-run")
        self.valid = _load_json(FIXTURE_DIR / "example-routing-run.json")

    def test_derived_arms_are_unrepresentable_as_executions(self) -> None:
        # The four derived arms never execute; a record claiming one
        # would be a fabrication and must not validate.
        for fake in ("always_best", "always_cheapest", "oracle", "oracle_budget"):
            with self.subTest(mode=fake):
                record = dict(self.valid)
                record["mode"] = fake
                self.assertTrue(validate(record, self.schema))

    def test_profile_sweep_requires_its_profile(self) -> None:
        record = dict(self.valid)
        record["mode"] = "profile_sweep"  # profile_id still null
        self.assertTrue(validate(record, self.schema))
        record["profile_id"] = "anthropic-sonnet"
        self.assertEqual(validate(record, self.schema), [])

    def test_cct_router_fixes_no_profile(self) -> None:
        record = dict(self.valid)
        record["profile_id"] = "anthropic-sonnet"  # mode stays cct_router
        self.assertTrue(validate(record, self.schema))

    def test_cost_provenance_pairings_are_enforced(self) -> None:
        bad_costs = {
            "measured with estimator": {
                "value": 1.0, "provenance": "measured",
                "estimator": "price-table-v1", "inputs": None,
            },
            "estimated without estimator": {
                "value": 1.0, "provenance": "estimated", "estimator": None, "inputs": None,
            },
            "unavailable with value": {
                "value": 0.0, "provenance": "unavailable", "estimator": None, "inputs": None,
            },
            "measured with null value": {
                "value": None, "provenance": "measured", "estimator": None, "inputs": None,
            },
        }
        for label, cost in bad_costs.items():
            with self.subTest(case=label):
                record = dict(self.valid)
                record["cost"] = cost
                self.assertTrue(validate(record, self.schema))

    def test_estimated_cost_inputs_shape_is_pinned_by_schema(self) -> None:
        # The owner's reproduction: inputs {"input": {"tokens": 1}} was
        # schema-valid for an estimated record. $defs/estimate_inputs
        # now closes the shape: both required buckets, each pairing
        # tokens with rate_per_million.
        record = json.loads(json.dumps(self.valid))
        record["cost"] = {
            "value": 1.0, "provenance": "estimated",
            "estimator": "price-table-v1", "inputs": {"input": {"tokens": 1}},
        }
        self.assertTrue(validate(record, self.schema))
        record["cost"]["inputs"] = {
            "input": {"tokens": 1000, "rate_per_million": 3.0},
            "output": {"tokens": 500, "rate_per_million": 15.0},
        }
        self.assertEqual(validate(record, self.schema), [])

    def test_verifier_without_evidence_is_rejected(self) -> None:
        record = dict(self.valid)
        record["verifiers"] = [{"command": "pytest -q", "exit_status": 0}]
        self.assertTrue(validate(record, self.schema))

    def test_minimal_record_without_evidence_containers_is_rejected(self) -> None:
        # Missing evidence must be explicit (empty array / nulls / an
        # insufficient_evidence entry), never an absent key — an absent
        # key is indistinguishable from an incomplete writer.
        minimal = {
            k: self.valid[k]
            for k in (
                "schema_version", "registry_digest", "preset_digest",
                "task_set_revision", "toolchain_digest", "task_id",
                "trial", "mode", "profile_id", "tokens", "cost",
            )
        }
        errors = validate(minimal, self.schema)
        self.assertTrue(errors, "identity+tokens+cost alone validated")
        for container in ("injected_events", "routing_decisions", "verifiers",
                          "tier2", "insufficient_evidence"):
            with self.subTest(container=container):
                self.assertTrue(any(container in e for e in errors))

    def test_hollow_evidence_containers_are_rejected(self) -> None:
        # The owner's reproduction: required containers filled with
        # empty objects validated. Each hollow shape must now fail.
        hollow = {
            "injected_events as [{}]": ("injected_events", [{}]),
            "rollbacks as [{}]": ("rollbacks", [{}]),
            "empty baseline": ("baseline", {}),
            "empty quality_gates": ("quality_gates", {}),
            "empty tier2": ("tier2", {}),
            "empty insufficient_evidence": ("insufficient_evidence", {}),
        }
        for label, (key, value) in hollow.items():
            with self.subTest(case=label):
                record = json.loads(json.dumps(self.valid))
                record[key] = value
                self.assertTrue(validate(record, self.schema), f"{label} validated")

    def test_hollow_considered_candidate_is_rejected(self) -> None:
        record = json.loads(json.dumps(self.valid))
        record["routing_decisions"][0]["considered"] = [{}]
        self.assertTrue(validate(record, self.schema))

    def test_insufficient_evidence_entries_require_a_reason(self) -> None:
        record = json.loads(json.dumps(self.valid))
        record["insufficient_evidence"] = {"cost": {}}
        self.assertTrue(validate(record, self.schema))
        record["insufficient_evidence"] = {"cost": {"reason": "no measured total_cost_usd"}}
        self.assertEqual(validate(record, self.schema), [])

    def test_routing_decision_requires_its_full_vocabulary(self) -> None:
        # FR-E1-10 promises provisional/reconciliation outcome per
        # decision; a decision omitting it (or any promised field) fails.
        record = json.loads(json.dumps(self.valid))
        del record["routing_decisions"][0]["provisional_outcome"]
        self.assertTrue(validate(record, self.schema))
        record2 = json.loads(json.dumps(self.valid))
        del record2["routing_decisions"][0]["effective_model"]
        self.assertTrue(validate(record2, self.schema))


class TestOutcomeMatrixRejection(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = _schema("outcome-matrix")
        self.valid = _load_json(FIXTURE_DIR / "example-outcome-matrix.json")

    def test_empty_fingerprint_is_rejected(self) -> None:
        matrix = dict(self.valid)
        matrix["fingerprint"] = {}
        self.assertTrue(validate(matrix, self.schema))

    def test_missing_any_fingerprint_component_is_rejected(self) -> None:
        for omitted in (
            "registry_digest", "preset_digest", "execution_identity",
            "task_set_revision", "toolchain_digest",
        ):
            with self.subTest(omitted=omitted):
                matrix = json.loads(json.dumps(self.valid))
                del matrix["fingerprint"][omitted]
                self.assertTrue(validate(matrix, self.schema))

    def test_matrix_requires_seeds_and_cost_basis(self) -> None:
        for omitted in ("trial_seeds", "cost_basis"):
            with self.subTest(omitted=omitted):
                matrix = dict(self.valid)
                del matrix[omitted]
                self.assertTrue(validate(matrix, self.schema))

    def test_empty_cell_is_rejected(self) -> None:
        matrix = dict(self.valid)
        matrix["cells"] = [{}]
        self.assertTrue(validate(matrix, self.schema))

    def test_incomplete_execution_identity_is_rejected(self) -> None:
        matrix = json.loads(json.dumps(self.valid))
        del matrix["fingerprint"]["execution_identity"][0]["tool_profile"]
        self.assertTrue(validate(matrix, self.schema))

    def test_estimated_cell_must_name_its_price_table(self) -> None:
        # A matrix declaring cost_basis estimated@v1 must be able to
        # PROVE its cells came from v1 — a versionless estimated cell
        # cannot, and is rejected.
        matrix = json.loads(json.dumps(self.valid))
        matrix["cells"][0]["cost"] = {
            "value": 1.0, "provenance": "estimated", "estimator": None,
        }
        self.assertTrue(validate(matrix, self.schema))
        matrix["cells"][0]["cost"]["estimator"] = "price-table-v1"
        self.assertEqual(validate(matrix, self.schema), [])

    def test_measured_cell_with_estimator_is_rejected(self) -> None:
        matrix = json.loads(json.dumps(self.valid))
        matrix["cells"][0]["cost"]["estimator"] = "price-table-v1"
        self.assertTrue(validate(matrix, self.schema))

    def test_sequence_dependent_measures_have_no_cell_slot(self) -> None:
        # Derived arms must report these not_applicable; a slot would
        # invite a derived arm to appear to have one. additionalProperties
        # is false, so smuggling one in must fail.
        matrix = json.loads(json.dumps(self.valid))
        matrix["cells"][0]["tier2"] = {"delegated": True}
        self.assertTrue(validate(matrix, self.schema))


class TestMetricContractCoverage(unittest.TestCase):
    """Every § Metric contract row has a real source field."""

    def setUp(self) -> None:
        self.routing_run = _schema("routing-run")
        self.matrix = _schema("outcome-matrix")
        self.score = _schema("score")
        self.stats = _schema("stats")

    def _props(self, schema: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
        node: Any = schema
        for key in path:
            node = (node.get("properties") or {}).get(key)
            if not isinstance(node, Mapping):
                return {}
        return node

    def test_row1_verifier_outcome_from_score(self) -> None:
        self.assertIn("result", self.score.get("properties", {}))

    def test_rows2_3_regressions_have_baselines(self) -> None:
        baseline = self._props(self.routing_run, "baseline")
        for field in ("lint_passed", "typecheck_passed"):
            with self.subTest(field=field):
                self.assertIn(field, baseline.get("properties", {}))

    def test_rows4_5_coverage_and_security_gates_exist(self) -> None:
        gates = self._props(self.routing_run, "quality_gates")
        coverage = (gates.get("properties") or {}).get("coverage", {})
        for field in ("before", "after"):
            with self.subTest(gate="coverage", field=field):
                self.assertIn(field, (coverage.get("properties") or {}))
        security = (gates.get("properties") or {}).get("security", {})
        findings = (security.get("properties") or {}).get("findings_by_severity", {})
        for field in ("before", "after"):
            with self.subTest(gate="security", field=field):
                self.assertIn(field, (findings.get("properties") or {}))

    def test_row6_scope_violations_exist(self) -> None:
        self.assertIn("scope_violations", self.routing_run.get("properties", {}))

    def test_row7_repair_cycles_carry_signatures(self) -> None:
        item = (self.routing_run.get("$defs") or {}).get("repair_cycle", {})
        self.assertIn("signature", item.get("required", []))

    def test_row8_interventions_are_records_not_a_count(self) -> None:
        interventions = self._props(self.routing_run, "interventions")
        self.assertEqual(interventions.get("type"), "array")

    def test_verifier_evidence_is_required_and_addressable(self) -> None:
        item = (self.routing_run.get("$defs") or {}).get("verifier_execution", {})
        self.assertIn("evidence_ref", item.get("required", []))
        self.assertEqual(item["properties"]["evidence_ref"]["type"], "string")

    def test_rows9_10_tier2_ratio_has_numerator_and_denominator(self) -> None:
        tier2 = self._props(self.routing_run, "tier2")
        props = tier2.get("properties", {})
        self.assertIn("delegated_lines", props, "rework ratio has no denominator")
        self.assertIn("reconciliation_diff_lines", props, "rework ratio has no numerator")

    def test_row11_rollbacks_exist(self) -> None:
        self.assertIn("rollbacks", self.routing_run.get("properties", {}))

    def test_row12_cost_carries_provenance(self) -> None:
        cost = self._props(self.routing_run, "cost")
        provenance = (cost.get("properties") or {}).get("provenance", {})
        self.assertEqual(
            sorted(provenance.get("enum", [])), ["estimated", "measured", "unavailable"]
        )

    def test_row13_elapsed_from_stats(self) -> None:
        self.assertIn("elapsed_seconds", self.stats.get("properties", {}))


class TestPriceTable(unittest.TestCase):
    def setUp(self) -> None:
        self.table = _load_json(REPO_ROOT / "benchmarks" / "pricing" / "price-table-v1.json")

    def test_declares_its_version(self) -> None:
        self.assertEqual(self.table.get("version"), "price-table-v1")

    def test_ships_no_usable_default_rate(self) -> None:
        default = (self.table.get("rates") or {}).get("_default", {})
        for kind in ("input", "output", "cache_read", "cache_write"):
            with self.subTest(kind=kind):
                self.assertIsNone(default.get(kind))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
