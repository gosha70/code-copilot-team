#!/usr/bin/env bash
# cct-home.sh — the one place that knows where CCT keeps a user's files (#411).
#
# The home is ${CCT_HOME:-~/.cct}. Through the 2.1.x line a file that is
# absent from the home but present in the legacy home ~/.code-copilot-team
# is read from there (a read-only fallback); the first 2.2 change removes
# the fallback. Nothing here moves a file: `cct home migrate` is the only
# mover, and it never overwrites.
#
# Installed scripts that run without a checkout (the harness-stamp hook,
# the claude-code launcher, pi-code) carry a verbatim copy of the block between the markers below;
# tests/test-shared-structure.sh keeps every copy identical to this file.
#
# bash 3.2; no dependencies.

# >>> cct-home resolver (verbatim copies: adapters/claude-code/.claude/hooks/harness-stamp.sh, adapters/claude-code/claude-code, adapters/pi/bin/pi-code)
CCT_HOME_DEFAULT_REL=".cct"
CCT_HOME_LEGACY_REL=".code-copilot-team"   # read-only fallback through 2.1.x; removed in 2.2

cct_home() {  # -> the home directory (it may not exist yet)
  printf '%s\n' "${CCT_HOME:-$HOME/$CCT_HOME_DEFAULT_REL}"
}

cct_home_path() {  # <relative> -> the path to read, or to create under the home
  local rel="$1" new legacy
  new="$(cct_home)/$rel"
  if [[ -n "${CCT_HOME:-}" ]]; then printf '%s\n' "$new"; return 0; fi
  if [[ -e "$new" ]]; then printf '%s\n' "$new"; return 0; fi
  legacy="$HOME/$CCT_HOME_LEGACY_REL/$rel"
  if [[ -e "$legacy" ]]; then printf '%s\n' "$legacy"; return 0; fi
  printf '%s\n' "$new"
}

cct_home_legacy_hits() {  # -> entries still served from the legacy home, one per line
  [[ -z "${CCT_HOME:-}" && -d "$HOME/$CCT_HOME_LEGACY_REL" ]] || return 0
  local entry name
  for entry in "$HOME/$CCT_HOME_LEGACY_REL"/* "$HOME/$CCT_HOME_LEGACY_REL"/.[!.]*; do
    [[ -e "$entry" ]] || continue
    name="${entry##*/}"
    [[ -e "$HOME/$CCT_HOME_DEFAULT_REL/$name" ]] || printf '%s\n' "$name"
  done
  return 0
}
# <<< cct-home resolver
