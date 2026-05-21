#!/usr/bin/env bash
# pre-pr-check.sh — gate three recurring PR-mechanics failures before
# the PR is opened or pushed.
#
# Consolidates the lessons from three real incidents:
#
#   1. Stray close-keywords in commit messages or PR body fire on merge.
#      GitHub reads syntax, not intent — "the future PR will say
#      Closes #34" in plain text IS a close-keyword to the parser.
#      PR #53 (2026-05-20) closed epic #34 in error this way.
#      Memory: feedback_close_keyword_audit_pre_pr.
#
#   2. PR title set via a follow-up edit (PR #41 last session) opens
#      the PR with the auto-generated branch-name title, and the
#      recovery edit can fail silently. Title must be set inline at
#      `gh pr create` time.
#
#   3. --body-file path not visible to gh because of sandbox/host
#      filesystem split (also PR #41). Body file existence must be
#      verified in the same shell that will run `gh`, immediately
#      before invocation.
#
# This script does NOT call `gh` itself. It runs the audits, prints
# the exact `gh pr create` command the caller should run next (with
# the verified arguments), and exits 0 only if every check passed.
#
# Exit codes:
#   0 — all checks pass; print the proposed gh pr create command
#   1 — one or more checks failed (diagnostics printed to stderr)
#   2 — usage error
#
# Bash 3.2 compatible (works with macOS default bash).
#
# Usage:
#   scripts/pre-pr-check.sh \
#       --closes <N>[,<N>...] \
#       --title <PR title> \
#       --body-file <path> \
#       [--base <branch>]
#
# Defaults: --base master.
#
# Examples:
#   # Sub-issue B (closes #49 only):
#   scripts/pre-pr-check.sh --closes 49 \
#       --title "feat(benchmark): calibration validation (Closes #49)" \
#       --body-file /tmp/pr-body-b.md
#
#   # Sub-issue E (closes #52 AND the #34 epic — both intentional):
#   scripts/pre-pr-check.sh --closes 52,34 \
#       --title "chore(benchmark): first labeled calibration set (Closes #52)" \
#       --body-file /tmp/pr-body-e.md

set -uo pipefail

CLOSES=""
TITLE=""
BODY_FILE=""
BASE="master"

usage() {
  sed -n '/^# Usage:/,/^# Examples:/p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --closes) CLOSES="$2"; shift 2 ;;
    --title)  TITLE="$2";  shift 2 ;;
    --body-file) BODY_FILE="$2"; shift 2 ;;
    --base)   BASE="$2";   shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "pre-pr-check: unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$CLOSES" || -z "$TITLE" || -z "$BODY_FILE" ]]; then
  echo "pre-pr-check: --closes, --title, and --body-file are required" >&2
  usage >&2
  exit 2
fi

# Normalize --closes into a list (whitespace + comma tolerant).
# Each entry must be a positive integer (no `#` prefix).
EXPECTED_IDS=()
IFS=',' read -ra _RAW <<< "$CLOSES"
for raw in "${_RAW[@]}"; do
  trimmed="$(echo "$raw" | tr -d ' #')"
  if ! [[ "$trimmed" =~ ^[0-9]+$ ]]; then
    echo "pre-pr-check: --closes value must be integer(s); got '$raw'" >&2
    exit 2
  fi
  EXPECTED_IDS+=("$trimmed")
done

# Helper: is an ID in the expected list?
id_expected() {
  local needle="$1"
  for id in "${EXPECTED_IDS[@]}"; do
    if [[ "$id" == "$needle" ]]; then return 0; fi
  done
  return 1
}

# Pattern: (Closes|Fixes|Resolves)[whitespace]#<digits>
# Case-insensitive on keyword to catch a `closes #34` typo too.
PATTERN='([Cc]loses|[Ff]ixes|[Rr]esolves)[[:space:]]+#[0-9]+'

