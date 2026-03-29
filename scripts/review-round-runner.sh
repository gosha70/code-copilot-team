#!/usr/bin/env bash
set -euo pipefail

# review-round-runner.sh — Execute one review round
#
# Reads state.json, creates a snapshot sandbox, spawns the reviewer,
# parses structured findings, writes findings-round-N.json, updates
# state.json, and returns the verdict.
#
# Usage: review-round-runner.sh <project-dir>
# Exit:  0 = PASS, 1 = FAIL/INVALID, 2 = BREAKER_TRIPPED
#
# Requires: jq, shasum or sha256sum
# Env:      CCT_PROVIDER_PROFILE (optional, default ~/.code-copilot-team/providers.toml)
#           CCT_REVIEW_MAX_ROUNDS (optional, default 5)
#           CCT_REVIEW_TIMEOUT_SEC (optional, default 900)
#           CCT_REVIEW_STALE_THRESHOLD (optional, default 2)

# ── Guards ────────────────────────────────────────────────────

if [[ $# -lt 1 ]]; then
    echo "Usage: review-round-runner.sh <project-dir>" >&2
    exit 1
fi

PROJECT_DIR="$(cd "$1" && pwd)"

if [[ ! -d "$PROJECT_DIR/.cct/review" ]]; then
    echo "Error: No .cct/review/ directory in $PROJECT_DIR" >&2
    exit 1
fi

if ! command -v jq &>/dev/null; then
    echo "Error: jq is required but not installed." >&2
    exit 1
fi

# ── Configuration ─────────────────────────────────────────────

REVIEW_DIR="$PROJECT_DIR/.cct/review"
STATE_FILE="$REVIEW_DIR/state.json"
PROFILE="${CCT_PROVIDER_PROFILE:-$HOME/.code-copilot-team/providers.toml}"
MAX_ROUNDS="${CCT_REVIEW_MAX_ROUNDS:-5}"
TIMEOUT_SEC="${CCT_REVIEW_TIMEOUT_SEC:-900}"
STALE_THRESHOLD="${CCT_REVIEW_STALE_THRESHOLD:-2}"

if [[ ! -f "$PROFILE" ]]; then
    echo "Error: Provider profile not found: $PROFILE" >&2
    exit 1
fi

# ── TOML helpers ──────────────────────────────────────────────

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

toml_get_array() {
    local file="$1" section="$2" key="$3"
    local raw
    raw=$(toml_get "$file" "$section" "$key")
    if [[ -z "$raw" ]]; then return; fi
    echo "$raw" | tr -d '[]' | tr ',' '\n' | sed 's/^ *"//;s/" *$//'
}

# ── Load or initialize state ─────────────────────────────────

if [[ -f "$STATE_FILE" ]]; then
    CURRENT_ROUND=$(jq -r '.current_round // 0' "$STATE_FILE")
    ATTEMPT=$(jq -r '.attempt // 1' "$STATE_FILE")
    LOOP_START=$(jq -r '.loop_start // 0' "$STATE_FILE")
    if [[ "$LOOP_START" == "0" || -z "$LOOP_START" ]]; then
        LOOP_START=$(date +%s)
    fi
    FEATURE_ID=$(jq -r '.feature_id // empty' "$STATE_FILE")
    PHASE=$(jq -r '.phase // empty' "$STATE_FILE")
    SUBJECT_PROVIDER=$(jq -r '.subject_provider // empty' "$STATE_FILE")
    PEER_PROVIDER=$(jq -r '.peer_provider // empty' "$STATE_FILE")
    REVIEW_SCOPE=$(jq -r '.review_scope // "both"' "$STATE_FILE")
    TARGET_REF=$(jq -r '.target_ref // empty' "$STATE_FILE")
else
    echo "Error: state.json not found. Create it via /review-submit." >&2
    exit 1
fi

NEXT_ROUND=$((CURRENT_ROUND + 1))

# ── Dirty worktree check ─────────────────────────────────────

if [[ -n "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null | grep -Ev '^[?][?] \.cct/')" ]]; then
    echo '{"error": "uncommitted_changes", "message": "commit or stash before submitting for review"}' >&2
    exit 1
fi

# ── Circuit breaker: round limit ─────────────────────────────

if [[ "$NEXT_ROUND" -gt "$MAX_ROUNDS" ]]; then
    cat > "$REVIEW_DIR/breaker-tripped.json" << BREAKER_EOF
{
  "breaker": "max_rounds",
  "rounds_completed": $CURRENT_ROUND,
  "max_rounds": $MAX_ROUNDS,
  "attempt": $ATTEMPT,
  "action": "Run /review-decide approve|reject|retry"
}
BREAKER_EOF
    echo "Circuit breaker: max rounds ($MAX_ROUNDS) reached after $CURRENT_ROUND rounds." >&2
    exit 2
fi

# ── Circuit breaker: wall-clock timeout ──────────────────────

NOW=$(date +%s)
if [[ -n "$LOOP_START" ]]; then
    ELAPSED=$((NOW - LOOP_START))
    if [[ "$ELAPSED" -ge "$TIMEOUT_SEC" ]]; then
        cat > "$REVIEW_DIR/breaker-tripped.json" << BREAKER_EOF
{
  "breaker": "timeout",
  "rounds_completed": $CURRENT_ROUND,
  "elapsed_sec": $ELAPSED,
  "timeout_sec": $TIMEOUT_SEC,
  "attempt": $ATTEMPT,
  "action": "Run /review-decide approve|reject|retry"
}
BREAKER_EOF
        echo "Circuit breaker: wall-clock timeout (${TIMEOUT_SEC}s) after ${ELAPSED}s." >&2
        exit 2
    fi
fi

# ── Circuit breaker: stale findings ──────────────────────────

check_stale_findings() {
    if [[ "$CURRENT_ROUND" -lt 2 || ! -f "$STATE_FILE" ]]; then return; fi

    local stale_ids
    stale_ids=$(jq -r --argjson threshold "$STALE_THRESHOLD" '
        .findings // {} | to_entries[] |
        select(.value.consecutive_fixed >= $threshold) |
        .key
    ' "$STATE_FILE" 2>/dev/null)

    if [[ -n "$stale_ids" ]]; then
        local stale_details
        stale_details=$(jq --argjson threshold "$STALE_THRESHOLD" '
            [.findings // {} | to_entries[] |
             select(.value.consecutive_fixed >= $threshold) |
             {id: .key, description: .value.description, rounds_seen: .value.rounds_seen,
              consecutive_fixed: .value.consecutive_fixed}]
        ' "$STATE_FILE" 2>/dev/null)

        cat > "$REVIEW_DIR/breaker-tripped.json" << BREAKER_EOF
{
  "breaker": "stale_findings",
  "rounds_completed": $CURRENT_ROUND,
  "stale_threshold": $STALE_THRESHOLD,
  "stale_findings": $stale_details,
  "attempt": $ATTEMPT,
  "action": "Run /review-decide approve|reject|retry"
}
BREAKER_EOF
        echo "Circuit breaker: stale findings detected (threshold: $STALE_THRESHOLD consecutive rounds with 'fixed' disposition)." >&2
        exit 2
    fi
}

check_stale_findings

# ── Load provider config ─────────────────────────────────────

load_provider_config() {
    local name="$1"
    local section="providers.$name"

    PROVIDER_TYPE=$(toml_get "$PROFILE" "$section" "type")
    COMMAND_TEMPLATE=$(toml_get "$PROFILE" "$section" "command")
    PROVIDER_TIMEOUT=$(toml_get "$PROFILE" "$section" "timeout_sec")
    HEALTHCHECK=$(toml_get "$PROFILE" "$section" "healthcheck")
    PROVIDER_MODEL=$(toml_get "$PROFILE" "$section" "model")
    PROVIDER_BASE_URL=$(toml_get "$PROFILE" "$section" "base_url")
    PROVIDER_API_KEY_ENV=$(toml_get "$PROFILE" "$section" "api_key_env")
    PROVIDER_MAX_TOKENS=$(toml_get "$PROFILE" "$section" "max_tokens")
    PROVIDER_TEMPERATURE=$(toml_get "$PROFILE" "$section" "temperature")
    PROVIDER_HOST=$(toml_get "$PROFILE" "$section" "host")

    if [[ -z "$PROVIDER_TYPE" ]]; then PROVIDER_TYPE="cli"; fi
    PROVIDER_TIMEOUT="${PROVIDER_TIMEOUT:-300}"

    case "$PROVIDER_TYPE" in
        cli|custom)
            [[ -z "$COMMAND_TEMPLATE" ]] && { echo "Error: No command for $PROVIDER_TYPE provider '$name'" >&2; return 1; }
            ;;
        openai-compatible)
            [[ -z "$PROVIDER_BASE_URL" ]] && { echo "Error: No base_url for provider '$name'" >&2; return 1; }
            [[ -z "$PROVIDER_MODEL" ]] && { echo "Error: No model for provider '$name'" >&2; return 1; }
            ;;
        ollama)
            [[ -z "$PROVIDER_MODEL" ]] && { echo "Error: No model for provider '$name'" >&2; return 1; }
            ;;
    esac
    return 0
}

run_healthcheck() {
    local hc="$1"
    if [[ -z "$hc" ]]; then return 0; fi
    bash -c "$hc" &>/dev/null
}

# Resolve provider with fallback
load_provider_config "$PEER_PROVIDER" || exit 1

if ! run_healthcheck "$HEALTHCHECK"; then
    echo "Healthcheck failed for '$PEER_PROVIDER', trying fallback chain..." >&2
    FALLBACK_CHAIN=$(toml_get_array "$PROFILE" "defaults" "fallback_chain.$SUBJECT_PROVIDER")
    FALLBACK_FOUND=false

    if [[ -n "$FALLBACK_CHAIN" ]]; then
        while IFS= read -r fallback; do
            [[ -z "$fallback" ]] && continue
            if [[ "$fallback" == "$SUBJECT_PROVIDER" ]]; then
                echo "Skipping '$fallback' (same as subject provider)." >&2
                continue
            fi
            if load_provider_config "$fallback" && run_healthcheck "$HEALTHCHECK"; then
                echo "Using fallback provider '$fallback'." >&2
                PEER_PROVIDER="$fallback"
                FALLBACK_FOUND=true
                break
            fi
        done <<< "$FALLBACK_CHAIN"
    fi

    if [[ "$FALLBACK_FOUND" != "true" ]]; then
        cat > "$REVIEW_DIR/breaker-tripped.json" << BREAKER_EOF
{
  "breaker": "provider_unavailable",
  "rounds_completed": $CURRENT_ROUND,
  "primary_provider": "$PEER_PROVIDER",
  "attempt": $ATTEMPT,
  "action": "Run /review-decide approve|reject|retry"
}
BREAKER_EOF
        echo "Circuit breaker: all providers unavailable." >&2
        exit 2
    fi
fi

# Compute fingerprint after provider resolution
FINGERPRINT_INPUT="$PROVIDER_TYPE:${COMMAND_TEMPLATE:-}:${PROVIDER_BASE_URL:-}:${PROVIDER_MODEL:-}"
if command -v shasum &>/dev/null; then
    RUNNER_FINGERPRINT=$(echo "$FINGERPRINT_INPUT" | shasum -a 256 | cut -d' ' -f1)
elif command -v sha256sum &>/dev/null; then
    RUNNER_FINGERPRINT=$(echo "$FINGERPRINT_INPUT" | sha256sum | cut -d' ' -f1)
else
    RUNNER_FINGERPRINT="unknown"
fi

# ── Create snapshot sandbox ──────────────────────────────────

SNAPSHOT_DIR=$(mktemp -d)
trap 'rm -rf "$SNAPSHOT_DIR"' EXIT

# Record pre-review state for post-review validation
PRE_REVIEW_HEAD=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "none")
PRE_REVIEW_STATUS=$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null || echo "")

