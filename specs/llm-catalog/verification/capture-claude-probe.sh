#!/usr/bin/env bash
# capture-claude-probe.sh — S3 capture of #400's probe against the installed
# Claude Code (FR-15): `cct llm test` runs the real `claude`, as a launch
# would, behind the stub gateway (tests/fixtures/llm-stub-gateway.py), once
# with no switch and once under each negative-control switch, and the record
# quotes each run's matrix, outcome and the state that follows.
#
# No real provider and no real credential: the gateway is local and the
# only credential is a planted sentinel. Each run has its own throwaway home
# and gateway. The record names the CLI version, so a newer Claude Code is
# captured again by running this script again.
#
# Usage: capture-claude-probe.sh [record.md]   (default: claude-code-probe-capture.md beside it)
# Needs: claude, python3, jq. The real binary is used: a shell-script wrapper
# on PATH (cmux ships one) is skipped; CLAUDE_BIN names the binary outright.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
RECORD="${1:-$HERE/claude-code-probe-capture.md}"
GATEWAY="$REPO/tests/fixtures/llm-stub-gateway.py"
CCT="$REPO/scripts/cct"
LIMIT="${CAPTURE_TIMEOUT_SEC:-90}"
HANG_LIMIT=15   # the time-out switch: the watchdog ends the run
SWITCHES="drop-tool-calls ignore-tool-results no-stream other-model resolve-model ignore-system-prompt reject-shape reject-model reject-billing reject-auth exceed-limits time-out drop-reasoning ignore-images server-error not-found extra-command"

real_claude() {  # the first claude on PATH that is not a script
  local dir f
  if [[ -n "${CLAUDE_BIN:-}" ]]; then printf '%s\n' "$CLAUDE_BIN"; return; fi
  local IFS=:
  for dir in $PATH; do
    f="$dir/claude"
    [[ -x "$f" && ! -d "$f" ]] || continue
    head -c 2 "$f" 2>/dev/null | grep -q '#!' && continue
    printf '%s\n' "$f"; return
  done
  return 1
}
CLAUDE="$(real_claude)" || { echo "no claude binary on PATH (a wrapper script does not count); set CLAUDE_BIN" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 2; }
command -v jq >/dev/null || { echo "jq not found" >&2; exit 2; }

W="$(mktemp -d "${TMPDIR:-/tmp}/cct-capture-probe.XXXXXX")"
case "$W" in */cct-capture-probe.*) ;; *) echo "unexpected work dir: $W" >&2; exit 2 ;; esac
GW_PID=""
cleanup() {
  [[ -n "$GW_PID" ]] && { kill "$GW_PID" 2>/dev/null; wait "$GW_PID" 2>/dev/null; }
  rm -rf "$W"
}
trap cleanup EXIT INT TERM
mkdir -p "$W/bin"
ln -s "$CLAUDE" "$W/bin/claude"
VERSION="$("$W/bin/claude" --version 2>/dev/null | head -1)"
BASE_PATH="$W/bin:$(dirname "$(command -v jq)"):/usr/bin:/bin:/usr/sbin:/sbin"

