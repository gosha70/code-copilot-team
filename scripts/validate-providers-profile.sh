#!/usr/bin/env bash
# validate-providers-profile.sh — check a provider profile against its schema
# (#214 Phase 2.3).
#
# Checks:
#   1. the file parses as TOML
#   2. every table and key is one the schema declares (a typo is an error,
#      not a silently ignored line)
#   3. types match (integer / number / boolean / string / array of strings)
#   4. api_key_env names a variable and never holds a key-shaped value
#   5. peer_for / fallback_chain targets resolve to declared providers
#   6. a value with a trailing inline comment is rejected: the profile parser
#      keeps everything after '=' , so `disable_thinking = true # why` fails
#      its exact comparison at run time
#
# Run from the repo root:
#   bash scripts/validate-providers-profile.sh [profile.toml] [schema.json]
#
# Defaults to ~/.code-copilot-team/providers.toml; the arguments exist so
# tests can run the same checks against fixtures.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="${1:-$HOME/.code-copilot-team/providers.toml}"
SCHEMA="${2:-$REPO_DIR/shared/schemas/providers.schema.json}"

[[ -f "$SCHEMA" ]] || { echo "[ERROR] schema not found: $SCHEMA"; exit 1; }
if [[ ! -f "$PROFILE" ]]; then
  echo "[SKIP] no provider profile at $PROFILE — nothing to validate."
  exit 0
fi

python3 - "$PROFILE" "$SCHEMA" <<'PY'
import json, re, sys

profile_path, schema_path = sys.argv[1], sys.argv[2]
try:
    import tomllib
except ModuleNotFoundError:  # python < 3.11
    print("[SKIP] tomllib not available (needs python 3.11+) — profile not validated.")
    sys.exit(0)

schema = json.load(open(schema_path))
defs = schema["$defs"]
prov_props = defs["provider"]["properties"]
required = defs["provider"].get("required", [])
types = defs["provider_type"]["enum"]

fails, passes = [], 0

def fail(msg):
    fails.append(msg)

try:
    with open(profile_path, "rb") as fh:
        doc = tomllib.load(fh)
except Exception as exc:                      # noqa: BLE001 - reported, not raised
    print(f"  FAIL: {profile_path} does not parse as TOML: {exc}")
    print("=" * 41)
    sys.exit(1)

# A trailing comment on a value line becomes part of the value for the shell
# parser the runner uses, so it is a defect here even though TOML allows it.
value_line = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*(.+?)\s*$")
for n, line in enumerate(open(profile_path, encoding="utf-8"), 1):
    m = value_line.match(line)
    if not m:
        continue
    raw = m.group(2)
    if raw.startswith(('"', "'", "[")):
        continue                               # quoted/array values may contain #
    if "#" in raw:
        fail(f"{profile_path}:{n}: `{m.group(1)}` has an inline comment; "
             "the profile parser keeps it as part of the value — move it to its own line")
    else:
        passes += 1

top_allowed = set(schema["properties"])
for key in doc:
    if key in top_allowed:
        passes += 1
    else:
        fail(f"unknown table [{key}] (allowed: {', '.join(sorted(top_allowed))})")

for key in doc.get("copyright", {}):
    if key in schema["properties"]["copyright"]["properties"]:
        passes += 1
    else:
        fail(f"unknown key [copyright].{key}")

providers = doc.get("providers", {})
for name, body in providers.items():
    if not isinstance(body, dict):
        fail(f"[providers.{name}] is not a table")
        continue
    for req in required:
        if req not in body:
            fail(f"[providers.{name}] is missing the required key `{req}`")
        else:
            passes += 1
    for key, value in body.items():
        spec = prov_props.get(key)
        if spec is None:
            fail(f"[providers.{name}] unknown key `{key}`")
            continue
        expected = spec.get("type")
        ok = True
        if key == "type":
            ok = value in types
            if not ok:
                fail(f"[providers.{name}] type `{value}` is not one of {'|'.join(types)}")
        elif expected == "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected == "boolean":
            ok = isinstance(value, bool)
        elif expected == "string":
            ok = isinstance(value, str)
        if not ok and key != "type":
            fail(f"[providers.{name}] `{key}` must be {expected}, got {type(value).__name__}")
        if ok:
            passes += 1
        if key == "api_key_env" and isinstance(value, str):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
                fail(f"[providers.{name}] api_key_env `{value}` is not a variable NAME")
            elif value.startswith(("sk-", "sk_")) or len(value) > 64:
                fail(f"[providers.{name}] api_key_env looks like a key, not a variable name")
            else:
                passes += 1
    if body.get("type") in ("cli", "custom") and not body.get("command"):
        fail(f"[providers.{name}] type {body['type']} needs a `command` template")
    if body.get("type") == "openai-compatible" and not body.get("base_url"):
        fail(f"[providers.{name}] type openai-compatible needs a `base_url`")
    for ck in ("command", "conformance_command"):
        if ck == "conformance_command" and ck in body and "{review_request}" not in body[ck]:
            fail(f"[providers.{name}] `{ck}` must carry the {{review_request}} placeholder")

for key, value in doc.get("defaults", {}).items():
    if key == "peer_for" and isinstance(value, dict):
        pairs = [(f"peer_for.{k}", v) for k, v in value.items()]
    elif key == "fallback_chain" and isinstance(value, dict):
        pairs = [(f"fallback_chain.{k}", v) for k, v in value.items()]
    else:
        pairs = [(key, value)]
    for flat, val in pairs:
        if flat.startswith("peer_for."):
            if not isinstance(val, str):
                fail(f"[defaults] {flat} must be a provider name")
            elif val not in providers:
                fail(f"[defaults] {flat} = `{val}` is not a declared provider")
            else:
                passes += 1
        elif flat.startswith("fallback_chain."):
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                fail(f"[defaults] {flat} must be an array of provider names")
            else:
                for v in val:
                    if v not in providers:
                        fail(f"[defaults] {flat} names `{v}`, which is not a declared provider")
                    else:
                        passes += 1
        else:
            fail(f"[defaults] unknown key `{flat}`")

for msg in fails:
    print(f"  FAIL: {msg}")
print("=" * 41)
print(f"  Provider profile: {passes} passed, {len(fails)} failed ({len(providers)} providers)")
print("=" * 41)
sys.exit(1 if fails else 0)
PY
