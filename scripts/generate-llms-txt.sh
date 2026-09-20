#!/usr/bin/env bash
# generate-llms-txt.sh — write llms.txt from the Learn registry (#214 Phase 6.1).
#
# EXPERIMENTAL. llms.txt is a proposal (https://llmstxt.org/), not a standard:
# a Markdown file that tells a language model what documentation a project has
# and where the Markdown lives. It is the documentation index in another
# format, so it is generated from the same registry by the same code
# (scripts/lib/docs_index.py) as the README and landing-page index, and cannot
# list a page they do not. Never hand-edit llms.txt.
#
# Usage: generate-llms-txt.sh [--stdout|--check|--write]   (default: --write)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEARN="$REPO_DIR/scripts/session_analytics/config_data/learn-sections.json"
TARGET="$REPO_DIR/llms.txt"

die() { echo "[ERROR] $*" >&2; exit 1; }

render() {
  [[ -f "$LEARN" ]] || die "$LEARN not found"
  python3 "$REPO_DIR/scripts/lib/docs_index.py" "$LEARN" "$REPO_DIR" llms
}

main() {
  local mode="${1:-write}" tmp
  case "$mode" in --stdout|--check|--write|write) ;;
    *) echo "usage: generate-llms-txt.sh [--stdout|--check|--write]" >&2; exit 2 ;;
  esac
  tmp="$(mktemp)"
  render > "$tmp" || { rm -f "$tmp"; exit 1; }
  case "$mode" in
    --stdout) cat "$tmp"; rm -f "$tmp" ;;
    --check)
      if ! diff -u "$TARGET" "$tmp" >/dev/null 2>&1; then
        echo "[STALE] llms.txt is out of date. Run: scripts/generate-llms-txt.sh" >&2
        diff -u "$TARGET" "$tmp" >&2 || true
        rm -f "$tmp"
        exit 1
      fi
      rm -f "$tmp"
      echo "[OK] llms.txt is up to date." >&2 ;;
    --write|write)
      mv "$tmp" "$TARGET"; echo "[OK] wrote llms.txt" >&2 ;;
  esac
}

main "${1:-write}"
