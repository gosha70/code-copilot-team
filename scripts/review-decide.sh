#!/usr/bin/env bash

# review-decide.sh — the deterministic core of /review-decide (#233).
#
# Validates the breaker state, writes .cct/review/decision.json, and applies
# retry semantics (attempt bump + loop_start reset). When
# .cct/review/breaker-tripped.json is missing — a crash can park a run
# without ever writing it — the breaker context is RECONSTRUCTED from the
# newest unresolved review_breaker escalation of THIS feature only, bound
# via .cct/review/state.json's feature_id, and the provenance is recorded
# in decision.json for the driver to validate on resume.
#
# The human-facing narrative (approve's bypass artifacts, reject's summary)
# stays in the /review-decide command; this script owns exactly the state
# transitions that must not depend on prompt-following.
#
# Usage: review-decide.sh <project-dir> <approve|reject|retry>
# Exit:  0 decision written; 1 usage/refusal (message on stderr).

set -uo pipefail

PROJECT_DIR="${1:-}"
DECISION="${2:-}"

if [[ -z "$PROJECT_DIR" || ! -d "$PROJECT_DIR" ]]; then
    echo "Usage: review-decide.sh <project-dir> <approve|reject|retry>" >&2
    exit 1
fi
case "$DECISION" in
    approve|reject|retry) ;;
    *)
        echo "Usage: review-decide.sh <project-dir> <approve|reject|retry>" >&2
        exit 1
        ;;
esac
if ! command -v jq &>/dev/null; then
    echo "Error: jq is required." >&2
    exit 1
fi

REVIEW_DIR="$PROJECT_DIR/.cct/review"
BTF="$REVIEW_DIR/breaker-tripped.json"
STATE="$REVIEW_DIR/state.json"

BREAKER_TYPE=""
RECONSTRUCTED_FROM=""

if [[ -f "$BTF" ]]; then
    # Normal path: the breaker artifact exists. Two producers, two key
    # names (runner writes `breaker`, driver writes `breaker_type`).
    BREAKER_TYPE=$(jq -r '.breaker_type // .breaker // "unknown"' "$BTF" 2>/dev/null || echo "unknown")
