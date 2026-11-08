#!/usr/bin/env bash
# check-github-hardening.sh — Verify baseline GitHub repository hardening.
#
# Reads whichever protection source the branch has: classic branch
# protection, or the rulesets that apply to it (GET /rules/branches/<b>).
# This repository protects master with a ruleset, and the classic-only
# version of this audit reported "no branch protection" against it.
#
# Checks:
#   - Branch protection exists on target branch (classic or ruleset)
#   - Required status checks include the expected CI check
#   - Code owner review is required
#   - At least one approving review is required
#   - Conversation resolution is required
#   - Linear history is required
#   - Force pushes/deletions are blocked
#   - Private vulnerability reporting is enabled
#
# Requires:
#   - gh CLI authenticated
#   - Repository read access (admin access gives more complete results)
#
# Usage:
#   bash scripts/check-github-hardening.sh
#   bash scripts/check-github-hardening.sh --repo gosha70/code-copilot-team
#   bash scripts/check-github-hardening.sh --repo gosha70/code-copilot-team --branch <name>  # override default-branch detection
#   bash scripts/check-github-hardening.sh --required-checks "sync-check"

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: check-github-hardening.sh [options]

Options:
  --repo <owner/name>        Repository slug (default: current gh repo)
  --branch <name>            Branch to inspect (default: repo default branch)
  --required-check <name>    Required CI check context (single-value alias)
  --required-checks "<a,b>"  Required CI check contexts (default: sync-check)
  -h, --help                 Show this help
EOF
}

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  s="${s%"${s##*[![:space:]]}"}"
  printf '%s' "$s"
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[ERROR] Missing required command: $cmd"
    exit 1
  fi
}

pass=0
fail=0

pass_check() {
  echo "  PASS: $1"
  pass=$((pass + 1))
}

fail_check() {
  echo "  FAIL: $1"
  fail=$((fail + 1))
}

assert_true() {
  local name="$1"
  local value="$2"
  if [[ "$value" == "true" ]]; then
    pass_check "$name"
  else
    fail_check "$name (got: $value)"
  fi
}

assert_false() {
  local name="$1"
  local value="$2"
  if [[ "$value" == "false" ]]; then
    pass_check "$name"
  else
    fail_check "$name (got: $value)"
  fi
}

assert_ge() {
  local name="$1"
  local value="$2"
  local expected="$3"
  if [[ "$value" =~ ^[0-9]+$ ]] && (( value >= expected )); then
    pass_check "$name"
  else
    fail_check "$name (expected >= $expected, got: $value)"
  fi
}

REPO=""
BRANCH=""
REQUIRED_CHECKS_CSV="sync-check"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --branch)
      BRANCH="${2:-}"
      shift 2
      ;;
    --required-check)
      REQUIRED_CHECKS_CSV="${2:-}"
      shift 2
      ;;
    --required-checks)
      REQUIRED_CHECKS_CSV="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

require_cmd gh
require_cmd jq

if [[ -z "$REPO" ]]; then
  REPO="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
fi

if [[ -z "$REPO" ]]; then
  echo "[ERROR] Could not resolve repository. Pass --repo <owner/name>."
  exit 1
fi

if [[ -z "$BRANCH" ]]; then
  BRANCH="$(gh repo view "$REPO" --json defaultBranchRef --jq '.defaultBranchRef.name')"
fi

if [[ -z "$BRANCH" ]]; then
  echo "[ERROR] Could not resolve target branch. Pass --branch <name>."
  exit 1
fi

IFS=',' read -r -a REQUIRED_CHECKS_RAW <<< "$REQUIRED_CHECKS_CSV"
REQUIRED_CHECKS=()
for raw in "${REQUIRED_CHECKS_RAW[@]}"; do
  c="$(trim "$raw")"
  if [[ -n "$c" ]]; then
    REQUIRED_CHECKS+=("$c")
  fi
done

if [[ "${#REQUIRED_CHECKS[@]}" -eq 0 ]]; then
  echo "[ERROR] At least one required check must be supplied."
  exit 1
fi

echo "=== GitHub hardening check ==="
echo "Repo:   $REPO"
echo "Branch: $BRANCH"
echo "Checks: $REQUIRED_CHECKS_CSV"
echo ""

# Protection source: classic branch protection first; else the rules that
# apply to the branch through rulesets. A branch can have both; classic
# is read when present because it is the stricter, older contract.
SOURCE=""
RULES_JSON="[]"
if gh api "/repos/$REPO/branches/$BRANCH/protection" >/dev/null 2>&1; then
  SOURCE="classic"
else
  RULES_JSON="$(gh api "/repos/$REPO/rules/branches/$BRANCH" 2>/dev/null || echo '[]')"
  if [[ "$(jq 'length' <<<"$RULES_JSON" 2>/dev/null || echo 0)" -gt 0 ]]; then
    SOURCE="ruleset"
  fi
