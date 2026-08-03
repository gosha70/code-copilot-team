#!/usr/bin/env bash

# test-pi-launcher.sh — Tests for the pi-code launcher contract
#
# Covers (specs/pi-harness-adoption FR-000/FR-002):
#   - upstream pi resolution + version validation (>= 0.79.0)
#   - argument forwarding (unknown flags and everything after --)
#   - --no-cct starts plain pi (no runtime, no CCT_RUNTIME marker)
#   - enforced launch loads runtime via --extension with CCT_RUNTIME=1
#   - recursion guard (CCT_PI_CODE_ACTIVE)
#   - exit-code preservation
#
# Uses a fake `pi` shim; no real Pi installation required.
#
# Run from the repo root:
#   bash tests/test-pi-launcher.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCHER="$REPO_DIR/adapters/pi/bin/pi-code"

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

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# ── Fake pi shim: records argv + relevant env, honors --version ─────
make_shim() {
  local dir="$1" version="$2"
  mkdir -p "$dir"
  cat > "$dir/pi" <<SHIM
#!/usr/bin/env bash
if [[ "\${1:-}" == "--version" ]]; then echo "$version"; exit 0; fi
{
  echo "ARGS:\$*"
  echo "CCT_RUNTIME:\${CCT_RUNTIME:-unset}"
  echo "CCT_PI_CODE_ACTIVE:\${CCT_PI_CODE_ACTIVE:-unset}"
  echo "CCT_PROFILE:\${CCT_PROFILE:-unset}"
  echo "CCT_PI_MODE:\${CCT_PI_MODE:-unset}"
  echo "CCT_PEER_REVIEW_ENABLED:\${CCT_PEER_REVIEW_ENABLED:-unset}"
  echo "CCT_PEER_PROVIDER:\${CCT_PEER_PROVIDER:-unset}"
  echo "CCT_PEER_REVIEW_SCOPE:\${CCT_PEER_REVIEW_SCOPE:-unset}"
} > "$TMP/capture.txt"
exit \${PI_SHIM_EXIT:-0}
SHIM
  chmod +x "$dir/pi"
}

make_shim "$TMP/bin-new" "0.80.2"
make_shim "$TMP/bin-old" "0.50.0"
BASE_PATH="/usr/bin:/bin"

echo "=== pi-code launcher tests ==="

# ── version / doctor without pi ─────────────────────────────
echo "--- diagnostics ---"
OUT=$(PATH="$BASE_PATH" "$LAUNCHER" version)
assert "version works without pi on PATH" "echo \"\$OUT\" | grep -q 'pi-code'"
assert "version reports minimum pi" "echo \"\$OUT\" | grep -q '0.79.0'"
if PATH="$BASE_PATH" "$LAUNCHER" doctor > "$TMP/doctor.txt" 2>&1; then
  assert "doctor fails without pi" "false"
else
  assert "doctor fails without pi" "true"
fi
assert "doctor names the missing pi" "grep -q 'upstream pi not found' '$TMP/doctor.txt'"

# ── enforced launch ─────────────────────────────────────────
echo "--- enforced launch ---"
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --profile review-heavy -- --model test/model > /dev/null 2>&1 || true
assert "runtime loaded via --extension" "grep -q -- '--extension' '$TMP/capture.txt'"
assert "runtime entry is runtime/index.ts" "grep -q 'runtime/index.ts' '$TMP/capture.txt'"
assert "CCT_RUNTIME=1 set on enforced launch" "grep -q 'CCT_RUNTIME:1' '$TMP/capture.txt'"
assert "recursion marker set" "grep -q 'CCT_PI_CODE_ACTIVE:1' '$TMP/capture.txt'"
assert "profile forwarded to runtime env" "grep -q 'CCT_PROFILE:review-heavy' '$TMP/capture.txt'"
assert "native args after -- forwarded unmodified" "grep -q -- '--model test/model' '$TMP/capture.txt'"

# Unknown flags forward to pi
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --thinking high > /dev/null 2>&1 || true
assert "unknown flag forwarded to pi" "grep -q -- '--thinking high' '$TMP/capture.txt'"

