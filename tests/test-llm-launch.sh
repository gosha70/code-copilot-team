#!/usr/bin/env bash
# test-llm-launch.sh — #479: `claude-code --llm <target>`, the per-launch
# LLM selection.
#
# claude, cmux and tmux are stubs. The claude stub records its argv and
# its WHOLE environment, so every assertion is about what the harness
# would actually have received:
#   - without --llm the launch is untouched, ambient variables included;
#   - with --llm the selected variables are set and the competing ones
#     removed, in headless, in-pane and typed (new pane) launches;
#   - a command typed into a multiplexer carries ids only: a planted
#     credential, the endpoint and the model are absent from it;
#   - every refusal happens before claude runs, with exit 3.
# No network, no real multiplexer.
#
# Run from the repo root: bash tests/test-llm-launch.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/test-counts.env"
LAUNCHER="$REPO_DIR/adapters/claude-code/claude-code"

PASS=0; FAIL=0
assert_exit() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$actual" -eq "$expected" ]]; then PASS=$((PASS+1)); echo "  PASS: $name (exit $actual)";
    else FAIL=$((FAIL+1)); echo "  FAIL: $name (expected exit $expected, got $actual)"; echo "${OUTPUT:-}" | sed 's/^/        | /' | head -6; fi
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
MOCK_BIN="$TMP/bin"; FAKE_HOME="$TMP/home"; PROJ="$TMP/proj"
mkdir -p "$MOCK_BIN" "$FAKE_HOME/.cct" "$PROJ"

# claude: argv, cwd and the whole environment.
cat > "$MOCK_BIN/claude" << 'MOCK'
#!/usr/bin/env bash
# A session's stamp records the harness version (#400 FR-17), which the
# launcher asks for before it starts claude: answered here, and logged
# apart from the session launches the assertions read.
if [[ "${1:-}" == "--version" ]]; then
    echo "--version" >> "${MOCK_CLAUDE_LOG:?}.version"
    echo "${MOCK_CLAUDE_VERSION:-2.1.332} (Claude Code)"
    exit 0
fi
{
    printf 'ARGV:'; printf ' %q' "$@"; printf '\n'
    printf 'PWD:%s\n' "$PWD"
    env | sed 's/^/ENV:/'
} >> "${MOCK_CLAUDE_LOG:?}"
echo '{"subtype":"success","result":"mock output"}'
exit 0
MOCK
# cmux: records what the launcher asks it to type.
cat > "$MOCK_BIN/cmux" << 'MOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == "send" ]]; then printf '%s' "${2:-}" >> "${MUX_LOG:?}"; else echo "CMUX:$*" >> "${MUX_LOG:?}.calls"; fi
exit 0
MOCK
# tmux: has-session answers per MOCK_TMUX_HAS_SESSION; new-session
# records the command it is given (its last argument).
cat > "$MOCK_BIN/tmux" << 'MOCK'
#!/usr/bin/env bash
echo "TMUX:$*" >> "${MUX_LOG:?}.calls"
case "${1:-}" in
    has-session) exit "${MOCK_TMUX_HAS_SESSION:-1}" ;;
    new-session) for last; do :; done; printf '%s' "$last" >> "${MUX_LOG:?}" ;;
esac
exit 0
MOCK
chmod +x "$MOCK_BIN/claude" "$MOCK_BIN/cmux" "$MOCK_BIN/tmux"

SECRET="planted-credential-value-do-not-leak"
AMBIENT_KEY="ambient-api-key-nobody-selected"

# The catalog under test: an api endpoint with a credential and a quirk,
# one with no credential, one behind x-api-key, one the harness cannot
# speak to, a managed provider, and a binding with every tuning key.
cat > "$FAKE_HOME/.cct/llms.toml" << 'EOF'
schema_version = 1

[providers.deepseek]
display_name = "DeepSeek"
kind = "api"
credential_mode = "env"
credential_env = "TEST_DEEPSEEK_KEY"

[providers.local]
kind = "api"
credential_mode = "none"

[providers.anthropic]
display_name = "Anthropic"
kind = "managed"
credential_mode = "native"

[endpoints.deepseek]
provider = "deepseek"
protocol = "anthropic-messages"
base_url = "https://api.deepseek.example/anthropic"
auth_header = "bearer"
quirks = ["rejects-dynamic-tools"]

[endpoints.keyed]
provider = "deepseek"
protocol = "anthropic-messages"
base_url = "https://keyed.example"
auth_header = "x-api-key"

[endpoints.local]
provider = "local"
protocol = "anthropic-messages"
base_url = "http://localhost:11434"
auth_header = "none"

[endpoints.responses]
provider = "deepseek"
protocol = "openai-responses"
base_url = "https://responses.example/v1"
auth_header = "bearer"

[llms.deepseek]
provider = "deepseek"
model = "deepseek-main[1m]"

[llms.keyed]
provider = "deepseek"
model = "keyed-model"

[llms.qwen]
provider = "local"
model = "qwen3:27b"

[llms.gpt]
provider = "deepseek"
model = "gpt-x"

[llms.opus]
provider = "anthropic"
model = "opus"

[bindings.deepseek-claude]
harness = "claude-code"
llm = "deepseek"
endpoint = "deepseek"
small_fast_model = "deepseek-small"
max_output_tokens = 32000
auto_compact_window = 786432
reasoning_effort = "max"

[bindings.keyed-claude]
harness = "claude-code"
llm = "keyed"
endpoint = "keyed"

[bindings.qwen-claude]
harness = "claude-code"
llm = "qwen"
endpoint = "local"

[bindings.gpt-claude]
harness = "claude-code"
llm = "gpt"
endpoint = "responses"

[bindings.opus-claude]
harness = "claude-code"
llm = "opus"
EOF

new_logs() { CLAUDE_LOG="$TMP/claude.$RANDOM.$RANDOM.log"; MUX_LOG="$TMP/mux.$RANDOM.$RANDOM.log"; : > "$MUX_LOG"; }