# Scanning model (corrected 2026-05-21 after PR #54 incident).
# GitHub's close-keyword parser in COMMIT MESSAGES fires on every
# `(Closes|Fixes|Resolves) #N` token in the raw text — including
# tokens that appear inside inline-backtick code spans (`...`) and
# inside triple-backtick fenced code blocks. The "backtick to be
# safe" guidance that the v1 of this script encoded was empirically
# wrong: PR #54's merge closed epic #34 via a commit whose ONLY
# `Closes #34` references were backticked or fenced.
#
# Consequence: the audit must NOT pre-strip markdown code spans
# before grepping. Every match in the raw text is a live close-
# keyword and must have its ID in --closes. The defense for a
# documentation reference is to REPHRASE rather than backtick —
# e.g. write "the PR that closes #34" (no close-keyword prefix) or
# "the close-keyword for #34" instead of "Closes #34".
#
# The empirical test is the only authoritative source for parser
# behavior; the playbook documents how to run one before assuming.

# scan_line — iterate over EVERY close-keyword match on a line (not
# just the first one) and check each match's own ID against --closes.
# Bug-protected: a line like `Closes #48 and later Closes #34` has
# two distinct matches, both checked; a line like `See #34 for
# context. Closes #48` has one close-keyword match (`Closes #48`) and
# the bare `#34` is NOT a match (no Closes/Fixes/Resolves prefix).
#
# Updates two outer-scope globals on FAIL: OVERALL_OK=0 and
# ANY_FAIL_REASON (concatenated). Prints [ok]/[FAIL] markers per
# match.
#
# Args:
#   $1 — the line to scan
#   $2 — context label (e.g. "commit abcd1234" or "body" or "title")
#   $3 — fail-reason suffix to append to ANY_FAIL_REASON on FAIL
scan_line() {
  local line="$1"
  local context="$2"
  local fail_suffix="$3"
  local match found_id
  # ``grep -oE PATTERN`` emits each match on its own line. Iterating
  # via a process substitution gives us one match per loop iteration;
  # extracting the number from THAT match (not from the whole line)
  # is the fix for the original single-extraction bug.
  while IFS= read -r match; do
    [[ -z "$match" ]] && continue
    found_id="$(echo "$match" | grep -oE '[0-9]+' | head -1)"
    if id_expected "$found_id"; then
      printf '  [ok]   %s: #%s (intended; match=%q)\n' "$context" "$found_id" "$match"
    else
      printf '  [FAIL] %s: #%s NOT in --closes (%s)\n' "$context" "$found_id" "$CLOSES" >&2
      printf '         line:  %s\n' "$line" >&2
      printf '         match: %s\n' "$match" >&2
      OVERALL_OK=0
      ANY_FAIL_REASON+="$fail_suffix; "
    fi
  done < <(echo "$line" | grep -oE "$PATTERN" || true)
}

OVERALL_OK=1
ANY_FAIL_REASON=""

# ── Check 1: commit-message close-keyword audit ───────────────────────

echo "=== pre-pr-check: commit-message close-keyword audit ==="
COMMIT_BODIES="$(git log "${BASE}..HEAD" --format='COMMIT %h%n%B%n---END---')"
PRE_SCAN_OK="$OVERALL_OK"
current_sha=""
while IFS= read -r line; do
  if [[ "$line" =~ ^COMMIT\ ([0-9a-f]+)$ ]]; then
    current_sha="${BASH_REMATCH[1]}"
    continue
  fi
  if [[ "$line" == "---END---" ]]; then
    current_sha=""
    continue
  fi
  if [[ "$line" =~ $PATTERN ]]; then
    scan_line "$line" "commit $current_sha" "commit messages reference unintended issue IDs (rephrase the prose to drop the close-keyword, or add the ID to --closes if intended — backticking does NOT save you for commit messages, see the playbook)"
  fi
done <<< "$COMMIT_BODIES"
if [[ "$OVERALL_OK" -eq "$PRE_SCAN_OK" ]]; then
  echo "  [PASS] no unexpected close-keywords in commit messages"
fi
echo

# ── Check 2: PR body file presence + close-keyword audit ──────────────

