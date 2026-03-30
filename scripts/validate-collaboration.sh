#!/usr/bin/env bash
set -euo pipefail

# validate-collaboration.sh — CI gate for peer review collaboration artifacts
#
# Validates that collaboration artifacts exist and meet review requirements:
#   - Build phase: PASS or approved bypass required (blocks PR on failure)
#   - Plan phase: advisory (warns on FAIL, does not block PR)
#   - Bypass without logged breaker type and decision fails
#
# Usage: validate-collaboration.sh [--project-dir DIR]
# Exit:  0 = pass, 1 = fail
#
# Requires: jq

# ── Parse arguments ──────────────────────────────────────────

PROJECT_DIR="."

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir) PROJECT_DIR="${2:?--project-dir requires a path}"; shift 2 ;;
        -h|--help)
            echo "Usage: validate-collaboration.sh [--project-dir DIR]"
            exit 0
            ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

if ! command -v jq &>/dev/null; then
    echo "Error: jq is required" >&2
    exit 1
fi

# ── Find collaboration artifacts ─────────────────────────────

SPECS_DIR="$PROJECT_DIR/specs"
ERRORS=0
WARNINGS=0

if [[ ! -d "$SPECS_DIR" ]]; then
    echo "No specs/ directory found. Skipping collaboration validation."
    exit 0
fi

# Find all feature directories that have collaboration artifacts
FEATURES=()
for feature_dir in "$SPECS_DIR"/*/; do
    [[ -d "$feature_dir" ]] || continue
    collab_dir="$feature_dir/collaboration"
    [[ -d "$collab_dir" ]] || continue
    FEATURES+=("$(basename "$feature_dir")")
done

if [[ ${#FEATURES[@]} -eq 0 ]]; then
    echo "No collaboration artifacts found. Skipping validation."
    exit 0
fi

echo "Collaboration Artifact Validation"
echo "================================="
echo ""

# ── Validate each feature's artifacts ────────────────────────

for feature in "${FEATURES[@]}"; do
    COLLAB_DIR="$SPECS_DIR/$feature/collaboration"
    echo "Feature: $feature"

    # Check build-review.md
    BUILD_REVIEW="$COLLAB_DIR/build-review.md"
    if [[ -f "$BUILD_REVIEW" ]]; then
        # Extract frontmatter values
        VERDICT=$(sed -n '/^---$/,/^---$/p' "$BUILD_REVIEW" | grep '^verdict:' | sed 's/^verdict: *//' || true)
        BYPASS=$(sed -n '/^---$/,/^---$/p' "$BUILD_REVIEW" | grep '^bypass:' | sed 's/^bypass: *//' || true)
        BLOCKING=$(sed -n '/^---$/,/^---$/p' "$BUILD_REVIEW" | grep '^blocking_findings_open:' | sed 's/^blocking_findings_open: *//' || true)
        SUBJECT=$(sed -n '/^---$/,/^---$/p' "$BUILD_REVIEW" | grep '^subject_provider:' | sed 's/^subject_provider: *//' || true)
        PEER=$(sed -n '/^---$/,/^---$/p' "$BUILD_REVIEW" | grep '^peer_provider:' | sed 's/^peer_provider: *//' || true)

        # FR-046: Build review must be PASS or approved bypass
        if [[ "$VERDICT" == "PASS" ]]; then
            echo "  build-review.md: PASS ✓"
        elif [[ "$BYPASS" == "true" ]]; then
            # FR-047: Bypass must have breaker type logged in the artifact itself
            BREAKER_TYPE=$(sed -n '/^---$/,/^---$/p' "$BUILD_REVIEW" | grep '^breaker_type:' | sed 's/^breaker_type: *//' || true)
            if [[ -z "$BREAKER_TYPE" ]]; then
                echo "  build-review.md: BYPASS without breaker_type in artifact — FAIL"
                ERRORS=$((ERRORS + 1))
            else
                echo "  build-review.md: BYPASS (breaker: $BREAKER_TYPE) ✓"
            fi
        else
            echo "  build-review.md: verdict '$VERDICT' — FAIL (PASS or approved bypass required)"
            ERRORS=$((ERRORS + 1))
        fi

        # Check blocking findings
        if [[ -n "$BLOCKING" && "$BLOCKING" != "0" && "$VERDICT" != "PASS" && "$BYPASS" != "true" ]]; then
            echo "  build-review.md: $BLOCKING blocking findings open — FAIL"
            ERRORS=$((ERRORS + 1))
        fi

        # Check subject != peer
        if [[ -n "$SUBJECT" && -n "$PEER" && "$SUBJECT" == "$PEER" ]]; then
            echo "  build-review.md: subject == peer ('$SUBJECT') — FAIL"
            ERRORS=$((ERRORS + 1))
        fi
    fi

    # Check plan-consult.md (advisory — warn only)
    PLAN_CONSULT="$COLLAB_DIR/plan-consult.md"
    if [[ -f "$PLAN_CONSULT" ]]; then
        PLAN_VERDICT=$(sed -n '/^---$/,/^---$/p' "$PLAN_CONSULT" | grep '^verdict:' | sed 's/^verdict: *//' || true)
        if [[ "$PLAN_VERDICT" == "PASS" ]]; then
            echo "  plan-consult.md: PASS ✓"
        else
            # FR-046: Plan review is advisory — warn, don't block
            echo "  plan-consult.md: verdict '$PLAN_VERDICT' — WARNING (advisory, does not block PR)"
            WARNINGS=$((WARNINGS + 1))
        fi
    fi

    echo ""
done

# ── Summary ──────────────────────────────────────────────────

echo "================================="
if [[ $ERRORS -gt 0 ]]; then
    echo "FAILED: $ERRORS error(s), $WARNINGS warning(s)"
    exit 1
elif [[ $WARNINGS -gt 0 ]]; then
    echo "PASSED with $WARNINGS warning(s)"
    exit 0
else
    echo "PASSED: all collaboration artifacts valid"
    exit 0
fi
