#!/usr/bin/env bash
set -euo pipefail

# peer-review-on-stop.sh — Stop hook for peer review
#
# When Claude finishes responding, checks for a pending peer-review marker
# (.cct/review/pending.json). If found and valid, invokes the peer-review
# runner. Fail-closed: blocks the stop event on runner failure (exit 2).
#
# Guards:
#   - stop_hook_active (infinite-loop prevention)
#   - CCT_PEER_REVIEW_ENABLED must be "true"
#   - Marker must exist at .cct/review/pending.json
#   - Marker must not be stale (requested_at vs CCT_SESSION_START)
#   - CCT_PEER_BYPASS=true skips review (logged)

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
MARKER_PATH="$PROJECT_DIR/.cct/review/pending.json"

# --- Marker exists? ---
if [[ ! -f "$MARKER_PATH" ]]; then
    exit 0
fi

# --- Validate marker has required keys ---
REQUIRED_KEYS=("feature_id" "phase" "target_ref" "subject_provider" "requested_at")
for key in "${REQUIRED_KEYS[@]}"; do
    VALUE=$(jq -r ".$key // empty" "$MARKER_PATH" 2>/dev/null) || true
    if [[ -z "$VALUE" ]]; then
        echo "Warning: Peer review marker missing required key '$key'. Removing invalid marker." >&2
        rm -f "$MARKER_PATH"
        exit 0
    fi
done

# --- Staleness check ---
REQUESTED_AT=$(jq -r '.requested_at // empty' "$MARKER_PATH" 2>/dev/null) || true
SESSION_START="${CCT_SESSION_START:-}"

if [[ -n "$SESSION_START" && -n "$REQUESTED_AT" ]]; then
    # Compare timestamps (works with ISO 8601 strings via string comparison)
    if [[ "$REQUESTED_AT" < "$SESSION_START" ]]; then
        echo "Warning: Peer review marker is stale (requested_at=$REQUESTED_AT, session_start=$SESSION_START). Removing stale marker." >&2
        rm -f "$MARKER_PATH"
        exit 0
    fi
fi

# --- Bypass check ---
if [[ "${CCT_PEER_BYPASS:-false}" == "true" ]]; then
    echo "Warning: Peer review bypassed (CCT_PEER_BYPASS=true). CI will reject bypass artifacts." >&2
    # Clean up marker
    rm -f "$MARKER_PATH"
    exit 0
fi

# --- Locate runner ---
# Search order: project-local, ~/.local/bin (setup.sh install location), then PATH
RUNNER=""
if [[ -x "$PROJECT_DIR/scripts/peer-review-runner.sh" ]]; then
    RUNNER="$PROJECT_DIR/scripts/peer-review-runner.sh"
elif [[ -x "$HOME/.local/bin/peer-review-runner.sh" ]]; then
    RUNNER="$HOME/.local/bin/peer-review-runner.sh"
elif command -v peer-review-runner.sh &>/dev/null; then
    RUNNER="peer-review-runner.sh"
fi

if [[ -z "$RUNNER" ]]; then
    echo "Error: peer-review-runner.sh not found. Peer review cannot proceed." >&2
    exit 2
fi

# --- Execute runner ---
echo "Invoking peer review runner..." >&2

if bash "$RUNNER" "$MARKER_PATH"; then
    echo "Peer review completed successfully." >&2
    exit 0
else
    echo "Peer review failed. Session blocked (fail-closed). Set CCT_PEER_BYPASS=true to bypass." >&2
    exit 2
fi