# run_launcher [VAR=value ...] -- <launcher args>
# A clean base environment (no multiplexer, no provider variable), plus
# the given assignments. CCT_REPO_DIR points the launcher at this checkout.
run_launcher() {
    local envs=()
    while [[ $# -gt 0 && "$1" != "--" ]]; do envs+=("$1"); shift; done
    shift
    RC=0
    OUTPUT=$(cd "${RUN_DIR:-$PROJ}" && env -i \
        HOME="$FAKE_HOME" PATH="$MOCK_BIN:$PATH" TERM=dumb SHELL=/bin/bash \
        CCT_REPO_DIR="$REPO_DIR" MOCK_CLAUDE_LOG="$CLAUDE_LOG" MUX_LOG="$MUX_LOG" \
        TEST_DEEPSEEK_KEY="$SECRET" \
        ${envs[@]+"${envs[@]}"} \
        bash "${LAUNCHER_UNDER_TEST:-$LAUNCHER}" "$@" 2>&1) || RC=$?
}
claude_env() {  # <NAME> -> the value claude received, or <unset>
    local line
    line=$(grep -m1 "^ENV:$1=" "$CLAUDE_LOG" 2>/dev/null) || { printf '<unset>'; return 0; }
    printf '%s' "${line#ENV:"$1"=}"
}
claude_ran() { if [[ -f "$CLAUDE_LOG" ]]; then grep -c '^ARGV:' "$CLAUDE_LOG" || true; else echo 0; fi; }

# A shell that carries another provider's whole configuration.
DIRTY=(
    ANTHROPIC_BASE_URL="https://ambient-gateway.example"
    ANTHROPIC_AUTH_TOKEN="ambient-bearer"
    ANTHROPIC_API_KEY="$AMBIENT_KEY"
    ANTHROPIC_MODEL="ambient-model"
    ANTHROPIC_DEFAULT_OPUS_MODEL="ambient-model"
    ANTHROPIC_DEFAULT_SONNET_MODEL="ambient-model"
    ANTHROPIC_DEFAULT_HAIKU_MODEL="ambient-model"
    ANTHROPIC_DEFAULT_FABLE_MODEL="ambient-model"
    ANTHROPIC_SMALL_FAST_MODEL="ambient-model"
    ANTHROPIC_CUSTOM_HEADERS="X-Ambient: 1"
    CLAUDE_CODE_SUBAGENT_MODEL="ambient-model"
    CLAUDE_CODE_USE_BEDROCK="1"
    ANTHROPIC_BEDROCK_BASE_URL="https://bedrock.example"
    CLAUDE_CODE_EFFORT_LEVEL="low"
    CLAUDE_CODE_AUTO_COMPACT_WINDOW="111"
    CLAUDE_CODE_MAX_OUTPUT_TOKENS="222"
    CLAUDE_CODE_OAUTH_TOKEN="ambient-login-token"
    CLAUDE_CODE_USE_GATEWAY="1"
    ANTHROPIC_UNIX_SOCKET="/tmp/ambient.sock"
    CLAUDE_CODE_OAUTH_REFRESH_TOKEN="ambient-refresh-token"
    CLAUDE_CODE_GATEWAY_TOKEN="ambient-gateway-token"
    CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR="7"
    CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR="8"
    CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR="9"
    ANTHROPIC_IDENTITY_TOKEN="ambient-identity-token"
    ANTHROPIC_IDENTITY_TOKEN_FILE="/tmp/ambient-identity-token.jwt"
)
# The other forms of Claude Code's own credentials, and what DIRTY gives each.
OWN_CREDENTIAL_FORMS="CLAUDE_CODE_OAUTH_REFRESH_TOKEN CLAUDE_CODE_GATEWAY_TOKEN CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR ANTHROPIC_IDENTITY_TOKEN ANTHROPIC_IDENTITY_TOKEN_FILE"
ambient_value() {
    case "$1" in
        CLAUDE_CODE_OAUTH_REFRESH_TOKEN) echo "ambient-refresh-token" ;;
        CLAUDE_CODE_GATEWAY_TOKEN) echo "ambient-gateway-token" ;;
        CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR) echo "7" ;;
        CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR) echo "8" ;;
        CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR) echo "9" ;;
        ANTHROPIC_IDENTITY_TOKEN) echo "ambient-identity-token" ;;
        ANTHROPIC_IDENTITY_TOKEN_FILE) echo "/tmp/ambient-identity-token.jwt" ;;
    esac
}

echo "=== --llm launch tests (#479) ==="

# ── Without --llm nothing changes ──
new_logs
run_launcher "${DIRTY[@]}" CCT_REPO_DIR=/nonexistent-checkout CCT_HOME=/nonexistent-home -- -p "native" --output-format json
assert_exit "native: a launch without --llm needs no checkout and no catalog" 0 "$RC"
assert_contains "native: argv is forwarded verbatim" "$(cat "$CLAUDE_LOG")" "ARGV: -p native --output-format json"
assert_eq "native: the ambient base URL is untouched" "https://ambient-gateway.example" "$(claude_env ANTHROPIC_BASE_URL)"
assert_eq "native: the ambient key is untouched" "$AMBIENT_KEY" "$(claude_env ANTHROPIC_API_KEY)"
assert_eq "native: the ambient provider switch is untouched" "1" "$(claude_env CLAUDE_CODE_USE_BEDROCK)"
assert_eq "native: the ambient model is untouched" "ambient-model" "$(claude_env ANTHROPIC_MODEL)"
assert_eq "native: the ambient tuning is untouched" "111" "$(claude_env CLAUDE_CODE_AUTO_COMPACT_WINDOW)"
assert_eq "native: the ambient login token is untouched" "ambient-login-token" "$(claude_env CLAUDE_CODE_OAUTH_TOKEN)"
assert_eq "native: the ambient gateway switch and socket are untouched" "1 /tmp/ambient.sock" "$(claude_env CLAUDE_CODE_USE_GATEWAY) $(claude_env ANTHROPIC_UNIX_SOCKET)"
for _v in $OWN_CREDENTIAL_FORMS; do
    assert_eq "native: ambient $_v is untouched" "$(ambient_value "$_v")" "$(claude_env "$_v")"
done
assert_not_contains "native: no selection notice" "$OUTPUT" "--llm"
# The assertions above have teeth: a launcher whose default target is
# set (the guard removed) fails them.
sed 's/^LLM_TARGET=""$/LLM_TARGET="opus"/' "$LAUNCHER" > "$TMP/mutant-launcher"
new_logs
LAUNCHER_UNDER_TEST="$TMP/mutant-launcher" run_launcher "${DIRTY[@]}" -- -p "native" --output-format json
assert_eq "native: mutation — a launcher that selects by default is caught" "<unset>" "$(claude_env ANTHROPIC_BASE_URL)"

# ── Selected, headless, from a shell configured for something else ──
new_logs
run_launcher "${DIRTY[@]}" -- --llm deepseek -p "hello there" --output-format json
assert_exit "selected: headless --llm launch succeeds" 0 "$RC"
assert_contains "selected: --llm is taken out of claude's argv" "$(grep '^ARGV:' "$CLAUDE_LOG")" " -p hello\\ there --output-format json"
assert_contains "selected: stdout is still pure claude output" "$(echo "$OUTPUT" | grep -v '^\[claude-code\]')" '{"subtype":"success","result":"mock output"}'
assert_eq "selected: the endpoint's base URL" "https://api.deepseek.example/anthropic" "$(claude_env ANTHROPIC_BASE_URL)"
assert_eq "selected: the credential reaches claude as the bearer token" "$SECRET" "$(claude_env ANTHROPIC_AUTH_TOKEN)"
assert_eq "selected: the credential nobody chose is removed" "<unset>" "$(claude_env ANTHROPIC_API_KEY)"
assert_eq "selected: the main model" "deepseek-main[1m]" "$(claude_env ANTHROPIC_MODEL)"
assert_eq "selected: the Opus alias stays on the endpoint, on the main model" "deepseek-main[1m]" "$(claude_env ANTHROPIC_DEFAULT_OPUS_MODEL)"
assert_eq "selected: the Sonnet alias too" "deepseek-main[1m]" "$(claude_env ANTHROPIC_DEFAULT_SONNET_MODEL)"
assert_eq "selected: the Fable alias too" "deepseek-main[1m]" "$(claude_env ANTHROPIC_DEFAULT_FABLE_MODEL)"
assert_eq "selected: the Haiku alias is the small, fast model" "deepseek-small" "$(claude_env ANTHROPIC_DEFAULT_HAIKU_MODEL)"
assert_eq "selected: the small-fast model" "deepseek-small" "$(claude_env ANTHROPIC_SMALL_FAST_MODEL)"
assert_eq "selected: the quirk turns off experimental betas" "1" "$(claude_env CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS)"
assert_eq "selected: the quirk turns off tool search" "false" "$(claude_env ENABLE_TOOL_SEARCH)"
assert_eq "selected: the quirk leaves the feedback command out" "1" "$(claude_env DISABLE_FEEDBACK_COMMAND)"
assert_eq "selected: the binding's output limit" "32000" "$(claude_env CLAUDE_CODE_MAX_OUTPUT_TOKENS)"
assert_eq "selected: the binding's auto-compact window" "786432" "$(claude_env CLAUDE_CODE_AUTO_COMPACT_WINDOW)"
assert_eq "selected: the binding's effort" "max" "$(claude_env CLAUDE_CODE_EFFORT_LEVEL)"
assert_eq "selected: ambient custom headers are removed" "<unset>" "$(claude_env ANTHROPIC_CUSTOM_HEADERS)"
assert_eq "selected: an ambient provider switch is removed" "<unset>" "$(claude_env CLAUDE_CODE_USE_BEDROCK)"
assert_eq "selected: ...with its base URL" "<unset>" "$(claude_env ANTHROPIC_BEDROCK_BASE_URL)"
assert_eq "selected: an ambient subagent model is removed" "<unset>" "$(claude_env CLAUDE_CODE_SUBAGENT_MODEL)"
assert_eq "selected: Claude Code's own login token never reaches an endpoint" "<unset>" "$(claude_env CLAUDE_CODE_OAUTH_TOKEN)"
assert_eq "selected: an ambient gateway switch is removed" "<unset>" "$(claude_env CLAUDE_CODE_USE_GATEWAY)"
assert_eq "selected: an ambient unix-socket transport is removed" "<unset>" "$(claude_env ANTHROPIC_UNIX_SOCKET)"
for _v in $OWN_CREDENTIAL_FORMS; do
    assert_eq "selected: $_v never reaches an endpoint" "<unset>" "$(claude_env "$_v")"
