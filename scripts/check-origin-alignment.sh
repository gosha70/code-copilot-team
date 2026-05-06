#!/usr/bin/env bash
# check-origin-alignment.sh — verify a feature's origin-alignment gate.
#
# Reads:    specs/<feature-id>/plan.md frontmatter for the origin: block
# Reads:    specs/<feature-id>/origin-alignment-*.md for the latest verdict
#
# Exit codes:
#   0 — aligned, high (proceed clean)
#   1 — aligned, medium/low (proceed with warning)
#       OR partial/derailed with a fresh committed origin-divergence.md
#       (the user has documented the deviation deliberately — option C
#       from the skill body's three-resolution escalation)
#   2 — partial (escalate to user)
#   3 — derailed (escalate to user)
#   4 — missing or stale alignment record
#   5 — origin frontmatter missing or malformed
#
# When exit ≥ 2, the caller (slash command, agent, /phase-complete) must
# surface the three-resolution escalation prompt to the user. See
# shared/skills/origin-confirmation/SKILL.md for the contract.
#
# Bash 3.2 compatible (works with macOS default bash).
#
# Usage: check-origin-alignment.sh <feature-id>

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# CCT_SPECS_DIR overrides the default specs/ root (used by the test
# harness to point at isolated fixture trees). Defaults to $REPO_DIR/specs.
SPECS_DIR="${CCT_SPECS_DIR:-$REPO_DIR/specs}"

usage() {
  cat <<'USAGE'
Usage: check-origin-alignment.sh <feature-id>

Validates that the feature's plan.md carries an origin: block and that
the latest origin-alignment-*.md record is fresh and indicates an
acceptable verdict.

Exit codes:
  0 — aligned, high (proceed clean)
  1 — aligned, medium/low (proceed with warning) — also returned when
      a fresh origin-divergence.md is present (option C, deliberate
      divergence acknowledged by the user)
  2 — partial (escalate to user)
  3 — derailed (escalate to user)
  4 — missing or stale alignment record
  5 — origin frontmatter missing or malformed

When exit ≥ 2, the caller must surface the three-resolution escalation
prompt to the user (rescope / restart / document-divergence). See
shared/skills/origin-confirmation/SKILL.md for the full contract.
USAGE
}

if [[ $# -eq 0 ]]; then
  usage
  exit 5
fi

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

FEATURE_ID="$1"

# Resolve the spec directory.
if [[ -d "$SPECS_DIR/$FEATURE_ID" ]]; then
  SPEC_DIR="$SPECS_DIR/$FEATURE_ID"
elif [[ -d "$SPECS_DIR/pitches/$FEATURE_ID" ]]; then
  SPEC_DIR="$SPECS_DIR/pitches/$FEATURE_ID"
else
  echo "  ✗ specs/$FEATURE_ID/ or specs/pitches/$FEATURE_ID/ not found" >&2
  exit 5
fi

PLAN="$SPEC_DIR/plan.md"
SPEC="$SPEC_DIR/spec.md"

if [[ ! -f "$PLAN" ]]; then
  echo "  ✗ $FEATURE_ID: plan.md not found at $PLAN" >&2
  exit 5
fi

# ── Frontmatter helpers ──────────────────────────────────────

# Print frontmatter body (between the first two --- lines).
extract_frontmatter() {
  awk 'BEGIN{n=0} /^---[[:space:]]*$/{n++; if(n==1){infm=1; next} if(n==2){exit}} infm{print}' "$1"
}

# Print the body of a top-level YAML block (keys nested under a top-level key).
# Continues until the next non-indented top-level key or EOF.
fm_block_body() {
  local file="$1" key="$2"
  extract_frontmatter "$file" | awk -v k="$key" '
    !inblock && $0 ~ "^"k":[[:space:]]*$" { inblock=1; next }
    inblock && /^[A-Za-z_]/ { exit }
    inblock { print }
  '
}

# Print a top-level scalar field value (e.g., "feature_id: foo").
fm_top_field() {
  local file="$1" key="$2"
  extract_frontmatter "$file" | awk -v k="$key" '
    $0 ~ "^"k":[[:space:]]+[^[:space:]]" {
      sub("^"k":[[:space:]]*", "")
      gsub(/^"|"$/, "")
      gsub(/^\047|\047$/, "")
      print
      exit
    }
  '
}

# Print a sub-field value from inside a top-level block.
# Example: fm_sub_field plan.md origin issue
fm_sub_field() {
  local file="$1" parent="$2" key="$3"
  fm_block_body "$file" "$parent" | awk -v k="$key" '
    $0 ~ "^[[:space:]]+"k":[[:space:]]+[^[:space:]]" {
      sub("^[[:space:]]+"k":[[:space:]]*", "")
      gsub(/^"|"$/, "")
      gsub(/^\047|\047$/, "")
      print
      exit
    }
  '
}

# True (exit 0) if a sub-list under a top-level block has at least one entry.
fm_sub_list_nonempty() {
  local file="$1" parent="$2" key="$3"
  fm_block_body "$file" "$parent" | awk -v k="$key" '
    $0 ~ "^[[:space:]]+"k":[[:space:]]*$" { in_list=1; next }
    in_list && $0 ~ "^[[:space:]]+-[[:space:]]+" { found=1; exit }
    in_list && $0 ~ "^[[:space:]]+[A-Za-z_]" && !($0 ~ "^[[:space:]]+-") { in_list=0 }
    END { exit found ? 0 : 1 }
  '
}

# Cross-platform mtime in epoch seconds.
file_mtime() {
  if stat -f '%m' "$1" >/dev/null 2>&1; then
    stat -f '%m' "$1"
  else
    stat -c '%Y' "$1"
  fi
}

# ── Validate origin block ────────────────────────────────────

ORIGIN_BODY="$(fm_block_body "$PLAN" "origin")"

if [[ -z "$ORIGIN_BODY" ]]; then
  # Try inline form: origin: { type: internal, reason: "..." }
  ORIGIN_INLINE="$(fm_top_field "$PLAN" "origin")"
  if [[ -z "$ORIGIN_INLINE" ]]; then
    echo "  ✗ $FEATURE_ID: origin: missing from plan.md frontmatter" >&2
    exit 5
  fi
  case "$ORIGIN_INLINE" in
    *"type: internal"*|*"type:internal"*)
      echo "  ✓ $FEATURE_ID: origin: { type: internal } — gate passes by exemption"
      exit 0
      ;;
    *"type: unrecoverable"*|*"type:unrecoverable"*)
      echo "  ✗ $FEATURE_ID: origin: { type: unrecoverable } — origin not recoverable" >&2
      exit 5
      ;;
    *)
      echo "  ✗ $FEATURE_ID: origin: '$ORIGIN_INLINE' is not a recognized inline form" >&2
      exit 5
      ;;
  esac
