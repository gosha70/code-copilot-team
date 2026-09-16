#!/usr/bin/env bash

# test-doc-gates.sh — the documentation gates in check-doc-accuracy.sh
# (#214 Phases 3.3 and 4.3).
#
# These gates answer "does every shipped guide reach its readers?" — the
# landing page, the published site, and the README's index. They are tested
# by planting a file the registry does not know about and asserting each gate
# names it, then removing it.
#
# Run from the repo root:
#   bash tests/test-doc-gates.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
GATE="$REPO_DIR/scripts/check-doc-accuracy.sh"
PASS=0
FAIL=0
PLANTED=()

cleanup() { for f in "${PLANTED[@]:-}"; do [[ -n "$f" ]] && rm -f "$f"; done; }
trap cleanup EXIT

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"; FAIL=$((FAIL + 1))
  fi
}

plant() {  # <path> — a guide no registry lists
  printf '# Unregistered\n\nPlanted by tests/test-doc-gates.sh.\n' > "$REPO_DIR/$1"
  PLANTED+=("$REPO_DIR/$1")
}

echo "=== documentation gates ==="

cd "$REPO_DIR"
CLEAN_OUT=$(bash "$GATE" --counts-only 2>&1) || true
assert "the tree as committed passes the gates" "grep -q 'check-doc-accuracy: clean' <<<\"\$CLEAN_OUT\""

# ── a guide directly under docs/ ─────────────────────────────
plant "docs/zz-unregistered-guide.md"
OUT=$(bash "$GATE" --counts-only 2>&1) || true
assert "an unregistered guide fails the site-coverage gate" \
  "grep -q 'docs/zz-unregistered-guide.md ships but the Learn registry' <<<\"\$OUT\""
assert "an unregistered guide fails the landing-page gate" \
  "grep -q 'docs/zz-unregistered-guide.md ships but the docs landing page' <<<\"\$OUT\""
rm -f "$REPO_DIR/docs/zz-unregistered-guide.md"

# ── a guide in a SUBDIRECTORY ────────────────────────────────
# The gates globbed docs/*.md, which matches immediate children only: all
# three guides under docs/dgx-spark/ were outside the checks entirely, and a
# new one there passed silently (#359 review).
plant "docs/dgx-spark/zz-unregistered-nested.md"
OUT=$(bash "$GATE" --counts-only 2>&1) || true
assert "a nested unregistered guide fails the site-coverage gate" \
  "grep -q 'docs/dgx-spark/zz-unregistered-nested.md ships but the Learn registry' <<<\"\$OUT\""
assert "a nested unregistered guide fails the landing-page gate" \
  "grep -q 'docs/dgx-spark/zz-unregistered-nested.md ships but the docs landing page' <<<\"\$OUT\""
rm -f "$REPO_DIR/docs/dgx-spark/zz-unregistered-nested.md"

# ── the nested guides that DO exist are checked, not skipped ──
OUT=$(bash "$GATE" --counts-only 2>&1) || true
for existing in docs/dgx-spark/setup-cookbook.md docs/dgx-spark/vllm-qwen38.md docs/dgx-spark/runbook-qwen38.md; do
  assert "checked, not skipped: $existing" "grep -q 'reaches the site: $existing' <<<\"\$OUT\""
done

# ── an adapter guide, which lives two directories down ───────
plant "adapters/pi/docs/zz-unregistered-adapter-guide.md"
OUT=$(bash "$GATE" --counts-only 2>&1) || true
# adapters/*/docs is registered as a glob, so this one is covered by the glob
# and must PASS — the gate's job is to catch what no registry entry covers.
assert "a guide inside a globbed directory is covered by that glob" \
  "grep -q 'reaches the site: adapters/pi/docs/zz-unregistered-adapter-guide.md' <<<\"\$OUT\""
rm -f "$REPO_DIR/adapters/pi/docs/zz-unregistered-adapter-guide.md"

# ── the tree is left as it was found ─────────────────────────
FINAL=$(bash "$GATE" --counts-only 2>&1) || true
assert "the gates are clean again afterwards" "grep -q 'check-doc-accuracy: clean' <<<\"\$FINAL\""

echo ""
echo "========================================="
printf "  Results: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "========================================="
[[ $FAIL -gt 0 ]] && exit 1
exit 0