echo "=== pre-pr-check: PR body file ==="
if [[ ! -e "$BODY_FILE" ]]; then
  echo "  [FAIL] body file does not exist: $BODY_FILE" >&2
  echo "         create it before re-running this check, or pipe content via process substitution if you must" >&2
  OVERALL_OK=0
  ANY_FAIL_REASON+="body file missing; "
elif [[ ! -r "$BODY_FILE" ]]; then
  echo "  [FAIL] body file not readable in this shell: $BODY_FILE" >&2
  echo "         (this is the failure mode from PR #41 — verify gh runs in the same fs context as this script)" >&2
  OVERALL_OK=0
  ANY_FAIL_REASON+="body file unreadable in this shell; "
elif [[ -z "$(tr -d '[:space:]' < "$BODY_FILE")" ]]; then
  echo "  [FAIL] body file is empty or whitespace-only: $BODY_FILE" >&2
  OVERALL_OK=0
  ANY_FAIL_REASON+="body file empty; "
else
  echo "  [PASS] body file exists, readable, non-empty: $BODY_FILE ($(wc -c < "$BODY_FILE" | tr -d ' ') bytes)"
  # Scan body for close keywords — strict mode (NO code-span
  # stripping; see the "Scanning model" comment block above for
  # why). Every close-keyword match on a line is checked against
  # --closes via scan_line.
  while IFS= read -r line; do
    if [[ "$line" =~ $PATTERN ]]; then
      scan_line "$line" "body" "body references unintended issue IDs"
    fi
  done < "$BODY_FILE"
fi
echo

# ── Check 3: title sanity ─────────────────────────────────────────────

echo "=== pre-pr-check: PR title ==="
if [[ -z "$TITLE" ]]; then
  echo "  [FAIL] --title is empty (PR would open with branch-name title, like PR #41 last session)" >&2
  OVERALL_OK=0
  ANY_FAIL_REASON+="title empty; "
else
  echo "  [PASS] title non-empty: $TITLE"
  if echo "$TITLE" | grep -qE "$PATTERN"; then
    # Scan EVERY close-keyword match in the title (scan_line handles
    # the "multiple matches per line" case + extracts the ID from
    # each match, not from the whole line).
    scan_line "$TITLE" "title" "title close-id mismatch"
  else
    # Per the repo's PR convention: every PR title carries a
    # '(Closes #N)' marker. PR #41 last session opened with the
    # auto-generated branch-name title (no marker) and the recovery
    # edit failed — this is a HARD failure, not a warning.
    echo "  [FAIL] title has no '(Closes|Fixes|Resolves) #N' marker — by repo convention every PR title includes it" >&2
    OVERALL_OK=0
    ANY_FAIL_REASON+="title missing close-keyword marker; "
  fi
fi
echo

# ── Outcome ───────────────────────────────────────────────────────────

if [[ "$OVERALL_OK" -eq 1 ]]; then
  echo "=== pre-pr-check: ALL CHECKS PASSED ==="
  echo
  echo "Proposed gh pr create command (run this NEXT, in the same shell):"
  echo
  printf '  gh pr create \\\n'
  printf '      --base %s \\\n' "$BASE"
  printf '      --title %q \\\n' "$TITLE"
  printf '      --body-file %q\n' "$BODY_FILE"
  echo
  echo "Reminder: if 'gh pr create' fails with the Projects-classic GraphQL deprecation,"
  echo "          fall back to the REST API path:"
  echo "  gh api -X PATCH /repos/<owner>/<repo>/pulls/<n> \\"
  echo "      --field title=... --field body=@$BODY_FILE"
  exit 0
fi

echo "=== pre-pr-check: FAILED ===" >&2
echo "Reason(s): $ANY_FAIL_REASON" >&2
echo "Fix the offending references (rephrase the prose to drop the close-keyword, or add the ID to --closes if intended). Backticking does NOT shield commit messages from GitHub's parser — see knowledge/wiki/playbooks/pre-pr-close-keyword-audit.md for the empirical finding." >&2
exit 1