# Copy working tree to snapshot (reviewer runs here, not in real repo)
cp -R "$PROJECT_DIR" "$SNAPSHOT_DIR/workspace"
# Remove real .git so reviewer cannot affect the actual repo
rm -rf "$SNAPSHOT_DIR/workspace/.git"
SANDBOX_DIR="$SNAPSHOT_DIR/workspace"

# ── Build review request ─────────────────────────────────────

REVIEW_REQUEST=$(mktemp)

# Include prior findings context if this is a subsequent round
PRIOR_CONTEXT=""
if [[ "$CURRENT_ROUND" -gt 0 ]]; then
    PREV_FINDINGS="$REVIEW_DIR/findings-round-${CURRENT_ROUND}.json"
    PREV_RESOLUTION="$REVIEW_DIR/resolution-round-${CURRENT_ROUND}.json"
    if [[ -f "$PREV_FINDINGS" ]]; then
        PRIOR_CONTEXT="## Prior Round Findings (Round $CURRENT_ROUND)

$(jq -r '.findings[] | "- [\(.severity)] \(.id): \(.description) (file: \(.file))"' "$PREV_FINDINGS" 2>/dev/null || echo "(could not parse prior findings)")
"
    fi
    if [[ -f "$PREV_RESOLUTION" ]]; then
        PRIOR_CONTEXT="$PRIOR_CONTEXT
