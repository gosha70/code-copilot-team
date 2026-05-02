#!/usr/bin/env bash

# validate-pitch.sh — Validate Shape-Up pitch artifacts in specs/pitches/*/
#
# Checks that each pitch directory has a pitch.md whose YAML frontmatter
# conforms to the schema declared in shared/templates/sdd/pitch-template.md
# and the FRs in specs/pitches/0001-shape-up-support/spec.md (FR-002..FR-006).
#
# Mirrors the style of scripts/validate-spec.sh.
#
# Usage:
#   validate-pitch.sh [--pitch-id ID | --all]
#   Default: --all

set -euo pipefail

# Locate the repo root containing specs/pitches/. Order:
#   1. $VALIDATE_PITCH_REPO (explicit override)
#   2. The script's parent's parent, if it contains specs/
#      (true when invoked from the canonical scripts/ location)
#   3. $PWD (works when the validator is installed to ~/.claude/templates/sdd/
#      and invoked from a consumer project's root)
SCRIPT_PARENT="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd || true)"
if [[ -n "${VALIDATE_PITCH_REPO:-}" ]]; then
  REPO_DIR="$VALIDATE_PITCH_REPO"
elif [[ -n "$SCRIPT_PARENT" && -d "$SCRIPT_PARENT/specs" ]]; then
  REPO_DIR="$SCRIPT_PARENT"
else
  REPO_DIR="$PWD"
fi
PITCHES_DIR="$REPO_DIR/specs/pitches"

# Allowed enum values. Keep in sync with pitch-template.md frontmatter.
VALID_APPETITES=("2w" "4w" "6w")
VALID_BET_STATUSES=("shaping" "shaped" "bet" "building" "shipped" "shelved")

# bet_status values that require cycle to be populated.
CYCLE_REQUIRED_STATUSES=("bet" "building" "shipped")

# bet_status values that require circuit_breaker to be populated.
# A pitch is allowed to have an empty circuit_breaker only while drafting.
CIRCUIT_BREAKER_REQUIRED_STATUSES=("shaped" "bet" "building" "shipped" "shelved")

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
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

contains() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [[ "$item" == "$needle" ]]; then
      return 0
    fi
  done
  return 1
}

pass() {
  echo "  [PASS] $1"
  TOTAL_PASS=$((TOTAL_PASS + 1))
}

fail() {
  echo "  [FAIL] $1"
  TOTAL_FAIL=$((TOTAL_FAIL + 1))
}

# ── Per-pitch validation ─────────────────────────────────────

validate_pitch_dir() {
  local pitch_dir="$1"
  local id
  id="$(basename "$pitch_dir")"
  local pitch="$pitch_dir/pitch.md"

  echo "--- $id ---"

  if [[ ! -f "$pitch" ]]; then
    fail "$id: pitch.md not found"
    return
  fi

  local pitch_id title appetite bet_status cycle circuit_breaker shaped_by shaped_date
  pitch_id="$(extract_frontmatter_field "$pitch" "pitch_id")"
  title="$(extract_frontmatter_field "$pitch" "title")"
  appetite="$(extract_frontmatter_field "$pitch" "appetite")"
  bet_status="$(extract_frontmatter_field "$pitch" "bet_status")"
  cycle="$(extract_frontmatter_field "$pitch" "cycle")"
  circuit_breaker="$(extract_frontmatter_field "$pitch" "circuit_breaker")"
  shaped_by="$(extract_frontmatter_field "$pitch" "shaped_by")"
  shaped_date="$(extract_frontmatter_field "$pitch" "shaped_date")"

  # Required fields (FR-002).
  if [[ -z "$pitch_id" ]]; then
    fail "$id: pitch_id missing from pitch.md frontmatter"
    return
  fi

  if [[ "$pitch_id" != "$id" ]]; then
    fail "$id: pitch_id '$pitch_id' does not match directory name '$id'"
    return
  fi

  if [[ -z "$title" ]]; then
    fail "$id: title missing from pitch.md frontmatter"
    return
  fi

  if [[ -z "$appetite" ]]; then
    fail "$id: appetite missing from pitch.md frontmatter"
    return
  fi

  if [[ -z "$bet_status" ]]; then
    fail "$id: bet_status missing from pitch.md frontmatter"
    return
  fi

  if [[ -z "$shaped_by" ]]; then
    fail "$id: shaped_by missing from pitch.md frontmatter"
    return
  fi

  if [[ -z "$shaped_date" ]]; then
    fail "$id: shaped_date missing from pitch.md frontmatter"
    return
  fi

  # Enum checks (FR-003, FR-004).
  if ! contains "$appetite" "${VALID_APPETITES[@]}"; then
    fail "$id: appetite '$appetite' is not valid (must be one of: ${VALID_APPETITES[*]})"
    return
  fi

  if ! contains "$bet_status" "${VALID_BET_STATUSES[@]}"; then
    fail "$id: bet_status '$bet_status' is not valid (must be one of: ${VALID_BET_STATUSES[*]})"
    return
  fi

  # Conditional checks (FR-005).
  if contains "$bet_status" "${CYCLE_REQUIRED_STATUSES[@]}"; then
    if [[ -z "$cycle" ]]; then
      fail "$id: cycle must be non-empty when bet_status='$bet_status'"
      return
    fi
  fi

  # Conditional checks (FR-006).
  if contains "$bet_status" "${CIRCUIT_BREAKER_REQUIRED_STATUSES[@]}"; then
    if [[ -z "$circuit_breaker" ]]; then
      fail "$id: circuit_breaker must be non-empty when bet_status='$bet_status'"
      return
    fi
  fi

  pass "$id: pitch.md frontmatter valid (appetite=$appetite, bet_status=$bet_status${cycle:+, cycle=$cycle})"
}

# ── CLI ──────────────────────────────────────────────────────

MODE="all"
PITCH_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pitch-id)
      MODE="single"
      PITCH_ID="${2:-}"
      if [[ -z "$PITCH_ID" ]]; then
        echo "Usage: validate-pitch.sh [--pitch-id ID | --all]"
        exit 1
      fi
      shift 2
      ;;
    --all)
      MODE="all"
      shift
      ;;
    -h|--help)
      echo "Usage: validate-pitch.sh [--pitch-id ID | --all]"
      exit 0
      ;;
    *)
      echo "Usage: validate-pitch.sh [--pitch-id ID | --all]"
      exit 1
      ;;
  esac
done

echo "=== Validating Shape-Up pitch conformance ==="
echo ""

if [[ ! -d "$PITCHES_DIR" ]]; then
  echo "No specs/pitches/ directory; nothing to validate."
  exit 0
fi

if [[ "$MODE" == "single" ]]; then
  if [[ ! -d "$PITCHES_DIR/$PITCH_ID" ]]; then
    echo "  [FAIL] specs/pitches/$PITCH_ID/ directory not found"
    exit 1
  fi
  validate_pitch_dir "$PITCHES_DIR/$PITCH_ID"
else
  found=0
  for dir in "$PITCHES_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    [[ -f "$dir/pitch.md" ]] || continue
    found=1
    validate_pitch_dir "$dir"
  done
  if [[ "$found" -eq 0 ]]; then
    echo "No pitch directories found in specs/pitches/"
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
