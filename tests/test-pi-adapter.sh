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

# T2.4: every command the generator DEFERS (excludes from prompt conversion)
# must be REGISTERED in the runtime as /cct:<name>, or a user typing it gets
# "unknown command". Cross-check the two lists so they cannot drift.
STATEFUL=$(grep '^PI_STATEFUL_COMMANDS=' "$REPO_DIR/scripts/generate.sh" | cut -d'"' -f2)
for cmd in $STATEFUL; do
  assert "stateful '$cmd' registered as /cct:$cmd in runtime" \
    "grep -q '\"cct:$cmd\"' '$PI_DIR/runtime/index.ts'"
done
# Deferred commands report honestly (not a silent no-op or fake success).
assert "deferred stateful command reports deferral" \
  "grep -q 'recognized but not yet active in pi-code' '$PI_DIR/runtime/index.ts'"
# phase-complete has real backing (validates the SDD gate).
assert "phase-complete validates the SDD gate" \
  "grep -A15 '\"cct:phase-complete\"' '$PI_DIR/runtime/index.ts' | grep -q 'validateSpecDir'"

# ── Command → prompt conversion (T2.2) ──────────────────────
echo "--- prompt conversion ---"
CONVERT="$REPO_DIR/scripts/pi-convert-command.sh"

# argument-hint is derived from the source `Usage:` line.
assert "generated prompt carries argument-hint (shape)" \
  "grep -q '^argument-hint: \"<topic>\"' '$RES/prompts/shape.md'"
# a command with no arguments omits argument-hint rather than emitting an empty one.
assert "no-argument command omits argument-hint (cooldown)" \
  "! grep -q '^argument-hint:' '$RES/prompts/cooldown.md'"

# Claude-only frontmatter keys are dropped, with a warning; description and
# argument-hint from source frontmatter are kept.
FIX="$REPO_DIR/tests/fixtures/pi-commands/with-claude-metadata.md"
CONV_OUT=$(bash "$CONVERT" "$FIX" 2>/dev/null)
CONV_ERR=$(bash "$CONVERT" "$FIX" 2>&1 >/dev/null)
assert "conversion keeps source description" "echo \"\$CONV_OUT\" | grep -q '^description: \"A fixture command'"
assert "conversion keeps source argument-hint" "echo \"\$CONV_OUT\" | grep -q '^argument-hint: \"<file> \[--force\]\"'"
assert "conversion drops allowed-tools" "! echo \"\$CONV_OUT\" | grep -q 'allowed-tools'"
assert "conversion drops model" "! echo \"\$CONV_OUT\" | grep -qE '^model:'"
assert "conversion warns about dropped Claude-only keys" "echo \"\$CONV_ERR\" | grep -q 'dropped Claude-only metadata'"
assert "conversion preserves \$ARGUMENTS" "echo \"\$CONV_OUT\" | grep -q 'ARGUMENTS'"
assert "conversion preserves positional \$1" "echo \"\$CONV_OUT\" | grep -q '\$1'"

assert "always-context bundle exists" "[[ -f '$RES/context/always-context.md' ]]"

# T2.5: the generator emits a provenance manifest mapping each generated
# resource to its source, and the runtime CLI reports it.
assert "provenance manifest exists" "[[ -f '$RES/provenance.json' ]]"
assert "provenance manifest is valid JSON" \
  "python3 -c 'import json; json.load(open(\"$RES/provenance.json\"))'"
assert "provenance maps a skill to its shared source" \
  "python3 -c 'import json,sys; d=json.load(open(\"$RES/provenance.json\")); sys.exit(0 if d[\"skills\"][\"safety\"]==\"shared/skills/safety/SKILL.md\" else 1)'"
assert "provenance maps a prompt to its command source" \
  "python3 -c 'import json,sys; d=json.load(open(\"$RES/provenance.json\")); sys.exit(0 if \"claude-code\" in d[\"prompts\"][\"shape\"] else 1)'"
# The count must match what was actually generated (no stale/missing entries).
assert "provenance skill count matches generated skills" \
  "[[ \"\$(python3 -c 'import json; print(len(json.load(open(\"$RES/provenance.json\"))[\"skills\"]))')\" == \"\$(ls -d '$RES/skills'/*/ | wc -l | tr -d ' ')\" ]]"

