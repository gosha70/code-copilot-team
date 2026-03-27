#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
if [[ ! -d "$PROJECT_DIR" ]]; then
  exit 0
fi

cd "$PROJECT_DIR" 2>/dev/null || exit 0

if ! command -v memkernel >/dev/null 2>&1; then
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  exit 0
fi

if ! python3 -c 'import memkernel' >/dev/null 2>&1; then
  exit 0
fi

resolve_project_id() {
  local settings_file="$PROJECT_DIR/.claude/settings.local.json"
  local configured="" project_root="" project_slug="" project_hash=""

  if [[ -f "$settings_file" ]]; then
    configured=$(python3 - "$settings_file" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
    value = data.get("mcpServers", {}).get("memkernel", {}).get("env", {}).get("MEMKERNEL_PROJECT_ID", "")
    if isinstance(value, str):
        print(value)
except Exception:
    pass
PY
)
  fi

  if [[ -n "$configured" ]]; then
    printf '%s\n' "$configured"
    return
  fi

  project_root=$(git -C "$PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null || (cd "$PROJECT_DIR" && pwd -P 2>/dev/null || echo "$PROJECT_DIR"))
  project_slug=$(basename "$project_root" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-*//; s/-*$//')
  [[ -n "$project_slug" ]] || project_slug="project"

  if command -v md5 >/dev/null 2>&1; then
    project_hash=$(printf '%s' "$project_root" | md5 -q)
  elif command -v md5sum >/dev/null 2>&1; then
    project_hash=$(printf '%s' "$project_root" | md5sum | cut -d' ' -f1)
  else
    project_hash=$(printf '%s' "$project_root" | cksum | awk '{print $1}')
  fi

  printf '%s-%s\n' "$project_slug" "${project_hash:0:12}"
}

if [[ -z "${MEMKERNEL_PROJECT_ID:-}" ]]; then
  export MEMKERNEL_PROJECT_ID
  MEMKERNEL_PROJECT_ID=$(resolve_project_id)
fi

exec python3 "$(dirname "$0")/memkernel-post-compact.py"