done
assert_contains "selected: the notice names provider, model and origin" "$OUTPUT" "--llm deepseek: DeepSeek · deepseek-main[1m] · https://api.deepseek.example"
assert_not_contains "selected: the notice never carries the URL's path" "$OUTPUT" "deepseek.example/anthropic"
assert_not_contains "selected: the credential is in nothing the launcher prints" "$OUTPUT" "$SECRET"
assert_eq "selected: the credential is in no launcher log" "0" "$(grep -rlF "$SECRET" "$FAKE_HOME/.claude/logs" 2>/dev/null | wc -l | tr -d ' ')"

new_logs
run_launcher -- -p "after" --llm=deepseek
assert_contains "selected: --llm=<target> after -p is honoured" "$(grep '^ARGV:' "$CLAUDE_LOG")" " -p after"
assert_eq "selected: ...and applied" "https://api.deepseek.example/anthropic" "$(claude_env ANTHROPIC_BASE_URL)"

# ── The other credential shapes ──
new_logs
run_launcher "${DIRTY[@]}" -- --llm keyed -p x
assert_eq "x-api-key: the credential is the API key" "$SECRET" "$(claude_env ANTHROPIC_API_KEY)"
assert_eq "x-api-key: an ambient bearer token is removed" "<unset>" "$(claude_env ANTHROPIC_AUTH_TOKEN)"
assert_eq "x-api-key: the file-descriptor form of the key is removed, so only the selected key is read" "<unset>" "$(claude_env CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR)"
assert_eq "no tuning in the binding: ambient tuning is removed, not inherited" "<unset>" "$(claude_env CLAUDE_CODE_AUTO_COMPACT_WINDOW)"
assert_eq "no small model in the binding: every alias is the main model" "keyed-model" "$(claude_env ANTHROPIC_DEFAULT_HAIKU_MODEL)"
assert_eq "no quirk declared: tool search is left alone" "<unset>" "$(claude_env ENABLE_TOOL_SEARCH)"

new_logs
run_launcher "${DIRTY[@]}" -- --llm qwen -p x
assert_eq "no credential: a placeholder token, so Claude Code never sends its own login" "none" "$(claude_env ANTHROPIC_AUTH_TOKEN)"
assert_eq "no credential: an ambient key never reaches the endpoint" "<unset>" "$(claude_env ANTHROPIC_API_KEY)"
assert_eq "no credential: the local base URL" "http://localhost:11434" "$(claude_env ANTHROPIC_BASE_URL)"
assert_eq "no credential: the login token is removed there too" "<unset>" "$(claude_env CLAUDE_CODE_OAUTH_TOKEN)"

# ── A managed provider: Claude Code's own login, from a dirty shell ──
new_logs
run_launcher "${DIRTY[@]}" -- --llm opus -p x
assert_exit "managed: launch succeeds" 0 "$RC"
assert_eq "managed: the model" "opus" "$(claude_env ANTHROPIC_MODEL)"
assert_eq "managed: the gateway base URL is removed" "<unset>" "$(claude_env ANTHROPIC_BASE_URL)"
assert_eq "managed: the gateway bearer token is removed" "<unset>" "$(claude_env ANTHROPIC_AUTH_TOKEN)"
assert_eq "managed: an alias remap is removed" "<unset>" "$(claude_env ANTHROPIC_DEFAULT_OPUS_MODEL)"
assert_eq "managed: ...the Fable one included" "<unset>" "$(claude_env ANTHROPIC_DEFAULT_FABLE_MODEL)"
assert_eq "managed: the small-fast remap is removed" "<unset>" "$(claude_env ANTHROPIC_SMALL_FAST_MODEL)"
assert_eq "managed: the provider switch is removed" "<unset>" "$(claude_env CLAUDE_CODE_USE_BEDROCK)"
assert_eq "managed: the harness's own API key passes through untouched" "$AMBIENT_KEY" "$(claude_env ANTHROPIC_API_KEY)"
assert_eq "managed: Claude Code's own login token passes through too" "ambient-login-token" "$(claude_env CLAUDE_CODE_OAUTH_TOKEN)"
assert_eq "managed: the gateway switch is removed" "<unset>" "$(claude_env CLAUDE_CODE_USE_GATEWAY)"
assert_eq "managed: the unix-socket transport is removed" "<unset>" "$(claude_env ANTHROPIC_UNIX_SOCKET)"
for _v in $OWN_CREDENTIAL_FORMS; do
    assert_eq "managed: $_v passes through, it is the harness's own" "$(ambient_value "$_v")" "$(claude_env "$_v")"
done
assert_contains "managed: the notice says how it signs in" "$OUTPUT" "Anthropic · opus · Claude Code's own login"

# ── Refusals: before claude runs, exit 3, with the reason ──
refused() {  # <name> <expected text> [VAR=value ...] -- <launcher args>
    local name="$1" expected="$2"; shift 2
    new_logs
    run_launcher "$@"
    if [[ "$RC" -eq 3 && "$(claude_ran)" == "0" ]] && echo "$OUTPUT" | grep -qF -- "$expected"; then
        PASS=$((PASS+1)); echo "  PASS: $name"
    else
        FAIL=$((FAIL+1)); echo "  FAIL: $name (exit $RC, claude ran $(claude_ran)x; expected exit 3, no run, and '$expected')"
        echo "$OUTPUT" | sed 's/^/        | /' | head -6
    fi
}
refused "refused: an unknown target" "unknown llm 'ghost'" -- --llm ghost -p x
refused "refused: an endpoint the harness cannot speak to" \
    "gpt@gpt-claude is unsupported on claude-code: endpoint 'responses' speaks openai-responses, claude-code speaks anthropic-messages" -- --llm gpt -p x
refused "refused: a credential variable that is not set" \
    "deepseek@deepseek-claude is unavailable on claude-code: credential variable TEST_DEEPSEEK_KEY is not set" TEST_DEEPSEEK_KEY= -- --llm deepseek -p x
