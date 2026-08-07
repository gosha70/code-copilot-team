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
  echo "PWD:\$PWD"
  echo "CCT_WORKER_ID:\${CCT_WORKER_ID:-unset}"
  echo "CCT_RUNTIME:\${CCT_RUNTIME:-unset}"
  echo "CCT_PI_CODE_ACTIVE:\${CCT_PI_CODE_ACTIVE:-unset}"
  echo "CCT_PROFILE:\${CCT_PROFILE:-unset}"
  echo "CCT_PI_MODE:\${CCT_PI_MODE:-unset}"
  echo "CCT_PEER_REVIEW_ENABLED:\${CCT_PEER_REVIEW_ENABLED:-unset}"
  echo "CCT_PEER_PROVIDER:\${CCT_PEER_PROVIDER:-unset}"
  echo "CCT_PEER_REVIEW_SCOPE:\${CCT_PEER_REVIEW_SCOPE:-unset}"
  echo "GITHUB_TOKEN:\${GITHUB_TOKEN:-unset}"
  echo "CCT_ENV_SCRUBBED:\${CCT_ENV_SCRUBBED:-unset}"
  echo "CCT_ENV_SCRUB_OFF:\${CCT_ENV_SCRUB_OFF:-unset}"
  echo "DASH_TOKEN_COUNT:\$(env | grep -c '^my-app_TOKEN=')"
  echo "CCT_CONFIG_API_KEY:\${CCT_CONFIG__providers__api_key:-unset}"
  echo "CCT_CLI_SETS:\${CCT_CLI_SETS:-unset}"
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
  "continuity"
  "continuity --json"
)
for surface in "${SURFACES[@]}"; do
  # shellcheck disable=SC2086
  OUT=$(CCT_HOME="$TMP/cct-home" PATH="$DIAG_PATH" "$LAUNCHER" $surface 2>&1 || true)
  assert "no secret leaks via: pi-code $surface" \
    "! echo \"\$OUT\" | grep -q 'sk-cct-test-secret'"
done

for cmd in features doctor config provenance continuity; do
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

# ── US3: continuity + unattended posture (FR-9/10/13/22) ────
echo "--- continuity + unattended ---"
CONT=$(PATH="$DIAG_PATH" "$LAUNCHER" continuity 2>&1 || true)
assert "continuity lists the three durable sources" \
  "echo \"\$CONT\" | grep -q 'tasks:' && echo \"\$CONT\" | grep -q 'checkpoint:' && echo \"\$CONT\" | grep -q 'auto-build-ledger:'"
assert "continuity reports Pi compaction as degraded (no native overclaim)" \
  "echo \"\$CONT\" | grep -q 'compaction: degraded' && echo \"\$CONT\" | grep -qi 'no PreCompact'"

CONT_J=$(PATH="$DIAG_PATH" "$LAUNCHER" continuity --json 2>&1 || true)
assert "continuity --json marks compaction native=false (FR-10)" \
  "echo \"\$CONT_J\" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"compaction\"][\"native\"] is False else 1)'"
assert "continuity --json reports each source with an explicit status (FR-13)" \
  "echo \"\$CONT_J\" | python3 -c 'import json,sys; d=json.load(sys.stdin); ok={\"present\",\"missing\",\"corrupt\"}; sys.exit(0 if all(s[\"status\"] in ok for s in d[\"sources\"]) else 1)'"

# doctor surfaces the unattended posture + cooldown-resume status (FR-22).
DOC_J=$(PATH="$DIAG_PATH" "$LAUNCHER" doctor --json 2>&1 || true)
assert "doctor --json reports the unattended posture" \
  "echo \"\$DOC_J\" | python3 -c 'import json,sys; d=json.load(sys.stdin); u=d[\"unattended\"]; sys.exit(0 if u[\"posture\"] in (\"active\",\"available\") and u[\"cooldown_resume\"] in (\"available\",\"unavailable\") else 1)'"

assert "help documents the continuity command" \
  "PATH=\"\$DIAG_PATH\" '$LAUNCHER' help | grep -q 'continuity'"

# ── #172: worktree provisioning subcommand ──────────────────
assert "help documents the worktree command" \
  "PATH=\"\$DIAG_PATH\" '$LAUNCHER' help | grep -q 'worktree create'"

