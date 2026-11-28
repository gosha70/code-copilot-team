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
# A permission fixture tests nothing where chmod cannot take the permission
# away (run as root, or on a file system without modes). Its assertions are
# skipped there and counted, so the pin holds; CI runs them.
denied() {  # <test flag: -r | -x> <path> <assertion name>...: 0 when chmod took the permission away
    test "$1" "$2" || return 0
    local name; shift 2
    for name in "$@"; do SKIPPED=$((SKIPPED+1)); echo "  SKIP: $name (chmod has no effect here, as when run as root)"; done
    return 1
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
# A value that starts with a dash is text to the digests like any other: a
# jq run that took it for an option would hash nothing at all.
D_DASH1=$(digests_of "$(home dash1 awk '{print} /^llm = "m"$/ {print "small_fast_model = \"--fast\""}')" m)
D_DASH2=$(digests_of "$(home dash2 awk '{print} /^llm = "m"$/ {print "small_fast_model = \"--slow\""}')" m)
EMPTY_SHA256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
assert_eq "digests: a value that starts with a dash is text: it moves the options digest, and no digest is that of nothing" "moved|no" \
    "$([[ "$(field 3 "$D_DASH1")" != "$(field 3 "$D_DASH2")" ]] && echo moved || echo same)|$(grep -q "$EMPTY_SHA256" <<< "$D_DASH1 $D_DASH2" && echo yes || echo no)"
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
    "2|null|cct llm: unknown command 'frob' (list | show | validate | compatibility | sessions | test)" "$(json_err)"
cctx "$BASE_HOME" -- llm sessions extra --json; ERR_SESSIONS="$OUT"
assert_eq "sessions --json, a usage error: exit 2 and the envelope alone" "2|sessions|cct llm sessions: unknown argument 'extra'" "$(json_err)"
cctx "$BASE_HOME" -- llm sessions --harness bogus --json
assert_eq "sessions --json, an unknown harness: exit 2, naming the harnesses" \
    "2|sessions|cct llm sessions: unknown harness 'bogus' (one of: claude-code, codex, pi, kiro)" "$(json_err)"

# ── cct llm sessions (#400 S4: FR-6, FR-17, FR-18, FR-19) ──
# Each stamp is written by the library a launch writes it with, from the
# project, with a stand-in claude for the harness version, which the
# compatibility state a resume computes needs too.
mkdir -p "$TMP/bin"; printf '#!/bin/sh\necho "2.1.332 (Claude Code)"\n' > "$TMP/bin/claude"; chmod +x "$TMP/bin/claude"
SESS_PROJ="$TMP/sess-proj"; mkdir -p "$SESS_PROJ"; SESS_PROJ=$(cd "$SESS_PROJ" && pwd -P)
CLAUDE_DIR="$TMP/claude-config"   # Claude Code's own directory: its transcripts
stamp_session() {  # <home> <target> <session-id>: the stamp a launch from the project writes
    (cd "$SESS_PROJ" && env -u CCT_HOME CCT_HOME="$1" PATH="$TMP/bin:$PATH" TEST_LLM_KEY="$SECRET" bash -c '
        for l in llm-catalog llm-adapters/claude-code llm-resolve cct-statefile llm-compat llm-sessions; do source "$1/scripts/lib/$l.sh"; done
        lc_validate "$(lc_catalog_path)" >/dev/null && lr_resolve claude-code "$2" "$PWD" && lss_stamp_new claude-code "$3"
    ' _ "$REPO_DIR" "$2" "$3")
}
sess() {  # <home> [VAR=value ...] -- <cct args>: cctx with Claude Code's directory and the stand-in claude
    local h="$1"; shift
    cctx "$h" CLAUDE_CONFIG_DIR="$CLAUDE_DIR" PATH="$TMP/bin:$PATH" "$@"
}
first() { jq -r ".sessions[0] | \"\(.resume.eligible)|\(.resume.reason)\"" <<< "$OUT"; }
resume_of() { jq -r --arg id "$1" '.sessions[] | select(.session_id == $id) | "\(.resume.eligible)|\(.resume.reason)"' <<< "$OUT"; }
SESS_HOME=$(home sessions)
sess "$SESS_HOME" -- llm sessions
assert_eq "sessions: none stamped yet, said, exit 0" \
    "0|No claude-code session started with --llm has a stamp yet ($SESS_HOME/llm-sessions/claude-code)." "$RC|$OUT"

SA=aaaaaaaa-0000-4000-8000-00000000000a; SB=bbbbbbbb-0000-4000-8000-00000000000b
stamp_session "$SESS_HOME" m "$SA"; stamp_session "$SESS_HOME" own "$SB"
# A resume goes ahead only past S3's gate, so each target has a passing
# test on record, under its evidence now, written by the probe's writer.
seed_pass() {  # <home> <target>...
    local h="$1"; shift
    (cd "$SESS_PROJ" && env -u CCT_HOME CCT_HOME="$h" PATH="$TMP/bin:$PATH" TEST_LLM_KEY="$SECRET" bash -c '
        r="$1"; shift
        for l in llm-catalog llm-adapters/claude-code llm-resolve cct-statefile llm-compat; do source "$r/scripts/lib/$l.sh"; done
        lc_validate "$(lc_catalog_path)" >/dev/null || { echo "seed_pass: the catalog is not valid"; exit 1; }
        m="{\"auth\":\"pass\",\"model_identity\":\"pass\",\"streaming\":\"pass\",\"system_prompt\":\"pass\",\"tool_call\":\"pass\",\"tool_result\":\"pass\",\"output_parsing\":\"pass\",\"clean_exit\":\"pass\",\"limit_controls\":\"not_applicable\"}"
        for t in "$@"; do
            lcm_state claude-code "$t" || { echo "seed_pass: $t: $LCM_ERR"; exit 1; }
            # Built apart: bash 3.2 misreads escaped quotes inside "$(...)".
            a=$(jq -nc --argjson m "$m" --argjson e "$LCM_EVIDENCE" "{at: \"2026-11-26T12:00:00Z\", outcome: \"pass\", matrix: \$m, evidence: \$e}")
            lcm_record_attempt claude-code "$LR_LLM" "$LR_BINDING" "$a" || { echo "seed_pass: $t: $LCM_ERR"; exit 1; }
        done' _ "$REPO_DIR" "$@") || echo "  FAIL: seed_pass could not write a record"
}
seed_pass "$SESS_HOME" m own
# Claude Code names a project's directory after its path, every other
# character a dash (S4's capture). It also records an API error as its own
# assistant entry, which is not a reply.
SLUG=$(printf '%s' "$SESS_PROJ" | sed 's/[^A-Za-z0-9]/-/g')
mkdir -p "$CLAUDE_DIR/projects/$SLUG"
printf '%s\n' '{"type":"user","message":{"role":"user","content":"hi"}}' \
    '{"type":"assistant","message":{"role":"assistant","model":"model-one-0501"}}' > "$CLAUDE_DIR/projects/$SLUG/$SA.jsonl"
printf '%s\n' '{"type":"user","message":{"role":"user","content":"hi"}}' \
    '{"type":"assistant","isApiErrorMessage":true,"message":{"role":"assistant","model":"<synthetic>"}}' > "$CLAUDE_DIR/projects/$SLUG/$SB.jsonl"
sess "$SESS_HOME" -- llm sessions --json; SESSIONS="$OUT"
row() { jq -r --arg id "$1" ".sessions[] | select(.session_id == \$id) | $2" <<< "$SESSIONS"; }
assert_eq "sessions --json: exit 0, both sessions, for claude-code" "0|2|claude-code" \
    "$RC|$(jq '.sessions | length' <<< "$SESSIONS")|$(jq -r .harness <<< "$SESSIONS")"
assert_eq "sessions: each with its target, requested model and project" "m@b|model-one|$SESS_PROJ" \
    "$(row "$SA" '"\(.target)|\(.requested_model)|\(.project)"')"
assert_eq "sessions: a reply in the harness's transcript establishes it, with the model the reply names" \
    "established|model-one-0501|yes" "$(row "$SA" '"\(.status)|\(.effective_model)|\(if .established_at then "yes" else "no" end)"')"
assert_eq "sessions: ...and its stamp keeps that" "established|model-one-0501" \
    "$(jq -r '"\(.status)|\(.effective_model)"' "$SESS_HOME/llm-sessions/claude-code/$SA.json")"
assert_eq "sessions: a transcript with only Claude Code's own API-error entry leaves it attempted, with no effective model" \
    "attempted|null" "$(row "$SB" '"\(.status)|\(.effective_model)"')"
assert_eq "sessions: both resumable now, with no reason" "true|null true|null" \
    "$(row "$SA" '"\(.resume.eligible)|\(.resume.reason)"') $(row "$SB" '"\(.resume.eligible)|\(.resume.reason)"')"
# Older than SB, so newest first is the reverse of the order the directory lists.
jq '.refreshed_at = "2026-01-01T00:00:00Z"' "$SESS_HOME/llm-sessions/claude-code/$SA.json" > "$TMP/sa.json"
cat "$TMP/sa.json" > "$SESS_HOME/llm-sessions/claude-code/$SA.json"
sess "$SESS_HOME" -- llm sessions --json
assert_eq "sessions: newest first" "$SB $SA" "$(jq -r '[.sessions[].session_id] | join(" ")' <<< "$OUT")"
sess "$SESS_HOME" -- llm sessions; SESSIONS_TEXT="$OUT"
assert_contains "sessions: the text names the harness" "$OUT" "claude-code sessions started with --llm, newest first"
assert_eq "sessions: ...and a row per session: its id, target, model, state, resume and project" "1" \
    "$(grep -F "$SA" <<< "$OUT" | grep -F 'm@b' | grep -F model-one-0501 | grep -F established | grep -wF yes | grep -cF "$SESS_PROJ")"
mkdir -p "$TMP/other-proj"
sess "$SESS_HOME" -- llm sessions --project "$SESS_PROJ" --json; IN_PROJ=$(jq '.sessions | length' <<< "$OUT")
sess "$SESS_HOME" -- llm sessions --project "$TMP/other-proj" --json
assert_eq "sessions --project: only the sessions started in that directory" "2 0" "$IN_PROJ $(jq '.sessions | length' <<< "$OUT")"
sess "$SESS_HOME" -- llm sessions --harness pi --json; SESSIONS_PI="$OUT"
assert_eq "sessions --harness: another harness's stamps, none before its slice" "0|pi|0" \
    "$RC|$(jq -r .harness <<< "$OUT")|$(jq '.sessions | length' <<< "$OUT")"

# What a resume by the session's id would refuse, each with its reason.
sess "$SESS_HOME" TEST_LLM_KEY= -- llm sessions --json
assert_eq "sessions: a target that cannot launch now is not resumable, and the other still is" \
    "false|m@b is unavailable on claude-code: credential variable TEST_LLM_KEY is not set true" \
    "$(jq -r --arg a "$SA" --arg b "$SB" '[(.sessions[] | select(.session_id == $a) | "\(.resume.eligible)|\(.resume.reason)"), (.sessions[] | select(.session_id == $b) | .resume.eligible)] | join(" ")' <<< "$OUT")"
printf '[llm]\nallowed = ["own"]\n' > "$SESS_PROJ/.cct.toml"
sess "$SESS_HOME" -- llm sessions --json
assert_eq "sessions: a target its project no longer allows is not resumable" \
    "false|--llm m@b is not allowed in this project: $SESS_PROJ/.cct.toml [llm].allowed lists own" "$(resume_of "$SA")"
rm -f "$SESS_PROJ/.cct.toml"
mkdir -p "$SESS_PROJ/.claude"; printf '{"env": {"ANTHROPIC_BASE_URL": "https://elsewhere.example"}}\n' > "$SESS_PROJ/.claude/settings.json"
sess "$SESS_HOME" -- llm sessions --json
assert_eq "sessions: a settings file setting a variable the launch controls makes it not resumable" \
    "false|a Claude Code settings file sets a variable this launch must control ($SESS_PROJ/.claude/settings.json: ANTHROPIC_BASE_URL)" \
    "$(resume_of "$SA")"
rm -f "$SESS_PROJ/.claude/settings.json"
COMPAT_REC="$SESS_HOME/llm-compat/claude-code/m@b.json"
mkdir -p "$(dirname "$COMPAT_REC")"; chmod 700 "$SESS_HOME/llm-compat" "$(dirname "$COMPAT_REC")"
printf 'not a record' > "$COMPAT_REC"; chmod 600 "$COMPAT_REC"
sess "$SESS_HOME" -- llm sessions --json
assert_eq "sessions: a compatibility record that cannot be read makes it not resumable, as the stamp's refresh would fail" \
    "false|the compatibility state of m@b cannot be computed: the record $COMPAT_REC is malformed" "$(resume_of "$SA")"
rm -f "$COMPAT_REC"
# A fork's transcript opens with its source's history, each entry marked
# forkedFrom: not this session's replies, so an API error alone after them
# leaves the fork attempted.
SD=dddddddd-0000-4000-8000-0000000000fd; stamp_session "$SESS_HOME" m "$SD"
printf '%s\n' "{\"type\":\"assistant\",\"forkedFrom\":{\"sessionId\":\"$SA\",\"messageUuid\":\"u1\"},\"message\":{\"role\":\"assistant\",\"model\":\"model-one-0501\"}}" \
    '{"type":"user","message":{"role":"user","content":"go on"}}' \
    '{"type":"assistant","isApiErrorMessage":true,"message":{"role":"assistant","model":"<synthetic>"}}' > "$CLAUDE_DIR/projects/$SLUG/$SD.jsonl"
sess "$SESS_HOME" -- llm sessions --json
assert_eq "sessions: a fork whose own reply never came stays attempted, whatever its copied history says" \
    "attempted|null" "$(jq -r --arg d "$SD" '.sessions[] | select(.session_id == $d) | "\(.status)|\(.effective_model)"' <<< "$OUT")"
rm -f "$SESS_HOME/llm-sessions/claude-code/$SD.json"
SC=cccccccc-0000-4000-8000-00000000000c; stamp_session "$SESS_HOME" m "$SC"
mkdir -p "$CLAUDE_DIR/projects/-shortened-path-1a2b3c"
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","model":"model-one-0601"}}' > "$CLAUDE_DIR/projects/-shortened-path-1a2b3c/$SC.jsonl"
sess "$SESS_HOME" -- llm sessions --json
assert_eq "sessions: a transcript in a directory not named after the path (Claude Code shortens long ones) is found by its id" \
    "established|model-one-0601" "$(jq -r --arg c "$SC" '.sessions[] | select(.session_id == $c) | "\(.status)|\(.effective_model)"' <<< "$OUT")"
MOVED_HOME=$(home sess-moved); stamp_session "$MOVED_HOME" m "$SA"
sed -i.bak 's#https://llm.example/#https://moved.example/#' "$MOVED_HOME/llms.toml"
sess "$MOVED_HOME" -- llm sessions --json; SESSIONS_MOVED="$OUT"
assert_eq "sessions: a target whose launch identity changed is not resumable (FR-19)" \
    "false|the launch identity of m@b changed since the session was stamped (its provider, endpoint, protocol, auth header, model, credential or quirks)" "$(first)"
sess "$MOVED_HOME" -- llm sessions
assert_contains "sessions: ...said under the table, with its resume column no" "$OUT" "Not resumable now: $SA: the launch identity of m@b changed"
NOCAT_HOME=$(home sess-nocat); stamp_session "$NOCAT_HOME" m "$SA"; mv "$NOCAT_HOME/llms.toml" "$NOCAT_HOME/llms.saved"
sess "$NOCAT_HOME" -- llm sessions --json
assert_eq "sessions: with no catalog the stamps are still listed, none resumable" \
    "0|false|there is no LLM catalog at $NOCAT_HOME/llms.toml" "$RC|$(first)"
BAD=dddddddd-0000-4000-8000-00000000000d
printf 'not a stamp' > "$SESS_HOME/llm-sessions/claude-code/$BAD.json"
sess "$SESS_HOME" -- llm sessions
assert_eq "sessions: a stamp that cannot be read is named, the others listed, exit 2" "2|yes|yes" \
    "$RC|$(grep -qF "the stamp of session $BAD cannot be read" <<< "$OUT" && echo yes || echo no)|$(grep -qF "$SA" <<< "$OUT" && echo yes || echo no)"
rm -f "$SESS_HOME/llm-sessions/claude-code/$BAD.json"
assert_eq "sessions: no credential value or endpoint path in any output" "0" \
    "$(printf '%s\n' "$SESSIONS" "$SESSIONS_TEXT" "$SESSIONS_MOVED" | grep -cF -e "$SECRET" -e "$PATH_TOKEN")"

# ── cct llm test (#400 S3: FR-15, FR-16, D6) ──
# The probe runs the mock harness (the `claude` first on PATH) against the stub
# gateway, one gateway per switch; the S3 capture runs the real Claude Code
# behind the same gateway. A private TMPDIR shows what each run leaves.
GATEWAY="$REPO_DIR/tests/fixtures/llm-stub-gateway.py"
MOCK_HARNESS="$TMP/mock-harness-$$-$RANDOM.py"   # a path of this run's own, for pgrep
cp "$REPO_DIR/tests/fixtures/llm-mock-claude.py" "$MOCK_HARNESS"
PROBE_TMP="$TMP/probe-tmp"; mkdir -p "$PROBE_TMP"
probe_home() {  # <name> <port>: a home whose target pm reaches the gateway, and cm an endpoint claude-code cannot speak to
    mkdir -p "$TMP/$1"
    cat > "$TMP/$1/llms.toml" <<EOF
schema_version = 1

[providers.p]
display_name = "Provider P"
kind = "api"
credential_mode = "env"
credential_env = "TEST_LLM_KEY"

[endpoints.gw]
provider = "p"
protocol = "anthropic-messages"
base_url = "http://127.0.0.1:$2/$PATH_TOKEN"
auth_header = "bearer"

[endpoints.chat]
provider = "p"
protocol = "openai-chat"
base_url = "https://chat.example/v1"
auth_header = "bearer"

[llms.pm]
provider = "p"
model = "probe-model"
reasoning = true
input = ["text", "image"]

[llms.cm]
provider = "p"
model = "chat-model"

[bindings.pt]
harness = "claude-code"
llm = "pm"
endpoint = "gw"
max_output_tokens = 1000

[bindings.ct]
harness = "claude-code"
llm = "cm"
endpoint = "chat"
EOF
    printf '%s' "$TMP/$1"
}
gateway() {  # <log> [--switch <name>]...: a stub gateway; GW_PID and GW_PORT
    local log="$1"; shift
    rm -f "$log.port"
    python3 "$GATEWAY" "$log" "$log.port" "$@" &
    GW_PID=$!
    for _ in $(seq 1 50); do [[ -s "$log.port" ]] && break; sleep 0.1; done
    GW_PORT=$(cat "$log.port" 2>/dev/null)
}
gateway_stop() { kill "$GW_PID" 2>/dev/null; wait "$GW_PID" 2>/dev/null; }
# The mock harness is the `claude` on PATH, as the real one is: a run
# through CCT_LLM_PROBE_CMD decides nothing (its own test is below).
mkdir -p "$TMP/probe-bin"
printf '#!/bin/sh\nexec python3 "%s" "$@"\n' "$MOCK_HARNESS" > "$TMP/probe-bin/claude"; chmod +x "$TMP/probe-bin/claude"
ptest() {  # <home> [VAR=value ...] -- <cct args>: cctx with the mock harness as claude, and the private TMPDIR
    local h="$1"; shift
    cctx "$h" PATH="$TMP/probe-bin:$PATH" TMPDIR="$PROBE_TMP" CCT_LLM_PROBE_TIMEOUT_SEC=20 "$@"
}

gateway "$TMP/gw-base.jsonl"
P_HOME=$(probe_home probe-base "$GW_PORT")
ptest "$P_HOME" -- llm compatibility pm --json
assert_eq "test: before any test the target is unverified" "unverified" "$(jq -r '.targets[0].state' <<< "$OUT")"
ptest "$P_HOME" -- llm test pm --json; TEST_PASS="$OUT"
assert_eq "test: one passing run moves unverified to supported (FR-15)" "0|pass|supported" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(jq -r .state <<< "$OUT")"
assert_eq "test: ...every capability passed, the declared reasoning and image ones included" \
    "auth=pass model_identity=pass streaming=pass system_prompt=pass tool_call=pass tool_result=pass output_parsing=pass clean_exit=pass limit_controls=pass reasoning_control=pass image_input=pass" \
    "$(jq -r '.matrix | to_entries | map("\(.key)=\(.value)") | join(" ")' <<< "$OUT")"
PREC="$P_HOME/llm-compat/claude-code/pm@pt.json"
assert_eq "test: ...recorded in both parts (FR-16), with the evidence digest and a redacted excerpt" "pass|pass|64|yes" \
    "$(jq -r '"\(.latest_attempt.outcome)|\(.latest_conclusive.outcome)|\(.latest_attempt.evidence.digest | length)|\(if (.latest_attempt.redacted | test("^CCT_PROBE_OK:")) then "yes" else "no" end)"' "$PREC")"
ptest "$P_HOME" -- llm test pm; TEST_TEXT="$OUT"
assert_contains "test: the text form shows the matrix, the outcome and the state" "$OUT" "Outcome: pass: passed every capability this binding needs"
gateway_stop

probe_switch() {  # <switch> <capability> <value> <state> [<timeout>]
    gateway "$TMP/gw-$1.jsonl" --switch "$1"
    local h; h=$(probe_home "probe-$1" "$GW_PORT")
    ptest "$h" CCT_LLM_PROBE_TIMEOUT_SEC="${5:-20}" -- llm test pm --json
    gateway_stop
    assert_eq "test: under $1, $2 is $3 and the target $4" "1|$3|$4" \
        "$RC|$(jq -r --arg c "$2" '.matrix[$c]' <<< "$OUT")|$(jq -r .state <<< "$OUT")"
    SWITCH_REC="$h/llm-compat/claude-code/pm@pt.json"
}
probe_switch drop-tool-calls tool_call fail incompatible
probe_switch ignore-tool-results tool_result fail incompatible
probe_switch no-stream streaming fail incompatible
probe_switch other-model model_identity fail incompatible
probe_switch ignore-system-prompt system_prompt fail incompatible
probe_switch reject-shape output_parsing fail incompatible
probe_switch reject-model output_parsing unverifiable unverified
probe_switch reject-billing output_parsing unverifiable unverified
# An alias the endpoint resolves passes, and the record keeps the name it
# reported; a later test that reports another passes too, and says the alias
# moved (the owner's ruling of 2026-11-27).
gateway "$TMP/gw-resolve.jsonl" --switch resolve-model
RM_HOME=$(probe_home probe-resolve "$GW_PORT")
ptest "$RM_HOME" -- llm test pm --json
gateway_stop
RM_REC="$RM_HOME/llm-compat/claude-code/pm@pt.json"
assert_eq "test: a dated id that contains the requested name passes model_identity, and the record keeps it" '0|pass|supported|["probe-model-20251101"]|1' \
    "$RC|$(jq -r .matrix.model_identity <<< "$OUT")|$(jq -r .state <<< "$OUT")|$(jq -c .latest_conclusive.reported_models "$RM_REC")|$(jq -r .detail <<< "$OUT" | grep -c '(the endpoint reports probe-model as probe-model-20251101)$')"
RM_FIRST_AT=$(jq -r .latest_conclusive.at "$RM_REC")
gateway "$TMP/gw-resolve-moved.jsonl" --switch resolve-model-moved
RM_HOME=$(probe_home probe-resolve "$GW_PORT")
ptest "$RM_HOME" -- llm test pm --json
gateway_stop
assert_eq "test: ...a later test that reports another passes too, records it, and says the alias moved" '0|pass|supported|["probe-model-20260215"]|1' \
    "$RC|$(jq -r .matrix.model_identity <<< "$OUT")|$(jq -r .state <<< "$OUT")|$(jq -c .latest_conclusive.reported_models "$RM_REC")|$(jq -r .detail <<< "$OUT" | grep -c "the endpoint reports probe-model as probe-model-20260215, where the test of $RM_FIRST_AT recorded probe-model-20251101: the alias moved")"
ptest "$RM_HOME" -- llm list; RM_LIST="$OUT"
ptest "$RM_HOME" -- llm show pm; RM_SHOW="$OUT"
ptest "$RM_HOME" -- harness explain claude-code --llm pm; RM_EXPLAIN="$OUT"
assert_eq "list, show and explain give the tested state a launch gets, not the static one (S3)" "1|1|1|1" \
    "$(grep -cE '^pm +claude-code .* supported *$' <<< "$RM_LIST")|$(grep -c 'STATE is what a launch gets' <<< "$RM_LIST")|$(grep -cE '^ +pm +claude-code .* supported$' <<< "$RM_SHOW")|$(grep -c '^  state     supported: passed its test of ' <<< "$RM_EXPLAIN")"
ptest "$RM_HOME" -- llm list --json; RM_LIST_J="$OUT"
ptest "$RM_HOME" -- llm show pm --json; RM_SHOW_J="$OUT"
ptest "$RM_HOME" -- harness explain claude-code --llm pm --json; RM_EXPLAIN_J="$OUT"
assert_eq "...and their --json gives it as launch_state, beside the static state" "unverified|supported|supported|supported" \
    "$(jq -r '.targets[] | select(.target == "pm") | .state' <<< "$RM_LIST_J")|$(jq -r '.targets[] | select(.target == "pm") | .launch_state' <<< "$RM_LIST_J")|$(jq -r '.bindings[0].launch_state' <<< "$RM_SHOW_J")|$(jq -r .launch_state <<< "$RM_EXPLAIN_J")"
# The alias rule matches whole name parts: a requested name inside a longer
# word, or a single letter of it, is another model; an empty name says
# nothing (#555's review).
alias_case() {  # <reported name> <tag>: cct llm test of an `opus` target behind a gateway reporting that name
    gateway "$TMP/gw-alias-$2.jsonl" --report-model "$1"
    local h; h=$(probe_home "probe-alias-$2" "$GW_PORT")
    sed 's/^model = "probe-model"$/model = "opus"/' "$h/llms.toml" > "$h/llms.toml.new" && mv "$h/llms.toml.new" "$h/llms.toml"
    ptest "$h" -- llm test pm --json
    gateway_stop
}
alias_case "octopus-7" octopus
assert_eq "test: a name holding the requested one only inside a longer word fails model_identity (octopus-7 for opus)" "1|fail|incompatible" \
    "$RC|$(jq -r .matrix.model_identity <<< "$OUT")|$(jq -r .state <<< "$OUT")"
alias_case "o" letter
assert_eq "test: ...as does a one-letter name (o for opus)" "1|fail|incompatible" \
    "$RC|$(jq -r .matrix.model_identity <<< "$OUT")|$(jq -r .state <<< "$OUT")"
alias_case "" empty
assert_eq "test: an empty model name says nothing: model_identity is unverifiable, and the detail says why" "1|unverifiable|unverified|1" \
    "$RC|$(jq -r .matrix.model_identity <<< "$OUT")|$(jq -r .state <<< "$OUT")|$(jq -r .detail <<< "$OUT" | grep -c 'the endpoint reported an empty model name')"
# The endpoint is the model: a command of its own, appended to the canary's
# tool call, is refused, and the run fails (#547's review).
gateway "$TMP/gw-extra.jsonl" --switch extra-command --extra-file "$TMP/extra-ran.txt"
X_HOME=$(probe_home probe-extra "$GW_PORT")
ptest "$X_HOME" -- llm test pm --json
gateway_stop
assert_eq "test: a command the endpoint appends to the canary's tool call never runs, and the run fails" "1|fail|fail|incompatible|absent|1" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(jq -r .matrix.tool_call <<< "$OUT")|$(jq -r .state <<< "$OUT")|$([[ -e "$TMP/extra-ran.txt" ]] && echo present || echo absent)|$(jq -r .detail <<< "$OUT" | grep -c "asked for more than the canary's command, and claude refused it")"
# The user's own permission rules apply in the test, as in a launch; the
# guard hook blocks what one that allows all of Bash would let run, unless
# hooks are off for the test (#547's review).
mkdir -p "$TMP/guard-allow" "$TMP/guard-off" "$TMP/guard-safe"
printf '%s\n' '{"permissions":{"allow":["Bash"]}}' > "$TMP/guard-allow/settings.json"
printf '%s\n' '{"permissions":{"allow":["Bash"]},"disableAllHooks":true}' > "$TMP/guard-off/settings.json"
printf '%s\n' '{"env":{"CLAUDE_CODE_SAFE_MODE":"1"}}' > "$TMP/guard-safe/settings.json"
gateway "$TMP/gw-guard.jsonl"
G_HOME=$(probe_home probe-guard "$GW_PORT")
ptest "$G_HOME" CLAUDE_CONFIG_DIR="$TMP/guard-allow" -- llm test pm --json
gateway_stop
assert_eq "test: under a user rule that allows all of Bash, an honest endpoint passes: the guard lets the canary's command through" "0|pass" \
    "$RC|$(jq -r .outcome <<< "$OUT")"
gateway "$TMP/gw-guard-extra.jsonl" --switch extra-command --extra-file "$TMP/extra-ran-guard.txt"
GX_HOME=$(probe_home probe-guard-extra "$GW_PORT")
ptest "$GX_HOME" CLAUDE_CONFIG_DIR="$TMP/guard-allow" -- llm test pm --json
gateway_stop
assert_eq "test: ...and the guard blocks a command the endpoint appends, which that rule would let run, and the run fails" "1|fail|fail|absent|1" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(jq -r .matrix.tool_call <<< "$OUT")|$([[ -e "$TMP/extra-ran-guard.txt" ]] && echo present || echo absent)|$(jq -r .detail <<< "$OUT" | grep -c "asked for more than the canary's command, and claude refused it")"
gateway "$TMP/gw-guard-image.jsonl" --switch image-command --extra-file "$TMP/extra-ran-image.txt"
GI_HOME=$(probe_home probe-guard-image "$GW_PORT")
ptest "$GI_HOME" CLAUDE_CONFIG_DIR="$TMP/guard-allow" -- llm test pm --json
gateway_stop
assert_eq "test: ...in the image run too: a command the endpoint asks for there never runs, and fails tool_call" "1|fail|fail|pass|absent|1" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(jq -r .matrix.tool_call <<< "$OUT")|$(jq -r .matrix.image_input <<< "$OUT")|$([[ -e "$TMP/extra-ran-image.txt" ]] && echo present || echo absent)|$(jq -r .detail <<< "$OUT" | grep -c "asked for more than the canary's command, and claude refused it")"
gateway "$TMP/gw-guard-refused.jsonl" --switch extra-command --extra-file "$TMP/extra-ran-refused.txt"
GR_HOME=$(probe_home probe-guard-refused "$GW_PORT")
ptest "$GR_HOME" CLAUDE_CONFIG_DIR="$TMP/guard-off" -- llm test pm
GR_TEXT="$OUT" GR_RC="$RC"
ptest "$GR_HOME" CLAUDE_CONFIG_DIR="$TMP/guard-off" -- llm test pm --json
gateway_stop
assert_eq "test: settings that turn hooks off refuse the test, naming the cause and --without-guard, with nothing run or recorded" "3|1|1|3|test|1|0|absent|absent" \
    "$GR_RC|$(grep -c "refused: hooks are off for this test (.*sets disableAllHooks)" <<< "$GR_TEXT")|$(grep -c 'pass --without-guard to run the test unguarded' <<< "$GR_TEXT")|$RC|$(jq -r .command <<< "$OUT")|$(jq -r .error <<< "$OUT" | grep -c 'pass --without-guard')|$(cat "$TMP/gw-guard-refused.jsonl" 2>/dev/null | wc -l | tr -d ' ')|$([[ -e "$TMP/extra-ran-refused.txt" ]] && echo present || echo absent)|$([[ -e "$GR_HOME/llm-compat/claude-code/pm@pt.json" ]] && echo present || echo absent)"
gateway "$TMP/gw-guard-off.jsonl" --switch extra-command --extra-file "$TMP/extra-ran-off.txt"
GO_HOME=$(probe_home probe-guard-off "$GW_PORT")
ptest "$GO_HOME" CLAUDE_CONFIG_DIR="$TMP/guard-off" -- llm test pm --without-guard
gateway_stop
assert_eq "test: ...--without-guard runs it, warned of before the run; the appended command then runs, as on the real binary, and the run still fails" "1|before|present|1|1" \
    "$RC|$(awk '/warning: --without-guard: hooks are off for this test \(.*sets disableAllHooks/ { w = NR } /^Outcome:/ { o = NR } END { print (w && o && w < o) ? "before" : "not before" }' <<< "$OUT")|$([[ -e "$TMP/extra-ran-off.txt" ]] && echo present || echo absent)|$(grep -c '^Outcome: fail: failed: tool_call' <<< "$OUT")|$(grep -c "asked for more than the canary's command, and claude ran it: hooks were off for this test" <<< "$OUT")"
gateway "$TMP/gw-guard-modes.jsonl"
GM_HOME=$(probe_home probe-guard-modes "$GW_PORT")
ptest "$GM_HOME" CLAUDE_CONFIG_DIR="$TMP/guard-safe" -- llm test pm
GM_SAFE="$OUT" GM_SAFE_RC="$RC"
ptest "$GM_HOME" CLAUDE_CODE_SIMPLE=1 -- llm test pm
gateway_stop
assert_eq "test: ...as do CLAUDE_CODE_SAFE_MODE in a settings file's env block and CLAUDE_CODE_SIMPLE in the environment, which turn hooks off too, each named" "3|1|3|1" \
    "$GM_SAFE_RC|$(grep -c 'refused: hooks are off for this test (.*sets CLAUDE_CODE_SAFE_MODE in its env block)' <<< "$GM_SAFE")|$RC|$(grep -c 'refused: hooks are off for this test (CLAUDE_CODE_SIMPLE is set in this environment)' <<< "$OUT")"
# CCT_LLM_PROBE_CMD replaces the harness: said, recorded, never conclusive.
gateway "$TMP/gw-seam.jsonl"
SE_HOME=$(probe_home probe-seam "$GW_PORT")
ptest "$SE_HOME" CCT_LLM_PROBE_CMD="python3 $MOCK_HARNESS" -- llm test pm
SEAM_RC="$RC"; SEAM_OUT="$OUT"
ptest "$SE_HOME" -- llm compatibility pm --json
gateway_stop
assert_eq "test: a run through CCT_LLM_PROBE_CMD is said, and decides nothing for the gate" "1|1|unverified|null" \
    "$SEAM_RC|$(grep -c 'CCT_LLM_PROBE_CMD is set, so it runs in place of claude' <<< "$SEAM_OUT")|$(jq -r '.targets[0].state' <<< "$OUT")|$(jq -c .latest_conclusive "$SE_HOME/llm-compat/claude-code/pm@pt.json")"
probe_switch exceed-limits limit_controls fail incompatible
probe_switch drop-reasoning reasoning_control fail incompatible
probe_switch ignore-images image_input fail incompatible
probe_switch reject-auth auth fail unverified
assert_eq "test: ...a refused credential is unavailable evidence, never conclusive" "unavailable|null" \
    "$(jq -r '"\(.latest_attempt.outcome)|\(.latest_conclusive)"' "$SWITCH_REC")"
probe_switch time-out clean_exit fail unverified 2
assert_eq "test: ...a run cut off by the watchdog is unverifiable, never conclusive" "unverifiable|null" \
    "$(jq -r '"\(.latest_attempt.outcome)|\(.latest_conclusive)"' "$SWITCH_REC")"
probe_switch server-error output_parsing unverifiable unverified
assert_eq "test: ...a server error decides nothing" "unverifiable|null" \
    "$(jq -r '"\(.latest_attempt.outcome)|\(.latest_conclusive)"' "$SWITCH_REC")"
probe_switch not-found output_parsing unverifiable unverified
assert_eq "test: ...and an error naming the request path keeps the endpoint's path out of the record" "yes|0" \
    "$(jq -r 'if (.latest_attempt.redacted | test("Cannot POST <endpoint-path>/v1/messages")) then "yes" else "no" end' "$SWITCH_REC")|$(grep -cF "$PATH_TOKEN" "$SWITCH_REC")"

gateway "$TMP/gw-crash.jsonl"
C_HOME=$(probe_home probe-crash "$GW_PORT")
ptest "$C_HOME" CCT_PROBE_MOCK_CRASH=1 -- llm test pm --json
gateway_stop
assert_eq "test: a harness that crashes after its answer fails clean_exit, and nothing is conclusive (FR-13)" "1|unverifiable|fail|null" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(jq -r .matrix.clean_exit <<< "$OUT")|$(jq -c .latest_conclusive "$C_HOME/llm-compat/claude-code/pm@pt.json")"
gateway "$TMP/gw-crash-image.jsonl"
CI_HOME=$(probe_home probe-crash-image "$GW_PORT")
ptest "$CI_HOME" CCT_PROBE_MOCK_CRASH=image -- llm test pm --json
gateway_stop
assert_eq "test: ...so does one that crashes in the image run alone, after a correct answer" "1|unverifiable|fail|unverifiable|null" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(jq -r .matrix.clean_exit <<< "$OUT")|$(jq -r .matrix.image_input <<< "$OUT")|$(jq -c .latest_conclusive "$CI_HOME/llm-compat/claude-code/pm@pt.json")"
# The crash is its exit status, never a real signal: on macOS a process a
# SIGSEGV ends writes a crash report and shows a dialog, every run (#547).
# Python reports an exit as 139 and that death as -11.
CRASH_RC=$(env -i PATH="$PATH" HOME="$TMP" CCT_PROBE_MOCK_CRASH=1 python3 -c \
    'import subprocess, sys; print(subprocess.run([sys.executable, sys.argv[1], "-p"], input="", capture_output=True, text=True).returncode)' \
    "$MOCK_HARNESS" 2>&1)
assert_eq "test: ...both by the status a shell reports for a SIGSEGV death, 139, with no signal raised" "139" "$CRASH_RC"
gateway "$TMP/gw-garbage.jsonl"
GB_HOME=$(probe_home probe-garbage "$GW_PORT")
ptest "$GB_HOME" CCT_PROBE_MOCK_GARBAGE=1 -- llm test pm --json
gateway_stop
assert_eq "test: output that cannot be parsed is unverifiable" "1|unverifiable|unverifiable" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(jq -r .matrix.output_parsing <<< "$OUT")"
gateway "$TMP/gw-1m.jsonl"
M_HOME=$(probe_home probe-1m "$GW_PORT")
sed -i.bak 's/^model = "probe-model"$/model = "probe-model[1m]"/' "$M_HOME/llms.toml"
ptest "$M_HOME" -- llm test pm --json
gateway_stop
assert_eq "test: a model with Claude Code's [1m] suffix matches what the endpoint reports, sent without it" "0|pass|probe-model" \
    "$RC|$(jq -r .matrix.model_identity <<< "$OUT")|$(jq -r .model "$TMP/gw-1m.jsonl" | sort -u | paste -sd, -)"
gateway "$TMP/gw-space.jsonl"
SP_HOME=$(probe_home probe-space "$GW_PORT")
SPACE_TMP="$TMP/a tmp dir"; mkdir -p "$SPACE_TMP"
ptest "$SP_HOME" TMPDIR="$SPACE_TMP" -- llm test pm --json
gateway_stop
assert_eq "test: a TMPDIR with a space in it changes nothing, and nothing is written outside it" "0|pass|0" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(ls -A "$TMP" | grep -c -x 'a')"
gateway "$TMP/gw-settings.jsonl"
ST_HOME=$(probe_home probe-settings "$GW_PORT")
mkdir -p "$TMP/claude-settings"
printf '%s\n' '{"env":{"ANTHROPIC_BASE_URL":"https://elsewhere.example"}}' > "$TMP/claude-settings/settings.json"
ptest "$ST_HOME" CLAUDE_CONFIG_DIR="$TMP/claude-settings" -- llm test pm
assert_eq "test: a settings file that sets the endpoint refuses the test, as it refuses a launch, and nothing is sent (FR-30)" "3|1|0" \
    "$RC|$(grep -c 'a Claude Code settings file sets a variable this test must control' <<< "$OUT")|$(cat "$TMP/gw-settings.jsonl" 2>/dev/null | wc -l | tr -d ' ')"
printf '%s\n' '{"env":{"CLAUDE_CODE_MAX_OUTPUT_TOKENS":"1000"}}' > "$TMP/claude-settings/settings.json"
ptest "$ST_HOME" CLAUDE_CONFIG_DIR="$TMP/claude-settings" -- llm test pm
gateway_stop
assert_eq "test: ...a tuning key in it is said, and the test runs" "0|1" \
    "$RC|$(grep -c 'sets CLAUDE_CODE_MAX_OUTPUT_TOKENS in its env block; Claude Code applies it over this test' <<< "$OUT")"

ptest "$P_HOME" -- llm test cm
assert_eq "test: an unsupported target is refused as a launch refuses it, with nothing run" "3|1" \
    "$RC|$(grep -c "refused: unsupported: endpoint 'chat' speaks openai-chat, claude-code speaks anthropic-messages" <<< "$OUT")"
ptest "$P_HOME" -- llm test cm --json; ERR_TEST_REFUSED="$OUT"
assert_eq "test: ...and under --json, the error envelope and exit 3" "3|test" "$RC|$(jq -r .command <<< "$OUT")"
ptest "$P_HOME" TEST_LLM_KEY= -- llm test pm
assert_eq "test: an unavailable target (its credential unset) is refused too" "3|1" \
    "$RC|$(grep -c 'refused: unavailable: credential variable TEST_LLM_KEY is not set' <<< "$OUT")"
ptest "$P_HOME" -- llm test --json; ERR_TEST_USAGE="$OUT"
assert_eq "test: no target is a usage error" "2|test|usage: cct llm test <target> [--harness <h>] [--without-guard] [--json]" \
    "$RC|$(jq -r .command <<< "$OUT")|$(jq -r .error <<< "$OUT")"
ptest "$P_HOME" -- llm test pm --bogus
assert_eq "test: an unknown option is a usage error" "2|cct llm test: unknown option '--bogus'" "$RC|$OUT"
ptest "$P_HOME" -- llm test pm --harness bogus
assert_eq "test: an unknown harness is a usage error" "2|cct llm test: unknown harness 'bogus' (one of: claude-code, codex, pi, kiro)" "$RC|$OUT"
ptest "$P_HOME" CCT_LLM_PROBE_TIMEOUT_SEC=0 -- llm test pm
assert_eq "test: a watchdog bound that is not a positive number refuses to run" "2|1" \
    "$RC|$(grep -c "CCT_LLM_PROBE_TIMEOUT_SEC='0' is not a positive whole number of seconds" <<< "$OUT")"

gateway "$TMP/gw-ambient.jsonl"
A_HOME=$(probe_home probe-ambient "$GW_PORT")
# The selected credential is the gateway's own sentinel here, so its log
# shows which credential arrived.
ptest "$A_HOME" TEST_LLM_KEY=probe-planted-credential ANTHROPIC_API_KEY=probe-ambient-credential \
    CLAUDE_CODE_USE_BEDROCK=probe-ambient-switch CCT_PROBE_MOCK_ENV_LOG="$TMP/mock-env.json" -- llm test pm --json
gateway_stop
assert_eq "test: the ambient sentinels reach neither the stub gateway nor the stub harness (FR-30)" "0|0|[]|false" \
    "$RC|$(grep -c 'probe-ambient' "$TMP/gw-ambient.jsonl")|$(jq -c .sentinel_values "$TMP/mock-env.json")|$(jq -r '.names | index("CLAUDE_CODE_USE_BEDROCK") != null' "$TMP/mock-env.json")"
assert_eq "test: ...while the selected credential reaches the gateway, as the plan sends it" "yes" \
    "$(grep -q '"authorization": "Bearer probe-planted-credential"' "$TMP/gw-ambient.jsonl" && echo yes || echo no)"
assert_eq "test: no credential value or endpoint path in any output or record" "0" \
    "$(printf '%s\n' "$TEST_PASS" "$TEST_TEXT" "$ERR_TEST_REFUSED" "$(cat "$P_HOME"/llm-compat/claude-code/*.json)" | grep -cF -e "$SECRET" -e "$PATH_TOKEN")"
REDACTED=$(HOME="/home/u-$PATH_TOKEN" bash -c '
    source "$1/scripts/lib/llm-probe.sh"
    LP_SECRET="$2" LP_SECRET_NAME=TEST_LLM_KEY LP_WD=/tmp/cct-llm-probe.X
    _lp_redact "key $2 at /tmp/cct-llm-probe.X/f in $HOME/x"' _ "$REPO_DIR" "$SECRET")
assert_eq "test: the recorded excerpt takes out the credential, the probe directory and the home directory" \
    "key [REDACTED:TEST_LLM_KEY] at <probe-dir>/f in ~/x" "$REDACTED"
assert_eq "test: every run removed its private directory and its handoff record" "0" \
    "$(ls -A "$PROBE_TMP" | grep -c -E '^cct-llm-(probe|test-group)\.')"

# Interrupted, the probe reaps the harness's process group and removes its
# directory (FR-15).
gateway "$TMP/gw-signal.jsonl" --switch time-out
S_HOME=$(probe_home probe-signal "$GW_PORT")
SIG_TMP="$TMP/signal-tmp"; mkdir -p "$SIG_TMP"
( cd "$TMP" && exec env -u CCT_HOME CCT_HOME="$S_HOME" TEST_LLM_KEY="$SECRET" PATH="$TMP/probe-bin:$PATH" TMPDIR="$SIG_TMP" \
    CCT_LLM_PROBE_TIMEOUT_SEC=60 bash "$CCT" llm test pm > "$TMP/signal.out" 2>&1 ) &
SIG_PID=$!
for _ in $(seq 1 100); do grep -q '"reply": "hang"' "$TMP/gw-signal.jsonl" 2>/dev/null && break; sleep 0.1; done
SIG_START=$(date +%s)
kill -TERM "$SIG_PID" 2>/dev/null; SIG_RC=0; wait "$SIG_PID" || SIG_RC=$?
SIG_TOOK=$(( $(date +%s) - SIG_START ))
sleep 0.5
gateway_stop
assert_eq "test: TERM during a run exits 143 at once, not when the 60-second bound ends the run" "143 yes" \
    "$SIG_RC $([[ "$SIG_TOOK" -le 10 ]] && echo yes || echo "no (${SIG_TOOK}s)")"
assert_eq "test: ...with the harness's process group reaped" "0" "$(pgrep -f "$MOCK_HARNESS" | wc -l | tr -d ' ')"
assert_eq "test: ...and nothing left in TMPDIR: the probe's directory, its handoff record, the watchdog's directory" "0" "$(ls -A "$SIG_TMP" | wc -l | tr -d ' ')"
# TERM to the whole process group (a job killed by %1, a CI cancellation)
# reaches the run's subshell too, which must still let the bounded runner
# reap the harness and end its watchdog: a watchdog left alive keeps its
# directory in TMPDIR.
gateway "$TMP/gw-group.jsonl" --switch time-out
GRP_HOME=$(probe_home probe-group "$GW_PORT")
GRP_TMP="$TMP/group-tmp"; mkdir -p "$GRP_TMP"
( cd "$TMP" && exec perl -e 'setpgrp(0, 0); exec @ARGV' env -u CCT_HOME CCT_HOME="$GRP_HOME" TEST_LLM_KEY="$SECRET" \
    PATH="$TMP/probe-bin:$PATH" TMPDIR="$GRP_TMP" CCT_LLM_PROBE_TIMEOUT_SEC=60 \
    bash "$CCT" llm test pm > "$TMP/group.out" 2>&1 ) &
GRP_PID=$!
for _ in $(seq 1 100); do grep -q '"reply": "hang"' "$TMP/gw-group.jsonl" 2>/dev/null && break; sleep 0.1; done
GRP_START=$(date +%s)
kill -TERM -- "-$GRP_PID" 2>/dev/null; GRP_RC=0; wait "$GRP_PID" || GRP_RC=$?
GRP_TOOK=$(( $(date +%s) - GRP_START ))
sleep 0.5
gateway_stop
assert_eq "test: TERM to the whole process group exits 143 at once, the harness reaped and TMPDIR empty" "143 yes 0 0" \
    "$GRP_RC $([[ "$GRP_TOOK" -le 10 ]] && echo yes || echo "no (${GRP_TOOK}s)") $(pgrep -f "$MOCK_HARNESS" | wc -l | tr -d ' ') $(ls -A "$GRP_TMP" | wc -l | tr -d ' ')"

# The watchdog: TERM at the bound, then KILL after a grace that the LLM
# probe sets to ten seconds and routing leaves at two.
WATCH=$( ( source "$REPO_DIR/scripts/lib/conformance-app.sh"; s=$(date +%s)
    ca_run_bounded 1 "trap '' TERM; sleep 30" /dev/null 1; rc=$?; echo "$rc $(( $(date +%s) - s ))" ) )
assert_eq "test: the watchdog kills a harness that ignores TERM once its grace ends" "124 yes" \
    "$(field 1 "$WATCH") $([[ "$(field 2 "$WATCH")" -le 6 ]] && echo yes || echo no)"
WATCH=$( ( source "$REPO_DIR/scripts/lib/conformance-app.sh"; s=$(date +%s)
    ca_run_bounded 1 "trap '' TERM; sleep 30" /dev/null; rc=$?; echo "$rc $(( $(date +%s) - s ))" ) )
assert_eq "test: ...routing's runs keep their two-second grace" "124 yes" \
    "$(field 1 "$WATCH") $([[ "$(field 2 "$WATCH")" -ge 2 && "$(field 2 "$WATCH")" -le 8 ]] && echo yes || echo no)"
assert_eq "test: ...a grace that is not a whole number of seconds refuses to run" "125" \
    "$( ( source "$REPO_DIR/scripts/lib/conformance-app.sh"; ca_run_bounded 1 true /dev/null x 2>/dev/null; echo $? ) )"
gateway "$TMP/gw-grace.jsonl" --switch time-out
GR_HOME=$(probe_home probe-grace "$GW_PORT")
GR_START=$(date +%s)
ptest "$GR_HOME" CCT_LLM_PROBE_TIMEOUT_SEC=1 CCT_PROBE_MOCK_IGNORE_TERM=1 -- llm test pm --json
GR_TOOK=$(( $(date +%s) - GR_START ))
gateway_stop
assert_eq "test: ...and the LLM probe kills a harness that ignores TERM ten seconds after it, the run unverifiable" "1|unverifiable|fail|yes" \
    "$RC|$(jq -r .outcome <<< "$OUT")|$(jq -r .matrix.clean_exit <<< "$OUT")|$([[ "$GR_TOOK" -ge 10 && "$GR_TOOK" -le 30 ]] && echo yes || echo "no (${GR_TOOK}s)")"
ROUTING_PROMPT=$( ( source "$REPO_DIR/scripts/lib/routing-probe.sh"; RB_TOOL_FILE=/tmp/t; rb_prompt 1 CCT_PROBE_OK:abc ) )
assert_eq "test: routing's canary prompt is byte for byte what it was before the shared primitives (D6)" \
    "$(printf 'Health canary. Do BOTH, nothing else:\n1. Run this exact shell command with your Bash tool: printf %%s CCT_TOOL_OK > /tmp/t\n2. Then reply with exactly this single line: CCT_PROBE_OK:abc')" \
    "$ROUTING_PROMPT"

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
SCHEMA_DOCS="$SCHEMA_DOCS SESSIONS SESSIONS_MOVED SESSIONS_PI ERR_SESSIONS TEST_PASS ERR_TEST_REFUSED ERR_TEST_USAGE"
if [[ -n "$PY_SCHEMA" ]]; then
    for doc in $SCHEMA_DOCS; do
        if schema_ok "${!doc}"; then PASS=$((PASS+1)); echo "  PASS: schema: the $doc document";
        else FAIL=$((FAIL+1)); echo "  FAIL: schema: the $doc document does not match $SCHEMA"; fi
    done
    if schema_ok "$(jq -c '. + {targets: []}' <<< "$ERR_MISSING")"; then
        FAIL=$((FAIL+1)); echo "  FAIL: schema: an error envelope that also lists targets must match no form"
    else PASS=$((PASS+1)); echo "  PASS: schema: an error envelope that also lists targets matches no form"; fi
    if schema_ok "$(jq -c '.sessions[0].resume.reason = null' <<< "$SESSIONS_MOVED")"; then
        FAIL=$((FAIL+1)); echo "  FAIL: schema: a session not resumable must say why"
    else PASS=$((PASS+1)); echo "  PASS: schema: a session not resumable must say why"; fi
else
    SCHEMA_SKIPPED=$(( $(wc -w <<< "$SCHEMA_DOCS") + 2 ))
    SKIPPED=$((SKIPPED + SCHEMA_SKIPPED))
    echo "  SKIP: jsonschema not installed — the $SCHEMA_SKIPPED schema checks did not run"
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
mkdir -p "$TMP/broken-wt/sub"; printf 'gitdir: %s\n' "$TMP/no-such-gitdir" > "$TMP/broken-wt/.git"
printf '[llm]\nallowed = ["m2"]\n' > "$TMP/broken-wt/.cct.toml"
cctx "$BASE_HOME" -- harness explain claude-code --llm m --project "$TMP/broken-wt/sub"
assert_exit "explain --project: a work tree git will not name still answers to its top level's .cct.toml" 3 "$RC"
mkdir -p "$TMP/emptygit/.git" "$TMP/emptygit/proj"; printf '[llm]\nallowed = ["m2"]\n' > "$TMP/emptygit/proj/.cct.toml"
cctx "$BASE_HOME" -- harness explain claude-code --llm m --project "$TMP/emptygit/proj"
assert_exit "explain --project: with no repository git accepts, the directory's own .cct.toml still applies" 3 "$RC"
assert_contains "explain --project: ...and the refusal names that file" "$OUT" \
    "is not allowed in this project: $(cd "$TMP/emptygit/proj" && pwd -P)/.cct.toml [llm].allowed lists m2"
# Both files apply: the one above refusing, while the directory's own allows.
mkdir -p "$TMP/emptygit2/.git" "$TMP/emptygit2/proj"
printf '[llm]\nallowed = ["m2"]\n' > "$TMP/emptygit2/.cct.toml"; printf '[llm]\nallowed = ["m"]\n' > "$TMP/emptygit2/proj/.cct.toml"
cctx "$BASE_HOME" -- harness explain claude-code --llm m --project "$TMP/emptygit2/proj"
assert_exit "explain --project: the file above refuses what the directory's own allows" 3 "$RC"
assert_contains "explain --project: ...and the refusal names the file above, the one that refused" "$OUT" \
    "is not allowed in this project: $(cd "$TMP/emptygit2" && pwd -P)/.cct.toml [llm].allowed lists m2"
mkdir -p "$TMP/unreadable-proj"; printf '[llm]\nallowed = ["m"]\n' > "$TMP/unreadable-proj/.cct.toml"; chmod 000 "$TMP/unreadable-proj/.cct.toml"
T="explain --project: a .cct.toml that cannot be read refuses, never reads as no restriction"
if denied -r "$TMP/unreadable-proj/.cct.toml" "$T"; then
    cctx "$BASE_HOME" -- harness explain claude-code --llm m --project "$TMP/unreadable-proj"
    assert_exit "$T" 3 "$RC"
fi

# ── cct help ──
HELP=$(bash "$CCT" help 2>&1)
assert_contains "cct help documents show" "$HELP" "cct llm show <llm>"
assert_contains "cct help documents harness explain" "$HELP" "cct harness explain <harness> --llm <target>"
assert_contains "cct help documents sessions" "$HELP" "cct llm sessions"
assert_contains "cct help documents test" "$HELP" "cct llm test <target>"

echo ""
echo "========================================="
echo "  llm-cli tests: $PASS passed, $FAIL failed$( [[ $SKIPPED -gt 0 ]] && echo ", $SKIPPED skipped")"
echo "========================================="
# A skipped check is not a missing assertion: CI installs jsonschema and
# does not run as root, so it runs all of them.
if [[ "$((PASS + SKIPPED))" -ne "${TEST_LLM_CLI_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_LLM_CLI_EXPECTED_PASS:-0}, got $PASS passed + $SKIPPED skipped)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