run_case() {  # <name> [<switch>] [<model>]: one run; prints the case's record line
  local name="$1" sw="${2:-}" model="${3:-probe-model}" h="$W/$1" args=() limit="$LIMIT"
  mkdir -p "$h/home/.cct" "$h/tmp"
  [[ -n "$sw" ]] && args=(--switch "$sw")
  [[ "$sw" == time-out ]] && limit="$HANG_LIMIT"
  python3 "$GATEWAY" "$h/gateway.jsonl" "$h/port" ${args[@]+"${args[@]}"} --extra-file "$h/extra-ran.txt" &
  GW_PID=$!
  for _ in $(seq 1 50); do [[ -s "$h/port" ]] && break; sleep 0.1; done
  cat > "$h/home/.cct/llms.toml" <<EOF
schema_version = 1

[providers.p]
display_name = "Provider P"
kind = "api"
credential_mode = "env"
credential_env = "TEST_LLM_KEY"

[endpoints.gw]
provider = "p"
protocol = "anthropic-messages"
base_url = "http://127.0.0.1:$(cat "$h/port")"
auth_header = "bearer"

[llms.pm]
provider = "p"
model = "$model"
reasoning = true
input = ["text", "image"]

[bindings.pt]
harness = "claude-code"
llm = "pm"
endpoint = "gw"
max_output_tokens = 1000
EOF
  (cd "$h" && env -i HOME="$h/home" PATH="$BASE_PATH" TERM=dumb LANG=en_US.UTF-8 TMPDIR="$h/tmp" \
      TEST_LLM_KEY=probe-planted-credential DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
      CCT_LLM_PROBE_TIMEOUT_SEC="$limit" bash "$CCT" llm test pm --json > "$h/out.json" 2> "$h/err.txt")
  echo "$?" > "$h/rc"
  kill "$GW_PID" 2>/dev/null; wait "$GW_PID" 2>/dev/null; GW_PID=""
  local extra=""
  if [[ "$sw" == extra-command ]]; then
    if [[ -e "$h/extra-ran.txt" ]]; then extra="; the endpoint's appended command RAN"; else extra="; the endpoint's appended command did not run"; fi
  fi
  jq -r --arg n "$name" --arg sw "${sw:-none}" --arg rc "$(cat "$h/rc")" --arg extra "$extra" '
    "| \($n) | \($sw) | \($rc) | \(.outcome // "-") | \(.state // "-") | \([.matrix // {} | to_entries[] | select(.value != "pass") | "\(.key): \(.value)"] | join(", ") | if . == "" then "every capability passed" else . end)\($extra) |"' "$h/out.json" 2>/dev/null \
    || echo "| $name | ${sw:-none} | $(cat "$h/rc") | - | - | no JSON: $(head -c 200 "$h/err.txt" | tr '\n' ' ') |"
}

gateway_line() {  # <name>: what the gateway received, request by request
  python3 - "$W/$1/gateway.jsonl" <<'PY'
import json, sys
rows = []
try:
    for line in open(sys.argv[1]):
        e = json.loads(line)
        rows.append(f"{e['reply']} (model {e['model']}, stream {str(e['stream']).lower()}, thinking {e['thinking']}, max_tokens {e['max_tokens']}, Bash offered {str('Bash' in e['tools']).lower()}, auth {json.dumps(e['auth'])})")
except FileNotFoundError:
    pass
print("; ".join(rows) if rows else "nothing")
PY
}

CASES="base model-1m $SWITCHES"
LINES=""
for c in $CASES; do
  case "$c" in
    base)     LINES="$LINES$(run_case base)"$'\n' ;;
    model-1m) LINES="$LINES$(run_case model-1m "" "probe-model[1m]")"$'\n' ;;
    *)        LINES="$LINES$(run_case "$c" "$c")"$'\n' ;;
  esac
done

{
  echo "# Probe capture: \`cct llm test\` against \`claude\` $VERSION"
  echo ""
  echo "Recorded $(date -u +%Y-%m-%d) by \`specs/llm-catalog/verification/capture-claude-probe.sh\` (#400 S3, FR-15)."
  echo "Each run is \`cct llm test pm --json\` with the real \`claude\` first on PATH, in a throwaway home, behind"
  echo "\`tests/fixtures/llm-stub-gateway.py\` with the switch named, and the planted credential \`probe-planted-credential\`."
  echo "The llm declares reasoning and image input, and the binding \`max_output_tokens = 1000\`, so every capability applies."
  echo "The time-out run's watchdog bound is ${HANG_LIMIT}s; the others' is ${LIMIT}s. The model-1m run asks for \`probe-model[1m]\`,"
  echo "and the gateway's log below shows the model Claude Code sent for it."
  echo ""
  echo "## The runs"
  echo ""
  echo "| Run | Switch | Exit | Outcome | State after | Capabilities that did not pass |"
  echo "|---|---|---|---|---|---|"
  printf '%s' "$LINES"
  echo ""
  echo "## What the gateway received"
  echo ""
  for c in $CASES; do echo "- **$c:** $(gateway_line "$c")"; done
} > "$RECORD"
echo "wrote $RECORD"
