#!/usr/bin/env bash

# test-peer-review.sh — Unit tests for peer-review-runner.sh
#
# Tests TOML parsing, typed provider dispatch, fallback chain,
# and healthcheck failure handling.
#
# Run from the repo root:
#   bash tests/test-peer-review.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$SCRIPT_DIR/../scripts/peer-review-runner.sh"
COUNTS_FILE="$SCRIPT_DIR/test-counts.env"
# shellcheck source=/dev/null
source "$COUNTS_FILE"
PASS=0
FAIL=0

assert_exit() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$actual" -eq "$expected" ]]; then
        echo "  PASS: $name (exit $actual)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $name (expected exit $expected, got $actual)"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -q "$needle"; then
        echo "  PASS: $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $name (expected to contain '$needle')"
        FAIL=$((FAIL + 1))
    fi
}

assert_not_contains() {
    local name="$1" haystack="$2" needle="$3"
    if echo "$haystack" | grep -q "$needle"; then
        echo "  FAIL: $name (should not contain '$needle')"
        FAIL=$((FAIL + 1))
    else
        echo "  PASS: $name"
        PASS=$((PASS + 1))
    fi
}

# ── Test setup ───────────────────────────────────────────────

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Create a mock project with marker and spec artifacts
setup_project() {
    local project_dir="$TMP/project-$$-$RANDOM"
    mkdir -p "$project_dir/.cct/review"
    mkdir -p "$project_dir/specs/test-feature"
    echo "# Test Plan" > "$project_dir/specs/test-feature/plan.md"

    cat > "$project_dir/.cct/review/pending.json" << 'MARKER'
{
    "feature_id": "test-feature",
    "phase": "build",
    "target_ref": "main",
    "subject_provider": "claude",
    "peer_provider": "",
    "review_scope": "both",
    "request_id": "test-123",
    "requested_at": "2026-01-01T00:00:00Z"
}
MARKER
    echo "$project_dir"
}

# Create a providers.toml with configurable content
write_profile() {
    local profile_path="$1"
    cat > "$profile_path"
}

# Run the runner with a specific profile, return exit code and capture output
run_runner() {
    local project_dir="$1"
    local profile="$2"
    local marker="$project_dir/.cct/review/pending.json"
    local rc=0
    local output
    output=$(CCT_PROVIDER_PROFILE="$profile" bash "$RUNNER" "$marker" 2>&1) || rc=$?
    echo "$output"
    return "$rc"
}

# ══════════════════════════════════════════════════════════════
echo "=== TOML parsing ==="
# ══════════════════════════════════════════════════════════════

# Extract toml_get and toml_get_array for direct testing
TOML_HELPERS=$(sed -n '/^toml_get()/,/^}/p; /^toml_get_array()/,/^}/p' "$RUNNER")

toml_get_test() {
    local file="$1" section="$2" key="$3"
    eval "$TOML_HELPERS"
    toml_get "$file" "$section" "$key"
}

toml_get_array_test() {
    local file="$1" section="$2" key="$3"
    eval "$TOML_HELPERS"
    toml_get_array "$file" "$section" "$key"
}

TOML_FILE="$TMP/test.toml"
cat > "$TOML_FILE" << 'TOML'
[defaults]
peer_for.claude = "codex"
fallback_chain.claude = ["openai", "ollama", "gdx-spark"]

[providers.codex]
type = "cli"
command = "codex --quiet --prompt-file {review_request}"
timeout_sec = 300
healthcheck = "codex --version"

[providers.openai]
type = "openai-compatible"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
model = "gpt-4o"
timeout_sec = 300

[providers.ollama]
type = "ollama"
model = "llama3"
host = "localhost:11434"
timeout_sec = 600

[providers.custom-ssh]
type = "custom"
command = "ssh gpubox 'python review.py --input {review_request}'"
timeout_sec = 900
TOML

