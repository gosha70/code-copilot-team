#!/usr/bin/env bash
# test-llm-cli.sh — `cct llm show`, `cct harness explain` and `--json`
# (#400 slice S1): the LaunchPlan, its digests and the read-only views,
# all planned by the resolver the launcher uses.
#
# A planted credential value and a token planted in an endpoint's path
# must never appear in any output: a credential is its variable's NAME and
# whether it is set, an endpoint is its origin, and the path is bound only
# by the launch-identity digest.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
CCT="$REPO_DIR/scripts/cct"
PI_CODE="$REPO_DIR/adapters/pi/bin/pi-code"
SCHEMA="$REPO_DIR/shared/schemas/llm-catalog-cli.schema.json"

PASS=0; FAIL=0; SKIPPED=0
assert_exit() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$actual" -eq "$expected" ]]; then PASS=$((PASS+1)); echo "  PASS: $name (exit $actual)";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected exit $expected, got $actual)"; fi
}
assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -qF -- "$needle"; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected to contain '$needle')"; echo "$haystack" | sed 's/^/        | /' | head -8; fi
}
assert_not_contains() {
    local name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -qF -- "$needle"; then FAIL=$((FAIL+1)); echo "  FAIL: $name (must not contain '$needle')";
    else PASS=$((PASS+1)); echo "  PASS: $name"; fi
}
assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected '$expected', got '$actual')"; fi
}
assert_ne() {
    local name="$1" a="$2" b="$3"
    if [[ "$a" != "$b" ]]; then PASS=$((PASS+1)); echo "  PASS: $name";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (both are '$a')"; fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

SECRET="planted-credential-value-do-not-print"
PATH_TOKEN="tenant-path-token-9f3e"

catalog() {
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
base_url = "https://llm.example/$PATH_TOKEN/v1"
auth_header = "bearer"

[endpoints.e-env]
provider = "p"
protocol = "anthropic-messages"
base_url_env = "TEST_LLM_URL"
auth_header = "bearer"

[llms.m]
provider = "p"
model = "model-one"

[llms.m2]
provider = "p"
model = "model-two"

[llms.own]
provider = "native"
model = "opus"

[llms.lonely]
provider = "p"
model = "model-unbound"

[bindings.b]
harness = "claude-code"
llm = "m"
endpoint = "e"

[bindings.b2]
harness = "claude-code"
llm = "m2"
endpoint = "e-env"

[bindings.own-b]
harness = "claude-code"
llm = "own"
EOF
}

# home <name> [filter command ...]: a CCT home whose catalog is the fixture,
# passed through the filter when one is given
home() {
    local name="$1"; shift
    mkdir -p "$TMP/$name"
    if [[ $# -gt 0 ]]; then catalog | "$@" > "$TMP/$name/llms.toml"; else catalog > "$TMP/$name/llms.toml"; fi
    printf '%s' "$TMP/$name"
}
BASE_HOME=$(home base)

# cctx <home> [VAR=value ...] -- <cct args>: RC and OUT
cctx() {
    local h="$1" envs=(); shift
    while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
    shift
    RC=0
    # From a directory with no project file: explain reads the current
    # directory's project unless --project names one (S5).
    OUT=$(cd "${CLI_RUN_DIR:-$TMP}" && env -u CCT_HOME CCT_HOME="$h" TEST_LLM_KEY="$SECRET" TEST_LLM_URL="https://env.example/$PATH_TOKEN/v1" \
        ${envs[@]+"${envs[@]}"} bash "$CCT" "$@" 2>&1) || RC=$?
}
digests_of() {  # <home> <target> [VAR=value ...] -> "catalog launch options"
    local h="$1" t="$2"; shift 2
    cctx "$h" "$@" -- harness explain claude-code --llm "$t" --json
    jq -r '[.digests.catalog, .digests.launch_identity, .digests.options] | join(" ")' <<< "$OUT"
}
field() { cut -d' ' -f"$1" <<< "$2"; }

echo "=== cct llm show, cct harness explain, --json (#400 S1) ==="

# ── cct llm show ──
cctx "$BASE_HOME" -- llm show m
assert_exit "show: an llm" 0 "$RC"
assert_contains "show: the provider, by display name, id and kind" "$OUT" "provider  Provider P (p, api)"
assert_contains "show: the credential, by variable name and whether it is set" "$OUT" "TEST_LLM_KEY (set)"
assert_not_contains "show: never the credential's value" "$OUT" "$SECRET"
assert_not_contains "show: never the endpoint's path" "$OUT" "$PATH_TOKEN"
cctx "$BASE_HOME" -- llm show ghost
assert_exit "show: an unknown llm is a usage error" 2 "$RC"
cctx "$BASE_HOME" -- llm show m --json
assert_eq "show --json: the llm's model" "model-one" "$(jq -r .llm.model <<< "$OUT")"
assert_eq "show --json: a binding's endpoint is its origin" "https://llm.example" "$(jq -r '.bindings[0].endpoint' <<< "$OUT")"
cctx "$BASE_HOME" -- llm show lonely
assert_contains "show: an llm nothing binds says so" "$OUT" "bindings  none: add a [bindings.<id>] table for it"

# ── cct harness explain, as text ──
cctx "$BASE_HOME" -- harness explain claude-code --llm m
assert_exit "explain: a launchable target" 0 "$RC"
assert_contains "explain: a copied credential is named with its source variable" "$OUT" "ANTHROPIC_AUTH_TOKEN, from TEST_LLM_KEY (set)"
assert_contains "explain: the variables the launch removes, by name" "$OUT" "    ANTHROPIC_API_KEY"
assert_not_contains "explain: never the credential's value" "$OUT" "$SECRET"
assert_not_contains "explain: never the endpoint's path" "$OUT" "$PATH_TOKEN"
assert_eq "explain: the three digests, abbreviated" "1" \
    "$(grep -cE '^  digests   catalog [0-9a-f]{12}  launch identity [0-9a-f]{12}  options [0-9a-f]{12}$' <<< "$OUT")"
cctx "$BASE_HOME" TEST_LLM_KEY= -- harness explain claude-code --llm m
assert_exit "explain: a launch that would be refused exits 3" 3 "$RC"
assert_contains "explain: ...naming the unset credential" "$OUT" "TEST_LLM_KEY (not set)"
assert_contains "explain: ...and the state" "$OUT" "state     unavailable"

# ── refusals ──
cctx "$BASE_HOME" -- harness explain pi --llm m
assert_exit "explain: pi has no adapter yet" 3 "$RC"
assert_contains "explain: ...and says so" "$OUT" "adapter not implemented"
cctx "$BASE_HOME" -- harness explain codex --llm m
assert_exit "explain: codex has no adapter yet" 3 "$RC"
cctx "$BASE_HOME" -- harness explain kiro --llm m
assert_exit "explain: kiro has no adapter yet" 3 "$RC"
cctx "$BASE_HOME" -- harness explain vim --llm m
assert_exit "explain: an unknown harness is refused" 3 "$RC"
assert_contains "explain: ...by name" "$OUT" "unknown harness 'vim'"
cctx "$BASE_HOME" -- harness explain claude-code --llm ghost
assert_exit "explain: an unknown target is refused" 3 "$RC"
cctx "$BASE_HOME" -- harness explain
assert_exit "explain: no harness and no target is a usage error" 2 "$RC"
cctx "$BASE_HOME" -- harness bogus
assert_exit "cct harness: an unknown subcommand is a usage error" 2 "$RC"
mkdir -p "$TMP/pi-home"
PI_RC=0; PI_OUT=$(env -i HOME="$TMP/pi-home" PATH="/usr/bin:/bin" bash "$PI_CODE" --llm m 2>&1) || PI_RC=$?
assert_exit "pi-code --llm is refused until the Pi adapter lands" 3 "$PI_RC"
assert_contains "pi-code --llm: ...and says why" "$PI_OUT" "--llm is not implemented for pi-code yet"

# ── cct harness explain --json: the LaunchPlan ──
cctx "$BASE_HOME" -- harness explain claude-code --llm m --json
PLAN="$OUT"
assert_eq "plan: the endpoint is its origin" "https://llm.example" "$(jq -r .identity.endpoint <<< "$PLAN")"
assert_eq "plan: a copied credential carries its source variable and whether it is set" "TEST_LLM_KEY true" \
    "$(jq -r '.env_names[] | select(.name == "ANTHROPIC_AUTH_TOKEN") | "\(.from) \(.set)"' <<< "$PLAN")"
assert_eq "plan: each removed name appears once" "$(jq '.env_clear | length' <<< "$PLAN")" "$(jq '.env_clear | unique | length' <<< "$PLAN")"
assert_eq "plan: three sha256 digests" "3" "$(jq '[.digests[] | select(test("^[0-9a-f]{64}$"))] | length' <<< "$PLAN")"
assert_not_contains "plan: never the credential's value" "$PLAN" "$SECRET"
assert_not_contains "plan: never the endpoint's path" "$PLAN" "$PATH_TOKEN"
cctx "$BASE_HOME" -- harness explain claude-code --llm own --json
assert_eq "plan: a managed provider has no endpoint" "null managed" "$(jq -r '"\(.identity.endpoint) \(.identity.provider_kind)"' <<< "$OUT")"

# ── the digests ──
D1=$(digests_of "$BASE_HOME" m)
assert_eq "digests: stable across runs" "$D1" "$(digests_of "$BASE_HOME" m)"
D_NAME=$(digests_of "$(home renamed sed 's/^display_name = "Provider P"/display_name = "Renamed P"/')" m)
assert_ne "digests: a display-name edit changes the catalog digest" "$(field 1 "$D1")" "$(field 1 "$D_NAME")"
assert_eq "digests: ...and not the launch identity" "$(field 2 "$D1")" "$(field 2 "$D_NAME")"
D_PATH_HOME=$(home path sed "s#https://llm.example/$PATH_TOKEN/v1#https://llm.example/other-tenant/v1#")
D_PATH=$(digests_of "$D_PATH_HOME" m)
assert_ne "digests: another path behind the same origin changes the launch identity" "$(field 2 "$D1")" "$(field 2 "$D_PATH")"
cctx "$D_PATH_HOME" -- harness explain claude-code --llm m --json
assert_eq "digests: ...while the shown endpoint stays the origin" "https://llm.example" "$(jq -r .identity.endpoint <<< "$OUT")"
D_ENV1=$(digests_of "$BASE_HOME" m2)
D_ENV2=$(digests_of "$BASE_HOME" m2 TEST_LLM_URL="https://env.example/another/v1")
assert_ne "digests: a base_url_env pointing elsewhere changes the launch identity" "$(field 2 "$D_ENV1")" "$(field 2 "$D_ENV2")"
assert_eq "digests: ...and not the catalog digest, which reads no environment" "$(field 1 "$D_ENV1")" "$(field 1 "$D_ENV2")"
assert_eq "digests: a credential's value enters no digest" "$D1" "$(digests_of "$BASE_HOME" m TEST_LLM_KEY=another-value)"
D_TUNE=$(digests_of "$(home tuned awk '{print} /^llm = "m"$/ {print "max_output_tokens = 4096"}')" m)
assert_ne "digests: a tuning key changes the options digest" "$(field 3 "$D1")" "$(field 3 "$D_TUNE")"
assert_eq "digests: ...and not the launch identity" "$(field 2 "$D1")" "$(field 2 "$D_TUNE")"
D_COMPACT=$(digests_of "$(home compact awk '{print} /^llm = "m"$/ {print "auto_compact_window = 120000"}')" m)
assert_ne "digests: auto_compact_window is a tuning key" "$(field 3 "$D1")" "$(field 3 "$D_COMPACT")"
# Each further input of the launch identity moves it; the catalog digest
# moves with the declared tables, and the options digest never does.
moves() {  # <digests> <other digests> -> catalog|launch|options, each moved or same
    local i out=""
    for i in 1 2 3; do
        if [[ "$(field "$i" "$1")" == "$(field "$i" "$2")" ]]; then out="$out|same"; else out="$out|moved"; fi
    done
    printf '%s' "${out#|}"
}
assert_eq "digests: a quirk moves the catalog and the launch identity, not the options" "moved|moved|same" \
    "$(moves "$D1" "$(digests_of "$(home quirk awk '{print} /^auth_header = "bearer"$/ && !q {print "quirks = [\"rejects-dynamic-tools\"]"; q=1}')" m)")"
assert_eq "digests: the auth header moves the catalog and the launch identity, not the options" "moved|moved|same" \
    "$(moves "$D1" "$(digests_of "$(home header awk '/^auth_header = "bearer"$/ && !d {print "auth_header = \"x-api-key\""; d=1; next} {print}')" m)")"
assert_eq "digests: the credential's variable moves the catalog and the launch identity, not the options" "moved|moved|same" \
    "$(moves "$D1" "$(digests_of "$(home credvar sed 's/^credential_env = "TEST_LLM_KEY"$/credential_env = "OTHER_LLM_KEY"/')" m)")"
assert_eq "digests: credential mode none (no variable, no auth header, as the catalog requires) moves both, not the options" "moved|moved|same" \
    "$(moves "$D1" "$(digests_of "$(home credmode sed -e 's/^credential_mode = "env"$/credential_mode = "none"/' -e '/^credential_env = /d' -e 's/^auth_header = "bearer"$/auth_header = "none"/')" m)")"
assert_eq "digests: the protocol moves the catalog and the launch identity, not the options" "moved|moved|same" \
    "$(moves "$D1" "$(digests_of "$(home proto awk '/^protocol = "anthropic-messages"$/ && !d {print "protocol = \"openai-chat\""; d=1; next} {print}')" m)")"
assert_eq "digests: the model moves the catalog and the launch identity, not the options" "moved|moved|same" \
    "$(moves "$D1" "$(digests_of "$(home model sed 's/^model = "model-one"$/model = "model-renamed"/')" m)")"
# The harness is the one input not varied here: this version accepts
# bindings for claude-code only.
# A valid catalog ties the provider kind to whether the binding names an
# endpoint, so the kind is varied in the resolved plan itself.
KIND=$(env -u CCT_HOME CCT_HOME="$BASE_HOME" bash -c '
    source "$1/scripts/lib/llm-catalog.sh"; source "$1/scripts/lib/llm-adapters/claude-code.sh"; source "$1/scripts/lib/llm-resolve.sh"
    lc_validate "$(lc_catalog_path)" >/dev/null && lr_resolve claude-code own || exit 1
    lr_digests; launch="$LR_DIGEST_LAUNCH" options="$LR_DIGEST_OPTIONS"
    LR_PROVIDER_KIND=api; lr_digests
    l=same; o=same
    [[ "$launch" != "$LR_DIGEST_LAUNCH" ]] && l=moved
    [[ "$options" != "$LR_DIGEST_OPTIONS" ]] && o=moved
    printf "%s|%s" "$l" "$o"' _ "$REPO_DIR")
assert_eq "digests: the provider kind moves the launch identity, not the options" "moved|same" "$KIND"
# Computed where they are read (explain, show), not by the resolution a
# launch makes: each digest takes many jq runs.
LAZY=$(env -u CCT_HOME CCT_HOME="$BASE_HOME" TEST_LLM_KEY="$SECRET" bash -c '
    source "$1/scripts/lib/llm-catalog.sh"; source "$1/scripts/lib/llm-adapters/claude-code.sh"; source "$1/scripts/lib/llm-resolve.sh"
    lc_validate "$(lc_catalog_path)" >/dev/null && lr_resolve claude-code m || exit 1
    printf "%s|" "${LR_DIGEST_CATALOG:-none}"
    lr_digests && printf "%s %s %s|" "${#LR_DIGEST_CATALOG}" "${#LR_DIGEST_LAUNCH}" "${#LR_DIGEST_OPTIONS}"
    lr_resolve pi m; lr_digests; printf "%s" "$?"' _ "$REPO_DIR")
assert_eq "digests: a resolution computes none; lr_digests computes all three, and none without a binding" "none|64 64 64|1" "$LAZY"

# ── list and validate --json ──
cctx "$BASE_HOME" -- llm list --json
LIST="$OUT"
assert_eq "list --json: one row per binding, and one for an unbound llm" "4" "$(jq '.targets | length' <<< "$LIST")"
assert_eq "list --json: a credential by name and whether it is set" "env TEST_LLM_KEY true" \
    "$(jq -r '.targets[] | select(.llm == "m") | .credential | "\(.mode) \(.name) \(.set)"' <<< "$LIST")"
assert_contains "list --json: an unbound llm has no binding and says why" \
    "$(jq -c '.targets[] | select(.llm == "lonely") | {binding, reason}' <<< "$LIST")" '"binding":null,"reason":"no binding'
cctx "$BASE_HOME" -- llm validate --json
VALID="$OUT"
assert_eq "validate --json: a valid catalog" "true 0" "$(jq -r '"\(.valid) \(.violations | length)"' <<< "$VALID")"
printf 'schema_version = 1\n[llms.x]\nprovider = "nope"\nmodel = "m"\n' > "$TMP/broken.toml"
cctx "$BASE_HOME" -- llm validate "$TMP/broken.toml" --json
BROKEN="$OUT"
assert_exit "validate --json: violations exit 1" 1 "$RC"
assert_eq "validate --json: a violation has its line and its table" "3 llms.x" "$(jq -r '.violations[0] | "\(.line) \(.context)"' <<< "$BROKEN")"
cctx "$BASE_HOME" -- llm validate "$TMP/no-such-file.toml" --json
assert_exit "validate --json: an unreadable file exits 2" 2 "$RC"
assert_contains "validate --json: ...and says so" "$(jq -r .error <<< "$OUT")" "cannot read the LLM catalog"
assert_not_contains "--json: no output carries the credential's value" "$LIST$VALID$BROKEN$PLAN" "$SECRET"

# ── --json when a command cannot answer: the envelope with an error field ──
# cctx folds stderr into OUT, so OUT must be one JSON document and nothing
# else: text printed before or after the envelope fails the check.
EMPTY_HOME="$TMP/empty"; mkdir -p "$EMPTY_HOME"
INVALID_HOME=$(home invalid sed 's/^provider = "native"$/provider = "nope"/')
UNREADABLE_HOME="$TMP/unreadable"; mkdir -p "$UNREADABLE_HOME/llms.toml"
json_err() {
    local doc
    doc=$(jq -sc 'if length == 1 then .[0] else empty end' <<< "$OUT" 2>/dev/null)
    if [[ -n "$doc" && "$doc" == "$OUT" ]]; then printf '%s|%s' "$RC" "$(jq -r '"\(.command)|\(.error)"' <<< "$OUT")"
    else printf '%s|not one JSON document alone: %s' "$RC" "$OUT"; fi
}
cctx "$EMPTY_HOME" -- llm list --json; ERR_MISSING="$OUT"
assert_eq "list --json, no catalog: exit 2 and the envelope alone" "2|list|no LLM catalog" "$(json_err)"
assert_eq "list --json, no catalog: ...naming the file" "$EMPTY_HOME/llms.toml" "$(jq -r .catalog <<< "$OUT")"
cctx "$EMPTY_HOME" -- llm show m --json
assert_eq "show --json, no catalog: exit 2 and the envelope alone" "2|show|no LLM catalog" "$(json_err)"
cctx "$EMPTY_HOME" -- harness explain claude-code --llm m --json
assert_eq "explain --json, no catalog: exit 2 and the envelope alone" "2|explain|no LLM catalog" "$(json_err)"
VIOLATION="$INVALID_HOME/llms.toml has 1 violation(s); fix them first (cct llm validate)"
cctx "$INVALID_HOME" -- llm list --json; ERR_INVALID="$OUT"
assert_eq "list --json, an invalid catalog: exit 1 and the envelope alone" "1|list|$VIOLATION" "$(json_err)"
cctx "$INVALID_HOME" -- llm show m --json
assert_eq "show --json, an invalid catalog: exit 1 and the envelope alone" "1|show|$VIOLATION" "$(json_err)"
cctx "$INVALID_HOME" -- harness explain claude-code --llm m --json; ERR_EXPLAIN="$OUT"
assert_eq "explain --json, an invalid catalog: exit 1 and the envelope alone" "1|explain|$VIOLATION" "$(json_err)"
cctx "$UNREADABLE_HOME" -- llm list --json
assert_eq "list --json, a catalog that cannot be read: exit 2 and the envelope alone" \
    "2|list|cannot read the LLM catalog: $UNREADABLE_HOME/llms.toml" "$(json_err)"
cctx "$BASE_HOME" -- llm show ghost --json; ERR_UNKNOWN="$OUT"
assert_eq "show --json, an unknown llm: exit 2 and the envelope alone" \
    "2|show|unknown llm 'ghost' (cct llm list shows the catalog)" "$(json_err)"
# A usage error: the same envelope, with no catalog (none was read), and a
# null command when none was recognized.
cctx "$BASE_HOME" -- llm list extra --json; ERR_USAGE="$OUT"
assert_eq "list --json, a usage error: exit 2 and the envelope alone" "2|list|cct llm list takes no arguments" "$(json_err)"
assert_eq "list --json, a usage error: ...with no catalog" "false" "$(jq 'has("catalog")' <<< "$OUT")"
cctx "$BASE_HOME" -- llm show --json
assert_eq "show --json, a usage error: exit 2 and the envelope alone" "2|show|usage: cct llm show <llm> [--json]" "$(json_err)"
cctx "$BASE_HOME" -- llm validate a b --json
assert_eq "validate --json, a usage error: exit 2 and the envelope alone" "2|validate|cct llm validate takes at most one file" "$(json_err)"
cctx "$BASE_HOME" -- llm compatibility --bogus --json
assert_eq "compatibility --json, a usage error: exit 2 and the envelope alone" \
    "2|compatibility|cct llm compatibility: unknown option '--bogus'" "$(json_err)"
cctx "$BASE_HOME" -- harness explain claude-code --json
assert_eq "explain --json, a usage error: exit 2 and the envelope alone" \
    "2|explain|usage: cct harness explain <harness> --llm <target> [--project <dir>] [--json]" "$(json_err)"
cctx "$BASE_HOME" -- harness bogus --json
assert_eq "harness --json, an unknown subcommand: a null command" \
    "2|null|usage: cct harness explain <harness> --llm <target> [--project <dir>] [--json]" "$(json_err)"
cctx "$BASE_HOME" -- llm frob --json; ERR_NO_COMMAND="$OUT"
assert_eq "--json, an unknown command: a null command" \
    "2|null|cct llm: unknown command 'frob' (list | show | validate | compatibility)" "$(json_err)"

# ── every --json document against the schema ──
cctx "$BASE_HOME" -- llm show m --json; SHOW="$OUT"
cctx "$BASE_HOME" -- harness explain pi --llm m --json; REFUSED="$OUT"
PY_SCHEMA=""
for py in python3 python3.13 python3.12 python3.11; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import jsonschema' >/dev/null 2>&1; then PY_SCHEMA="$py"; break; fi
done
schema_ok() {  # <json document>
    printf '%s' "$1" | "$PY_SCHEMA" -c '
import json, sys, jsonschema
schema = json.load(open(sys.argv[1]))
jsonschema.Draft202012Validator.check_schema(schema)
jsonschema.Draft202012Validator(schema).validate(json.load(sys.stdin))' "$SCHEMA" >/dev/null 2>&1
}
SCHEMA_DOCS="LIST SHOW VALID BROKEN PLAN REFUSED ERR_MISSING ERR_INVALID ERR_EXPLAIN ERR_UNKNOWN ERR_USAGE ERR_NO_COMMAND"
if [[ -n "$PY_SCHEMA" ]]; then
    for doc in $SCHEMA_DOCS; do
        if schema_ok "${!doc}"; then PASS=$((PASS+1)); echo "  PASS: schema: the $doc document";
        else FAIL=$((FAIL+1)); echo "  FAIL: schema: the $doc document does not match $SCHEMA"; fi
    done
    if schema_ok "$(jq -c '. + {targets: []}' <<< "$ERR_MISSING")"; then
        FAIL=$((FAIL+1)); echo "  FAIL: schema: an error envelope that also lists targets must match no form"
    else PASS=$((PASS+1)); echo "  PASS: schema: an error envelope that also lists targets matches no form"; fi
else
    SKIPPED=$(( $(wc -w <<< "$SCHEMA_DOCS") + 1 ))
    echo "  SKIP: jsonschema not installed — the $SKIPPED schema checks did not run"
fi

# ── a project's [llm] restriction, through explain (#400 S5) ──
mkdir -p "$TMP/policy-proj"
printf '[llm]\nallowed = ["m2"]\n' > "$TMP/policy-proj/.cct.toml"
cctx "$BASE_HOME" -- harness explain claude-code --llm m --project "$TMP/policy-proj"
assert_exit "explain --project: a target the project does not list is refused" 3 "$RC"
assert_contains "...naming the project's list" "$OUT" "is not allowed in this project"
CLI_RUN_DIR="$TMP/policy-proj" cctx "$BASE_HOME" -- harness explain claude-code --llm m
assert_exit "explain: the project is the current directory's by default" 3 "$RC"
cctx "$BASE_HOME" -- harness explain claude-code --llm m --project "$TMP/no-such-dir"
assert_exit "explain --project: a directory that does not exist is a usage error" 2 "$RC"
mkdir -p "$TMP/git-proj/sub/deeper"
git -C "$TMP/git-proj" init -q
printf '[llm]\nallowed = ["m2"]\n' > "$TMP/git-proj/.cct.toml"
cctx "$BASE_HOME" -- harness explain claude-code --llm m --project "$TMP/git-proj/sub/deeper"
assert_exit "explain --project: a subdirectory follows its git top level's .cct.toml" 3 "$RC"
mkdir -p "$TMP/unreadable-proj"; printf '[llm]\nallowed = ["m"]\n' > "$TMP/unreadable-proj/.cct.toml"; chmod 000 "$TMP/unreadable-proj/.cct.toml"
cctx "$BASE_HOME" -- harness explain claude-code --llm m --project "$TMP/unreadable-proj"
assert_exit "explain --project: a .cct.toml that cannot be read refuses, never reads as no restriction" 3 "$RC"

# ── cct help ──
HELP=$(bash "$CCT" help 2>&1)
assert_contains "cct help documents show" "$HELP" "cct llm show <llm>"
assert_contains "cct help documents harness explain" "$HELP" "cct harness explain <harness> --llm <target>"

echo ""
echo "========================================="
echo "  llm-cli tests: $PASS passed, $FAIL failed$( [[ $SKIPPED -gt 0 ]] && echo ", $SKIPPED skipped (jsonschema not installed)")"
echo "========================================="
# A skipped schema check is not a missing assertion: CI installs jsonschema
# and runs all of them.
if [[ "$((PASS + SKIPPED))" -ne "${TEST_LLM_CLI_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_LLM_CLI_EXPECTED_PASS:-0}, got $PASS passed + $SKIPPED skipped)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