refused "refused: no catalog" "there is no LLM catalog at $TMP/empty-home/llms.toml" CCT_HOME="$TMP/empty-home" -- --llm deepseek -p x
mkdir -p "$TMP/bad-home"
printf 'schema_version = 1\n[providers.p]\nkind = "cloud"\ncredential_mode = "none"\n' > "$TMP/bad-home/llms.toml"
refused "refused: an invalid catalog, with its violations" "kind 'cloud' is not accepted" CCT_HOME="$TMP/bad-home" -- --llm deepseek -p x
refused "refused: the interactive path too, before any multiplexer" "unknown llm 'ghost'" -- --shell cmux --llm ghost "$PROJ"
assert_eq "refused: ...nothing was typed" "" "$(cat "$MUX_LOG")"
cp "$LAUNCHER" "$TMP/orphan-launcher"
new_logs
LAUNCHER_UNDER_TEST="$TMP/orphan-launcher" run_launcher CCT_REPO_DIR= -- --llm deepseek -p x
assert_exit "refused: a launcher that cannot find its checkout" 3 "$RC"
assert_contains "refused: ...names both remedies" "$OUTPUT" "Set CCT_REPO_DIR to your checkout"

# A settings env block would override the selection (Claude Code applies
# it over the environment it is started with): refused by file and name.
mkdir -p "$FAKE_HOME/.claude"
printf '{"env": {"ANTHROPIC_BASE_URL": "https://settings.example", "HOOK_X": "1"}}\n' > "$FAKE_HOME/.claude/settings.json"
refused "refused: a user settings env block that sets a selected variable" "$FAKE_HOME/.claude/settings.json: ANTHROPIC_BASE_URL" -- --llm deepseek -p x
assert_not_contains "refused: ...an unrelated settings key is not named" "$OUTPUT" "HOOK_X"
assert_not_contains "refused: ...and the settings value is not printed" "$OUTPUT" "settings.example"
printf '{"env": {"HOOK_X": "1"}}\n' > "$FAKE_HOME/.claude/settings.json"
mkdir -p "$PROJ/.claude"
printf '{"env": {"CLAUDE_CODE_USE_BEDROCK": "1"}}\n' > "$PROJ/.claude/settings.local.json"
refused "refused: a project settings env block that sets a removed variable" "$PROJ/.claude/settings.local.json: CLAUDE_CODE_USE_BEDROCK" -- --llm deepseek -p x
rm -f "$PROJ/.claude/settings.local.json"
new_logs
run_launcher -- --llm deepseek -p x
assert_exit "settings: an env block with unrelated keys does not refuse" 0 "$RC"

# Tuning in a settings file is said, not refused: it changes how the
# session behaves on its target, never which target it reaches.
SETTINGS="$FAKE_HOME/.claude/settings.json"
printf '{"env": {"CLAUDE_CODE_EFFORT_LEVEL": "high", "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "1", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "2", "HOOK_X": "1"}}\n' > "$SETTINGS"
new_logs
run_launcher -- --llm opus -p x
assert_exit "settings: tuning variables in an env block do not refuse" 0 "$RC"
assert_eq "settings: ...claude runs" "1" "$(claude_ran)"
assert_contains "settings: ...the effort level is noted, by file and name" "$OUTPUT" "note: $SETTINGS sets CLAUDE_CODE_EFFORT_LEVEL in its env block"
assert_contains "settings: ...the auto-compact window too" "$OUTPUT" "note: $SETTINGS sets CLAUDE_CODE_AUTO_COMPACT_WINDOW in its env block"
assert_contains "settings: ...and the output limit" "$OUTPUT" "note: $SETTINGS sets CLAUDE_CODE_MAX_OUTPUT_TOKENS in its env block"
assert_contains "settings: ...the notice says whose value the session uses" "$OUTPUT" "so that value is the one the session uses"
assert_not_contains "settings: ...an unrelated key is not noted" "$OUTPUT" "HOOK_X"
assert_not_contains "settings: ...and nothing is refused" "$OUTPUT" "refused"
# The same when the binding itself sets the variable.
new_logs
run_launcher -- --llm deepseek -p x
assert_exit "settings: a tuning variable the binding sets is noted too, not refused" 0 "$RC"
assert_contains "settings: ...by file and name" "$OUTPUT" "note: $SETTINGS sets CLAUDE_CODE_EFFORT_LEVEL in its env block"
# Beside a model variable the launch is still refused, for the model variable.
printf '{"env": {"CLAUDE_CODE_EFFORT_LEVEL": "high", "ANTHROPIC_MODEL": "another-model"}}\n' > "$SETTINGS"
refused "settings: tuning beside a model variable is still refused" "$SETTINGS: ANTHROPIC_MODEL" -- --llm opus -p x
assert_not_contains "settings: ...and the tuning variable is not among the refused" "$(echo "$OUTPUT" | grep '^    ')" "CLAUDE_CODE_EFFORT_LEVEL"
# Credential and transport variables are refused like routing ones.
printf '{"env": {"CLAUDE_CODE_OAUTH_TOKEN": "settings-login-token"}}\n' > "$SETTINGS"
refused "settings: a login token in an env block is refused for an endpoint target" "$SETTINGS: CLAUDE_CODE_OAUTH_TOKEN" -- --llm deepseek -p x
assert_not_contains "settings: ...its value is not printed" "$OUTPUT" "settings-login-token"
new_logs
run_launcher -- --llm opus -p x
assert_exit "settings: ...and is the harness's own business on a managed target" 0 "$RC"
printf '{"env": {"CLAUDE_CODE_USE_GATEWAY": "1"}}\n' > "$SETTINGS"
refused "settings: a gateway switch in an env block is refused" "$SETTINGS: CLAUDE_CODE_USE_GATEWAY" -- --llm opus -p x
printf '{"env": {"ANTHROPIC_UNIX_SOCKET": "/tmp/settings.sock"}}\n' > "$SETTINGS"
refused "settings: a unix-socket transport in an env block is refused" "$SETTINGS: ANTHROPIC_UNIX_SOCKET" -- --llm opus -p x
printf '{"env": {"CLAUDE_CODE_GATEWAY_TOKEN": "settings-gateway-token"}}\n' > "$SETTINGS"
refused "settings: a gateway token in an env block is refused for an endpoint target" "$SETTINGS: CLAUDE_CODE_GATEWAY_TOKEN" -- --llm deepseek -p x
new_logs
run_launcher -- --llm opus -p x
assert_exit "settings: ...and is the harness's own business on a managed target" 0 "$RC"
printf '{"env": {"ANTHROPIC_IDENTITY_TOKEN": "settings-identity-token"}}\n' > "$SETTINGS"
refused "settings: an identity token in an env block is refused for an endpoint target" "$SETTINGS: ANTHROPIC_IDENTITY_TOKEN" -- --llm deepseek -p x
new_logs
run_launcher -- --llm opus -p x
assert_exit "settings: ...and is the harness's own business on a managed target" 0 "$RC"
printf '{"env": {"HOOK_X": "1"}}\n' > "$SETTINGS"

# ── Usage errors ──
new_logs; run_launcher -- --llm
assert_exit "usage: --llm needs a target" 1 "$RC"
new_logs; run_launcher -- --llm deepseek init web-static
assert_exit "usage: --llm does not apply to a wrapper subcommand" 1 "$RC"
assert_contains "usage: ...and says so" "$OUTPUT" "--llm selects the LLM for a session; it does not apply to 'init'"

