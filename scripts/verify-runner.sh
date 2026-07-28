#!/usr/bin/env bash
set -uo pipefail

# verify-runner.sh — provider-neutral verification-gate runner (T6.2, FR-016).
#
# Runs the gates named in CCT_VERIFY_GATES (comma-separated) over the project at
# $1 and writes .cct/verify/result.json:
#   { "<gate>": { "status": "supported|degraded|unsupported", "pass": bool,
#                 "detail": "..." }, ... }
#
# Honesty model (mirror T5.1): a gate only reports pass:true when it ACTUALLY
# ran. Gates with no substrate in this repo (generic lint, type-check,
# dependency audit) report status "unsupported", pass:false — never faked. The
# runtime (workflow/verify.ts) decides blocking; a REQUIRED unsupported gate is a
# hard config error there, not here.
#
# Usage: verify-runner.sh <project-dir>
# Exit:  0 = all run gates passed, 1 = a run gate failed, 2 = usage/error.

if [[ $# -lt 1 ]]; then
  echo "usage: verify-runner.sh <project-dir>" >&2
  exit 2
fi
PROJECT_DIR="$1"
[[ -d "$PROJECT_DIR" ]] || { echo "not a directory: $PROJECT_DIR" >&2; exit 2; }
GATES="${CCT_VERIFY_GATES:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$PROJECT_DIR/.cct/verify"
mkdir -p "$OUT_DIR"

# --- result accumulation (bash 3.2: no associative arrays) ------------------
RESULT_ENTRIES=""   # JSON object members, comma-separated
OVERALL_RC=0

json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' '; }

record() { # <gate> <status> <pass:true|false> <detail>
  local gate="$1" status="$2" pass="$3" detail; detail="$(json_escape "$4")"
  local entry="\"$gate\": {\"status\": \"$status\", \"pass\": $pass, \"detail\": \"$detail\"}"
  RESULT_ENTRIES="${RESULT_ENTRIES:+$RESULT_ENTRIES,
  }$entry"
  [[ "$pass" == "true" || "$status" == "unsupported" ]] || OVERALL_RC=1
}

run_quiet() { ( cd "$PROJECT_DIR" && "$@" ) >/dev/null 2>&1; }

# --- per-gate handlers ------------------------------------------------------
gate_drift() {
  if [[ ! -x "$SCRIPT_DIR/generate.sh" ]]; then
    record drift unsupported false "no scripts/generate.sh in this project"; return
  fi
  ( cd "$PROJECT_DIR" && bash "$SCRIPT_DIR/generate.sh" ) >/dev/null 2>&1
  local drift; drift="$( cd "$PROJECT_DIR" && git add -A adapters/ 2>/dev/null; git diff --cached --name-only -- adapters/ 2>/dev/null; git reset -q adapters/ 2>/dev/null )"
  if [[ -z "$drift" ]]; then record drift supported true "generated resources in sync"
  else record drift supported false "generated drift in: $(echo "$drift" | tr '\n' ' ')"; fi
}

gate_docs() {
  if [[ ! -x "$SCRIPT_DIR/validate-spec.sh" ]]; then
    record docs unsupported false "no scripts/validate-spec.sh"; return
  fi
  if run_quiet bash "$SCRIPT_DIR/validate-spec.sh" --all; then
    record docs supported true "spec/plan/tasks artifacts valid"
  else record docs supported false "validate-spec.sh --all failed"; fi
}

gate_tests() { # <gate-name> — the substrate has no unit/integration split
  local name="${1:-tests}"
  local vh="$SCRIPT_DIR/../adapters/claude-code/.claude/hooks/verify-on-stop.sh"
  if [[ -x "$vh" ]]; then
    if ( cd "$PROJECT_DIR" && HOOK_STOP_BLOCK=false bash "$vh" ) >/dev/null 2>&1; then
      record "$name" supported true "project test detector passed (report mode)"
    else record "$name" supported false "project tests failed"; fi
  else record "$name" unsupported false "no test detector available"; fi
}

gate_build() {
  if [[ -f "$PROJECT_DIR/Dockerfile" ]]; then
    if run_quiet docker build -q -f "$PROJECT_DIR/Dockerfile" "$PROJECT_DIR"; then
      record build degraded true "docker build only (no generic language build)"
    else record build degraded false "docker build failed"; fi
  else
    record build degraded false "no generic build substrate (docker-only); nothing to build"
  fi
}

# No substrate in this repo — reported honestly, never faked.
gate_unsupported() { record "$1" unsupported false "$2"; }

for gate in ${GATES//,/ }; do
  case "$gate" in
    drift)          gate_drift ;;
    docs)           gate_docs ;;
    tests|unit)     gate_tests tests ;;
    integration)    gate_tests integration ;;
    build)          gate_build ;;
    lint)           gate_unsupported lint "no generic code linter wired in this project" ;;
    type-check)     gate_unsupported type-check "no tsc --noEmit/mypy runner (strip-types does not check)" ;;
    dependency-audit) gate_unsupported dependency-audit "no npm audit/pip-audit/dependency-review configured" ;;
    security)       record security degraded false "repo-config hardening only; no code SAST" ;;
    visual)         gate_unsupported visual "ui-harness requires a web project with a running dev server" ;;
    "")             ;;
    *)              gate_unsupported "$gate" "unknown gate" ;;
  esac
done

printf '{\n  %s\n}\n' "$RESULT_ENTRIES" > "$OUT_DIR/result.json"
exit "$OVERALL_RC"
