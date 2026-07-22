#!/usr/bin/env bash

# test-pi-adapter.sh — Tests for the Pi adapter generation + install surface
#
# Covers (specs/pi-harness-adoption): FR-002 (advisory manifest has no
# extensions), FR-003 (deterministic generation), C-4 (always-context),
# FR-001 (installer never clobbers an unrelated pi-code).
#
# Run from the repo root:
#   bash tests/test-pi-adapter.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PI_DIR="$REPO_DIR/adapters/pi"
RES="$PI_DIR/resources"
SKILLS="$REPO_DIR/shared/skills"

PASS=0
FAIL=0

assert() {
  local name="$1" condition="$2"
  if eval "$condition"; then
    echo "  PASS: $name"; PASS=$((PASS + 1))
  else
    echo "  FAIL: $name"; FAIL=$((FAIL + 1))
  fi
}

echo "=== Pi adapter tests ==="

# ── Generation outputs ──────────────────────────────────────
echo "--- generation outputs ---"
bash "$REPO_DIR/scripts/generate.sh" > /dev/null

SHARED_COUNT=$(ls -d "$SKILLS"/*/ | wc -l | tr -d ' ')
PI_SKILL_COUNT=$(ls -d "$RES/skills"/*/ 2>/dev/null | wc -l | tr -d ' ')
assert "all shared skills copied verbatim ($SHARED_COUNT)" "[[ '$PI_SKILL_COUNT' == '$SHARED_COUNT' ]]"
assert "skill copy is byte-identical (safety)" "cmp -s '$SKILLS/safety/SKILL.md' '$RES/skills/safety/SKILL.md'"

assert "static command converted (bet)" "[[ -f '$RES/prompts/bet.md' ]]"
assert "prompt has description frontmatter" "head -2 '$RES/prompts/bet.md' | grep -q '^description:'"
assert "stateful command excluded (review-submit)" "[[ ! -f '$RES/prompts/review-submit.md' ]]"
assert "stateful command excluded (auto-build)" "[[ ! -f '$RES/prompts/auto-build.md' ]]"
assert "always-context bundle exists" "[[ -f '$RES/context/always-context.md' ]]"
assert "always-context includes safety policy" "grep -q 'Destructive' '$RES/context/always-context.md' || grep -qi 'safety' '$RES/context/always-context.md'"

# ── Determinism (FR-003) ────────────────────────────────────
echo "--- determinism ---"
SUM1=$(cd "$RES" && find . -type f | LC_ALL=C sort | xargs cat | shasum | cut -d' ' -f1)
bash "$REPO_DIR/scripts/generate.sh" > /dev/null
SUM2=$(cd "$RES" && find . -type f | LC_ALL=C sort | xargs cat | shasum | cut -d' ' -f1)
assert "generation is deterministic (two runs identical)" "[[ '$SUM1' == '$SUM2' ]]"

# ── Advisory manifest (FR-002/FR-002a) ──────────────────────
echo "--- advisory package manifest ---"
PKG="$REPO_DIR/package.json"
assert "root package.json exists" "[[ -f '$PKG' ]]"
assert "keyword pi-package present" "grep -q '\"pi-package\"' '$PKG'"
assert "manifest exposes skills" "grep -q 'adapters/pi/resources/skills' '$PKG'"
assert "manifest exposes prompts" "grep -q 'adapters/pi/resources/prompts' '$PKG'"
assert "manifest never exposes extensions (runtime not auto-loaded)" "! grep -q '\"extensions\"' '$PKG'"
assert "runtime not in auto-discovered extensions dir" "[[ ! -d '$PI_DIR/extensions' && ! -d '$PI_DIR/resources/extensions' ]]"
assert "runtime guards on CCT_RUNTIME marker" "grep -q 'CCT_RUNTIME' '$PI_DIR/runtime/index.ts'"
assert "runtime defers project_trust ownership" "grep -q 'return undefined' '$PI_DIR/runtime/index.ts'"
assert "README declares advisory mode" "grep -q 'Installation mode: Advisory' '$PI_DIR/README.md'"

# ── Installer safety (FR-001) ───────────────────────────────
echo "--- installer ---"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Refuses to overwrite an unrelated pi-code
mkdir -p "$TMP/bin-foreign"
printf '#!/bin/sh\necho unrelated\n' > "$TMP/bin-foreign/pi-code"
chmod +x "$TMP/bin-foreign/pi-code"
if CCT_HOME="$TMP/cct1" CCT_BIN_DIR="$TMP/bin-foreign" bash "$PI_DIR/setup.sh" > /dev/null 2>&1; then
  assert "installer refuses unrelated pi-code" "false"
else
  assert "installer refuses unrelated pi-code" "true"