# ── Interactive, already inside a multiplexer: this process becomes claude ──
new_logs
run_launcher "${DIRTY[@]}" CMUX_WORKSPACE_ID=1 -- --llm deepseek "$PROJ"
assert_exit "in-pane: launch succeeds" 0 "$RC"
assert_eq "in-pane: claude ran once, in the project" "$PROJ" "$(grep -m1 '^PWD:' "$CLAUDE_LOG" | sed 's/^PWD://')"
assert_contains "in-pane: claude gets no --llm" "$(grep '^ARGV:' "$CLAUDE_LOG")" "ARGV:"
assert_not_contains "in-pane: ...none at all" "$(grep '^ARGV:' "$CLAUDE_LOG")" "llm"
assert_eq "in-pane: the selection is applied" "https://api.deepseek.example/anthropic" "$(claude_env ANTHROPIC_BASE_URL)"
assert_eq "in-pane: the ambient key is removed" "<unset>" "$(claude_env ANTHROPIC_API_KEY)"
assert_eq "in-pane: nothing was typed into a multiplexer" "" "$(cat "$MUX_LOG")"

new_logs
run_launcher CMUX_WORKSPACE_ID=1 -- --peer-review deepseek --llm opus "$PROJ"
assert_eq "in-pane: peer review and --llm compose" "true opus" "$(claude_env CCT_PEER_REVIEW_ENABLED) $(claude_env ANTHROPIC_MODEL)"

# ── Interactive, a new cmux workspace: the typed command carries ids only ──
new_logs
run_launcher "${DIRTY[@]}" -- --shell cmux --verbose --llm deepseek "$PROJ"
assert_exit "typed: launch succeeds" 0 "$RC"
TYPED=$(cat "$MUX_LOG")
assert_eq "typed: the outer launcher does not run claude" "0" "$(claude_ran)"
assert_contains "typed: the banner says which LLM was selected" "$OUTPUT" "LLM:     deepseek (DeepSeek · deepseek-main[1m] · https://api.deepseek.example)"
assert_contains "typed: the command names the target" "$TYPED" "--llm deepseek"
assert_contains "typed: ...re-runs this launcher in the pane" "$TYPED" "CCT_LLM_CHILD=1 $LAUNCHER --llm deepseek --verbose"
assert_contains "typed: ...in the project" "$TYPED" "cd $PROJ && exec env"
assert_not_contains "typed: the credential is not typed" "$TYPED" "$SECRET"
assert_not_contains "typed: the endpoint is not typed" "$TYPED" "deepseek.example"
assert_not_contains "typed: the model is not typed" "$TYPED" "deepseek-main"
assert_not_contains "typed: no provider variable is typed" "$TYPED" "ANTHROPIC_"
# ...and the pane, running exactly what was typed, becomes the session.
pane() {  # [VAR=value ...] : runs $TYPED as the pane's shell would
    RC=0
    OUTPUT=$(env -i HOME="$FAKE_HOME" PATH="$MOCK_BIN:$PATH" TERM=dumb SHELL=/bin/bash \
        CCT_REPO_DIR="$REPO_DIR" MOCK_CLAUDE_LOG="$CLAUDE_LOG" MUX_LOG="$MUX_LOG" \
        TEST_DEEPSEEK_KEY="$SECRET" "$@" bash -c "$TYPED" 2>&1) || RC=$?
}
pane "${DIRTY[@]}"
assert_exit "typed: the pane's command runs" 0 "$RC"
assert_contains "typed: claude gets the forwarded flag and no --llm" "$(grep '^ARGV:' "$CLAUDE_LOG")" "ARGV: --verbose"
assert_eq "typed: the pane applies the selection" "https://api.deepseek.example/anthropic" "$(claude_env ANTHROPIC_BASE_URL)"
assert_eq "typed: the credential is read in the pane" "$SECRET" "$(claude_env ANTHROPIC_AUTH_TOKEN)"
assert_eq "typed: the ambient key is removed in the pane" "<unset>" "$(claude_env ANTHROPIC_API_KEY)"
assert_eq "typed: the pane marker does not reach claude" "<unset>" "$(claude_env CCT_LLM_CHILD)"
assert_eq "typed: the session runs in the project" "$PROJ" "$(grep -m1 '^PWD:' "$CLAUDE_LOG" | sed 's/^PWD://')"

new_logs
run_launcher -- --shell cmux --peer-review deepseek --llm opus "$PROJ"
TYPED=$(cat "$MUX_LOG")
assert_contains "typed: peer review rides along as before" "$TYPED" "CCT_PEER_REVIEW_ENABLED=true CCT_PEER_PROVIDER=deepseek"
assert_contains "typed: ...next to the pane marker and the target" "$TYPED" "CCT_LLM_CHILD=1"
pane
assert_eq "typed: the pane has both" "true opus" "$(claude_env CCT_PEER_REVIEW_ENABLED) $(claude_env ANTHROPIC_MODEL)"

# A project path cannot hijack the typed command.
HOSTILE="$TMP/it's a \"dir\"; touch $TMP/CANARY; \$(touch $TMP/CANARY2)"
mkdir -p "$HOSTILE"
new_logs
run_launcher -- --shell cmux --llm opus "$HOSTILE"
TYPED=$(cat "$MUX_LOG")
pane
assert_exit "hostile path: the typed command still runs" 0 "$RC"
assert_eq "hostile path: claude starts in exactly that directory" "$HOSTILE" "$(grep -m1 '^PWD:' "$CLAUDE_LOG" | sed 's/^PWD://')"
assert_eq "hostile path: no second command ran" "no" "$([[ -e "$TMP/CANARY" || -e "$TMP/CANARY2" ]] && echo yes || echo no)"
NEWLINE_DIR="$TMP/line"$'\n'"break"
mkdir -p "$NEWLINE_DIR"
refused "hostile path: a newline in it is refused before typing" "the project path holds a control character" -- --shell cmux --llm opus "$NEWLINE_DIR"
assert_eq "hostile path: ...nothing was typed" "" "$(cat "$MUX_LOG")"
assert_contains "hostile path: ...and the remedy is a launch that types nothing" "$OUTPUT" "from inside a cmux or tmux pane"

# The flags forwarded to claude and the launcher's own path are typed too.
NEWLINE_ARG="--append-system-prompt=two"$'\n'"lines"
refused "hostile argument: a forwarded flag with a newline is refused before typing" \
    "the argument forwarded to claude holds a control character" -- --shell cmux --llm opus "$NEWLINE_ARG" "$PROJ"
assert_eq "hostile argument: ...nothing was typed" "" "$(cat "$MUX_LOG")"
refused "hostile argument: ...and before a tmux session is created" \
    "the argument forwarded to claude holds a control character" -- --shell tmux --llm opus "$NEWLINE_ARG" "$PROJ"
assert_not_contains "hostile argument: ...no session was created" "$(cat "$MUX_LOG.calls" 2>/dev/null)" "new-session"
# Inside a pane nothing is typed, so the same flag is an argument like any other.
new_logs
run_launcher CMUX_WORKSPACE_ID=1 -- --llm opus "$NEWLINE_ARG" "$PROJ"
assert_exit "hostile argument: inside a pane it is not typed, so it is not refused" 0 "$RC"
assert_contains "hostile argument: ...and claude receives it" "$(grep '^ARGV:' "$CLAUDE_LOG")" "append-system-prompt=two"
ODD_DIR="$TMP/odd"$'\n'"launcher"
mkdir -p "$ODD_DIR"
cp "$LAUNCHER" "$ODD_DIR/claude-code"
LAUNCHER_UNDER_TEST="$ODD_DIR/claude-code" refused "hostile launcher path: refused before typing" \
    "the launcher's own path holds a control character" -- --shell cmux --llm opus "$PROJ"
