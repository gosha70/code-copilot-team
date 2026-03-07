#!/usr/bin/env bash
set -euo pipefail

# peer-review-runner.sh — Executes peer provider review and writes collaboration artifact
#
# Reads the pending marker JSON, resolves the peer provider from the global
# profile (~/.code-copilot-team/providers.toml), executes the provider's
# review command, and writes the collaboration artifact under specs/.
#
# Usage: peer-review-runner.sh <pending-marker-path>
# Exit:  0 = success, 1 = failure
#
# The marker is always deleted after processing (success or fail).

# ── Guards ────────────────────────────────────────────────────

if [[ $# -lt 1 ]]; then
    echo "Usage: peer-review-runner.sh <pending-marker-path>" >&2
    exit 1
fi

MARKER_PATH="$1"

if [[ ! -f "$MARKER_PATH" ]]; then
    echo "Error: Marker file not found: $MARKER_PATH" >&2
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not installed." >&2
    exit 1
fi

# ── Configuration ─────────────────────────────────────────────

PROFILE="${CCT_PROVIDER_PROFILE:-$HOME/.code-copilot-team/providers.toml}"

if [[ ! -f "$PROFILE" ]]; then
    echo "Error: Provider profile not found: $PROFILE" >&2
    echo "Run setup.sh to create the default profile." >&2
    exit 1
fi

# ── Parse marker ──────────────────────────────────────────────

FEATURE_ID=$(jq -r '.feature_id // empty' "$MARKER_PATH")
PHASE=$(jq -r '.phase // empty' "$MARKER_PATH")
TARGET_REF=$(jq -r '.target_ref // empty' "$MARKER_PATH")
SUBJECT_PROVIDER=$(jq -r '.subject_provider // empty' "$MARKER_PATH")
PEER_PROVIDER=$(jq -r '.peer_provider // empty' "$MARKER_PATH")
REVIEW_SCOPE=$(jq -r '.review_scope // "both"' "$MARKER_PATH")

for field in FEATURE_ID PHASE TARGET_REF SUBJECT_PROVIDER; do
    if [[ -z "${!field}" ]]; then
        echo "Error: Missing required field '$field' in marker." >&2
        rm -f "$MARKER_PATH"
        exit 1
    fi
done

# ── TOML helpers ──────────────────────────────────────────────
# Simple line-based parser for flat TOML with [section] headers.

toml_get() {
    local file="$1" section="$2" key="$3"
    awk -v section="$section" -v key="$key" '
        /^\[/ { current = $0; gsub(/[\[\] ]/, "", current) }
        current == section && $0 ~ "^" key " *=" {
            val = $0
            sub(/^[^=]*= */, "", val)
            gsub(/^"|"$/, "", val)
            print val
            exit
        }
    ' "$file"
}

# ── Resolve peer provider ────────────────────────────────────

if [[ -z "$PEER_PROVIDER" ]]; then
    PEER_PROVIDER=$(toml_get "$PROFILE" "defaults" "peer_for.$SUBJECT_PROVIDER")
    if [[ -z "$PEER_PROVIDER" ]]; then
        echo "Error: No default peer configured for '$SUBJECT_PROVIDER' in $PROFILE" >&2
        rm -f "$MARKER_PATH"
        exit 1
    fi
fi

# Validate provider identity: subject != peer
if [[ "$SUBJECT_PROVIDER" == "$PEER_PROVIDER" ]]; then
    echo "Error: Subject and peer provider are the same ('$PEER_PROVIDER'). Cross-provider review requires different providers." >&2
    rm -f "$MARKER_PATH"
    exit 1
fi

# ── Load provider config ─────────────────────────────────────

PROVIDER_SECTION="providers.$PEER_PROVIDER"
COMMAND_TEMPLATE=$(toml_get "$PROFILE" "$PROVIDER_SECTION" "command")
TIMEOUT_SEC=$(toml_get "$PROFILE" "$PROVIDER_SECTION" "timeout_sec")
HEALTHCHECK=$(toml_get "$PROFILE" "$PROVIDER_SECTION" "healthcheck")
PROVIDER_MODEL=$(toml_get "$PROFILE" "$PROVIDER_SECTION" "model")

if [[ -z "$COMMAND_TEMPLATE" ]]; then
    echo "Error: No command template found for provider '$PEER_PROVIDER' in $PROFILE" >&2
    rm -f "$MARKER_PATH"
    exit 1
fi

TIMEOUT_SEC="${TIMEOUT_SEC:-300}"

# ── Compute runner fingerprint ────────────────────────────────

if command -v shasum &>/dev/null; then
    RUNNER_FINGERPRINT=$(echo "$COMMAND_TEMPLATE" | shasum -a 256 | cut -d' ' -f1)
elif command -v sha256sum &>/dev/null; then
    RUNNER_FINGERPRINT=$(echo "$COMMAND_TEMPLATE" | sha256sum | cut -d' ' -f1)
else
    RUNNER_FINGERPRINT="unknown"
fi

# ── Healthcheck ───────────────────────────────────────────────

if [[ -n "$HEALTHCHECK" ]]; then
    if ! bash -c "$HEALTHCHECK" &>/dev/null; then
        echo "Error: Healthcheck failed for provider '$PEER_PROVIDER': $HEALTHCHECK" >&2
        rm -f "$MARKER_PATH"
        exit 1
    fi
fi

# ── Prepare review request ────────────────────────────────────

PROJECT_DIR=$(dirname "$(cd "$(dirname "$MARKER_PATH")" && pwd)")
REVIEW_REQUEST=$(mktemp)
trap 'rm -f "$REVIEW_REQUEST"; rm -f "$MARKER_PATH"' EXIT

cat > "$REVIEW_REQUEST" << REVIEW_EOF
# Peer Review Request

Feature: $FEATURE_ID
Phase: $PHASE
Scope: $REVIEW_SCOPE
Target ref: $TARGET_REF
Subject provider: $SUBJECT_PROVIDER

## Review Instructions

Review the changes for this feature. Focus on:
$(if [[ "$REVIEW_SCOPE" == "code" ]]; then
    echo "- Code correctness, edge cases, error handling"
    echo "- Security vulnerabilities"
    echo "- Performance issues"
elif [[ "$REVIEW_SCOPE" == "design" ]]; then
    echo "- Architecture decisions and trade-offs"
    echo "- API design and interface contracts"
    echo "- Scalability and maintainability"
else
    echo "- Code correctness, edge cases, error handling"
    echo "- Architecture decisions and trade-offs"
    echo "- Security vulnerabilities"
    echo "- API design and interface contracts"
fi)

## Artifacts to Review

$(if [[ -d "$PROJECT_DIR/specs/$FEATURE_ID" ]]; then
    find "$PROJECT_DIR/specs/$FEATURE_ID" -name '*.md' -not -path '*/collaboration/*' | sort | while read -r f; do
        echo "- ${f#$PROJECT_DIR/}"
    done
else
    echo "- No spec artifacts found at specs/$FEATURE_ID/"
fi)

## Output Format

Provide your review as markdown with:
1. A 2-3 sentence summary
2. Blocking findings (must fix before proceeding)
3. Advisory findings (suggestions for improvement)
4. A verdict: PASS, FAIL, or INCONCLUSIVE
REVIEW_EOF

# ── Execute provider command ──────────────────────────────────

# Substitute placeholders in command template
RESOLVED_CMD="$COMMAND_TEMPLATE"
RESOLVED_CMD="${RESOLVED_CMD//\{review_request\}/$REVIEW_REQUEST}"
RESOLVED_CMD="${RESOLVED_CMD//\{model\}/${PROVIDER_MODEL:-}}"

# Detect timeout command
TIMEOUT_CMD=""
if command -v timeout &>/dev/null; then
    TIMEOUT_CMD="timeout"
elif command -v gtimeout &>/dev/null; then
    TIMEOUT_CMD="gtimeout"
fi

echo "Running peer review via '$PEER_PROVIDER'..." >&2

if [[ -n "$TIMEOUT_CMD" ]]; then
    REVIEW_OUTPUT=$($TIMEOUT_CMD "$TIMEOUT_SEC" bash -c "$RESOLVED_CMD" 2>&1) && REVIEW_EXIT=0 || REVIEW_EXIT=$?
else
    REVIEW_OUTPUT=$(bash -c "$RESOLVED_CMD" 2>&1) && REVIEW_EXIT=0 || REVIEW_EXIT=$?
fi

# Check for timeout
if [[ $REVIEW_EXIT -eq 124 || $REVIEW_EXIT -eq 143 ]]; then
    echo "Error: Provider '$PEER_PROVIDER' timed out after ${TIMEOUT_SEC}s." >&2
    exit 1
fi

# ── Determine artifact path and mode ──────────────────────────

if [[ "$PHASE" == "plan" ]]; then
    ARTIFACT_NAME="plan-consult.md"
    MODE="consult"
else
    ARTIFACT_NAME="build-review.md"
    MODE="review"
fi

COLLAB_DIR="$PROJECT_DIR/specs/$FEATURE_ID/collaboration"
mkdir -p "$COLLAB_DIR"
ARTIFACT_PATH="$COLLAB_DIR/$ARTIFACT_NAME"

# ── Parse verdict from review output ──────────────────────────

# Try to extract verdict from the provider's output
VERDICT="INCONCLUSIVE"
if echo "$REVIEW_OUTPUT" | grep -qi "PASS"; then
    VERDICT="PASS"
elif echo "$REVIEW_OUTPUT" | grep -qi "FAIL"; then
    VERDICT="FAIL"
fi

# Count blocking findings (lines starting with "- " under a "Blocking" header)
BLOCKING_COUNT=0
if echo "$REVIEW_OUTPUT" | grep -qi "blocking"; then
    BLOCKING_COUNT=$(echo "$REVIEW_OUTPUT" | awk '/[Bb]locking/{found=1; next} /^$|^#/{found=0} found && /^- /{count++} END{print count+0}')
fi

# If provider failed, force FAIL verdict
if [[ $REVIEW_EXIT -ne 0 ]]; then
    VERDICT="FAIL"
fi

# ── Write collaboration artifact ──────────────────────────────

TODAY=$(date +%Y-%m-%d)

cat > "$ARTIFACT_PATH" << ARTIFACT_EOF
---
feature_id: $FEATURE_ID
date: $TODAY
status: final
phase: $PHASE
mode: $MODE
subject_provider: $SUBJECT_PROVIDER
peer_provider: $PEER_PROVIDER
peer_profile: $PEER_PROVIDER
runner_fingerprint: $RUNNER_FINGERPRINT
verdict: $VERDICT
blocking_findings_open: $BLOCKING_COUNT
target_ref: $TARGET_REF
---

# Peer Review: $FEATURE_ID — ${PHASE^} Phase

**Reviewer**: $PEER_PROVIDER
**Scope**: $REVIEW_SCOPE

$REVIEW_OUTPUT
ARTIFACT_EOF

echo "Artifact written to $ARTIFACT_PATH" >&2
echo "Verdict: $VERDICT (blocking findings: $BLOCKING_COUNT)" >&2

# Marker is cleaned up by the EXIT trap

if [[ "$VERDICT" == "FAIL" || $REVIEW_EXIT -ne 0 ]]; then
    exit 1
fi

exit 0
