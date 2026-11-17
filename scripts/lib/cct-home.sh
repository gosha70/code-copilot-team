#!/usr/bin/env bash
# cct-home.sh — the one place that knows where CCT keeps a user's files (#411).
#
# The home is ${CCT_HOME:-~/.cct}. Through the 2.1.x line a top-level entry
# that is absent from the home but present in the legacy home
# ~/.code-copilot-team is served from there, reads and writes alike, so a
# directory is never split between the two; the first 2.2 change removes
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
CCT_HOME_LEGACY_REL=".code-copilot-team"   # served as a fallback through 2.1.x; removed in 2.2

cct_home() {  # -> the home directory (it may not exist yet)
  printf '%s\n' "${CCT_HOME:-$HOME/$CCT_HOME_DEFAULT_REL}"
}

_cct_home_present() {  # <path>: true if the entry exists, a dangling symlink included
  [[ -e "$1" || -L "$1" ]]
}

cct_home_path() {  # <relative> -> the path to read, write, or create
  # The TOP-LEVEL ENTRY decides the home, never the full path: pi/audit.log
  # goes wherever pi/ lives, so a first write can never create ~/.cct/pi and
  # shadow a legacy pi/ that holds everything else. Presence does not follow
  # a final symlink: a dangling ~/.cct/<entry> still selects the home (and
  # fails loudly there) instead of silently reviving a stale legacy copy.
  local rel="$1" entry="${1%%/*}"
  if [[ -z "${CCT_HOME:-}" ]] && ! _cct_home_present "$(cct_home)/$entry" && _cct_home_present "$HOME/$CCT_HOME_LEGACY_REL/$entry"; then
    printf '%s\n' "$HOME/$CCT_HOME_LEGACY_REL/$rel"; return 0
  fi
  printf '%s\n' "$(cct_home)/$rel"
}

cct_home_legacy_hits() {  # -> entries still served from the legacy home, one per line
  [[ -z "${CCT_HOME:-}" && -d "$HOME/$CCT_HOME_LEGACY_REL" ]] || return 0
  local entry name
  for entry in "$HOME/$CCT_HOME_LEGACY_REL"/* "$HOME/$CCT_HOME_LEGACY_REL"/.[!.]* "$HOME/$CCT_HOME_LEGACY_REL"/..?*; do
    _cct_home_present "$entry" || continue
    name="${entry##*/}"
    case "$name" in .cct-migrate-aside.*) continue ;; esac   # set aside by an interrupted migrate; cct home reports it
    _cct_home_present "$HOME/$CCT_HOME_DEFAULT_REL/$name" || printf '%s\n' "$name"
  done
  return 0
}
# <<< cct-home resolver