assert_eq "hostile launcher path: ...nothing was typed" "" "$(cat "$MUX_LOG")"

# Every kind of control character is refused, not only a newline: the
# C0 controls, DEL, and the C1 controls in their UTF-8 form.
control_refused() {  # <label> <the character>
    local dir="$TMP/ctl-$1-a$2b"
    mkdir -p "$dir"
    refused "control character: $1 in the project path is refused before typing" \
        "the project path holds a control character" -- --shell cmux --llm opus "$dir"
}
control_refused "a tab" $'\t'
control_refused "a carriage return" $'\r'
control_refused "an escape" $'\033'
control_refused "DEL" $'\177'
control_refused "a C1 control (U+009B)" $'\302\233'
ESC_ARG="--append-system-prompt=red"$'\033'"[31m"
refused "control character: an escape in a forwarded flag is refused before typing" \
    "the argument forwarded to claude holds a control character" -- --shell cmux --llm opus "$ESC_ARG" "$PROJ"

# Printable non-ASCII is NOT a control character. bash writes it as
# $'…' when it types the command; the pane's shell reads that back.
INTL_DIR="$TMP/café 日本語 dir"
INTL_ARG="--append-system-prompt=naïve 日本"
mkdir -p "$INTL_DIR"
new_logs
run_launcher -- --shell cmux --llm opus "$INTL_ARG" "$INTL_DIR"
assert_exit "non-ASCII: a printable non-ASCII path and flag are typed, not refused" 0 "$RC"
TYPED=$(cat "$MUX_LOG")
assert_contains "non-ASCII: ...in the form the shell reads back" "$TYPED" "\$'"
pane
assert_exit "non-ASCII: the pane runs what was typed" 0 "$RC"
assert_eq "non-ASCII: claude starts in exactly that directory" "$INTL_DIR" "$(grep -m1 '^PWD:' "$CLAUDE_LOG" | sed 's/^PWD://')"
assert_contains "non-ASCII: ...and receives the flag byte for byte" "$(grep '^ARGV:' "$CLAUDE_LOG")" \
    "$(LC_ALL=C bash -c 'printf "%q" "$1"' _ "$INTL_ARG")"

# ── Interactive, a new tmux session ──
new_logs
run_launcher "${DIRTY[@]}" -- --shell tmux --llm deepseek "$PROJ"
assert_exit "tmux: launch succeeds" 0 "$RC"
TYPED=$(cat "$MUX_LOG")
assert_contains "tmux: the session command re-runs this launcher with the target" "$TYPED" "env CCT_LLM_CHILD=1 $LAUNCHER --llm deepseek"
assert_not_contains "tmux: the credential is not in the session command" "$TYPED" "$SECRET"
assert_not_contains "tmux: ...nor in any tmux call" "$(cat "$MUX_LOG.calls")" "$SECRET"
RUN_IN="$PROJ"
RC=0; OUTPUT=$(cd "$RUN_IN" && env -i HOME="$FAKE_HOME" PATH="$MOCK_BIN:$PATH" TERM=dumb SHELL=/bin/bash \
    CCT_REPO_DIR="$REPO_DIR" MOCK_CLAUDE_LOG="$CLAUDE_LOG" MUX_LOG="$MUX_LOG" TEST_DEEPSEEK_KEY="$SECRET" \
    bash -c "$TYPED" 2>&1) || RC=$?
assert_eq "tmux: the session command applies the selection" "https://api.deepseek.example/anthropic" "$(claude_env ANTHROPIC_BASE_URL)"
# An existing session runs whatever it was started with: never attached to.
refused "tmux: an existing session is refused, not attached to" "already exists, and attaching to it would not apply the selection" \
    MOCK_TMUX_HAS_SESSION=0 -- --shell tmux --llm deepseek "$PROJ"
assert_not_contains "tmux: ...and never killed" "$(cat "$MUX_LOG.calls")" "kill-session"
assert_not_contains "tmux: ...nor attached" "$(cat "$MUX_LOG.calls")" "attach-session"

# ── Help ──
assert_contains "help documents --llm" "$(bash "$LAUNCHER" help 2>&1)" "--llm <target>"

# ── A launch and its explanation agree (#400 S1): one resolver ──
# From a shell carrying another provider's whole configuration: every
# variable `cct harness explain` says the launch sets reaches claude, and
# every one it says the launch removes is absent from claude's environment.
new_logs
run_launcher "${DIRTY[@]}" -- --llm deepseek -p x
EXPLAIN_JSON=$(cd "$PROJ" && env -i HOME="$FAKE_HOME" PATH="$MOCK_BIN:$PATH" TEST_DEEPSEEK_KEY="$SECRET" \
    "${DIRTY[@]}" bash "$REPO_DIR/scripts/cct" harness explain claude-code --llm deepseek --json 2>/dev/null)
# Each list must be non-empty, so an explanation that failed cannot pass.
AGREE_SET=0
while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    if [[ "$(claude_env "$name")" == "<unset>" ]]; then AGREE_SET=-1; break; fi
    AGREE_SET=1
done <<< "$(jq -r '.env_names[] | select(.set) | .name' <<< "$EXPLAIN_JSON" 2>/dev/null)"
assert_eq "explain and launch agree: what explain says is set reaches claude" 1 "$AGREE_SET"
AGREE_CLEAR=0
while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    if [[ "$(claude_env "$name")" != "<unset>" ]]; then AGREE_CLEAR=-1; break; fi
    AGREE_CLEAR=1
done <<< "$(jq -r '.env_clear[]' <<< "$EXPLAIN_JSON" 2>/dev/null)"
assert_eq "explain and launch agree: what explain says is removed is absent from claude" 1 "$AGREE_CLEAR"

# ── a project's [llm] restriction (#400 FR-24, D13; S5) ──
PROJ_ROOT=$(cd "$PROJ" && pwd -P)   # the launcher names the physical path
printf '[llm]\nallowed = ["opus"]\n' > "$PROJ/.cct.toml"
refused "project policy: a target the project does not list is refused" \
    "--llm deepseek is not allowed in this project: $PROJ_ROOT/.cct.toml [llm].allowed lists opus" -- --llm deepseek -p x
new_logs; run_launcher -- --llm opus -p x
assert_eq "project policy: a listed target launches" "0:1" "$RC:$(claude_ran)"
refused "project policy: the interactive path refuses before any multiplexer" "is not allowed in this project" \
    -- --shell cmux --llm deepseek "$PROJ"
assert_eq "project policy: ...nothing was typed" "" "$(cat "$MUX_LOG")"
printf '[llm]\nallowed = ["opus"]\ndefault = "opus"\n' > "$PROJ/.cct.toml"
refused "project policy: a key that would grant is refused by name" \
    "[llm].default is not accepted: projects restrict, never grant" -- --llm opus -p x
new_logs; run_launcher -- -p "native"
assert_eq "project policy: a launch without --llm never reads it" "0:1" "$RC:$(claude_ran)"
rm -f "$PROJ/.cct.toml"; printf '[llm]\nallowed = ["opus"]\n' > "$PROJ/.cct.local.toml"
new_logs; run_launcher -- --llm deepseek -p x
assert_eq "project policy: .cct.local.toml is never read" "0:1" "$RC:$(claude_ran)"
printf '[llm]\nallowed = ["opus"]\n' > "$PROJ/.cct.toml"; printf '[llm]\nallowed = ["deepseek"]\n' > "$PROJ/.cct.local.toml"
refused "project policy: ...so a personal file cannot widen the committed list" \
    "--llm deepseek is not allowed in this project" -- --llm deepseek -p x