## Builder Resolutions (Round $CURRENT_ROUND)

$(jq -r '.resolutions[] | "- \(.finding_id): \(.disposition)\(.detail // "" | if . != "" then " — " + . else "" end)"' "$PREV_RESOLUTION" 2>/dev/null || echo "(could not parse prior resolutions)")
"
    fi
fi

cat > "$REVIEW_REQUEST" << REVIEW_EOF
# Peer Review Request — Round $NEXT_ROUND

Feature: $FEATURE_ID
Phase: $PHASE
Scope: $REVIEW_SCOPE
Target ref: $TARGET_REF
Round: $NEXT_ROUND

## Review Instructions

You are a code reviewer. Review the changes and produce structured findings.
$(if [[ "$REVIEW_SCOPE" == "code" ]]; then
    echo "Focus on: code correctness, edge cases, error handling, security vulnerabilities, performance."
elif [[ "$REVIEW_SCOPE" == "design" ]]; then
    echo "Focus on: architecture decisions, API design, interface contracts, scalability, maintainability."
else
    echo "Focus on: code correctness, architecture decisions, security, API design, error handling."
fi)

${PRIOR_CONTEXT}
## Files to Review

$(if [[ -d "$SANDBOX_DIR/specs/$FEATURE_ID" ]]; then
    find "$SANDBOX_DIR/specs/$FEATURE_ID" -name '*.md' -not -path '*/collaboration/*' | sort | while read -r f; do
        echo "- ${f#$SANDBOX_DIR/}"
    done
else
    echo "- No spec artifacts found at specs/$FEATURE_ID/"
fi)