# `worktree` (no subcommand) must ROUTE to the runtime CLI (not the recursion
# guard / pi launch) and print usage with exit 64. An empty CCT_HOME forces
# the repo runtime fallback (managed install may be stale).
WT_HOME="$TMP/wt-home"; mkdir -p "$WT_HOME"
WT_RC=0
WT_OUT=$(CCT_HOME="$WT_HOME" PATH="$DIAG_PATH" "$LAUNCHER" worktree 2>&1) || WT_RC=$?
assert "worktree routes to the runtime CLI (usage shown)" \
  "echo \"\$WT_OUT\" | grep -q 'worktree create'"
assert "worktree with no subcommand exits 64" "[ \"\$WT_RC\" -eq 64 ]"
WT_G_OUT=$(CCT_PI_CODE_ACTIVE=1 CCT_HOME="$WT_HOME" PATH="$DIAG_PATH" "$LAUNCHER" worktree 2>&1) || true
assert "worktree allowed under the recursion guard" \
  "echo \"\$WT_G_OUT\" | grep -q 'worktree create'"

# `worktree run` provisions AND launches pi INSIDE the worktree (process
# boundary). A fake `pi` shim (bin-new, on DIAG_PATH) records its own PWD and
# CCT_WORKER_ID to capture.txt.
if command -v git >/dev/null 2>&1; then
  WR_REPO="$TMP/wr-repo"; mkdir -p "$WR_REPO"
  git -C "$WR_REPO" init -q -b master
  git -C "$WR_REPO" config user.email t@e.com
  git -C "$WR_REPO" config user.name T
  echo seed > "$WR_REPO/README.md"; git -C "$WR_REPO" add -A; git -C "$WR_REPO" commit -q -m seed
  rm -f "$TMP/capture.txt"
  ( cd "$WR_REPO" && CCT_HOME="$TMP/wr-home" PATH="$DIAG_PATH" "$LAUNCHER" worktree run fix-9 --branch fix/nine ) >/dev/null 2>&1 || true
  WR_WT="$(cd "$(dirname "$WR_REPO")/.cct-worktrees/wr-repo/fix-9" 2>/dev/null && pwd -P || echo MISSING)"
  assert "worktree run launches pi INSIDE the worktree" \
    "test -f \"\$TMP/capture.txt\" && grep -q \"PWD:\$WR_WT\" \"\$TMP/capture.txt\""
  assert "worktree run exports CCT_WORKER_ID to the child" \
    "grep -q 'CCT_WORKER_ID:fix-9' \"\$TMP/capture.txt\""
  assert "worktree run wrote the record to the PRIMARY ledger" \
    "grep -q '\"workerId\": \"fix-9\"' \"\$WR_REPO/.cct/worktrees.json\""

  # A controller (an active pi session) sets CCT_PI_CODE_ACTIVE=1. `worktree run`
  # must still hand off and launch the worker — the recursion guard permits this
  # intentional child, not the accidental runtime-stacking it defends against.
  WR_REPO2="$TMP/wr-repo2"; mkdir -p "$WR_REPO2"
  git -C "$WR_REPO2" init -q -b master
  git -C "$WR_REPO2" config user.email t@e.com
  git -C "$WR_REPO2" config user.name T
  echo seed > "$WR_REPO2/README.md"; git -C "$WR_REPO2" add -A; git -C "$WR_REPO2" commit -q -m seed
  rm -f "$TMP/capture.txt"
  ( cd "$WR_REPO2" && CCT_PI_CODE_ACTIVE=1 CCT_HOME="$TMP/wr-home2" PATH="$DIAG_PATH" "$LAUNCHER" worktree run ctl-1 --branch feature/ctl-1 ) >/dev/null 2>&1 || true
  WR_WT2="$(cd "$(dirname "$WR_REPO2")/.cct-worktrees/wr-repo2/ctl-1" 2>/dev/null && pwd -P || echo MISSING)"
  assert "worktree run launches the worker even under an active controller (CCT_PI_CODE_ACTIVE=1)" \
    "test -f \"\$TMP/capture.txt\" && grep -q \"PWD:\$WR_WT2\" \"\$TMP/capture.txt\""
  assert "worktree run under a controller still exports CCT_WORKER_ID" \
    "grep -q 'CCT_WORKER_ID:ctl-1' \"\$TMP/capture.txt\""

  # SECURITY: forwarded args must NOT be able to escape the worktree or disable
  # enforcement. `-- --project <primary>` / `--no-cct` are rejected before
  # provisioning (no orphan) and the worker never launches in the primary.
  PRIMARY_ESC="$TMP/primary-escape"; mkdir -p "$PRIMARY_ESC"
  rm -f "$TMP/capture.txt"
  ESC_RC=0
  ( cd "$WR_REPO2" && CCT_HOME="$TMP/wr-home2" PATH="$DIAG_PATH" "$LAUNCHER" worktree run esc-1 --branch feature/esc-1 -- --project "$PRIMARY_ESC" ) >/dev/null 2>&1 || ESC_RC=$?
  assert "worktree run rejects a forwarded --project (isolation escape)" "[ \"\$ESC_RC\" -ne 0 ]"
  assert "rejected --project escape launches NOTHING (no capture)" "[ ! -f \"\$TMP/capture.txt\" ]"
  assert "rejected --project escape leaves NO orphan ledger record" \
    "! grep -q 'esc-1' \"\$WR_REPO2/.cct/worktrees.json\" 2>/dev/null"
  # Pre-provision rejection means NO git side effects at all: no worktree dir…
  assert "rejected --project escape created NO worktree directory" \
    "test ! -e \"\$(dirname \"\$WR_REPO2\")/.cct-worktrees/wr-repo2/esc-1\""
  # …and no branch.
  assert "rejected --project escape created NO git branch" \
    "! git -C \"\$WR_REPO2\" show-ref --verify --quiet refs/heads/feature/esc-1"

  ESC2_RC=0
  ( cd "$WR_REPO2" && CCT_HOME="$TMP/wr-home2" PATH="$DIAG_PATH" "$LAUNCHER" worktree run esc-2 --branch feature/esc-2 -- --project "$PRIMARY_ESC" --no-cct ) >/dev/null 2>&1 || ESC2_RC=$?
  assert "worktree run rejects forwarded --project + --no-cct" "[ \"\$ESC2_RC\" -ne 0 ]"

  # Defense-2 backstop, exercised directly: a locked-project handoff refuses a
  # mismatched --project / --no-cct even entering the public parser.
  D2_RC=0
  ( cd "$WR_REPO2" && CCT_HOME="$TMP/wr-home2" PATH="$DIAG_PATH" CCT_LOCKED_PROJECT_PATH="$WR_WT2" "$LAUNCHER" --project "$PRIMARY_ESC" ) >/dev/null 2>&1 || D2_RC=$?
  assert "locked-project backstop refuses a mismatched --project" "[ \"\$D2_RC\" -ne 0 ]"
  D3_RC=0
  ( cd "$WR_REPO2" && CCT_HOME="$TMP/wr-home2" PATH="$DIAG_PATH" CCT_LOCKED_PROJECT_PATH="$WR_WT2" "$LAUNCHER" --no-cct --project "$WR_WT2" ) >/dev/null 2>&1 || D3_RC=$?
  assert "locked-project backstop refuses --no-cct" "[ \"\$D3_RC\" -ne 0 ]"
