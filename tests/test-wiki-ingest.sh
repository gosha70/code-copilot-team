#!/usr/bin/env bash

# test-wiki-ingest.sh — Test runner for the wiki ingest pipeline.
#
# Wraps two layers:
#   1. The Python unittest suite under scripts/wiki_ingest/tests/
#      (proposal/prompt/ingestor/json-extract/copilot-cli/e2e).
#   2. A bash-level end-to-end smoke test of the ./scripts/wiki-ingest
#      entrypoint with the deterministic --backend test, asserting a
#      proposal file lands and exits 0.
#
# Run from the repo root:
#   bash tests/test-wiki-ingest.sh
#
# Exit 0 when both layers pass, exit 1 on any failure.
#
# Convention:
#   - stdlib-only Python (no pip install step required).
#   - Output goes to a tempdir; the real doc_internal/proposals/ is
#     never touched.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$SCRIPT_DIR/.."
WIKI_INGEST_BIN="$REPO_DIR/scripts/wiki-ingest"
SAMPLE_FIXTURE="$REPO_DIR/scripts/wiki_ingest/tests/fixtures/sample-incident.md"

PASS=0
FAIL=0

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"
    FAIL=$((FAIL + 1))
  fi
}

# ── Section 1: Python unittest discovery ──────────────────

echo "=== Python unittest suite ==="

UNITTEST_LOG="$(mktemp)"
trap 'rm -f "$UNITTEST_LOG"' EXIT

if PYTHONPATH="$REPO_DIR/scripts" python3 -m unittest discover \
     -v scripts/wiki_ingest/tests >"$UNITTEST_LOG" 2>&1; then
  echo "  PASS: unittest discovery exit 0"
  PASS=$((PASS + 1))
else
  echo "  FAIL: unittest discovery exit non-zero"
  FAIL=$((FAIL + 1))
  echo "--- last 40 lines of unittest output ---"
  tail -n 40 "$UNITTEST_LOG"
  echo "----------------------------------------"
fi

# Pull the "Ran N tests" line out of unittest's verbose output. The
# count is informational here — drift is not a failure on its own,
# because individual tests assert their own contracts. We surface
# the number so a reader of CI logs can see at a glance whether new
# tests were added or removed.
RAN_LINE="$(grep -E '^Ran [0-9]+ tests' "$UNITTEST_LOG" || true)"
if [[ -n "$RAN_LINE" ]]; then
  echo "  INFO: $RAN_LINE"
fi

# ── Section 2: Bash entrypoint smoke test ─────────────────

echo ""
echo "=== Bash entrypoint smoke test ==="

assert "wiki-ingest entrypoint exists" "[[ -f '$WIKI_INGEST_BIN' ]]"
assert "wiki-ingest entrypoint is executable" "[[ -x '$WIKI_INGEST_BIN' ]]"
assert "sample-incident fixture exists" "[[ -f '$SAMPLE_FIXTURE' ]]"

# Run the entrypoint against the deterministic test backend in a
# tempdir. Capture both stdout (proposal path) and exit code.
# Resolve symlinks (macOS mktemp returns /var/... which is a symlink
# to /private/var/...; Python's Path.resolve() follows the symlink, so
# the printed proposal path won't string-prefix-match an unresolved
# tempdir).
SMOKE_TMPDIR="$(cd "$(mktemp -d)" && pwd -P)"
SMOKE_STDOUT="$(mktemp)"
SMOKE_STDERR="$(mktemp)"
# shellcheck disable=SC2064
trap "rm -rf '$SMOKE_TMPDIR' '$SMOKE_STDOUT' '$SMOKE_STDERR' '$UNITTEST_LOG'" EXIT

set +e
"$WIKI_INGEST_BIN" \
    --backend test \
    --output-dir "$SMOKE_TMPDIR" \
    "$SAMPLE_FIXTURE" \
    >"$SMOKE_STDOUT" 2>"$SMOKE_STDERR"
SMOKE_EXIT=$?
set -e

assert "wiki-ingest --backend test exits 0" "[[ '$SMOKE_EXIT' -eq 0 ]]"

PROPOSAL_PATH="$(tr -d '\n' < "$SMOKE_STDOUT")"
assert "wiki-ingest prints a non-empty proposal path" "[[ -n '$PROPOSAL_PATH' ]]"
assert "proposal file exists at the printed path" "[[ -f '$PROPOSAL_PATH' ]]"
assert "proposal file lives under requested output-dir" \
  "[[ '$PROPOSAL_PATH' == $SMOKE_TMPDIR/* ]]"
assert "proposal frontmatter has gate_disposition" \
  "grep -q '^gate_disposition:' '$PROPOSAL_PATH'"
assert "proposal frontmatter has ingestor_version" \
  "grep -q '^ingestor_version:' '$PROPOSAL_PATH'"
assert "proposal frontmatter records backend: 'test'" \
  "grep -q \"^backend: 'test'\" '$PROPOSAL_PATH'"

# ── Section 3: Bash entrypoint dry-run ────────────────────

echo ""
echo "=== Bash entrypoint dry-run ==="

DRY_TMPDIR="$(cd "$(mktemp -d)" && pwd -P)"
DRY_STDOUT="$(mktemp)"
# shellcheck disable=SC2064
trap "rm -rf '$SMOKE_TMPDIR' '$SMOKE_STDOUT' '$SMOKE_STDERR' '$UNITTEST_LOG' '$DRY_TMPDIR' '$DRY_STDOUT'" EXIT

set +e
"$WIKI_INGEST_BIN" \
    --backend test \
    --dry-run \
    --output-dir "$DRY_TMPDIR" \
    "$SAMPLE_FIXTURE" \
    >"$DRY_STDOUT" 2>/dev/null
DRY_EXIT=$?
set -e

assert "wiki-ingest --dry-run exits 0" "[[ '$DRY_EXIT' -eq 0 ]]"

DRY_PATH="$(tr -d '\n' < "$DRY_STDOUT")"
assert "dry-run proposal file exists" "[[ -f '$DRY_PATH' ]]"
assert "dry-run frontmatter still has gate_disposition" \
  "grep -q '^gate_disposition:' '$DRY_PATH'"
# Body must NOT contain wiki-page frontmatter or required H2s.
assert "dry-run body omits the draft (no page_type: incident)" \
  "! grep -q '^page_type: incident' '$DRY_PATH'"
assert "dry-run body omits the incident H2s" \
  "! grep -q '^## What happened' '$DRY_PATH'"

# ── Section 4: Negative path — missing source ─────────────

echo ""
echo "=== Negative paths ==="

set +e
"$WIKI_INGEST_BIN" \
    --backend test \
    --output-dir "$SMOKE_TMPDIR" \
    /nonexistent/path/that/does/not/exist.md \
    >/dev/null 2>"$SMOKE_STDERR"
MISSING_EXIT=$?
set -e

assert "missing source exits 5" "[[ '$MISSING_EXIT' -eq 5 ]]"
assert "missing source prints diagnostic to stderr" \
  "grep -q 'source file not found' '$SMOKE_STDERR'"

set +e
"$WIKI_INGEST_BIN" \
    --backend totally-not-a-real-backend \
    --output-dir "$SMOKE_TMPDIR" \
    "$SAMPLE_FIXTURE" \
    >/dev/null 2>"$SMOKE_STDERR"
UNKNOWN_BACKEND_EXIT=$?
set -e

assert "unknown backend exits 2" "[[ '$UNKNOWN_BACKEND_EXIT' -eq 2 ]]"

# ── Results ───────────────────────────────────────────────

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
