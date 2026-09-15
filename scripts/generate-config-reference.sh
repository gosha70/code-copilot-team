#!/usr/bin/env bash
# generate-config-reference.sh — render docs/configuration-reference.md from
# the schemas and defaults that already describe each setting (#214 Phase 2.3).
#
# Motivation: configuration was spread over four surfaces with no map — an
# automation.json schema, a providers.toml with no schema at all, a
# session-analytics defaults file plus ~40 environment variables, and prose
# in the README. Each surface already carries its own descriptions; this
# renders them in one page instead of restating them in a fifth place.
#
# Sources (only these):
#   shared/schemas/automation.schema.json        per-feature auto-build config
#   shared/schemas/providers.schema.json         ~/.code-copilot-team/providers.toml
#   scripts/session_analytics/config_data/defaults.json   analytics defaults
#   scripts/session_analytics/config.py + constants.py    env var ↔ key pairs
#
# Usage:
#   generate-config-reference.sh            # write docs/configuration-reference.md
#   generate-config-reference.sh --stdout
#   generate-config-reference.sh --check    # exit non-zero if the doc is stale
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_DIR/docs/configuration-reference.md"

render() { python3 "$REPO_DIR/scripts/lib/config_reference.py" "$REPO_DIR"; }

main() {
  case "${1:-write}" in
    --stdout) render ;;
    --check)
      local tmp; tmp="$(mktemp)"
      render >"$tmp" || { rm -f "$tmp"; exit 1; }
      if ! diff -u "$OUT" "$tmp" >/dev/null 2>&1; then
        echo "[STALE] docs/configuration-reference.md is out of date. Run: scripts/generate-config-reference.sh" >&2
        diff -u "$OUT" "$tmp" >&2 || true
        rm -f "$tmp"; exit 1
      fi
      rm -f "$tmp"; echo "[OK] docs/configuration-reference.md is up to date." >&2 ;;
    --write|write)
      local tmp; tmp="$(mktemp)"
      render >"$tmp" || { rm -f "$tmp"; exit 1; }
      mv "$tmp" "$OUT"; echo "[OK] wrote $OUT" >&2 ;;
    *) echo "usage: generate-config-reference.sh [--stdout|--check|--write]" >&2; exit 2 ;;
  esac
}

main "${1:-write}"
