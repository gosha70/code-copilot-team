#!/usr/bin/env bash
# test-llm-compat.sh — compatibility of catalog targets (#400 FR-13, FR-14,
# FR-16, FR-28; slice S2): the rule table and its pin, every state from
# fixtures, degradation by each part of the evidence digest, the two-part
# records, a malformed record refused by name, `cct llm compatibility` and
# doctor's LLM catalog section.
#
# A stub `claude` reports the harness version; nothing reaches a network.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
CCT="$REPO_DIR/scripts/cct"
RULES="$REPO_DIR/shared/llm/compat-rules.json"
SCHEMA="$REPO_DIR/shared/schemas/llm-catalog-cli.schema.json"
# Bump both when the table changes: a changed table must change rule_version.
RULES_VERSION_PIN=2
RULES_SHA_PIN="d01a1280a47104be638820fcfa150ad4e2d57f12306ed3c1fd4d90ab133e7b3c"

PASS=0; FAIL=0; SKIPPED=0
assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected '$expected', got '$actual')"; fi
}
assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected to contain '$needle')"; printf '%s\n' "$haystack" | sed 's/^/        | /' | head -8; fi
}
assert_not_contains() {
    local name="$1" haystack="$2" needle="$3"
    if printf '%s' "$haystack" | grep -qF -- "$needle"; then FAIL=$((FAIL+1)); echo "  FAIL: $name (must not contain '$needle')";
    else PASS=$((PASS+1)); echo "  PASS: $name"; fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

SECRET="planted-credential-value-do-not-print"
PATH_TOKEN="tenant-path-token-7c1a"
HOME_DIR="$TMP/home"
mkdir -p "$HOME_DIR/.cct" "$TMP/bin" "$TMP/tools"
echo "2.1.331 (Claude Code)" > "$TMP/claude-version"
printf '#!/bin/sh\ncat "%s"\n' "$TMP/claude-version" > "$TMP/bin/claude"
chmod +x "$TMP/bin/claude"

# A PATH with no claude on it, for "not installed": every entry holding one
# is dropped, and jq is linked in case it shared such a directory.
NOCLAUDE_PATH="$TMP/tools"
IFS=: read -r -a PARTS <<< "$PATH"
for d in "${PARTS[@]}"; do [[ -x "$d/claude" ]] || NOCLAUDE_PATH="$NOCLAUDE_PATH:$d"; done
ln -s "$(command -v jq)" "$TMP/tools/jq"

catalog() {  # [extra lines for the end of binding b]
    cat <<EOF
schema_version = 1

[providers.p]
display_name = "Provider P"
kind = "api"
credential_mode = "env"
credential_env = "TEST_LLM_KEY"

[providers.native]
kind = "managed"
credential_mode = "native"

[endpoints.e]
provider = "p"
protocol = "anthropic-messages"
base_url = "https://llm.example/${E_PATH:-$PATH_TOKEN}/v1"
auth_header = "bearer"

[endpoints.chat]
provider = "p"
protocol = "openai-chat"
base_url = "https://chat.example/v1"
auth_header = "bearer"

[llms.m]
provider = "p"
model = "model-one"

[llms.r]
provider = "p"
model = "model-r"
reasoning = true

[llms.own]
provider = "native"
model = "opus"

[llms.c]
provider = "p"
model = "model-c"

[llms.f]
provider = "p"
model = "model-f"

[llms.u]
provider = "p"
model = "model-u"

[bindings.rb]
harness = "claude-code"
llm = "r"
endpoint = "e"

[bindings.own-b]
harness = "claude-code"
llm = "own"

[bindings.cb]
harness = "claude-code"
llm = "c"
endpoint = "chat"

[bindings.fb]
harness = "claude-code"
llm = "f"
endpoint = "e"

[bindings.ub]
harness = "claude-code"
llm = "u"
endpoint = "e"

[bindings.b]
harness = "claude-code"
llm = "m"
endpoint = "e"
${1:-}
EOF
}
catalog > "$HOME_DIR/.cct/llms.toml"

cctx() { env -i HOME="$HOME_DIR" PATH="$TMP/bin:$PATH" TEST_LLM_KEY="$SECRET" ${RULES_OVERRIDE:+CCT_LLM_RULES_FILE="$RULES_OVERRIDE"} "$@"; }
compat() { cctx bash "$CCT" llm compatibility "$@"; }
field() { jq -r --arg t "$1" ".targets[] | select(.target == \$t) | $2"; }
record() {  # <llm> <binding> <attempt-json>: the probe's writer
    cctx bash -c '
        source "$1/scripts/lib/llm-catalog.sh"; source "$1/scripts/lib/llm-adapters/claude-code.sh"
        source "$1/scripts/lib/llm-resolve.sh"; source "$1/scripts/lib/cct-statefile.sh"
        source "$1/scripts/lib/llm-compat.sh"
        lcm_record_attempt claude-code "$2" "$3" "$4" || { echo "$LCM_ERR"; exit 1; }
    ' _ "$REPO_DIR" "$1" "$2" "$3"
}
attempt() {  # <outcome> <matrix-json> <evidence-json> [at]
    jq -nc --arg o "$1" --argjson m "$2" --argjson e "$3" --arg at "${4:-2026-11-23T20:00:00Z}" \
        '{at: $at, outcome: $o, matrix: $m, evidence: $e, detail: null}'
}
evidence_of() { compat "$1" --json | jq -c '.targets[0].evidence'; }
MATRIX='{"auth":"pass","model_identity":"pass","streaming":"pass","system_prompt":"pass","tool_call":"pass","tool_result":"pass","output_parsing":"pass","clean_exit":"pass","limit_controls":"not_applicable"}'
REC_DIR="$HOME_DIR/.cct/llm-compat/claude-code"
mode_of() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }

