#!/usr/bin/env bash

# validate-spec.sh — Validate SDD artifacts in specs/*/ directories
#
# Checks that each spec directory conforms to the spec_mode declared
# in its plan.md YAML frontmatter, per shared/rules/on-demand/spec-workflow.md.
#
# Usage:
#   validate-spec.sh [--feature-id ID | --all]
#   Default: --all

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SPECS_DIR="$REPO_DIR/specs"

TOTAL_PASS=0
TOTAL_FAIL=0

# ── Helpers ──────────────────────────────────────────────────

# Extract a YAML frontmatter field value from a file.
# Expects --- delimited frontmatter at the top of the file.
extract_frontmatter_field() {
  local file="$1" field="$2"
  sed -n '/^---$/,/^---$/p' "$file" \
    | grep "^${field}:" \
    | head -1 \
    | sed "s/^${field}:[[:space:]]*//" \
    | sed 's/^"\(.*\)"$/\1/' \
    | sed "s/^'\(.*\)'$/\1/" \
    | tr -d '[:space:]'
}

pass() {
  echo "  [PASS] $1"
  TOTAL_PASS=$((TOTAL_PASS + 1))
}

fail() {
  echo "  [FAIL] $1"
  TOTAL_FAIL=$((TOTAL_FAIL + 1))
}

# ── Per-spec validation ──────────────────────────────────────

validate_spec_dir() {
  local spec_dir="$1"
  local id
  id="$(basename "$spec_dir")"
  local plan="$spec_dir/plan.md"

  echo "--- $id ---"

  # plan.md must exist
  if [[ ! -f "$plan" ]]; then
    fail "$id: plan.md not found"
    return
  fi

  # Extract required frontmatter fields
  local spec_mode feature_id justification status
  spec_mode="$(extract_frontmatter_field "$plan" "spec_mode")"
  feature_id="$(extract_frontmatter_field "$plan" "feature_id")"
  justification="$(extract_frontmatter_field "$plan" "justification")"
  status="$(extract_frontmatter_field "$plan" "status")"

  # spec_mode must be present and valid
  if [[ -z "$spec_mode" ]]; then
    fail "$id: spec_mode missing from plan.md frontmatter"
    return
  fi

  if [[ "$spec_mode" != "full" && "$spec_mode" != "lightweight" && "$spec_mode" != "none" ]]; then
    fail "$id: spec_mode '$spec_mode' is not valid (must be full, lightweight, or none)"
    return
  fi

  # feature_id must be present
  if [[ -z "$feature_id" ]]; then
    fail "$id: feature_id missing from plan.md frontmatter"
    return
  fi

  # status must be present and valid
  if [[ -z "$status" ]]; then
    fail "$id: status missing from plan.md frontmatter"
    return
  fi

  if [[ "$status" != "draft" && "$status" != "approved" ]]; then
    fail "$id: status '$status' is not valid (must be draft or approved)"
    return
  fi
  pass "$id: plan.md frontmatter valid (spec_mode=$spec_mode, status=$status)"

  # Mode-specific validation
  case "$spec_mode" in
    full)
      # spec.md must exist
      if [[ ! -f "$spec_dir/spec.md" ]]; then
        fail "$id: spec.md required for spec_mode=full but not found"
        return
      fi

      # spec.md must have User Scenarios, Requirements, Constraints sections
      local missing_sections=""
      grep -q '## User Scenarios' "$spec_dir/spec.md" || missing_sections="$missing_sections User Scenarios,"
      grep -q '## Requirements' "$spec_dir/spec.md" || missing_sections="$missing_sections Requirements,"
      grep -q '## Constraints' "$spec_dir/spec.md" || missing_sections="$missing_sections Constraints,"

      if [[ -n "$missing_sections" ]]; then
        fail "$id: spec.md missing required sections:$missing_sections"
        return
      fi

      # No unresolved [NEEDS CLARIFICATION] markers
      # Match actual markers: [NEEDS CLARIFICATION]: ... or [NEEDS CLARIFICATION: ...]
      # but not descriptive references like "has unresolved [NEEDS CLARIFICATION] markers"
      if grep -qE '\[NEEDS CLARIFICATION\]:|\[NEEDS CLARIFICATION:' "$spec_dir/spec.md"; then
        fail "$id: spec.md has unresolved [NEEDS CLARIFICATION] markers"
        return
      fi

      # tasks.md must exist
      if [[ ! -f "$spec_dir/tasks.md" ]]; then
        fail "$id: tasks.md required for spec_mode=full but not found"
        return
      fi

      pass "$id: spec_mode=full artifacts valid"
      ;;

    lightweight)
      # spec.md must exist
      if [[ ! -f "$spec_dir/spec.md" ]]; then
        fail "$id: spec.md required for spec_mode=lightweight but not found"
        return
      fi

      # spec.md must have Requirements and Constraints sections
      local missing_sections=""
      grep -q '## Requirements' "$spec_dir/spec.md" || missing_sections="$missing_sections Requirements,"
      grep -q '## Constraints' "$spec_dir/spec.md" || missing_sections="$missing_sections Constraints,"

      if [[ -n "$missing_sections" ]]; then
        fail "$id: spec.md missing required sections:$missing_sections"
        return
      fi

      # No unresolved [NEEDS CLARIFICATION] markers
      # Match actual markers: [NEEDS CLARIFICATION]: ... or [NEEDS CLARIFICATION: ...]
      # but not descriptive references like "has unresolved [NEEDS CLARIFICATION] markers"
      if grep -qE '\[NEEDS CLARIFICATION\]:|\[NEEDS CLARIFICATION:' "$spec_dir/spec.md"; then
        fail "$id: spec.md has unresolved [NEEDS CLARIFICATION] markers"
        return
      fi

      pass "$id: spec_mode=lightweight artifacts valid"
      ;;

    none)
      # justification must be non-empty
      if [[ -z "$justification" ]]; then
        fail "$id: justification required in plan.md frontmatter for spec_mode=none"
        return
      fi

      # spec.md must NOT exist
      if [[ -f "$spec_dir/spec.md" ]]; then
        fail "$id: spec.md must NOT exist for spec_mode=none"
        return
      fi

      pass "$id: spec_mode=none artifacts valid"
      ;;
  esac
}

# ── CLI ──────────────────────────────────────────────────────

MODE="all"
FEATURE_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --feature-id)
      MODE="single"
      FEATURE_ID="$2"
      shift 2
      ;;
    --all)
      MODE="all"
      shift
      ;;
    *)
      echo "Usage: validate-spec.sh [--feature-id ID | --all]"
      exit 1
      ;;
  esac
done

echo "=== Validating SDD spec conformance ==="
echo ""

if [[ "$MODE" == "single" ]]; then
  if [[ ! -d "$SPECS_DIR/$FEATURE_ID" ]]; then
    echo "  [FAIL] specs/$FEATURE_ID/ directory not found"
    exit 1
  fi
  validate_spec_dir "$SPECS_DIR/$FEATURE_ID"
else
  found=0
  for dir in "$SPECS_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    # Skip directories without plan.md (e.g. .DS_Store artifacts)
    [[ -f "$dir/plan.md" ]] || continue
    found=1
    validate_spec_dir "$dir"
  done
  if [[ "$found" -eq 0 ]]; then
    echo "No spec directories found in specs/"
    exit 0
  fi
fi

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$TOTAL_PASS" "$TOTAL_FAIL"
echo "========================================="

if [[ $TOTAL_FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
