#!/usr/bin/env bash
# harden-github.sh — Apply and verify GitHub branch/review hardening in one command.
#
# Usage:
#   bash scripts/harden-github.sh
#   bash scripts/harden-github.sh --repo gosha70/code-copilot-team --branch master
#   bash scripts/harden-github.sh --checks "sync-check" --dry-run
#   bash scripts/harden-github.sh --no-apply --checks "sync-check"

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: harden-github.sh [options]

Options:
  --repo <owner/name>     Repository slug (default: current gh repo)
  --branch <name>         Branch to protect/audit (default: repo default branch)
  --checks "<a,b,c>"      Required status checks (default: sync-check)
  --dry-run               Show apply payload and run no mutating API call
  --no-apply              Skip apply; run audit only
  -h, --help              Show this help
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APPLY_SCRIPT="$SCRIPT_DIR/apply-branch-protection.sh"
CHECK_SCRIPT="$SCRIPT_DIR/check-github-hardening.sh"

if [[ ! -x "$APPLY_SCRIPT" ]]; then
  echo "[ERROR] Missing executable: $APPLY_SCRIPT"
  exit 1
fi

if [[ ! -x "$CHECK_SCRIPT" ]]; then
  echo "[ERROR] Missing executable: $CHECK_SCRIPT"
  exit 1
fi

REPO=""
BRANCH=""
CHECKS_CSV="sync-check"
DRY_RUN=false
NO_APPLY=false

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
    --no-apply)
      NO_APPLY=true
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

COMMON_ARGS=()
if [[ -n "$REPO" ]]; then
  COMMON_ARGS+=(--repo "$REPO")
fi
if [[ -n "$BRANCH" ]]; then
  COMMON_ARGS+=(--branch "$BRANCH")
fi

if $DRY_RUN; then
  echo "=== Dry run: apply payload ==="
  bash "$APPLY_SCRIPT" "${COMMON_ARGS[@]}" --checks "$CHECKS_CSV" --dry-run
  echo ""
  echo "Dry run completed. No remote settings were changed."
  exit 0
fi

if ! $NO_APPLY; then
  echo "=== Apply hardening ==="
  bash "$APPLY_SCRIPT" "${COMMON_ARGS[@]}" --checks "$CHECKS_CSV"
  echo ""
fi

echo "=== Audit hardening ==="
bash "$CHECK_SCRIPT" "${COMMON_ARGS[@]}" --required-checks "$CHECKS_CSV"