## Required Output Format

You MUST structure your response with these exact sections:

### Summary
2-3 sentences summarizing the review.

### Findings
For each finding, use this exact format (one per line):
FINDING|<severity>|<category>|<file>|<line_hint>|<description>|<suggested_fix>

Where:
- severity: blocking, warning, or note
- category: correctness, security, style, performance, design, testing, documentation
- file: path relative to project root
- line_hint: semantic anchor (e.g., "near variable expansion in query function")
- description: clear description of the issue
- suggested_fix: actionable fix suggestion

### Verdict
State exactly one of: PASS, FAIL, or INCONCLUSIVE
REVIEW_EOF

# ── Execute provider ─────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ADAPTER_DIR="$SCRIPT_DIR/provider-adapters"

build_provider_cmd() {
    case "$PROVIDER_TYPE" in
        cli|custom)
            local cmd="$COMMAND_TEMPLATE"
            cmd="${cmd//\{review_request\}/$REVIEW_REQUEST}"
            cmd="${cmd//\{model\}/${PROVIDER_MODEL:-}}"
            echo "$cmd"
            ;;
        openai-compatible)
            local cmd="'$ADAPTER_DIR/openai-compatible.sh'"
            cmd="$cmd --base-url '$PROVIDER_BASE_URL'"
            cmd="$cmd --model '$PROVIDER_MODEL'"
            cmd="$cmd --input '$REVIEW_REQUEST'"
            [[ -n "${PROVIDER_API_KEY_ENV:-}" ]] && cmd="$cmd --api-key-env '$PROVIDER_API_KEY_ENV'"
            [[ -n "${PROVIDER_MAX_TOKENS:-}" ]] && cmd="$cmd --max-tokens '$PROVIDER_MAX_TOKENS'"
            [[ -n "${PROVIDER_TEMPERATURE:-}" ]] && cmd="$cmd --temperature '$PROVIDER_TEMPERATURE'"
            echo "$cmd"
            ;;
        ollama)
            local cmd="'$ADAPTER_DIR/ollama.sh'"
            cmd="$cmd --model '$PROVIDER_MODEL'"
            cmd="$cmd --input '$REVIEW_REQUEST'"
            [[ -n "${PROVIDER_HOST:-}" ]] && cmd="$cmd --host '$PROVIDER_HOST'"
            echo "$cmd"
            ;;
        *)
            echo "Error: Unknown provider type '$PROVIDER_TYPE'" >&2
            return 1
            ;;
    esac
}

