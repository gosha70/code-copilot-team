#!/usr/bin/env bash

# test-github-hardening.sh — scripts/check-github-hardening.sh against a gh
# stub, so the audit's reading of both protection sources is pinned:
# classic branch protection, and a ruleset (the "rules for a branch" API),
# which is what this repository actually uses. The ruleset fixture is the
# master ruleset as GitHub returned it on 2026-11-08, so the expected
# PASS/FAIL lines are the audit's verdict on the real configuration.
#
# Run from the repo root:
#   bash tests/test-github-hardening.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK="$REPO_DIR/scripts/check-github-hardening.sh"
COUNTS_FILE="$SCRIPT_DIR/test-counts.env"
# shellcheck source=/dev/null
source "$COUNTS_FILE"
PASS=0
FAIL=0

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (expected '$expected', got '$actual')"; FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name (missing '$needle')"; FAIL=$((FAIL + 1))
  fi
}

STUB_DIR=$(mktemp -d)
trap 'rm -rf "$STUB_DIR"' EXIT

# The master ruleset's effective rules, as GET /repos/{o}/{r}/rules/branches/master
# returned them (two rulesets: PUSH RULE 14462450 with a bypass actor, and
# master-protection 19893594 without).
cat > "$STUB_DIR/rules.json" << 'JSON'
[
  {"type":"deletion","ruleset_id":14462450,"ruleset_source_type":"Repository","parameters":null},
  {"type":"non_fast_forward","ruleset_id":14462450,"ruleset_source_type":"Repository","parameters":null},
  {"type":"pull_request","ruleset_id":19893594,"ruleset_source_type":"Repository","parameters":{"required_approving_review_count":0,"dismiss_stale_reviews_on_push":false,"required_reviewers":[],"require_code_owner_review":false,"require_last_push_approval":false,"required_review_thread_resolution":false,"require_extra_approval_for_unattributed_changes":true,"allowed_merge_methods":["merge","squash","rebase"]}},
  {"type":"non_fast_forward","ruleset_id":19893594,"ruleset_source_type":"Repository","parameters":null},
  {"type":"deletion","ruleset_id":19893594,"ruleset_source_type":"Repository","parameters":null},
  {"type":"required_status_checks","ruleset_id":19893594,"ruleset_source_type":"Repository","parameters":{"strict_required_status_checks_policy":false,"do_not_enforce_on_create":false,"required_status_checks":[{"context":"pi-tests"},{"context":"sync-check"},{"context":"CodeQL"}]}}
]
JSON

cat > "$STUB_DIR/classic.json" << 'JSON'
{"required_status_checks":{"strict":true,"contexts":["sync-check","CodeQL"]},
 "required_pull_request_reviews":{"require_code_owner_reviews":true,"required_approving_review_count":1},
 "required_conversation_resolution":{"enabled":true},
 "required_linear_history":{"enabled":true},
 "enforce_admins":{"enabled":true},
 "allow_force_pushes":{"enabled":false},
 "allow_deletions":{"enabled":false}}
JSON

# gh stub: MODE=classic serves classic protection; MODE=ruleset answers 404
# there and serves the rules fixture; MODE=none has neither. `--jq` is
# honoured by piping the fixture through jq, as gh would.
cat > "$STUB_DIR/gh" << 'GH'
#!/usr/bin/env bash
FIX="${STUB_FIXTURES:?}"
MODE="${STUB_MODE:?}"
[[ "${1:-}" == "api" ]] || exit 0
path="$2"; shift 2
jqexpr=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jq) jqexpr="$2"; shift 2 ;;
    *) shift ;;
  esac
done
emit() { if [[ -n "$jqexpr" ]]; then jq -r "$jqexpr" <<<"$1"; else printf '%s\n' "$1"; fi; }
case "$path" in
  */branches/*/protection)
    [[ "$MODE" == "classic" ]] || { echo '{"message":"Branch not protected"}' >&2; exit 1; }
    emit "$(cat "$FIX/classic.json")" ;;
  */rules/branches/*)
    [[ "$MODE" == "ruleset" ]] && emit "$(cat "$FIX/rules.json")" || emit "[]" ;;
  */rulesets/14462450)
    emit '{"id":14462450,"name":"PUSH RULE","bypass_actors":[{"actor_id":5,"actor_type":"RepositoryRole","bypass_mode":"always"}]}' ;;
  */rulesets/19893594)
    emit '{"id":19893594,"name":"master-protection","bypass_actors":[]}' ;;
  /repos/*)
    emit '{"security_and_analysis":{"private_vulnerability_reporting":{"status":"enabled"}}}' ;;
  *) exit 1 ;;
esac
GH
chmod +x "$STUB_DIR/gh"

run_audit() {
  # run_audit <mode> [extra args] → RC, OUTPUT
  local mode="$1"; shift
  RC=0
  OUTPUT=$(PATH="$STUB_DIR:$PATH" STUB_FIXTURES="$STUB_DIR" STUB_MODE="$mode" \
    bash "$CHECK" --repo acme/widgets --branch master "$@" 2>&1) || RC=$?
}

echo "=== check-github-hardening: ruleset source ==="
run_audit ruleset --required-checks "sync-check,CodeQL"
assert_contains "the audit names the ruleset as the protection source" "$OUTPUT" "branch protection exists (source: ruleset)"
assert_contains "required check CodeQL is read from the ruleset" "$OUTPUT" "PASS: required check 'CodeQL' configured"
assert_contains "required check sync-check is read from the ruleset" "$OUTPUT" "PASS: required check 'sync-check' configured"
assert_contains "non_fast_forward reads as force pushes blocked" "$OUTPUT" "PASS: force pushes blocked"
assert_contains "deletion rule reads as deletions blocked" "$OUTPUT" "PASS: branch deletions blocked"
assert_contains "zero required approvals is reported, not hidden" "$OUTPUT" "FAIL: required approving review count >= 1"
assert_contains "no linear-history rule is reported" "$OUTPUT" "FAIL: linear history required"
assert_contains "a bypass actor on a contributing ruleset is reported" "$OUTPUT" "FAIL: admins are subject to protections"
assert_contains "...naming the ruleset that grants the bypass" "$OUTPUT" "ruleset 14462450 (PUSH RULE) has 1 bypass actor"
assert_eq "the ruleset audit exits 1 on its failures" 1 "$RC"

echo "=== check-github-hardening: classic source ==="
run_audit classic --required-checks "sync-check,CodeQL"
assert_contains "classic protection is still read" "$OUTPUT" "branch protection exists (source: classic)"
assert_eq "a fully hardened classic branch passes" 0 "$RC"

echo "=== check-github-hardening: no protection ==="
run_audit none
assert_contains "neither source → the audit says so" "$OUTPUT" "no classic protection and no ruleset applies"
assert_eq "...and exits 1" 1 "$RC"

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "$TEST_GITHUB_HARDENING_EXPECTED_PASS" ]]; then
  echo "  FAIL: assertion-count drift (expected $TEST_GITHUB_HARDENING_EXPECTED_PASS, got $PASS)"
  FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