else
  echo "  SKIP: worktree run (git unavailable)"
fi

# ── #173: env scrubbing at the worktree-run handoff (pi-sandbox-hardening) ───
assert "help documents env scrub-list" \
  "PATH=\"\$DIAG_PATH\" '$LAUNCHER' help | grep -q 'env scrub-list'"

# `env scrub-list` routes to the runtime CLI and reports a credential-shaped
# var from its own environment; allowed under the recursion guard.
ES_HOME="$TMP/es-home"; mkdir -p "$ES_HOME"
ES_OUT=$(GITHUB_TOKEN=leakme CCT_HOME="$ES_HOME" PATH="$DIAG_PATH" "$LAUNCHER" env scrub-list 2>&1) || true
assert "env scrub-list reports a credential-shaped name" \
  "echo \"\$ES_OUT\" | grep -q '^GITHUB_TOKEN\$'"
ES_G_OUT=$(GITHUB_TOKEN=leakme CCT_PI_CODE_ACTIVE=1 CCT_HOME="$ES_HOME" PATH="$DIAG_PATH" "$LAUNCHER" env scrub-list 2>&1) || true
assert "env scrub-list allowed under the recursion guard" \
  "echo \"\$ES_G_OUT\" | grep -q '^GITHUB_TOKEN\$'"