RESOLVED_CMD=$(build_provider_cmd) || exit 1

TIMEOUT_CMD=""
if command -v timeout &>/dev/null; then
    TIMEOUT_CMD="timeout"
elif command -v gtimeout &>/dev/null; then
    TIMEOUT_CMD="gtimeout"
fi

echo "Running review round $NEXT_ROUND via '$PEER_PROVIDER' (type: $PROVIDER_TYPE)..." >&2

# Run the reviewer inside the sandbox directory with read-only env marker.
# SSH_AUTH_SOCK and GPG_AGENT_INFO are unset to prevent commit signing.
SANDBOX_ENV="env -u SSH_AUTH_SOCK -u GPG_AGENT_INFO CCT_READ_ONLY=true"

if [[ -n "$TIMEOUT_CMD" ]]; then
    REVIEW_OUTPUT=$(cd "$SANDBOX_DIR" && $TIMEOUT_CMD "$PROVIDER_TIMEOUT" $SANDBOX_ENV bash -c "$RESOLVED_CMD" 2>&1) && REVIEW_EXIT=0 || REVIEW_EXIT=$?
else
    REVIEW_OUTPUT=$(cd "$SANDBOX_DIR" && $SANDBOX_ENV bash -c "$RESOLVED_CMD" 2>&1) && REVIEW_EXIT=0 || REVIEW_EXIT=$?
fi

rm -f "$REVIEW_REQUEST"

if [[ $REVIEW_EXIT -eq 124 || $REVIEW_EXIT -eq 143 ]]; then
    echo "Error: Provider '$PEER_PROVIDER' timed out after ${PROVIDER_TIMEOUT}s." >&2
    exit 1
fi

# ── Post-review validation ───────────────────────────────────

POST_REVIEW_HEAD=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "none")
POST_REVIEW_STATUS=$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null || echo "")

ROUND_VALID=true
if [[ "$PRE_REVIEW_HEAD" != "$POST_REVIEW_HEAD" ]]; then
    echo "INVALID: git HEAD changed during review ($PRE_REVIEW_HEAD → $POST_REVIEW_HEAD)." >&2
    ROUND_VALID=false
fi
if [[ "$PRE_REVIEW_STATUS" != "$POST_REVIEW_STATUS" ]]; then
    echo "INVALID: working tree changed during review." >&2
    ROUND_VALID=false
fi

# ── Parse findings ───────────────────────────────────────────

compute_finding_id() {
    local file="$1" category="$2" description="$3"
    # Normalize: lowercase, collapse whitespace, strip line number refs
    local normalized
    normalized=$(echo "$description" | tr '[:upper:]' '[:lower:]' | tr -s ' ' | sed 's/line [0-9]*//g; s/  */ /g')
    local input="${file}|${category}|${normalized}"
    local hash
    if command -v shasum &>/dev/null; then
        hash=$(printf '%s' "$input" | shasum -a 256 | cut -c1-8)
    elif command -v sha256sum &>/dev/null; then
        hash=$(printf '%s' "$input" | sha256sum | cut -c1-8)
    else
        hash="00000000"
    fi
    echo "f-${hash}"
}

# Extract verdict
VERDICT="INCONCLUSIVE"
if echo "$REVIEW_OUTPUT" | grep -q '^### Verdict'; then
    VERDICT_LINE=$(echo "$REVIEW_OUTPUT" | sed -n '/^### Verdict/,/^$/p' | grep -oiE 'PASS|FAIL|INCONCLUSIVE' | head -1 | tr '[:lower:]' '[:upper:]')
    if [[ -n "$VERDICT_LINE" ]]; then
        VERDICT="$VERDICT_LINE"
    fi
elif echo "$REVIEW_OUTPUT" | grep -qi "PASS"; then
    VERDICT="PASS"
elif echo "$REVIEW_OUTPUT" | grep -qi "FAIL"; then
    VERDICT="FAIL"
fi

# If round is invalid, discard findings
if [[ "$ROUND_VALID" != "true" ]]; then
    VERDICT="INVALID"
fi

if [[ $REVIEW_EXIT -ne 0 ]]; then
    VERDICT="FAIL"
fi

