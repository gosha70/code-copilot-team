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

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
MOCK_BIN="$TMP/bin"; FAKE_HOME="$TMP/home"; PROJ="$TMP/proj"
mkdir -p "$MOCK_BIN" "$FAKE_HOME/.cct" "$PROJ"

# claude: argv, cwd and the whole environment.
cat > "$MOCK_BIN/claude" << 'MOCK'
#!/usr/bin/env bash
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
assert_contains "selected: --llm is taken out of claude's argv" "$(cat "$CLAUDE_LOG")" "ARGV: -p hello\\ there --output-format json"
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
assert_contains "selected: --llm=<target> after -p is honoured" "$(cat "$CLAUDE_LOG")" "ARGV: -p after"
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
run_launcher "${DIRTY[@]}" -- --shell cmux --continue --llm deepseek "$PROJ"
assert_exit "typed: launch succeeds" 0 "$RC"
TYPED=$(cat "$MUX_LOG")
assert_eq "typed: the outer launcher does not run claude" "0" "$(claude_ran)"
assert_contains "typed: the banner says which LLM was selected" "$OUTPUT" "LLM:     deepseek (DeepSeek · deepseek-main[1m] · https://api.deepseek.example)"
assert_contains "typed: the command names the target" "$TYPED" "--llm deepseek"
assert_contains "typed: ...re-runs this launcher in the pane" "$TYPED" "CCT_LLM_CHILD=1 $LAUNCHER --llm deepseek --continue"
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
assert_contains "typed: claude gets the resume flag and no --llm" "$(grep '^ARGV:' "$CLAUDE_LOG")" "ARGV: --continue"
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

echo ""
echo "========================================="
echo "  llm-launch tests: $PASS passed, $FAIL failed"
echo "========================================="
if [[ "$PASS" -ne "${TEST_LLM_LAUNCH_EXPECTED_PASS:-0}" ]]; then
    echo "  FAIL: assertion-count drift (expected ${TEST_LLM_LAUNCH_EXPECTED_PASS:-0}, got $PASS)"
    FAIL=$((FAIL+1))
fi
[[ $FAIL -eq 0 ]]
