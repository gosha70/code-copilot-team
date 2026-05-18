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

# ── Section 5: audit-flush e2e round-trip ─────────────────
#
# Run in a scratch git init repo that contains a copy of the
# wiki_ingest package. This means _resolve_repo_root() resolves to
# the scratch root (Path(__file__).parent.parent.parent), so a real
# `git commit` does not touch the working repo.

echo ""
echo "=== audit-flush e2e round-trip ==="

WIKI_BIN="$REPO_DIR/scripts/wiki"
assert "wiki entrypoint exists" "[[ -f '$WIKI_BIN' ]]"
assert "wiki entrypoint is executable" "[[ -x '$WIKI_BIN' ]]"

AF_SCRATCH="$(mktemp -d)"
# Sections 2+3 (wiki-ingest smoke tests) write to the working repo's
# knowledge/wiki/.audit/. Clean that up on exit along with all other temp
# files. The REPO_DIR .audit/ is an untracked side-effect of running ingest
# against the real repo root; we own the cleanup here.
# shellcheck disable=SC2064
trap "rm -rf '$SMOKE_TMPDIR' '$SMOKE_STDOUT' '$SMOKE_STDERR' '$UNITTEST_LOG' '$DRY_TMPDIR' '$DRY_STDOUT' '$AF_SCRATCH' '$REPO_DIR/knowledge/wiki/.audit'" EXIT

AF_REPO="$AF_SCRATCH/repo"
mkdir -p "$AF_REPO"
git -C "$AF_REPO" init --quiet
git -C "$AF_REPO" config user.email "test@example.com"
git -C "$AF_REPO" config user.name "Test"

# Seed a README so HEAD exists before audit-flush runs.
printf '# scratch\n' > "$AF_REPO/README.md"
git -C "$AF_REPO" add README.md
git -C "$AF_REPO" commit --quiet -m "init"

# Copy the wiki_ingest package into the scratch repo's scripts/ dir so
# that _resolve_repo_root() (Path(__file__).parent.parent.parent)
# resolves to AF_REPO rather than the working repo.
# Also copy the schema files that the multi-page ingestor requires.
mkdir -p "$AF_REPO/scripts"
cp -r "$REPO_DIR/scripts/wiki_ingest" "$AF_REPO/scripts/wiki_ingest"
mkdir -p "$AF_REPO/knowledge/wiki/schema"
cp "$REPO_DIR/knowledge/wiki/schema/ingest-rules.md" "$AF_REPO/knowledge/wiki/schema/"
cp "$REPO_DIR/knowledge/wiki/schema/page-types.md" "$AF_REPO/knowledge/wiki/schema/"
cp "$REPO_DIR/knowledge/wiki/schema/citation-rules.md" "$AF_REPO/knowledge/wiki/schema/"

# Helper alias: run wiki_ingest with the scratch package on PYTHONPATH.
AF_WIKI="PYTHONPATH=$AF_REPO/scripts python3 -m wiki_ingest"

# Step 1: run `wiki ingest --backend test` inside the scratch repo.
# --allow-out-of-repo is required because the fixture lives in the
# working repo, not in the scratch repo.
AF_INGEST_OUT="$(mktemp)"
AF_INGEST_PROPOSALS="$AF_SCRATCH/proposals"
mkdir -p "$AF_INGEST_PROPOSALS"
set +e
eval "$AF_WIKI ingest \
    --backend test \
    --allow-out-of-repo \
    --output-dir '$AF_INGEST_PROPOSALS' \
    '$REPO_DIR/scripts/wiki_ingest/tests/fixtures/sample-incident.md'" \
    >"$AF_INGEST_OUT" 2>/dev/null
AF_INGEST_EXIT=$?
set -e
assert "audit-flush e2e: wiki ingest exits 0" "[[ '$AF_INGEST_EXIT' -eq 0 ]]"

AF_LOG="$AF_REPO/knowledge/wiki/.audit/ingest-log.md"
assert "audit-flush e2e: ingest-log.md exists after ingest" "[[ -f '$AF_LOG' ]]"