# Parse FINDING| lines into JSON
FINDINGS_JSON="[]"
if [[ "$ROUND_VALID" == "true" ]]; then
    while IFS='|' read -r _ severity category file line_hint description suggested_fix; do
        [[ -z "$severity" ]] && continue
        severity=$(echo "$severity" | tr -d ' ' | tr '[:upper:]' '[:lower:]')
        category=$(echo "$category" | tr -d ' ' | tr '[:upper:]' '[:lower:]')
        file=$(echo "$file" | tr -d ' ')

        FINDING_ID=$(compute_finding_id "$file" "$category" "$description")

        # Check first_seen from state
        FIRST_SEEN=$NEXT_ROUND
        if [[ -f "$STATE_FILE" ]]; then
            EXISTING_FIRST=$(jq -r --arg id "$FINDING_ID" '.findings[$id].first_seen_round // empty' "$STATE_FILE" 2>/dev/null)
            if [[ -n "$EXISTING_FIRST" ]]; then
                FIRST_SEEN=$EXISTING_FIRST
            fi
        fi

        FINDINGS_JSON=$(echo "$FINDINGS_JSON" | jq \
            --arg id "$FINDING_ID" \
            --arg sev "$severity" \
            --arg cat "$category" \
            --arg file "$file" \
            --arg hint "$line_hint" \
            --arg desc "$description" \
            --arg fix "$suggested_fix" \
            --argjson fsr "$FIRST_SEEN" \
            '. + [{id: $id, severity: $sev, category: $cat, file: $file,
                    line_hint: $hint, description: $desc, suggested_fix: $fix,
                    first_seen_round: $fsr, disposition: null}]')
    done < <(echo "$REVIEW_OUTPUT" | grep '^FINDING|')
fi

BLOCKING_COUNT=$(echo "$FINDINGS_JSON" | jq '[.[] | select(.severity == "blocking")] | length')

# If there are blocking findings and verdict was PASS, override to FAIL
if [[ "$BLOCKING_COUNT" -gt 0 && "$VERDICT" == "PASS" ]]; then
    VERDICT="FAIL"
fi

# ── Write findings-round-N.json ──────────────────────────────

FINDINGS_FILE="$REVIEW_DIR/findings-round-${NEXT_ROUND}.json"
cat > "$FINDINGS_FILE" << FINDINGS_EOF
$(jq -n \
    --argjson round "$NEXT_ROUND" \
    --arg verdict "$VERDICT" \
    --arg provider "$PEER_PROVIDER" \
    --argjson findings "$FINDINGS_JSON" \
    --arg raw_output "$REVIEW_OUTPUT" \
    '{round: $round, verdict: $verdict, reviewer_provider: $provider,
      findings: $findings, raw_output: $raw_output}')
FINDINGS_EOF

echo "Round $NEXT_ROUND findings written to $FINDINGS_FILE" >&2
echo "Verdict: $VERDICT (blocking: $BLOCKING_COUNT)" >&2

# ── Update state.json ────────────────────────────────────────

# Merge findings into accumulated state
ACCUMULATED=$(jq '.findings // {}' "$STATE_FILE" 2>/dev/null || echo '{}')

# Update accumulated findings with this round's data
for FINDING_ID in $(echo "$FINDINGS_JSON" | jq -r '.[].id'); do
    FINDING_DATA=$(echo "$FINDINGS_JSON" | jq --arg id "$FINDING_ID" '.[] | select(.id == $id)')
    DESCRIPTION=$(echo "$FINDING_DATA" | jq -r '.description')
    FIRST_SEEN=$(echo "$FINDING_DATA" | jq -r '.first_seen_round')

    # Get existing rounds_seen array or start fresh
    EXISTING_ROUNDS=$(echo "$ACCUMULATED" | jq -r --arg id "$FINDING_ID" '.[$id].rounds_seen // []')
    UPDATED_ROUNDS=$(echo "$EXISTING_ROUNDS" | jq --argjson r "$NEXT_ROUND" '. + [$r] | unique')

    # Track consecutive_fixed from prior resolutions
    CONSEC_FIXED=0
    if [[ -f "$STATE_FILE" ]]; then
        CONSEC_FIXED=$(echo "$ACCUMULATED" | jq -r --arg id "$FINDING_ID" '.[$id].consecutive_fixed // 0')
        # Check if last round's resolution was "fixed"
        PREV_RESOLUTION="$REVIEW_DIR/resolution-round-${CURRENT_ROUND}.json"
        if [[ -f "$PREV_RESOLUTION" ]]; then
            PREV_DISP=$(jq -r --arg id "$FINDING_ID" '.resolutions[] | select(.finding_id == $id) | .disposition // ""' "$PREV_RESOLUTION" 2>/dev/null)
            if [[ "$PREV_DISP" == "fixed" ]]; then
                CONSEC_FIXED=$((CONSEC_FIXED + 1))
            else
                CONSEC_FIXED=0
            fi
        fi
    fi

    ACCUMULATED=$(echo "$ACCUMULATED" | jq \
        --arg id "$FINDING_ID" \
        --arg desc "$DESCRIPTION" \
        --argjson fsr "$FIRST_SEEN" \
        --argjson rounds "$UPDATED_ROUNDS" \
        --argjson cf "$CONSEC_FIXED" \
        '.[$id] = {description: $desc, first_seen_round: $fsr, rounds_seen: $rounds, consecutive_fixed: $cf}')