# T2.3: the bundle is not just generated — the runtime loads it at session
# start and doctor reports it, and the Pi-specific size limit is documented.
assert "runtime imports the context loader" \
  "grep -q 'context.ts' '$PI_DIR/runtime/index.ts'"
assert "runtime injects always-context at session start" \
  "grep -q 'injectAlwaysContext' '$PI_DIR/runtime/index.ts'"
assert "doctor reports the always-context bundle" \
  "grep -q 'always-on context' '$PI_DIR/runtime/index.ts'"
assert "context module documents the advisory size limit" \
  "grep -q 'ALWAYS_CONTEXT_SOFT_LIMIT_BYTES' '$PI_DIR/runtime/context.ts'"
assert "README documents the Pi size limit (not Codex 32 KiB)" \
  "grep -q 'advisory soft limit' '$PI_DIR/README.md'"
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
# Both manifests list the same pi content resources; they are two declarations
# of one fact and must not drift (same class as the compat.env check).
for key in skills prompts themes; do
  ROOT_PATH=$(sed -n "/\"$key\": \[/,/\]/p" "$REPO_DIR/package.json" | grep -oE '\./[a-z/.-]+' | head -1)
  ADPT_PATH=$(sed -n "/\"$key\": \[/,/\]/p" "$PI_DIR/package.json" | grep -oE '\./[a-z/.-]+' | head -1)
  assert "manifests agree on pi.$key target" \
    "[[ 'adapters/pi/${ADPT_PATH#./}' == '${ROOT_PATH#./}' ]]"
done
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

# ── Config validation (T1.7) ────────────────────────────────
echo "--- config validation ---"
CFG="$REPO_DIR/tests/fixtures/cct-config"
if command -v node >/dev/null 2>&1 && [[ "$(node --version | sed 's/^v//' | cut -d. -f1)" -ge 22 ]]; then
  RC=0; bash "$REPO_DIR/scripts/validate-cct-config.sh" "$CFG/valid.toml" >/dev/null 2>&1 || RC=$?
  assert "validator accepts a valid config (exit 0)" "[[ '$RC' == '0' ]]"

  OUT=$(bash "$REPO_DIR/scripts/validate-cct-config.sh" "$CFG/obsolete-key.toml" 2>&1 || true)
  RC=0; bash "$REPO_DIR/scripts/validate-cct-config.sh" "$CFG/obsolete-key.toml" >/dev/null 2>&1 || RC=$?
  assert "validator rejects an obsolete key (exit 1)" "[[ '$RC' == '1' ]]"
  assert "validator names the obsolete key" "echo \"\$OUT\" | grep -q 'security.allow_all'"

  RC=0; bash "$REPO_DIR/scripts/validate-cct-config.sh" "$CFG/future-version.toml" >/dev/null 2>&1 || RC=$?
  assert "validator rejects a future schema version (exit 1)" "[[ '$RC' == '1' ]]"
else
  echo "  SKIP: config validation (node >= 22.6 unavailable)"
  if [[ -n "${CI:-}" ]]; then echo "  FAIL: node >= 22.6 required in CI"; FAIL=$((FAIL + 1)); fi
fi

# ── Workflow validity (CI cannot self-check a broken workflow) ──
echo "--- workflow validation ---"
assert "workflows validate" "bash '$REPO_DIR/scripts/validate-workflows.sh' >/dev/null 2>&1"
WF_BAD="$REPO_DIR/tests/fixtures/workflow-invalid"
WF_OUT=$(bash "$REPO_DIR/scripts/validate-workflows.sh" "$WF_BAD" 2>&1 || true)
WF_RC=0
bash "$REPO_DIR/scripts/validate-workflows.sh" "$WF_BAD" >/dev/null 2>&1 || WF_RC=$?
assert "validator rejects a duplicate-key workflow (exit 1)" "[[ '$WF_RC' == '1' ]]"
assert "validator names the duplicated trigger" \
  "echo \"\$WF_OUT\" | grep -q 'duplicate keys: on.pull_request'"

# ── Capability registry (T1.1) ──────────────────────────────
echo "--- capability registry ---"
CAP_DIR="$REPO_DIR/shared/capabilities"
assert "capability schema exists" "[[ -f '$REPO_DIR/shared/schemas/capability.schema.json' ]]"
assert "capability schema is valid JSON" \
  "ruby -rjson -e 'JSON.parse(File.read(ARGV[0]))' '$REPO_DIR/shared/schemas/capability.schema.json' 2>/dev/null"