# ── --no-cct ────────────────────────────────────────────────
echo "--- --no-cct ---"
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --no-cct -- -p "hello" > /dev/null 2>&1 || true
assert "--no-cct: no runtime extension" "! grep -q -- '--extension' '$TMP/capture.txt'"
assert "--no-cct: CCT_RUNTIME unset" "grep -q 'CCT_RUNTIME:unset' '$TMP/capture.txt'"
assert "--no-cct: args still forwarded" "grep -q -- '-p hello' '$TMP/capture.txt'"
NOCCT_WARN=$(PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --no-cct 2>&1 >/dev/null || true)
assert "--no-cct visibly reported as unenforced" "echo \"\$NOCCT_WARN\" | grep -qi 'UNENFORCED'"

# ── version gate ────────────────────────────────────────────
echo "--- version gate ---"
if PATH="$TMP/bin-old:$BASE_PATH" "$LAUNCHER" > /dev/null 2>&1; then
  assert "pi older than 0.79.0 rejected" "false"
else
  RC=$?
  assert "pi older than 0.79.0 rejected" "true"
fi
PATH="$TMP/bin-old:$BASE_PATH" "$LAUNCHER" > /dev/null 2>&1 || RC=$?
assert "old-pi rejection uses exit 65" "[[ '${RC:-0}' == '65' ]]"

# ── recursion guard ─────────────────────────────────────────
echo "--- recursion guard ---"
if CCT_PI_CODE_ACTIVE=1 PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" > /dev/null 2>&1; then
  assert "recursive invocation blocked" "false"
else
  RC=$?
  assert "recursive invocation blocked" "true"