# Count data lines (lines after the 2-line preamble) using the scratch package.
AF_LOG_DATA_LINES="$(PYTHONPATH="$AF_REPO/scripts" python3 - "$AF_LOG" <<'PYEOF'
import sys, pathlib
from wiki_ingest.audit_lint import INGEST_LOG_MARKER
p = pathlib.Path(sys.argv[1])
lines = p.read_text(encoding="utf-8").split("\n")
data = [l for l in lines[2:] if l.strip()]
print(len(data))
PYEOF
)"
assert "audit-flush e2e: at least 1 pending data line after ingest" \
  "[[ '$AF_LOG_DATA_LINES' -ge 1 ]]"

# Step 2: dry-run — should print "N pending ingest-log line(s); blob <sha>"
AF_DRY_OUT="$(mktemp)"
set +e
eval "$AF_WIKI audit-flush --dry-run" >"$AF_DRY_OUT" 2>/dev/null
AF_DRY_EXIT=$?
set -e
assert "audit-flush --dry-run exits 0" "[[ '$AF_DRY_EXIT' -eq 0 ]]"
assert "audit-flush --dry-run prints 'pending ingest-log line(s)'" \
  "grep -q 'pending ingest-log line' '$AF_DRY_OUT'"
assert "audit-flush --dry-run output contains 'blob'" \
  "grep -q 'blob' '$AF_DRY_OUT'"

# Step 3: ingest-log.md must NOT be committed yet (dry-run does not commit).
AF_LOG_STATUS="$(git -C "$AF_REPO" status --porcelain -- 'knowledge/wiki/.audit/ingest-log.md')"
assert "audit-flush e2e: ingest-log.md is still uncommitted after --dry-run" \
  "[[ -n '$AF_LOG_STATUS' ]]"

# Step 4: real flush.
AF_FLUSH_OUT="$(mktemp)"
set +e
eval "$AF_WIKI audit-flush" >"$AF_FLUSH_OUT" 2>/dev/null
AF_FLUSH_EXIT=$?
set -e
assert "audit-flush exits 0" "[[ '$AF_FLUSH_EXIT' -eq 0 ]]"

# Step 5: verify commit message and single-file diff.
AF_COMMIT_MSG="$(git -C "$AF_REPO" log -1 --format='%s')"
assert "audit-flush commit message starts with 'audit: flush'" \
  "[[ '$AF_COMMIT_MSG' == 'audit: flush '* ]]"
assert "audit-flush commit message contains 'pending ingest-log line'" \
  "[[ '$AF_COMMIT_MSG' == *'pending ingest-log line'* ]]"

AF_STAT="$(git -C "$AF_REPO" show --stat --format='' HEAD)"
# Count files listed in the stat (lines containing "|")
AF_FILE_COUNT="$(printf '%s\n' "$AF_STAT" | grep -c '|' || true)"
assert "audit-flush commit changes exactly one file" \
  "[[ '$AF_FILE_COUNT' -eq 1 ]]"
assert "audit-flush commit changes ingest-log.md" \
  "[[ '$AF_STAT' == *'ingest-log.md'* ]]"

# Step 6: second run must be a no-op.
AF_NOOP_OUT="$(mktemp)"
set +e
eval "$AF_WIKI audit-flush" >"$AF_NOOP_OUT" 2>/dev/null
AF_NOOP_EXIT=$?
set -e
assert "audit-flush second run exits 0" "[[ '$AF_NOOP_EXIT' -eq 0 ]]"
assert "audit-flush second run prints 'nothing to flush'" \
  "grep -q 'nothing to flush' '$AF_NOOP_OUT'"

# The scratch repo is under AF_SCRATCH — removed by the trap above.
# Verify no stray .audit/ was left in the working repo itself.
assert "audit-flush e2e: no stray .audit/ in the working repo" \
  "[[ ! -e '$REPO_DIR/knowledge/wiki/.audit/ingest-log.md' ]] || \
   git -C '$REPO_DIR' diff --quiet -- 'knowledge/wiki/.audit/ingest-log.md'"

# ── Results ───────────────────────────────────────────────

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