done

jq -n \
    --argjson round "$NEXT_ROUND" \
    --argjson attempt "$ATTEMPT" \
    --argjson loop_start "$LOOP_START" \
    --arg feature_id "$FEATURE_ID" \
    --arg phase "$PHASE" \
    --arg subject_provider "$SUBJECT_PROVIDER" \
    --arg peer_provider "$PEER_PROVIDER" \
    --arg review_scope "$REVIEW_SCOPE" \
    --arg target_ref "$TARGET_REF" \
    --arg last_verdict "$VERDICT" \
    --argjson findings "$ACCUMULATED" \
    '{current_round: $round, attempt: $attempt, loop_start: $loop_start,
      feature_id: $feature_id, phase: $phase,
      subject_provider: $subject_provider, peer_provider: $peer_provider,
      review_scope: $review_scope, target_ref: $target_ref,
      last_verdict: $last_verdict, findings: $findings}' \
    > "$STATE_FILE"

# ── Write loop-summary.json on PASS ──────────────────────────

if [[ "$VERDICT" == "PASS" ]]; then
    TODAY=$(date +%Y-%m-%d)
    jq -n \
        --arg feature_id "$FEATURE_ID" \
        --arg date "$TODAY" \
        --arg phase "$PHASE" \
        --arg verdict "PASS" \
        --argjson rounds_completed "$NEXT_ROUND" \
        --argjson attempt "$ATTEMPT" \
        --arg subject_provider "$SUBJECT_PROVIDER" \
        --arg peer_provider "$PEER_PROVIDER" \
        --arg runner_fingerprint "$RUNNER_FINGERPRINT" \
        --argjson bypass false \
        --arg target_ref "$TARGET_REF" \
        --argjson findings "$ACCUMULATED" \
        '{feature_id: $feature_id, date: $date, phase: $phase, verdict: $verdict,
          rounds_completed: $rounds_completed, attempt_count: $attempt,
          subject_provider: $subject_provider, peer_provider: $peer_provider,
          runner_fingerprint: $runner_fingerprint, bypass: $bypass,
          target_ref: $target_ref, findings: $findings}' \
        > "$REVIEW_DIR/loop-summary.json"

    # Write collaboration artifact
    if [[ "$PHASE" == "plan" ]]; then
        ARTIFACT_NAME="plan-consult.md"
        MODE="consult"
    else
        ARTIFACT_NAME="build-review.md"
        MODE="review"
    fi

    COLLAB_DIR="$PROJECT_DIR/specs/$FEATURE_ID/collaboration"
    mkdir -p "$COLLAB_DIR"
    cat > "$COLLAB_DIR/$ARTIFACT_NAME" << ARTIFACT_EOF
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
rounds_completed: $NEXT_ROUND
attempt_count: $ATTEMPT
bypass: false
---

# Peer Review: $FEATURE_ID — $(echo "$PHASE" | awk '{print toupper(substr($0,1,1)) substr($0,2)}') Phase

**Reviewer**: $PEER_PROVIDER
**Scope**: $REVIEW_SCOPE
**Rounds**: $NEXT_ROUND
**Verdict**: $VERDICT

## Summary

$(echo "$REVIEW_OUTPUT" | awk '/^### Summary/{found=1; next} /^### /{found=0} found{print}')

## Findings

$(echo "$FINDINGS_JSON" | jq -r '.[] | "- [\(.severity)] \(.id): \(.description) (\(.file))"')
ARTIFACT_EOF

    echo "PASS — loop-summary.json and collaboration artifact written." >&2
    exit 0
fi

# FAIL or INVALID
exit 1