fi
assert "unrelated pi-code left intact" "grep -q unrelated '$TMP/bin-foreign/pi-code'"

# Clean install into temp HOME
CCT_HOME="$TMP/cct2" CCT_BIN_DIR="$TMP/bin2" bash "$PI_DIR/setup.sh" > /dev/null 2>&1
assert "installer places launcher" "[[ -x '$TMP/bin2/pi-code' ]]"
assert "installer places runtime" "[[ -f '$TMP/cct2/pi/runtime/index.ts' ]]"
assert "installer places resources" "[[ -d '$TMP/cct2/pi/resources/skills' ]]"
assert "installer places compat.env" "grep -q 'CCT_PI_MIN_VERSION' '$TMP/cct2/pi/compat.env'"

# Idempotency
CCT_HOME="$TMP/cct2" CCT_BIN_DIR="$TMP/bin2" bash "$PI_DIR/setup.sh" > /dev/null 2>&1
assert "installer is idempotent" "[[ -x '$TMP/bin2/pi-code' ]]"

# Repair (T0.4) — restores a missing component, refuses a foreign launcher
rm -f "$TMP/cct2/pi/compat.env"
REPAIR_OUT=$(CCT_HOME="$TMP/cct2" CCT_BIN_DIR="$TMP/bin2" bash "$PI_DIR/setup.sh" --repair 2>&1)
assert "repair reports the missing component" "echo \"\$REPAIR_OUT\" | grep -q '\[missing\] compat.env'"
assert "repair restores the missing component" "[[ -f '$TMP/cct2/pi/compat.env' ]]"
REPAIR_OK=$(CCT_HOME="$TMP/cct2" CCT_BIN_DIR="$TMP/bin2" bash "$PI_DIR/setup.sh" --repair 2>&1)
assert "repair reports a healthy install as ok" "echo \"\$REPAIR_OK\" | grep -q '\[ok\]      compat.env'"

mkdir -p "$TMP/bin3"
printf '#!/bin/bash\necho other\n' > "$TMP/bin3/pi-code"; chmod +x "$TMP/bin3/pi-code"
RC=0
CCT_HOME="$TMP/cct3" CCT_BIN_DIR="$TMP/bin3" bash "$PI_DIR/setup.sh" --repair > /dev/null 2>&1 || RC=$?
assert "repair refuses a foreign launcher (exit 1)" "[[ '$RC' == '1' ]]"
assert "repair leaves the foreign launcher intact" "grep -q 'echo other' '$TMP/bin3/pi-code'"

# Uninstall
CCT_HOME="$TMP/cct2" CCT_BIN_DIR="$TMP/bin2" bash "$PI_DIR/setup.sh" --uninstall > /dev/null 2>&1
assert "uninstall removes launcher" "[[ ! -f '$TMP/bin2/pi-code' ]]"
assert "uninstall removes managed dir" "[[ ! -d '$TMP/cct2/pi' ]]"

# ── Advisory manifests (T0.1 / T0.3) ────────────────────────
echo "--- advisory manifests ---"
assert "adapter manifest exists" "[[ -f '$PI_DIR/package.json' ]]"
for key in skills prompts themes; do
  assert "adapter manifest declares pi.$key" \
    "grep -q '\"$key\"' '$PI_DIR/package.json'"
  assert "root manifest declares pi.$key" \
    "sed -n '/\"pi\": {/,/^  }/p' '$REPO_DIR/package.json' | grep -q '\"$key\"'"
done
assert "adapter manifest declares no pi.extensions" "! grep -q 'extensions' '$PI_DIR/package.json'"
assert "root manifest declares no pi.extensions" "! grep -q 'extensions' '$REPO_DIR/package.json'"
assert "themes resource directory is populated" "ls '$RES/themes'/*.json >/dev/null 2>&1"

# ── Version compatibility declaration (T0.6) ────────────────
echo "--- version compatibility ---"
assert "compat.env declares a semver minimum" \
  "grep -qE '^CCT_PI_MIN_VERSION=\"[0-9]+\.[0-9]+\.[0-9]+\"' '$PI_DIR/compat.env'"
COMPAT_MIN=$(grep -m1 '^CCT_PI_MIN_VERSION=' "$PI_DIR/compat.env" | cut -d'"' -f2)
LAUNCHER_MIN=$(grep -m1 '^CCT_PI_MIN_VERSION=' "$PI_DIR/bin/pi-code" | cut -d'"' -f2)
assert "launcher fallback matches compat.env ($COMPAT_MIN)" "[[ '$COMPAT_MIN' == '$LAUNCHER_MIN' ]]"
assert "CI consumes compat.env" \
  "grep -q 'compat.env' '$REPO_DIR/.github/workflows/pi-tests.yml'"

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  Pi adapter tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
