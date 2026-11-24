#!/usr/bin/env bash
# test-llm-catalog.sh — #479: the LLM catalog (scripts/lib/llm-catalog.sh)
# and its read-only CLI (`cct llm list | validate`).
#
# Every refusal is asserted BY NAME: the grammar the catalog shares with
# the routing registry (scripts/lib/cct-toml.sh), the catalog's own
# tables and keys, target resolution, and what the CLI prints: a
# credential by its variable's name, an endpoint by its origin, never a
# value or a path.
#
# Run from the repo root: bash tests/test-llm-catalog.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
CLI="$REPO_DIR/scripts/llm-cli.sh"
EXAMPLE="$REPO_DIR/shared/templates/llm/llms.toml.example"

PASS=0; FAIL=0
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
# A permission fixture tests nothing where chmod cannot take the permission
# away (run as root, or on a file system without modes). Its assertions are
# skipped there and counted, so the pin holds; CI runs them.
SKIPPED=0
denied() {  # <test flag: -r | -x> <path> <assertion name>...: 0 when chmod took the permission away
    test "$1" "$2" || return 0
    local name; shift 2
    for name in "$@"; do SKIPPED=$((SKIPPED+1)); echo "  SKIP: $name (chmod has no effect here, as when run as root)"; done
    return 1
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# A small valid catalog; each case below is this file with one edit.
base() {
    cat <<'EOF'
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
base_url = "https://llm.example/v1"
auth_header = "bearer"

[llms.m]
provider = "p"
model = "model-one"

[llms.own]
provider = "native"
model = "opus"

[bindings.b]
harness = "claude-code"
llm = "m"
endpoint = "e"

[bindings.own-b]
harness = "claude-code"
llm = "own"
EOF
}

validate() {  # <file> -> OUTPUT, RC
    RC=0
    OUTPUT=$(bash "$CLI" validate "$1" 2>&1) || RC=$?
}

# viol <name> <expected text> <sed expression over base> [<text appended>]
# One assertion: the catalog is refused (exit 1) AND the violation is
# named with a line number.
viol() {
    local name="$1" expected="$2" edit="$3" extra="${4:-}" f="$TMP/case.toml"
    base | sed -e "$edit" > "$f"
    if [[ -n "$extra" ]]; then printf '%s\n' "$extra" >> "$f"; fi
    validate "$f"
    if [[ "$RC" -eq 1 ]] && echo "$OUTPUT" | grep -F -- "$expected" | grep -q '^line [0-9][0-9]*: '; then
        PASS=$((PASS+1)); echo "  PASS: $name"
    else
        FAIL=$((FAIL+1)); echo "  FAIL: $name (exit $RC; expected a 'line N:' violation containing '$expected')"
        echo "$OUTPUT" | sed 's/^/        | /' | head -6
    fi
}

echo "=== LLM catalog tests (#479) ==="

# ── The valid cases ──
base > "$TMP/base.toml"
validate "$TMP/base.toml"
assert_exit "the base catalog is valid" 0 "$RC"
validate "$EXAMPLE"
assert_exit "the shipped example is valid" 0 "$RC"
assert_contains "validate names the file it accepted" "$OUTPUT" "is a valid LLM catalog"
validate "$TMP/no-such-file.toml"
assert_exit "an unreadable catalog exits 2" 2 "$RC"
printf 'schema_version = 1\n' > "$TMP/empty.toml"
validate "$TMP/empty.toml"
assert_exit "a catalog with no tables is valid" 0 "$RC"

# ── Grammar: the shared lexer's rejections, by name ──
viol "grammar: schema_version is required" "schema_version = 1 is required" '/^schema_version/d'
viol "grammar: an unsupported schema_version" "schema_version 2 is not supported" 's/^schema_version = 1/schema_version = 2/'
viol "grammar: a non-integer schema_version" "schema_version must be an integer" 's/^schema_version = 1/schema_version = "1"/'
viol "grammar: a key before the first table" "appears outside any table" 's/^schema_version = 1/schema_version = 1\ndefault = "m"/'
viol "grammar: a table outside the four" "table [policy] is not accepted" 's/^\[llms\.m\]/[policy]/'
viol "grammar: an id that starts with a hyphen" "table [llms.-m] is not accepted" 's/^\[llms\.m\]/[llms.-m]/'
viol "grammar: an id with a dot" "table [llms.m.x] is not accepted" 's/^\[llms\.m\]/[llms.m.x]/'
viol "grammar: array-of-tables" "array-of-tables is not accepted" 's/^\[llms\.m\]/[[llms]]/'
viol "grammar: a malformed table header" "malformed table header" 's/^\[llms\.m\]/[llms.m/'
viol "grammar: a duplicate table" "duplicate table declaration: [llms.m]" 's/^\[llms\.own\]/[llms.m]/'
viol "grammar: a duplicate key" "duplicate key 'model' in [llms.m]" 's/^model = "model-one"/model = "model-one"\nmodel = "again"/'
viol "grammar: a dotted key" "dotted keys are not accepted: 'a.b'" 's/^model = "model-one"/model = "model-one"\na.b = "x"/'
viol "grammar: an inline table" "inline tables are not accepted" 's/^model = "model-one"/model = { id = "x" }/'
viol "grammar: a multiline string" "multiline strings are not accepted" 's/^model = "model-one"/model = """x"""/'
viol "grammar: a literal string" "literal (single-quoted) strings are not accepted" "s/^model = \"model-one\"/model = 'x'/"
viol "grammar: a non-string array" "only single-line arrays of basic strings are accepted" 's/^auth_header = "bearer"/auth_header = "bearer"\nquirks = [1, 2]/'
viol "grammar: malformed quoting" "malformed quoting" 's/^model = "model-one"/model = "x/'
viol "grammar: an unrecognized value form" "unrecognized value form" 's/^model = "model-one"/model = 1.5/'
viol "grammar: an unrecognized line" "unrecognized line" 's/^model = "model-one"/model/'

# ── Providers ──
viol "provider: kind is required" "[providers.p] kind is required" '/^kind = "api"/d'
viol "provider: kind outside the set" "kind 'cloud' is not accepted" 's/^kind = "api"/kind = "cloud"/'
viol "provider: kind of the wrong type" "'kind' must be a string" 's/^kind = "api"/kind = true/'
viol "provider: credential_mode is required" "[providers.native] credential_mode is required" '/^credential_mode = "native"/d'
viol "provider: keychain is reserved" "secure-store credentials are not implemented" 's/^credential_mode = "env"/credential_mode = "keychain"/'
viol "provider: native is refused for an api provider" "credential_mode 'native' is not accepted for an api provider" 's/^credential_mode = "env"/credential_mode = "native"/'
viol "provider: env is refused for a managed provider" "is not accepted for a managed provider" 's/^credential_mode = "native"/credential_mode = "none"/'
viol "provider: credential_env is required with env" "credential_env is required with credential_mode" '/^credential_env/d'
viol "provider: credential_env is a NAME" "credential_env must be an environment-variable NAME" 's/^credential_env = "TEST_LLM_KEY"/credential_env = "not a name"/'
viol "provider: credential_env only with env" "credential_env is only accepted with credential_mode" 's/^credential_mode = "native"/credential_mode = "native"\ncredential_env = "X_KEY"/'
viol "provider: an unknown key" "[providers.p] unknown key 'api_key'" 's/^kind = "api"/kind = "api"\napi_key = "x"/'
viol "provider: a key no slice consumes yet" "'data_policy' is not implemented in this version" 's/^kind = "api"/kind = "api"\ndata_policy = "local-only"/'

# ── Endpoints ──
viol "endpoint: provider is required" "[endpoints.e] provider is required" '/^\[endpoints\.e\]/,/^protocol/{/^provider = "p"/d;}'
viol "endpoint: an undefined provider" "provider 'ghost' is not defined" '/^\[endpoints\.e\]/,/^protocol/s/^provider = "p"/provider = "ghost"/'
viol "endpoint: on a managed provider" "an endpoint cannot belong to a managed provider" '/^\[endpoints\.e\]/,/^protocol/s/^provider = "p"/provider = "native"/'
viol "endpoint: protocol is required" "[endpoints.e] protocol is required" '/^protocol/d'
viol "endpoint: protocol outside the set" "protocol 'grpc' is not accepted" 's/^protocol = "anthropic-messages"/protocol = "grpc"/'
viol "endpoint: neither base_url nor base_url_env" "exactly one of base_url | base_url_env is required" '/^base_url/d'
viol "endpoint: both base_url and base_url_env" "exactly one of base_url | base_url_env is required" 's|^base_url = .*|&\nbase_url_env = "TEST_LLM_URL"|'
viol "endpoint: base_url that is not http(s)" "base_url must be an absolute http(s) URL" 's|^base_url = .*|base_url = "ftp://llm.example"|'
viol "endpoint: base_url with userinfo" "base_url must not carry userinfo" 's|^base_url = .*|base_url = "https://user:pw@llm.example/v1"|'
viol "endpoint: base_url with a query" "base_url must not carry a query" 's|^base_url = .*|base_url = "https://llm.example/v1?key=1"|'
viol "endpoint: base_url with a fragment" "base_url must not carry a fragment" 's|^base_url = .*|base_url = "https://llm.example/v1#x"|'
viol "endpoint: base_url_env is a NAME" "base_url_env must be an environment-variable NAME" 's|^base_url = .*|base_url_env = "llm url"|'
viol "endpoint: auth_header is required" "[endpoints.e] auth_header is required" '/^auth_header/d'
viol "endpoint: auth_header outside the set" "auth_header 'basic' is not accepted" 's/^auth_header = "bearer"/auth_header = "basic"/'
viol "endpoint: none is refused when the provider has a credential" 'auth_header "none" is not accepted' 's/^auth_header = "bearer"/auth_header = "none"/'
viol "endpoint: a header is refused when the provider has no credential" 'auth_header must be "none"' '/^credential_env/d; s/^credential_mode = "env"/credential_mode = "none"/'
viol "endpoint: a quirk outside the set" "quirk 'slow' is not accepted" 's/^auth_header = "bearer"/auth_header = "bearer"\nquirks = ["slow"]/'

# ── LLMs ──
viol "llm: provider is required" "[llms.m] provider is required" '/^\[llms\.m\]/,/^model/{/^provider = "p"/d;}'
viol "llm: an undefined provider" "provider 'ghost' is not defined" '/^\[llms\.m\]/,/^model/s/^provider = "p"/provider = "ghost"/'
viol "llm: model is required" "[llms.m] model is required" '/^model = "model-one"/d'
viol "llm: a model with whitespace" "model must be a non-empty id without whitespace" 's/^model = "model-one"/model = "model one"/'
viol "llm: context_window must be positive" "'context_window' must be a positive integer" 's/^model = "model-one"/model = "model-one"\ncontext_window = 0/'
viol "llm: reasoning is a boolean" "'reasoning' must be true or false" 's/^model = "model-one"/model = "model-one"\nreasoning = "yes"/'
viol "llm: input outside the set" "input 'audio' is not accepted" 's/^model = "model-one"/model = "model-one"\ninput = ["text", "audio"]/'
viol "llm: an unknown key" "[llms.m] unknown key 'temperature'" 's/^model = "model-one"/model = "model-one"\ntemperature = 1/'

# ── Bindings ──
viol "binding: harness is required" "[bindings.own-b] harness is required" '/^\[bindings\.own-b\]/,$ {/^harness/d;}'
viol "binding: harness outside the set" "harness 'cursor' is not accepted" '/^\[bindings\.own-b\]/,$ s/^harness = "claude-code"/harness = "cursor"/'
viol "binding: a harness with no launcher yet" "harness 'codex' has no --llm launcher in this version" '/^\[bindings\.own-b\]/,$ s/^harness = "claude-code"/harness = "codex"/'
viol "binding: llm is required" "[bindings.own-b] llm is required" '/^llm = "own"/d'
viol "binding: an undefined llm" "llm 'ghost' is not defined" 's/^llm = "own"/llm = "ghost"/'
viol "binding: endpoint is required for an api provider" "endpoint is required: llm 'm' belongs to the api provider 'p'" '/^endpoint = "e"/d'
viol "binding: an undefined endpoint" "endpoint 'ghost' is not defined" 's/^endpoint = "e"/endpoint = "ghost"/'
viol "binding: an endpoint on a managed provider's llm" "cannot name an endpoint" 's/^llm = "own"/llm = "own"\nendpoint = "e"/'
viol "binding: small_fast_model on a managed provider" "small_fast_model applies to an endpoint binding" 's/^llm = "own"/llm = "own"\nsmall_fast_model = "haiku"/'
viol "binding: max_output_tokens must be positive" "'max_output_tokens' must be a positive integer" 's/^endpoint = "e"/endpoint = "e"\nmax_output_tokens = -1/'
viol "binding: auto_compact_window is an integer" "'auto_compact_window' must be an integer" 's/^endpoint = "e"/endpoint = "e"\nauto_compact_window = "big"/'
viol "binding: reasoning_effort is one lowercase word" "reasoning_effort must be one lowercase word" 's/^endpoint = "e"/endpoint = "e"\nreasoning_effort = "Very High"/'
viol "binding: an unknown key" "[bindings.b] unknown key 'model'" 's/^endpoint = "e"/endpoint = "e"\nmodel = "x"/'
viol "binding: a duplicate (harness, llm, endpoint)" "[bindings.b2] duplicates [bindings.b]" 's/^schema_version = 1/schema_version = 1/' '
[bindings.b2]
harness = "claude-code"
llm = "m"
endpoint = "e"'

# ── A credential is never accepted as a value, and never echoed ──
SECRET="sk-plantedsecret0123456789"
viol "secret: a credential-shaped value is refused" "holds a value that looks like a credential" "s/^model = \"model-one\"/model = \"$SECRET\"/"
assert_not_contains "secret: the refusal does not print the value" "$OUTPUT" "$SECRET"
viol "secret: a refused enum value is not echoed either" "protocol '<redacted>' is not accepted" "s/^protocol = \"anthropic-messages\"/protocol = \"$SECRET\"/"
assert_not_contains "secret: ...the value itself is absent" "$OUTPUT" "$SECRET"

# ── Resolution: <llm> or <llm>@<binding>, explicit bindings only ──
resolve() {  # <catalog> <target> -> OUTPUT ("llm binding" or the error), RC
    RC=0
    OUTPUT=$(bash -c '
        source "$1/scripts/lib/llm-catalog.sh"
        lc_validate "$2" >/dev/null || exit 9
        if lc_resolve claude-code "$3"; then printf "%s %s" "$LC_R_LLM" "$LC_R_BINDING"; else printf "%s" "$LC_R_ERR"; exit 1; fi
    ' _ "$REPO_DIR" "$1" "$2" 2>&1) || RC=$?
}
resolve "$TMP/base.toml" m
assert_eq "resolve: <llm> finds its one binding" "m b" "$OUTPUT"
resolve "$TMP/base.toml" m@b
assert_eq "resolve: <llm>@<binding>" "m b" "$OUTPUT"
resolve "$TMP/base.toml" ghost
assert_contains "resolve: an unknown llm" "$OUTPUT" "unknown llm 'ghost'"
resolve "$TMP/base.toml" m@ghost
assert_contains "resolve: an unknown binding" "$OUTPUT" "unknown binding 'ghost'"
resolve "$TMP/base.toml" m@own-b
assert_contains "resolve: a binding for another llm" "$OUTPUT" "binding 'own-b' is for llm 'own', not 'm'"
resolve "$TMP/base.toml" "m@b@c"
assert_contains "resolve: a malformed target" "$OUTPUT" "is not a target"
{ base; printf '\n[endpoints.e2]\nprovider = "p"\nprotocol = "anthropic-messages"\nbase_url = "https://other.example"\nauth_header = "bearer"\n\n[bindings.b2]\nharness = "claude-code"\nllm = "m"\nendpoint = "e2"\n'; } > "$TMP/two.toml"
resolve "$TMP/two.toml" m
assert_exit "resolve: several bindings are refused" 1 "$RC"
assert_contains "resolve: ...naming them and the form to use" "$OUTPUT" "several bindings for claude-code (b, b2): use --llm m@<binding>"
resolve "$TMP/two.toml" m@b2
assert_eq "resolve: ...and the @ form picks one" "m b2" "$OUTPUT"
base | sed '/^\[bindings\.b\]/,/^endpoint = "e"/d' > "$TMP/unbound.toml"
resolve "$TMP/unbound.toml" m
assert_contains "resolve: no binding is never inferred" "$OUTPUT" "llm 'm' has no binding for claude-code: add a [bindings.<id>] table"

# ── cct llm list ──
list() {  # env assignments... -> OUTPUT, RC (CCT_HOME is the fixture home)
    RC=0
    OUTPUT=$(env -u TEST_LLM_KEY -u TEST_LLM_URL "$@" CCT_HOME="$TMP/home" bash "$CLI" list 2>&1) || RC=$?
}
mkdir -p "$TMP/home"
list
assert_exit "list: no catalog exits 2" 2 "$RC"
assert_contains "list: ...and says where to put one" "$OUTPUT" "no LLM catalog at $TMP/home/llms.toml"

PLANTED="planted-credential-value-do-not-print"
cp "$TMP/two.toml" "$TMP/home/llms.toml"
list TEST_LLM_KEY="$PLANTED"
assert_exit "list: a valid catalog exits 0" 0 "$RC"
assert_contains "list: a credential is shown by NAME and whether it is set" "$OUTPUT" "TEST_LLM_KEY (set)"
assert_not_contains "list: ...never by value" "$OUTPUT" "$PLANTED"
assert_contains "list: an endpoint is shown by its origin" "$OUTPUT" "https://llm.example "
assert_not_contains "list: ...never with its path" "$OUTPUT" "llm.example/v1"
assert_contains "list: an llm with several bindings lists <llm>@<binding>" "$OUTPUT" "m@b2"
assert_contains "list: a managed provider signs in itself" "$OUTPUT" "its own login"
assert_contains "list: a launchable target is unverified, and the word is explained" "$OUTPUT" "unverified: launchable; no compatibility probe exists yet"
list
assert_contains "list: an unset credential makes the target unavailable" "$OUTPUT" "unavailable: credential variable TEST_LLM_KEY is not set"
assert_contains "list: ...and says so in the credential column" "$OUTPUT" "TEST_LLM_KEY (not set)"

base | sed 's/^protocol = "anthropic-messages"/protocol = "openai-responses"/' > "$TMP/home/llms.toml"
list TEST_LLM_KEY="$PLANTED"
assert_contains "list: an endpoint the harness cannot speak to is unsupported" "$OUTPUT" \
    "unsupported: endpoint 'e' speaks openai-responses, claude-code speaks anthropic-messages"

base | sed 's|^base_url = .*|base_url_env = "TEST_LLM_URL"|' > "$TMP/home/llms.toml"
list TEST_LLM_KEY="$PLANTED"
assert_contains "list: an unset base URL variable makes the target unavailable" "$OUTPUT" "unavailable: base URL variable TEST_LLM_URL is not set"
list TEST_LLM_KEY="$PLANTED" TEST_LLM_URL="https://tenant.example/path/tenant-token-xyz"
assert_contains "list: a base URL from the environment is shown by its origin" "$OUTPUT" "https://tenant.example "
assert_not_contains "list: ...its path is never printed" "$OUTPUT" "tenant-token-xyz"
list TEST_LLM_KEY="$PLANTED" TEST_LLM_URL="https://tenant.example/v1?token=tenant-token-xyz"
assert_contains "list: a base URL value the rule refuses is unavailable" "$OUTPUT" "unavailable: the value of TEST_LLM_URL must not carry a query"
assert_not_contains "list: ...and the refused value is not printed" "$OUTPUT" "tenant-token-xyz"

cp "$TMP/unbound.toml" "$TMP/home/llms.toml"
list
assert_contains "list: an llm nothing binds is listed with the remedy" "$OUTPUT" "no binding: add a [bindings.<id>] table for it"

base | sed 's/^kind = "api"/kind = "cloud"/' > "$TMP/home/llms.toml"
list
assert_exit "list: an invalid catalog exits 1" 1 "$RC"
assert_contains "list: ...after naming the violation" "$OUTPUT" "kind 'cloud' is not accepted"

# The legacy home is a fallback for a catalog too (#411): one resolver.
mkdir -p "$TMP/legacy-home/.code-copilot-team"
cp "$TMP/base.toml" "$TMP/legacy-home/.code-copilot-team/llms.toml"
LEGACY_OUT=$(env -u CCT_HOME -u TEST_LLM_KEY HOME="$TMP/legacy-home" bash "$CLI" list 2>&1) || true
assert_contains "list: the catalog is found through the CCT home resolver" "$LEGACY_OUT" "model-one"

# ── cct llm, through the front door ──
CCT_OUT=$(bash "$REPO_DIR/scripts/cct" llm validate "$EXAMPLE" 2>&1); CCT_RC=$?
assert_exit "cct llm validate dispatches to the catalog CLI" 0 "$CCT_RC"
assert_contains "cct help documents llm" "$(bash "$REPO_DIR/scripts/cct" help 2>&1)" "cct llm list"
assert_contains "cct help documents --llm on start" "$(bash "$REPO_DIR/scripts/cct" help 2>&1)" "cct start --llm"
USAGE_RC=0; USAGE_OUT=$(bash "$CLI" bogus 2>&1) || USAGE_RC=$?
assert_exit "an unknown cct llm command exits 2" 2 "$USAGE_RC"
assert_contains "...and names the four that exist" "$USAGE_OUT" "list | show | validate | compatibility"

# ── a project's [llm] restriction (#400 FR-24, D13; S5) ──
PROJ="$TMP/policy-proj"; mkdir -p "$PROJ"
policy() {  # <.cct.toml content, "-" for none, or "=" as it is> -> rc|restricts|allowed|error
    [[ "$1" == "=" ]] || rm -f "$PROJ/.cct.toml"
    [[ "$1" == "-" || "$1" == "=" ]] || printf '%s\n' "$1" > "$PROJ/.cct.toml"
    bash -c 'source "$1/scripts/lib/llm-catalog.sh"; rc=0; lc_project_policy "$2" || rc=$?
             printf "%s|%s|%s|%s" "$rc" "$([[ -n "$LC_POLICY_FILE" ]] && echo yes || echo no)" \
                 "$(printf "%s" "$LC_ALLOWED" | paste -sd, -)" "$LC_POLICY_ERR"' _ "$REPO_DIR" "$PROJ"
}
assert_eq "policy: no .cct.toml restricts nothing" "0|no||" "$(policy -)"
assert_eq "policy: a .cct.toml without [llm] restricts nothing" "0|no||" "$(policy '[security]
fail_closed = true')"
assert_eq "policy: [llm].allowed lists llm ids and <llm>@<binding> targets" "0|yes|m,own@own-b|" "$(policy '[llm]
allowed = ["m", "own@own-b"]')"
assert_eq "policy: an empty list allows nothing" "0|yes||" "$(policy '[llm]
allowed = []')"
assert_contains "policy: any other [llm] key is refused by name" "$(policy '[llm]
allowed = ["m"]
default = "m"')" "[llm].default is not accepted: projects restrict, never grant"
assert_contains "policy: a dotted key at the root is refused, never ignored" "$(policy 'llm.allowed = ["m"]')" \
    "write the project's LLM restriction as an [llm] table"
assert_contains "policy: an inline table at the root is refused too" "$(policy 'llm = { allowed = ["m"] }')" \
    "write the project's LLM restriction as an [llm] table"
assert_contains "policy: an [llm.<x>] sub-table is refused" "$(policy '[llm.extra]
x = 1')" "is not accepted: projects restrict, never grant"
assert_contains "policy: allowed must be a list" "$(policy '[llm]
allowed = "m"')" "must be one line of double-quoted ids"
assert_contains "policy: an entry must be an llm id or <llm>@<binding>" "$(policy '[llm]
allowed = ["m", "not an id"]')" "'not an id' in [llm].allowed is not an llm id"
assert_contains "policy: allowed given twice is refused" "$(policy '[llm]
allowed = ["m"]
allowed = ["m2"]')" "given twice"
assert_eq "policy: a key named llm inside another table is that table's own" "0|no||" "$(policy '[providers.p]
llm = "x"')"
assert_eq "policy: the rest of the file may use forms the catalog lexer refuses" "0|yes|m|" "$(policy '[security]
protected_paths = [
  ".env",
]
[llm]
allowed = ["m"]')"
printf '[llm]\nallowed = ["m2"]\n' > "$PROJ/.cct.local.toml"
mkdir -p "$PROJ/.code-copilot-team"; printf '[llm]\nallowed = ["m2"]\n' > "$PROJ/.code-copilot-team/config.toml"
assert_eq "policy: .cct.local.toml and the legacy config.toml are never read" "0|no||" "$(policy -)"
# TOML may quote the table's name: still the [llm] table, read or refused as such.
assert_eq "policy: a quoted table name is the same [llm] table" "0|yes|m|" "$(policy '["llm"]
allowed = ["m"]')"
assert_eq "policy: ...single-quoted and spaced too" "0|yes|m|" "$(policy "[ 'llm' ]
allowed = [\"m\"]")"
assert_eq "policy: a quoted dotted key at the top is refused, never ignored" \
    "1|no||$PROJ/.cct.toml line 1: write the project's LLM restriction as an [llm] table with allowed = [...]" "$(policy '"llm".allowed = ["m"]')"
assert_eq "policy: a header with a comment is the [llm] table" "0|yes|m|" "$(policy '[llm] # the team restriction
allowed = ["m"]')"
assert_eq "policy: ...and so is one after a byte-order mark" "0|yes|m|" "$(policy "$(printf '\357\273\277[llm]\nallowed = ["m"]')")"
assert_eq "policy: [[llm]] is refused, never ignored" \
    "1|no||$PROJ/.cct.toml line 1: '[[llm]]' is not accepted: projects restrict, never grant (only [llm] allowed = [...])" "$(policy '[[llm]]
allowed = ["m"]')"
# Any other header naming the table is refused, never read as another table.
assert_eq "policy: text after the [llm] header is refused, never skipped" \
    "1|no||$PROJ/.cct.toml line 1: '[llm] x' is not accepted: write the header as [llm], alone or followed by a comment" "$(policy '[llm] x
allowed = ["m"]')"
assert_contains "policy: ...and so is text inside it" "$(policy '[llm x]
allowed = ["m"]')" "'[llm x]' is not accepted: write the header as [llm]"
assert_eq "policy: [llmx] is another table, whose keys are its own" "0|no||" "$(policy '[llmx]
allowed = ["m"]')"
# Pi's parser trims Unicode spaces from a line and a header's name, so a
# table Pi reads is read here too, never skipped.
assert_eq "policy: a no-break space around or inside the header is a blank" "0|yes|m|" "$(policy "$(printf '\302\240[\302\240llm ]\nallowed = ["m"]')")"
assert_eq "policy: ...and so is a byte-order mark before a later header" "0|yes|m|" "$(policy "$(printf '[security]\nfail_closed = true\n\357\273\277[llm]\nallowed = ["m"]')")"
assert_eq "policy: a header's comment in Latin-1 is a comment in any locale" "0|yes|m|" "$(policy "$(printf '[llm] # \351t\351\nallowed = ["m"]')")"
assert_eq "policy: a refused header is shown only up to an = or a #, since a value may follow" \
    "1|no||$PROJ/.cct.toml line 1: '[llm] api_key ...' is not accepted: write the header as [llm], alone or followed by a comment" "$(policy '[llm] api_key = "sk-not-a-real-key-0000"
allowed = ["m"]')"
# The list is one line of double-quoted ids, the only form the lexer reads:
# any other TOML form of it is refused, naming that one.
ONE_LINE='[llm].allowed must be one line of double-quoted ids separated by commas, as in allowed = ["<llm>", "<llm>@<binding>"], with no escapes, no trailing comma and no comment after it'
assert_eq "policy: a list over several lines is refused, naming the one-line form" "1|no||$PROJ/.cct.toml line 2: $ONE_LINE" "$(policy '[llm]
allowed = [
  "m",
]')"
assert_eq "policy: ...and so is a trailing comma" "1|no||$PROJ/.cct.toml line 2: $ONE_LINE" "$(policy '[llm]
allowed = ["m",]')"
assert_eq "policy: ...and single-quoted ids" "1|no||$PROJ/.cct.toml line 2: $ONE_LINE" "$(policy "[llm]
allowed = ['m']")"
assert_eq "policy: ...and a quoted key" \
    "1|no||$PROJ/.cct.toml line 2: this line is not accepted in [llm], which holds one line: allowed = [\"<llm>\", \"<llm>@<binding>\"]" "$(policy '[llm]
"allowed" = ["m"]')"
assert_eq "policy: a line refused in [llm] is not echoed, since its value may be a secret" \
    "1|no||$PROJ/.cct.toml line 2: this line is not accepted in [llm], which holds one line: allowed = [\"<llm>\", \"<llm>@<binding>\"]" "$(policy '[llm]
api.key = "sk-not-a-real-key-0000"')"
# A restriction that cannot be read is never read as none.
printf '[llm]\nallowed = ["m"]\n' > "$PROJ/.cct.toml"; chmod 000 "$PROJ/.cct.toml"
T="policy: a .cct.toml that cannot be read is refused by name"
denied -r "$PROJ/.cct.toml" "$T" && assert_eq "$T" "1|no||cannot read $PROJ/.cct.toml" "$(policy =)"
rm -f "$PROJ/.cct.toml"; mkdir "$PROJ/.cct.toml"
assert_eq "policy: a .cct.toml that is not a file is refused" "1|no||cannot read $PROJ/.cct.toml" "$(policy =)"
rmdir "$PROJ/.cct.toml"; chmod 000 "$PROJ"
T="policy: a project directory that cannot be searched is refused"
denied -x "$PROJ" "$T" && assert_eq "$T" "1|no||cannot read $PROJ/.cct.toml: the directory cannot be searched" "$(policy =)"
chmod 700 "$PROJ"

echo ""
echo "========================================="
echo "  llm-catalog tests: $PASS passed, $FAIL failed$( [[ $SKIPPED -gt 0 ]] && echo ", $SKIPPED skipped")"
echo "========================================="
if [[ "$((PASS + SKIPPED))" -ne "${TEST_LLM_CATALOG_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_LLM_CATALOG_EXPECTED_PASS:-0}, got $PASS passed + $SKIPPED skipped)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