fi

ORIGIN_TYPE="$(fm_sub_field "$PLAN" "origin" "type")"
if [[ "$ORIGIN_TYPE" == "internal" ]]; then
  REASON="$(fm_sub_field "$PLAN" "origin" "reason")"
  if [[ -z "$REASON" ]]; then
    echo "  ✗ $FEATURE_ID: origin: { type: internal } requires a reason field" >&2
    exit 5
  fi
  echo "  ✓ $FEATURE_ID: origin: { type: internal, reason: \"$REASON\" } — gate passes by exemption"
  exit 0
fi
if [[ "$ORIGIN_TYPE" == "unrecoverable" ]]; then
  NOTE="$(fm_sub_field "$PLAN" "origin" "note")"
  echo "  ✗ $FEATURE_ID: origin: { type: unrecoverable, note: \"$NOTE\" } — origin not recoverable" >&2
  exit 5
fi

# Must have at least one identifier: issue | urls | transcripts.
ORIGIN_ISSUE="$(fm_sub_field "$PLAN" "origin" "issue")"
HAS_URLS=0
HAS_TRANSCRIPTS=0
fm_sub_list_nonempty "$PLAN" "origin" "urls" && HAS_URLS=1
fm_sub_list_nonempty "$PLAN" "origin" "transcripts" && HAS_TRANSCRIPTS=1

if [[ -z "$ORIGIN_ISSUE" && "$HAS_URLS" -eq 0 && "$HAS_TRANSCRIPTS" -eq 0 ]]; then
  echo "  ✗ $FEATURE_ID: origin: must include at least one of issue, urls, transcripts" >&2
  exit 5
fi

# ── Find latest alignment record ─────────────────────────────
# Format: origin-alignment-YYYY-MM-DD-HHMM.md (lexicographic = chronological).

LATEST_RECORD=""
for f in "$SPEC_DIR"/origin-alignment-*.md; do
  [[ -f "$f" ]] || continue
  if [[ -z "$LATEST_RECORD" ]] || [[ "$f" > "$LATEST_RECORD" ]]; then
    LATEST_RECORD="$f"
  fi
done

if [[ -z "$LATEST_RECORD" ]]; then
  echo "  ✗ $FEATURE_ID: no origin-alignment-*.md record found in $SPEC_DIR" >&2
  echo "    Run /origin-check $FEATURE_ID to produce a fresh record." >&2
  exit 4
fi

# Staleness check: alignment record must be newer than plan.md (and spec.md if present).
REC_MTIME="$(file_mtime "$LATEST_RECORD" 2>/dev/null || echo 0)"
PLAN_MTIME="$(file_mtime "$PLAN" 2>/dev/null || echo 0)"
if [[ -n "$REC_MTIME" && -n "$PLAN_MTIME" && "$REC_MTIME" -lt "$PLAN_MTIME" ]]; then
  echo "  ✗ $FEATURE_ID: alignment record older than plan.md (stale)" >&2
  echo "    record: ${LATEST_RECORD#$REPO_DIR/}" >&2
  exit 4