fi
assert "recursion block uses exit 64" "[[ '${RC:-0}' == '64' ]]"
OUT=$(CCT_PI_CODE_ACTIVE=1 PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" version)
assert "diagnostic commands allowed under recursion guard" "echo \"\$OUT\" | grep -q 'pi-code'"

# ── Pi invocation mode → CCT_PI_MODE (T5.4) ─────────────────
# The launcher derives the mode from forwarded flags and exports CCT_PI_MODE,
# which the runtime uses as the authoritative audit label. One case per form.
echo "--- pi mode detection ---"
mode_case() { # $1=passthrough-args  $2=expected-mode
  rm -f "$TMP/capture.txt"
  # shellcheck disable=SC2086
  PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" -- $1 > /dev/null 2>&1 || true
  assert "CCT_PI_MODE=$2 for [pi $1]" "grep -q 'CCT_PI_MODE:$2' '$TMP/capture.txt'"
}
mode_case ""                 tui
mode_case "-p"               print
mode_case "--print"          print
mode_case "--mode json"      json
mode_case "--mode=json"      json
mode_case "--mode rpc"       rpc
mode_case "--mode=rpc"       rpc
mode_case "--mode print"     print
mode_case "chat --mode json" json
mode_case "--thinking high"  tui

# ── Peer-review launcher flags → CCT_PEER_* (T6.3, FR-000a) ──
echo "--- peer-review flags ---"
peer_run() { rm -f "$TMP/capture.txt"; PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" "$@" > /dev/null 2>&1 || true; }

peer_run --peer-review
assert "peer: --peer-review sets ENABLED=true" "grep -q 'CCT_PEER_REVIEW_ENABLED:true' '$TMP/capture.txt'"
assert "peer: no provider -> unset" "grep -q 'CCT_PEER_PROVIDER:unset' '$TMP/capture.txt'"
assert "peer: default scope both" "grep -q 'CCT_PEER_REVIEW_SCOPE:both' '$TMP/capture.txt'"

peer_run --peer-review codex
assert "peer: spaced provider consumed" "grep -q 'CCT_PEER_PROVIDER:codex' '$TMP/capture.txt'"

peer_run --peer-review=gemini
assert "peer: equals provider consumed" "grep -q 'CCT_PEER_PROVIDER:gemini' '$TMP/capture.txt'"

peer_run --peer-review --profile ci
assert "peer: following flag NOT eaten as provider" "grep -q 'CCT_PEER_PROVIDER:unset' '$TMP/capture.txt'"
assert "peer: --profile still applies after --peer-review" "grep -q 'CCT_PROFILE:ci' '$TMP/capture.txt'"

peer_run --peer-review-off
assert "peer: --peer-review-off sets ENABLED=false" "grep -q 'CCT_PEER_REVIEW_ENABLED:false' '$TMP/capture.txt'"
assert "peer: off exports no scope" "grep -q 'CCT_PEER_REVIEW_SCOPE:unset' '$TMP/capture.txt'"

peer_run --peer-review --peer-review-scope code
assert "peer: scope spaced=code" "grep -q 'CCT_PEER_REVIEW_SCOPE:code' '$TMP/capture.txt'"
peer_run --peer-review --peer-review-scope=design
assert "peer: scope equals=design" "grep -q 'CCT_PEER_REVIEW_SCOPE:design' '$TMP/capture.txt'"

rm -f "$TMP/capture.txt"
SCOPE_ERR=$(PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --peer-review --peer-review-scope bogus 2>&1 >/dev/null || true)
assert "peer: invalid scope rejected with error" "echo \"$SCOPE_ERR\" | grep -qF 'code|design|both'"
assert "peer: invalid scope did not launch pi" "! test -f '$TMP/capture.txt'"

peer_run --profile ci
assert "peer: no flags -> ENABLED unset" "grep -q 'CCT_PEER_REVIEW_ENABLED:unset' '$TMP/capture.txt'"

peer_run --no-cct --peer-review codex
assert "peer: --no-cct carries no peer env" "grep -q 'CCT_PEER_REVIEW_ENABLED:unset' '$TMP/capture.txt'"

peer_run --thinking high
assert "peer: unknown flag still forwarded" "grep -q -- '--thinking high' '$TMP/capture.txt'"

# ── no passthrough args ─────────────────────────────────────
# bash 3.2 (macOS /bin/bash) errors on "${a[@]}" for an empty array under
# `set -u`, which broke the default launch path with no extra arguments.
echo "--- no passthrough args ---"
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" > /dev/null 2>&1 || true
assert "enforced launch execs pi with no args" "grep -q 'CCT_RUNTIME:1' '$TMP/capture.txt'"
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --no-cct > /dev/null 2>&1 || true
assert "--no-cct execs pi with no args" "grep -q 'CCT_RUNTIME:unset' '$TMP/capture.txt'"

# ── exit-code preservation ──────────────────────────────────
echo "--- exit codes ---"
if PI_SHIM_EXIT=7 PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" --no-cct > /dev/null 2>&1; then
  RC=0
else
  RC=$?
fi
assert "pi exit code preserved through exec" "[[ '$RC' == '7' ]]"

# ── Diagnostic subcommands (T1.6) ───────────────────────────
echo "--- diagnostics ---"
# The diagnostic subcommands shell out to node; BASE_PATH deliberately does
# not contain it, so add its real location for these cases only.
NODE_DIR="$(dirname "$(command -v node 2>/dev/null || echo /usr/bin/node)")"
DIAG_PATH="$TMP/bin-new:$NODE_DIR:$BASE_PATH"

for cmd in features config; do
  OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" "$cmd" 2>&1 || true)
  assert "$cmd produces output" "[[ -n \"\$OUT\" ]]"
done

OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" features 2>&1 || true)
assert "features reports capability status" "echo \"\$OUT\" | grep -q 'enabled'"
assert "features reports implementation kind" "echo \"\$OUT\" | grep -q 'cct-first-party'"

OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" config 2>&1 || true)
assert "config reports resolved keys" "echo \"\$OUT\" | grep -q 'security.fail_closed'"
# Diagnostics must never imply project config was trusted (C-3).
assert "config states the untrusted resolution" "echo \"\$OUT\" | grep -q 'UNTRUSTED'"

OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" config explain security.fail_closed 2>&1 || true)
assert "explain shows the setting layer" "echo \"\$OUT\" | grep -q 'set by:'"

RC=0
PATH="$DIAG_PATH" "$LAUNCHER" config explain no.such.key > /dev/null 2>&1 || RC=$?
assert "explain exits 1 for an unknown key" "[[ '$RC' == '1' ]]"

# Sensitive values must be redacted on EVERY surface. --json once leaked the
# raw value while the text path redacted it — this output is pasted into issues.
mkdir -p "$TMP/cct-home"
printf 'config_version = 2\n[providers]\napi_key = "sk-cct-test-secret"\n' > "$TMP/cct-home/config.toml"
for extra in "" "--json"; do
  OUT=$(CCT_HOME="$TMP/cct-home" PATH="$DIAG_PATH" "$LAUNCHER" config explain providers.api_key $extra 2>&1 || true)
  assert "explain${extra:+ $extra} redacts a sensitive value" \
    "! echo \"\$OUT\" | grep -q 'sk-cct-test-secret' && echo \"\$OUT\" | grep -q 'redacted'"
done

# Sweep every surface, not only the two that leaked. A surface added later
# is covered by this loop the moment it is listed.
SURFACES=(
  "config"
  "config --json"
  "doctor"
  "doctor --json"
  "features"
  "features --json"
  "config explain providers.api_key"
  "config explain providers.api_key --json"
  "export"
  "export --json"
  "resources"
  "resources --json"
  "provenance"
  "provenance --json"
)
for surface in "${SURFACES[@]}"; do
  # shellcheck disable=SC2086
  OUT=$(CCT_HOME="$TMP/cct-home" PATH="$DIAG_PATH" "$LAUNCHER" $surface 2>&1 || true)
  assert "no secret leaks via: pi-code $surface" \
    "! echo \"\$OUT\" | grep -q 'sk-cct-test-secret'"
done

for cmd in features doctor config provenance; do
  OUT=$(PATH="$DIAG_PATH" "$LAUNCHER" "$cmd" --json 2>&1 || true)
  assert "$cmd --json emits valid JSON" \
    "echo \"\$OUT\" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null"
done

# Diagnostics stay usable inside a session; only launches recurse.
OUT=$(CCT_PI_CODE_ACTIVE=1 PATH="$DIAG_PATH" "$LAUNCHER" features 2>&1 || true)
assert "recursion guard permits diagnostics" "echo \"\$OUT\" | grep -q 'capabilities'"

assert "help documents the diagnostic commands" \
  "PATH=\"\$DIAG_PATH\" '$LAUNCHER' help | grep -q 'config explain'"
assert "help documents the provenance command" \
  "PATH=\"\$DIAG_PATH\" '$LAUNCHER' help | grep -q 'provenance'"

# ── Redacted export (T1.8) ──────────────────────────────────
echo "--- export ---"
EXP_HOME="$TMP/exp-home"
mkdir -p "$EXP_HOME"
printf 'config_version = 2\n[security]\nfail_closed = true\n[providers]\napi_key = "sk-export-secret"\n' > "$EXP_HOME/config.toml"

EXP=$(CCT_HOME="$EXP_HOME" PATH="$DIAG_PATH" "$LAUNCHER" export 2>&1 || true)
assert "export marks output as redacted" "echo \"\$EXP\" | grep -q 'redacted'"
assert "export never emits the raw secret" "! echo \"\$EXP\" | grep -q 'sk-export-secret'"
assert "export includes a resolved key" "echo \"\$EXP\" | grep -q 'security.fail_closed'"

# The exported TOML must re-parse — it claims to be a portable artifact.
echo "$EXP" > "$TMP/exported.toml"
assert "exported TOML re-parses through the loader" \
  "CCT_CFG='$TMP/exported.toml' node --experimental-strip-types --input-type=module -e 'import fs from \"node:fs\"; import { parseToml } from \"$REPO_DIR/adapters/pi/runtime/config/toml.ts\"; const t = parseToml(fs.readFileSync(process.env.CCT_CFG, \"utf8\")); process.exit(t.security && t.security.fail_closed === true ? 0 : 1);' 2>/dev/null"

EXPJ=$(CCT_HOME="$EXP_HOME" PATH="$DIAG_PATH" "$LAUNCHER" export --json 2>&1 || true)
assert "export --json never emits the raw secret" "! echo \"\$EXPJ\" | grep -q 'sk-export-secret'"
assert "export --json is valid JSON with redacted flag" \
  "echo \"\$EXPJ\" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get(\"redacted\") is True else 1)'"

# T2.5: resources reports provenance for skills and prompts.
RES_OUT=$(CCT_HOME="$EXP_HOME" PATH="$DIAG_PATH" "$LAUNCHER" resources 2>&1 || true)
assert "resources reports a skill source" "echo \"\$RES_OUT\" | grep -q 'shared/skills'"
assert "resources reports a prompt source" "echo \"\$RES_OUT\" | grep -q 'claude-code'"
RES_J=$(CCT_HOME="$EXP_HOME" PATH="$DIAG_PATH" "$LAUNCHER" resources --json 2>&1 || true)
assert "resources --json reports found:true" \
  "echo \"\$RES_J\" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get(\"found\") else 1)'"

# ── FU-2: provenance (FR-027) ───────────────────────────────
# A read-only report composing version + install identity + capability/trust.
# Fields the runtime cannot obtain (checksum, the full SBOM) MUST be reported
# absent-but-machine-readable (null / {available:false}), never fabricated.
echo "--- provenance ---"
PROV=$(PATH="$DIAG_PATH" "$LAUNCHER" provenance 2>&1 || true)
assert "provenance names the package + source" \
  "echo \"\$PROV\" | grep -q 'code-copilot-team-pi' && echo \"\$PROV\" | grep -q 'git:github.com/gosha70'"
assert "provenance summarizes capabilities with the authority" \
  "echo \"\$PROV\" | grep -q 'capabilities:' && echo \"\$PROV\" | grep -q 'COMPATIBILITY.md'"
assert "provenance reports checksum as not-available (honest)" \
  "echo \"\$PROV\" | grep -qi 'checksum' && echo \"\$PROV\" | grep -q 'not available at runtime'"
assert "provenance reports security classification with the authority (honest)" \
  "echo \"\$PROV\" | grep -qi 'security:' && echo \"\$PROV\" | grep -q 'COMPATIBILITY.md'"

PROV_J=$(PATH="$DIAG_PATH" "$LAUNCHER" provenance --json 2>&1 || true)
assert "provenance --json marks checksum null (absent, not fabricated)" \
  "echo \"\$PROV_J\" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"checksum\"] is None else 1)'"
assert "provenance --json marks the SBOM unavailable with a release pointer" \
  "echo \"\$PROV_J\" | python3 -c 'import json,sys; d=json.load(sys.stdin); s=d[\"sbom\"]; sys.exit(0 if s[\"available\"] is False and s[\"release_artifact\"]==\"adapters/pi/sbom.cdx.json\" else 1)'"
assert "provenance --json marks security classification unavailable with an authority pointer" \
  "echo \"\$PROV_J\" | python3 -c 'import json,sys; d=json.load(sys.stdin); s=d[\"security\"]; sys.exit(0 if s[\"available\"] is False and s[\"authority\"]==\"shared/capabilities/COMPATIBILITY.md\" else 1)'"
assert "provenance --json states runtime deps: none" \
  "echo \"\$PROV_J\" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"dependencies\"][\"runtime\"]==\"none\" else 1)'"

# The two public version surfaces must never drift: provenance reports the SAME
# version as `pi-code version` (both trace to the launcher's PI_CODE_VERSION).
V_VER=$(PATH="$DIAG_PATH" "$LAUNCHER" version 2>&1 | grep -oE 'pi-code [0-9]+\.[0-9]+\.[0-9]+' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
P_VER=$(echo "$PROV_J" | python3 -c 'import json,sys; print(json.load(sys.stdin)["package"]["version"])')
assert "provenance version matches the version command (no drift)" \
  "[[ -n '$V_VER' && '$V_VER' == '$P_VER' ]]"

# ── T6.4: init / sync (FR-000a) ─────────────────────────────
echo "--- init / sync ---"

INIT_DIR="$TMP/proj-init"; mkdir -p "$INIT_DIR"

# --dry-run is report-only: no writes.
DRY_OUT=$(PATH="$BASE_PATH" "$LAUNCHER" init "$INIT_DIR" --dry-run 2>&1 || true)
assert "init --dry-run reports report-only" "echo \"\$DRY_OUT\" | grep -q 'no writes'"
assert "init --dry-run writes nothing" "[[ -z \"\$(ls -A '$INIT_DIR')\" ]]"

# Real init scaffolds ONLY the Pi-native footprint (config.toml + manifest).
PATH="$BASE_PATH" "$LAUNCHER" init "$INIT_DIR" --profile ci >/dev/null 2>&1
assert "init creates .code-copilot-team/config.toml" "[[ -f '$INIT_DIR/.code-copilot-team/config.toml' ]]"
assert "init creates the .cct-init.json manifest" "[[ -f '$INIT_DIR/.code-copilot-team/.cct-init.json' ]]"
assert "init emits no .claude/ (Pi-native only)" "[[ ! -e '$INIT_DIR/.claude' && ! -e '$INIT_DIR/CLAUDE.md' ]]"
assert "init --profile seeds the profile" "grep -q 'profile = \"ci\"' '$INIT_DIR/.code-copilot-team/config.toml'"
assert "manifest marks config.toml as user-config" "grep -q '\"kind\": \"user-config\"' '$INIT_DIR/.code-copilot-team/.cct-init.json'"

# Ownership proof: the manifest hash matches the generated config's content.
MANI_HASH=$(grep '"hash"' "$INIT_DIR/.code-copilot-team/.cct-init.json" | grep -oE '[0-9a-f]{32,}')
CFG_HASH=$(shasum -a 256 "$INIT_DIR/.code-copilot-team/config.toml" | awk '{print $1}')
assert "manifest hash matches config.toml content" "[[ -n '$MANI_HASH' && '$MANI_HASH' == '$CFG_HASH' ]]"

# No-clobber: re-init preserves a user-edited config and reports it, exit 0.
echo "# user edit" >> "$INIT_DIR/.code-copilot-team/config.toml"
BEFORE=$(shasum -a 256 "$INIT_DIR/.code-copilot-team/config.toml" | awk '{print $1}')
RC=0; RE_OUT=$(PATH="$BASE_PATH" "$LAUNCHER" init "$INIT_DIR" 2>&1) || RC=$?
AFTER=$(shasum -a 256 "$INIT_DIR/.code-copilot-team/config.toml" | awk '{print $1}')
assert "re-init preserves edited config (no clobber)" "[[ '$BEFORE' == '$AFTER' ]]"
assert "re-init reports already-initialized" "echo \"\$RE_OUT\" | grep -qi 'already initialized'"
assert "re-init exits 0" "[[ '$RC' == '0' ]]"

RC=0; PATH="$BASE_PATH" "$LAUNCHER" init "$INIT_DIR" --bogus >/dev/null 2>&1 || RC=$?
assert "init rejects an unknown option (exit 2)" "[[ '$RC' == '2' ]]"

# sync --dry-run against a fake repo: report-only, no staging, names the contract.
FAKE="$TMP/fakerepo"; mkdir -p "$FAKE/scripts" "$FAKE/adapters/pi"
: > "$FAKE/scripts/generate.sh"; : > "$FAKE/adapters/pi/setup.sh"
SYNC_OUT=$(CCT_REPO_DIR="$FAKE" PATH="$BASE_PATH" "$LAUNCHER" sync --dry-run 2>&1 || true)
assert "sync --dry-run is report-only (no staging)" "echo \"\$SYNC_OUT\" | grep -q 'no staging'"
assert "sync --dry-run names setup.sh --sync" "echo \"\$SYNC_OUT\" | grep -q 'setup.sh --sync'"

RC=0; PATH="$BASE_PATH" "$LAUNCHER" sync --bogus >/dev/null 2>&1 || RC=$?
assert "sync rejects an unknown option (exit 2)" "[[ '$RC' == '2' ]]"
RC=0; PATH="$BASE_PATH" "$LAUNCHER" sync extra >/dev/null 2>&1 || RC=$?
assert "sync rejects a positional arg (exit 2)" "[[ '$RC' == '2' ]]"

# sync from an isolated location with no repo -> honest exit 78 (not a silent no-op).
ISO="$TMP/iso"; mkdir -p "$ISO"; cp "$LAUNCHER" "$ISO/pi-code"; chmod +x "$ISO/pi-code"
RC=0; CCT_REPO_DIR=/nonexistent PATH="$BASE_PATH" "$ISO/pi-code" sync --dry-run >/dev/null 2>&1 || RC=$?
assert "sync without a repo fails with exit 78" "[[ '$RC' == '78' ]]"

# init/sync are exempt from the recursion guard (they never re-enter pi).
mkdir -p "$TMP/proj2"
RC=0; CCT_PI_CODE_ACTIVE=1 PATH="$BASE_PATH" "$LAUNCHER" init "$TMP/proj2" --dry-run >/dev/null 2>&1 || RC=$?
assert "init allowed under the recursion guard" "[[ '$RC' == '0' ]]"

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "========================================="
echo "  pi-code launcher tests: $PASS passed, $FAIL failed"
echo "========================================="
[[ $FAIL -eq 0 ]]