rm -f "$PROJ/.cct.toml" "$PROJ/.cct.local.toml"
LOCKED="$TMP/locked-proj"; mkdir -p "$LOCKED"; chmod 000 "$LOCKED"
T1="project policy: an interactive launch into a directory it cannot enter is refused"
T2="project policy: ...nothing was typed"
if denied -x "$LOCKED" "$T1" "$T2"; then
    refused "$T1" "cannot enter $LOCKED, so its project's restriction cannot be read" -- --shell cmux --llm deepseek "$LOCKED"
    assert_eq "$T2" "" "$(cat "$MUX_LOG")"
fi
chmod 700 "$LOCKED"

# ── Sessions and resume (#400 S4: FR-17, FR-18, FR-19, D9) ──
STAMPS="$FAKE_HOME/.cct/llm-sessions/claude-code"
REAL_PROJ=$(cd "$PROJ" && pwd -P)
UUID_RE='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
session_of() { grep '^ARGV:' "$CLAUDE_LOG" | tail -1 | grep -oE -- '--session-id [0-9a-f-]{36}' | awk '{print $2}'; }
stamp() { cat "$STAMPS/$1.json" 2>/dev/null; }
file_mode() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }

new_logs
run_launcher -- --llm deepseek -p "a new session"
S1=$(session_of)
assert_exit "sessions: a new --llm session starts" 0 "$RC"
assert_eq "sessions: claude gets a session id the launcher generated (D9)" "yes" "$([[ "$S1" =~ $UUID_RE ]] && echo yes || echo no)"
assert_eq "sessions: its stamp is attempted, for the resolved target (FR-17)" "attempted deepseek@deepseek-claude deepseek-main[1m] anthropic-messages 2.1.332" \
    "$(stamp "$S1" | jq -r '"\(.status) \(.llm)@\(.binding) \(.requested_model) \(.protocol) \(.harness_version)"')"
assert_eq "sessions: ...with the three digests, the evidence digest and the compatibility state" "4 unverified" \
    "$(stamp "$S1" | jq -r '"\([.digests[] | select(. != null)] | length) \(.compatibility.state)"')"
assert_eq "sessions: ...no gate yet, the project, and no effective model before the harness's evidence" "none yet false $REAL_PROJ null" \
    "$(stamp "$S1" | jq -r '"\(.gate.state) \(.gate.bypassed) \(.project) \(.effective_model)"')"
assert_eq "sessions: ...and the names the launch cleared, as explain lists them (FR-30)" \
    "$(jq -c .env_clear <<< "$EXPLAIN_JSON")" "$(stamp "$S1" | jq -c .env_clear)"
assert_not_contains "sessions: the stamp holds no credential value" "$(stamp "$S1")" "$SECRET"
assert_eq "sessions: the stamp is private" "600" "$(file_mode "$STAMPS/$S1.json")"
assert_contains "sessions: the session id is said, to resume it by" "$OUTPUT" "session $S1 (resume it with --resume $S1)"

# D9: the launcher chooses the id. A --session-id naming an existing session
# would have that session's stamp replaced before claude refused the id.
cp "$STAMPS/$S1.json" "$TMP/s1.saved"
refused "sessions: a --session-id with --llm is refused: the launcher generates the id (D9)" \
    "--session-id is not accepted with --llm" -- --llm opus -p x --session-id "$S1"
assert_eq "sessions: ...and the stamp of the session it names is untouched" "same" \
    "$(cmp -s "$STAMPS/$S1.json" "$TMP/s1.saved" && echo same || echo changed)"
refused "sessions: ...in its --session-id=<id> form too, saying to drop it" "Drop --session-id" -- --llm opus -p x "--session-id=$S1"
refused "sessions: a bare --continue with --llm is refused (FR-18)" "--continue resumes whichever session Claude Code picks" -- --llm deepseek -p x --continue
# Claude Code acts on --continue before --resume, and on --teleport and
# --from-pr before --resume too (2.1.332).
refused "sessions: ...and so is --continue beside --resume <id>, which Claude Code acts on first" \
    "--continue resumes whichever session Claude Code picks (it wins over --resume)" -- --llm deepseek -p x --resume "$S1" --continue
refused "sessions: ...and --from-pr, a session Claude Code finds for itself" \
    "--from-pr resumes a session Claude Code finds for itself" -- --llm deepseek -p x --from-pr 12
refused "sessions: ...and --teleport" "--teleport resumes a session Claude Code finds for itself" -- --llm deepseek -p x --teleport=remote-1
refused "sessions: ...and so is the resume picker" "the resume picker lets Claude Code choose the session" -- --llm deepseek -p x --resume
refused "sessions: ...and a session named rather than given by its id" "the resume picker lets Claude Code choose the session" -- --llm deepseek -p x --resume my-session

C1=$(stamp "$S1" | jq -r .created_at)
# The reply Claude Code's transcript records for the session (S4's capture:
# the project's directory is its path, every other character a dash).
TRANSCRIPTS="$FAKE_HOME/.claude/projects/$(printf '%s' "$REAL_PROJ" | sed 's/[^A-Za-z0-9]/-/g')"
mkdir -p "$TRANSCRIPTS"
printf '%s\n' '{"type":"assistant","message":{"role":"assistant","model":"deepseek-main"}}' > "$TRANSCRIPTS/$S1.jsonl"
# A stamp whose list of cleared names went stale (written by an older
# launcher): the refresh writes this launch's list (FR-30).
jq -c '.env_clear = ["STALE_NAME"] | .refreshed_at = "2026-01-01T00:00:00Z"' "$STAMPS/$S1.json" > "$TMP/s1.stale"
cat "$TMP/s1.stale" > "$STAMPS/$S1.json"
new_logs
run_launcher -- --llm deepseek -p again --resume "$S1"
assert_exit "sessions: resumed by its id with its own target" 0 "$RC"
assert_eq "sessions: ...claude resumes that id, and no new id is added" "1 0" \
    "$(grep '^ARGV:' "$CLAUDE_LOG" | grep -c -- "--resume $S1") $(grep '^ARGV:' "$CLAUDE_LOG" | grep -c -- '--session-id')"
assert_eq "sessions: ...and the stamp is refreshed, its creation time kept" "$C1 yes" \
    "$(stamp "$S1" | jq -r '"\(.created_at) \(if .refreshed_at != "2026-01-01T00:00:00Z" then "yes" else "no" end)"')"
assert_eq "sessions: ...and established from the transcript's reply, with the model it names (FR-17)" "established deepseek-main" \
    "$(stamp "$S1" | jq -r '"\(.status) \(.effective_model)"')"
assert_eq "sessions: ...and its list of cleared names is this launch's" \
    "$(jq -c .env_clear <<< "$EXPLAIN_JSON")" "$(stamp "$S1" | jq -c .env_clear)"
refused "sessions: resumed with another target, refused, naming both (FR-18)" \
    "session $S1 was started with deepseek@deepseek-claude, not opus@opus-claude" -- --llm opus -p x --resume "$S1"
new_logs
run_launcher -- --llm deepseek -p again "-r$S1"
assert_eq "sessions: -r<id> as one argument is a resume by that id too, with no new id" "0 1 0" \
    "$RC $(grep '^ARGV:' "$CLAUDE_LOG" | grep -c -- "-r$S1") $(grep '^ARGV:' "$CLAUDE_LOG" | grep -c -- '--session-id')"