if command -v git >/dev/null 2>&1; then
  # Default-ON: the worker pi must NOT see the credential; the scrubbed NAMES
  # ride in CCT_ENV_SCRUBBED; the CCT_WORKER_* contract survives (keep-listed).
  ES_REPO="$TMP/es-repo"; mkdir -p "$ES_REPO"
  git -C "$ES_REPO" init -q -b master
  git -C "$ES_REPO" config user.email t@e.com
  git -C "$ES_REPO" config user.name T
  echo seed > "$ES_REPO/README.md"; git -C "$ES_REPO" add -A; git -C "$ES_REPO" commit -q -m seed
  rm -f "$TMP/capture.txt"
  ( cd "$ES_REPO" && GITHUB_TOKEN=leakme CCT_CONFIG__providers__api_key=sk-leak CCT_CLI_SETS="providers.api_key=sk-cli" CCT_HOME="$TMP/es-home1" PATH="$DIAG_PATH" "$LAUNCHER" worktree run scrub-1 --branch feature/scrub-1 ) >/dev/null 2>&1 || true
  assert "worktree run scrubs the credential from the worker env" \
    "test -f \"\$TMP/capture.txt\" && grep -q 'GITHUB_TOKEN:unset' \"\$TMP/capture.txt\""
  assert "the CCT_CONFIG__* carrier namespace is scrubbed at the handoff" \
    "grep -q 'CCT_CONFIG_API_KEY:unset' \"\$TMP/capture.txt\""
  assert "the CCT_CLI_SETS carrier is scrubbed at the handoff" \
    "grep -q 'CCT_CLI_SETS:unset' \"\$TMP/capture.txt\""
  assert "worktree run reports scrubbed NAMES via CCT_ENV_SCRUBBED" \
    "grep 'CCT_ENV_SCRUBBED:' \"\$TMP/capture.txt\" | grep -q 'GITHUB_TOKEN'"
  assert "scrubbed handoff still exports CCT_WORKER_ID" \
    "grep -q 'CCT_WORKER_ID:scrub-1' \"\$TMP/capture.txt\""

  # Global (user-owned) opt-out restores pass-through — no CCT_ENV_SCRUBBED.
  ES_HOME2="$TMP/es-home2"; mkdir -p "$ES_HOME2"
  printf '[security]\nenv_scrub = false\n' > "$ES_HOME2/config.toml"
  rm -f "$TMP/capture.txt"
  ( cd "$ES_REPO" && GITHUB_TOKEN=leakme CCT_HOME="$ES_HOME2" PATH="$DIAG_PATH" "$LAUNCHER" worktree run scrub-2 --branch feature/scrub-2 ) >/dev/null 2>&1 || true
  assert "global env_scrub=false restores pass-through at the handoff" \
    "test -f \"\$TMP/capture.txt\" && grep -q 'GITHUB_TOKEN:leakme' \"\$TMP/capture.txt\""
  assert "pass-through handoff records the disabling layer (CCT_ENV_SCRUB_OFF)" \
    "grep -q 'CCT_ENV_SCRUB_OFF:global' \"\$TMP/capture.txt\""
  assert "pass-through handoff exports no CCT_ENV_SCRUBBED" \
    "grep -q 'CCT_ENV_SCRUBBED:unset' \"\$TMP/capture.txt\""

  # A repo-local opt-out (config.toml or the conventionally-gitignored
  # config.local.toml) must NOT loosen the launcher boundary: the untrusted
  # CLI never reads project layers, so scrubbing still happens.
  ES_REPO3="$TMP/es-repo3"; mkdir -p "$ES_REPO3/.code-copilot-team"
  git -C "$ES_REPO3" init -q -b master
  git -C "$ES_REPO3" config user.email t@e.com
  git -C "$ES_REPO3" config user.name T
  printf '[security]\nenv_scrub = false\n' > "$ES_REPO3/.code-copilot-team/config.toml"
  printf '[security]\nenv_scrub = false\n' > "$ES_REPO3/.code-copilot-team/config.local.toml"
  echo seed > "$ES_REPO3/README.md"; git -C "$ES_REPO3" add -A; git -C "$ES_REPO3" commit -q -m seed
  rm -f "$TMP/capture.txt"
  ( cd "$ES_REPO3" && GITHUB_TOKEN=leakme CCT_HOME="$TMP/es-home3" PATH="$DIAG_PATH" "$LAUNCHER" worktree run scrub-3 --branch feature/scrub-3 ) >/dev/null 2>&1 || true
  assert "repo-local env_scrub=false is IGNORED at the handoff (still scrubbed)" \
    "test -f \"\$TMP/capture.txt\" && grep -q 'GITHUB_TOKEN:unset' \"\$TMP/capture.txt\""