echo "=== compatibility (S2) ==="

# ── the rule table (FR-14) ──
# shellcheck source=/dev/null
source "$REPO_DIR/scripts/lib/llm-catalog.sh"
# shellcheck source=/dev/null
source "$REPO_DIR/scripts/lib/llm-adapters/claude-code.sh"
assert_eq "rules: the table is version $RULES_VERSION_PIN" "$RULES_VERSION_PIN" "$(jq -r .rule_version "$RULES")"
assert_eq "rules: its content is pinned to that version (bump both together)" "$RULES_SHA_PIN" \
    "$(jq -cS 'del(.rule_version)' "$RULES" | { command -v shasum >/dev/null && shasum -a 256 || sha256sum; } | cut -d' ' -f1)"
assert_eq "rules: Claude Code speaks the protocol its adapter speaks" "$LLM_CC_PROTOCOL" \
    "$(jq -r '.harnesses["claude-code"].protocols | join(" ")' "$RULES")"
assert_eq "rules: Claude Code honours every quirk the catalog accepts" "$LC_QUIRKS" \
    "$(jq -r '.harnesses["claude-code"].quirks | join(" ")' "$RULES")"
assert_eq "rules: Claude Code may use a managed provider's own login (departure 3)" "true" \
    "$(jq -r '.harnesses["claude-code"].managed' "$RULES")"
# FR-20: the version the #399 work pinned, from which Claude Code retries a
# request without tool search after a 400 or 422 (its MCP documentation).
assert_eq "rules: Claude Code's minimum is the #399 retry's version (FR-20)" "2.1.305" \
    "$(jq -r '.harnesses["claude-code"].min_version' "$RULES")"
assert_eq "rules: Codex speaks openai-responses only (S0's capture)" "openai-responses" \
    "$(jq -r '.harnesses.codex.protocols | join(" ")' "$RULES")"
assert_eq "rules: Pi speaks all three protocols (S0's capture)" "anthropic-messages openai-chat openai-responses" \
    "$(jq -r '.harnesses.pi.protocols | sort | join(" ")' "$RULES")"
assert_eq "rules: Kiro reaches only its own managed models" "0:true" \
    "$(jq -r '"\(.harnesses.kiro.protocols | length):\(.harnesses.kiro.managed)"' "$RULES")"