else
    # Reconstruction path (#233): bind to THIS feature via state.json —
    # scanning every ledger could resolve another feature's breaker with
    # this feature's decision.
    if [[ ! -f "$STATE" ]]; then
        echo "Error: no .cct/review/breaker-tripped.json and no .cct/review/state.json —" >&2
        echo "cannot bind a reconstruction to a feature. Nothing to decide." >&2
        exit 1
    fi
    FEATURE_ID=$(jq -r '.feature_id // empty' "$STATE" 2>/dev/null)
    if [[ -z "$FEATURE_ID" ]]; then
        echo "Error: .cct/review/state.json carries no feature_id — cannot bind a" >&2
        echo "reconstruction to a feature. Nothing to decide." >&2
        exit 1
    fi
    # feature_id is about to become a path segment — a separator or
    # traversal here would walk the reconstruction out of the ledger.
    if [[ ! "$FEATURE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
        echo "Error: state.json feature_id '$FEATURE_ID' is not a safe path segment — refusing." >&2
        exit 1
    fi
    ESC_DIR="$PROJECT_DIR/.cct/auto-build/$FEATURE_ID/escalations"
    NEWEST=""
    i=1
    while [[ -f "$ESC_DIR/esc-$i.json" ]]; do
        esc="$ESC_DIR/esc-$i.json"
        case "$(jq -r 'if type == "object" and (.resolved | type == "boolean")
                       then ((.reason // "") + ":" + (.resolved | tostring)) else "invalid" end' \
                "$esc" 2>/dev/null)" in
            review_breaker:false) NEWEST="$esc" ;;
            invalid)
                echo "Error: escalation record $esc is unreadable — refusing to reconstruct from corrupt state." >&2
                exit 1
                ;;
        esac
        i=$((i + 1))
    done
    # A GAP (esc-2 missing while esc-3 exists) hides everything above it
    # from the sequential scan — an unresolved later record must never
    # read as "nothing to decide". Same fail-closed rule as the driver.
    top=$((i - 1))
    for f in "$ESC_DIR"/esc-*.json; do
        [[ -e "$f" ]] || continue
        n=$(basename "$f" .json); n=${n#esc-}
        [[ "$n" =~ ^[0-9]+$ ]] || continue
        if (( n > top )); then
            echo "Error: escalation records are gapped (esc-$((top + 1)) missing while esc-$n exists) —" >&2
            echo "the sequence cannot be trusted; refusing to reconstruct." >&2
            exit 1
        fi
    done
    if [[ -z "$NEWEST" ]]; then
        echo "No active circuit breaker: .cct/review/breaker-tripped.json does not exist and" >&2
        echo "no unresolved review_breaker escalation was found under" >&2
        echo ".cct/auto-build/$FEATURE_ID/escalations/. Nothing to decide." >&2
        exit 1
    fi
    DETAIL=$(jq -r '.detail // ""' "$NEWEST")
    if [[ "$DETAIL" =~ review\ runner\ exited\ [0-9]+ ]]; then
        BREAKER_TYPE="runner_crash_legacy"
    else
        BREAKER_TYPE="reconstructed"
    fi
    RECONSTRUCTED_FROM="$NEWEST"
    echo "[review-decide] no breaker-tripped.json — reconstructed '$BREAKER_TYPE' from $NEWEST" >&2
    echo "[review-decide] WARNING: a crash park's review state may be inconsistent (findings can be newer than state.json)." >&2
fi

NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# Stage the decision, but PUBLISH it last: decision.json is the marker the
# driver consumes, so it must never exist over stale retry state. Ordering
# is stage-decision -> apply-retry-state (checked, durable) -> publish.
DEC_TMP=$(mktemp "$REVIEW_DIR/decision.XXXXXX") || { echo "Error: mktemp failed" >&2; exit 1; }
if ! jq -n --arg d "$DECISION" --arg t "$NOW_ISO" --arg b "$BREAKER_TYPE" --arg r "$RECONSTRUCTED_FROM" \
    '{decision: $d, timestamp: $t, breaker_type: $b}
     + (if $r != "" then {reconstructed_from: $r} else {} end)' > "$DEC_TMP"; then
    rm -f "$DEC_TMP"
    echo "Error: could not stage decision.json" >&2
    exit 1
fi

if [[ "$DECISION" == "retry" ]]; then
    # Retry semantics are MANDATORY, reconstruction or not (#233's
    # second-order trap): a park can sit for hours, and a retry that only
    # writes decision.json trips the review loop clock before the next
    # reviewer runs. Any failure here leaves NO consumable decision.
    if [[ ! -f "$STATE" ]]; then
        rm -f "$DEC_TMP"
        echo "Error: retry needs .cct/review/state.json (attempt bump + loop_start reset) and it is missing — no decision was recorded." >&2
        exit 1
    fi
    ST_TMP=$(mktemp "$REVIEW_DIR/state.XXXXXX") || { rm -f "$DEC_TMP"; echo "Error: mktemp failed — no decision was recorded" >&2; exit 1; }
    if ! jq --argjson now "$(date +%s)" '.attempt = ((.attempt // 1) + 1) | .loop_start = $now' \
        "$STATE" > "$ST_TMP"; then
        rm -f "$ST_TMP" "$DEC_TMP"
        echo "Error: could not apply retry semantics to state.json — no decision was recorded." >&2
        exit 1
    fi
    if ! mv "$ST_TMP" "$STATE"; then
        rm -f "$ST_TMP" "$DEC_TMP"
        echo "Error: could not publish the retry state update — no decision was recorded." >&2
        exit 1
    fi
    echo "[review-decide] retry: attempt bumped, loop_start reset" >&2
fi

if ! mv "$DEC_TMP" "$REVIEW_DIR/decision.json"; then
    rm -f "$DEC_TMP"
    echo "Error: could not publish decision.json" >&2
    exit 1
fi

rm -f "$BTF" 2>/dev/null || true
echo "[review-decide] decision '$DECISION' recorded (breaker_type: $BREAKER_TYPE)" >&2
exit 0