new_logs; run_launcher -- --llm deepseek -p hi --append-system-prompt "-respond tersely"; RA="$RC:$(claude_ran)"
new_logs; run_launcher -- --llm deepseek -p -- "-rewrite the README"; RB="$RC:$(claude_ran)"
assert_eq "sessions: an option's value or a prompt after -- that starts with -r is text, not a resume" "0:1 0:1" "$RA $RB"

new_logs
run_launcher "${DIRTY[@]}" -- -p "restore" --resume "$S1"
assert_exit "sessions: resumed by its id without --llm" 0 "$RC"
assert_contains "sessions: ...its stamped target is restored, and said" "$OUTPUT" "session $S1 was started with --llm deepseek@deepseek-claude: resuming it on that target"
assert_eq "sessions: ...and applied over the shell's own" "https://api.deepseek.example/anthropic" "$(claude_env ANTHROPIC_BASE_URL)"
new_logs
run_launcher "${DIRTY[@]}" -- -p y --resume "$S1" -c
assert_eq "sessions: without --llm, --continue beside --resume <id> restores nothing, and says what it does not check" \
    "no 1 https://ambient-gateway.example" \
    "$(grep -q 'resuming it on' <<< "$OUTPUT" && echo yes || echo no) $(grep -c 'this resumes whichever session Claude Code picks' <<< "$OUTPUT") $(claude_env ANTHROPIC_BASE_URL)"
new_logs
run_launcher "${DIRTY[@]}" -- -p fork-native --resume "$S1" --fork-session
assert_eq "sessions: a fork without --llm is a new native session: nothing restored, no id added" \
    "no https://ambient-gateway.example 0" \
    "$(grep -q 'resuming it on' <<< "$OUTPUT" && echo yes || echo no) $(claude_env ANTHROPIC_BASE_URL) $(grep '^ARGV:' "$CLAUDE_LOG" | grep -c -- '--session-id')"
NOSTAMP=99999999-8888-7777-6666-555555555555
new_logs
run_launcher "${DIRTY[@]}" -- -p native --resume "$NOSTAMP"
assert_eq "sessions: a session without a stamp resumes natively, unchanged" "https://ambient-gateway.example" "$(claude_env ANTHROPIC_BASE_URL)"
assert_not_contains "sessions: ...with nothing restored" "$OUTPUT" "resuming it on"
assert_eq "sessions: ...no id added, and no stamp written" "0 no" \
    "$(grep '^ARGV:' "$CLAUDE_LOG" | grep -c -- '--session-id') $([[ -e "$STAMPS/$NOSTAMP.json" ]] && echo yes || echo no)"
refused "sessions: a session without a stamp is refused with --llm" "session $NOSTAMP has no stamp" -- --llm deepseek -p x --resume "$NOSTAMP"
assert_eq "sessions: ...naming the ways out: resume it without --llm, or fork it" "1 1" \
    "$(grep -c 'Resume it without --llm' <<< "$OUTPUT") $(grep -cF -- "--resume $NOSTAMP --fork-session --llm deepseek@deepseek-claude" <<< "$OUTPUT")"

# The minimum version and the records are read for the stamp's compatibility
# state only: before S3's gate no launch is refused on the state, and a
# record that cannot be read refuses the launch by name, since the stamp
# cannot be written (FR-17, FR-29).
new_logs
run_launcher MOCK_CLAUDE_VERSION=2.1.300 -- --llm deepseek -p old
OLD=$(session_of)
assert_eq "sessions: a claude older than the minimum still launches before S3's gate; its stamp says unavailable" \
    "0:1 unavailable" "$RC:$(claude_ran) $(stamp "$OLD" | jq -r .compatibility.state)"
COMPAT_REC="$FAKE_HOME/.cct/llm-compat/claude-code/deepseek@deepseek-claude.json"
mkdir -p "$(dirname "$COMPAT_REC")"; chmod 700 "$FAKE_HOME/.cct/llm-compat" "$(dirname "$COMPAT_REC")"
printf 'not a record' > "$COMPAT_REC"; chmod 600 "$COMPAT_REC"
refused "sessions: a compatibility record that cannot be read refuses the launch, naming it" \
    "the record $COMPAT_REC is malformed" -- --llm deepseek -p x
rm -f "$COMPAT_REC"

cp "$FAKE_HOME/.cct/llms.toml" "$TMP/llms.saved"
sed -i.bak 's#https://api.deepseek.example/anthropic#https://moved.deepseek.example/anthropic#' "$FAKE_HOME/.cct/llms.toml"
refused "sessions: a restored target whose launch identity changed is refused (FR-19)" \
    "the launch identity of deepseek@deepseek-claude changed since session $S1 was stamped" -- -p x --resume "$S1"
cp "$TMP/llms.saved" "$FAKE_HOME/.cct/llms.toml"
sed -i.bak 's/^max_output_tokens = 32000$/max_output_tokens = 16000/' "$FAKE_HOME/.cct/llms.toml"
new_logs
run_launcher -- --llm deepseek -p x --resume "$S1"
assert_eq "sessions: a tuning change is said, and the resume allowed (FR-19)" "0:1:1" \
    "$RC:$(claude_ran):$(grep -c "the tuning options of deepseek@deepseek-claude changed since session $S1 was stamped" <<< "$OUTPUT")"
cp "$TMP/llms.saved" "$FAKE_HOME/.cct/llms.toml"

new_logs
run_launcher -- --llm opus -p fork --resume "$S1" --fork-session
F1=$(session_of)
assert_exit "sessions: a fork onto another target starts a new session" 0 "$RC"
assert_eq "sessions: ...under its own id, stamped with that target and its origin" "opus@opus-claude $S1" \
    "$(stamp "$F1" | jq -r '"\(.llm)@\(.binding) \(.forked_from)"')"
LISTED=$(env -i HOME="$FAKE_HOME" PATH="$MOCK_BIN:$PATH" TEST_DEEPSEEK_KEY="$SECRET" bash "$REPO_DIR/scripts/cct" llm sessions --json 2>&1)
assert_eq "sessions: cct llm sessions lists what the launcher stamped, each resumable now" \
    "deepseek@deepseek-claude true|opus@opus-claude true $S1" \
    "$(jq -r --arg a "$S1" --arg f "$F1" '[(.sessions[] | select(.session_id == $a) | "\(.target) \(.resume.eligible)"),
        (.sessions[] | select(.session_id == $f) | "\(.target) \(.resume.eligible) \(.forked_from)")] | join("|")' <<< "$LISTED" 2>&1)"

new_logs
run_launcher -- -p x --continue
assert_contains "sessions: a native bare --continue says what it does not check, where stamps exist" "$OUTPUT" "this resumes whichever session Claude Code picks"
mkdir -p "$TMP/stampless-home"
new_logs
run_launcher HOME="$TMP/stampless-home" -- -p x --continue
assert_not_contains "sessions: ...and nothing where none exist, so a launcher that never used --llm is unchanged" "$OUTPUT" "whichever session"
refused "sessions: a typed launch with --llm and --continue is refused" "--continue resumes whichever session" \
    -- --shell cmux --continue --llm deepseek "$PROJ"
assert_eq "sessions: ...before anything is typed" "" "$(cat "$MUX_LOG")"

echo ""
echo "========================================="
echo "  llm-launch tests: $PASS passed, $FAIL failed$( [[ $SKIPPED -gt 0 ]] && echo ", $SKIPPED skipped")"
echo "========================================="
if [[ "$((PASS + SKIPPED))" -ne "${TEST_LLM_LAUNCH_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_LLM_LAUNCH_EXPECTED_PASS:-0}, got $PASS passed + $SKIPPED skipped)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