for f in catalog pi claude-code; do
  assert "capability file $f.yaml exists" "[[ -f '$CAP_DIR/$f.yaml' ]]"
done
assert "capability registry validates" "bash '$REPO_DIR/scripts/validate-capabilities.sh' >/dev/null 2>&1"

# Negative fixtures: prove the validator still catches what it claims to.
# Without these, editing the validator could silently stop enforcing anything
# while the passing-direction assertion above stayed green.
BAD_FIXTURE="$REPO_DIR/tests/fixtures/capabilities-invalid"
BAD_OUT=$(bash "$REPO_DIR/scripts/validate-capabilities.sh" "$BAD_FIXTURE" 2>&1 || true)
BAD_RC=0
bash "$REPO_DIR/scripts/validate-capabilities.sh" "$BAD_FIXTURE" >/dev/null 2>&1 || BAD_RC=$?
assert "validator rejects the invalid fixture (exit 1)" "[[ '$BAD_RC' == '1' ]]"
assert "validator catches an invented capability id" \
  "echo \"\$BAD_OUT\" | grep -q 'ids not in catalog: fixture.invented'"
assert "validator catches an unclassified catalog id" \
  "echo \"\$BAD_OUT\" | grep -q 'catalog ids not classified: fixture.beta'"
assert "validator catches a bad implementation_kind" \
  "echo \"\$BAD_OUT\" | grep -q 'bad implementation_kind'"
assert "validator catches a non-enabled status with no reason" \
  "echo \"\$BAD_OUT\" | grep -q 'requires a reason'"

# The runtime carries its own seed; it must agree with pi.yaml or `features`
# and the generated parity report would disagree about the same capability.
if command -v ruby >/dev/null 2>&1; then
  DRIFT=$(ruby -ryaml -e '
    doc = YAML.load_file(ARGV[0])
    src = File.read(ARGV[1])
    problems = []
    yaml_ids = doc["capabilities"].map { |c| c["id"] }
    ts_ids = src.scan(/id: "([a-z0-9.\-]+)"/).flatten.uniq
    (yaml_ids - ts_ids).each { |i| problems << "missing from runtime: #{i}" }
    (ts_ids - yaml_ids).each { |i| problems << "missing from pi.yaml: #{i}" }
    doc["capabilities"].each do |c|
      idx = src.index("id: \"#{c["id"]}\"")
      next unless idx
      window = src[idx, 320].to_s
      unless window.include?("runtime_status: \"#{c["runtime_status"]}\"")
        problems << "status drift: #{c["id"]} (pi.yaml says #{c["runtime_status"]})"
      end
      unless window.include?("implementation_kind: \"#{c["implementation_kind"]}\"")
        problems << "kind drift: #{c["id"]} (pi.yaml says #{c["implementation_kind"]})"
      end
    end
    print problems.join("; ")
  ' "$CAP_DIR/pi.yaml" "$PI_DIR/runtime/capabilities.ts")
  assert "runtime capability seed matches pi.yaml${DRIFT:+ — $DRIFT}" "[[ -z '$DRIFT' ]]"

  # The guard must be able to fail: run it against a deliberately drifted copy.
  DRIFTED="$TMP/pi-drifted.yaml"
  sed 's/^    runtime_status: enabled$/    runtime_status: degraded/' "$CAP_DIR/pi.yaml" > "$DRIFTED"
  PLANTED=$(ruby -ryaml -e '
    doc = YAML.load_file(ARGV[0]); src = File.read(ARGV[1]); n = 0
    doc["capabilities"].each do |c|
      idx = src.index("id: \"#{c["id"]}\""); next unless idx
      n += 1 unless src[idx, 320].to_s.include?("runtime_status: \"#{c["runtime_status"]}\"")
    end
    print n
  ' "$DRIFTED" "$PI_DIR/runtime/capabilities.ts")
  assert "drift guard fires on planted drift ($PLANTED detected)" "[[ '$PLANTED' -gt 0 ]]"
else
  echo "  SKIP: capability drift guard — ruby not found"
  if [[ -n "${CI:-}" ]]; then
    echo "  FAIL: ruby is required in CI; the drift guard must run"
    FAIL=$((FAIL + 1))
  fi
fi

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  Pi adapter tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