assert_eq "rules: every protocol named is one the catalog accepts" "" \
    "$(jq -r '[.harnesses[].protocols[]] | unique | .[]' "$RULES" | grep -vxF -f <(tr ' ' '\n' <<< "$LC_PROTOCOLS") || true)"
assert_eq "rules: every required capability is one the table defines" "[]" \
    "$(jq -c '.capabilities as $c | [.harnesses[] | (.required + .conditional)[] | select(IN($c[]) | not)] | unique' "$RULES")"
assert_eq "rules: every min_version is unset or a dotted version" "[]" \
    "$(jq -c '[.harnesses | to_entries[] | select(.value.min_version != null and ((.value.min_version | tostring) | test("^[0-9]+(\\.[0-9]+)*$") | not)) | .key]' "$RULES")"

# ── static states (FR-13) ──
OUT=$(compat --json); RC=$?
assert_eq "compatibility exits 0" "0" "$RC"
assert_eq "never tested: unverified" "unverified|never tested" "$(field m '"\(.state)|\(.reason)"' <<< "$OUT")"
assert_eq "...with the current evidence: harness version and rule version" "2.1.331|$RULES_VERSION_PIN" \
    "$(field m '"\(.evidence.harness_version)|\(.evidence.rule_version)"' <<< "$OUT")"
assert_eq "an endpoint speaking another protocol: unsupported, with the launch's reason" \
    "unsupported|endpoint 'chat' speaks openai-chat, claude-code speaks anthropic-messages" \
    "$(field c '"\(.state)|\(.reason)"' <<< "$OUT")"
assert_eq "a managed provider's own login is reachable: unverified" "unverified" "$(field own .state <<< "$OUT")"
OUT=$(env -i HOME="$HOME_DIR" PATH="$TMP/bin:$PATH" bash "$CCT" llm compatibility m --json)
assert_eq "an unset credential: unavailable" "unavailable|credential variable TEST_LLM_KEY is not set" \
    "$(field m '"\(.state)|\(.reason)"' <<< "$OUT")"
OUT=$(env -i HOME="$HOME_DIR" PATH="$NOCLAUDE_PATH" TEST_LLM_KEY="$SECRET" bash "$CCT" llm compatibility m --json)
assert_eq "claude not installed: unavailable" "unavailable|claude is not installed (not found on PATH)" \
    "$(field m '"\(.state)|\(.reason)"' <<< "$OUT")"
assert_eq "...and no evidence" "null" "$(field m .evidence <<< "$OUT")"
jq '.harnesses["claude-code"].min_version = "2.1.400"' "$RULES" > "$TMP/rules-min.json"
OUT=$(RULES_OVERRIDE="$TMP/rules-min.json" compat m --json)
assert_eq "claude older than the table's minimum: unavailable" \
    "unavailable|claude 2.1.331 is older than 2.1.400, the oldest version claude-code supports" \
    "$(field m '"\(.state)|\(.reason)"' <<< "$OUT")"

