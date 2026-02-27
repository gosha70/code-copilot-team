#!/usr/bin/env bash
# apply-branch-protection.sh — Apply baseline GitHub branch protection settings.
#
# Requires:
#   - gh CLI authenticated with repo admin access
#   - GitHub repository admin permissions
#
# Usage:
#   bash scripts/apply-branch-protection.sh
#   bash scripts/apply-branch-protection.sh --repo gosha70/code-copilot-team
#   bash scripts/apply-branch-protection.sh --repo gosha70/code-copilot-team --branch master
#   bash scripts/apply-branch-protection.sh --checks "sync-check" --dry-run

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: apply-branch-protection.sh [options]

Options:
  --repo <owner/name>     Repository slug (default: current gh repo)
  --branch <name>         Branch to protect (default: repo default branch)
  --checks "<a,b,c>"      Required status checks (default: sync-check)
  --dry-run               Print payload without applying
  -h, --help              Show this help
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

REPO=""
BRANCH=""
CHECKS_CSV="sync-check"
DRY_RUN=false

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
    --checks)
      CHECKS_CSV="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
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
  echo "[ERROR] Could not resolve default branch for $REPO. Pass --branch <name>."
  exit 1
fi

IFS=',' read -r -a RAW_CHECKS <<< "$CHECKS_CSV"
CHECKS_JSON_ITEMS=()
for raw in "${RAW_CHECKS[@]}"; do
  check="$(trim "$raw")"
  if [[ -n "$check" ]]; then
    CHECKS_JSON_ITEMS+=("\"$check\"")
  fi
done

if [[ "${#CHECKS_JSON_ITEMS[@]}" -eq 0 ]]; then
  echo "[ERROR] At least one required status check must be provided via --checks."
  exit 1
fi

CHECKS_JSON="["
for i in "${!CHECKS_JSON_ITEMS[@]}"; do
  if [[ "$i" -gt 0 ]]; then
    CHECKS_JSON+=", "
  fi
  CHECKS_JSON+="${CHECKS_JSON_ITEMS[$i]}"
done
CHECKS_JSON+="]"

read -r -d '' PAYLOAD <<EOF || true
{
  "required_status_checks": {
    "strict": true,
    "contexts": $CHECKS_JSON
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": true
}
EOF

echo "=== Branch protection target ==="
echo "Repo:   $REPO"
echo "Branch: $BRANCH"
echo "Checks: $CHECKS_CSV"
echo ""

if $DRY_RUN; then
  echo "=== Dry run payload ==="
  echo "$PAYLOAD"
  exit 0
fi

echo "Applying branch protection..."
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/$REPO/branches/$BRANCH/protection" \
  --input - <<<"$PAYLOAD" >/dev/null

echo "Branch protection applied."
echo ""
echo "=== Verification snapshot ==="
gh api "/repos/$REPO/branches/$BRANCH/protection" --jq '{
  required_status_checks: .required_status_checks.contexts,
  strict_status_checks: .required_status_checks.strict,
  require_code_owner_reviews: .required_pull_request_reviews.require_code_owner_reviews,
  required_approving_review_count: .required_pull_request_reviews.required_approving_review_count,
  enforce_admins: .enforce_admins.enabled,
  required_linear_history: .required_linear_history.enabled,
  required_conversation_resolution: .required_conversation_resolution.enabled
}'