# Basic key reads
VAL=$(toml_get_test "$TOML_FILE" "defaults" "peer_for.claude")
[[ "$VAL" == "codex" ]] && { echo "  PASS: toml_get defaults peer_for.claude"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get defaults peer_for.claude (got '$VAL')"; FAIL=$((FAIL+1)); }

VAL=$(toml_get_test "$TOML_FILE" "providers.codex" "type")
[[ "$VAL" == "cli" ]] && { echo "  PASS: toml_get cli type"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get cli type (got '$VAL')"; FAIL=$((FAIL+1)); }

VAL=$(toml_get_test "$TOML_FILE" "providers.openai" "type")
[[ "$VAL" == "openai-compatible" ]] && { echo "  PASS: toml_get openai-compatible type"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get openai-compatible type (got '$VAL')"; FAIL=$((FAIL+1)); }

VAL=$(toml_get_test "$TOML_FILE" "providers.openai" "base_url")
[[ "$VAL" == "https://api.openai.com/v1" ]] && { echo "  PASS: toml_get base_url"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get base_url (got '$VAL')"; FAIL=$((FAIL+1)); }

VAL=$(toml_get_test "$TOML_FILE" "providers.ollama" "type")
[[ "$VAL" == "ollama" ]] && { echo "  PASS: toml_get ollama type"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get ollama type (got '$VAL')"; FAIL=$((FAIL+1)); }

VAL=$(toml_get_test "$TOML_FILE" "providers.ollama" "host")
[[ "$VAL" == "localhost:11434" ]] && { echo "  PASS: toml_get ollama host"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get ollama host (got '$VAL')"; FAIL=$((FAIL+1)); }

VAL=$(toml_get_test "$TOML_FILE" "providers.custom-ssh" "type")
[[ "$VAL" == "custom" ]] && { echo "  PASS: toml_get custom type"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get custom type (got '$VAL')"; FAIL=$((FAIL+1)); }

VAL=$(toml_get_test "$TOML_FILE" "providers.nonexistent" "type")
[[ -z "$VAL" ]] && { echo "  PASS: toml_get missing provider returns empty"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get missing provider (got '$VAL')"; FAIL=$((FAIL+1)); }

# Array parsing
ARRAY=$(toml_get_array_test "$TOML_FILE" "defaults" "fallback_chain.claude")
FIRST=$(echo "$ARRAY" | head -1)
COUNT=$(echo "$ARRAY" | wc -l | tr -d ' ')
[[ "$FIRST" == "openai" ]] && { echo "  PASS: toml_get_array first element"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get_array first element (got '$FIRST')"; FAIL=$((FAIL+1)); }
[[ "$COUNT" == "3" ]] && { echo "  PASS: toml_get_array count"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get_array count (expected 3, got $COUNT)"; FAIL=$((FAIL+1)); }

EMPTY_ARRAY=$(toml_get_array_test "$TOML_FILE" "defaults" "fallback_chain.nonexistent")
[[ -z "$EMPTY_ARRAY" ]] && { echo "  PASS: toml_get_array missing key returns empty"; PASS=$((PASS+1)); } \
    || { echo "  FAIL: toml_get_array missing key (got '$EMPTY_ARRAY')"; FAIL=$((FAIL+1)); }

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Runner guards ==="
# ══════════════════════════════════════════════════════════════

# No arguments
RC=0; bash "$RUNNER" 2>/dev/null || RC=$?
assert_exit "no arguments exits 1" 1 "$RC"

# Nonexistent marker
RC=0; bash "$RUNNER" "/nonexistent/marker.json" 2>/dev/null || RC=$?
assert_exit "nonexistent marker exits 1" 1 "$RC"

# Missing profile
PROJECT=$(setup_project)
RC=0
CCT_PROVIDER_PROFILE="/nonexistent/providers.toml" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>/dev/null || RC=$?
assert_exit "missing profile exits 1" 1 "$RC"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Provider type validation ==="
# ══════════════════════════════════════════════════════════════

# cli provider missing command
PROFILE="$TMP/cli-no-cmd.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "broken"
[providers.broken]
type = "cli"
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "cli missing command exits 1" 1 "$RC"
assert_contains "cli missing command error message" "$OUTPUT" "No command template"

# openai-compatible missing base_url
PROFILE="$TMP/oai-no-url.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "broken"
[providers.broken]
type = "openai-compatible"
model = "gpt-4o"
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "openai-compatible missing base_url exits 1" 1 "$RC"
assert_contains "openai-compatible missing base_url error" "$OUTPUT" "No base_url"

# openai-compatible missing model
PROFILE="$TMP/oai-no-model.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "broken"
[providers.broken]
type = "openai-compatible"
base_url = "http://localhost:8000/v1"
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "openai-compatible missing model exits 1" 1 "$RC"
assert_contains "openai-compatible missing model error" "$OUTPUT" "No model"

# ollama missing model
PROFILE="$TMP/ollama-no-model.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "broken"
[providers.broken]
type = "ollama"
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "ollama missing model exits 1" 1 "$RC"
assert_contains "ollama missing model error" "$OUTPUT" "No model"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Type-based dispatch ==="
# ══════════════════════════════════════════════════════════════

# cli type dispatches via command template
PROFILE="$TMP/cli-dispatch.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "echo-provider"
[providers.echo-provider]
type = "cli"
command = "echo 'PASS: review complete. Verdict: PASS'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "cli dispatch succeeds" 0 "$RC"
assert_contains "cli dispatch produces artifact" "$OUTPUT" "Verdict: PASS"

# custom type dispatches via command template (same as cli)
PROFILE="$TMP/custom-dispatch.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "custom-echo"
[providers.custom-echo]
type = "custom"
command = "echo 'Review PASS — no issues found'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "custom dispatch succeeds" 0 "$RC"
assert_contains "custom dispatch produces artifact" "$OUTPUT" "Verdict: PASS"

# Legacy provider (no type field) defaults to cli
PROFILE="$TMP/legacy-dispatch.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "legacy"
[providers.legacy]
command = "echo 'Legacy review PASS'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "legacy (no type) defaults to cli" 0 "$RC"
assert_contains "legacy dispatch produces artifact" "$OUTPUT" "Verdict: PASS"

# Unknown type is rejected
PROFILE="$TMP/unknown-type.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "badtype"
[providers.badtype]
type = "kubernetes"
command = "echo should not run"
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "unknown type exits 1" 1 "$RC"
assert_contains "unknown type error message" "$OUTPUT" "Unknown provider type"

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Healthcheck and fallback chain ==="
# ══════════════════════════════════════════════════════════════

# Primary healthy — no fallback needed
PROFILE="$TMP/healthy-primary.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "primary"
fallback_chain.claude = ["fallback"]
[providers.primary]
type = "cli"
command = "echo 'Primary PASS'"
timeout_sec = 10
healthcheck = "true"
[providers.fallback]
type = "cli"
command = "echo 'Fallback PASS'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "healthy primary succeeds" 0 "$RC"
assert_contains "healthy primary used" "$OUTPUT" "Running peer review via 'primary'"
assert_not_contains "fallback not triggered" "$OUTPUT" "trying fallback"

# Primary unhealthy, fallback healthy
PROFILE="$TMP/fallback-engage.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "dead-primary"
fallback_chain.claude = ["alive-fallback"]
[providers.dead-primary]
type = "cli"
command = "echo 'should not run'"
timeout_sec = 10
healthcheck = "false"
[providers.alive-fallback]
type = "cli"
command = "echo 'Fallback review PASS'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "fallback engages on primary failure" 0 "$RC"
assert_contains "fallback chain walked" "$OUTPUT" "trying fallback"
assert_contains "fallback provider used" "$OUTPUT" "Running peer review via 'alive-fallback'"

# All providers unhealthy — error
PROFILE="$TMP/all-dead.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "dead1"
fallback_chain.claude = ["dead2", "dead3"]
[providers.dead1]
type = "cli"
command = "echo 'should not run'"
timeout_sec = 10
healthcheck = "false"
[providers.dead2]
type = "cli"
command = "echo 'should not run'"
timeout_sec = 10
healthcheck = "false"
[providers.dead3]
type = "cli"
command = "echo 'should not run'"
timeout_sec = 10
healthcheck = "false"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "all providers dead exits 1" 1 "$RC"
assert_contains "all-dead error message" "$OUTPUT" "All providers failed healthcheck"

# No fallback chain configured, primary unhealthy
PROFILE="$TMP/no-fallback.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "dead-only"
[providers.dead-only]
type = "cli"
command = "echo 'should not run'"
timeout_sec = 10
healthcheck = "false"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "no fallback chain, dead primary exits 1" 1 "$RC"

# Fallback chain with subject provider should skip self-review
PROFILE="$TMP/self-review-fallback.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "dead-peer"
fallback_chain.claude = ["claude", "real-fallback"]
[providers.dead-peer]
type = "cli"
command = "echo 'should not run'"
timeout_sec = 10
healthcheck = "false"
[providers.claude]
type = "cli"
command = "echo 'self-review should not run'"
timeout_sec = 10
healthcheck = "true"
[providers.real-fallback]
type = "cli"
command = "echo 'Real fallback PASS'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "fallback skips self-review candidate" 0 "$RC"
assert_contains "self-review skipped message" "$OUTPUT" "same as subject provider"
assert_contains "real fallback used" "$OUTPUT" "Running peer review via 'real-fallback'"

# Fingerprint reflects actual provider after fallback
PROFILE="$TMP/fingerprint-fallback.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "dead-primary"
fallback_chain.claude = ["alive-alt"]
[providers.dead-primary]
type = "cli"
command = "echo 'primary command'"
timeout_sec = 10
healthcheck = "false"
[providers.alive-alt]
type = "cli"
command = "echo 'Fallback PASS'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
ARTIFACT="$PROJECT/specs/test-feature/collaboration/build-review.md"
if [[ -f "$ARTIFACT" ]]; then
    EXPECTED_INPUT="cli:echo 'Fallback PASS'::"
    if command -v shasum &>/dev/null; then
        EXPECTED_FP=$(echo "$EXPECTED_INPUT" | shasum -a 256 | cut -d' ' -f1)
    else
        EXPECTED_FP=$(echo "$EXPECTED_INPUT" | sha256sum | cut -d' ' -f1)
    fi
    ACTUAL_FP=$(grep 'runner_fingerprint:' "$ARTIFACT" | sed 's/.*: //')
    if [[ "$ACTUAL_FP" == "$EXPECTED_FP" ]]; then
        echo "  PASS: fingerprint matches fallback provider"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: fingerprint matches fallback provider (expected $EXPECTED_FP, got $ACTUAL_FP)"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  FAIL: artifact not created for fingerprint test"
    FAIL=$((FAIL + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Artifact generation ==="
# ══════════════════════════════════════════════════════════════

# Verify collaboration artifact is written correctly
PROFILE="$TMP/artifact-test.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "test-reviewer"
[providers.test-reviewer]
type = "cli"
command = "echo '## Summary\nAll good.\n\n## Blocking\nNone.\n\n## Verdict\nPASS'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?

ARTIFACT="$PROJECT/specs/test-feature/collaboration/build-review.md"
if [[ -f "$ARTIFACT" ]]; then
    echo "  PASS: collaboration artifact created"
    PASS=$((PASS + 1))
else
    echo "  FAIL: collaboration artifact not found at $ARTIFACT"
    FAIL=$((FAIL + 1))
fi

if [[ -f "$ARTIFACT" ]]; then
    ARTIFACT_CONTENT=$(cat "$ARTIFACT")
    assert_contains "artifact has feature_id" "$ARTIFACT_CONTENT" "feature_id: test-feature"
    assert_contains "artifact has phase" "$ARTIFACT_CONTENT" "phase: build"
    assert_contains "artifact has verdict" "$ARTIFACT_CONTENT" "verdict: PASS"
    assert_contains "artifact has peer_provider" "$ARTIFACT_CONTENT" "peer_provider: test-reviewer"
    assert_contains "artifact has runner_fingerprint" "$ARTIFACT_CONTENT" "runner_fingerprint:"
fi

# Plan phase writes plan-consult.md
PROFILE="$TMP/plan-artifact.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "plan-reviewer"
[providers.plan-reviewer]
type = "cli"
command = "echo 'Plan review PASS'"
timeout_sec = 10
healthcheck = "true"
TOML
PROJECT=$(setup_project)
# Override marker to plan phase
cat > "$PROJECT/.cct/review/pending.json" << 'MARKER'
{
    "feature_id": "test-feature",
    "phase": "plan",
    "target_ref": "main",
    "subject_provider": "claude",
    "peer_provider": "",
    "review_scope": "design",
    "request_id": "test-456",
    "requested_at": "2026-01-01T00:00:00Z"
}
MARKER
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
PLAN_ARTIFACT="$PROJECT/specs/test-feature/collaboration/plan-consult.md"
if [[ -f "$PLAN_ARTIFACT" ]]; then
    echo "  PASS: plan artifact created as plan-consult.md"
    PASS=$((PASS + 1))
    PLAN_CONTENT=$(cat "$PLAN_ARTIFACT")
    assert_contains "plan artifact has mode consult" "$PLAN_CONTENT" "mode: consult"
else
    echo "  FAIL: plan artifact not found at $PLAN_ARTIFACT"
    FAIL=$((FAIL + 1))
fi

# Marker is cleaned up after run
PROJECT=$(setup_project)
PROFILE="$TMP/marker-cleanup.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "cleaner"
[providers.cleaner]
type = "cli"
command = "echo 'PASS'"
timeout_sec = 10
healthcheck = "true"
TOML
MARKER_PATH="$PROJECT/.cct/review/pending.json"
CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$MARKER_PATH" >/dev/null 2>&1 || true
if [[ ! -f "$MARKER_PATH" ]]; then
    echo "  PASS: marker cleaned up after successful run"
    PASS=$((PASS + 1))
else
    echo "  FAIL: marker not cleaned up"
    FAIL=$((FAIL + 1))
fi

echo ""

# ══════════════════════════════════════════════════════════════
echo "=== Subject/peer identity ==="
# ══════════════════════════════════════════════════════════════

# Same subject and peer rejected
PROFILE="$TMP/same-identity.toml"
write_profile "$PROFILE" << 'TOML'
[defaults]
peer_for.claude = "claude"
[providers.claude]
type = "cli"
command = "echo 'should not run'"
healthcheck = "true"
TOML
PROJECT=$(setup_project)
RC=0; OUTPUT=$(CCT_PROVIDER_PROFILE="$PROFILE" bash "$RUNNER" "$PROJECT/.cct/review/pending.json" 2>&1) || RC=$?
assert_exit "same subject/peer rejected" 1 "$RC"
assert_contains "same identity error" "$OUTPUT" "Subject and peer provider are the same"

echo ""

# ══════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "$TEST_PEER_REVIEW_EXPECTED_PASS" ]]; then
    echo "  FAIL: assertion-count drift (expected $TEST_PEER_REVIEW_EXPECTED_PASS, got $PASS)"
    FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
