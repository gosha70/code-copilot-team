#!/usr/bin/env bash
set -euo pipefail

# peer-review-on-stop.sh — Stop hook for peer review validation
#
# Validates that the review loop completed before the session ends.
# Does NOT initiate review — that is driven by the agent via /review-submit.
#
# Behavior:
#   - Build phase: blocks stop if loop-summary.json is missing or verdict
#     is not PASS/bypass. Exit 2 = blocked.
#   - Plan phase: exempt — plan review is advisory, never blocks stop.
#   - Peer review disabled: no-op (exit 0).
#
# Guards:
#   - stop_hook_active (infinite-loop prevention)
#   - CCT_PEER_REVIEW_ENABLED must be "true"
#   - CCT_PEER_BYPASS=true skips validation (logged)

# --- jq guard ---
if ! command -v jq &>/dev/null; then
    exit 0
fi

# --- Read event JSON from stdin ---
INPUT=$(cat)

# --- Infinite-loop guard ---
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null) || exit 0
if [[ "$STOP_HOOK_ACTIVE" == "true" ]]; then
    exit 0
fi

# --- Peer review enabled? ---
if [[ "${CCT_PEER_REVIEW_ENABLED:-false}" != "true" ]]; then
    exit 0
fi

# --- Resolve project directory ---
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
REVIEW_DIR="$PROJECT_DIR/.cct/review"
SUMMARY="$REVIEW_DIR/loop-summary.json"

# --- Bypass check ---
if [[ "${CCT_PEER_BYPASS:-false}" == "true" ]]; then
    echo "Warning: Peer review bypassed (CCT_PEER_BYPASS=true). CI will reject bypass artifacts." >&2
    exit 0
fi

# --- Determine phase ---
PHASE=""
if [[ -f "$REVIEW_DIR/state.json" ]]; then
    PHASE=$(jq -r '.phase // empty' "$REVIEW_DIR/state.json" 2>/dev/null) || true
fi

# --- Plan phase: exempt (advisory review never blocks stop) ---
if [[ "$PHASE" == "plan" ]]; then
    exit 0
fi

# --- No review state: review was never started ---
# The stop hook validates review completion, but cannot enforce review initiation.
# Enforcement of "must run /review-submit" comes from the agent manifests and
# /phase-complete (which checks loop-summary.json before proceeding).
if [[ ! -d "$REVIEW_DIR" || ! -f "$REVIEW_DIR/state.json" ]]; then
    echo "Warning: Peer review is enabled but no review state found. Review was never started." >&2
    echo "If this is a Build session, run /review-submit before /phase-complete." >&2
    exit 0
fi

# --- Build phase: validate loop-summary.json ---
if [[ ! -f "$SUMMARY" ]]; then
    echo "Error: Peer review required but loop-summary.json not found." >&2
    echo "Run /review-submit to complete the review loop before ending the session." >&2
    exit 2
fi

VERDICT=$(jq -r '.verdict // empty' "$SUMMARY" 2>/dev/null) || true
BYPASS=$(jq -r '.bypass // false' "$SUMMARY" 2>/dev/null) || true

if [[ "$VERDICT" == "PASS" || "$BYPASS" == "true" ]]; then
    exit 0
fi

echo "Error: Peer review verdict is '$VERDICT' (not PASS) and no approved bypass." >&2
echo "Run /review-submit to continue the review loop, or /review-decide approve to bypass." >&2
exit 2
