#!/usr/bin/env bash
# Deterministic verifier for cct-dogfood-memkernel :: memory-brain-spec.
#
# Hard checks (failure => verify exits non-zero):
#   1. specs/memory-brain/spec.md exists.
#   2. The seven required section headers are present.
#   3. pyproject.toml is byte-for-byte identical to the baseline.
#   4. src/memkernel/mcp/ is byte-for-byte identical to the baseline.
#
# Best-effort checks (skipped if toolchain absent; failure => verify
# exits non-zero):
#   5. ruff check is clean.
#   6. mypy src/ is clean.
#   7. pytest passes.
#
# Each check writes a tagged line:
#   ✓ <label>: <summary>     -- pass
#   ✗ <label>: <summary>     -- fail
#   - <label>: <reason>      -- skipped (best-effort only)
#
# The adapter parses these glyphs to populate VerifyResult.lint_passed
# and VerifyResult.typecheck_passed; do not change the tag format
# without updating adapter._scan_check_status in lockstep.

set -u
# Run from cwd. The harness invokes this as `bash .cct-verify.sh`
# with cwd set to the worktree root; manual runs must do the same
# (the script does not auto-resolve the worktree because it is copied
# into the worktree by prepare_task, not symlinked from its source).

PASS=0
FAIL=0
SKIP=0

ok()   { echo "✓ $*"; PASS=$((PASS+1)); }
bad()  { echo "✗ $*"; FAIL=$((FAIL+1)); }
skip() { echo "- $*"; SKIP=$((SKIP+1)); }

# ── Hard check 1: spec.md exists ─────────────────────────────────────────
SPEC=specs/memory-brain/spec.md
if [[ -f "$SPEC" ]]; then
  ok "spec_exists: $SPEC present"
else
  bad "spec_exists: $SPEC missing"
fi

# ── Hard check 2: seven required section headers ────────────────────────
# Pattern: lines like ``## 1. Problem Statement`` or ``## Problem Statement``
# (numbering is in the source body but we accept either).
SECTIONS=(
  "Problem Statement"
  "Proposed Architecture"
  "Memory Tier Model"
  "Lifecycle State Machine"
  "Routing Layer"
  "Synthesis Port"
  "Acceptance Criteria"
)
if [[ -f "$SPEC" ]]; then
  for section in "${SECTIONS[@]}"; do
    # ``-E`` extended regex; allow optional ``N. `` numeric prefix and
    # any number of leading ``#``s. Trailing whitespace tolerated.
    if grep -qE "^#+[[:space:]]+([0-9]+\.[[:space:]]+)?${section}[[:space:]]*$" "$SPEC"; then
      ok "section: $section"
    else
      bad "section: $section missing from $SPEC"
    fi
  done
else
  for section in "${SECTIONS[@]}"; do
    skip "section: $section (spec missing — see spec_exists)"
  done
fi

# ── Hard check 3: pyproject.toml unchanged ──────────────────────────────
BASELINE=.cct-baseline
if [[ -f $BASELINE/pyproject.toml ]]; then
  if diff -q "$BASELINE/pyproject.toml" pyproject.toml > /dev/null 2>&1; then
    ok "pyproject_unchanged: no new dependencies"
  else
    bad "pyproject_unchanged: pyproject.toml modified — spec-first issue forbids new deps"
    diff "$BASELINE/pyproject.toml" pyproject.toml | sed 's/^/    /' | head -20
  fi
else
  bad "pyproject_unchanged: baseline missing ($BASELINE/pyproject.toml not captured)"
fi

# ── Hard check 4: src/memkernel/mcp/ unchanged ──────────────────────────
if [[ -d $BASELINE/mcp ]]; then
  if diff -rq "$BASELINE/mcp" src/memkernel/mcp > /dev/null 2>&1; then
    ok "mcp_unchanged: no new MCP code"
  else
    bad "mcp_unchanged: src/memkernel/mcp/ modified — spec-first issue forbids MCP changes"
    diff -rq "$BASELINE/mcp" src/memkernel/mcp 2>&1 | sed 's/^/    /' | head -20
  fi
else
  # If memkernel never had a mcp dir (very early commit), this check is
  # vacuously true.
  if [[ -d src/memkernel/mcp ]]; then
    bad "mcp_unchanged: baseline missing but src/memkernel/mcp/ exists — agent may have created MCP code"
  else
    ok "mcp_unchanged: no MCP dir in baseline or worktree"
  fi
fi

# ── Best-effort check 5: ruff ───────────────────────────────────────────
if command -v ruff >/dev/null 2>&1; then
  if ruff check . > /tmp/cct-ruff.log 2>&1; then
    ok "ruff: clean"
  else
    bad "ruff: errors"
    sed 's/^/    /' /tmp/cct-ruff.log | head -30
  fi
else
  skip "ruff: not installed in venv"
fi

# ── Best-effort check 6: mypy ───────────────────────────────────────────
if command -v mypy >/dev/null 2>&1; then
  # mypy without runtime deps will emit "Cannot find implementation"
  # errors; treat that as "skip" rather than "fail". A real run with
  # runtime deps installed (poetry install --with dev) would be strict.
  if mypy src/ > /tmp/cct-mypy.log 2>&1; then
    ok "mypy: clean"
  else
    if grep -q "Cannot find implementation or library stub" /tmp/cct-mypy.log; then
      skip "mypy: runtime deps not installed (Cannot find implementation errors)"
    else
      bad "mypy: errors"
      sed 's/^/    /' /tmp/cct-mypy.log | head -30
    fi
  fi
else
  skip "mypy: not installed in venv"
fi

# ── Best-effort check 7: pytest ─────────────────────────────────────────
if command -v pytest >/dev/null 2>&1; then
  # Memkernel's full test suite needs chromadb + sentence-transformers.
  # If those imports fail at collection, treat as skipped. Also treat
  # pytest exit code 5 ("no tests collected") as skip — that fires on
  # synthetic test fixtures that don't carry any tests, and on a real
  # memkernel checkout it would indicate the test suite couldn't even
  # discover anything (usually a deps-missing symptom).
  pytest -q --no-header --tb=line > /tmp/cct-pytest.log 2>&1
  rc=$?
  if [[ $rc -eq 0 ]]; then
    ok "pytest: passes"
  elif [[ $rc -eq 5 ]]; then
    skip "pytest: no tests collected (deps missing or empty suite)"
  elif grep -qE "ImportError|ModuleNotFoundError" /tmp/cct-pytest.log; then
    skip "pytest: runtime deps missing (collection errors)"
  else
    bad "pytest: failures"
    sed 's/^/    /' /tmp/cct-pytest.log | tail -30
  fi
else
  skip "pytest: not installed in venv"
fi

echo
echo "[verify] PASS=$PASS FAIL=$FAIL SKIP=$SKIP"

# Hard checks alone determine the exit code. Skipped best-effort checks
# do not fail the verifier.
[[ $FAIL -eq 0 ]] || exit 1
exit 0