# ── the evidence (FR-9): computed with its own digests, never keyed on none ──
EVID=$(env -i HOME="$HOME_DIR" PATH="$TMP/bin:$PATH" TEST_LLM_KEY="$SECRET" bash -c '
    for l in llm-catalog llm-adapters/claude-code llm-resolve cct-statefile llm-compat; do source "$1/scripts/lib/$l.sh"; done
    lc_validate "$(lc_catalog_path)" >/dev/null && lr_resolve claude-code m || exit 1
    ok=no
    if lcm_evidence 2.1.331 && jq -e "[.launch_identity, .options, .digest] | all(test(\"^[0-9a-f]{64}$\"))" >/dev/null <<< "$LCM_EVIDENCE"; then ok=yes; fi
    lr_resolve pi m; rc=0; lcm_evidence 2.1.331 || rc=$?
    printf "%s|%s|%s" "$ok" "$rc" "$LCM_EVIDENCE"' _ "$REPO_DIR")
assert_eq "evidence: a fresh resolution gets its digests computed; no binding, no evidence" "yes|1|null" "$EVID"
EVID=$(env -i HOME="$HOME_DIR" PATH="$TMP/bin:$PATH" bash -c '
    set -u
    for l in llm-catalog llm-adapters/claude-code llm-resolve cct-statefile llm-compat; do source "$1/scripts/lib/$l.sh"; done
    LCM_EVIDENCE="{\"stale\": true}"; rc=0; lcm_evidence 2.1.331 || rc=$?
    printf "%s|%s|%s" "$rc" "$LCM_EVIDENCE" "$LCM_ERR"' _ "$REPO_DIR" 2>&1)
assert_eq "evidence: called before any resolution, under set -u, it refuses and leaves no stale evidence" \
    "1|null|no evidence: no target was resolved" "$EVID"

# ── records (FR-16) and the conclusive states ──
EV_M=$(evidence_of m)
OUT=$(record m b "$(attempt pass "$MATRIX" "$EV_M")"); assert_eq "the probe's writer records a pass" "" "$OUT"
OUT=$(compat --json)
assert_eq "a passing test under the current evidence: supported" "supported|passed its test of 2026-11-23T20:00:00Z" \
    "$(field m '"\(.state)|\(.reason)"' <<< "$OUT")"
assert_eq "...a not_applicable capability never blocks" "not_applicable" \
    "$(jq -r '.latest_conclusive.matrix.limit_controls' "$REC_DIR/m@b.json")"
assert_eq "...the record is 0600 in a 0700 directory" "600:700" "$(mode_of "$REC_DIR/m@b.json"):$(mode_of "$REC_DIR")"
assert_eq "...and both parts show the pass" "pass|pass" "$(field m '"\(.latest_attempt.outcome)|\(.latest_conclusive.outcome)"' <<< "$OUT")"
record m b "$(attempt unverifiable '{"auth":"pass","streaming":"unverifiable"}' "$EV_M" 2026-11-23T21:00:00Z)" >/dev/null
OUT=$(compat m --json)
assert_eq "an unverifiable test later leaves the conclusive pass: still supported" "supported" "$(field m .state <<< "$OUT")"
assert_eq "...and is the latest attempt" "unverifiable|2026-11-23T21:00:00Z|pass" \
    "$(field m '"\(.latest_attempt.outcome)|\(.latest_attempt.at)|\(.latest_conclusive.outcome)"' <<< "$OUT")"

record r rb "$(attempt pass "$MATRIX" "$(evidence_of r)")" >/dev/null
assert_contains "an llm declaring reasoning needs reasoning_control to pass" \
    "$(compat r --json | field r '"\(.state)|\(.reason)"')" "unverified|the test of 2026-11-23T20:00:00Z passed, but not every capability this binding needs: reasoning_control"
record r rb "$(attempt pass "$(jq -c '. + {reasoning_control: "pass"}' <<< "$MATRIX")" "$(evidence_of r)")" >/dev/null
assert_eq "...and is supported once it has" "supported" "$(compat r --json | field r .state)"
record own own-b "$(attempt pass "$(jq -c '.tool_result = "unverifiable"' <<< "$MATRIX")" "$(evidence_of own)")" >/dev/null
OUT=$(compat own --json)
assert_eq "a pass with a required capability unverifiable is not supported" "unverified" "$(field own .state <<< "$OUT")"
assert_contains "...the reason names it" "$(field own .reason <<< "$OUT")" ": tool_result"
record f fb "$(attempt fail "$(jq -c '.tool_call = "fail"' <<< "$MATRIX")" "$(evidence_of f)")" >/dev/null
assert_eq "a behavioral failure under the current evidence: incompatible" \
    "incompatible|failed its test of 2026-11-23T20:00:00Z: tool_call" "$(compat f --json | field f '"\(.state)|\(.reason)"')"
record u ub "$(attempt unverifiable '{"auth":"pass","clean_exit":"unverifiable"}' "$(evidence_of u)")" >/dev/null
assert_eq "only an unverifiable test: unverified, saying so" \
    "unverified|never tested conclusively: the last test, 2026-11-23T20:00:00Z, was unverifiable" \
    "$(compat u --json | field u '"\(.state)|\(.reason)"')"
assert_eq "...and no conclusive part" "null" "$(jq -c .latest_conclusive "$REC_DIR/u@ub.json")"
# A refused credential is unavailable evidence (FR-13): recorded as the
# latest attempt, never conclusive, and the reason carries its detail.
record u ub "$(jq -nc --argjson e "$(evidence_of u)" '{at: "2026-11-23T22:00:00Z", outcome: "unavailable",
    matrix: {auth: "fail"}, evidence: $e, detail: "the endpoint refused the credential (HTTP 401)", redacted: "Not logged in"}')" >/dev/null
assert_eq "a refused credential: recorded, never conclusive, and the reason says what the test saw" \
    "unverified|never tested conclusively: the last test, 2026-11-23T22:00:00Z, was unavailable (the endpoint refused the credential (HTTP 401))|null" \
    "$(compat u --json | field u '"\(.state)|\(.reason)"')|$(jq -c .latest_conclusive "$REC_DIR/u@ub.json")"

# ── degradation by each part of the evidence digest ──
# The owner's ruling of 2026-11-26 (FR-13's amendment, S3): a passing test
# still stands on a newer claude, and says so; any other change degrades it.
echo "2.1.400 (Claude Code)" > "$TMP/claude-version"
OUT=$(compat m --json)
assert_eq "a newer claude keeps a passing test supported, the change still shown (the owner's ruling)" \
    "supported|[\"harness_version\"]" "$(field m '"\(.state)|\(.degraded | tojson)"' <<< "$OUT")"
assert_contains "...saying it passed on the older one, and the newer one is untested" "$(field m .reason <<< "$OUT")" \
    "passed its test of 2026-11-23T20:00:00Z on claude 2.1.331; claude is now 2.1.400, which has not been tested"
assert_eq "a failed test on an older claude is unverified, never supported" "unverified" "$(compat f --json | field f .state)"
catalog 'max_output_tokens = 4096' > "$HOME_DIR/.cct/llms.toml"
assert_eq "a newer claude does not let a changed tuning option through" "unverified|[\"options\",\"harness_version\"]" \
    "$(compat m --json | field m '"\(.state)|\(.degraded | tojson)"')"
catalog > "$HOME_DIR/.cct/llms.toml"
echo "2.1.330 (Claude Code)" > "$TMP/claude-version"
OUT=$(compat m --json)
assert_eq "an older claude than the test's degrades it" "unverified|[\"harness_version\"]" "$(field m '"\(.state)|\(.degraded | tojson)"' <<< "$OUT")"
assert_contains "...saying what changed" "$(field m .reason <<< "$OUT")" "no longer applies: claude 2.1.331 is now 2.1.330"
echo "Claude Code (development build)" > "$TMP/claude-version"
assert_eq "a claude whose version cannot be read degrades it: versions that cannot be compared never pass" \
    "unverified" "$(compat m --json | field m .state)"
echo "2.1.331 (Claude Code)" > "$TMP/claude-version"
jq '.rule_version += 1' "$RULES" > "$TMP/rules-next.json"
OUT=$(RULES_OVERRIDE="$TMP/rules-next.json" compat m --json)
assert_eq "a new rule version degrades it" "unverified|[\"rule_version\"]" "$(field m '"\(.state)|\(.degraded | tojson)"' <<< "$OUT")"
assert_contains "...saying so" "$(field m .reason <<< "$OUT")" "rule version $RULES_VERSION_PIN is now $((RULES_VERSION_PIN + 1))"
catalog 'max_output_tokens = 4096' > "$HOME_DIR/.cct/llms.toml"
OUT=$(compat m --json)
assert_eq "a changed tuning option degrades it" "unverified|[\"options\"]" "$(field m '"\(.state)|\(.degraded | tojson)"' <<< "$OUT")"
E_PATH="another-tenant" catalog > "$HOME_DIR/.cct/llms.toml"
OUT=$(compat m --json)
assert_eq "another endpoint path degrades it" "unverified|[\"launch_identity\"]" "$(field m '"\(.state)|\(.degraded | tojson)"' <<< "$OUT")"
assert_contains "...saying the launch identity changed" "$(field m .reason <<< "$OUT")" "the launch identity changed"
catalog | sed 's/display_name = "Provider P"/display_name = "Renamed"/' > "$HOME_DIR/.cct/llms.toml"
assert_eq "a display-name edit leaves it supported" "supported" "$(compat m --json | field m .state)"
catalog > "$HOME_DIR/.cct/llms.toml"

# ── a record that cannot be used is refused by name (FR-29) ──
cp "$REC_DIR/m@b.json" "$TMP/m-good.json"
echo '{"schema_version": 1, "harness": "claude-code"' > "$REC_DIR/m@b.json"
OUT=$(compat --json 2>"$TMP/err"); RC=$?
assert_eq "a malformed record: compatibility exits 2" "2" "$RC"
assert_contains "...naming the file" "$(cat "$TMP/err")" "the record $REC_DIR/m@b.json is malformed"
assert_eq "...the target is unverified, the record unused" "unverified" "$(field m .state <<< "$OUT")"
assert_eq "...the other targets are still computed" "supported" "$(field r .state <<< "$OUT")"
OUT=$(record m b "$(attempt pass "$MATRIX" "$EV_M")")
assert_contains "the writer refuses to update a malformed record" "$OUT" "is malformed; not updated"
assert_eq "...and leaves it as it was" '{"schema_version": 1, "harness": "claude-code"' "$(cat "$REC_DIR/m@b.json")"
OUT=$(record m b '{"outcome": "pass"}')
assert_contains "the writer refuses something that is not a probe attempt" "$OUT" "not a probe attempt"
rm -f "$REC_DIR/m@b.json"; ln -s "$TMP/m-good.json" "$REC_DIR/m@b.json"
compat m >/dev/null 2>"$TMP/err"; RC=$?
assert_eq "a symlinked record is refused (exit 2)" "2" "$RC"
assert_contains "...by name" "$(cat "$TMP/err")" "cannot read the record $REC_DIR/m@b.json"
rm -f "$REC_DIR/m@b.json"; cp "$TMP/m-good.json" "$REC_DIR/m@b.json"; chmod 600 "$REC_DIR/m@b.json"

# ── the command ──
TEXT=$(compat); RC=$?
assert_eq "text: exits 0" "0" "$RC"
assert_contains "text: a row per binding, with the state and why" "$TEXT" "m       claude-code  supported     passed its test of 2026-11-23T20:00:00Z"
assert_contains "text: names the rule version and the harness version" "$TEXT" "Rule version $RULES_VERSION_PIN; claude 2.1.331."
JSON=$(compat --json)
assert_eq "json: one target per binding" "6" "$(jq '.targets | length' <<< "$JSON")"
for doc in "$TEXT" "$JSON"; do
    assert_not_contains "never the credential's value" "$doc" "$SECRET"
    assert_not_contains "never the endpoint's path" "$doc" "$PATH_TOKEN"
done
compat nope >/dev/null 2>"$TMP/err"; RC=$?
assert_eq "an unknown target is a usage error" "2" "$RC"
compat --harness vim >/dev/null 2>&1; RC=$?
assert_eq "an unknown harness is a usage error" "2" "$RC"
compat --harness= >/dev/null 2>&1; RC=$?
assert_eq "an empty --harness= is a usage error, as --harness '' is" "2" "$RC"
# --json when it cannot answer: the error envelope, one JSON document and
# nothing else (stdout and stderr together), and the text form's exit code.
lone() { printf '%s|%s|%s' "$RC" "$(jq -r '"\(.command)|\(.error)"' <<< "$OUT" 2>/dev/null)" "$(jq -s length <<< "$OUT" 2>/dev/null)"; }
OUT=$(compat nope --json 2>&1); RC=$?; ERR_TARGET="$OUT"
assert_eq "json: an unknown target, the error envelope alone" \
    "2|compatibility|unknown llm 'nope' (cct llm list shows the catalog)|1" "$(lone)"
echo 'not json' > "$TMP/rules-bad.json"
OUT=$(RULES_OVERRIDE="$TMP/rules-bad.json" compat --json 2>&1); RC=$?
assert_eq "json: a rule table that cannot be read, the error envelope alone" \
    "2|compatibility|cannot read the compatibility rule table: $TMP/rules-bad.json|1" "$(lone)"
assert_contains "a harness with no binding says so" "$(compat --harness codex)" "has no binding for codex"
assert_eq "one target" "1|m" "$(compat m --json | jq -r '"\(.targets | length)|\(.targets[0].target)"')"
assert_contains "cct help documents compatibility" "$(bash "$CCT" help 2>&1)" "cct llm compatibility [<target>]"

PY_SCHEMA=""
for py in python3 python3.13 python3.12 python3.11; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import jsonschema' >/dev/null 2>&1; then PY_SCHEMA="$py"; break; fi
done
if [[ -n "$PY_SCHEMA" ]]; then
    for doc in JSON ERR_TARGET; do
        if printf '%s' "${!doc}" | "$PY_SCHEMA" -c '
import json, sys, jsonschema
schema = json.load(open(sys.argv[1]))
jsonschema.Draft202012Validator.check_schema(schema)
jsonschema.Draft202012Validator(schema).validate(json.load(sys.stdin))' "$SCHEMA" >/dev/null 2>&1; then
            PASS=$((PASS+1)); echo "  PASS: schema: the $doc document"
        else FAIL=$((FAIL+1)); echo "  FAIL: schema: the $doc document does not match $SCHEMA"; fi
    done
else
    SKIPPED=2
    echo "  SKIP: jsonschema not installed — the two compatibility documents were not validated"
fi

# ── doctor's LLM catalog section (FR-28) ──
DOC=$(cctx bash "$CCT" doctor --no-network --json 2>/dev/null)
rows() { jq -r '.checks[] | select(.section == "LLM catalog") | "\(.check)=\(.status)"' <<< "$1" | paste -sd' ' -; }
assert_eq "doctor: the catalog, then one row per target" \
    "catalog=ok m on claude-code=ok r on claude-code=ok own on claude-code=warn c on claude-code=warn f on claude-code=warn u on claude-code=warn" \
    "$(rows "$DOC")"
assert_contains "doctor: a row gives the state and why" "$DOC" "incompatible: failed its test of 2026-11-23T20:00:00Z: tool_call"
echo 'not json' > "$REC_DIR/u@ub.json"
assert_contains "doctor: an unreadable record fails the section" "$(rows "$(cctx bash "$CCT" doctor --no-network --json 2>/dev/null)")" "test records=fail"
DOC=$(RULES_OVERRIDE="$TMP/rules-bad.json" cctx bash "$CCT" doctor --no-network --json 2>/dev/null)
assert_eq "doctor: a compatibility error fails the section with its message" \
    "catalog=ok compatibility=fail|cannot read the compatibility rule table: $TMP/rules-bad.json" \
    "$(rows "$DOC")|$(jq -r '.checks[] | select(.section == "LLM catalog" and .check == "compatibility") | .detail' <<< "$DOC")"
rm -f "$HOME_DIR/.cct/llms.toml"
OUT=$(compat --json 2>&1); RC=$?
assert_eq "json: no catalog, the error envelope alone" "2|compatibility|no LLM catalog|1" "$(lone)"
assert_eq "doctor: no catalog is skipped, not a failure" "catalog=skip" "$(rows "$(cctx bash "$CCT" doctor --no-network --json 2>/dev/null)")"

echo ""
echo "========================================="
echo "  llm-compat tests: $PASS passed, $FAIL failed$( [[ $SKIPPED -gt 0 ]] && echo ", $SKIPPED skipped (jsonschema not installed)")"
echo "========================================="
if [[ "$((PASS + SKIPPED))" -ne "${TEST_LLM_COMPAT_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_LLM_COMPAT_EXPECTED_PASS:-0}, got $PASS passed + $SKIPPED skipped)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
