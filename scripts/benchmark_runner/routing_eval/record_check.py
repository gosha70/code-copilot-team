"""Executable record validation for routing-eval artifacts.

The schemas in benchmarks/schema are documentation-grade for the wider
harness, but routing-eval's contracts are load-bearing at RUNTIME: the
arc verifier must refuse a record the persisted contract rejects, or
"schema-valid evidence" is a property only the test suite enforces.
This module carries the validator for the subset E1's schemas use
($ref, oneOf, anyOf, not, const, enum, pattern, lengths,
additionalProperties-as-schema, minProperties) plus loaders pinned to
the shipped schema files.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = _REPO_ROOT / "benchmarks" / "schema"


def load_schema(name: str) -> Mapping[str, Any]:
    with (SCHEMA_DIR / f"{name}.schema.json").open(encoding="utf-8") as f:
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
    if type_decl in ("integer", "number"):
        if isinstance(value, bool):
            return False
        if not isinstance(value, _TYPE_MAP[type_decl]):
            return False
        # NaN and infinity are not JSON numbers, and NaN additionally
        # defeats every ordered comparison ("NaN < minimum" is false),
        # so a non-finite cost would slide past minimum checks and into
        # T5 selection. Reject them as type violations.
        return math.isfinite(float(value))
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