fi

if [[ -z "$SOURCE" ]]; then
  fail_check "branch protection exists (no classic protection and no ruleset applies to '$BRANCH')"
  echo ""
  echo "========================================="
  printf "  Results: %d passed, %d failed\n" "$pass" "$fail"
  echo "========================================="
  exit 1
fi
pass_check "branch protection exists (source: $SOURCE)"

if [[ "$SOURCE" == "classic" ]]; then
  strict_checks="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_status_checks.strict')"
  checks_csv="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_status_checks.contexts | join(",")')"
  require_code_owner_reviews="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_pull_request_reviews.require_code_owner_reviews')"
  required_approvals="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_pull_request_reviews.required_approving_review_count')"
  require_conversation_resolution="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_conversation_resolution.enabled')"
  require_linear_history="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_linear_history.enabled')"
  enforce_admins="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.enforce_admins.enabled')"
  allow_force_pushes="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.allow_force_pushes.enabled')"
  allow_deletions="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.allow_deletions.enabled')"
else
  # Ruleset rules: one object per rule type. The pull_request and
  # required_status_checks rules carry parameters; non_fast_forward,
  # deletion and required_linear_history are present-or-absent.
  pr_rule="$(jq -c '[.[] | select(.type == "pull_request")][0] // {}' <<<"$RULES_JSON")"
  sc_rule="$(jq -c '[.[] | select(.type == "required_status_checks")][0] // {}' <<<"$RULES_JSON")"
  strict_checks="$(jq -r '.parameters.strict_required_status_checks_policy // false' <<<"$sc_rule")"
  checks_csv="$(jq -r '[.parameters.required_status_checks[]?.context] | join(",")' <<<"$sc_rule")"
  require_code_owner_reviews="$(jq -r '.parameters.require_code_owner_review // false' <<<"$pr_rule")"
  required_approvals="$(jq -r '.parameters.required_approving_review_count // 0' <<<"$pr_rule")"
  require_conversation_resolution="$(jq -r '.parameters.required_review_thread_resolution // false' <<<"$pr_rule")"
  require_linear_history="$(jq -r 'any(.[]; .type == "required_linear_history")' <<<"$RULES_JSON")"
  allow_force_pushes="$(jq -r 'any(.[]; .type == "non_fast_forward") | not' <<<"$RULES_JSON")"
  allow_deletions="$(jq -r 'any(.[]; .type == "deletion") | not' <<<"$RULES_JSON")"
  # "Admins are subject": no ruleset that contributes a rule to this
  # branch grants a bypass. Each is named so the owner can see which.
  enforce_admins="true"
  for ruleset_id in $(jq -r '[.[].ruleset_id] | unique | .[]' <<<"$RULES_JSON"); do
    bypass_count="$(gh api "/repos/$REPO/rulesets/$ruleset_id" --jq '.bypass_actors | length' 2>/dev/null || echo "?")"
    ruleset_name="$(gh api "/repos/$REPO/rulesets/$ruleset_id" --jq '.name' 2>/dev/null || echo "?")"
    if [[ "$bypass_count" != "0" ]]; then
      enforce_admins="false"
      echo "  INFO: ruleset $ruleset_id ($ruleset_name) has $bypass_count bypass actor(s)"
    fi
  done
fi

assert_true "strict status checks enabled" "$strict_checks"
assert_true "code owner reviews required" "$require_code_owner_reviews"
assert_ge "required approving review count >= 1" "$required_approvals" 1
assert_true "conversation resolution required" "$require_conversation_resolution"
assert_true "linear history required" "$require_linear_history"
assert_true "admins are subject to protections" "$enforce_admins"
assert_false "force pushes blocked" "$allow_force_pushes"
assert_false "branch deletions blocked" "$allow_deletions"

for required_check in "${REQUIRED_CHECKS[@]}"; do
  has_required_check="$(jq -rn --arg csv "$checks_csv" --arg c "$required_check" '$csv | split(",") | index($c) != null')"
  assert_true "required check '$required_check' configured" "$has_required_check"
done

echo "  INFO: required status checks = ${checks_csv:-<none>}"

pvr_status="$(gh api "/repos/$REPO" --jq '.security_and_analysis.private_vulnerability_reporting.status // ""' 2>/dev/null || true)"
if [[ "$pvr_status" == "enabled" ]]; then
  pass_check "private vulnerability reporting enabled"
elif [[ -z "$pvr_status" ]]; then
  fail_check "private vulnerability reporting status visible"
else
  fail_check "private vulnerability reporting enabled (got: $pvr_status)"
fi

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$pass" "$fail"
echo "========================================="

if [[ "$fail" -gt 0 ]]; then
  exit 1
fi