else
  echo "  SKIP: worktree-run scrub (git unavailable)"
fi

# The disabled marker is explicit (never confusable with a name).
ES_MARK=$(GITHUB_TOKEN=leakme CCT_CONFIG__security__env_scrub=false CCT_HOME="$ES_HOME" PATH="$DIAG_PATH" "$LAUNCHER" env scrub-list 2>&1) || true
assert "env scrub-list prints an explicit disabled marker with the layer" \
  "echo \"\$ES_MARK\" | grep -q '^=disabled=env\$'"

if command -v git >/dev/null 2>&1; then
  # Phase-2 review F1: a scrub-listed name that is NOT a shell identifier
  # (bash `unset` cannot remove it) must still be removed — env -u path.
  ES_LIST_DASH=$(env 'my-app_TOKEN=leakme' CCT_HOME="$TMP/es-home4" PATH="$DIAG_PATH" "$LAUNCHER" env scrub-list 2>&1) || true
  assert "scrub-list reports a non-identifier credential name" \
    "echo \"\$ES_LIST_DASH\" | grep -q '^my-app_TOKEN\$'"
  rm -f "$TMP/capture.txt"
  ( cd "$ES_REPO" && env 'my-app_TOKEN=leakme' CCT_HOME="$TMP/es-home4" PATH="$DIAG_PATH" "$LAUNCHER" worktree run scrub-4 --branch feature/scrub-4 ) >/dev/null 2>&1 || true
  assert "a non-identifier credential is ALSO removed from the worker env" \
    "test -f \"\$TMP/capture.txt\" && grep -q 'DASH_TOKEN_COUNT:0' \"\$TMP/capture.txt\""

  # Phase-2 review F2: scrub-list now resolves BEFORE provisioning, so a
  # scrub-list failure (NODE_OPTIONS breaks every node invocation; the
  # scrub-list call is the first) refuses the handoff with NO git side
  # effects — no worktree dir, no ledger record, no branch.
  ES_FAIL_RC=0
  ES_FAIL_OUT=$( cd "$ES_REPO" && NODE_OPTIONS="--require /does/not/exist" GITHUB_TOKEN=leakme CCT_HOME="$TMP/es-home5" PATH="$DIAG_PATH" "$LAUNCHER" worktree run scrub-5 --branch feature/scrub-5 2>&1 ) || ES_FAIL_RC=$?
  assert "scrub-list failure refuses the handoff (fail closed)" "[ \"\$ES_FAIL_RC\" -ne 0 ]"
  assert "the refusal names the unscrubbed-handoff contract" \
    "echo \"\$ES_FAIL_OUT\" | grep -q 'refusing an unscrubbed handoff'"
  assert "scrub-list failure created NO worktree directory" \
    "test ! -e \"\$(dirname \"\$ES_REPO\")/.cct-worktrees/es-repo/scrub-5\""
  assert "scrub-list failure created NO ledger record" \
    "! grep -q 'scrub-5' \"\$ES_REPO/.cct/worktrees.json\" 2>/dev/null"
  assert "scrub-list failure created NO git branch" \
    "! git -C \"\$ES_REPO\" show-ref --verify --quiet refs/heads/feature/scrub-5"

  # Final-round review F6: the exec now goes through /usr/bin/env -u; pin the
  # argv contract — benign forwarded pi args must survive the handoff intact
  # alongside the scrub.
  rm -f "$TMP/capture.txt"
  ( cd "$ES_REPO" && GITHUB_TOKEN=leakme CCT_HOME="$TMP/es-home6" PATH="$DIAG_PATH" "$LAUNCHER" worktree run scrub-6 --branch feature/scrub-6 -- --thinking high -p "do it" ) >/dev/null 2>&1 || true
  assert "forwarded pi args survive the env -u handoff" \
    "test -f \"\$TMP/capture.txt\" && grep -q -- '--thinking high -p do it' \"\$TMP/capture.txt\""
  assert "the arg-forwarding handoff still scrubbed the credential" \
    "grep -q 'GITHUB_TOKEN:unset' \"\$TMP/capture.txt\""
fi

