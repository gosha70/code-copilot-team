#!/usr/bin/env bash
# check-github-hardening.sh — Verify baseline GitHub repository hardening.
#
# Checks:
#   - Branch protection exists on target branch
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
#   bash scripts/check-github-hardening.sh --repo gosha70/code-copilot-team --branch master
#   bash scripts/check-github-hardening.sh --required-check sync-check

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: check-github-hardening.sh [options]

Options:
  --repo <owner/name>        Repository slug (default: current gh repo)
  --branch <name>            Branch to inspect (default: repo default branch)
  --required-check <name>    Required CI check context (default: sync-check)
  -h, --help                 Show this help
EOF
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
REQUIRED_CHECK="sync-check"

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
      REQUIRED_CHECK="${2:-}"
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

echo "=== GitHub hardening check ==="
echo "Repo:   $REPO"
echo "Branch: $BRANCH"
echo "Check:  $REQUIRED_CHECK"
echo ""

if gh api "/repos/$REPO/branches/$BRANCH/protection" >/dev/null 2>&1; then
  pass_check "branch protection exists"
else
  fail_check "branch protection exists"
  echo ""
  echo "========================================="
  printf "  Results: %d passed, %d failed\n" "$pass" "$fail"
  echo "========================================="
  exit 1
fi

strict_checks="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_status_checks.strict')"
checks_csv="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_status_checks.contexts | join(",")')"
has_required_check="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq ".required_status_checks.contexts | index(\"$REQUIRED_CHECK\") != null")"
require_code_owner_reviews="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_pull_request_reviews.require_code_owner_reviews')"
required_approvals="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_pull_request_reviews.required_approving_review_count')"
require_conversation_resolution="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_conversation_resolution.enabled')"
require_linear_history="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.required_linear_history.enabled')"
enforce_admins="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.enforce_admins.enabled')"
allow_force_pushes="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.allow_force_pushes.enabled')"
allow_deletions="$(gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '.allow_deletions.enabled')"

assert_true "strict status checks enabled" "$strict_checks"
assert_true "required check '$REQUIRED_CHECK' configured" "$has_required_check"
assert_true "code owner reviews required" "$require_code_owner_reviews"
assert_ge "required approving review count >= 1" "$required_approvals" 1
assert_true "conversation resolution required" "$require_conversation_resolution"
assert_true "linear history required" "$require_linear_history"
assert_true "admins are subject to protections" "$enforce_admins"
assert_false "force pushes blocked" "$allow_force_pushes"
assert_false "branch deletions blocked" "$allow_deletions"

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