fi
if [[ -f "$SPEC" ]]; then
  SPEC_MTIME="$(file_mtime "$SPEC" 2>/dev/null || echo 0)"
  if [[ -n "$REC_MTIME" && -n "$SPEC_MTIME" && "$REC_MTIME" -lt "$SPEC_MTIME" ]]; then
    echo "  ✗ $FEATURE_ID: alignment record older than spec.md (stale)" >&2
    echo "    record: ${LATEST_RECORD#$REPO_DIR/}" >&2
    exit 4
  fi
fi

# ── Parse verdict ────────────────────────────────────────────

VERDICT_RAW="$(grep -E '^Verdict:[[:space:]]*' "$LATEST_RECORD" | head -1 | sed 's/^Verdict:[[:space:]]*//')"
CONFIDENCE_RAW="$(grep -E '^Confidence:[[:space:]]*' "$LATEST_RECORD" | head -1 | sed 's/^Confidence:[[:space:]]*//')"

# Lowercase + strip trailing whitespace and any trailing punctuation.
VERDICT="$(printf '%s' "$VERDICT_RAW" | tr '[:upper:]' '[:lower:]' | awk '{print $1}' | tr -d ',.;')"
CONFIDENCE="$(printf '%s' "$CONFIDENCE_RAW" | tr '[:upper:]' '[:lower:]' | awk '{print $1}' | tr -d ',.;')"

if [[ -z "$VERDICT" ]]; then
  echo "  ✗ $FEATURE_ID: no 'Verdict:' line in ${LATEST_RECORD#$REPO_DIR/}" >&2
  exit 4
fi

# A committed origin-divergence.md (resolution C from the skill body)
# unblocks a partial/derailed verdict if it is at least as new as the
# alignment record. The user has acknowledged the deviation in writing
# and committed it; the gate downgrades to "proceed with warning" so
# reviewers see both the deviation and the user's deliberate choice.
DIVERGENCE_FILE="$SPEC_DIR/origin-divergence.md"
HAS_FRESH_DIVERGENCE=0
if [[ -f "$DIVERGENCE_FILE" ]]; then
  DIV_MTIME="$(file_mtime "$DIVERGENCE_FILE" 2>/dev/null || echo 0)"
  if [[ -n "$DIV_MTIME" && -n "$REC_MTIME" && "$DIV_MTIME" -ge "$REC_MTIME" ]]; then
    HAS_FRESH_DIVERGENCE=1
  fi
fi

case "$VERDICT" in
  aligned)
    case "$CONFIDENCE" in
      high)
        echo "  ✓ $FEATURE_ID: aligned, high — gate passes (record: ${LATEST_RECORD#$REPO_DIR/})"
        exit 0
        ;;
      medium|low)
        echo "  ⚠ $FEATURE_ID: aligned, $CONFIDENCE — gate passes with warning (record: ${LATEST_RECORD#$REPO_DIR/})"
        exit 1
        ;;
      *)
        echo "  ⚠ $FEATURE_ID: aligned, confidence missing — treating as low (record: ${LATEST_RECORD#$REPO_DIR/})"
        exit 1
        ;;
    esac
    ;;
  partial)
    if [[ "$HAS_FRESH_DIVERGENCE" -eq 1 ]]; then
      echo "  ⚠ $FEATURE_ID: partial — gate passes with documented divergence" >&2
      echo "    record:     ${LATEST_RECORD#$REPO_DIR/}" >&2
      echo "    divergence: ${DIVERGENCE_FILE#$REPO_DIR/}" >&2
      exit 1
    fi
    echo "  ✗ $FEATURE_ID: partial alignment — escalate to user (record: ${LATEST_RECORD#$REPO_DIR/})" >&2
    echo "    Resolutions: A) rescope spec  B) restart from origin  C) document divergence" >&2
    exit 2
    ;;
  derailed)
    if [[ "$HAS_FRESH_DIVERGENCE" -eq 1 ]]; then
      echo "  ⚠ $FEATURE_ID: derailed — gate passes with documented divergence" >&2
      echo "    record:     ${LATEST_RECORD#$REPO_DIR/}" >&2
      echo "    divergence: ${DIVERGENCE_FILE#$REPO_DIR/}" >&2
      exit 1
    fi
    echo "  ✗ $FEATURE_ID: derailed — escalate to user (record: ${LATEST_RECORD#$REPO_DIR/})" >&2
    echo "    Resolutions: A) rescope spec  B) restart from origin  C) document divergence" >&2
    exit 3
    ;;
  *)
    echo "  ✗ $FEATURE_ID: unknown verdict '$VERDICT' in ${LATEST_RECORD#$REPO_DIR/}" >&2
    exit 4
    ;;
esac
