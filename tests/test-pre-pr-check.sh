#!/usr/bin/env bash

# test-pre-pr-check.sh — scripts/pre-pr-check.sh, the close-keyword audit a
# hand-opened PR runs before `gh pr create` (#408).
#
# The script scans the branch's commit messages, the body file and the
# title for GitHub's nine close-keyword forms and compares every match
# with --closes; `--closes none` declares a PR that closes nothing. These
# assertions drive it against a throwaway repository, so no real branch
# is read.
#
# Run from the repo root:
#   bash tests/test-pre-pr-check.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK="$REPO_DIR/scripts/pre-pr-check.sh"
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

# A repository with a master branch and a feature branch one commit on.
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
GIT=(git -C "$WORK" -c user.name=t -c user.email=t@example.com)
"${GIT[@]}" init -q
"${GIT[@]}" checkout -q -b master
"${GIT[@]}" commit -q --allow-empty -m "root"
"${GIT[@]}" checkout -q -b feature/x
"${GIT[@]}" commit -q --allow-empty -m "docs: tighten the audit wording"

run_check() {
  # run_check <closes> <title> <body text> → RC, OUTPUT (stdout + stderr)
  local body="$WORK/body.md"
  printf '%s\n' "$3" > "$body"
  RC=0
  OUTPUT=$(cd "$WORK" && bash "$CHECK" --closes "$1" --title "$2" --body-file "$body" --base master 2>&1) || RC=$?
}

echo "=== pre-pr-check: --closes <N> ==="
run_check 5 "feat(x): the thing (Closes #5)" "Closes #5."
assert_eq "an intended close passes" 0 "$RC"
run_check 5 "feat(x): the thing" "Closes #5."
assert_eq "a title without its marker still fails when the PR closes an issue" 1 "$RC"
run_check "5,abc" "t" "b"
assert_eq "a non-integer --closes is a usage error (exit 2)" 2 "$RC"

echo "=== pre-pr-check: --closes none ==="
run_check none "docs(rules): close-keyword audit for hand-opened PRs" "Adds the audit step to the skill. Leaves #10 open."
assert_eq "a PR that closes nothing passes with --closes none" 0 "$RC"
assert_contains "...and is handed the gh pr create command" "$OUTPUT" "gh pr create"
assert_contains "...with the title accepted without a close marker" "$OUTPUT" "title carries no close marker"

run_check none "docs(rules): audit" "Also Closes #5 by restatement."
assert_eq "a body keyword fails under --closes none" 1 "$RC"
assert_contains "...naming the body match" "$OUTPUT" "[FAIL] body: #5 NOT in --closes (none)"

run_check none "docs(rules): audit (Closes #5)" "Clean body."
assert_eq "a title marker fails under --closes none" 1 "$RC"

"${GIT[@]}" commit -q --allow-empty -m "note: the earlier slice closed #7 by accident"
run_check none "docs(rules): audit" "Clean body."
assert_eq "a past-tense keyword in a commit message fails under --closes none" 1 "$RC"
assert_contains "...naming the commit" "$OUTPUT" "[FAIL] commit"

echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ "$PASS" -ne "$TEST_PRE_PR_CHECK_EXPECTED_PASS" ]]; then
  echo "  FAIL: assertion-count drift (expected $TEST_PRE_PR_CHECK_EXPECTED_PASS, got $PASS)"
  FAIL=$((FAIL + 1))
fi

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