# Fail-closed wiring (source assertion, #172 precedent): a scrub-list failure
# refuses the handoff — never a silent unscrubbed launch.
assert "worktree run fails closed on a scrub-list failure (source wiring)" \
  "grep -q 'refusing an unscrubbed handoff' '$LAUNCHER'"

# ── #185: read-only `pi-code team` CLI (Slice A of #174) ─────────────────────
if command -v git >/dev/null 2>&1; then
  TEAM_REPO="$TMP/team-repo"; mkdir -p "$TEAM_REPO/.cct"
  git -C "$TEAM_REPO" init -q -b master
  git -C "$TEAM_REPO" config user.email t@e.com
  git -C "$TEAM_REPO" config user.name T
  echo seed > "$TEAM_REPO/README.md"; git -C "$TEAM_REPO" add -A; git -C "$TEAM_REPO" commit -q -m seed
  # A valid team ledger (hand-crafted; loadTeamLedger sanitizes/reconciles).
  cat > "$TEAM_REPO/.cct/team.json" <<JSON
{"version":1,"teamId":"alpha","createdAt":"2026-08-06T00:00:00Z","status":"forming","members":[{"memberId":"lead1","role":"lead","status":"active","joinedAt":"2026-08-06T00:00:00Z"}],"tasks":[],"planApproval":{"required":true,"approved":false,"approvedBy":null,"approvedAt":null},"shutdown":{"requested":false,"requestedBy":null,"reason":"","at":null}}
JSON
  # Read-only status renders even WITHOUT agents.teams_enabled (project untrusted).
  TEAM_OUT=$(cd "$TEAM_REPO" && CCT_HOME="$TMP/team-home" PATH="$DIAG_PATH" "$LAUNCHER" team status --json 2>&1) || true
  assert "pi-code team status --json renders a valid ledger read-only" \
    "echo \"\$TEAM_OUT\" | grep -q '\"teamId\": \"alpha\"'"
  assert "pi-code team status --json reports enabled + trust note" \
    "echo \"\$TEAM_OUT\" | grep -q '\"enabled\"' && echo \"\$TEAM_OUT\" | grep -q 'trustNote'"
  # Missing ledger in a git repo -> "no team" (distinct from a non-repo).
  NOTEAM_REPO="$TMP/noteam-repo"; mkdir -p "$NOTEAM_REPO"
  git -C "$NOTEAM_REPO" init -q -b master
  git -C "$NOTEAM_REPO" config user.email t@e.com
  git -C "$NOTEAM_REPO" config user.name T
  echo seed > "$NOTEAM_REPO/README.md"; git -C "$NOTEAM_REPO" add -A; git -C "$NOTEAM_REPO" commit -q -m seed
  NOTEAM=$(cd "$NOTEAM_REPO" && CCT_HOME="$TMP/team-home" PATH="$DIAG_PATH" "$LAUNCHER" team status 2>&1) || true
  assert "pi-code team status reports 'no team' when absent" \
    "echo \"\$NOTEAM\" | grep -qi 'no team'"
  assert "help documents the team command" \
    "PATH=\"\$DIAG_PATH\" '$LAUNCHER' help | grep -q 'team status'"
else
  echo "  SKIP: pi-code team (git unavailable)"
fi

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

# ── #179: init --extension-template (guardrails starter) ────
EXT_DIR="$TMP/ext-proj"; mkdir -p "$EXT_DIR"
EXT_DRY=$(PATH="$BASE_PATH" "$LAUNCHER" init "$EXT_DIR" --extension-template --dry-run 2>&1 || true)
assert "init --extension-template --dry-run reports the template files" \
  "echo \"\$EXT_DRY\" | grep -q 'cct-guardrails.ts'"
assert "init --extension-template --dry-run writes nothing" \
  "[ ! -e \"\$EXT_DIR/.pi\" ]"
PATH="$BASE_PATH" "$LAUNCHER" init "$EXT_DIR" --extension-template >/dev/null 2>&1
assert "init --extension-template scaffolds the extension" \
  "test -f \"\$EXT_DIR/.pi/extensions/cct-guardrails.ts\""
assert "init --extension-template scaffolds the reference validator" \
  "test -f \"\$EXT_DIR/.pi/extensions/validators/check-python-ast.py\""
assert "init --extension-template scaffolds the template README" \
  "test -f \"\$EXT_DIR/.pi/extensions/README.md\""
assert "init --extension-template scaffolds the template tsconfig" \
  "test -f \"\$EXT_DIR/.pi/extensions/tsconfig.json\""
assert "manifest records the template files with hashes" \
  "grep -q 'extension-template' \"\$EXT_DIR/.code-copilot-team/.cct-init.json\" && grep -q '.pi/extensions/cct-guardrails.ts' \"\$EXT_DIR/.code-copilot-team/.cct-init.json\""
assert "manifest is valid JSON with no empty hashes (P1/P5)" \
  "python3 -c \"import json,sys;m=json.load(open('\$EXT_DIR/.code-copilot-team/.cct-init.json'));sys.exit(0 if all(e.get('hash') for e in m['generated']) else 1)\""
# Pre-existing-init path: files scaffolded, NO manifest-fragment leak, manifest untouched.
EXT_DIR2="$TMP/ext-preinit"; mkdir -p "$EXT_DIR2"
PATH="$BASE_PATH" "$LAUNCHER" init "$EXT_DIR2" >/dev/null 2>&1
MANI_BEFORE=$(cat "$EXT_DIR2/.code-copilot-team/.cct-init.json")
PRE_OUT=$(PATH="$BASE_PATH" "$LAUNCHER" init "$EXT_DIR2" --extension-template 2>/dev/null)
assert "pre-existing init scaffolds without leaking manifest fragments" \
  "test -f \"\$EXT_DIR2/.pi/extensions/cct-guardrails.ts\" && ! echo \"\$PRE_OUT\" | grep -q 'extension-template\", \"hash'"
assert "pre-existing init leaves the manifest untouched" \
  "[ \"\$MANI_BEFORE\" = \"\$(cat \"\$EXT_DIR2/.code-copilot-team/.cct-init.json\")\" ]"
# A partial/stale template source must FAIL the scaffold, not half-succeed (P1).
PART_HOME="$TMP/ext-partial-home"; mkdir -p "$PART_HOME/pi/resources/extension-template"
printf '// stale partial\n' > "$PART_HOME/pi/resources/extension-template/cct-guardrails.ts"
EXT_DIR3="$TMP/ext-partial"; mkdir -p "$EXT_DIR3"
PART_RC=0
CCT_HOME="$PART_HOME" PATH="$BASE_PATH" "$LAUNCHER" init "$EXT_DIR3" --extension-template >/dev/null 2>&1 || PART_RC=$?
assert "a stale partial managed template falls back to the complete repo copy" \
  "[ \"\$PART_RC\" -eq 0 ] && grep -q 'issue #179' \"\$EXT_DIR3/.pi/extensions/cct-guardrails.ts\""
# No-clobber: an edited template survives a re-init with the flag.
printf '// my edits\n' >> "$EXT_DIR/.pi/extensions/cct-guardrails.ts"
PATH="$BASE_PATH" "$LAUNCHER" init "$EXT_DIR" --extension-template >/dev/null 2>&1
assert "re-init preserves an edited template (no clobber)" \
  "grep -q 'my edits' \"\$EXT_DIR/.pi/extensions/cct-guardrails.ts\""
# Plain init unchanged: no template without the flag.
PLAIN_DIR="$TMP/ext-plain"; mkdir -p "$PLAIN_DIR"
PATH="$BASE_PATH" "$LAUNCHER" init "$PLAIN_DIR" >/dev/null 2>&1
assert "plain init scaffolds no extension template" "[ ! -e \"\$PLAIN_DIR/.pi\" ]"
assert "help documents --extension-template" \
  "PATH=\"\$DIAG_PATH\" '$LAUNCHER' help | grep -q 'extension-template'"

# ── #179: the headless doc's exact command shape reaches pi ──
rm -f "$TMP/capture.txt"
PATH="$TMP/bin-new:$BASE_PATH" "$LAUNCHER" -- --mode json -p "headless probe" --no-session >/dev/null 2>&1 || true
assert "headless recipe: forwarded --mode json -p reaches pi (doc shape)" \
  "test -f \"\$TMP/capture.txt\" && grep -q -- '--mode json -p headless probe --no-session' \"\$TMP/capture.txt\""
assert "headless recipe runs ENFORCED (runtime extension loaded)" \
  "grep -q -- '--extension' \"\$TMP/capture.txt\" && grep -q 'CCT_RUNTIME:1' \"\$TMP/capture.txt\""

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
